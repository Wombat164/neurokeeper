#!/usr/bin/env python3
# @capability:  doctor
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/vault-doctor.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/adr-0002-doctor-exit-semantics.md
"""vault-doctor.py -- aggregate read-only health: run each APPLICABLE engine, print one consolidated
report, and roll up an HONEST exit code.

Tri-state per engine (ADR-0002): ok / fail / skipped. A `skipped` engine is one whose required config is
absent (e.g. frontmatter-lint without FRONTMATTER_SCHEMA, memory-consolidate without CLAUDE_MEMORY_DIR) --
it is reported as skipped, NEVER silently counted as a pass. The `--check` exit asserts "an engine ERRORED
or a real GATE failed" -- NOT "the vault is healthy": advisory engines (taxonomy-inventory, frontmatter-
lint) contribute numbers to the report but cannot fail the roll-up. Composes by subprocess (not in-process)
so each engine's own exit code + --json are the source of truth.

Usage: vault-doctor.py [--json] [--check] [--strict] [--since <git-ref>]
  --since <git-ref> : forwarded to ref-audit; narrows the reported findings (and the gate) to notes
                      changed since <git-ref>. The scan stays graph-global.
  --check  : exit 1 iff a gating engine failed or any engine errored (skips/advisory never fail).
  --strict : forwarded to ref-audit (also fail on unresolved links).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from _vault_lib import force_utf8_stdout
    force_utf8_stdout()
except Exception:
    pass


def _run(engine, eargs):
    r = subprocess.run([sys.executable, os.path.join(HERE, engine), *eargs],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _version():
    """neurokeeper version for the run-receipt: installed metadata, else pyproject, else 'unknown'."""
    try:
        from importlib.metadata import version
        return version("neurokeeper")
    except Exception:
        pass
    try:
        pp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")
        with open(pp, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if s.startswith("version") and "=" in s:
                    return s.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "unknown"


def main():
    args = sys.argv[1:]
    as_json, check, strict = "--json" in args, "--check" in args, "--strict" in args
    since = None
    if "--since" in args:
        i = args.index("--since")
        if i + 1 < len(args) and not args[i + 1].startswith("-"):
            since = args[i + 1]

    mem = os.environ.get("CLAUDE_MEMORY_DIR", "")
    has_mem = bool(mem) and os.path.isdir(os.path.expanduser(mem))
    has_schema = bool(os.environ.get("FRONTMATTER_SCHEMA"))

    # name, engine file, args, gates(can fail roll-up), applicable
    plan = [
        ("taxonomy-inventory", "vault-taxonomy-inventory.py", ["--json"], False, True),
        ("ref-audit", "vault-ref-audit.py", ["--check", "--json"] + (["--strict"] if strict else [])
         + (["--since", since] if since else []), True, True),
        ("frontmatter-lint", "vault-frontmatter-lint.py", ["--check", "--json"], False, has_schema),
        ("memory-consolidate", "memory-consolidate.py", ["--check"], True, has_mem),
    ]

    results, failed, scan_count, t0 = [], [], None, time.perf_counter()
    for name, engine, eargs, gates, applicable in plan:
        if not applicable:
            results.append({"engine": name, "state": "skipped", "reason": "required config not set"})
            continue
        rc, out, err = _run(engine, eargs)
        data = None
        if "--json" in eargs:
            try:
                data = json.loads(out)
            except Exception:
                data = None
        if isinstance(data, dict):                      # run-receipt: how many notes were actually scanned
            if name == "taxonomy-inventory" and "total_md" in data:
                scan_count = data["total_md"]
            elif scan_count is None and "files" in data:
                scan_count = data["files"]
        if rc == 0:
            state = "ok"
        elif rc == 2:
            state = "skipped"             # usage/config error (e.g. schema missing) -> not a health failure
        elif gates and rc == 1:
            state = "fail"; failed.append(name)
        else:
            state = "error"; failed.append(name)
        results.append({
            "engine": name, "state": state, "exit": rc,
            "summary": (data.get("counts") if isinstance(data, dict) and "counts" in data else None),
            "stderr": (err.strip()[:200] if state == "error" else None),
        })

    # Run-receipt: what this run actually did, so a wrong root / 0-file scan is loud, not silently green.
    receipt = {
        "tool": "neurokeeper", "version": _version(),
        "root": os.path.abspath(os.path.expanduser(os.environ.get("VAULT_ROOT") or ".")),
        "files_scanned": scan_count,
        "engines_run": [r["engine"] for r in results if r["state"] != "skipped"],
        "duration_ms": round((time.perf_counter() - t0) * 1000),
    }
    roll = {"receipt": receipt, "failed": failed, "engines": results}

    if as_json:
        print(json.dumps(roll, indent=2, ensure_ascii=False))
        sys.exit(1 if (check and failed) else 0)

    print("=== neurokeeper doctor ===")
    warn = "   <-- 0 files: check VAULT_ROOT" if receipt["files_scanned"] == 0 else ""
    print(f"root {receipt['root']} | {receipt['files_scanned']} files scanned | "
          f"neurokeeper {receipt['version']} | {receipt['duration_ms']}ms{warn}")
    marks = {"ok": "[ok]   ", "fail": "[FAIL] ", "skipped": "[skip] ", "error": "[ERROR]"}
    for r in results:
        line = f"  {marks[r['state']]} {r['engine']}"
        if r["state"] == "skipped":
            line += "  (required config not set)"
        elif r.get("summary"):
            line += "  " + ", ".join(f"{k}={v}" for k, v in r["summary"].items())
        print(line)
    print(f"\nroll-up: {'OK' if not failed else 'FAIL (' + ', '.join(failed) + ')'}")
    print("(exit asserts: an engine errored or a real gate failed -- NOT 'vault is healthy'.")
    print(" taxonomy-inventory + frontmatter-lint are informational; skipped = config absent. See ADR-0002.)")
    sys.exit(1 if (check and failed) else 0)


if __name__ == "__main__":
    main()
