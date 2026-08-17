#!/usr/bin/env python3
# @capability:  ingest-core
# @compute:     deterministic
# @effect:      pure library (no I/O)
# @engine:      scripts/_ingest_core.py
# @prompt:      (none)
# @adapters:    import (shared helper)
# @portability: L1a-generic
# @forbidden:   n/a (writes nothing)
# @audit:       none
# @status:      experimental
# @doc:         docs/adr-0004-ingestion-source-seam.md
"""Source-agnostic core for ingestion engines.

Everything downstream of ingest is the same regardless of what produced the record: recognising that
someone asked for something, resolving when it is due, spotting a handling marking, deciding whether
an attachment is worth opening, and deciding whether a human or a model needs to look. Only the
reader differs. This module is that shared half, so a second source does not fork it.

Three rules define what may live here, and a test enforces the first:

1. **No site vocabulary.** No programme codes, no organisation names, no domains, no personal
   identities, no folder names. Those are DATA and belong in a caller-supplied config.
2. **No I/O.** Pure functions over values. The caller reads files and writes reports.
3. **No source assumptions.** Nothing here may know what a mailbox, a notebook or a ticket is. Where
   a source-specific signal is needed, the caller passes it in.

The engine is MULTILINGUAL by construction and ships no language. Which languages are active, and
the patterns for each, are config: baking a language set into a shared engine is the same mistake as
baking in programme codes. `self_test()` proves every language a site DECLARES actually matches the
probes that site wrote for it, because a pattern firing in one language and silently not in another
under-scores that share of the corpus while the report still looks healthy.
"""
import re
from datetime import datetime, timezone

try:
    import dateparser
except ImportError:                      # optional: without it, deadline phrases stay unresolved
    dateparser = None


# ---------------------------------------------------------------------------
# Language packs: MULTILINGUAL by construction, with no language built in
# ---------------------------------------------------------------------------
# The engine matches patterns; it does not know which languages you work in. Which languages are
# active, and the regexes for each, are CONFIG. Baking a specific set into a shared engine is the
# same mistake as baking in programme codes: it happens to be right for one operator and wrong for
# everyone else, and it cannot be corrected without editing the engine.
#
# A pack declares, per language, the vocabulary for each signal, plus PROBES the parity harness uses
# to prove the language is actually wired up. See `config.example/ingest-languages.example.yaml`.
#
# The engine ships NO packs. `load_language_packs()` returns empty structures until a caller supplies
# them, and `parity_failures()` reports an unconfigured engine rather than silently passing.

SIGNAL_KINDS = ("request", "decision", "waiting", "deliver", "meeting")
SIGNAL_SETS = ("urgency", "deadline_cue", "delegation", "attach_ref", "substantive_filename")

QUESTION_LINE = re.compile(r"^[^\n]{10,220}\?\s*$", re.M)   # punctuation, not language

# Handling markings are standards-based (RFC-style TLP, treaty and national marking schemes), so the
# DEFAULT set is genuinely generic. Sites extend it via `markings.extra` for local schemes.
CLASSIFICATION_MARK_DEFAULT = re.compile(
    # The separator class is wide because OCR-DERIVED text reaches this scanner. Tesseract reads a
    # colon as a period or a semicolon often enough that a scanned page marked TLP:AMBER was
    # reported as carrying no marking at all, which is the exact silent bypass this scan exists to
    # prevent. Widening the SEPARATOR is safe: both the keyword and a valid level are still
    # required, so "TLP" alone, "AMBER" alone and "TLP.PURPLE" all remain non-matches.
    r"\b(TLP[\s:;.,\-]{0,3}(RED|AMBER\+STRICT|AMBER|GREEN|CLEAR|WHITE)|"
    r"COMMERCIAL[- ]IN[- ]CONFIDENCE|PROPRIETARY\s+(?:AND\s+)?CONFIDENTIAL)\b",
    re.I,
)


