#!/usr/bin/env python3
# @capability:  vault-correlate
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/vault-correlate.py
# @prompt:      (none)
# @adapters:    CLI (stdin/stdout JSON)
# @portability: L1a-generic
# @forbidden:   never writes to the vault
# @audit:       none
# @doc:         docs/engine-vault-correlate.md
# @status:      active
"""Correlate external items against the notes in a vault.

Answers one question, deterministically and with its working shown: *does this vault already have a
note about this thing?* The "thing" is any external item reduced to a small envelope -- a mail, a
ticket, a meeting transcript, a PDF -- so the engine never needs to know what produced it.

Input (stdin or --item-file), one object or a list:

    {"id": "...", "title": "...", "body": "...",
     "participants": ["ada@example.org", "Ada Lovelace"],
     "codes": ["PROJ-1"], "date": "2026-08-05"}

Output (stdout JSON):

    {"items": [{"id": ..., "state": ..., "score": ..., "candidates":
                [{"note": "<relpath>", "score": 62, "evidence": ["code PROJ-1", ...]}]}]}

States: anchored (>=70, one note) | correlated (40-69) | weak (reached 40+, but every single signal
was individually below MIN_ANCHOR_SIGNAL) | topic-known (a code matched, no note reached 40) |
ambiguous (top two candidates within 15 points of each other) | new (<40).

Design notes worth keeping in mind when editing:

* Scoring is additive with a floor rule: no single signal below MIN_ANCHOR_SIGNAL may produce an
  `anchored` verdict on its own, and a candidate built ENTIRELY out of such signals reports `weak`
  rather than `correlated`. Filename-substring matching without this rule is how a correlator starts
  confidently attaching mail to the wrong note. A false `correlated` is worse than a `new`: `new`
  sends the reader to go and look, while `correlated` hands them three wrong candidates and an
  invitation to stop looking.
* Every channel is capped per candidate note, not just per hit. An unbounded channel means "enough of
  the same weak evidence" eventually equals "one strong piece of evidence", which is exactly what the
  floor rule exists to prevent.
* Title/alias token overlap is weighted by inverse document frequency. A token appearing in 200 note
  titles carries almost no information; a rare one is nearly decisive. Raw token counting treats them
  the same, which is the classic failure of this kind of matcher.
* The vault is read through a small frontmatter MAP so the engine works on any markdown vault. It has
  no knowledge of specific folder names, keys or codes: those come from --config or the defaults.
* Index is cached. The key is (mtime, size) on an ordinary disk, and a CONTENT HASH where the
  substrate probe says metadata cannot be trusted: on a synced mount those two values are the
  sync client's answers, so an edited note can keep its old signature and the cache serves a
  stale card with no error anywhere.
"""
import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _vault_lib import (VAULT, force_utf8_stdout, md_files,  # noqa: E402
                        parse_frontmatter, split_frontmatter)

# --- scoring constants (single place to tune) -------------------------------
W_CODE = 40          # a shared code, DECLARED in one of the note's code-ish frontmatter keys
W_CODE_SOFT = 28     # the same code carried only by the note's title, alias or filename
W_PHRASE = 35        # the item's title contains a note's title or alias verbatim
W_PHRASE_MAX = 40    # ...and that is ALL the phrase channel may contribute to one note
W_TOKENS_MAX = 25    # IDF-weighted token overlap, capped
W_PERSON = 20        # a participant resolves to a person named by the note
W_PERSON_MAX = 25    # ...and that is ALL the person channel may contribute to one note
W_TAG = 10           # a shared tag
MIN_ANCHOR_SIGNAL = 30   # no signal weaker than this may anchor by itself


# Pattern-matched identifiers: records minted by OTHER systems (orders, tickets, changes) whose
# numbers appear in a document's prose rather than its metadata. Nobody will ever hand-curate them --
# there are thousands and they are born daily -- so they are recognised by SHAPE, from a small list of
# regexes, and indexed wherever they occur INCLUDING the body.
#
# They score above MIN_ANCHOR_SIGNAL, i.e. one is enough to anchor, which no other body-derived signal
# is allowed to do. That is earned rather than assumed: measured across 1516 real items these keys
# average ~1.0 documents per distinct value, so a shared one is very nearly proof. Contrast a shared
# title token, which is worth a fraction of that.
W_CODE_PATTERN = 35
# ...and that is ALL the record channel may contribute to one note. An index or tracker note listing
# twenty order numbers would otherwise out-score the dossier note that is genuinely about one of
# them, purely by listing more. Two shared record numbers are better evidence than one, but not
# twice as good, and no channel here is allowed to reach ANCHORED on its own.
W_CODE_PATTERN_MAX = 45
EVIDENCE_MAX = 5         # evidence lines returned per candidate, markers included
ANCHORED, CORRELATED, AMBIGUOUS_GAP = 70, 40, 15

