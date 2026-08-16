#!/usr/bin/env python3
# @capability:  denylist-audit
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/denylist-audit.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         wiki/content/reference/index.md
"""denylist-audit.py -- audit the list a gate enforces, because nothing else does.

A gate that scans outbound material is only as good as its term list, and lists of that kind are
always grown reactively, one leak at a time. Two failures follow, both of which end with a green
verdict over material that should have been refused.

**A partially-listed family certifies its own siblings.** A list holding two members of an
identifier family and not the other three does not merely miss three terms: the member it DOES
catch is exactly what makes the clean verdict on the others credible. The gate is not silent, it is
actively reassuring.

**A narrowed entry can be silently dead.** Observed while fixing a real false positive: a short term
listed as a bare substring matched inside an ordinary English word, the fix was a word boundary,
and the first attempt wrote a malformed pattern that matched NOTHING AT ALL. A denylist term
silently disabled is worse than one that over-fires, because over-firing is visible and this is not.

So this asks two questions the gate itself cannot: is the list COMPLETE, and does each entry still
MATCH what it claims to.

Checks:

  dead-pattern     an entry that does not match its own declared example, or does not compile
  no-example       a regex entry with no example, so its liveness cannot be established
  family-partial   an identifier-register family with some members listed and some not
  variant-unlisted a case/hyphen/space variant present in the corpus that the list does not catch

Declare an example with a trailing comment, which is what makes liveness checkable:

    regex:(?i)\\bACME\\b    # example: ACME

  denylist-audit.py --denylist <file> [--register <file>] [--corpus <root>]
  Exit: 0 clean, 1 findings, 2 no denylist given, 3 denylist unreadable
"""
import argparse
import json
import os
import re
import sys

EXIT_OK, EXIT_FINDINGS, EXIT_UNCONFIGURED, EXIT_UNREACHABLE = 0, 1, 2, 3

_EXAMPLE = re.compile(r"#\s*example:\s*(.+?)\s*$", re.I)


