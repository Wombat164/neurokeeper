#!/usr/bin/env python3
# @capability:  acme-owner-audit
# @compute:     deterministic
# @effect:      read-only
# @engine:      examples/engines/acme-owner-audit.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L2-config
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doctor:      gate
# @doc:         wiki/content/how-to/extend-with-your-own-engine.md
"""A worked EXTERNAL engine: flag notes whose declared owner is not in a team roster.

This file is not part of the core and is not installed with it. It stands in for an engine living in
somebody else's repository, and exists so the seam is demonstrated by something that actually runs
rather than asserted in prose. CI dispatches it against examples/vault/ and composes it into the
doctor roll-up on every push.

It is deliberately domain-specific -- a roster and an `owner` field are your organisation's
vocabulary, not the tool's -- which is exactly why it belongs outside the core. ADR-0004 refuses
this content upstream; NEUROKEEPER_ENGINE_PATH is why that refusal does not force a fork.

Config: OWNER_ROSTER = path to a text file, one owner per line.
Exit:   0 scanned and clean (or reported without --check)
        1 --check and at least one note has an off-roster owner
        2 OWNER_ROSTER not set          (NOT CONFIGURED: doctor reports this as skipped)
        3 OWNER_ROSTER set but unreadable (UNREACHABLE: a real defect, fails the roll-up)
"""
import json
import os
import sys

from neurokeeper.lib import force_utf8_stdout, md_files, parse_frontmatter


def main():
    force_utf8_stdout()
    as_json = "--json" in sys.argv
    check = "--check" in sys.argv

    roster_path = os.environ.get("OWNER_ROSTER")
    if not roster_path:
        # 2, not 1. "You did not configure this" is not "your collection is unhealthy", and
        # collapsing the two is how an unconfigured check gets read as a passing one.
        print("acme-owner-audit: OWNER_ROSTER not set (path to a roster file, one owner per line)",
              file=sys.stderr)
        sys.exit(2)
    try:
        with open(roster_path, encoding="utf-8") as fh:
            roster = {line.strip() for line in fh if line.strip() and not line.startswith("#")}
    except OSError as e:
        # 3, not 2. The operator named a roster, so the check is ON; a check pointing at nothing
        # must not roll up green just because it could not read its own subject.
        print(f"acme-owner-audit: OWNER_ROSTER is set but unreadable: {e}", file=sys.stderr)
        sys.exit(3)

    findings = []
    for path, _reldir in md_files():
        with open(path, encoding="utf-8") as fh:
            fm = parse_frontmatter(fh.read())
        owner = (fm or {}).get("owner")
        if owner and str(owner) not in roster:
            findings.append({"path": path, "owner": str(owner)})

    if as_json:
        print(json.dumps({"engine": "acme-owner-audit",
                          "counts": {"off_roster": len(findings), "roster_size": len(roster)},
                          "unknown_owners": findings}, indent=2))
    else:
        for f in findings:
            print(f"unknown owner '{f['owner']}': {f['path']}")
        print(f"acme-owner-audit: {len(findings)} note(s) with an owner not in the roster "
              f"({len(roster)} on roster)")

    sys.exit(1 if (check and findings) else 0)


if __name__ == "__main__":
    main()