# 5: both reasons at once. Cards store normalised code keys (from the scoring rework), and the cache
# SIGNATURE depends on whether the substrate's metadata can be trusted (a synced mount can leave an
# edited note with the same mtime and size). Neither change is comparable with an older entry.
CACHE_VERSION = 5

# NOT the effective map. These are last-resort defaults for a collection that declares nothing, and
# they are routinely overridden. Effective resolution, weakest first (see main()):
#     these defaults  ->  the collection's frontmatter schema (`correlate:` block)  ->  --config
#                         frontmatter_map  ->  CLI flags
# A schema that declares `correlate: {codes: [...]}` REPLACES the list below wholesale, so reading
# this constant alone tells you nothing about which keys a given collection actually indexes. Print
# the resolved map with --stats rather than inferring it from here.
#
# This comment exists because a reader took this list as authoritative, concluded a key was missing
# when the schema had already declared it, and "fixed" it with a --config that then clobbered the
# schema and dropped two keys. The resolution order was documented, but in main(), which is not
# where anyone looking up "which keys are codes?" ends up.
DEFAULT_FM_MAP = {
    "title": ["title"],
    "aliases": ["aliases", "alias"],
    "tags": ["tags"],
    "codes": ["code", "codes", "contract", "project", "programme", "program", "ref"],
    "people": ["people", "attendees", "stakeholders", "owner", "recipient", "participants"],
    "updated": ["updated", "modified", "created", "date"],
}

# Tokens too common in any vault to carry signal on their own.
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over", "een", "der", "des", "van",
    "voor", "met", "het", "de", "en", "les", "des", "pour", "avec", "dans", "sur", "note", "notes",
    "index", "readme", "overview", "meeting", "update", "draft", "final", "new", "old",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'&.]{2,}")
# Name parts must be split identically on both sides of the comparison, or "Ada Lovelace" in a note
# never meets "ada.lovelace@example.org" in an item. Dots and @ are separators here, unlike in tokens().
NAME_SPLIT = re.compile(r"[\s,;<>()@._\-]+")
# Domain-ish and honorific fragments that would otherwise match every person in the vault.
NAME_NOISE = {"com", "org", "net", "www", "mail", "example", "info", "noreply", "no-reply",
              "mr", "mrs", "ms", "dr", "prof", "the", "van", "der", "den", "de", "le", "la"}


# A code is written many ways -- "PROJ-1", "PROJ_1", "proj 1", "Proj/1" -- so both sides of every code
# comparison are normalised to hyphen-joined uppercase parts before they meet.
CODE_PART_RE = re.compile(r"[A-Za-z0-9]+")
CODE_NGRAM_MAX = 4       # longest run of title/filename parts considered as one candidate code
CODE_SOFT_MIN_LEN = 3    # a shorter run is noise, not a code


def code_key(value):
    """Normalise a code so PROJ-1, PROJ_1 and 'proj 1' compare equal."""
    return "-".join(CODE_PART_RE.findall(str(value or "").upper()))


def code_ngrams(text):
    """Every contiguous run of up to CODE_NGRAM_MAX parts of `text`, as normalised code keys.

    A note often carries its programme or dossier name only in its title and filename and never
    declares it in a code field, so the declared-code channel cannot see it at all. Splitting the
    title/filename into runs lets an item's code meet it: `project-alpha-review.md` yields
    PROJECT-ALPHA among others. Runs that are only digits, only stopwords or too short are dropped,
    because those match half a vault and would make the channel worse than useless.
    """
    parts = CODE_PART_RE.findall(str(text or "").upper())
    out = set()
    for i in range(len(parts)):
        for n in range(1, CODE_NGRAM_MAX + 1):
            if i + n > len(parts):
                break
            run = parts[i:i + n]
            if all(p.isdigit() or len(p) < 2 or p.lower() in STOPWORDS for p in run):
                continue
            key = "-".join(run)
            if len(key) >= CODE_SOFT_MIN_LEN:
                out.add(key)
    return out


def name_parts(value):
    """Comparable name fragments from a display name or an email address."""
    return {p for p in NAME_SPLIT.split(str(value or "").lower())
            if len(p) > 3 and p not in NAME_NOISE and not p.isdigit()}
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
MDLINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+\.md)\)")


def tokens(text):
    """Lowercased content tokens, stopwords and pure numbers dropped."""
    out = set()
    for t in TOKEN_RE.findall(text or ""):
        t = t.strip(".'&").lower()
        if len(t) > 2 and t not in STOPWORDS and not t.isdigit():
            out.add(t)
    return out


