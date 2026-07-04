#!/usr/bin/env python3
# @capability:  frontmatter-fix
# @compute:     deterministic
# @effect:      mutating
# @engine:      scripts/vault-frontmatter-fix.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   attended-exempt (optional VAULT_FORBIDDEN_ZONES)
# @audit:       git
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Deterministic frontmatter reconciliation. Applies the schema maps via SURGICAL
line-edits on the frontmatter block (no YAML reparse -> preserves formatting/order):
  - status off-vocab -> canonical (schema state.status.map); maturity-misused values move to maturity:
  - horizon off-vocab -> canonical (schema state.horizon.map)
  - redundant `date:` dropped ONLY where it equals `created:` (canonical = created/updated); date != created
    is LEFT + flagged (may be a meaningful content date)
Read-only dry-run by default. --apply is mutating (assert_obsidian_closed guard) + git audit.
Usage: python scripts/vault-frontmatter-fix.py [--apply] [--force] [--json] [--dates] [--audit-log <file>]
  --audit-log <file> : on --apply, append a tamper-evident record of the batch to a hash-chained log
                       (scripts/_audit.py), on top of the git diff. Verifiable with _audit.verify().
"""
import os, re, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import yaml
except Exception:
    yaml = None
try:
    from _vault_guard import assert_obsidian_closed
except Exception:
    def assert_obsidian_closed(force=False): pass

from _vault_lib import (VAULT, md_files, safe_write, VaultWriteError,   # shared core
                        in_forbidden_zone, force_utf8_stdout)
from _audit import append as _audit_append  # noqa: E402  (reusable hash-chained audit substrate)
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

def kv(line):
    m = re.match(r"^([A-Za-z0-9_\-]+):\s*(.*?)\s*$", line)
    return (m.group(1), m.group(2)) if m else (None, None)

def main():
    force_utf8_stdout()
    args = sys.argv[1:]
    if not yaml: print("PyYAML required", file=sys.stderr); sys.exit(2)
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
    st = sc["state"]["status"]; status_vals = set(st["values"]); status_map = st.get("map", {})
    outbox_vals = set(st.get("outbox_values", []))
    hz_map = sc["state"]["horizon"].get("map", {})
    stats = {"status_remap": 0, "maturity_move": 0, "horizon_remap": 0, "date_dropped": 0,
             "date_kept_diff": 0, "files_changed": 0}
    samples = []
    apply = "--apply" in args
    do_dates = "--dates" in args   # date-dedup is opt-in (ripples into dataview queries + templates)
    audit_log = None
    if "--audit-log" in args:
        i = args.index("--audit-log")
        if i + 1 < len(args) and not args[i + 1].startswith("-"):
            audit_log = args[i + 1]
    if apply: assert_obsidian_closed("--force" in args)

    for p, rel in md_files():
        if in_forbidden_zone(rel): continue   # VAULT_FORBIDDEN_ZONES: never touch these files
        try: text = open(p, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError): continue   # skip unreadable (no replace-then-write corruption)
        if not text.startswith("---"): continue
        end = text.find("\n---", 3)
        if end == -1: continue
        head, body = text[3:end], text[end:]
        lines = head.split("\n")
        kvs = dict(kv(l) for l in lines if kv(l)[0])
        nt = kvs.get("note_type", "")
        # outbox status (pending/sent/void) is valid -> exempt. Derive outbox from note_type OR the PATH,
        # so a not-yet-typed outbox note isn't corrupted (pending->draft) by an early run (order-independence).
        plnorm = p.replace(os.sep, "/")
        is_outbox = nt == "outbox" or "/11 - Outbox/" in plnorm or any(
            s in plnorm for s in ("/sent-mails/", "/actions/", "/deliverables/", "/mail/"))
        out = []
        for line in lines:
            k, v = kv(line)
            if k == "status" and v:
                if not (v in outbox_vals and is_outbox) and v not in status_vals and v in status_map:
                    mp = status_map[v]
                    if isinstance(mp, dict):  # maturity-misused -> set status + move value to maturity
                        out.append(re.sub(r":\s*.*$", ": " + mp["set_status"], line, count=1))
                        stats["maturity_move"] += 1
                        if "maturity" not in kvs:
                            out.append("maturity: " + mp["move_to_maturity"])
                    else:
                        out.append(re.sub(r":\s*.*$", ": " + mp, line, count=1))
                        stats["status_remap"] += 1
                    continue
            if k == "horizon" and v in hz_map:
                out.append(re.sub(r":\s*.*$", ": " + hz_map[v], line, count=1))
                stats["horizon_remap"] += 1; continue
            if do_dates and k == "date" and "created" in kvs:
                cr = str(kvs.get("created") or "")
                if re.match(r"\d{4}-\d{2}-\d{2}", v) and cr[:10] == v[:10]:
                    stats["date_dropped"] += 1; continue   # same calendar day as created -> redundant, drop
                else:
                    stats["date_kept_diff"] += 1            # genuinely different day -> keep + flag for review
            out.append(line)
        new_head = "\n".join(out)
        if new_head != head:
            stats["files_changed"] += 1
            if len(samples) < 8:
                samples.append(os.path.relpath(p, VAULT))
            if apply:
                try:
                    safe_write(p, "---" + new_head + body)   # symlink/out-of-vault writes refused
                except VaultWriteError as e:
                    print(f"  skip (guard): {e}", file=sys.stderr)

    if apply and audit_log and stats["files_changed"] > 0:   # R13: tamper-evident record of the apply
        from datetime import datetime, timezone
        _audit_append(audit_log, {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                  "engine": "frontmatter-fix", "action": "apply",
                                  "files_changed": stats["files_changed"], "files": sorted(samples)})

    if "--json" in args:
        print(json.dumps(stats, indent=2)); return
    mode = "APPLIED" if "--apply" in args else "DRY-RUN (pass --apply to write, Obsidian closed)"
    print(f"=== FRONTMATTER FIX ({mode}) ===")
    for k, v in stats.items(): print(f"  {k}: {v}")
    print("\nsample files: " + (", ".join(samples) if samples else "(none)"))

if __name__ == "__main__":
    main()
