#!/usr/bin/env python3
# @capability:  path-audit
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/path-audit.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         wiki/content/reference/index.md
"""path-audit.py -- find the things that still point at where this used to be.

Closes principle O1: a structural change breaks things that never mention it.

Every long-lived collection eventually moves. A new disk, off a synced mount, a machine migration, a
repository rename. Every absolute path embedded in tooling, worktrees, editable installs, symlinks
and hook configuration keeps naming the old location, and nothing announces it.

The failure is this project's central one, with an extra twist. A scan rooted at a stale path
reports zero findings and zero findings reads as clean; worse, a rollback copy usually still exists
at the old location, so the tool does not merely succeed, it succeeds against real, stale content.

Observed here while the fix for a different issue was landing: renaming this repository broke every
worktree attached to it. The worktree's pointer named the old path, `git status` inside it returned
`fatal: not a git repository`, and nothing warned at rename time. The commits were never at risk.
The repair command exists. Neither fact helps if nobody knows to look.

What it reports:

  worktree-broken     a worktree whose gitdir pointer does not resolve (repair: git worktree repair)
  worktree-stale      registered, but the working directory is gone
  editable-install    a .pth naming a path for this project that no longer exists
  broken-link         a symlink or junction inside the root whose target is gone
  hookspath-missing   core.hooksPath naming a directory that is not there, so NO hook runs

  path-audit.py --check    # 0 clean, 1 findings, 2 not a git repository
  path-audit.py --json
"""
import argparse
import glob
import json
import os
import site
import subprocess
import sys

EXIT_OK, EXIT_FINDINGS, EXIT_NOT_APPLICABLE = 0, 1, 2


def git(root, *args):
    try:
        p = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=15)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def worktrees(root):
    """Every worktree this repository believes it has, checked against what its pointer says."""
    out = []
    listing = git(root, "worktree", "list", "--porcelain") or ""
    current = {}
    for line in listing.splitlines() + [""]:
        if not line.strip():
            if current.get("worktree"):
                out.append(current)
            current = {}
            continue
        key, _, val = line.partition(" ")
        current[key] = val
    findings = []
    for wt in out:
        path = wt["worktree"]
        if not os.path.isdir(path):
            findings.append({"state": "worktree-stale", "path": path,
                             "detail": "registered as a worktree and the directory is gone. Tidy "
                                       "with: git worktree prune"})
            continue
        # The main worktree has a .git DIRECTORY; a linked one has a .git FILE naming its gitdir.
        dotgit = os.path.join(path, ".git")
        if os.path.isfile(dotgit) and git(path, "rev-parse", "--is-inside-work-tree") is None:
            findings.append({"state": "worktree-broken", "path": path,
                             "detail": "its pointer names a gitdir that does not resolve, usually "
                                       "because the parent repository was renamed or moved. Repair "
                                       f"with: git -C \"{root}\" worktree repair \"{path}\""})
    return findings


def editable_installs(root):
    """A .pth naming this project at a path that no longer exists.

    An editable install is a path written into site-packages at install time. Renaming the checkout
    leaves it naming the old location, and the import then fails or, worse, resolves to a stale copy
    still sitting there.
    """
    findings, name = [], os.path.basename(os.path.abspath(root)).lower()
    dirs = []
    try:
        dirs = list(site.getsitepackages()) + [site.getusersitepackages()]
    except Exception:
        pass
    for d in dirs:
        for p in glob.glob(os.path.join(d, "*.pth")):
            try:
                body = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith(("import ", "#")):
                    continue
                if name not in line.lower():
                    continue
                if not os.path.isdir(line):
                    findings.append({"state": "editable-install", "path": p, "target": line,
                                     "detail": f"names {line}, which does not exist. Re-install "
                                               f"editable from the current location"})
    return findings


def broken_links(root, exclude):
    findings = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in exclude]
        for name in list(dirs) + files:
            p = os.path.join(dirpath, name)
            if os.path.islink(p) and not os.path.exists(p):
                findings.append({"state": "broken-link", "path": p,
                                 "target": os.readlink(p) if hasattr(os, "readlink") else "?",
                                 "detail": "a link whose target is gone. On Windows a dangling "
                                           "junction reports as absent rather than as an error, so "
                                           "a walk through it silently finds nothing"})
    return findings


def hooks_path(root):
    cfg = git(root, "config", "core.hooksPath")
    if not cfg:
        return []
    resolved = cfg if os.path.isabs(cfg) else os.path.join(root, cfg)
    if os.path.isdir(resolved):
        return []
    return [{"state": "hookspath-missing", "path": cfg,
             "detail": "core.hooksPath names a directory that is not there, so NO hook runs at all, "
                       "including any that worked before the move"}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("VAULT_ROOT") or ".")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = os.path.abspath(args.root)

    if git(root, "rev-parse", "--is-inside-work-tree") is None:
        print(f"path-audit: {root} is not a git repository; nothing to audit.", file=sys.stderr)
        return EXIT_NOT_APPLICABLE

    exclude = set(x for x in (os.environ.get("VAULT_SCAN_EXCLUDE")
                              or ".git,node_modules,.venv,__pycache__").split(",") if x)
    findings = (worktrees(root) + editable_installs(root)
                + broken_links(root, exclude) + hooks_path(root))

    if args.json:
        print(json.dumps({"root": root, "findings": findings}, indent=2))
        return EXIT_FINDINGS if findings else EXIT_OK

    if not findings:
        print("path-audit OK: nothing still points at a location this project has left")
        return EXIT_OK
    print(f"path-audit: {len(findings)} finding(s)")
    for f in findings:
        print(f"  [{f['state']}] {f['path']}")
        print(f"      {f['detail']}")
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