def _listify(val):
    if val is None:
        return []
    if isinstance(val, str):
        return [v.strip() for v in re.split(r"[,;]", val) if v.strip()] if "," in val else [val.strip()]
    if isinstance(val, (list, tuple)):
        out = []
        for v in val:
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
            elif isinstance(v, (int, float)):
                out.append(str(v))
        return out
    if isinstance(val, (int, float)):
        return [str(val)]
    return []


def _strip_links(val):
    """Frontmatter values are often '[[Some Note]]'. Keep the target text."""
    return [re.sub(r"^\[\[|\]\]$", "", v).split("|")[0].strip() for v in val]


class NoteCard(dict):
    """A vault note reduced to what correlation needs. Plain dict so it serialises to the cache."""


def extract_patterns(text, patterns):
    """{matched value: pattern name} for every configured identifier shape found in the text.

    A pattern is a regex, optionally with `min_digits`. The digit floor exists because the shapes
    that matter here are mostly-numeric record numbers, while the same character class also matches
    hex fragments and word-like tokens. Expressing "at least N digits" inside the regex is possible
    and unreadable; a post-filter says what it means.
    """
    out = {}
    for name, spec in (patterns or {}).items():
        rx, floor = (spec if isinstance(spec, tuple) else (spec, 0))
        for m in rx.findall(text):
            s = m if isinstance(m, str) else m[0]
            if floor and sum(c.isdigit() for c in s) < floor:
                continue
            v = code_key(s)
            if v:
                out.setdefault(v, name)
    return out


def compile_patterns(raw):
    """{name: (compiled, min_digits)} from `identifier_patterns`. Bad regex is skipped, not fatal."""
    out = {}
    for name, spec in (raw or {}).items():
        pat = spec.get("match") if isinstance(spec, dict) else spec
        floor = int(spec.get("min_digits", 0)) if isinstance(spec, dict) else 0
        try:
            out[name] = (re.compile(pat), floor)
        # TypeError as well as re.error: a spec whose key is misspelled (`regex:` instead of
        # `match:`) leaves pat = None, and re.compile raises TypeError, which is not a re.error.
        # The docstring promises one bad pattern does not sink the rest, and it did.
        except (re.error, TypeError) as exc:  # noqa: PERF203 - one bad pattern must not sink the rest
            print(f"WARN: identifier_patterns.{name}: unusable ({exc}); skipped", file=sys.stderr)
    return out


def build_card(path, reldir, fm_map, vault, patterns=None):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return None
    fm = parse_frontmatter(text)
    if fm is None or fm.get("__parse_error__"):
        fm = {}
    rel = os.path.relpath(path, vault).replace(os.sep, "/")
    stem = os.path.splitext(os.path.basename(path))[0]

    def pick(field):
        for key in fm_map.get(field, []):
            if key in fm and fm[key] not in (None, "", []):
                return fm[key]
        return None

    title = pick("title")
    title = title.strip() if isinstance(title, str) and title.strip() else stem
    aliases = _strip_links(_listify(pick("aliases")))
    tags = [t.lower().lstrip("#") for t in _listify(pick("tags"))]
    # Open-vocab schema axes (e.g. `domain`) are free topical vocabulary, so they behave exactly like
    # tags for correlation purposes. Enumerated axes are classifiers and stay out.
    for axis in fm_map.get("_topical", []):
        tags += [str(v).lower().lstrip("#") for v in _strip_links(_listify(fm.get(axis)))]
    codes = [k for k in (code_key(c) for c in _strip_links(_listify(pick("codes")))) if k]
    people = [p.lower() for p in _strip_links(_listify(pick("people")))]

    _, rest = split_frontmatter(text)
    body = rest or text
    links = [m.strip() for m in WIKILINK_RE.findall(body)] + \
            [os.path.splitext(os.path.basename(m))[0] for m in MDLINK_RE.findall(body)]

    return NoteCard({
        "note": rel, "reldir": reldir.replace(os.sep, "/"), "stem": stem,
        "patcodes": sorted(extract_patterns(text, patterns).items()),
        "title": title, "aliases": aliases, "tags": tags, "codes": codes,
        "people": people, "links_out": sorted(set(links))[:200],
        "note_type": fm.get("note_type") or fm.get("type"),
    })


