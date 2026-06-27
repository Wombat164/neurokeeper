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

Usage: python scripts/memory-consolidate.py [--json] [--today YYYY-MM-DD]
"""
import os, re, sys, json, math
from datetime import datetime, timezone

MEM_DIR = os.environ.get("CLAUDE_MEMORY_DIR") or os.path.expanduser("~/.claude/memory")
INBOX_DIR = os.environ.get("VAULT_INBOX_DIR", "")   # optional: inbox-pressure metric (skipped if unset)
VAULT_ROOT = os.environ.get("VAULT_ROOT", "")        # optional: Phase-E vault-note count (skipped if unset)
STALE_THRESHOLD = 0.15
MEMORY_LINE_LIMIT = 180
BYTES_BUDGET = 45000  # soft load-budget: over this, MEMORY.md likely partial-loads (tunable)

def parse_args():
    today, as_json, check, terse = None, False, False, False
    for a in sys.argv[1:]:
        if a == "--json": as_json = True
        elif a == "--check": check = True
        elif a == "--terse": terse = True
    if "--today" in sys.argv:
        i = sys.argv.index("--today")
        if i + 1 < len(sys.argv): today = sys.argv[i+1]
    return today, as_json, check, terse

def main():
    for _s in (sys.stdout, sys.stderr):            # cross-platform UTF-8 (Windows defaults cp1252)
        try: _s.reconfigure(encoding="utf-8")
        except Exception: pass
    today_str, as_json, check, terse = parse_args()
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
        files[fn] = {"path": p, "text": text, "days": days, "base_weight": bw}

    names = list(files)
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
        half_life = 90 + 90 * math.log2(rc + 1)
        recency = math.exp(-files[fn]["days"] / half_life)
        importance = recency * files[fn]["base_weight"]
        rows.append({
            "file": fn, "refs": rc, "days": round(files[fn]["days"]),
            "importance": round(importance, 3),
            "referenced_in_index": fn in referenced_index,
            "is_archive": fn.startswith("archive-"),
            "outbound": has_outbound(fn),
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
             and not r["referenced_in_index"]]
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
            print(f"memory WARN: MEMORY.md {mem_bytes//1024}KB > budget {BYTES_BUDGET//1024}KB "
                  f"-- consider /vault-memory-audit --consolidate (not blocking)")
        else:
            print(f"memory OK: {mem_bytes//1024}KB, 0 defects")
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
