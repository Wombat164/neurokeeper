#!/usr/bin/env python3
# @capability:  init
# @compute:     deterministic
# @effect:      mutating
# @engine:      scripts/init.py
# @prompt:      (none)
# @adapters:    cli
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       git
# @status:      active
# @doc:         docs/adr-0004-substrate-boundary.md
"""init -- configure this tool for a collection, and say what it did.

Adoption on an EXISTING collection is documented: baseline it, gate on net-new, work the backlog
down. That covers everyone who already has a collection and leaves the other case uncovered.

Someone starting today gets a set of engines, four optional config files and no order to do anything
in. The engines each skip cleanly when unconfigured, which is correct, and which also means a fresh
collection reports a clean bill of health while doing almost nothing:

    [skip]  frontmatter-lint    (required config not set)
    [skip]  memory-consolidate  (required config not set)
    roll-up: OK

That output is honest and it is a bad first experience, because a newcomer cannot tell "correctly
minimal" from "silently doing nothing" -- the same confusion between absent and empty that the exit
contract fixes one layer down.

## What it will not do

WRITE CONTENT. It writes configuration. It does not create notes, folders or a naming convention: a
tool that invents a structure on day one has decided the collection's shape before its owner has,
and ADR-0004 refuses exactly that.

MARK DERIVED CONFIG AS DECIDED. A schema drafted from what a collection already contains is
`harvested` by definition. Promoting it silently would turn this tool's reading of a collection into
that collection's law, which is the failure provenance exists to prevent.

CLAIM SUCCESS. It prints every file it wrote and ends on a real `doctor --check`, because a wizard
whose output cannot be checked has produced configuration nobody can audit.

Exit: 0 configured (or nothing to do), 1 the closing verification failed, 3 the collection is
      unreadable.
"""
import argparse
import json
import os
import subprocess
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _vault_lib import force_utf8_stdout, md_files, parse_frontmatter  # noqa: E402

EXIT_OK, EXIT_VERIFY_FAILED, EXIT_UNREADABLE = 0, 1, 3

# Engines a collection can turn on here, with the config each one costs. The choice and its price
# belong on the same line: "which engines do you want" is unanswerable without it.
OFFERS = [
    ("ref-audit", None, "reference integrity: broken links, orphans, dead ends"),
    ("taxonomy-inventory", None, "naming, tag and frontmatter inventory"),
    ("frontmatter-lint", "FRONTMATTER_SCHEMA", "validate notes against your schema"),
    ("register-lint", "IDENTIFIER_REGISTER", "do documents use your identifiers correctly"),
    ("memory-consolidate", "CLAUDE_MEMORY_DIR", "health of a file-based memory store"),
]

# Keys that are structure rather than subject matter, so a derived schema does not propose them as
# vocabulary axes. Deliberately short: over-excluding here hides a real axis, and the cost of an
# extra proposed axis is one line a human deletes.
_NOT_AXES = {"title", "aliases", "created", "updated", "date", "author", "description",
             "summary", "source", "url", "id", "uid", "cssclass", "publish", "permalink"}
_MAX_VALUES = 24          # beyond this a field is open vocabulary, not an enum


def _say(msg=""):
    print(msg)


def scan_collection(root):
    """What is actually here: note count, frontmatter fields, and their value distributions.

    The count is printed out loud on purpose. A wizard that silently scopes to the wrong root writes
    a config that reports clean forever, and the person who ran it has no way to notice.
    """
    fields = {}
    n = 0
    # The root is passed EXPLICITLY. Setting VAULT_ROOT here and calling md_files() with no argument
    # silently scanned the working directory instead: the module-level default is captured at import
    # time, so a later environment change does nothing. That produced a confident note count for the
    # wrong collection, which is precisely what printing the count out loud is meant to catch.
    for path, _reldir in md_files(root):
        n += 1
        try:
            fm = parse_frontmatter(open(path, encoding="utf-8", errors="replace").read())
        except OSError:
            continue
        if not isinstance(fm, dict):
            continue
        for k, v in fm.items():
            if k.startswith("__"):
                continue
            vals = v if isinstance(v, list) else [v]
            c = fields.setdefault(k, Counter())
            for item in vals:
                if isinstance(item, (str, int, float)) and str(item).strip():
                    c[str(item).strip()] += 1
    return n, fields