class VaultIndex:
    """Frontmatter-aware note index with the inverted maps correlation needs."""


    def __init__(self, cards, patterns=None):
        self.cards = {c["note"]: c for c in cards}
        self.patterns = patterns or {}
        self.code2notes = defaultdict(set)
        self.patcode2notes = defaultdict(set)
        self.patcode2name = {}
        self.softcode2notes = defaultdict(set)
        self.tag2notes = defaultdict(set)
        self.person2notes = defaultdict(set)
        self.token2notes = defaultdict(set)
        self.phrase2notes = defaultdict(set)
        for c in cards:
            nid = c["note"]
            for pc in c.get("patcodes") or ():
                value, name = pc if isinstance(pc, (list, tuple)) else (pc, None)
                self.patcode2notes[value].add(nid)
                self.patcode2name[value] = name
            for code in c["codes"]:
                self.code2notes[code].add(nid)
            # A code the note only WEARS (in its title, an alias or its filename) rather than declares.
            for field in [c["title"], c["stem"]] + c["aliases"]:
                for key in code_ngrams(field):
                    self.softcode2notes[key].add(nid)
            for tag in c["tags"]:
                self.tag2notes[tag].add(nid)
            for p in c["people"]:
                for part in name_parts(p):
                    self.person2notes[part].add(nid)
            for phrase in [c["title"]] + c["aliases"]:
                if phrase and len(phrase) >= 6:
                    self.phrase2notes[phrase.lower()].add(nid)
            for t in tokens(" ".join([c["title"], c["stem"]] + c["aliases"])):
                self.token2notes[t].add(nid)
        self.n = max(1, len(cards))
        # Inverse document frequency: a token in almost every note tells you nothing.
        self.idf = {t: math.log(self.n / len(ns)) for t, ns in self.token2notes.items()}
        # A token present in EVERY note has idf 0, which is correct (it discriminates nothing). But a
        # one-note vault makes that true of every token, so max_idf collapses to 0 and the normaliser
        # divides by zero. Fall back to 1.0: token overlap then contributes nothing and the phrase /
        # code / person signals carry the correlation, which is the right behaviour for a tiny vault.
        self.max_idf = max(self.idf.values(), default=0.0) or 1.0

    def __len__(self):
        return len(self.cards)

    def unrelated(self, a_id, b_id):
        """True iff two notes look like genuinely different subjects.

        Related means: they share a code or a tag, one links to the other, or they sit in the same
        top-level folder. Anything else is treated as a real fork in the correlation, which is what
        makes an `ambiguous` verdict worth escalating.
        """
        a, b = self.cards.get(a_id), self.cards.get(b_id)
        if not a or not b:
            return True
        if set(a["codes"]) & set(b["codes"]):
            return False
        if set(a["tags"]) & set(b["tags"]):
            return False
        for src, other_id in ((a, b_id), (b, a_id)):
            other_stem = os.path.splitext(os.path.basename(other_id))[0].lower()
            if any(link.lower() == other_stem for link in src["links_out"]):
                return False
        return a["reldir"].split("/")[0] != b["reldir"].split("/")[0]


def load_index(vault, include, fm_map, cache_path, refresh=False, patterns=None):
    """Build (or incrementally refresh) the index.

    Two things decide whether a cached card is still valid, and both are here because either one
    alone lets a stale card through.

    The PATTERN SET, because pattern-derived codes are baked into a card: a run with different (or
    absent) patterns produced cards whose record index is wrong for this run.

    The SUBSTRATE, because the signature is normally (mtime, size), which is cheap and correct on an
    ordinary disk and neither on a synced mount. There, both values are the sync client's answers
    rather than the author's, so an edited note can keep its old signature and the cache serves a
    stale card forever, with plausible output and no error anywhere. Where metadata cannot be
    trusted the signature is a content hash instead: a read per file, and the only thing that stays
    true.
    """
    from _substrate import content_signature, probe          # noqa: E402
    substrate = probe(vault)
    trust_metadata = substrate["metadata_reliable"]
    # Identity of the pattern set, so a changed or absent one invalidates cards that baked in the
    # old answer. Sorted for stability: dict order must not decide cache validity.
    pattern_key = sorted((n, rx.pattern, floor) for n, (rx, floor) in (patterns or {}).items())
    cache = {}
    if cache_path and os.path.exists(cache_path) and not refresh:
        try:
            blob = json.load(open(cache_path, encoding="utf-8"))
            # `patterns` is part of the key because patcodes are BAKED INTO the cached card: a run
            # with different (or no) patterns produced cards whose record index is wrong for this
            # run, and the note file has not changed, so mtime/size can never catch it.
            if (blob.get("version") == CACHE_VERSION and blob.get("fm_map") == fm_map
                    and blob.get("patterns") == pattern_key):
                cache = blob.get("cards", {})
        except Exception:
            cache = {}

    cards, fresh, reused = [], 0, 0
    for path, reldir in md_files(vault):
        rel = os.path.relpath(path, vault).replace(os.sep, "/")
        if include and not any(rel == i or rel.startswith(i.rstrip("/") + "/") for i in include):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig = ([int(st.st_mtime), st.st_size] if trust_metadata
               else [content_signature(path)])
        hit = cache.get(rel)
        if hit and hit.get("sig") == sig:
            cards.append(NoteCard(hit["card"]))
            reused += 1
            continue
        card = build_card(path, reldir, fm_map, vault, patterns)
        if card:
            cards.append(card)
            cache[rel] = {"sig": sig, "card": dict(card)}
            fresh += 1

    if cache_path:
        live = {c["note"] for c in cards}
        cache = {k: v for k, v in cache.items() if k in live}
        try:
            os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump({"version": CACHE_VERSION, "fm_map": fm_map,
                           "patterns": pattern_key, "cards": cache}, f)
        except OSError as exc:
            print(f"WARN: could not write cache {cache_path}: {exc}", file=sys.stderr)

    return VaultIndex(cards, patterns), {"notes": len(cards), "parsed": fresh, "cached": reused}


