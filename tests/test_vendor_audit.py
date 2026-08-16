"""Tests for vendor-audit.py (issue #32).

The failure this engine exists for: a file kept as a resident copy ON PURPOSE, because it is called
from outside the consumer's tree and a shim would break that caller, then documented as "kept in
sync by hand". One such copy drifted to 311 lines against upstream's 416, missing a flag and four
functions, and nothing noticed, because a stale analyzer reports cheerfully.

The subtle contract, and what most of these tests are about: it must report that UPSTREAM MOVED,
never that the two files DIFFER. They always differ. A check that fires constantly is one nobody
reads, which is how the original drift survived in the first place.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vendor-audit.py")


def _setup(tmp_path, upstream_text="upstream v1\n", local_text="local copy, quite different\n",
           sha=None, why="called by another repo's gate; must work with no clone here"):
    (tmp_path / "up").mkdir()
    (tmp_path / "loc").mkdir()
    up = tmp_path / "up" / "engine.py"
    up.write_text(upstream_text, encoding="utf-8")
    (tmp_path / "loc" / "engine.py").write_text(local_text, encoding="utf-8")
    entry = {"local": "loc/engine.py", "upstream": "up/engine.py"}
    if why:
        entry["why_resident"] = why
    if sha == "current":
        import hashlib
        # Hash the FILE, not the string it came from. write_text() translates newlines on Windows,
        # so sha256(text.encode()) is not the sha of the bytes on disk, and a fixture built that way
        # reports drift that does not exist.
        entry["upstream_sha256"] = hashlib.sha256(up.read_bytes()).hexdigest()
        entry["reconciled"] = "2026-08-16"
    elif sha:
        entry["upstream_sha256"] = sha
        entry["reconciled"] = "2026-01-01"
    man = tmp_path / "vendored.json"
    man.write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    return man, up


def _run(manifest, *args):
    env = dict(os.environ, VENDOR_MANIFEST=str(manifest))
    return subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True, env=env)


def test_unconfigured_is_a_skip_not_a_failure(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "VENDOR_MANIFEST"}
    r = subprocess.run([sys.executable, ENGINE, "--check"], capture_output=True, text=True, env=env)
    assert r.returncode == 2, r.stderr


def test_manifest_named_but_missing_is_an_error(tmp_path):
    # Configured and unreachable is a defect, not a skip: the same distinction as issue #30.
    r = _run(tmp_path / "no-such-manifest.json", "--check")
    assert r.returncode == 3, (r.returncode, r.stderr)


def test_wildly_different_files_are_NOT_a_finding(tmp_path):
    # The heart of it. Local and upstream differ enormously and that is the intended state; as long
    # as upstream has not moved since reconciliation, there is nothing to say.
    man, _ = _setup(tmp_path, sha="current")
    r = _run(man, "--check")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "still reconciled" in r.stdout


def test_upstream_moving_is_the_finding(tmp_path):
    man, up = _setup(tmp_path, sha="current")
    up.write_text("upstream v2, with a new flag\n", encoding="utf-8")
    r = _run(man, "--check")
    assert r.returncode == 1, r.stdout
    assert "upstream-moved" in r.stdout


def test_local_edits_alone_never_trigger(tmp_path):
    # A consumer editing their own resident copy is normal and is not upstream's business.
    man, _ = _setup(tmp_path, sha="current")
    (tmp_path / "loc" / "engine.py").write_text("local, heavily customised\n", encoding="utf-8")
    assert _run(man, "--check").returncode == 0


def test_absent_upstream_is_not_drift(tmp_path):
    # On a machine without the source checked out there is nothing to compare, and that is exactly
    # the situation the resident copy exists for. It must not read as a failure.
    man, up = _setup(tmp_path, sha="current")
    up.unlink()
    r = _run(man, "--check")
    assert r.returncode == 0, r.stdout
    assert "upstream-absent" in r.stdout


def test_entry_without_a_stated_reason_is_flagged(tmp_path):
    man, _ = _setup(tmp_path, sha="current", why=None)
    r = _run(man, "--check")
    assert "unexplained" in r.stdout


def test_adopt_records_a_baseline_and_clears_the_finding(tmp_path):
    man, up = _setup(tmp_path, sha="current")
    up.write_text("upstream v2\n", encoding="utf-8")
    assert _run(man, "--check").returncode == 1
    assert _run(man, "--adopt").returncode == 0
    assert _run(man, "--check").returncode == 0
    saved = json.loads(man.read_text(encoding="utf-8"))["entries"][0]
    assert saved["upstream_sha256"] and saved["reconciled"]


def test_json_mode_carries_the_findings(tmp_path):
    man, up = _setup(tmp_path, sha="current")
    up.write_text("moved\n", encoding="utf-8")
    r = _run(man, "--json")
    d = json.loads(r.stdout)
    assert d["entries"] == 1
    assert d["findings"][0]["state"] == "upstream-moved"
