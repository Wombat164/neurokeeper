#!/usr/bin/env python3
# @capability:  memory-audit
# @compute:     hybrid
# @effect:      mutating
# @engine:      scripts/memory-consolidate.py
# @prompt:      prompts/memory-audit.md
# @adapters:    skill:memory-audit, cli
# @portability: L1a-generic
# @forbidden:   enforced
# @audit:       dream-log
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""
memory-consolidate.py -- DETERMINISTIC analyzer for /vault-memory-audit --consolidate.

WHY THIS EXISTS: the --consolidate analysis (importance curve, 5-metric health score,
orphan/broken-link/stale/dead-end detection, proposal table) was previously LLM-eyeballed,
which is the documented never-hallucinate failure class (fabricated counts, hallucinated filenames,
undetected orphans). This computes every number from the real filesystem so the proposal
is reproducible and cannot be hallucinated. Output is read-only; it proposes, never writes.

Implements the consolidation spec (see prompts/memory-audit.md):
  half_life_days = 90 + 90*log2(reference_count + 1)
  recency        = exp(-days_since_mtime / half_life_days)
  importance     = recency * base_weight     (2.0 if PERMANENT tag, 1.5 if HIGH, else 1.0)
  archive candidate: importance < 0.15

Usage: python scripts/memory-consolidate.py [--json|--terse|--check|--lint|--candidates] [--today YYYY-MM-DD]
  --lint       : advisory index-compression + size-cap + link-integrity check (R11). Never blocks (exit 0).
  --candidates : deterministic MERGE + CONTRADICTION candidate pairs (R14) as JSON, a narrowing
                 pre-filter for a gated judge; the engine proposes candidates, never verdicts.
