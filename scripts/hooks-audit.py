#!/usr/bin/env python3
# @capability:  hooks-audit
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/hooks-audit.py
# @prompt:      (none)
# @adapters:    cli, ci
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         wiki/content/reference/index.md
"""hooks-audit.py -- find gates that look installed and do not run.

A control that lives in `.git/` does not exist for anyone who clones. `.git/hooks` is machine-local
by design, so a gate placed there is a gate exactly one person has, and nothing reports the absence
on every other machine: the ruleset is right there in the tree, tracked and visible, which is what
makes it convincing.

There is a second, quieter shape. Once `core.hooksPath` is set, git stops reading `.git/hooks`
ENTIRELY. Any hook still sitting there is shadowed: executable, plausible, and dead. Someone
inspecting `.git/hooks` sees a pre-commit and concludes the repository is gated.

Found in the wild while this engine was being written, in the repository that ships the pattern: a
gitleaks secret scan in `.git/hooks/pre-commit`, shadowed by a `core.hooksPath` set later, silently
not running on any commit since.

What it reports:

  shadowed          a hook in .git/hooks that cannot run, because hooksPath points elsewhere
  untracked-gate    a live hook that git does not track: a control only this machine has
  hookspath-missing core.hooksPath points at a directory that is not there, so NOTHING runs
  not-wired         the repo ships a hooks directory but hooksPath does not point at it

  hooks-audit.py --check     # exit 0 clean, 1 findings, 2 not a git repository
  hooks-audit.py --json
"""
import argparse
import json
import os
import subprocess
import sys

EXIT_OK, EXIT_FINDINGS, EXIT_NOT_APPLICABLE = 0, 1, 2

# Candidate directories a project uses to ship tracked hooks. Presence of one means the project
# INTENDS its gates to travel, which is what makes "not wired" a finding rather than a preference.
SHIPPED_DIRS = ("hooks", "bootstrap/hooks", ".githooks", "githooks")


def git(root, *args):
    try:
        p = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


# git only ever invokes these names. Anything else in a hooks directory is a manifest, a helper or
# a README, and counting it as a hook produces confident nonsense: the first run of this engine
# reported the project's own hooks/hooks.json as an unwired gate.
HOOK_NAMES = {
    "applypatch-msg", "pre-applypatch", "post-applypatch", "pre-commit", "pre-merge-commit",
    "prepare-commit-msg", "commit-msg", "post-commit", "pre-rebase", "post-checkout", "post-merge",
    "pre-push", "pre-receive", "update", "proc-receive", "post-receive", "post-update",
    "reference-transaction", "push-to-checkout", "pre-auto-gc", "post-rewrite",
    "sendemail-validate", "fsmonitor-watchman", "post-index-change",
}


def is_hook(path):
    """True only for a file git would actually invoke.

    Executability is deliberately NOT required: git runs hooks on Windows regardless of the POSIX
    bit, and testing it there reports absence for a gate that works.
    """
    return os.path.isfile(path) and os.path.basename(path) in HOOK_NAMES


def audit(root):
    findings = []
    if not git(root, "rev-parse", "--is-inside-work-tree"):
        return None

    effective = git(root, "rev-parse", "--git-path", "hooks")
    effective_abs = os.path.normpath(os.path.join(root, effective)) if effective else ""
    hooks_path_cfg = git(root, "config", "core.hooksPath")
    dotgit = os.path.normpath(os.path.join(git(root, "rev-parse", "--git-dir") or ".git", "hooks"))
    dotgit_abs = os.path.normpath(os.path.join(root, dotgit))

    if hooks_path_cfg and not os.path.isdir(effective_abs):
        findings.append({"state": "hookspath-missing", "path": effective_abs,
                         "detail": "core.hooksPath names a directory that is not there, so NO hook "
                                   "runs at all, including any that used to work"})

    # Shadowed: something in .git/hooks that git will never consult.
    if os.path.normcase(effective_abs) != os.path.normcase(dotgit_abs) and os.path.isdir(dotgit_abs):
        for name in sorted(os.listdir(dotgit_abs)):
            p = os.path.join(dotgit_abs, name)
            if not is_hook(p):
                continue
            live = os.path.join(effective_abs, name)
            findings.append({
                "state": "shadowed", "hook": name, "path": p,
                "detail": ("this hook cannot run: core.hooksPath points at "
                           f"{effective}. An equivalent {'exists' if os.path.isfile(live) else 'does NOT exist'} "
                           "at the live path"),
                "live_equivalent": os.path.isfile(live)})

    # Untracked: a live hook git does not carry, so it exists on this machine only.
    if os.path.isdir(effective_abs):
        for name in sorted(os.listdir(effective_abs)):
            p = os.path.join(effective_abs, name)
            if not is_hook(p):
                continue
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if not git(root, "ls-files", "--error-unmatch", rel):
                findings.append({"state": "untracked-gate", "hook": name, "path": p,
                                 "detail": "this gate is not tracked, so it exists on this machine "
                                           "only and every clone is ungated"})

    # Intent without wiring: the project ships hooks and git is not told to use them.
    for cand in SHIPPED_DIRS:
        d = os.path.join(root, cand)
        if os.path.isdir(d) and any(is_hook(os.path.join(d, n)) for n in os.listdir(d)):
            if os.path.normcase(os.path.normpath(d)) != os.path.normcase(effective_abs):
                findings.append({"state": "not-wired", "path": cand,
                                 "detail": f"the repo ships hooks in {cand} and core.hooksPath is "
                                           f"{hooks_path_cfg or 'unset'}, so they do not run here. "
                                           f"Wire with: git config core.hooksPath {cand}"})
    return {"root": root, "hooks_path_config": hooks_path_cfg or None,
            "effective_hooks_dir": effective, "findings": findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.environ.get("VAULT_ROOT") or ".")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = audit(os.path.abspath(args.root))
    if result is None:
        print(f"hooks-audit: {args.root} is not a git repository; nothing to audit.", file=sys.stderr)
        return EXIT_NOT_APPLICABLE

    if args.json:
        print(json.dumps(result, indent=2))
        return EXIT_FINDINGS if result["findings"] else EXIT_OK

    f = result["findings"]
    print(f"hooks-audit: effective hooks dir is {result['effective_hooks_dir']}"
          f" (core.hooksPath {result['hooks_path_config'] or 'unset'})")
    if not f:
        print("hooks-audit OK: every gate present here is one a clone would also get")
        return EXIT_OK
    print(f"  {len(f)} finding(s)")
    for x in f:
        print(f"  [{x['state']}] {x.get('hook', x.get('path'))}")
        print(f"      {x['detail']}")
    return EXIT_FINDINGS


if __name__ == "__main__":
    sys.exit(main())