class LanguagePacks:
    """Compiled, merged patterns for the configured languages.

    Merging rather than iterating per language is deliberate: a corpus mixes languages inside a
    single item (a Dutch reply quoting an English request), so per-language dispatch would need to
    segment the text first and would get it wrong at exactly the boundaries that matter.
    """

    def __init__(self, langs=(), actions=None, sets=None, probes=None, markings=None):
        self.langs = tuple(langs)
        self.actions = actions or {}          # kind -> compiled
        self.sets = sets or {}                # set name -> compiled
        self.probes = probes or {}            # lang -> {signal: probe text}
        self.markings = markings or CLASSIFICATION_MARK_DEFAULT

    @property
    def action_patterns(self):
        """[(kind, compiled)] in the historical shape, for callers that iterate."""
        return [(k, v) for k, v in self.actions.items()]

    def configured(self):
        return bool(self.langs)


def _join(fragments):
    parts = [f for f in fragments if f]
    return re.compile("|".join(f"(?:{f})" for f in parts), re.I) if parts else None


def load_language_packs(cfg):
    """Build LanguagePacks from a config mapping. Empty config yields an unconfigured pack set.

    cfg shape:
        languages:
          active: [en, nl]
          packs:
            en:
              actions: {request: '...', decision: '...'}
              urgency: '...'
              deadline_cue: '...'
              probes: {request: 'could you please send the file'}
    """
    langs_cfg = (cfg or {}).get("languages") or {}
    packs = langs_cfg.get("packs") or {}
    active = [str(l) for l in (langs_cfg.get("active") or list(packs))]

    actions, sets, probes = {}, {}, {}
    for kind in SIGNAL_KINDS:
        frag = [((packs.get(l) or {}).get("actions") or {}).get(kind) for l in active]
        pat = _join(frag)
        if pat:
            actions[kind] = pat
    for name in SIGNAL_SETS:
        pat = _join([(packs.get(l) or {}).get(name) for l in active])
        if pat:
            sets[name] = pat
    for l in active:
        pr = (packs.get(l) or {}).get("probes") or {}
        if pr:
            probes[l] = dict(pr)

    marks = CLASSIFICATION_MARK_DEFAULT
    extra = (cfg or {}).get("markings", {}).get("extra") if isinstance(cfg, dict) else None
    if extra:
        joined = "|".join(f"(?:{e})" for e in extra)
        marks = re.compile(f"{CLASSIFICATION_MARK_DEFAULT.pattern}|{joined}", re.I)

    return LanguagePacks(active, actions, sets, probes, marks)


# ---------------------------------------------------------------------------
# File-format facts. Not language, not site vocabulary: these are properties of the formats
# themselves, so they belong in the engine.
# ---------------------------------------------------------------------------
INLINE_ATTACH = re.compile(
    r"^(image|oledata|ole)\d*\.(png|jpe?g|gif|bmp|emf|wmf|mso)$|^winmail\.dat$", re.I)
PARSEABLE_EXT = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
                 ".csv", ".txt", ".md", ".rtf"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


DEFAULT_GATE_RULES = {
    "no_topic_high_score": 20, "ask_without_specifics": 15, "many_questions": 15,
    "deadline_unresolved": 15, "long_body": 15, "thin_body_with_attachments": 15,
    "image_needs_vision": 20, "delegated_unread": 15, "contradictory_direction": 10,
    "new_and_nontrivial": 10, "long_thread": 10, "resolved_credit": -15,
}

def find_markings(text: str, packs=None) -> list[str]:
    """Handling markings found in a body or a parsed attachment, normalized and deduped."""
    if not text:
        return []
    pat = packs.markings if packs is not None else CLASSIFICATION_MARK_DEFAULT
    seen = {" ".join(m.group(0).split()).upper() for m in pat.finditer(text)}
    return sorted(seen)[:4]

_PARSER_LANGS = None


def _parser_languages():
    """Language codes the installed date parser recognises. Empty set when it is absent."""
    global _PARSER_LANGS
    if _PARSER_LANGS is None:
        try:
            from dateparser.data.languages import language_map
            _PARSER_LANGS = set(language_map)
        except Exception:  # noqa: BLE001 - fall back to a permissive, well-known subset
            _PARSER_LANGS = {"en", "nl", "fr", "de", "es", "it", "pt", "pl", "sv", "da", "no", "fi"}
    return _PARSER_LANGS


