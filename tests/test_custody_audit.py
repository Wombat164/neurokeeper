"""Tests for custody-audit.py (issue #24).

Every other engine validates CONTENT and passes happily whether or not that content has ever been
committed, pushed or backed up. These lock the four durability questions, and most of the tests are
about what must NOT fire: a custody check that reports on healthy artifacts gets switched off, and
then reports nothing about the unhealthy ones either.
"""
import json
import os
import subprocess
import sys
import time

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "custody-audit.py")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "kept.md").write_text("content\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    return r


def _manifest(tmp_path, **body):
    p = tmp_path / "custody.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _run(root, manifest, *args):
    env = dict(os.environ, CUSTODY_MANIFEST=str(manifest))
    env.pop("VAULT_ROOT", None)
    return subprocess.run([sys.executable, ENGINE, "--root", str(root), *args],
                          capture_output=True, text=True, env=env, timeout=90)


def _states(root, manifest):
    r = _run(root, manifest, "--json")
    return [f["state"] for f in json.loads(r.stdout)["findings"]]


def test_unconfigured_is_a_skip(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "CUSTODY_MANIFEST"}
    r = subprocess.run([sys.executable, ENGINE, "--check"], capture_output=True, text=True, env=env)
    assert r.returncode == 2


def test_manifest_named_but_missing_is_an_error(tmp_path):
    r = _run(_repo(tmp_path), tmp_path / "nope.json", "--check")
    assert r.returncode == 3


def test_tracked_artifact_is_clean(tmp_path):
    # NEGATIVE control: the ordinary healthy case must be silent.
    r = _repo(tmp_path)
    m = _manifest(tmp_path, artifacts=[{"path": "kept.md", "disposition": "tracked"}], remotes=[])
    assert _states(r, m) == []


def test_the_silent_gap_is_found(tmp_path):
    # The headline: a file neither tracked nor ignored exists on one disk and nothing says so.
    r = _repo(tmp_path)
    (r / "secret.yaml").write_text("real\n", encoding="utf-8")
    m = _manifest(tmp_path, artifacts=[{"path": "secret.yaml", "disposition": "ignored-ephemeral"}],
                  remotes=[])
    assert "unignored-gap" in _states(r, m)


def test_ignored_encrypted_without_a_counterpart_is_found(tmp_path):
    # The interesting row: "gitignored, sanitised example committed" is a GOOD pattern that nothing
    # enforces, so a new sensitive file joins the gap unnoticed.
    r = _repo(tmp_path)
    (r / ".gitignore").write_text("secret.yaml\n", encoding="utf-8")
    (r / "secret.yaml").write_text("real\n", encoding="utf-8")
    _git(r, "add", ".gitignore")
    _git(r, "commit", "-qm", "ignore")
    m = _manifest(tmp_path, artifacts=[{"path": "secret.yaml", "disposition": "ignored-encrypted",
                                        "encrypted_counterpart": "secret.yaml.age"}], remotes=[])
    assert "counterpart-missing" in _states(r, m)


def test_stale_counterpart_is_found(tmp_path):
    # A backup older than what it backs up is not a backup, and looks identical to a good one.
    r = _repo(tmp_path)
    (r / ".gitignore").write_text("secret.yaml\n", encoding="utf-8")
    (r / "secret.yaml.age").write_text("old-cipher\n", encoding="utf-8")
    _git(r, "add", ".gitignore", "secret.yaml.age")
    _git(r, "commit", "-qm", "cipher")
    time.sleep(0.05)
    (r / "secret.yaml").write_text("newer plaintext\n", encoding="utf-8")
    m = _manifest(tmp_path, artifacts=[{"path": "secret.yaml", "disposition": "ignored-encrypted",
                                        "encrypted_counterpart": "secret.yaml.age"}], remotes=[])
    assert "counterpart-stale" in _states(r, m)


def test_uncommitted_counterpart_is_found(tmp_path):
    # Encrypting and never committing the ciphertext protects against nothing beyond this disk.
    r = _repo(tmp_path)
    (r / ".gitignore").write_text("secret.yaml\n", encoding="utf-8")
    _git(r, "add", ".gitignore")
    _git(r, "commit", "-qm", "ignore")
    (r / "secret.yaml").write_text("real\n", encoding="utf-8")
    time.sleep(0.05)
    (r / "secret.yaml.age").write_text("cipher\n", encoding="utf-8")
    m = _manifest(tmp_path, artifacts=[{"path": "secret.yaml", "disposition": "ignored-encrypted",
                                        "encrypted_counterpart": "secret.yaml.age"}], remotes=[])
    assert "counterpart-untracked" in _states(r, m)


def test_unpushed_commits_are_found(tmp_path):
    # Custody, not content: nothing is wrong with the work, it just exists in one place.
    r = _repo(tmp_path)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    _git(r, "remote", "add", "origin", str(bare))
    _git(r, "push", "-q", "origin", "HEAD")
    (r / "kept.md").write_text("more\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "local only")
    assert "unpushed" in _states(r, _manifest(tmp_path, artifacts=[], remotes=["origin"]))


def test_pushed_repo_is_clean(tmp_path):
    r = _repo(tmp_path)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], capture_output=True)
    _git(r, "remote", "add", "origin", str(bare))
    _git(r, "push", "-q", "origin", "HEAD")
    assert _states(r, _manifest(tmp_path, artifacts=[], remotes=["origin"])) == []


def test_non_canonical_copy_is_found(tmp_path):
    # A rollback copy is complete, valid, and indistinguishable from the original in an editor.
    r = _repo(tmp_path)
    m = _manifest(tmp_path, artifacts=[], remotes=[], canonical_root=str(tmp_path / "elsewhere"))
    assert "non-canonical-copy" in _states(r, m)


def test_stale_receipt_is_found_without_touching_the_scheduler(tmp_path):
    # Receipts, never process introspection: three platforms, three failure modes, no determinism.
    r = _repo(tmp_path)
    rec = r / "receipt.json"
    rec.write_text("{}\n", encoding="utf-8")
    old = time.time() - 72 * 3600
    os.utime(rec, (old, old))
    m = _manifest(tmp_path, artifacts=[], remotes=[],
                  receipts=[{"name": "nightly", "path": "receipt.json", "max_age_hours": 36}])
    assert "receipt-stale" in _states(r, m)


def test_fresh_receipt_is_clean(tmp_path):
    r = _repo(tmp_path)
    (r / "receipt.json").write_text("{}\n", encoding="utf-8")
    m = _manifest(tmp_path, artifacts=[], remotes=[],
                  receipts=[{"name": "nightly", "path": "receipt.json", "max_age_hours": 36}])
    assert _states(r, m) == []
