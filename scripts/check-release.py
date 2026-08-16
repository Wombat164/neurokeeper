#!/usr/bin/env python3
# @capability:  check-release
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/check-release.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         RELEASING.md
"""check-release.py -- deterministic pre-release gate. Exit 1 on any violation; run in CI.

Asserts (no auth, no network -- unlike `claude plugin validate`):
  1. version sync   : pyproject.toml == neurokeeper/__init__.py == .claude-plugin/plugin.json
  2. plugin.json    : kebab-case name, non-empty version + description
  3. marketplace.json: kebab-case name, owner.name, >=1 plugin each with a kebab name + a source

This is the cheap, offline half of release validation; the richer `claude plugin validate --strict`
(which may need auth) stays a documented manual/pre-publish step in RELEASING.md.
"""
import json
import os
import re
import sys
import pathlib
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# --- prose version pins (issue #33) ------------------------------------------------------------
#
# Only the refs a reader COPIES are checked. Prose that merely mentions a version ("fixed in 0.3.2")
# is legitimately historical and is none of this check's business: a linter that fires on correct
# text is one nobody reads, which is worse than not having it.
PIN_PATTERNS = [
    (re.compile(r"^\s*rev:\s*v(\d+\.\d+\.\d+)\s*$"), "pre-commit rev"),
    (re.compile(r"uses:\s*[\w.-]+/[\w.-]+@v(\d+\.\d+\.\d+)"), "workflow uses ref"),
    (re.compile(r"^>?\s*(?:\*\*)?Status:?(?:\*\*)?\s*\*\*(\d+\.\d+\.\d+)"), "status line"),
]
SCAN_GLOBS = ("README.md", "docs/**/*.md", "wiki/content/**/*.md")
# Files whose whole purpose is to record what WAS true. Never checked.
SKIP_NAME = ("changelog", "adr-", "roadmap")
# Escape hatch for a single deliberate line, e.g. an example pinned to an older release on purpose.
OPT_OUT = "<!-- pin-ok -->"


def _prose_pins(root=None):
    """Every copyable version ref in the docs: (path, lineno, version, kind, line).

    `root` is a parameter so the check can be tested against a fixture tree rather than only
    against the repository it happens to live in.
    """
    root = pathlib.Path(root or ROOT)
    out = []
    for pattern in SCAN_GLOBS:
        for path in sorted(root.glob(pattern)):
            if any(s in path.name.lower() for s in SKIP_NAME):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if OPT_OUT in line:
                    continue
                for rx, kind in PIN_PATTERNS:
                    m = rx.search(line)
                    if m:
                        out.append((path.relative_to(root).as_posix(), i, m.group(1), kind, line))
                        break
    return out


def _tag_exists(version):
    try:
        r = subprocess.run(["git", "-C", ROOT, "tag", "-l", f"v{version}"],
                           capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return True          # cannot tell: stay quiet rather than cry wolf


def main():
    errors = []

    # 1. version sync
    try:
        vers = {
            "pyproject.toml": re.search(r'(?m)^version\s*=\s*"([^"]+)"', _read("pyproject.toml")).group(1),
            "__init__.py": re.search(r'__version__\s*=\s*"([^"]+)"', _read("neurokeeper/__init__.py")).group(1),
            "plugin.json": json.loads(_read(".claude-plugin/plugin.json")).get("version"),
        }
    except (OSError, AttributeError) as e:
        print(f"check-release FAIL: cannot read a version ({e})")
        sys.exit(1)
    if None in vers.values() or len(set(vers.values())) != 1:
        errors.append(f"version drift: {vers}")

    # 2. plugin.json
    pj = json.loads(_read(".claude-plugin/plugin.json"))
    if not KEBAB.match(pj.get("name", "")):
        errors.append(f"plugin.json name not kebab-case: {pj.get('name')!r}")
    for field in ("version", "description"):
        if not pj.get(field):
            errors.append(f"plugin.json missing {field}")

    # 3. marketplace.json
    mk = json.loads(_read(".claude-plugin/marketplace.json"))
    if not KEBAB.match(mk.get("name", "")):
        errors.append(f"marketplace.json name not kebab-case: {mk.get('name')!r}")
    if not (mk.get("owner") or {}).get("name"):
        errors.append("marketplace.json missing owner.name")
    plugins = mk.get("plugins") or []
    if not plugins:
        errors.append("marketplace.json has no plugins[]")
    for p in plugins:
        if not KEBAB.match(p.get("name", "")):
            errors.append(f"marketplace plugin name not kebab-case: {p.get('name')!r}")
        if not p.get("source"):
            errors.append(f"marketplace plugin {p.get('name')!r} missing source")

    # 4. prose version pins (issue #33)
    #
    # The manifests above are read by tooling that would fail loudly on a mismatch. The refs BELOW
    # are read by humans, who copy them into their own pre-commit config and CI workflow. A stale
    # one hands a reader a toolchain two minor versions behind while every gate reports green, and
    # nobody reports it, because from the outside it just works.
    current = vers["pyproject.toml"]
    pins, warned_tags = _prose_pins(), set()
    for path, lineno, found, kind, line in pins:
        if found != current:
            errors.append(f"stale {kind} in {path}:{lineno}: v{found} (package is {current})\n"
                          f"      {line.strip()[:88]}")
        else:
            warned_tags.add(found)

    if errors:
        print("check-release FAIL:")
        for e in errors:
            print("  - " + e)
        sys.exit(1)

    # A pin can be correct and still unusable, which is the other half of the ordering problem: docs
    # bumped to a version whose tag has not been cut yet resolve to nothing, a harder failure than
    # pointing at an old release. Advisory rather than an error, because bumping the docs BEFORE
    # tagging is the normal release order and must not be blocked.
    for v in sorted(warned_tags):
        if not _tag_exists(v):
            print(f"check-release NOTE: docs pin v{v} and no such tag exists yet. Cut it before "
                  f"publishing, or the quickstart points at a ref that does not resolve.")
    print(f"check-release OK: version {current} synced; {len(pins)} prose pin(s) match; "
          f"plugin + marketplace manifests valid")


if __name__ == "__main__":
    main()