def correlate(item, idx, top=3, register=None):
    """Score every plausible note for one item. Returns the verdict dict."""
    scores = defaultdict(int)
    evidence = defaultdict(list)
    best_signal = defaultdict(int)

    def add(nid, points, why):
        scores[nid] += points
        evidence[nid].append(why)
        best_signal[nid] = max(best_signal[nid], points)

    title = item.get("title") or ""
    body = item.get("body") or ""
    hay = f"{title}\n{body}"
    hay_l = hay.lower()

    # 1. Codes: the strongest deterministic signal there is -- when the note DECLARES the code in a
    # code-ish frontmatter key. A note that carries the code only in its title, an alias or its
    # filename is real but weaker evidence, because a filename token can be incidental. That match
    # scores W_CODE_SOFT, deliberately placed below MIN_ANCHOR_SIGNAL (so it can never anchor on its
    # own) and above everything the person channel can contribute (so the right note stops losing to
    # a pile of shared participants). Evidence is labelled so a reader can tell the two apart.
    item_codes = {k for k in (code_key(c) for c in item.get("codes") or []) if k}
    for code in item_codes:
        declared = idx.code2notes.get(code, set())
        for nid in declared:
            add(nid, W_CODE, f"code {code} (declared)")
        for nid in idx.softcode2notes.get(code, ()):
            if nid not in declared:
                add(nid, W_CODE_SOFT, f"code {code} (title)")

    # 1a. Pattern-matched record numbers. Both sides are derived by SHAPE, so nothing has to be
    # declared anywhere: the item's text and the note's text are scanned with the same small set of
    # regexes. These are the sharpest identifiers a collection has -- measured at roughly one
    # document per distinct value -- so one is allowed to anchor, unlike any other body-derived
    # signal. See W_CODE_PATTERN.
    if idx.patterns:
        spent = defaultdict(int)
        for pc in sorted(extract_patterns(hay, idx.patterns)):
            for nid in idx.patcode2notes.get(pc, ()):
                room = W_CODE_PATTERN_MAX - spent[nid]
                if room <= 0:
                    add(nid, 0, f"record {pc} (channel budget spent)")
                    continue
                pts = min(W_CODE_PATTERN, room)
                spent[nid] += pts
                add(nid, pts, f"record {pc}")


    # 1b. Inherited codes (issue #21). Treating identifiers as flat tokens loses most of the signal
    # in a real collection: an item names the specific thing, and notes are written at the level
    # people think at. An item about `2026-AG-4` reaches notes declaring `ALPHA-REQ` or `ALPHA`
    # only by accidental title overlap, if at all, though nothing about the relationship is
    # ambiguous to a human.
    #
    # Scored BELOW a direct hit and decaying with distance, because inheritance is weaker evidence:
    # the parent is genuinely about the child, and it is also about that child's siblings. Merging
    # the two weights would let a vehicle-level note outrank the note actually about the agreement.
    if register is not None:
        for code in item_codes:
            ident, _ = register.resolve(code)
            if not ident:
                continue
            for depth, parent in enumerate(register.parents(ident), start=1):
                weight = max(1, int(W_CODE / (2 ** depth)))
                for nid in idx.code2notes.get(parent.upper(), ()):
                    add(nid, weight, f"code {code} inherits {parent} (parent, depth {depth})")

    # 2. A note's title or alias appearing verbatim in the item, capped as a CHANNEL.
    # An alias is another name for the SAME note, so a second alias matching is not independent
    # corroboration: it is one signal counted twice. Uncapped, two matching names scored 70 and
    # anchored outright -- and because each hit is worth more than MIN_ANCHOR_SIGNAL, neither the
    # floor rule nor the `weak` state could catch it. This is the person channel's bug in the one
    # channel strong enough to defeat both guards.
    # Two suppressions, in order: a name wholly contained in a longer matching name of the same note
    # ("widget prog" inside "widget programme") is the same match seen twice and scores nothing at
    # all; anything surviving that shares one budget, W_PHRASE_MAX.
    phrase_hits = defaultdict(list)
    for phrase, nids in idx.phrase2notes.items():
        if phrase in hay_l:
            for nid in nids:
                phrase_hits[nid].append(phrase)
    for nid, phrases in phrase_hits.items():
        # Longest first: the most specific name of the note is the one that earns full weight.
        ordered = sorted(set(phrases), key=lambda p: (-len(p), p))
        kept, budget = [], W_PHRASE_MAX
        for phrase in ordered:
            if any(phrase in longer for longer in kept):
                continue
            kept.append(phrase)
            pts = min(W_PHRASE, budget)
            budget -= pts
            add(nid, pts, f"phrase '{phrase[:40]}'")

    # 3. IDF-weighted token overlap against title + aliases.
    item_tokens = tokens(title) | tokens(body[:2000])
    if item_tokens:
        per_note = defaultdict(float)
        for t in item_tokens:
            w = idx.idf.get(t)
            if w is None:
                continue
            for nid in idx.token2notes[t]:
                per_note[nid] += w
        for nid, raw in per_note.items():
            pts = int(min(W_TOKENS_MAX, round(W_TOKENS_MAX * raw / (idx.max_idf * 2.5))))
            if pts >= 3:
                add(nid, pts, f"token overlap {pts}")

    # 4. Participants matching people the note names, capped as a CHANNEL and not merely per hit.
    # In a small organisation the same participants recur across most notes, so participant overlap
    # has little power to discriminate between them -- yet uncapped it is additive in the number of
    # shared participants, so five shared names on an otherwise unrelated note out-score a real
    # topical match. W_PERSON_MAX is the whole channel's budget for one note: participants may
    # reinforce a topical match, never carry one. Names past the budget still appear as evidence
    # (they are true, and a reader wants to see them) but contribute nothing to the score.
    person_hits = defaultdict(list)
    for p in item.get("participants") or []:
        for part in name_parts(p):
            for nid in idx.person2notes.get(part, ()):
                if part not in person_hits[nid]:
                    person_hits[nid].append(part)
    for nid, parts in person_hits.items():
        budget = W_PERSON_MAX
        for part in sorted(parts):
            pts = min(W_PERSON, budget)
            budget -= pts
            add(nid, pts, f"person '{part}'")

    # 5. Tags.
    for t in idx.tag2notes:
        if t and len(t) > 3 and re.search(rf"\b{re.escape(t)}\b", hay_l):
            for nid in idx.tag2notes[t]:
                add(nid, W_TAG, f"tag {t}")

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    candidates = [{"note": nid, "score": min(100, sc),
                   "evidence": sorted(set(evidence[nid]))[:EVIDENCE_MAX]} for nid, sc in ranked[:top]]

    top_score = candidates[0]["score"] if candidates else 0
    top_nid = candidates[0]["note"] if candidates else None

    # Floor rule: a pile of weak signals must not masquerade as certainty.
    capped = False
    if top_nid and top_score >= ANCHORED and best_signal[top_nid] < MIN_ANCHOR_SIGNAL:
        top_score = ANCHORED - 1
        candidates[0]["score"] = top_score
        # The marker takes a slot inside EVIDENCE_MAX rather than being appended past it: a consumer
        # that reads `evidence` as a fixed-width list would otherwise see six entries here and five
        # everywhere else, and the `weak` state now depends on this field being read correctly.
        ev = candidates[0]["evidence"]
        ev[:] = ev[:EVIDENCE_MAX - 1] + ["capped: no single signal >= %d" % MIN_ANCHOR_SIGNAL]
        capped = True

    # ...and the STATE must say so, not merely annotate it. A candidate whose every signal is
    # individually below MIN_ANCHOR_SIGNAL has accumulated a number without ever finding one piece of
    # evidence worth acting on, so it reports `weak` instead of `correlated`/`anchored`. This matters
    # because a false `correlated` is worse than a `new`: `new` sends the reader to go and look, while
    # `correlated` hands them three wrong candidates and an invitation to stop looking.
    weak = bool(top_nid) and top_score >= CORRELATED and best_signal[top_nid] < MIN_ANCHOR_SIGNAL

    # Ambiguity is two candidates pointing at DIFFERENT THINGS, not merely two close scores. In any
    # real vault a dossier is spread over several notes that naturally tie, and calling that ambiguous
    # marks nearly everything ambiguous, which is the same as marking nothing.
    ambiguous = False
    if len(candidates) > 1 and candidates[0]["score"] >= CORRELATED \
            and candidates[0]["score"] - candidates[1]["score"] <= AMBIGUOUS_GAP:
        ambiguous = idx.unrelated(candidates[0]["note"], candidates[1]["note"])

    # `weak` outranks `ambiguous`: which of two thin candidates is meant is a smaller problem than
    # neither of them resting on evidence worth acting on.
    if weak:
        state = "weak"
    elif ambiguous:
        state = "ambiguous"
    elif top_score >= ANCHORED:
        state = "anchored"
    elif top_score >= CORRELATED:
        state = "correlated"
    elif item_codes:
        # The item is code-bearing but nothing scored: the reader at least knows what it is about.
        state = "topic-known"
    else:
        state = "new"

    return {"id": item.get("id"), "state": state, "score": top_score,
            "capped": capped, "weak": weak, "candidates": candidates}


