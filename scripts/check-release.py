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
  1. version sync   : pyproject.toml == claude_harness/__init__.py == .claude-plugin/plugin.json
  2. plugin.json    : kebab-case name, non-empty version + description
  3. marketplace.json: kebab-case name, owner.name, >=1 plugin each with a kebab name + a source

This is the cheap, offline half of release validation; the richer `claude plugin validate --strict`
(which may need auth) stays a documented manual/pre-publish step in RELEASING.md.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def main():
    errors = []

    # 1. version sync
    try:
        vers = {
            "pyproject.toml": re.search(r'(?m)^version\s*=\s*"([^"]+)"', _read("pyproject.toml")).group(1),
            "__init__.py": re.search(r'__version__\s*=\s*"([^"]+)"', _read("claude_harness/__init__.py")).group(1),
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

    if errors:
        print("check-release FAIL:")
        for e in errors:
            print("  - " + e)
        sys.exit(1)
    print(f"check-release OK: version {vers['pyproject.toml']} synced; plugin + marketplace manifests valid")


if __name__ == "__main__":
    main()
