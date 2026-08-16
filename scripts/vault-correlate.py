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

States: anchored (>=70, one note) | correlated (40-69) | topic-known (a code matched, no note
reached 40) | ambiguous (top two candidates within 15 points of each other) | new (<40).

Design notes worth keeping in mind when editing:

* Scoring is additive with a floor rule: no single signal below MIN_ANCHOR_SIGNAL may produce an
  `anchored` verdict on its own. Filename-substring matching without this rule is how a correlator
  starts confidently attaching mail to the wrong note.
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
W_CODE = 40          # a shared dossier/programme/ticket code
W_PHRASE = 35        # the item's title contains a note's title or alias verbatim
W_TOKENS_MAX = 25    # IDF-weighted token overlap, capped
W_PERSON = 20        # a participant resolves to a person named by the note
W_TAG = 10           # a shared tag
MIN_ANCHOR_SIGNAL = 30   # no signal weaker than this may anchor by itself
ANCHORED, CORRELATED, AMBIGUOUS_GAP = 70, 40, 15

CACHE_VERSION = 3   # 3: signature depends on substrate trust, so v2 entries are not comparable

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


def build_card(path, reldir, fm_map, vault):
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
    codes = [c.upper() for c in _strip_links(_listify(pick("codes")))]
    people = [p.lower() for p in _strip_links(_listify(pick("people")))]

    _, rest = split_frontmatter(text)
    body = rest or text
    links = [m.strip() for m in WIKILINK_RE.findall(body)] + \
            [os.path.splitext(os.path.basename(m))[0] for m in MDLINK_RE.findall(body)]

    return NoteCard({
        "note": rel, "reldir": reldir.replace(os.sep, "/"), "stem": stem,
        "title": title, "aliases": aliases, "tags": tags, "codes": codes,
        "people": people, "links_out": sorted(set(links))[:200],
        "note_type": fm.get("note_type") or fm.get("type"),
    })


class VaultIndex:
    """Frontmatter-aware note index with the inverted maps correlation needs."""

    def __init__(self, cards):
        self.cards = {c["note"]: c for c in cards}
        self.code2notes = defaultdict(set)
        self.tag2notes = defaultdict(set)
        self.person2notes = defaultdict(set)
        self.token2notes = defaultdict(set)
        self.phrase2notes = defaultdict(set)
        for c in cards:
            nid = c["note"]
            for code in c["codes"]:
                self.code2notes[code].add(nid)
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


def load_index(vault, include, fm_map, cache_path, refresh=False):
    """Build (or incrementally refresh) the index.

    The cache key is normally (mtime, size), which is cheap and correct on an ordinary disk. On a
    synced mount it is neither: size and mtime are the sync client's answers rather than the
    author's, so an edited note can keep its old signature and the cache serves a stale card
    forever, with plausible output and no error anywhere.

    So the substrate decides the key. Where metadata cannot be trusted the signature is a content
    hash, which costs a read per file and is the only thing that stays true.
    """
    from _substrate import content_signature, probe          # noqa: E402
    substrate = probe(vault)
    trust_metadata = substrate["metadata_reliable"]
    cache = {}
    if cache_path and os.path.exists(cache_path) and not refresh:
        try:
            blob = json.load(open(cache_path, encoding="utf-8"))
            if blob.get("version") == CACHE_VERSION and blob.get("fm_map") == fm_map:
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
        card = build_card(path, reldir, fm_map, vault)
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
                json.dump({"version": CACHE_VERSION, "fm_map": fm_map, "cards": cache}, f)
        except OSError as exc:
            print(f"WARN: could not write cache {cache_path}: {exc}", file=sys.stderr)

    return VaultIndex(cards), {"notes": len(cards), "parsed": fresh, "cached": reused}


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

    # 1. Codes: the strongest deterministic signal there is.
    item_codes = {str(c).upper() for c in item.get("codes") or []}
    for code in item_codes:
        for nid in idx.code2notes.get(code, ()):
            add(nid, W_CODE, f"code {code}")

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

    # 2. A note's title or alias appearing verbatim in the item.
    for phrase, nids in idx.phrase2notes.items():
        if phrase in hay_l:
            for nid in nids:
                add(nid, W_PHRASE, f"phrase '{phrase[:40]}'")

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

    # 4. Participants matching people the note names.
    seen_person = set()
    for p in item.get("participants") or []:
        for part in name_parts(p):
            for nid in idx.person2notes.get(part, ()):
                if (nid, part) not in seen_person:
                    seen_person.add((nid, part))
                    add(nid, W_PERSON, f"person '{part}'")

    # 5. Tags.
    for t in idx.tag2notes:
        if t and len(t) > 3 and re.search(rf"\b{re.escape(t)}\b", hay_l):
            for nid in idx.tag2notes[t]:
                add(nid, W_TAG, f"tag {t}")

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    candidates = [{"note": nid, "score": min(100, sc),
                   "evidence": sorted(set(evidence[nid]))[:5]} for nid, sc in ranked[:top]]

    top_score = candidates[0]["score"] if candidates else 0
    top_nid = candidates[0]["note"] if candidates else None

    # Floor rule: a pile of weak signals must not masquerade as certainty.
    capped = False
    if top_nid and top_score >= ANCHORED and best_signal[top_nid] < MIN_ANCHOR_SIGNAL:
        top_score = ANCHORED - 1
        candidates[0]["score"] = top_score
        candidates[0]["evidence"].append("capped: no single signal >= %d" % MIN_ANCHOR_SIGNAL)
        capped = True

    # Ambiguity is two candidates pointing at DIFFERENT THINGS, not merely two close scores. In any
    # real vault a dossier is spread over several notes that naturally tie, and calling that ambiguous
    # marks nearly everything ambiguous, which is the same as marking nothing.
    ambiguous = False
    if len(candidates) > 1 and candidates[0]["score"] >= CORRELATED \
            and candidates[0]["score"] - candidates[1]["score"] <= AMBIGUOUS_GAP:
        ambiguous = idx.unrelated(candidates[0]["note"], candidates[1]["note"])

    if ambiguous:
        state = "ambiguous"
    elif top_score >= ANCHORED:
        state = "anchored"
    elif top_score >= CORRELATED:
        state = "correlated"
    elif item_codes & set(idx.code2notes) or any(
            c in " ".join(idx.code2notes) for c in item_codes):
        state = "topic-known"
    elif item_codes:
        state = "topic-known"
    else:
        state = "new"

    return {"id": item.get("id"), "state": state, "score": top_score,
            "capped": capped, "candidates": candidates}


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

    idx, stats = load_index(args.vault, include, fm_map, args.cache, refresh=args.refresh)
    if args.stats:
        print(f"index: {stats['notes']} notes ({stats['parsed']} parsed, {stats['cached']} cached)",
              file=sys.stderr)
    if not len(idx):
        print("WARN: index is empty; check --vault / --include", file=sys.stderr)

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