def load_schema(path):
    """Read the vault's frontmatter schema-as-code, the same file `frontmatter-lint` validates against.

    Without this the engine would carry its own private idea of which keys mean what, and a vault that
    renamed an axis would keep linting clean while silently correlating worse. The schema is the
    declared source of truth, so read it where it HAS authority and no further:

      * `axes` names are canonical key names. Axes declared `open: true` hold free topical vocabulary
        (a subject/domain), so they are folded into the tag signal. Axes with an enumerated `values`
        list are classifiers (`note_type: note` is true of almost every note) and carry almost no
        correlation information, so they are deliberately NOT used as signals.
      * `state` (status/maturity/horizon) is lifecycle, not subject matter. Never a correlation signal.

    The schema has no vocabulary for "which key holds a dossier code" or "which key names people",
    which are the two roles correlation leans on hardest. A vault may declare them in an optional
    `correlate:` block so that one file still governs; otherwise the engine's own defaults apply.

    Returns (role_overrides, topical_keys). Missing/unreadable schema -> ({}, []), i.e. no change.
    """
    if not path or not os.path.exists(path):
        return {}, []
    try:
        import yaml
        raw = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - a broken schema must not sink correlation
        print(f"WARN: could not read schema {path}: {exc}", file=sys.stderr)
        return {}, []
    if not isinstance(raw, dict):
        return {}, []

    topical = []
    for axis, spec in (raw.get("axes") or {}).items():
        if isinstance(spec, dict) and spec.get("open"):
            topical.append(axis)

    roles = {}
    for field, keys in (raw.get("correlate") or {}).items():
        if field in DEFAULT_FM_MAP:
            roles[field] = _listify(keys)
        else:
            print(f"WARN: schema `correlate:` declares unknown role {field!r}; ignored", file=sys.stderr)
    return roles, topical