def derive_schema(fields, notes):
    """A schema DRAFT from what the collection already contains. Provenance: harvested, always.

    Enum or open vocabulary is decided by value count, because that is a fact about the collection
    rather than a judgment about it. A field with four distinct values across 900 notes is an axis;
    one with 600 is free text, and enumerating it would produce a schema that fails on everything.
    """
    axes = {}
    for name, counter in sorted(fields.items()):
        if name.lower() in _NOT_AXES or name.startswith("_"):
            continue
        if len(counter) == 0:
            continue
        if len(counter) <= _MAX_VALUES:
            axes[name] = {"values": sorted(counter), "recommended": False}
        else:
            axes[name] = {"open": True}
    return {
        "version": 1,
        # Not a comment, a field. A reader who opens this file six months from now must be told what
        # it is without having to remember, and a comment survives no round-trip.
        "provenance": "harvested",
        "_note": (f"DRAFT derived from {notes} note(s) by `neurokeeper init`. It describes what the "
                  f"collection CONTAINS, not what it should contain. Nothing here was decided by "
                  f"anyone: review it, delete the axes that are accidents, and only then treat it "
                  f"as canon."),
        "axes": axes,
    }


def _yaml_dump(obj, indent=0):
    """Minimal YAML writer, so a derived draft does not require PyYAML to be installed to be read.

    Deliberately tiny: this writes config files whose shapes are known here. It is not a general
    serializer and must not be used as one.
    """
    pad = " " * indent
    out = []
    for k, v in obj.items():
        if isinstance(v, dict):
            out.append(f"{pad}{k}:")
            out.append(_yaml_dump(v, indent + 2))
        elif isinstance(v, list):
            inline = ", ".join(json.dumps(str(x)) for x in v)
            out.append(f"{pad}{k}: [{inline}]")
        elif isinstance(v, bool):
            out.append(f"{pad}{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            out.append(f"{pad}{k}: {v}")
        else:
            out.append(f"{pad}{k}: {json.dumps(str(v))}")
    return "\n".join(x for x in out if x)


def _copy_example(name, dest):
    src = os.path.join(os.path.dirname(HERE), "config.example", name)
    if not os.path.isfile(src):
        return None
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    with open(dest, "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    return dest


def wire_gates(root, dry_run):
    """Point git at a hooks dir, because configuration does not clone.

    A shipped gate is not a running one. `core.hooksPath` is per-clone local config, so a repo can
    carry a hooks directory that has never executed on this machine -- which is the shape
    `hooks-audit` exists to report.
    """
    hooks = os.path.join(root, ".githooks")
    if dry_run:
        return [f"(dry-run) would set core.hooksPath to .githooks and create {hooks}"]
    os.makedirs(hooks, exist_ok=True)
    r = subprocess.run(["git", "-C", root, "config", "core.hooksPath", ".githooks"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"could not set core.hooksPath: {r.stderr.strip()} (is {root} a git repo?)"]
    return ["git core.hooksPath -> .githooks  (verify with: neurokeeper hooks-audit)"]


def _ask(prompt, default, options=None):
    try:
        raw = input(f"{prompt} [{default}]: ").strip()
    except EOFError:
        return default
    if not raw:
        return default
    if options and raw not in options:
        _say(f"  not one of {options}; using {default}")
        return default
    return raw


def main(argv=None):
    force_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Configure neurokeeper for a collection. Writes config, never content.")
    ap.add_argument("--collection", default=".", help="Collection root (default: here).")
    ap.add_argument("--out", help="Where config goes (default: <collection>/.neurokeeper).")
    ap.add_argument("--non-interactive", action="store_true",
                    help="Ask nothing; use the flags below. For CI and scripted provisioning.")
    ap.add_argument("--schema", choices=["example", "derive", "skip"], default=None,
                    help="Frontmatter schema: copy the shipped example, DERIVE a draft from what "
                         "the collection contains (always written as harvested), or skip.")
    ap.add_argument("--register", choices=["example", "skip"], default=None,
                    help="Identifier register: copy the shipped example, or skip. There is no "
                         "derive: identifiers are your collection's canon, and a tool that invents "
                         "them has decided what they mean.")
    ap.add_argument("--gates", action="store_true", help="Wire git core.hooksPath.")
    ap.add_argument("--baseline", action="store_true",
                    help="Accept the current findings as the starting point, so the gate reports "
                         "net-new from here.")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be written; write nothing.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.collection)
    if not os.path.isdir(root):
        print(f"init: not a directory: {root}", file=sys.stderr)
        return EXIT_UNREADABLE
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(root, ".neurokeeper")

    _say(f"collection: {root}")
    notes, fields = scan_collection(root)
    # Said out loud, first, before anything is written. A wizard that silently scopes to the wrong
    # root produces a config that reports clean forever.
    _say(f"found:      {notes} markdown note(s), {len(fields)} distinct frontmatter field(s)")
    if notes == 0:
        _say("            (none -- if that is a surprise, the root above is wrong; nothing was written)")
        if not args.non_interactive and not args.dry_run:
            return EXIT_OK
    _say()

    interactive = not args.non_interactive
    schema_mode = args.schema
    register_mode = args.register
    do_gates, do_baseline = args.gates, args.baseline

    if interactive:
        _say("engines available, with the config each one needs:")
        for name, cfg, what in OFFERS:
            _say(f"  {name:<20} {what}" + (f"  [needs {cfg}]" if cfg else "  [no config]"))
        _say()
        if schema_mode is None:
            schema_mode = _ask("frontmatter schema: example / derive / skip", "derive",
                               ["example", "derive", "skip"])
        if register_mode is None:
            register_mode = _ask("identifier register: example / skip", "skip", ["example", "skip"])
        if not do_gates:
            do_gates = _ask("wire git hooks (core.hooksPath)? yes / no", "yes", ["yes", "no"]) == "yes"
        if not do_baseline and notes:
            do_baseline = _ask("baseline today's findings, so the gate reports net-new? yes / no",
                               "yes", ["yes", "no"]) == "yes"
    schema_mode = schema_mode or "skip"
    register_mode = register_mode or "skip"

    written, notes_out, env = [], [], {}
    if not args.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    if schema_mode == "derive":
        if not fields:
            notes_out.append("no frontmatter found, so there was nothing to derive a schema from")
        else:
            dest = os.path.join(out_dir, "frontmatter-schema.yaml")
            doc = derive_schema(fields, notes)
            if args.dry_run:
                notes_out.append(f"(dry-run) would write {dest} with {len(doc['axes'])} axes")
            else:
                with open(dest, "w", encoding="utf-8", newline="") as fh:
                    fh.write(_yaml_dump(doc) + "\n")
                written.append(dest)
            env["FRONTMATTER_SCHEMA"] = dest
            notes_out.append("the derived schema is a DRAFT marked provenance: harvested. It says "
                             "what the collection contains, not what it should. Review it before "
                             "treating it as canon.")
    elif schema_mode == "example":
        dest = os.path.join(out_dir, "frontmatter-schema.yaml")
        if args.dry_run:
            notes_out.append(f"(dry-run) would copy the shipped schema example to {dest}")
        elif _copy_example("frontmatter-schema.example.yaml", dest):
            written.append(dest)
        env["FRONTMATTER_SCHEMA"] = dest

    if register_mode == "example":
        dest = os.path.join(out_dir, "identifier-register.yaml")
        if args.dry_run:
            notes_out.append(f"(dry-run) would copy the shipped register example to {dest}")
        elif _copy_example("identifier-register.example.yaml", dest):
            written.append(dest)
        env["IDENTIFIER_REGISTER"] = dest

    if do_gates:
        notes_out.extend(wire_gates(root, args.dry_run))

    if do_baseline and notes:
        dest = os.path.join(out_dir, "ref-audit-baseline.json")
        if args.dry_run:
            notes_out.append(f"(dry-run) would write a baseline to {dest}")
        else:
            r = subprocess.run([sys.executable, os.path.join(HERE, "vault-ref-audit.py"),
                                "--write-baseline", dest],
                               capture_output=True, text=True, env={**os.environ, "VAULT_ROOT": root})
            if r.returncode in (0, 1) and os.path.isfile(dest):
                written.append(dest)
                notes_out.append("baseline accepts today's findings as the starting point. It is "
                                 "not a fix and does not pretend to be: the count stays visible and "
                                 "the gate now reports what is NEW.")
            else:
                notes_out.append(f"could not write a baseline: {(r.stderr or r.stdout).strip()[:200]}")

    _say("wrote:" if written else "wrote: nothing")
    for p in written:
        _say(f"  {p}")
    if notes_out:
        _say()
        for n in notes_out:
            _say(f"  - {n}")

    if env:
        _say("\nset these, or your engines will skip and report a clean bill of health:")
        for k, v in env.items():
            _say(f'  export {k}="{v}"')

    # End on a real run, not a claim. A wizard whose output cannot be checked has produced
    # configuration nobody can audit.
    _say("\nverifying...")
    if args.dry_run:
        _say("  (dry-run: nothing written, nothing to verify)")
        rc = 0
    else:
        r = subprocess.run([sys.executable, os.path.join(HERE, "vault-doctor.py"), "--check"],
                           text=True, env={**os.environ, "VAULT_ROOT": root, **env})
        rc = r.returncode
        _say(f"  doctor --check -> exit {rc}")
    _say("\nnext: neurokeeper doctor        (the same check, any time)")

    if args.json:
        print(json.dumps({"engine": "init", "collection": root, "notes": notes,
                          "counts": {"written": len(written), "fields": len(fields)},
                          "written": written, "env": env, "verify_exit": rc}, indent=2))
    return EXIT_OK if rc == 0 else EXIT_VERIFY_FAILED


if __name__ == "__main__":
    sys.exit(main())