def parse_denylist(path):
    """Entries as (raw, kind, pattern, example, lineno). Comments and blanks dropped."""
    out = []
    for i, line in enumerate(open(path, encoding="utf-8", errors="replace").read().splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _EXAMPLE.search(line)
        example = m.group(1) if m else None
        body = line[:m.start()].strip() if m else stripped
        if body.startswith("regex:"):
            out.append({"raw": body, "kind": "regex", "pattern": body[len("regex:"):],
                        "example": example, "line": i})
        else:
            out.append({"raw": body, "kind": "literal", "pattern": re.escape(body),
                        "example": example or body, "line": i})
    return out


def check_liveness(entries):
    """Every entry must match something it is supposed to match.

    This is the planted-defect idea applied to a list rather than to a detector: an entry that
    matches nothing is reported as DEAD rather than assumed strict.
    """
    findings = []
    for e in entries:
        try:
            rx = re.compile(e["pattern"], re.IGNORECASE)
        except re.error as err:
            findings.append({"state": "dead-pattern", "line": e["line"], "entry": e["raw"],
                             "detail": f"does not compile ({err}), so it matches nothing and the "
                                       f"gate is silently missing this term"})
            continue
        if e["kind"] == "regex" and not e["example"]:
            findings.append({"state": "no-example", "line": e["line"], "entry": e["raw"],
                             "detail": "a regex entry with no '# example:' comment. Its liveness "
                                       "cannot be established, so a malformed pattern here would "
                                       "match nothing and never be noticed"})
            continue
        if not rx.search(e["example"]):
            findings.append({"state": "dead-pattern", "line": e["line"], "entry": e["raw"],
                             "detail": f"does not match its own example {e['example']!r}. A term "
                                       f"silently disabled is worse than one that over-fires, "
                                       f"because over-firing is visible"})
    return findings


def check_families(entries, register_path):
    """A register family with some members listed and some not.

    Fully deterministic: the register already knows which identifiers are siblings, so this needs no
    heuristics at all. It is the highest-value half for exactly that reason.
    """
    if not register_path:
        return []
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _register import load                                    # noqa: E402
    reg = load(register_path)

    compiled = []
    for e in entries:
        try:
            compiled.append(re.compile(e["pattern"], re.IGNORECASE))
        except re.error:
            pass

    def listed(ident):
        return any(rx.search(ident) for rx in compiled)

    # Siblings share a parent. Walk one level, group by it.
    parent_of = {e["from"]: e["to"] for e in reg.edges if e["type"] == "parent"}
    families = {}
    for ident in reg.entities:
        parent = parent_of.get(ident)
        if parent:
            families.setdefault(parent, []).append(ident)

    findings = []
    for parent, members in sorted(families.items()):
        if len(members) < 2:
            continue
        on = [m for m in members if listed(m)]
        off = [m for m in members if not listed(m)]
        if on and off:
            findings.append({"state": "family-partial", "entry": parent,
                             "listed": sorted(on), "unlisted": sorted(off),
                             "detail": f"{len(on)} of {len(members)} members of the family under "
                                       f"{parent} are listed. The listed ones are what make a clean "
                                       f"verdict on {', '.join(sorted(off))} credible"})
    return findings


def check_variants(entries, corpus_root):
    """Case, hyphen and separator variants PRESENT IN THE CORPUS that the list does not catch.

    Presence in the corpus is what keeps this from being noise: generating variants is easy and
    generating useful ones is not, so only variants that actually occur are reported.
    """
    if not corpus_root:
        return []
    compiled = []
    for e in entries:
        try:
            compiled.append(re.compile(e["pattern"], re.IGNORECASE))
        except re.error:
            pass

    text = []
    for dirpath, dirs, files in os.walk(corpus_root):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.endswith((".md", ".markdown", ".txt")):
                try:
                    text.append(open(os.path.join(dirpath, fn), encoding="utf-8",
                                     errors="replace").read())
                except OSError:
                    pass
    corpus = "\n".join(text)
    if not corpus:
        return []

    findings, seen = [], set()
    for e in entries:
        base = e["raw"][len("regex:"):] if e["kind"] == "regex" else e["raw"]
        core = re.sub(r"[^A-Za-z0-9]+", "", base)
        if len(core) < 3:
            continue
        for variant in {core, core.upper(), core.lower(), core.title(),
                        "-".join(core), " ".join(core)}:
            if variant in seen or not variant.strip():
                continue
            if variant not in corpus:
                continue
            if any(rx.search(variant) for rx in compiled):
                continue
            seen.add(variant)
            findings.append({"state": "variant-unlisted", "entry": e["raw"], "variant": variant,
                             "detail": f"the spelling {variant!r} occurs in the corpus and no entry "
                                       f"matches it"})
    return findings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--denylist")
    ap.add_argument("--register")
    ap.add_argument("--corpus")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = args.denylist or os.environ.get("EGRESS_DENYLIST", "")
    if not path:
        print("denylist-audit: no denylist given (--denylist or EGRESS_DENYLIST).", file=sys.stderr)
        return EXIT_UNCONFIGURED
    if not os.path.isfile(path):
        print(f"denylist-audit: denylist named but not found at {path}. An error rather than an "
              f"empty list: auditing nothing would report a clean list.", file=sys.stderr)
        return EXIT_UNREACHABLE

    entries = parse_denylist(path)
    findings = (check_liveness(entries)
                + check_families(entries, args.register)
                + check_variants(entries, args.corpus))

    if args.json:
        print(json.dumps({"denylist": path, "entries": len(entries), "findings": findings}, indent=2))
        return EXIT_FINDINGS if findings else EXIT_OK

    if not findings:
        print(f"denylist-audit OK: {len(entries)} entries, every one live and no partial families")
        return EXIT_OK
    print(f"denylist-audit: {len(findings)} finding(s) over {len(entries)} entries")
    for f in findings:
        where = f"line {f['line']}: " if "line" in f else ""
        print(f"  [{f['state']}] {where}{f['entry']}")
        print(f"      {f['detail']}")
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
