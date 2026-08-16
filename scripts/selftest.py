#!/usr/bin/env python3
# @capability:  selftest
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/selftest.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         wiki/content/reference/index.md
"""selftest.py -- prove the detectors still detect, using planted defects.

WHY THIS EXISTS

Every serious failure in this project's own history has the same shape: a check that looked healthy
while unable to see. A byte budget set at 1.8x the real cap, so an index over the limit reported
fine. Walk-excludes that narrowed a scan until it found nothing and called that clean. An analyzer
that exited 0 when its store was missing. A release gate that never read the prose it was supposedly
keeping in sync. A vendored copy 105 lines behind upstream, reporting cheerfully. None of these
errored. All of them passed.

Unit tests catch this in CI, on the maintainer's machine, against the maintainer's fixtures. They do
not travel to the install site, where the config, the platform and the vault are all different, and
where a rule silently stops matching after an upgrade. So each detector ships a KNOWN-BAD fixture
and must find every defect planted in it, on demand, wherever it is installed.

The pattern is old and proven elsewhere: EICAR for antivirus, mutation testing for test suites,
restore-verification for backups. A detector that has never been observed to fire is indistinguishable
from one that cannot.

BOTH HALVES ARE REQUIRED

A fixture asserts must_detect AND must_not_detect. A detector that reports everything also "finds"
the planted defect, so a selftest without negative controls proves only that the engine emits
output. The clean notes in each fixture are load-bearing, not padding.

  selftest.py                # run every fixture
  selftest.py --engine ref-audit
  selftest.py --json

Exit: 0 every detector alive, 1 a detector missed a planted defect or fired on a clean one,
2 no fixtures found (nothing was proven, which is not the same as everything passing).
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "selftest"
ENGINES = ROOT / "scripts"

EXIT_OK, EXIT_FAILED, EXIT_NO_FIXTURES = 0, 1, 2


def _dig(data, path):
    """Fetch a dotted key path out of the engine's JSON, tolerating absence."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def run_fixture(fixture_dir):
    spec = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))
    vault = fixture_dir / spec.get("vault", "vault")
    engine = ENGINES / spec["engine"]
    if not engine.is_file():
        return [{"ok": False, "why": f"engine not found: {engine}", "kind": "setup"}], None

    env = dict(os.environ)
    for k, v in (spec.get("env") or {}).items():
        env[k] = v.replace("{vault}", str(vault)).replace("{fixture}", str(fixture_dir))
    # Never inherit the caller's real configuration into a fixture run.
    for k in spec.get("unset_env", []):
        env.pop(k, None)

    proc = subprocess.run([sys.executable, str(engine), *spec.get("args", [])],
                          capture_output=True, text=True, env=env, timeout=120)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return [{"ok": False, "kind": "setup",
                 "why": f"engine did not emit JSON (exit {proc.returncode}): "
                        f"{(proc.stderr or proc.stdout).strip()[:160]}"}], proc

    results = []
    for a in spec.get("must_detect", []):
        blob = json.dumps(_dig(data, a["path"]))
        results.append({"ok": a["contains"] in (blob or ""), "kind": "must_detect",
                        "why": a["why"], "path": a["path"], "needle": a["contains"]})
    for a in spec.get("must_not_detect", []):
        blob = json.dumps(_dig(data, a["path"]))
        results.append({"ok": a["absent"] not in (blob or ""), "kind": "must_not_detect",
                        "why": a["why"], "path": a["path"], "needle": a["absent"]})
    return results, proc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", help="run only the fixture with this name")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not FIXTURES.is_dir():
        print(f"selftest: no fixtures at {FIXTURES}. Nothing was proven, which is not the same as "
              f"everything passing.", file=sys.stderr)
        return EXIT_NO_FIXTURES

    dirs = sorted(d for d in FIXTURES.iterdir()
                  if d.is_dir() and (d / "expected.json").is_file()
                  and (args.engine is None or d.name == args.engine))
    if not dirs:
        print(f"selftest: no fixture matched {args.engine!r}", file=sys.stderr)
        return EXIT_NO_FIXTURES

    report, failed = [], 0
    for d in dirs:
        results, _ = run_fixture(d)
        bad = [r for r in results if not r["ok"]]
        failed += len(bad)
        report.append({"fixture": d.name, "checks": len(results),
                       "failed": len(bad), "results": results})

    if args.json:
        print(json.dumps({"fixtures": report, "failed": failed}, indent=2))
        return EXIT_FAILED if failed else EXIT_OK

    for f in report:
        mark = "ok  " if not f["failed"] else "FAIL"
        print(f"  [{mark}] {f['fixture']:<22} {f['checks']} planted check(s)")
        for r in f["results"]:
            if not r["ok"]:
                if r["kind"] == "must_detect":
                    print(f"         MISSED: {r['why']}")
                    print(f"           expected {r['needle']!r} in {r['path']}, detector did not "
                          f"report it. The defect is still there; the detector is not.")
                elif r["kind"] == "must_not_detect":
                    print(f"         OVER-FIRED: {r['why']}")
                    print(f"           {r['needle']!r} appeared in {r['path']} and should not. A "
                          f"detector that reports everything proves nothing when it reports a defect.")
                else:
                    print(f"         {r['why']}")
    total = sum(f["checks"] for f in report)
    if failed:
        print(f"\nselftest FAILED: {failed} of {total} planted check(s) across {len(report)} fixture(s)")
        return EXIT_FAILED
    print(f"\nselftest OK: {total} planted check(s) across {len(report)} fixture(s); detectors are alive")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
