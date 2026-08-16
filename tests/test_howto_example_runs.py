"""The worked example in the extend-with-your-own-engine how-to must actually run.

Extracted from the page itself rather than copied here, so the two cannot drift. A documented
example that no longer works is worse than no example: it is a claim about the code, made with
confidence, that the reader will debug for an hour before doubting.

CONTRIBUTING puts it plainly -- a claim in the docs must match the code. This is that rule with
teeth for the one claim readers will paste into their own repository first.
"""
import os
import re
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOWTO = os.path.join(HARNESS, "wiki", "content", "how-to", "extend-with-your-own-engine.md")


def _example_source():
    if not os.path.isfile(HOWTO):
        pytest.skip("how-to page not present in this checkout")
    doc = open(HOWTO, encoding="utf-8").read()
    blocks = [b for b in re.findall(r"```python\n(.*?)```", doc, re.S) if "acme-owner-audit" in b]
    assert blocks, "the how-to no longer contains the worked example it is built around"
    return blocks[0]


@pytest.fixture
def world(tmp_path):
    """The example engine, its roster, and a collection with one on-roster and one off-roster note."""
    (tmp_path / "engines").mkdir()
    (tmp_path / "engines" / "acme-owner-audit.py").write_text(_example_source(), encoding="utf-8")
    (tmp_path / "roster.txt").write_text("ada.lovelace\ngrace.hopper\nalan.turing\n", encoding="utf-8")
    v = tmp_path / "vault"
    v.mkdir()
    (v / "ok.md").write_text("---\nowner: ada.lovelace\n---\nfine\n", encoding="utf-8")
    (v / "off.md").write_text("---\nowner: charles.babbage\n---\noff roster\n", encoding="utf-8")
    return tmp_path


def _run(world, *args, roster=True):
    env = dict(os.environ)
    env["VAULT_ROOT"] = str(world / "vault")
    env["NEUROKEEPER_ENGINE_PATH"] = str(world / "engines")
    env.pop("OWNER_ROSTER", None)
    if roster:
        env["OWNER_ROSTER"] = str(world / "roster.txt")
    return subprocess.run([sys.executable, "-m", "neurokeeper.cli", "acme-owner-audit", *args],
                          capture_output=True, text=True, cwd=HARNESS, env=env, timeout=120)


def test_it_dispatches_and_finds_the_off_roster_note(world):
    r = _run(world)
    assert r.returncode == 0, r.stderr
    assert "charles.babbage" in r.stdout
    assert "ada.lovelace" not in r.stdout


def test_json_mode_is_machine_readable(world):
    import json
    r = _run(world, "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["count"] == 1
    assert data["unknown_owners"][0]["owner"] == "charles.babbage"


def test_check_gates(world):
    assert _run(world, "--check").returncode == 1


def test_unset_config_is_exit_2_not_a_crash(world):
    # The example teaches the exit contract; if it taught it wrongly, every engine copied from it
    # would report "not configured" as a failure, or worse, a failure as success.
    r = _run(world, roster=False)
    assert r.returncode == 2
    assert "OWNER_ROSTER" in r.stderr


def test_unreadable_config_is_exit_3(world):
    env_pointing_nowhere = world / "engines"          # a directory: set, and not readable as a file
    env = dict(os.environ)
    env["VAULT_ROOT"] = str(world / "vault")
    env["NEUROKEEPER_ENGINE_PATH"] = str(world / "engines")
    env["OWNER_ROSTER"] = str(env_pointing_nowhere)
    r = subprocess.run([sys.executable, "-m", "neurokeeper.cli", "acme-owner-audit"],
                       capture_output=True, text=True, cwd=HARNESS, env=env, timeout=120)
    assert r.returncode == 3, (r.returncode, r.stderr)


def test_it_joins_the_doctor_rollup_as_the_page_says(world):
    # The page gives the example an '@doctor: gate' header. That is a promise about the roll-up.
    import json
    env = dict(os.environ)
    env["VAULT_ROOT"] = str(world / "vault")
    env["NEUROKEEPER_ENGINE_PATH"] = str(world / "engines")
    env["OWNER_ROSTER"] = str(world / "roster.txt")
    env.pop("CLAUDE_MEMORY_DIR", None)
    env.pop("FRONTMATTER_SCHEMA", None)
    r = subprocess.run([sys.executable, os.path.join(HARNESS, "scripts", "vault-doctor.py"),
                        "--json", "--check"], capture_output=True, text=True, env=env, timeout=180)
    data = json.loads(r.stdout)
    entry = {e["engine"]: e for e in data["engines"]}["acme-owner-audit"]
    assert entry["origin"] == "external"
    assert entry["state"] == "fail"          # the off-roster note is a real finding
    assert r.returncode == 1
