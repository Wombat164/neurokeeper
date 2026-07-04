#!/usr/bin/env python3
# @capability:  vault-lib
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/_vault_lib.py
# @prompt:      (none)
# @adapters:    import (shared helper)
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Shared helpers for the vault-taxonomy engines (the DRY core they all import).

Vault path + scan-exclusions come from the environment so the engines are vault-agnostic:
  VAULT_ROOT          - the vault directory (default: cwd)
  VAULT_SCAN_EXCLUDE  - comma-separated dir prefixes to skip (default: .obsidian,.claude,.git,.trash)

Provides: md_files() walk, split_frontmatter()/parse_frontmatter(), folder_suffixes() (for link-aware
path matching), kebabify() (code/acronym-preserving slug), within_vault()/safe_write() (the symlink +
path-traversal write guard), force_utf8_stdout() (cross-platform UTF-8 stdout). One definition, imported
by every engine.
"""
import os, re, sys

VAULT = os.environ.get("VAULT_ROOT") or os.getcwd()
SCAN_EXCLUDE = tuple(x for x in (os.environ.get("VAULT_SCAN_EXCLUDE")
                                 or ".obsidian,.claude,.git,.trash").split(",") if x)

# Soft cap on a frontmatter block before YAML parsing -- guards yaml.safe_load against alias-bomb /
# billion-laughs style amplification on hostile note content (the parser is bounded, not the input).
FM_MAX_BYTES = 64 * 1024

# OPTIONAL forbidden-zones enforcement for the mutators. Comma-separated reldir prefixes; when set, a
# mutator SKIPS writing any file whose reldir matches. Default UNSET => no skipping (the current
# attended-exemption behaviour: an operator watching the run + git audit is the control).
FORBIDDEN_ZONES = tuple(z.strip() for z in (os.environ.get("VAULT_FORBIDDEN_ZONES") or "").split(",")
                        if z.strip())


def in_forbidden_zone(reldir, zones=None):
    """True iff reldir is, or sits under, a VAULT_FORBIDDEN_ZONES prefix. UNSET zones => always False."""
    zones = FORBIDDEN_ZONES if zones is None else zones
    if not zones or not reldir:
        return False
    rel = reldir.replace(os.sep, "/").strip("/")
    for z in zones:
        z = z.replace(os.sep, "/").strip("/")
        if z and (rel == z or rel.startswith(z + "/")):
            return True
    return False


def force_utf8_stdout():
    """Best-effort: make stdout/stderr emit UTF-8 on every platform. Windows consoles default to a
    legacy codepage (cp1252), which corrupts non-ASCII when `--json` output is redirected to a file.
    Guarded: a no-op on streams that lack reconfigure() (older Pythons) or are already wrapped."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


class VaultWriteError(Exception):
    """A write/rename was refused because it would escape the vault (symlink or out-of-vault path)."""


def within_vault(path, vault=None):
    """True iff realpath(path) is the vault root or inside it (case-insensitive on Windows)."""
    root = os.path.normcase(os.path.realpath(vault or VAULT))
    real = os.path.normcase(os.path.realpath(path))
    return real == root or real.startswith(root + os.sep)


def safe_write(path, text, newline=""):
    """Write `text` to a REAL file confined to the vault. Refuses (raises VaultWriteError) if `path`
    is a symlink, or if it resolves outside realpath(VAULT) -- a symlink-escape / path-traversal guard
    for the bulk mutators. newline='' preserves the file's existing CRLF/LF. Returns the path written."""
    if os.path.islink(path):
        raise VaultWriteError(f"refusing to write through symlink: {path}")
    if not within_vault(path):
        raise VaultWriteError(f"refusing to write outside vault: {path}")
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)
    return path

def md_files(vault=None, exclude=None):
    """Yield (abspath, reldir) for every .md under vault, skipping excluded dir prefixes."""
    vault = vault or VAULT
    exclude = SCAN_EXCLUDE if exclude is None else exclude
    for root, dirs, files in os.walk(vault):
        rel = os.path.relpath(root, vault); rel = "" if rel == "." else rel
        if any(rel == e or rel.startswith(e + os.sep) for e in exclude):
            dirs[:] = []; continue
        dirs[:] = [d for d in dirs if not d.startswith(".")]  # Obsidian ignores dot-dirs (tool caches, .obsidian, .git, ...) (issue #3)
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(root, f), rel

def split_frontmatter(text):
    """Return (frontmatter_body, rest_including_closing_fence) or (None, text) if no frontmatter."""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    return (text[3:end], text[end:]) if end != -1 else (None, text)

def parse_frontmatter(text):
    """Parsed frontmatter dict, None if absent, or {'__parse_error__': True} on YAML error / oversize."""
    fm, _ = split_frontmatter(text)
    if fm is None:
        return None
    if len(fm.encode("utf-8", "replace")) > FM_MAX_BYTES:
        sys.stderr.write(f"WARN: frontmatter block > {FM_MAX_BYTES} bytes; skipping YAML parse "
                         "(alias-bomb guard)\n")
        return {"__parse_error__": True}
    try:
        import yaml
        return yaml.safe_load(fm) or {}
    except Exception:
        return {"__parse_error__": True}

def folder_suffixes(vault=None, exclude=(".git", ".trash")):
    """All real-folder path-SUFFIXES ('a/b/c/','b/c/','c/') for link-aware path matching
    (Obsidian links use shortest unique paths). Rejects '/'-in-title false folders."""
    vault = vault or VAULT
    out = set()
    for root, dirs, _ in os.walk(vault):
        rel = os.path.relpath(root, vault).replace(os.sep, "/")
        if rel == "." or rel.split("/")[0] in exclude:
            continue
        segs = rel.split("/")
        for i in range(len(segs)):
            out.add("/".join(segs[i:]) + "/")
    return out

DASH = re.compile(r"\s*(?:--|[—–])\s*")
_SPLIT = re.compile(r"[\s_/\-–—]+")
CODE_RE = re.compile(r"^[A-Z]{1,4}[0-9][A-Z0-9]*$")   # code-like stems: AB12 CD345 EF6 A10 Q4 (uppercase+digit, preserved verbatim)

def kebabify(stem):
    """Full kebab, preserving uppercase dossier-codes + all-caps acronyms (>=2)."""
    toks = []
    for tok in _SPLIT.split(stem):
        c = re.sub(r"[^A-Za-z0-9]", "", tok)
        if c:
            toks.append(c if (CODE_RE.match(c) or (c.isupper() and len(c) >= 2)) else c.lower())
    return "-".join(toks)
