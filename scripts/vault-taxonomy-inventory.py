#!/usr/bin/env python3
# @capability:  vault-taxonomy-inventory
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/vault-taxonomy-inventory.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""vault-taxonomy-inventory.py -- DETERMINISTIC inventory of vault naming / tags / frontmatter.
Grounds the taxonomy work: naming, tags, frontmatter. Read-only.

Usage: python scripts/vault-taxonomy-inventory.py [--json]
"""
import os, re, sys, json
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _vault_lib import md_files, force_utf8_stdout, FM_MAX_BYTES   # shared core
try:
    import yaml
except Exception:
    yaml = None

def frontmatter(text):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1: return None, text
    fm_raw = text[3:end].strip()
    body = text[end+4:]
    if yaml:
        if len(fm_raw.encode("utf-8", "replace")) > FM_MAX_BYTES:
            return {"__parse_error__": True}, body   # alias-bomb guard: skip oversized frontmatter
        try: return (yaml.safe_load(fm_raw) or {}), body
        except Exception: return {"__parse_error__": True}, body
    return {"__no_yaml__": True}, body

def main():
    force_utf8_stdout()
    as_json = "--json" in sys.argv
    total = 0
    # naming
    n_dashdash = n_emdash = n_paren = 0
    name_lens = []
    longest = []
    top_dirs = Counter()
    # frontmatter
    n_fm = n_no_fm = n_fm_err = 0
    field_freq = Counter()
    status_vals = Counter(); maturity_vals = Counter(); horizon_vals = Counter(); lang_vals = Counter()
    # tags
    fm_tag_counter = Counter()
    inline_tag_counter = Counter()

    inline_re = re.compile(r"(?:^|\s)#([A-Za-z][\w/\-]+)")
    code_fence = re.compile(r"```.*?```", re.S)

    for path, rel in md_files():
        fname = os.path.basename(path)
        total += 1
        stem = fname[:-3]
        top_dirs[rel.split(os.sep)[0] if rel else "(root)"] += 1
        if " -- " in stem: n_dashdash += 1
        if "—" in stem or "–" in stem: n_emdash += 1
        if re.search(r"\(.+\)", stem): n_paren += 1
        name_lens.append(len(stem))
        longest.append((len(stem), fname))
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        fm, body = frontmatter(text)
        if fm is None:
            n_no_fm += 1
        elif fm.get("__parse_error__"):
            n_fm_err += 1
        else:
            n_fm += 1
            for k in fm.keys():
                field_freq[k] += 1
            def vals(key, ctr):
                v = fm.get(key)
                if isinstance(v, list):
                    for x in v: ctr[str(x)] += 1
                elif v is not None: ctr[str(v)] += 1
            vals("status", status_vals); vals("maturity", maturity_vals)
            vals("horizon", horizon_vals); vals("lang", lang_vals)
            t = fm.get("tags")
            if isinstance(t, list):
                for x in t: fm_tag_counter[str(x)] += 1
            elif isinstance(t, str):
                for x in re.split(r"[,\s]+", t):
                    if x: fm_tag_counter[x] += 1
        # inline tags (strip code fences first)
        for m in inline_re.finditer(code_fence.sub("", body)):
            inline_tag_counter[m.group(1)] += 1

    # near-duplicate tag detection
    all_tags = Counter()
    for c in (fm_tag_counter, inline_tag_counter):
        for k, v in c.items(): all_tags[k] += v
    def norm(t):
        t = t.lower().replace("_", "").replace("-", "").replace("/", "")
        return t[:-1] if t.endswith("s") else t
    groups = defaultdict(list)
    for t, c in all_tags.items():
        groups[norm(t)].append((t, c))
    merge_candidates = {k: v for k, v in groups.items() if len(set(t for t, _ in v)) > 1}

    longest.sort(reverse=True)
    result = {
        "total_md": total,
        "by_top_dir": dict(top_dirs.most_common()),
        "naming": {
            "with_ -- ": n_dashdash, "with_emdash_or_endash": n_emdash,
            "with_parenthetical": n_paren,
            "avg_name_len": round(sum(name_lens)/len(name_lens), 1) if name_lens else 0,
            "max_name_len": max(name_lens) if name_lens else 0,
            "longest_10": [f"{l}: {n}" for l, n in longest[:10]],
        },
        "frontmatter": {
            "with_fm": n_fm, "no_fm": n_no_fm, "parse_errors": n_fm_err,
            "coverage_pct": round(n_fm/total*100, 1) if total else 0,
            "field_frequency": dict(field_freq.most_common()),
            "status_values": dict(status_vals.most_common()),
            "maturity_values": dict(maturity_vals.most_common()),
            "horizon_values": dict(horizon_vals.most_common()),
            "lang_values": dict(lang_vals.most_common()),
        },
        "tags": {
            "distinct_total": len(all_tags),
            "distinct_frontmatter": len(fm_tag_counter),
            "distinct_inline": len(inline_tag_counter),
            "top_30": dict(all_tags.most_common(30)),
            "merge_candidate_groups": len(merge_candidates),
            "merge_candidates": {k: sorted(v, key=lambda x:-x[1]) for k, v in
                                 sorted(merge_candidates.items(), key=lambda kv:-sum(c for _,c in kv[1]))[:25]},
        },
    }
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False)); return

    n = result["naming"]; f = result["frontmatter"]; t = result["tags"]
    print(f"=== VAULT TAXONOMY INVENTORY ({total} .md files, excl attachments/substrate) ===")
    print("top dirs: " + ", ".join(f"{k}:{v}" for k,v in list(result['by_top_dir'].items())[:8]))
    print("\n-- NAMING (B1) --")
    print(f"  ' -- ' separator : {n['with_ -- ']}  | em/en-dash: {n['with_emdash_or_endash']} | parenthetical: {n['with_parenthetical']}")
    print(f"  name length avg {n['avg_name_len']} / max {n['max_name_len']}")
    print("  longest: " + " | ".join(n["longest_10"][:4]))
    print("\n-- FRONTMATTER (B3) --")
    print(f"  coverage {f['coverage_pct']}% ({f['with_fm']} with / {f['no_fm']} without / {f['parse_errors']} parse-err)")
    print("  fields (freq): " + ", ".join(f"{k}={v}" for k,v in list(f['field_frequency'].items())[:20]))
    print(f"  status values: {f['status_values']}")
    print(f"  maturity values: {f['maturity_values']}")
    print(f"  horizon values: {f['horizon_values']}")
    print(f"  lang values: {f['lang_values']}")
    print("\n-- TAGS (B2) --")
    print(f"  distinct {t['distinct_total']} (fm {t['distinct_frontmatter']} / inline {t['distinct_inline']}) | merge-candidate groups: {t['merge_candidate_groups']}")
    print("  top: " + ", ".join(f"{k}({v})" for k,v in list(t['top_30'].items())[:15]))
    print("  merge candidates (normalized -> variants):")
    for k, v in list(t["merge_candidates"].items())[:15]:
        print(f"    {k}: " + " / ".join(f"{tag}({c})" for tag,c in v))

if __name__ == "__main__":
    main()
