"""Tests for selftest.py -- the negative control that proves the detectors detect.

There is a recursion here worth stating plainly: this file tests the thing that tests the tests. The
reason it is not silly is that a selftest which cannot FAIL is exactly the pathology it exists to
catch, and nothing else in the suite would notice. So most of what follows blinds a detector on
purpose and asserts that the selftest goes red.
"""
import json
import os
import shutil
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "selftest.py")
REF_AUDIT = os.path.join(HARNESS, "scripts", "vault-ref-audit.py")


def _run(*args):
    return subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True,
                          cwd=HARNESS, timeout=180)


def test_all_fixtures_pass_as_shipped():
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "detectors are alive" in r.stdout


def test_every_fixture_has_both_halves():
    # A fixture with only must_detect proves the engine emits output, not that it discriminates.
    root = os.path.join(HARNESS, "selftest")
    names = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    assert names, "no fixtures shipped"
    for name in names:
        spec = json.load(open(os.path.join(root, name, "expected.json"), encoding="utf-8"))
        assert spec.get("must_detect"), f"{name} plants no defects"
        assert spec.get("must_not_detect"), f"{name} has no negative controls"


def test_blinding_a_detector_makes_the_selftest_fail(tmp_path):
    # THE test. Remove ref-audit's broken-link reporting and assert the selftest notices. Without
    # this, the selftest could be silently inert and every run would still say "alive".
    backup = tmp_path / "ref-audit.bak"
    shutil.copy2(REF_AUDIT, backup)
    try:
        src = open(REF_AUDIT, encoding="utf-8").read()
        blinded = src.replace('"broken_links": broken_links,', '"broken_links": [],', 1)
        assert blinded != src, "anchor for blinding not found; update this test with the engine"
        open(REF_AUDIT, "w", encoding="utf-8").write(blinded)

        r = _run("--engine", "ref-audit")
        assert r.returncode == 1, "selftest passed while the detector was blind"
        assert "MISSED" in r.stdout
    finally:
        shutil.copy2(backup, REF_AUDIT)

    # and it recovers, so the failure was the blinding rather than a broken fixture
    assert _run("--engine", "ref-audit").returncode == 0


def test_over_firing_detector_also_fails(tmp_path):
    # The other half. A detector that reports the CLEAN note as broken must fail too, otherwise
    # "it found the planted defect" proves nothing.
    backup = tmp_path / "ref-audit2.bak"
    shutil.copy2(REF_AUDIT, backup)
    try:
        src = open(REF_AUDIT, encoding="utf-8").read()
        noisy = src.replace('"broken_links": broken_links,',
                            '"broken_links": broken_links + [{"note": "x.md", "target": "real-target"}],', 1)
        assert noisy != src
        open(REF_AUDIT, "w", encoding="utf-8").write(noisy)

        r = _run("--engine", "ref-audit")
        assert r.returncode == 1, "selftest passed while the detector fired on a clean link"
        assert "OVER-FIRED" in r.stdout
    finally:
        shutil.copy2(backup, REF_AUDIT)
    assert _run("--engine", "ref-audit").returncode == 0


def test_unknown_engine_is_not_a_silent_pass():
    # "No fixtures ran" must never look like "everything passed", which is the same confusion
    # between absent and empty that issue #30 fixed one layer down.
    r = _run("--engine", "no-such-engine")
    assert r.returncode == 2, r.stdout + r.stderr


def test_json_mode_reports_per_check():
    r = _run("--json")
    d = json.loads(r.stdout)
    assert d["failed"] == 0
    assert sum(f["checks"] for f in d["fixtures"]) >= 8
