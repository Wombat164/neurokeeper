#!/usr/bin/env python3
# @capability:  vendor-audit
# @compute:     deterministic
# @effect:      read-only (--adopt writes the manifest only)
# @engine:      scripts/vendor-audit.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         wiki/content/reference/index.md
"""vendor-audit.py -- notice when an upstream file moves under a deliberately-vendored copy.

WHY THIS EXISTS

The de-dup pattern works: a consumer keeps thin shims that delegate to the engines here, so a fix
upstream reaches every consumer with no manual step. Some files cannot be shimmed, for reasons that
are good rather than lazy: they are invoked from outside the consumer's tree, by a gate in another
repository, on machines where this project was never cloned. A shim exits when the engine is absent,
which would block that gate. So those stay resident copies.

What the documentation then says is "kept in sync by hand", and that is where it fails. One such
copy drifted to 311 lines against upstream's 416, missing an entire flag and four functions, and
nobody noticed. The reason nobody noticed is the reason it matters: a stale analyzer reports
cheerfully. There is no error to see.

WHY THIS DOES NOT AUTO-SYNC

Pulling upstream over a resident copy silently discards local configuration. Pushing the other way
leaks consumer specifics into a portable core. Neither direction is safe to automate. The machine
should NOTICE; a human should reconcile.

WHAT IT REPORTS, AND WHAT IT DELIBERATELY DOES NOT

It reports that UPSTREAM MOVED since the copy was last reconciled. It does NOT report that the two
files differ: they always differ, by design, and a check that fires constantly is one nobody reads.

  vendor-audit.py --check     # exit 0 reconciled, 1 upstream moved, 2 no manifest, 3 manifest unreadable
  vendor-audit.py --json      # machine-readable findings
  vendor-audit.py --adopt     # record the CURRENT upstream state as reconciled (after a human merge)

The manifest is JSON at $VENDOR_MANIFEST:

  {"entries": [
     {"local": "scripts/memory-consolidate.py",
      "upstream": "../neurokeeper/scripts/memory-consolidate.py",
      "upstream_sha256": "ab12...",
      "reconciled": "2026-08-16",
      "why_resident": "called by another repo's pre-commit gate; must work with no clone here"}
  ]}

Relative paths resolve against the manifest's own directory, so a manifest is portable between
checkouts. `why_resident` is required on every entry: a vendored copy without a stated reason is
indistinguishable from an accident, and this file exists because that distinction got lost once.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

EXIT_OK, EXIT_DRIFT, EXIT_UNCONFIGURED, EXIT_UNREACHABLE = 0, 1, 2, 3


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path():
    return os.environ.get("VENDOR_MANIFEST", "")


def load(path):
    """Return (entries, base_dir). Exits 3 if configured and unusable: see ADR-0002's amendment."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        print(f"vendor-audit: manifest configured but unreadable: {path}\n  {e}\n"
              f"  This is an error rather than a skip: a manifest was named and could not be read,\n"
              f"  so no answer is available and reporting 'nothing vendored' would be a lie.",
              file=sys.stderr)
        raise SystemExit(EXIT_UNREACHABLE)
    except ValueError as e:
        print(f"vendor-audit: manifest is not valid JSON: {path}\n  {e}", file=sys.stderr)
        raise SystemExit(EXIT_UNREACHABLE)
    entries = data.get("entries")
    if not isinstance(entries, list):
        print(f"vendor-audit: manifest has no entries[] list: {path}", file=sys.stderr)
        raise SystemExit(EXIT_UNREACHABLE)
    return entries, os.path.dirname(os.path.abspath(path))


def resolve(base, rel):
    return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(base, rel))


def audit(entries, base):
    """Compare each entry's recorded upstream hash against the upstream file as it is now."""
    findings = []
    for i, e in enumerate(entries):
        local, upstream = e.get("local"), e.get("upstream")
        if not local or not upstream:
            findings.append({"entry": i, "state": "malformed",
                             "detail": "entry needs both 'local' and 'upstream'"})
            continue
        if not e.get("why_resident"):
            findings.append({"entry": i, "local": local, "state": "unexplained",
                             "detail": "no why_resident: a vendored copy without a stated reason "
                                       "cannot be told apart from an accident"})
        up = resolve(base, upstream)
        if not os.path.isfile(up):
            # Upstream absent is NOT drift. The consumer may simply not have the source checked out,
            # which is the whole reason this file is resident rather than a shim.
            findings.append({"entry": i, "local": local, "upstream": up, "state": "upstream-absent",
                             "detail": "cannot compare; not a defect on a machine without the source"})
            continue
        recorded, now = e.get("upstream_sha256", ""), sha256(up)
        if not recorded:
            findings.append({"entry": i, "local": local, "upstream": up, "state": "never-reconciled",
                             "detail": "no upstream_sha256 recorded; run --adopt to set a baseline"})
        elif recorded != now:
            findings.append({"entry": i, "local": local, "upstream": up, "state": "upstream-moved",
                             "reconciled": e.get("reconciled", "?"),
                             "detail": "upstream changed since this copy was reconciled; diff the "
                                       "two, port what applies, then --adopt"})
    return findings


def adopt(path, entries, base):
    stamped = 0
    for e in entries:
        up = resolve(base, e.get("upstream", ""))
        if e.get("upstream") and os.path.isfile(up):
            e["upstream_sha256"] = sha256(up)
            e["reconciled"] = datetime.date.today().isoformat()
            stamped += 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"entries": entries}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"vendor-audit: recorded a reconciled baseline for {stamped} entr(ies) in {path}")
    return EXIT_OK


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--adopt", action="store_true")
    args = ap.parse_args()

    path = manifest_path()
    if not path:
        print("vendor-audit: VENDOR_MANIFEST not set; nothing is declared as vendored.\n"
              "  Set it to a manifest to enable this check.", file=sys.stderr)
        return EXIT_UNCONFIGURED
    entries, base = load(path)

    if args.adopt:
        return adopt(path, entries, base)

    findings = audit(entries, base)
    drift = [f for f in findings if f["state"] in ("upstream-moved", "malformed")]

    if args.json:
        print(json.dumps({"manifest": path, "entries": len(entries), "findings": findings}, indent=2))
        return EXIT_DRIFT if drift else EXIT_OK

    if not findings:
        print(f"vendor-audit OK: {len(entries)} vendored cop(ies) still reconciled with upstream")
        return EXIT_OK
    print(f"vendor-audit: {len(findings)} finding(s) over {len(entries)} vendored cop(ies)")
    for f in findings:
        print(f"  [{f['state']}] {f.get('local', '?')}")
        print(f"      {f['detail']}")
        if f["state"] == "upstream-moved":
            print(f"      upstream: {f['upstream']}  (last reconciled {f['reconciled']})")
    return EXIT_DRIFT if drift else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
