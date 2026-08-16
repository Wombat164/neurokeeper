"""Tests for hooks-audit.py (issue #27).

A control that lives in .git/ does not exist for anyone who clones, and the failure is silent: the
ruleset sits in the tree looking convincing while the enforcement is on one machine.

There is a second shape these tests care about more, because it is less obvious. Once
core.hooksPath is set, git stops reading .git/hooks ENTIRELY, so any hook still there is executable,
plausible and dead. That is how this repository lost its local secret-scan gate: found by running
this engine against the project that ships the pattern.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "hooks-audit.py")

HOOK = "#!/usr/bin/env bash\nexit 0\n"


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("x\n", encoding="utf-8")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "init")
    return r


def _run(root, *args):
    return subprocess.run([sys.executable, ENGINE, "--root", str(root), *args],
                          capture_output=True, text=True, timeout=60)


def _states(root):
    r = _run(root, "--json")
    return [f["state"] for f in json.loads(r.stdout)["findings"]]


def test_plain_repo_with_no_hooks_is_clean(tmp_path):
    r = _repo(tmp_path)
    assert _run(r, "--check").returncode == 0


def test_not_a_git_repo_is_not_applicable(tmp_path):
    # Exit 2, never 0: "there is nothing to audit here" must not read as "audited and clean".
    d = tmp_path / "plain"
    d.mkdir()
    assert _run(d, "--check").returncode == 2


def test_untracked_hook_is_a_finding(tmp_path):
    # The headline case: a gate that exists on this machine only.
    r = _repo(tmp_path)
    (r / ".git" / "hooks" / "pre-commit").write_text(HOOK, encoding="utf-8")
    assert "untracked-gate" in _states(r)


def test_tracked_and_wired_hook_is_clean(tmp_path):
    # The shape the issue argues for: shipped in the tree, reached via core.hooksPath.
    r = _repo(tmp_path)
    (r / "hooks").mkdir()
    (r / "hooks" / "pre-commit").write_text(HOOK, encoding="utf-8")
    _git(r, "add", "hooks/pre-commit")
    _git(r, "commit", "-qm", "hooks")
    _git(r, "config", "core.hooksPath", "hooks")
    assert _states(r) == []


def test_hook_shadowed_by_hookspath_is_reported(tmp_path):
    # The quiet one. Setting core.hooksPath makes git ignore .git/hooks completely, so a hook left
    # there is dead while looking entirely installed.
    r = _repo(tmp_path)
    (r / "hooks").mkdir()
    (r / "hooks" / "pre-push").write_text(HOOK, encoding="utf-8")
    _git(r, "add", "hooks/pre-push")
    _git(r, "commit", "-qm", "hooks")
    _git(r, "config", "core.hooksPath", "hooks")
    (r / ".git" / "hooks" / "pre-commit").write_text(HOOK, encoding="utf-8")

    findings = json.loads(_run(r, "--json").stdout)["findings"]
    shadowed = [f for f in findings if f["state"] == "shadowed"]
    assert shadowed, findings
    assert shadowed[0]["hook"] == "pre-commit"
    assert shadowed[0]["live_equivalent"] is False   # nothing at the live path does its job


def test_shipped_hooks_that_are_not_wired_are_reported(tmp_path):
    # Intent without wiring: the repo clearly means to gate and git was never told.
    r = _repo(tmp_path)
    (r / "hooks").mkdir()
    (r / "hooks" / "pre-commit").write_text(HOOK, encoding="utf-8")
    _git(r, "add", "hooks/pre-commit")
    _git(r, "commit", "-qm", "hooks")
    assert "not-wired" in _states(r)


def test_hookspath_pointing_nowhere_is_reported(tmp_path):
    # Worst case: hooksPath set to a directory that does not exist means NOTHING runs, including
    # hooks that worked yesterday.
    r = _repo(tmp_path)
    _git(r, "config", "core.hooksPath", "no-such-dir")
    assert "hookspath-missing" in _states(r)


def test_a_manifest_beside_the_hooks_is_not_a_hook(tmp_path):
    # NEGATIVE control. The first run of this engine reported the project's own hooks/hooks.json as
    # an unwired gate, because it counted any file. git only ever invokes the known hook names.
    r = _repo(tmp_path)
    (r / "hooks").mkdir()
    (r / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
    (r / "hooks" / "README.md").write_text("notes\n", encoding="utf-8")
    _git(r, "add", "hooks")
    _git(r, "commit", "-qm", "manifest")
    assert _states(r) == []
