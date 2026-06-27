#!/usr/bin/env python3
# @capability:  vault-write-guard
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/_vault_guard.py
# @prompt:      (none)
# @adapters:    import (shared helper)
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Shared preflight for bulk vault-write capabilities: refuse to write while Obsidian is running.

The Obsidian Linter reformats/corrupts frontmatter wikilinks on live EXTERNAL bulk writes (2026-06-27
incident: `parent: [[X]]` mangled into a blanked nested list across ~400 files). Pattern doc section 6
mandates this preflight for every mutating-vault capability. Usage:

    from _vault_guard import assert_obsidian_closed
    if apply: assert_obsidian_closed("--force" in sys.argv)
"""
import os, subprocess, sys

def obsidian_running():
    """True / False / None(undeterminable)."""
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Obsidian.exe"],
                                 capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=10).stdout
            return "Obsidian.exe" in out
        r = subprocess.run(["pgrep", "-x", "obsidian"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return None

def assert_obsidian_closed(force=False):
    state = obsidian_running()
    if state is True and not force:
        sys.stderr.write(
            "REFUSING bulk vault write: Obsidian is running. Its Linter corrupts frontmatter "
            "wikilinks on live external writes (2026-06-27 incident). Close Obsidian and retry "
            "(or pass --force to override).\n")
        sys.exit(2)
    if state is None:
        sys.stderr.write("WARN: could not determine whether Obsidian is running; proceeding. "
                         "Ensure Obsidian is closed before bulk vault writes.\n")
