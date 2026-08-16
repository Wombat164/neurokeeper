"""neurokeeper CLI dispatcher.

The deterministic engines live as single-file scripts under scripts/ (that dir is also the Claude Code
plugin payload, and the pytest suite invokes those files directly). This thin dispatcher exposes them as
ONE installable console command -- `neurokeeper <engine> [args]` -- without moving the engines.

It locates the engines whether the package was installed as a wheel (engines force-included under the
package as _engines/) or run from a repo / plugin checkout (scripts/ at the root), then runs the requested
engine in-process via runpy so the engine parses its own argv exactly as `python scripts/<engine>.py` would.
"""
import os
import runpy
import sys

ENGINES = {
    "name-reconcile":     "vault-name-reconcile.py",
    "tag-reconcile":      "vault-tag-reconcile.py",
    "frontmatter-lint":   "vault-frontmatter-lint.py",
    "frontmatter-fix":    "vault-frontmatter-fix.py",
    "set-note-type":      "vault-set-note-type.py",
    "taxonomy-inventory": "vault-taxonomy-inventory.py",
    "ref-audit":          "vault-ref-audit.py",
    "correlate":          "vault-correlate.py",
    # Not part of the doctor composition either: doctor reports on vault health, this reports
    # on what a push or a paste would disclose. Different question, different failure mode.
    "egress-gate":        "egress-gate.py",
    "doctor":             "vault-doctor.py",
    "memory-consolidate": "memory-consolidate.py",
    "registry-generate":  "registry-generate.py",
    "check-release":      "check-release.py",
    "vendor-audit":       "vendor-audit.py",
    "selftest":           "selftest.py",
    "hooks-audit":        "hooks-audit.py",
    "custody-audit":      "custody-audit.py",
    "register-lint":      "register-lint.py",
    "path-audit":         "path-audit.py",
    "denylist-audit":     "denylist-audit.py",
}


def _engines_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "_engines"),                  # built wheel (force-include)
                 os.path.join(os.path.dirname(here), "scripts")):  # repo / plugin checkout
        if os.path.isdir(cand):
            return cand
    raise SystemExit("neurokeeper: engines directory not found (expected _engines/ or ../scripts/)")


def _external_engines():
    """Engines discovered on NEUROKEEPER_ENGINE_PATH: {name: (path, source_dir)}.

    A third party's engine belongs in the third party's repository. ADR-0004 refuses domain-specific
    content in the portable core, so "add it here" is the wrong answer for most real needs, and
    forking or vendoring is worse.

    Discovery itself lives in scripts/_engine_path.py because doctor composes the same set: two
    copies of a search path is the shape where the dispatcher and the roll-up disagree in silence.
    """
    sys.path.insert(0, _engines_dir())
    from _engine_path import discover
    return discover()


ENGINE_PATH_VAR = "NEUROKEEPER_ENGINE_PATH"


def _resolve(engine):
    """(script_path, origin) for an engine name, or exit 2 saying where it looked.

    A built-in name always wins and an external engine may NOT shadow one: silently replacing a core
    engine would make every report about this tool untrustworthy. Prefix your engine's name.
    """
    external = _external_engines()
    clash = sorted(set(external) & set(ENGINES))
    if clash:
        raise SystemExit(
            f"neurokeeper: external engine(s) {', '.join(clash)} shadow a built-in name.\n"
            f"  Refusing rather than choosing: a core engine quietly replaced makes every report "
            f"from this tool untrustworthy. Rename yours with an owner prefix, e.g. acme-{clash[0]}.")
    if engine in ENGINES:
        return os.path.join(_engines_dir(), ENGINES[engine]), "built-in"
    if engine in external:
        return external[engine][0], external[engine][1]

    searched = [_engines_dir()] + [d for _, d in external.values()]
    print(f"neurokeeper: unknown engine '{engine}'", file=sys.stderr)
    print(f"  looked in: {', '.join(dict.fromkeys(searched))}", file=sys.stderr)

    # The likeliest reason a just-written engine is 'unknown': the file is there, the header is not.
    # Said here rather than as a permanent line in --list, where every helper module beside every
    # engine would be listed as ignored and the one that matters would be lost in it.
    for d in dict.fromkeys(os.environ.get(ENGINE_PATH_VAR, "").split(os.pathsep)):
        cand = os.path.join(d.strip(), engine + ".py")
        if d.strip() and os.path.isfile(cand):
            print(f"  {cand} exists but carries no '# @capability:' header, so it is not "
                  f"registered as an engine.", file=sys.stderr)
            break
    if not os.environ.get(ENGINE_PATH_VAR):
        print(f"  {ENGINE_PATH_VAR} is not set, so no external engines were searched.",
              file=sys.stderr)
    print("", file=sys.stderr)
    _usage(2)


def _usage(rc=0):
    out = sys.stderr if rc else sys.stdout
    print("usage: neurokeeper <engine> [args]\n\nengines:", file=out)
    for name in ENGINES:
        print(f"  {name}", file=out)
    # Deliberately NOT wrapped in a try. An earlier version caught SystemExit here so that --list
    # would keep working with a broken path, which silently swallowed the one error this discovery
    # mechanism most needs to report: the listing then showed the built-ins and said nothing about
    # the external engines that had just gone missing.
    external = _external_engines()
    if external:
        print("\nexternal engines (via " + ENGINE_PATH_VAR + "):", file=out)
        for name, (_, src) in sorted(external.items()):
            print(f"  {name:<22} {src}", file=out)
    print("\nexample: neurokeeper name-reconcile --json", file=out)
    sys.exit(rc)


def main():
    for _s in (sys.stdout, sys.stderr):            # cross-platform UTF-8 (Windows defaults cp1252)
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help", "-l", "--list"):
        _usage(0)
    engine = argv[0]
    script, _origin = _resolve(engine)
    if not os.path.exists(script):
        raise SystemExit(f"neurokeeper: engine file missing: {script}")
    sys.argv = [script] + argv[1:]            # the engine parses its own argv
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