def load_register(path):
    """{child: parent} from a register's parent edges. Missing/unreadable -> {} (flat space)."""
    if not path or not os.path.exists(path):
        return {}
    try:
        import yaml
        raw = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - a broken register must never sink correlation
        print(f"WARN: could not read register {path}: {exc}", file=sys.stderr)
        return {}
    return compile_patterns(raw.get("identifier_patterns"))


def load_config(path):
    """Read the optional `vault:` config section. Returns (include, fm_map)."""
    if not path:
        return [], dict(DEFAULT_FM_MAP)
    try:
        import yaml
    except ImportError:
        sys.exit("vault-correlate: --config needs pyyaml (pip install pyyaml)")
    try:
        raw = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except Exception as exc:
        sys.exit(f"vault-correlate: bad config {path}: {exc}")
    v = (raw.get("vault") or {}) if isinstance(raw, dict) else {}
    fm_map = dict(DEFAULT_FM_MAP)
    for field, keys in (v.get("frontmatter_map") or {}).items():
        if field in fm_map:
            fm_map[field] = _listify(keys)
    return _listify(v.get("include")), fm_map


def main(argv=None):
    force_utf8_stdout()
    ap = argparse.ArgumentParser(description="Correlate external items against vault notes.")
    ap.add_argument("--vault", default=VAULT)
    ap.add_argument("--config", help="YAML with a `vault:` section (include, frontmatter_map).")
    ap.add_argument("--register", help="YAML carrying `identifier_patterns`: record-number shapes "
                                       "matched in BOTH the item's and each note's text. Optional.")
    ap.add_argument("--schema", help="Frontmatter schema-as-code (the file frontmatter-lint validates "
                                     "against). Default: $FRONTMATTER_SCHEMA, else "
                                     "<vault>/.claude/data/frontmatter-schema.yaml. --no-schema to skip.")
    ap.add_argument("--no-schema", action="store_true", help="Ignore the frontmatter schema entirely.")
    ap.add_argument("--include", action="append", default=[],
                    help="Limit to these relative dirs (repeatable). Overrides config.")
    ap.add_argument("--item-file", help="JSON file with one item or a list. Default: stdin.")
    ap.add_argument("--cache", default=".vault-correlate-cache.json")
    ap.add_argument("--refresh", action="store_true", help="Ignore the cache and reparse everything.")
    ap.add_argument("--top", type=int, default=3, help="Candidates per item (default 3).")
    ap.add_argument("--list-records", action="store_true",
                    help="Dump the record-number index (needs --register) instead of correlating: "
                         "every value found in the collection, with the notes carrying it. This is "
                         "the supported way to answer 'where does this number appear' -- it reads "
                         "the SAME index the matching uses, so a search and a match can never "
                         "disagree, and it is cached, so it is instant after the first run.")
    ap.add_argument("--pattern", help="With --list-records: limit to one named pattern.")
    ap.add_argument("--stats", action="store_true", help="Print index stats to stderr.")
    args = ap.parse_args(argv)

    # Resolution order, weakest first: engine defaults -> the vault's schema (authoritative for what it
    # governs) -> an explicit --config frontmatter_map -> CLI flags.
    include, cfg_map = load_config(args.config)
    fm_map = dict(DEFAULT_FM_MAP)
    topical = []
    if not args.no_schema:
        schema_path = args.schema or os.environ.get("FRONTMATTER_SCHEMA") or \
            os.path.join(args.vault, ".claude", "data", "frontmatter-schema.yaml")
        roles, topical = load_schema(schema_path)
        fm_map.update(roles)
        if (roles or topical) and args.stats:
            print(f"schema: {schema_path} (roles from schema: {sorted(roles) or 'none'}; "
                  f"topical axes: {topical or 'none'})", file=sys.stderr)
    fm_map.update({k: v for k, v in cfg_map.items() if v != DEFAULT_FM_MAP.get(k)})
    fm_map["_topical"] = topical
    if args.include:
        include = args.include

    # The flag wins, but the env var is the documented config channel and the rest of this engine
    # already honours it (see the register load below). Reading it in only one of the two places
    # meant a correctly-configured site got record-number scoring during correlation and an error
    # from --list-records, which reads as "my register is broken" rather than "pass it twice".
    _patterns = load_register(args.register or os.environ.get("IDENTIFIER_REGISTER"))
    idx, stats = load_index(args.vault, include, fm_map, args.cache, refresh=args.refresh,
                            patterns=_patterns)
    if args.stats:
        print(f"index: {stats['notes']} notes ({stats['parsed']} parsed, {stats['cached']} cached)",
              file=sys.stderr)
    if not len(idx):
        print("WARN: index is empty; check --vault / --include", file=sys.stderr)

    if args.list_records:
        if not idx.patterns:
            sys.exit("vault-correlate: --list-records needs --register with `identifier_patterns`")
        rows = []
        for value, notes in idx.patcode2notes.items():
            name = idx.patcode2name.get(value)
            if args.pattern and name != args.pattern:
                continue
            rows.append({"pattern": name, "value": value,
                         "notes": sorted(notes), "count": len(notes)})
        rows.sort(key=lambda r: (r["pattern"] or "", -r["count"], r["value"]))
        json.dump({"records": rows, "distinct": len(rows)}, sys.stdout, indent=1)
        print()
        return 0

    raw = open(args.item_file, encoding="utf-8").read() if args.item_file else sys.stdin.read()
    if not raw.strip():
        sys.exit("vault-correlate: no input items")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"vault-correlate: input is not valid JSON: {exc}")
    items = payload if isinstance(payload, list) else [payload]

    # The register is optional: without IDENTIFIER_REGISTER correlate behaves exactly as before.
    # A register that IS named and cannot be read is an error rather than a silent absence, because
    # scoring without it would quietly lose the inheritance signal and still look like a clean run.
    register = None
    if os.environ.get("IDENTIFIER_REGISTER"):
        try:
            from _register import load as _load_register
            register = _load_register()
        except Exception as e:
            sys.stderr.write(f"correlate: IDENTIFIER_REGISTER set but unusable: {e}\n")
            sys.exit(2)

    results = [correlate(it, idx, top=args.top, register=register)
               for it in items if isinstance(it, dict)]
    json.dump({"vault": args.vault, "index": stats, "items": results},
              sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
