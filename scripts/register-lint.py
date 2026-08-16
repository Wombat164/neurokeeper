#!/usr/bin/env python3
# @capability:  register-lint
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/register-lint.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         wiki/content/reference/index.md
"""register-lint.py -- does this collection use its own identifiers correctly?

Structural validation asks whether a field is KNOWN. It cannot ask whether a value is THE RIGHT KIND
OF THING, because both fields are known and both values are strings. Four classes live in that gap:

  wrong-category  a value the register calls an agreement, declared under the request field
  alias           a non-canonical spelling, invisible to every exact match
  compound        two identifiers packed into one value, e.g. ALPHA/2026-AG-4
  unknown         an identifier that exists nowhere in the register

REPORT ONLY, DELIBERATELY

This engine never blocks. It is a whole-collection inventory, and applying a new register to a
mature collection produces hundreds of findings on day one; a reader ignores three hundred stale
ones to reach the one that is theirs, then stops reading. Enforcement belongs to the author-time
guard, which is diff-scoped and therefore silent about inherited history (ADR-0005).

PROVENANCE CHANGES THE WORDING, NOT JUST THE SEVERITY

A `harvested` entry was typed by rule from what the collection already contained, so a mismatch may
mean the REGISTER is wrong rather than the document. The message hedges accordingly. An `inferred`
entry is a tool's guess and is reported without ever being enforced, because a name a tool invented
becoming canonical by being the only spelling that passes a check is the failure this whole design
exists to prevent.

  register-lint.py --check    # 0 clean, 1 findings, 2 no register configured, 3 register unusable
  register-lint.py --json
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _register import RegisterError, load, register_path  # noqa: E402

EXIT_OK, EXIT_FINDINGS, EXIT_UNCONFIGURED, EXIT_UNREACHABLE = 0, 1, 2, 3

_FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)
_KV = re.compile(r"^([A-Za-z_][\w-]*):\s*(\S.*?)\s*$")
# Two identifiers packed into one value. Conservative on purpose: a separator with an alphanumeric
# run on each side. A date such as 2026-08-16 must not read as a compound, so the parts have to
# resolve against the register before anything is reported.
_COMPOUND = re.compile(r"^(?P<a>[A-Za-z0-9][\w.-]*)\s*[/|,;+]\s*(?P<b>[A-Za-z0-9][\w.-]*)$")


def frontmatter(text):
    m = _FM.match(text)
    if not m:
        return {}
    out = {}
    for i, line in enumerate(m.group(1).splitlines(), start=2):
        kv = _KV.match(line)
        if kv:
            out[kv.group(1).lower()] = (kv.group(2).strip().strip("\"'"), i)
    return out


def check_value(reg, field, value, lineno, path):
    """Findings for one frontmatter value. Returns a list; usually empty."""
    out = []
    ident, how = reg.resolve(value)

    if ident and how == "alias":
        out.append({"state": "alias", "path": path, "line": lineno, "field": field,
                    "value": value, "canonical": ident,
                    "detail": f"{reg.phrase(ident)} the canonical spelling is {ident!r}",
                    "remedy": f"replace it with {ident!r}",
                    "enforceable": reg.rules(ident)["enforce"],
                    "fixable": reg.rules(ident)["fix"]})
        return out

    if not ident:
        m = _COMPOUND.match(str(value))
        if m:
            a, _ = reg.resolve(m.group("a"))
            b, _ = reg.resolve(m.group("b"))
            if a and b:
                out.append({"state": "compound", "path": path, "line": lineno, "field": field,
                            "value": value, "parts": [a, b],
                            "detail": f"two identifiers in one value: {a} and {b}. Split them, or "
                                      f"the field means neither",
                            "remedy": f"split into {a} and {b}, each under the field its tier "
                                      f"expects",
                            "enforceable": reg.rules(a)["enforce"] and reg.rules(b)["enforce"],
                            "fixable": False})
                return out
        out.append({"state": "unknown", "path": path, "line": lineno, "field": field,
                    "value": value,
                    "detail": "not in the register under any spelling. Either it is new and the "
                              "register should learn it, or it is a typo",
                    "remedy": "add it to the register, or correct the spelling",
                    "enforceable": False, "fixable": False})
        return out

    # Exact hit: is it under the field its tier expects?
    tier = reg.entities[ident]["tier"]
    expected = reg.tier_fields.get(tier)
    if expected and expected != field:
        out.append({"state": "wrong-category", "path": path, "line": lineno, "field": field,
                    "value": value, "expected_field": expected, "tier": tier,
                    "detail": f"{reg.phrase(ident)} this is a {tier}, which belongs under "
                              f"{expected!r}, not {field!r}",
                    "remedy": f"move it to the {expected!r} field",
                    "enforceable": reg.rules(ident)["enforce"],
                    "fixable": reg.rules(ident)["fix"]})
    return out


def scan(reg, root, exclude):
    findings = []
    watched = set(reg.tier_fields.values())
    if not watched:
        return findings
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in exclude and not d.startswith(".")]
        for fn in files:
            if not fn.endswith((".md", ".markdown")):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for field, (value, lineno) in frontmatter(text).items():
                if field in watched:
                    findings.extend(check_value(reg, field, value, lineno, rel))
    return findings


def guard(reg, root, path, ref=None, as_hook=False, quiet_ok=True):
    """Author-time guard for ONE document, scoped to the lines this change touched.

    Firing on pre-existing violations is the documented way a linter gets switched off. Applying a
    register to a mature collection produces findings on day one that nobody present caused; a
    reader ignores all of them to reach the one that is theirs, and then stops reading. So:

      * findings on lines this edit touched are reported in FULL, with the remedy, and block;
      * findings elsewhere in the same document collapse to a single count and do not block.

    The backlog stays visible and cannot grow, and nobody is made to answer for it on every save.

    Only ENFORCEABLE findings block (ADR-0005). A register entry that was inferred rather than
    decided may be wrong, and blocking a person's work on a guess the tool made about their own
    vocabulary is how the tool loses the argument about whether it should exist.
    """
    rel = os.path.relpath(os.path.abspath(path), root).replace(os.sep, "/")
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        print(f"register-lint --guard: cannot read {path}: {e}", file=sys.stderr)
        return EXIT_UNREACHABLE

    watched = set(reg.tier_fields.values())
    findings = []
    for field, (value, lineno) in frontmatter(text).items():
        if field in watched:
            findings.extend(check_value(reg, field, value, lineno, rel))

    from _scope import changed_lines
    changed = changed_lines(root, path, ref=ref, who="register-lint --guard")
    # None means "cannot narrow" -- not a repo, untracked, git unavailable. Treat every line as in
    # scope rather than none: narrowing to nothing would report a clean document never examined.
    introduced, pre_existing = [], []
    for f in findings:
        (introduced if (changed is None or f["line"] in changed) else pre_existing).append(f)

    blocking = [f for f in introduced if f.get("enforceable")]
    advisory = [f for f in introduced if not f.get("enforceable")]

    if not blocking:
        if pre_existing and not quiet_ok:
            print(f"[guard] {rel}: {len(pre_existing)} pre-existing finding(s), none introduced by "
                  f"this edit. Not blocking.")
        for f in advisory:
            print(f"[guard] {rel}:{f['line']}  {f['field']}: {f['value']!r} -- {f['detail']}\n"
                  f"        (advisory: this register entry is not enforceable)")
        return EXIT_OK

    print(f"[guard] {rel} -- this edit introduces {len(blocking)} contradiction(s):", file=sys.stderr)
    for f in blocking:
        print(f"  {f['field']}: {f['value']!r} -- {f['detail']}", file=sys.stderr)
        # The remedy, not just the fault. A guard that says only "wrong" gets silenced, and naming
        # where the canon lives is what lets a reader go and argue with it instead.
        print(f"      fix: {f.get('remedy') or 'correct the value, or amend the register'}",
              file=sys.stderr)
    for f in advisory:
        print(f"  {f['field']}: {f['value']!r} -- {f['detail']} (advisory, not blocking)",
              file=sys.stderr)
    if pre_existing:
        print(f"  ({len(pre_existing)} further pre-existing finding(s), not caused by this edit.)",
              file=sys.stderr)
    print(f"  canon: {reg.path}", file=sys.stderr)
    # 2 is what a PostToolUse hook must return to block, and it is also this engine's
    # NOT-CONFIGURED code. A hook that could not tell "blocked" from "no register" would be a
    # coin-flip, so the collision is opt-in: --hook says the caller is a hook and wants 2.
    return 2 if as_hook else EXIT_FINDINGS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("VAULT_ROOT") or ".")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--guard", metavar="PATH",
                    help="Author-time guard for ONE document: report findings on the lines this "
                         "change touched and block on them; collapse the rest to a count. This is "
                         "the enforcing mode -- the whole-collection report never blocks.")
    ap.add_argument("--guard-ref", metavar="REF",
                    help="With --guard: diff against this ref instead of HEAD.")
    ap.add_argument("--hook", action="store_true",
                    help="With --guard: exit 2 to block, which is what a PostToolUse hook requires. "
                         "Off by default because 2 is also this engine's NOT-CONFIGURED code, and a "
                         "caller unable to tell 'blocked' from 'no register' is a coin-flip.")
    ap.add_argument("--verbose", action="store_true",
                    help="With --guard: also say when a document has a pre-existing backlog that "
                         "this edit did not add to.")
    ap.add_argument("--staged", action="store_true",
                    help="Report only on files in the git index; count the rest as pre-existing.")
    ap.add_argument("--since", metavar="REF",
                    help="Report only on files changed since REF; count the rest as pre-existing.")
    args = ap.parse_args()

    if not register_path():
        print("register-lint: IDENTIFIER_REGISTER not set; no register is declared.\n"
              "  Copy config.example/identifier-register.example.yaml and point at it to enable.",
              file=sys.stderr)
        return EXIT_UNCONFIGURED
    try:
        reg = load()
    except RegisterError as e:
        print(f"register-lint: {e}", file=sys.stderr)
        return EXIT_UNREACHABLE

    root = os.path.abspath(args.root)

    if args.guard:
        return guard(reg, root, args.guard, ref=args.guard_ref, as_hook=args.hook,
                     quiet_ok=not args.verbose)

    exclude = set(x for x in (os.environ.get("VAULT_SCAN_EXCLUDE") or ".git,.obsidian,node_modules")
                  .split(",") if x)
    findings = scan(reg, root, exclude)

    # File-level scoping, the same family ref-audit uses and the same shared implementation. Out of
    # scope means COUNTED, never discarded: a backlog nobody can see cannot be worked down, and
    # cannot be shown to be growing.
    pre_existing_out_of_scope = 0
    if args.staged or args.since:
        from _scope import changed_since, staged_paths
        in_scope = (staged_paths(root, who="register-lint --staged") if args.staged
                    else changed_since(root, args.since, who="register-lint --since"))
        kept = [f for f in findings if f["path"] in in_scope]
        pre_existing_out_of_scope = len(findings) - len(kept)
        findings = kept

    if args.json:
        counts = {}
        for f in findings:
            counts[f["state"]] = counts.get(f["state"], 0) + 1
        print(json.dumps({"register": reg.path, "entities": len(reg.entities),
                          "counts": counts, "findings": findings,
                          "pre_existing_out_of_scope": pre_existing_out_of_scope}, indent=2))
        return EXIT_FINDINGS if findings else EXIT_OK

    if not findings:
        print(f"register-lint OK: every declared identifier is used as the register describes "
              f"({len(reg.entities)} entities)")
        if pre_existing_out_of_scope:
            print(f"  {pre_existing_out_of_scope} pre-existing finding(s) outside this scope.")
        return EXIT_OK
    print(f"register-lint: {len(findings)} finding(s) against {len(reg.entities)} entities")
    for f in findings:
        mark = "" if f.get("enforceable") else "  [not enforceable]"
        print(f"  [{f['state']}] {f['path']}:{f['line']}  {f['field']}: {f['value']!r}{mark}")
        print(f"      {f['detail']}")
    if pre_existing_out_of_scope:
        print(f"\n  {pre_existing_out_of_scope} further pre-existing finding(s) outside this scope, "
              f"counted and not listed.")
    print("\n  This report never blocks. Enforcement is --guard's job, scoped to the lines a change "
          "touches (ADR-0005).")
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