def unsupported_date_languages(langs):
    """Configured codes the date parser will ignore. Surface these; do not fail on them.

    A site may name a pack anything. If the name is not a code the parser knows, deadline resolution
    quietly stops working for that language while every other signal keeps firing, which looks like
    "we just have no deadlines" rather than like a misconfiguration.
    """
    return [l for l in langs if l not in _parser_languages()]


def resolve_deadline(phrase: str, base: datetime | None, display: str | None = None,
                     langs=(), now: datetime | None = None) -> dict:
    """Turn a deadline phrase into a real date, relative to when the item was WRITTEN.

    A weekday name or a bare "6/8" means the one after the author typed it, not after the run.
    Without a resolved date an already-blown deadline is indistinguishable from a live one, which is
    the failure mode of returning to a backlog.

    `langs` are the configured language codes, passed through to the date parser. They are NOT
    hardcoded here: which languages a site works in is config, and a fixed list would silently fail
    to parse dates for anyone whose languages differ.
    """
    out = {"phrase": display or phrase, "date": None, "days_until": None, "passed": None}
    if dateparser is None or not base:
        return out
    # Only pass codes the date parser actually knows. A site is free to name its packs anything, and
    # an unrecognised code makes dateparser resolve NOTHING while raising no error, which would kill
    # deadline detection silently. Unknown codes fall back to autodetect rather than to failure.
    known = [l for l in langs if l in _parser_languages()]
    try:
        d = dateparser.parse(
            phrase, languages=known or None,
            settings={"RELATIVE_BASE": base.replace(tzinfo=None),
                      "PREFER_DATES_FROM": "future", "DATE_ORDER": "DMY", "RETURN_AS_TIMEZONE_AWARE": False},
        )
    except Exception:  # noqa: BLE001 - a weird phrase must not kill the run
        d = None
    if d:
        d = d.replace(tzinfo=timezone.utc)
        out["date"] = d.strftime("%Y-%m-%d")
        # `base` and `now` are different clocks and both must be injectable: base is when the
        # item was WRITTEN, which a relative phrase resolves against; now is the reference TODAY,
        # which the remaining distance is measured from. Only base was a parameter, so this read
        # the wall clock. Invisible in normal use and fatal to a characterization snapshot: every
        # recorded distance shrinks by one per day, so the harness reports drift daily on
        # unchanged code, and a check that cries wolf every morning gets re-frozen unread.
        out["days_until"] = (d - (now or datetime.now(timezone.utc))).days
        out["passed"] = out["days_until"] < 0
    return out

def extract_actions(clean_body: str, base: datetime | None = None, packs=None,
                    now: datetime | None = None) -> dict:
    packs = packs if packs is not None else LanguagePacks()
    kinds = [k for k, pat in packs.actions.items() if pat.search(clean_body)]
    questions = [q.strip() for q in QUESTION_LINE.findall(clean_body)][:5]
    # Keep the whole phrase for display but hand ONLY the date token to the date parser: a cue word
    # plus a date parses as nothing, the bare date parses fine. The cue is context for a human and
    # noise for the parser.
    #
    # Uses finditer over findall deliberately. Per-language cue patterns are OR-ed together, so the
    # number of capture groups depends on how many languages are configured, and unpacking a fixed
    # pair breaks the moment a site adds a second language. Take group(0) as the display text and the
    # first non-empty group as the date token, which is stable for any number of alternatives.
    cue = packs.sets.get("deadline_cue")
    raw, resolved = [], []
    if cue:
        for m in list(cue.finditer(clean_body))[:5]:
            display = " ".join(m.group(0).split())
            token = next((g for g in m.groups() if g), display)
            raw.append(display)
            resolved.append(resolve_deadline(token, base, display=display, langs=packs.langs,
                                              now=now))
    return {
        "action_kinds": kinds,
        "questions": questions,
        "deadline_hits": raw,
        "deadlines": resolved,
        "urgent_words": (sorted({w.lower() for w in packs.sets["urgency"].findall(clean_body)})[:6]
                         if packs.sets.get("urgency") else []),
    }

