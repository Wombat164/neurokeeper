"""claude-harness CLI dispatcher.

The deterministic engines live as single-file scripts under scripts/ (that dir is also the Claude Code
plugin payload, and the pytest suite invokes those files directly). This thin dispatcher exposes them as
ONE installable console command -- `claude-harness <engine> [args]` -- without moving the engines.

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
    "doctor":             "vault-doctor.py",
    "memory-consolidate": "memory-consolidate.py",
    "registry-generate":  "registry-generate.py",
    "check-release":      "check-release.py",
}


def _engines_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "_engines"),                  # built wheel (force-include)
                 os.path.join(os.path.dirname(here), "scripts")):  # repo / plugin checkout
        if os.path.isdir(cand):
            return cand
    raise SystemExit("claude-harness: engines directory not found (expected _engines/ or ../scripts/)")


def _usage(rc=0):
    out = sys.stderr if rc else sys.stdout
    print("usage: claude-harness <engine> [args]\n\nengines:", file=out)
    for name in ENGINES:
        print(f"  {name}", file=out)
    print("\nexample: claude-harness name-reconcile --json", file=out)
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
    if engine not in ENGINES:
        print(f"claude-harness: unknown engine '{engine}'\n", file=sys.stderr)
        _usage(2)
    script = os.path.join(_engines_dir(), ENGINES[engine])
    if not os.path.exists(script):
        raise SystemExit(f"claude-harness: engine file missing: {script}")
    sys.argv = [script] + argv[1:]            # the engine parses its own argv
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
