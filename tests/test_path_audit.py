"""Tests for path-audit (issue #40), which closes principle O1.

A structural change breaks things that never mention it. Renaming or moving a repository leaves
worktrees, editable installs, links and hook configuration naming the old location, and nothing
announces it. The failure is the project's central one with an extra turn: a rollback copy usually
still exists at the old path, so a tool does not merely succeed, it succeeds against real, stale
content.

This is not hypothetical. Renaming this repository broke both of its worktrees earlier today.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "path-audit.py")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _repo(tmp_path, name="repo"):
    r = tmp_path / name
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("x\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    return r


def _run(root, *args):
    return subprocess.run([sys.executable, ENGINE, "--root", str(root), *args],
                          capture_output=True, text=True, timeout=90)


def _states(root):
    return [f["state"] for f in json.loads(_run(root, "--json").stdout)["findings"]]


def test_a_plain_repo_is_clean(tmp_path):
    assert _run(_repo(tmp_path), "--check").returncode == 0


def test_not_a_git_repo_is_not_applicable(tmp_path):
    # Exit 2, never 0: "nothing to audit here" must not read as "audited and clean".
    d = tmp_path / "plain"
    d.mkdir()
    assert _run(d, "--check").returncode == 2


def test_a_healthy_worktree_is_clean(tmp_path):
    r = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git(r, "worktree", "add", "-q", str(wt), "-b", "side")
    assert _states(r) == []


def test_renaming_the_parent_breaks_the_worktree_and_is_caught(tmp_path):
    """The exact failure that happened here: the pointer names a gitdir that no longer resolves."""
    r = _repo(tmp_path, "before")
    wt = tmp_path / "wt"
    _git(r, "worktree", "add", "-q", str(wt), "-b", "side")
    assert _git(wt, "status", "--porcelain").returncode == 0     # healthy first

    moved = tmp_path / "after"
    os.rename(r, moved)

    # The worktree is now broken: git inside it cannot find its repository.
    assert _git(wt, "status", "--porcelain").returncode != 0

    states = _states(moved)
    assert "worktree-broken" in states, states
    finding = [f for f in json.loads(_run(moved, "--json").stdout)["findings"]
               if f["state"] == "worktree-broken"][0]
    assert "worktree repair" in finding["detail"]                 # carries the remedy, not just the fault


def test_repair_clears_the_finding(tmp_path):
    # A check that cannot go green after the documented fix teaches people to ignore it.
    r = _repo(tmp_path, "before")
    wt = tmp_path / "wt"
    _git(r, "worktree", "add", "-q", str(wt), "-b", "side")
    moved = tmp_path / "after"
    os.rename(r, moved)
    assert "worktree-broken" in _states(moved)

    _git(moved, "worktree", "repair", str(wt))
    assert "worktree-broken" not in _states(moved)


def test_a_deleted_worktree_directory_is_reported_as_stale(tmp_path):
    import shutil
    r = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git(r, "worktree", "add", "-q", str(wt), "-b", "side")
    shutil.rmtree(wt)
    assert "worktree-stale" in _states(r)


def test_hookspath_naming_nothing_is_reported(tmp_path):
    # The worst case: not one hook runs, including ones that worked yesterday.
    r = _repo(tmp_path)
    _git(r, "config", "core.hooksPath", "hooks-that-moved")
    assert "hookspath-missing" in _states(r)


def test_a_present_hookspath_is_clean(tmp_path):
    r = _repo(tmp_path)
    (r / "hooks").mkdir()
    _git(r, "config", "core.hooksPath", "hooks")
    assert "hookspath-missing" not in _states(r)