ESCALATE_THRESHOLD = 35


def escalation_gate(sig: dict, rules: dict | None = None) -> dict:
    """Score how much the deterministic pass did NOT understand about one item.

    Takes an explicit signal dict rather than a source record, so nothing here knows what a mailbox,
    a notebook or a ticket is. The caller maps its own record onto these names:

        body              str    the item text the engine actually scored
        topics            list   recognised topics, [] if none matched
        score             int    the item's relevance/urgency score
        actions           dict   output of extract_actions()
        deadline_state    str    "unresolved" | "imminent" | "passed" | "future" | None
        attachments       list   [{"inline": bool, "tier": str}, ...]
        digests           list   [{"parsed": bool}, ...] for attachments actually read
        needs_vision      list   names of images that may be load-bearing but cannot be read
        aside             bool   scored high but not primarily directed at the operator
        correlation_state str    "NEW" when the knowledge base has never seen this
        group_size        int    thread/cluster size collapsed into this one row

    Returns {"ambiguity", "confidence", "reasons"}. Higher ambiguity means the deterministic pass
    resolved less, and past a threshold the item earns a model read.
    """
    G = dict(DEFAULT_GATE_RULES)
    if rules:
        G.update(rules)
    amb, why = 0, []
    a = sig.get("actions") or {}
    body_len = len(sig.get("body") or "")
    score = sig.get("score", 0)
    atts = sig.get("attachments") or []

    # 1. Recognised as important, but not recognised as anything in particular.
    if not sig.get("topics") and score >= 40:
        amb += G["no_topic_high_score"]; why.append("high score, no topic matched")

    # 2. Someone is clearly asking for something, but the engine cannot tell what.
    if a.get("action_kinds") and not a.get("questions") and not a.get("deadline_hits"):
        amb += G["ask_without_specifics"]; why.append("ask detected, no explicit question or deadline")

    # 3. Several questions at once: real interpretation work, not pattern matching.
    if len(a.get("questions", [])) >= 3:
        amb += G["many_questions"]; why.append(f"{len(a['questions'])} questions to disentangle")

    # 4. A deadline phrase we could not turn into a date.
    if sig.get("deadline_state") == "unresolved":
        amb += G["deadline_unresolved"]; why.append("deadline phrase would not resolve to a date")

    # 5. Long body: the cost of a model read is justified by what a human would otherwise scan.
    if body_len > 3000:
        amb += G["long_body"]; why.append(f"long body ({body_len} chars)")

    # 6. The substance is in an attachment, not the item text.
    if body_len < 400 and any(not x.get("inline") for x in atts):
        amb += G["thin_body_with_attachments"]; why.append("short body, substance is in the attachment")

    # 6b. An image the engine cannot read but that looks load-bearing. Only a vision read settles it.
    if sig.get("needs_vision"):
        amb += G["image_needs_vision"]
        why.append(f"image needs a vision read: {', '.join(sig['needs_vision'][:2])}")

    # 6c. Delegated to a document we did not successfully read (gate off, cap hit, or parse failed).
    # Keys on PARSED digests, not on the digest list: a failed parse leaves a truthy error record,
    # which silenced this rule precisely when the document had not been read.
    delegating = any(x.get("tier") in ("delegated", "thin-body-wrapper", "forwarded",
                                       "substantive-filename") for x in atts)
    if delegating and not [d for d in (sig.get("digests") or []) if d.get("parsed")]:
        amb += G["delegated_unread"]; why.append("body delegates to an attachment that was not read")

    # 7. Contradictory signals: scored high but not actually directed at the operator.
    if score >= 50 and sig.get("aside"):
        amb += G["contradictory_direction"]; why.append("scores high but is not directed at you")

    # 8. Never seen in the knowledge base and non-trivial: may need a note written.
    if sig.get("correlation_state") == "NEW" and score >= 40:
        amb += G["new_and_nontrivial"]; why.append("no vault anchor and non-trivial")

    # 9. A long thread compressed into one row hides its own history.
    if sig.get("group_size", 1) >= 4:
        amb += G["long_thread"]
        why.append(f"{sig['group_size']}-message thread collapsed to one row")

    # Cheap negative signal: a short, clear, anchored, low-score item is genuinely done.
    # NOT applied when unread attachments are present: a thin body over unparsed documents is the
    # definition of unresolved, and this credit cancelled rule 6 exactly there.
    unread_att = bool([x for x in atts if not x.get("inline")]) and not [
        d for d in (sig.get("digests") or []) if d.get("parsed")]
    if body_len < 800 and sig.get("topics") and score < 40 and not unread_att:
        amb += G["resolved_credit"]; why.append("short, anchored, low score")

    amb = max(0, min(100, amb))
    return {"ambiguity": amb, "reasons": why, "confidence": 100 - amb}

