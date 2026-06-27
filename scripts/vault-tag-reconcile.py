#!/usr/bin/env python3
# @capability:  tag-reconcile
# @compute:     deterministic
# @effect:      mutating
# @engine:      scripts/vault-tag-reconcile.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   attended-exempt (optional VAULT_FORBIDDEN_ZONES)
# @audit:       git
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Deterministic tag reconciliation.

Detects MORPHOLOGICAL merge groups -- case / plural / hyphen / underscore / slash variants of one root
(e.g. source/sources, red-team/redteam, SIAM/siam, project/projects) -- and proposes the KEBAB-CASE
variant as canonical (lowercase + hyphen-separated; ties broken by count). EXCLUDE_NORMS holds known
semantic false-positives (PACS != PAC). True SYNONYMS (e.g. car<->automobile) do NOT normalise together
and are out of scope for auto-detection (supply a --synonyms map for those, operator-curated).

NB on apply: prefer Tag Wrangler for the actual rename/merge -- it uses Obsidian's own parse engine
(no linter-race, updates all usages incl. child tags). This engine's --apply is the fallback (guarded
regex bulk write); the proposal feeds either path.
  Tag Wrangler -- pjeby, MIT licence -- https://github.com/pjeby/tag-wrangler

Read-only proposal by default. `--apply` is a MUTATING bulk vault write: it rewrites frontmatter `tags:`
and inline `#tags`, guarded by assert_obsidian_closed() (the linter-race) -- run it deliberately
(Obsidian closed) = the operator confirmation. git is the audit.

Usage: python scripts/vault-tag-reconcile.py [--json] [--apply] [--force]
"""
import os, re, sys, json
from collections import defaultdict, Counter
try:
    import yaml
except Exception:
    yaml = None
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from _vault_guard import assert_obsidian_closed
except Exception:
    def assert_obsidian_closed(force=False): pass

from _vault_lib import (VAULT, md_files, safe_write, VaultWriteError,   # shared core
                        in_forbidden_zone, force_utf8_stdout, FM_MAX_BYTES)
INLINE = re.compile(r"(?:^|\s)#([A-Za-z][\w/\-]+)")
FENCE = re.compile(r"```.*?```", re.S)

def norm(t):
    t = t.lower().lstrip("#").replace("_", "").replace("-", "").replace("/", "")
    # strip a trailing plural 's' ONLY if >=3 chars remain -> avoids false merges of short codes
    # (CIS->ci would collide with CI; OPS->op with OP). EXCLUDE_NORMS guards semantic dupes (PAC/PACS).
    return t[:-1] if (t.endswith("s") and len(t) >= 4) else t

# Known SEMANTIC false-positives -- distinct concepts that share a normalized stem; never auto-merge.
# Curate here as they surface (the morphological heuristic cannot tell an acronym ending in 's' from a
# plural). pac!=pacs ; bms!=bmss (BMSS is a unit, not the plural of BMS).
EXCLUDE_NORMS = {"pac", "bms"}

def kebab_rank(t):
    """Higher = more kebab-case (canonical preference: lowercase + hyphen-separated)."""
    r = 2 if t == t.lower() else 0
    if "-" in t and "_" not in t and "/" not in t: r += 1
    return r

def fm_tags(text):
    if not text.startswith("---"): return []
    end = text.find("\n---", 3)
    if end == -1 or not yaml: return []
    block = text[3:end]
    if len(block.encode("utf-8", "replace")) > FM_MAX_BYTES: return []   # alias-bomb guard: skip oversized fm
    try: fm = yaml.safe_load(block) or {}
    except Exception: return []
    t = fm.get("tags")
    if isinstance(t, list): return [str(x) for x in t]
    if isinstance(t, str): return [x for x in re.split(r"[,\s]+", t) if x]
    return []

def collect():
    counts = Counter(); files_by_tag = defaultdict(set)
    for p, _ in md_files():
        try: text = open(p, encoding="utf-8", errors="replace").read()
        except Exception: continue
        tags = set(fm_tags(text))
        body = text.split("\n---", 1)[-1] if text.startswith("---") else text
        for m in INLINE.finditer(FENCE.sub("", body)): tags.add(m.group(1))
        for t in tags:
            counts[t] += 1; files_by_tag[t].add(p)
    return counts, files_by_tag

def proposals(counts):
    groups = defaultdict(list)
    for t, n in counts.items(): groups[norm(t)].append((t, n))
    out = []
    for k, variants in groups.items():
        distinct = {t for t, _ in variants}
        if len(distinct) < 2 or k in EXCLUDE_NORMS: continue
        variants.sort(key=lambda x: (-kebab_rank(x[0]), -x[1]))  # kebab canonical, then count
        canonical = variants[0][0]
        merges = [(t, n) for t, n in variants if t != canonical]
        out.append({"canonical": canonical, "merge": merges,
                    "affected": sum(n for _, n in merges)})
    out.sort(key=lambda g: -g["affected"])
    return out

def main():
    force_utf8_stdout()
    args = sys.argv[1:]
    counts, files_by_tag = collect()
    props = proposals(counts)
    if "--json" in args:
        print(json.dumps({"distinct_tags": len(counts), "merge_groups": len(props),
                          "proposals": props}, indent=2, ensure_ascii=False)); return
    if "--apply" not in args:
        print(f"=== TAG RECONCILE (proposal) -- {len(counts)} distinct tags, {len(props)} merge groups ===")
        print("(read-only; pass --apply to rewrite, Obsidian closed)\n")
        for g in props:
            print(f"  {g['canonical']:28} <- " + ", ".join(f"{t}({n})" for t, n in g["merge"])
                  + f"   [{g['affected']} note-uses]")
        return
    # --apply : mutating bulk write
    assert_obsidian_closed("--force" in args)
    remap = {}
    for g in props:
        for t, _ in g["merge"]: remap[t] = g["canonical"]
    changed = 0
    for p in set().union(*[files_by_tag[t] for t in remap]) if remap else []:
        if in_forbidden_zone(os.path.dirname(os.path.relpath(p, VAULT))): continue   # never write these
        try: text = open(p, encoding="utf-8", newline="").read()       # newline='' preserves CRLF/LF
        except (UnicodeDecodeError, OSError): continue                  # skip unreadable (no replace-then-write)
        orig = text
        for old, new in remap.items():
            text = re.sub(r"(?m)(^|\s|\[|,|\")#" + re.escape(old) + r"(?=$|[\s,\]\"])",
                          lambda m: m.group(1) + "#" + new, text)   # inline
            text = re.sub(r"(?m)(^\s*-\s*|\[\s*|,\s*)" + re.escape(old) + r"(?=\s*[,\]\n])",
                          lambda m: m.group(1) + new, text)          # frontmatter list items
        if text != orig:
            try:
                safe_write(p, text); changed += 1                       # symlink/out-of-vault writes refused
            except VaultWriteError as e:
                print(f"  skip (guard): {e}", file=sys.stderr)
    print(f"applied {len(remap)} tag merges across {changed} files")

if __name__ == "__main__":
    main()
