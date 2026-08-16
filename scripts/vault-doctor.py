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
    # An external engine is named by absolute path; a built-in by filename relative to HERE.
    script = engine if os.path.isabs(engine) else os.path.join(HERE, engine)
    if not os.path.isfile(script):
        # Checked BEFORE running, because the interpreter exits 2 when it cannot open a script and
        # 2 already means NOT CONFIGURED. A missing engine therefore reported as a tidy skip, with
        # the whole subject unexamined and the roll-up green. Reported as an error instead.
        return -1, "", f"engine file not found: {script}"
    r = subprocess.run([sys.executable, script, *eargs], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _rejected_our_flags(stderr):
    """Did the engine exit 2 because it could not parse --check/--json, rather than as a skip?

    Deliberately narrow. A false positive turns a legitimate skip into a reported error, so this
    matches only the shapes an argument parser produces when it refuses a flag.
    """
    s = (stderr or "").lower()
    return ("unrecognized argument" in s or "unrecognised argument" in s
            or "no such option" in s or "invalid choice" in s
            or ("usage:" in s and "error:" in s))


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


def _substrate_summary(root):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _substrate import probe
        d = probe(root)
        return {"metadata_reliable": d["metadata_reliable"], "sync_marker": d["sync_marker"],
                "placeholders": d["placeholders"], "note": d["note"]}
    except Exception as e:
        return {"metadata_reliable": None, "note": f"substrate probe unavailable: {e}"}


def main():
    args = sys.argv[1:]
    as_json, check, strict = "--json" in args, "--check" in args, "--strict" in args
    staged = "--staged" in args
    since = None
    if "--since" in args:
        i = args.index("--since")
        if i + 1 < len(args) and not args[i + 1].startswith("-"):
            since = args[i + 1]

    mem = os.environ.get("CLAUDE_MEMORY_DIR", "")
    # Configured-but-wrong is NOT the same as not-configured. Testing isdir() here made a
    # mistyped or moved store look like an unused feature: doctor skipped it, said 'required
    # config not set', and rolled up OK. If a store was named at all, run the engine and let
    # it speak (it exits 3 for a configured store it cannot reach).
    has_mem = bool(mem)
    has_schema = bool(os.environ.get("FRONTMATTER_SCHEMA"))

    # name, engine file, args, gates(can fail roll-up), applicable
    plan = [
        ("taxonomy-inventory", "vault-taxonomy-inventory.py", ["--json"], False, True),
        ("ref-audit", "vault-ref-audit.py", ["--check", "--json"] + (["--strict"] if strict else [])
         + (["--since", since] if since else []) + (["--staged"] if staged else []), True, True),
        ("frontmatter-lint", "vault-frontmatter-lint.py", ["--check", "--json"], False, has_schema),
        ("memory-consolidate", "memory-consolidate.py", ["--check"], True, has_mem),
    ]

    # Engines from elsewhere that opted in with a `@doctor:` header. They run LAST and are listed
    # separately in the report: an operator reading a health summary is entitled to know which
    # findings came from this project's engines and which came from someone else's. Their file path
    # is absolute, so _run's join against HERE is bypassed on purpose.
    external = []
    try:
        from _engine_path import doctor_participants
        external = doctor_participants()
    except SystemExit:
        raise
    except Exception:
        external = []
    # Invoked exactly as a built-in is: --check asserts read-only, --json carries counts into the
    # report. This is a stated condition of declaring @doctor, not a guess about someone's CLI.
    # The trap it opens is closed below: argparse exits 2 on an unrecognised flag, and 2 means
    # NOT CONFIGURED, so an engine that ignored the contract would be reported as a tidy skip.
    plan += [(name, path, ["--check", "--json"], gates, True) for name, path, gates in external]
    external_names = {name for name, _p, _g in external}

    results, failed, scan_count, t0 = [], [], None, time.perf_counter()
    for name, engine, eargs, gates, applicable in plan:
        if not applicable:
            results.append({"engine": name, "state": "skipped", "reason": "required config not set",
                            "origin": ("external" if name in external_names else "built-in")})
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
        elif rc == 2 and name in external_names and _rejected_our_flags(err):
            # argparse also exits 2 for an unrecognised flag, which collides with NOT CONFIGURED.
            # Left alone, an engine that never implemented --check would be reported as a tidy skip
            # and its whole subject would go unchecked while the roll-up stayed green.
            state = "error"; failed.append(name)
            err = (err + "\n" if err else "") + (
                "doctor invokes participants with '--check --json' and this engine rejected them. "
                "Implement both flags, or drop the '@doctor:' header. Reported as an error rather "
                "than a skip because exit 2 would otherwise read as 'not configured'.")
        elif rc == 2:
            state = "skipped"             # NOT CONFIGURED (e.g. schema absent) -> not a health failure
        elif rc == 3:
            # UNREACHABLE: the engine was configured and could not read its subject. Distinct from
            # 2 on purpose: this one is a real defect, and skipping it is how a broken check stays
            # invisible. Fails the roll-up whether or not the engine is a gate.
            state = "error"; failed.append(name)
        elif gates and rc == 1:
            state = "fail"; failed.append(name)
        elif rc == 1 and name in external_names:
            # Declared advisory, exited 1. Reported as a contract breach rather than quietly
            # downgraded to 'ok': the alternative is that an engine's only way of saying something
            # is wrong gets swallowed by the level it declared for itself.
            state = "error"; failed.append(name)
            err = (err + "\n" if err else "") + (
                "declared '@doctor: advisory' but exited 1. Advisory engines report and exit 0; "
                "exit 1 means a gate failed. Declare '@doctor: gate' or return 0.")
        else:
            state = "error"; failed.append(name)
        results.append({
            "engine": name, "state": state, "exit": rc,
            "origin": ("external" if name in external_names else "built-in"),
            "summary": (data.get("counts") if isinstance(data, dict) and "counts" in data else None),
            "stderr": (err.strip()[:200] if state == "error" else None),
        })

    # Run-receipt: what this run actually did, so a wrong root / 0-file scan is loud, not silently green.
    scanned_root = os.path.abspath(os.path.expanduser(os.environ.get("VAULT_ROOT") or "."))
    receipt = {
        "tool": "neurokeeper", "version": _version(),
        "root": scanned_root,
        "files_scanned": scan_count,
        "engines_run": [r["engine"] for r in results if r["state"] != "skipped"],
        "duration_ms": round((time.perf_counter() - t0) * 1000),
        # Name the substrate once per run. The receipt already proves WHICH root was scanned and how
        # many files; this is the other half, whether the filesystem's answers about those files can
        # be trusted at all.
        "substrate": _substrate_summary(scanned_root),
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
