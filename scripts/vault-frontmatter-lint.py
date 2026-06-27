#!/usr/bin/env python3
# @capability:  frontmatter-lint
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/vault-frontmatter-lint.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Deterministic frontmatter linter. Validates vault notes against the
L2 schema (frontmatter-schema.yaml): off-vocab values (status/maturity/horizon/lang/note_type/
sphere), missing recommended axes (note_type/sphere), date-field redundancy, unknown fields.
Read-only. --json / --terse / --check (advisory: reports, exits 0 -- tighten later when vault is clean).
Usage: python scripts/vault-frontmatter-lint.py [--json|--terse|--check] [--schema P] [--vault P]
"""
import os, re, sys, json
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _vault_lib import VAULT, md_files, parse_frontmatter, force_utf8_stdout   # shared core
try:
    import yaml
except Exception:
    yaml = None

SCHEMA = os.environ.get("FRONTMATTER_SCHEMA") or os.path.join(VAULT, ".claude/data/frontmatter-schema.yaml")
EXAMPLE_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "config.example", "frontmatter-schema.example.yaml")


def resolve_schema():
    """(path, used_example): the configured schema if present, else the bundled example, else None."""
    if os.path.isfile(SCHEMA):
        return SCHEMA, False
    if os.path.isfile(EXAMPLE_SCHEMA):
        return EXAMPLE_SCHEMA, True
    return None, False

def flatten(items):
    out = set()
    for it in items or []:
        for x in re.split(r"[,\s]+", str(it)):
            if x: out.add(x)
    return out

def main():
    force_utf8_stdout()
    args = sys.argv[1:]
    mode = ("json" if "--json" in args else "terse" if "--terse" in args
            else "check" if "--check" in args else "report")
    if not yaml:
        print("PyYAML required", file=sys.stderr); sys.exit(2)
    schema_path, used_example = resolve_schema()
    if schema_path is None:
        print(f"FRONTMATTER_SCHEMA not found (looked at: {SCHEMA}).\n"
              "Set FRONTMATTER_SCHEMA to your schema-as-code file -- copy + edit "
              "config.example/frontmatter-schema.example.yaml.", file=sys.stderr)
        sys.exit(2)
    if used_example:
        print(f"NOTE: FRONTMATTER_SCHEMA unset/missing; using the bundled example: {schema_path}",
              file=sys.stderr)
    sc = yaml.safe_load(open(schema_path, encoding="utf-8"))
    axes, state = sc.get("axes", {}), sc.get("state", {})
    nt_vals = set(axes.get("note_type", {}).get("values", []))
    sph_vals = set(axes.get("sphere", {}).get("values", []))
    vocab = {k: set(state.get(k, {}).get("values", [])) for k in ("status", "maturity", "horizon", "lang")}
    outbox_status = set(state.get("status", {}).get("outbox_values", []))
    known = flatten(sc.get("known_fields"))

    c = Counter()
    offvocab = {k: Counter() for k in ("status", "maturity", "horizon", "lang", "note_type", "sphere")}
    unknown = Counter()

    for path, rel in md_files():
        c["files"] += 1
        try: text = open(path, encoding="utf-8", errors="replace").read()
        except Exception: continue
        fm = parse_frontmatter(text)
        if fm is None: c["no_fm"] += 1; continue
        if fm.get("__parse_error__"): c["parse_err"] += 1; continue
        if "note_type" not in fm: c["missing_note_type"] += 1
        elif str(fm["note_type"]) not in nt_vals:
            c["offvocab_note_type"] += 1; offvocab["note_type"][str(fm["note_type"])] += 1
        if "sphere" not in fm: c["missing_sphere"] += 1
        else:
            for x in (fm["sphere"] if isinstance(fm["sphere"], list) else [fm["sphere"]]):
                if str(x) not in sph_vals: c["offvocab_sphere"] += 1; offvocab["sphere"][str(x)] += 1
        for key in ("status", "maturity", "horizon", "lang"):
            v = fm.get(key)
            if v is None: continue
            allowed = vocab[key] | (outbox_status if (key == "status" and fm.get("note_type") == "outbox") else set())
            for x in (v if isinstance(v, list) else [v]):
                if str(x) not in allowed:
                    c["offvocab_" + key] += 1; offvocab[key][str(x)] += 1
        # date+created coexistence is benign (2026-06-27 decision) -- not flagged
        if [k for k in fm.keys() if k not in known]:
            c["unknown_fields"] += 1
            for k in fm.keys():
                if k not in known: unknown[k] += 1

    result = {"counts": dict(c), "offvocab": {k: dict(v) for k, v in offvocab.items()},
              "unknown_fields": dict(unknown.most_common(20))}
    if mode == "json": print(json.dumps(result, indent=2, ensure_ascii=False)); return
    if mode == "terse":
        print(f"frontmatter: {c['files']} notes | missing note_type {c['missing_note_type']} / sphere "
              f"{c['missing_sphere']} | offvocab status {c['offvocab_status']}")
        return
    print(f"=== FRONTMATTER LINT ({c['files']} notes) ===")
    for k in ("no_fm","parse_err","missing_note_type","missing_sphere","offvocab_status",
              "offvocab_maturity","offvocab_horizon","offvocab_lang","offvocab_note_type",
              "offvocab_sphere","unknown_fields"):
        print(f"  {k}: {c[k]}")
    print("\noff-vocab STATUS values (-> reconcile via schema map):")
    for v, n in offvocab["status"].most_common(): print(f"  {v}: {n}")
    print("off-vocab MATURITY / HORIZON / LANG:")
    for cat in ("maturity","horizon","lang"):
        if offvocab[cat]: print(f"  {cat}: {dict(offvocab[cat])}")
    print("top UNKNOWN fields:")
    for k, n in unknown.most_common(15): print(f"  {k}: {n}")
    if mode == "check": sys.exit(0)  # advisory until the vault is reconciled

if __name__ == "__main__":
    main()