def band(score: int) -> str:
    if score >= 60:
        return "ACT-NOW"
    if score >= 40:
        return "REVIEW"
    if score >= 20:
        return "SCAN"
    return "FYI"

def content_hash(*parts) -> str:
    """A short, stable digest over several strings, with an unambiguous separator.

    The NUL between parts is the whole point: without it hash("ab", "c") and hash("a", "bc") are the
    same value, so two different items collide and an idempotency ledger silently treats one as a
    re-import of the other.
    """
    import hashlib
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def normalise_marking(m: str) -> str:
    """Fold a handling marking to one comparable form: collapsed spacing, tight colon, upper case.

    `TLP: Amber`, `tlp:amber` and `TLP  :  AMBER` are the same marking written three ways, and a
    policy comparing them as strings treats them as three, which is how a rule permitting one of
    them silently fails to permit the others.
    """
    return re.sub(r"\s*:\s*", ":", " ".join((m or "").split())).upper()


def load_forbidden_zones(path) -> list:
    """Read a zones file: `<path-prefix>` optionally followed by a rationale. Returns the prefixes.

    The loader upstream was missing while `in_forbidden_zone` and `safe_write(zones=...)` both
    existed, so every consumer parsed the file itself, and the parse is where the trap is.

    A zone is a DIRECTORY PREFIX, so it ends at the first "/" followed by whitespace or end of
    line. That is what lets a rationale sit after a single space, which real files do the moment one
    path is long enough to break the column alignment. A tab or two-or-more spaces is the fallback
    for a line with no trailing slash.

    Getting this wrong is not cosmetic. Take the whole line as the path and every prefix match
    fails, which silently disables the entire write-ban while the loader still reports the right
    number of zones. A ban that is loaded, counted and inert is worse than one that is absent,
    because the count reads as proof that it works.

    Prefixes come back normalised to forward slashes with a trailing slash, so a caller comparing
    them cannot accidentally match `06 - Procurementdossier` against the zone `06 - Procurement`.
    """
    from pathlib import Path as _P
    if not path or not _P(path).exists():
        return []
    zones = []
    for line in _P(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^(.*?/)(?:\s|$)", line)
        prefix = m.group(1) if m else re.split(r"\t|\s{2,}", line, maxsplit=1)[0]
        prefix = prefix.strip()
        if prefix:
            zones.append(prefix.replace("\\", "/").rstrip("/") + "/")
    return zones


# ============================================================================
# THE ITEM, AND ITS PROJECTIONS
# ============================================================================
# One shape for "something ingested from outside", plus the projections that turn it into what a
# particular consumer wants. The projections are the point: a source reader should never need to
# know what the correlation engine's envelope looks like, and two readers producing subtly
# different envelopes is how one of them quietly correlates worse than the other with nothing
# saying so.

ITEM_FIELDS = ("id", "fallback_id", "title", "body", "created", "modified",
               "path", "order", "participants", "codes", "attachments",
               "source", "raw_ref", "loss")


def make_item(**kw) -> dict:
    """Build an Item, refusing any field the contract does not declare.

    The refusal is the useful part. A typo in a keyword would otherwise create a field nobody reads,
    and the value would be silently absent everywhere downstream while the caller believed it was
    set.
    """
    item = {f: kw.get(f) for f in ITEM_FIELDS}
    for list_field in ("path", "participants", "codes", "attachments", "loss"):
        item[list_field] = list(item[list_field] or [])
    item["title"] = item["title"] or "untitled"
    item["body"] = item["body"] or ""
    unknown = set(kw) - set(ITEM_FIELDS)
    if unknown:
        raise ValueError(f"unknown Item field(s): {sorted(unknown)}")
    return item


def correlation_envelope(item: dict, body_cap: int = 8000) -> dict:
    """The shape the correlation engine accepts, for an Item from any source.

    This lived in a consumer, which meant the INPUT CONTRACT OF A PUBLISHED ENGINE was defined in a
    private file: anyone using `correlate` had to reverse-engineer the envelope from prose. It also
    meant every new source reader was free to invent its own envelope, and the correlation engine
    cannot tell a worse envelope from a worse corpus.

    NEGATIVE RESULT, measured. Do not re-add container-qualified titles without new evidence.

    Contextual retrieval (prepending a container's context to a chunk before indexing) is reported
    to cut failed retrievals substantially, and item titles are often uninformative on their own
    ("Todo", "Notes", "Misc"), so qualifying a title with its container looked like a free win.
    Measured on a real 411-page notebook:

        qualify every title      -> WORSE  (ambiguous +7, correlated -6, anchored -1)
        qualify only short ones  -> exactly baseline, over 153 qualified titles

    Why it does not transfer: the reported technique adds context that DIFFERS per chunk, so it
    discriminates. A container name is IDENTICAL across every item in that container, so it is a
    constant. It discriminates nothing and drags every item in a container toward the same notes,
    manufacturing ties. The container chain is still carried in `path` for an emitter to use; it
    just does not belong in the matching signal.
    """
    when = item.get("created") or item.get("modified")
    return {
        "title": item.get("title") or "",
        "body": (item.get("body") or "")[:body_cap],
        "participants": list(item.get("participants") or []),
        # Source-declared codes AND engine-classified topics. Correlation wants every identifier
        # that could anchor a match; which side produced it is not its concern.
        "codes": sorted(set(item.get("codes") or []) | set(item.get("topics") or [])),
        "date": when.strftime("%Y-%m-%d") if isinstance(when, datetime) else None,
    }


def read_gate_frontmatter(item: dict, default_source: str = "import") -> dict:
    """Project an Item onto the frontmatter fields a read-gate policy reasons about.

    An imported item has no frontmatter yet, since that is what is about to be written, so the gate
    is asked about the fields the note WOULD carry.

    DETECTED MARKINGS ARE NOT A CLASSIFICATION, and this projection once said they were. A
    classification is an authority's assertion about material; a detected marking is a regex hit in
    body text, which fires as readily on an item DISCUSSING markings as on one carrying them.
    Measured on a real collection: 164 notes contain high-marking text and almost none are marked,
    partly because one of the marking words is also an ordinary word in one of the languages
    scanned. Asserting a marking nobody applied leaves a policy unable to tell prose from a real
    marking, which is worse than having no signal.

    Provenance and inherited marking are kept in SEPARATE fields for the same reason. Every item has
    provenance; only a marked one has an inherited marking, and conflating them makes a rule that
    denies on inheritance deny everything.
    """
    marks = [m for m in (item.get("markings") or []) if m]
    view = {
        "source": item.get("source") or default_source,
        "tags": [f"topic/{t}" for t in (item.get("topics") or [])],
        "status": "stub",
    }
    if marks:
        view["detected_marking"] = marks
    ref = item.get("raw_ref") or item.get("source_ref") or item.get("id")
    if ref:
        view["source_ref"] = [str(ref)]
        if marks:
            view["marking_derived_from"] = [str(ref)]
    return view


REPORT_STAMP = "%Y-%m-%d"


def report_name(engine: str, stamp, source: str | None = None, ext: str = "md") -> str:
    """`<engine>-[<source>-]<stamp>.<ext>`: the one definition of a report filename.

    Three consumer engines already agreed on this shape, each with its own f-string, so there was
    nothing to unify in behaviour. What there was to unify is the ABILITY TO DRIFT: change the stamp
    format in one and the others keep the old one, and a directory of reports stops sorting together
    with no error anywhere. Three literals is not a lot of duplication; it is exactly enough for two
    of them to be edited and the third forgotten.

    `source` is included only when an engine can be pointed at more than one subject in a day. A
    mailbox run is per-day and a date is enough; an archive run is per-archive, and two archives
    processed on one day must not overwrite each other.
    """
    stamp = stamp.strftime(REPORT_STAMP) if hasattr(stamp, "strftime") else str(stamp)
    middle = f"{source}-" if source else ""
    return f"{engine}-{middle}{stamp}.{ext.lstrip('.')}"


def slug(text: str, maxlen: int = 60) -> str:
    """Lowercase kebab, ACCENT-FOLDED first so `reunion` and `réunion` land on the same slug.

    Without the fold the two are different filenames and different ledger keys, so the same subject
    written either way imports twice. It also keeps a slug ASCII-safe, which matters wherever it
    becomes a path or a link target.
    """
    import unicodedata
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    s = re.sub(r"[^\w\-]+", "-", t).strip("-").lower()
    s = re.sub(r"-+", "-", s)
    return (s[:maxlen].rstrip("-") or "untitled")

def first_lines(text: str, n: int = 3, width: int = 150) -> str:
    out = []
    for ln in (text or "").splitlines():
        ln = ln.strip()
        if len(ln) > 3 and not ln.startswith((">", "|", "*\t")):
            out.append(ln[:width])
        if len(out) >= n:
            break
    return " / ".join(out)


# ---------------------------------------------------------------------------
# Trilingual parity
# ---------------------------------------------------------------------------
# A pattern that only fires in one language does not fail loudly. It silently under-scores that share
# of the corpus while the report still looks healthy, which is why this is enforced rather than
# assumed. Run it after touching ANY pattern above.

def parity_failures(packs):
    """Which configured languages fail their own probes. Empty means every language is wired up.

    Generic over whatever languages a site declares. The engine has no opinion about which languages
    exist; it only insists that each one a site claims to support actually matches the probe that
    site wrote for it. A pattern firing in one language and silently not in another under-scores that
    share of the corpus while the report still looks healthy, which is the failure this prevents.
    """
    if packs is None or not packs.configured():
        return [("(no languages configured)", "-", "declare languages.active and languages.packs")]
    bad = []
    for lang, probes in sorted(packs.probes.items()):
        for signal, text in sorted(probes.items()):
            if signal in SIGNAL_KINDS:
                hit = signal in [k for k, pat in packs.actions.items() if pat.search(text)]
            elif signal in SIGNAL_SETS:
                pat = packs.sets.get(signal)
                hit = bool(pat and pat.search(text))
            else:
                bad.append((signal, lang, f"unknown signal name in probes: {signal!r}"))
                continue
            if not hit:
                bad.append((signal, lang, text))
    missing = [l for l in packs.langs if l not in packs.probes]
    for l in missing:
        bad.append(("(no probes)", l, "a language with no probes is unverifiable"))
    return bad


def self_test(packs, verbose=True):
    """Exit-code-shaped parity check: 0 when every configured language matches its probes."""
    bad = parity_failures(packs)
    if verbose:
        for signal, lang, text in bad:
            print(f"  MISS {signal} [{lang}]: {text!r}")
    if bad:
        if verbose:
            print(f"\nPARITY FAIL: {len(bad)} probe(s) did not match")
        return 1
    if verbose:
        langs = " / ".join(l.upper() for l in packs.langs)
        print(f"PARITY OK: {langs} at parity across all configured signals.")
    return 0