"""
import os, re, sys, json, math
from datetime import datetime, timezone

MEM_DIR = os.environ.get("CLAUDE_MEMORY_DIR") or os.path.expanduser("~/.claude/memory")
INBOX_DIR = os.environ.get("VAULT_INBOX_DIR", "")   # optional: inbox-pressure metric (skipped if unset)
VAULT_ROOT = os.environ.get("VAULT_ROOT", "")        # optional: Phase-E vault-note count (skipped if unset)
STALE_THRESHOLD = 0.15
MEMORY_LINE_LIMIT = 180   # warn threshold; HARD harness cap = 200 lines
# HARNESS READ CAP (verified 2026-07-04 vs Claude Code memory loader + docs):
# MEMORY.md loads ONLY the first 200 lines OR 25000 bytes, whichever first; anything past
# either axis is silently dropped from context. The prior 45000 was 1.8x the real cap, so
# this reported "OK" while the loader truncated the index. Aim <=17500 / <=140 for headroom.
BYTES_BUDGET = 25000  # HARD harness cap; aim <=17500 for headroom
LINE_CAP, LINE_TARGET = 200, 140        # hard harness cap / headroom target (for --lint)
BYTES_CAP, BYTES_TARGET = 25000, 17500  # hard harness cap / headroom target (for --lint)
CAVEMAN_MAX_ENTRY_CHARS = 260           # dense archive-rollup pointers may run long; flag only outliers
# Per-note-type BASE half-life (days); the reference-count bonus multiplies on top:
#   half_life = base * (1 + log2(refs + 1)).  Default base 90 reproduces the prior
#   90 + 90*log2(refs+1) curve EXACTLY, so untyped stores are unchanged.
TYPE_HALFLIFE = {"user": 365, "reference": 270, "feedback": 180, "project": 90}
SNOOZE_DEFAULT_DAYS = 120  # a `reviewed:` stamp suppresses the stale flag for this long, unless `ttl:` overrides


def _frontmatter(text):
    """Flat key->value of the leading YAML block (captures nested keys like metadata.type too)."""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    fm = {}
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"\s*([A-Za-z_][\w-]*):\s*(\S.*?)\s*$", line)
            if mm:
                fm[mm.group(1).lower()] = mm.group(2).strip().strip("\"'")
    return fm


def _snoozed(fm, now):
    """True if a recent `reviewed:` stamp (within `ttl:` days, else SNOOZE_DEFAULT_DAYS) suppresses staleness."""
    try:
        rdate = datetime.strptime(fm.get("reviewed", "")[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    ttl = fm.get("ttl", "")
    ttl_days = int(ttl) if ttl.isdigit() else SNOOZE_DEFAULT_DAYS
    return (now - rdate).total_seconds() / 86400.0 <= ttl_days

def _strip_protected(s):
    # Remove [[wikilink targets]], `backtick spans`, and ](link-target) so the separator/arrow
    # checks do NOT false-positive on ' -- ' that is legitimately part of a real note name or path.
    # Display text of links is KEPT, so a ' -- ' inside [Display Title] IS still flagged.
    s = re.sub(r"\[\[[^\]]*\]\]", "", s)   # wikilink targets
    s = re.sub(r"`[^`]*`", "", s)           # backtick spans (paths/code)
    s = re.sub(r"\]\([^)]*\)", "]", s)      # markdown link targets, keep display
    return s

def caveman_lint(mem_text):
    """Deterministic index-compression + entry-shape check on the entrypoint index.
    Returns list of (lineno, kind, message). Advisory; never mutates."""
    findings = []
    for i, line in enumerate(mem_text.splitlines(), 1):
        if not line.startswith("- "):
            continue  # only list entries; headers/blockquotes exempt
        probe = _strip_protected(line)
        if " -- " in probe:
            findings.append((i, "dash-sep", "use ' - ' not ' -- '"))
        if " -> " in probe:
            findings.append((i, "arrow", "use ' > ' not ' -> '"))
        if len(line) > CAVEMAN_MAX_ENTRY_CHARS:
            findings.append((i, "long", f"{len(line)} chars > {CAVEMAN_MAX_ENTRY_CHARS}; compress"))
    return findings

# --- R14: deterministic candidate detection. A cheap pre-filter that narrows the LLM's (or a human's)
# read set from the whole store to a handful; the same deterministic-first + gated-judgment shape as the
# R9 tag fuzzy-gate, on memory FILES instead of tags. These are CANDIDATES, never verdicts.
_STOP_TOKENS = {"feedback", "reference", "project", "archive", "note", "the", "and", "for", "with"}
_STANCE_PAIRS = [("always", "never"), ("must", "forbidden"), ("prefer", "avoid"),
                 ("enable", "disable"), ("required", "prohibited"), ("keep", "remove"),
                 ("allow", "block"), ("include", "exclude")]


def _stem_tokens(fn):
    return {t for t in re.split(r"[-_]", fn[:-3]) if len(t) > 2} - _STOP_TOKENS


def _candidates(files):
    """Deterministic MERGE + CONTRADICTION candidate pairs over the memory store.

    MERGE: filename-stem token overlap (>=2 shared discriminating tokens) or a shared
    `originSessionId` (two notes born of the same session). CONTRADICTION: feedback-rule pairs that
    share a domain keyword AND carry opposite stance words (always/never, prefer/avoid, ...). Both are
    narrowing pre-filters; the residue goes to a gated judge, not straight to an apply.
    """
    names = [n for n in files if n != "MEMORY.md" and not n.startswith("archive-")]
    toks = {n: _stem_tokens(n) for n in names}
    sess = {n: _frontmatter(files[n]["text"]).get("originsessionid", "") for n in names}

    merge = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            signals = {}
            shared = sorted(toks[a] & toks[b])
            if len(shared) >= 2:
                signals["stem_overlap"] = shared
            if sess[a] and sess[a] == sess[b]:
                signals["same_session"] = sess[a][:12]
            if signals:
                merge.append({"a": a, "b": b, "signals": signals})

    def _stances(text):
        low = text.lower()
        out = set()
        for pos, neg in _STANCE_PAIRS:
            if re.search(rf"\b{re.escape(pos)}\b", low):
                out.add(pos)
            if re.search(rf"\b{re.escape(neg)}\b", low):
                out.add(neg)
        return out

    feedbacks = [n for n in names if n.startswith("feedback") or files[n].get("type") == "feedback"]
    contra = []
    for i, a in enumerate(feedbacks):
        for b in feedbacks[i + 1:]:
            shared = sorted(toks[a] & toks[b])
            if not shared:
                continue
            sa, sb = _stances(files[a]["text"]), _stances(files[b]["text"])
            opp = [f"{pos}/{neg}" for pos, neg in _STANCE_PAIRS
                   if (pos in sa and neg in sb) or (neg in sa and pos in sb)]
            if opp:
                contra.append({"a": a, "b": b, "shared_keywords": shared, "opposite_stances": opp})

    return {"merge_candidates": merge, "contradiction_candidates": contra}


def parse_args():
    today, as_json, check, terse, lint, candidates = None, False, False, False, False, False
    for a in sys.argv[1:]:
        if a == "--json": as_json = True
        elif a == "--check": check = True
        elif a == "--terse": terse = True
        elif a == "--lint": lint = True
        elif a == "--candidates": candidates = True
    if "--today" in sys.argv:
        i = sys.argv.index("--today")
        if i + 1 < len(sys.argv): today = sys.argv[i+1]
    return today, as_json, check, terse, lint, candidates

def main():
    for _s in (sys.stdout, sys.stderr):            # cross-platform UTF-8 (Windows defaults cp1252)
        try: _s.reconfigure(encoding="utf-8")
        except Exception: pass
    today_str, as_json, check, terse, lint, candidates = parse_args()
    # Graceful no-op if the memory store is unset/missing (avoids an os.listdir traceback in --terse/
    # --check/hook contexts). Preserves behaviour when the dir exists.
    if not os.path.isdir(MEM_DIR):
        print(f"memory: CLAUDE_MEMORY_DIR not set or not found ({MEM_DIR}); nothing to audit.")
        sys.exit(0)
    now = (datetime.strptime(today_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
           if today_str else datetime.now(timezone.utc))

    # ---- gather memory files (top-level only; _shared is its own repo) ----
    # META_EXCLUDE: repo-meta, not memories (don't count as orphans/stale).
    META_EXCLUDE = {"README.md"}
    files = {}  # name -> {path, text, mtime_days, refs_out, base_weight}
    for fn in sorted(os.listdir(MEM_DIR)):
        if not fn.endswith(".md"): continue
        if fn in META_EXCLUDE: continue
        p = os.path.join(MEM_DIR, fn)
        if not os.path.isfile(p): continue
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            text = ""
        mtime = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc)
        days = max(0.0, (now - mtime).total_seconds() / 86400.0)
        # base_weight escape hatch = an EMOJI-tagged marker matched on a WORD BOUNDARY (so "higher"/
        # "highlight"/casual "permanent" prose do not trigger it): require the emoji AND the whole word.
        if "⚠️" in text and re.search(r"\bPERMANENT\b", text):
            bw = 2.0
        elif "🔥" in text and re.search(r"\bHIGH\b", text):
            bw = 1.5
        else:
            bw = 1.0
        fm = _frontmatter(text)
        files[fn] = {"path": p, "text": text, "days": days, "base_weight": bw,
                     "type": fm.get("type", ""), "snoozed": _snoozed(fm, now)}

    names = list(files)
    if candidates:                                  # R14: emit deterministic merge/contradiction candidates
        print(json.dumps(_candidates(files), indent=2, ensure_ascii=False))
        sys.exit(0)
    index_files = ["MEMORY.md"] + [f for f in names if f.startswith("archive-")]
    index_text = "\n".join(files[f]["text"] for f in index_files if f in files)

    # ---- reference counting ----
    # A wikilink to `stem` in ANY form: [[stem]], [[stem|alias]], [[stem#heading]], [[stem\|alias]].
    def ref_pat(stem):
        return re.compile(r"\[\[" + re.escape(stem) + r"(?:[|#\\][^\]]*)?\]\]")
    # referenced-in-index: appears as (name.md), any [[stem...]] link form, OR a bare full-filename
    # mention (e.g. "companion: aa-docx-workflow.md" prose) in MEMORY.md or any archive-*.md.
    def referenced_in(text, fn):
        stem = fn[:-3]
        return (f"({fn})" in text) or bool(ref_pat(stem).search(text)) or (fn in text)
    referenced_index = {fn for fn in names if referenced_in(index_text, fn)}

    # inbound reference_count across the WHOLE corpus (for the forgetting curve), excluding self.
    # Counts (fn) plus every [[stem...]] link form (alias/heading/escaped-pipe); undercounting here
    # would shorten the half-life and overstate staleness.
    def inbound(fn):
        stem = fn[:-3]; pat = ref_pat(stem); c = 0
        for other in names:
            if other == fn: continue
            t = files[other]["text"]
            c += t.count(f"({fn})") + len(pat.findall(t))
        return c

    # outbound links present? ([[...]] OR a (path/file.md) ref, any case / subdir)
    link_re = re.compile(r"\[\[[^\]]+\]\]|\([A-Za-z0-9_][\w./-]*\.md\)")
    def has_outbound(fn):
        return bool(link_re.search(files[fn]["text"]))

    # ---- per-file metrics ----
    rows = []
    for fn in names:
        if fn == "MEMORY.md": continue
        rc = inbound(fn)
        base = TYPE_HALFLIFE.get(files[fn]["type"].lower(), 90)
        half_life = base * (1 + math.log2(rc + 1))   # base 90 == prior 90 + 90*log2(rc+1)
        recency = math.exp(-files[fn]["days"] / half_life)
        importance = recency * files[fn]["base_weight"]
        rows.append({
            "file": fn, "refs": rc, "days": round(files[fn]["days"]),
            "importance": round(importance, 3),
            "referenced_in_index": fn in referenced_index,
            "is_archive": fn.startswith("archive-"),
            "outbound": has_outbound(fn),
            "note_type": files[fn]["type"], "snoozed": files[fn]["snoozed"],
        })

    # ---- categories ----
    orphans = [r["file"] for r in rows
               if not r["referenced_in_index"] and not r["is_archive"]]
    # broken links in MEMORY.md
    mem_text = files["MEMORY.md"]["text"]
    broken = []
    for m in re.finditer(r"\(([A-Za-z0-9_][\w./-]*\.md)\)", mem_text):   # any case / underscore-lead / subdir
        ref = m.group(1)
        if ref not in names and ref not in META_EXCLUDE and not ref.startswith("_shared"):
            broken.append(ref)
    broken = sorted(set(broken))
    stale = [r for r in rows if r["importance"] < STALE_THRESHOLD
             and not r["referenced_in_index"] and not r["snoozed"]]
    snoozed = [r["file"] for r in rows if r["snoozed"]]
    dead_ends = [r for r in rows if not r["outbound"] and r["refs"] == 0
                 and not r["is_archive"]]
    underscored = [fn for fn in names
                   if re.match(r"(feedback|project|reference)_", fn)]

    # ---- 5-metric health score ----
    total = len([r for r in rows])
    inbox_n = -1
    if INBOX_DIR and os.path.isdir(INBOX_DIR):
        try:
            inbox_n = len([f for f in os.listdir(INBOX_DIR)
                           if os.path.isfile(os.path.join(INBOX_DIR, f))])
        except Exception:
            inbox_n = -1
    inbox_pressure = (inbox_n / 25.0) if inbox_n >= 0 else None
    stale_frac = len(stale) / total if total else 0
    dead_frac = len(dead_ends) / total if total else 0
    def band(v, g, y):
        return "GREEN" if v < g else ("YELLOW" if v <= y else "RED")
    score = {
        "inbox_pressure": (round(inbox_pressure, 2) if inbox_pressure is not None else "n/a",
                           band(inbox_pressure, 0.4, 1.0) if inbox_pressure is not None else "n/a"),
        "orphan_count": (len(orphans), band(len(orphans), 1, 3)),
        "broken_links": (len(broken), band(len(broken), 1, 2)),
        "stale_fraction": (round(stale_frac, 3), band(stale_frac, 0.05, 0.15)),
        "dead_end_fraction": (round(dead_frac, 3), band(dead_frac, 0.10, 0.25)),
    }
    mem_lines = mem_text.count("\n") + 1

    # ---- Phase E proximity (active vault notes) ----
    excluded = ("00 - Inbox", "Sources", "08 - Archive", "10 - Attachments", ".obsidian", ".git", ".claude")
    active_notes = -1
    for root, dirs, fs in (os.walk(VAULT_ROOT) if (VAULT_ROOT and os.path.isdir(VAULT_ROOT)) else []):
        if active_notes < 0: active_notes = 0
        rel = os.path.relpath(root, VAULT_ROOT)
        if any(rel == e or rel.startswith(e + os.sep) for e in excluded):
            dirs[:] = []
            continue
        active_notes += sum(1 for f in fs if f.endswith(".md"))

    result = {
        "memory_lines": mem_lines, "memory_limit": MEMORY_LINE_LIMIT,
        "total_memory_files": total,
        "score": score,
        "orphans": orphans,
        "broken_links": broken,
        "stale": sorted(stale, key=lambda r: r["importance"])[:40],
        "dead_ends": sorted(dead_ends, key=lambda r: r["importance"]),
        "underscored": underscored,
        "snoozed": snoozed,
        "active_vault_notes": active_notes,
        "heaviest_files": sorted(
            ({"file": fn, "chars": len(files[fn]["text"])} for fn in names if fn != "MEMORY.md"),
            key=lambda x: -x["chars"])[:10],
        "lowest_importance": sorted(rows, key=lambda r: r["importance"])[:25],
    }

    mem_bytes = len(mem_text.encode("utf-8"))
    defects = len(broken) + len(orphans)
    if terse:
        flag = "OK" if (mem_bytes <= BYTES_BUDGET and defects == 0) else "REVIEW"
        print(f"memory: MEMORY.md {mem_bytes//1024}KB/{mem_lines}L (budget {BYTES_BUDGET//1024}KB) "
              f"| orphans {len(orphans)} broken {len(broken)} stale {len(stale)} [{flag}]")
        return
    if check:
        # hard defects block the commit; size over budget warns only (legitimate growth)
        if defects:
            print(f"MEMORY DISCIPLINE FAIL: {len(broken)} broken-links, {len(orphans)} orphans "
                  f"(run: python scripts/memory-consolidate.py)")
            sys.exit(1)
        if mem_bytes > BYTES_BUDGET:
            print(f"memory WARN: MEMORY.md {mem_bytes//1024}KB > 25KB harness cap (TRUNCATING) "
                  f"- run consolidation (not blocking)")
        else:
            print(f"memory OK: {mem_bytes//1024}KB, 0 defects")
        sys.exit(0)

    if lint:
        # ADVISORY index-compression + health + cap check (R11). Never blocks: exit 0.
        issues = caveman_lint(mem_text)
        caps = []
        if mem_lines > LINE_CAP:      caps.append(f"{mem_lines} lines > {LINE_CAP} HARD CAP (TRUNCATING)")
        elif mem_lines > LINE_TARGET: caps.append(f"{mem_lines} lines > {LINE_TARGET} headroom target")
        if mem_bytes > BYTES_CAP:      caps.append(f"{mem_bytes//1024}KB > 25KB HARD CAP (TRUNCATING)")
        elif mem_bytes > BYTES_TARGET: caps.append(f"{mem_bytes//1024}KB > 17.5KB headroom target")
        if defects: caps.append(f"{len(broken)} broken-links, {len(orphans)} orphans")
        if not caps and not issues:
            print(f"memory-lint OK: {mem_lines}L/{mem_bytes//1024}KB, caveman-clean, 0 defects")
            sys.exit(0)
        print("memory-lint (advisory - not blocking):")
        for m in caps:
            print(f"  CAP   {m}")
        for ln, kind, msg in issues[:25]:
            print(f"  L{ln:<4} {kind:<9} {msg}")
        if len(issues) > 25:
            print(f"  ... +{len(issues)-25} more caveman findings")
        sys.exit(0)

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False)); return

    # ---- human report ----
    def b(v): return f"[{v[1]}]"
    print(f"MEMORY.md size : {mem_lines} lines (limit {MEMORY_LINE_LIMIT}) "
          f"[{'OK' if mem_lines<=MEMORY_LINE_LIMIT else 'OVER'}]")
    print(f"Memory files   : {total}")
    print("--- 5-metric health score ---")
    print(f"  inbox-pressure   : {score['inbox_pressure'][0]} {b(score['inbox_pressure'])}")
    print(f"  orphan-count     : {score['orphan_count'][0]} {b(score['orphan_count'])}")
    print(f"  broken-links     : {score['broken_links'][0]} {b(score['broken_links'])}")
    print(f"  stale-fraction   : {score['stale_fraction'][0]} {b(score['stale_fraction'])}")
    print(f"  dead-end-fraction: {score['dead_end_fraction'][0]} {b(score['dead_end_fraction'])}")
    print(f"Phase E proximity: {active_notes} / 5000 active vault notes "
          f"({round(active_notes/5000*100)}%)")
    print(f"\nOrphans ({len(orphans)}): " + (", ".join(orphans) if orphans else "none"))
    print(f"Broken links ({len(broken)}): " + (", ".join(broken) if broken else "none"))
    print(f"Underscored filenames ({len(underscored)}): " +
          (", ".join(underscored) if underscored else "none"))
    if snoozed:
        print(f"Snoozed (recent reviewed:/ttl: -- excluded from stale) ({len(snoozed)}): " + ", ".join(snoozed))
    print(f"\nStale (importance<{STALE_THRESHOLD} AND unreferenced) -- {len(stale)}:")
    for r in result["stale"]:
        print(f"  {r['importance']:.3f}  {r['days']:>4}d  refs={r['refs']}  {r['file']}")
    print(f"\nDead-ends (no outbound + 0 inbound) -- {len(dead_ends)}:")
    for r in result["dead_ends"][:20]:
        print(f"  {r['importance']:.3f}  {r['file']}")
    print("\nHeaviest memory files (chars):")
    for r in result["heaviest_files"]:
        print(f"  {r['chars']:>6}  {r['file']}")

if __name__ == "__main__":
    main()
