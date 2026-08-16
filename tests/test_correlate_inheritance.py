"""Tests for identifier inheritance in correlate (issue #21, ADR-0005).

Treating identifiers as flat tokens loses most of the signal in a real collection. An item names the
specific thing (an agreement); notes are written at the level people think at (the vehicle it sits
under). Nothing about that relationship is ambiguous to a human, and a flat matcher scores zero.

The weighting is the part worth guarding. Inheritance is weaker evidence than a direct hit, because
the parent is genuinely about the child AND about that child's siblings. If the two ever scored
alike, a vehicle-level note would outrank the note actually about the agreement.
"""
import json
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vault-correlate.py")
yaml = pytest.importorskip("yaml")

REGISTER = {
    "tiers": ["vehicle", "request", "agreement"],
    "tier_fields": {"vehicle": "programme"},
    "entities": {
        "ALPHA": {"tier": "vehicle", "source": "decided"},
        "ALPHA-REQ": {"tier": "request", "source": "harvested"},
        "2026-AG-4": {"tier": "agreement", "source": "harvested"},
    },
    "edges": [
        {"from": "ALPHA-REQ", "type": "parent", "to": "ALPHA"},
        {"from": "2026-AG-4", "type": "parent", "to": "ALPHA-REQ"},
    ],
}


def _setup(tmp_path, notes):
    v = tmp_path / "v"
    v.mkdir()
    for name, fm in notes.items():
        v.joinpath(name).write_text(
            "---\n" + "\n".join(f"{k}: {x}" for k, x in fm.items()) + "\n---\nbody\n",
            encoding="utf-8")
    reg = tmp_path / "register.yaml"
    reg.write_text(yaml.safe_dump(REGISTER), encoding="utf-8")
    item = tmp_path / "item.json"
    item.write_text(json.dumps({"id": "m1", "title": "2026-AG-4 invoice 12",
                                "body": "attached", "codes": ["2026-AG-4"]}), encoding="utf-8")
    return v, reg, item


def _run(v, item, reg=None):
    env = dict(os.environ, VAULT_ROOT=str(v))
    env.pop("IDENTIFIER_REGISTER", None)
    if reg:
        env["IDENTIFIER_REGISTER"] = str(reg)
    r = subprocess.run([sys.executable, ENGINE, "--item-file", str(item)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["items"][0]


def test_without_a_register_the_parent_note_is_not_reached(tmp_path):
    # The status quo the issue describes: the identifier channel scores zero.
    v, reg, item = _setup(tmp_path, {"vehicle.md": {"title": "Alpha overview", "programme": "ALPHA"}})
    assert _run(v, item)["candidates"] == []


def test_with_a_register_the_item_reaches_its_parent_note(tmp_path):
    v, reg, item = _setup(tmp_path, {"vehicle.md": {"title": "Alpha overview", "programme": "ALPHA"}})
    cands = _run(v, item, reg)["candidates"]
    assert cands, "inheritance produced no candidate"
    assert cands[0]["note"] == "vehicle.md"
    assert any("inherits ALPHA" in e for e in cands[0]["evidence"]), cands[0]["evidence"]


def test_inherited_evidence_never_outscores_a_direct_hit(tmp_path):
    # The guard that keeps the feature honest: the note actually about the agreement must win.
    v, reg, item = _setup(tmp_path, {
        "vehicle.md": {"title": "Alpha overview", "programme": "ALPHA"},
        "agreement.md": {"title": "The agreement itself", "contract": "2026-AG-4"},
    })
    cands = _run(v, item, reg)["candidates"]
    assert cands[0]["note"] == "agreement.md", [(c["note"], c["score"]) for c in cands]
    direct = cands[0]["score"]
    inherited = next(c["score"] for c in cands if c["note"] == "vehicle.md")
    assert inherited < direct


def test_inheritance_decays_with_distance(tmp_path):
    # A grandparent is weaker evidence than a parent, and the scores must say so.
    v, reg, item = _setup(tmp_path, {
        "parent.md": {"title": "The request", "programme": "ALPHA-REQ"},
        "grandparent.md": {"title": "Alpha overview", "programme": "ALPHA"},
    })
    cands = {c["note"]: c["score"] for c in _run(v, item, reg)["candidates"]}
    assert cands["parent.md"] > cands["grandparent.md"], cands


def test_a_register_named_but_unusable_is_an_error(tmp_path):
    # Scoring on silently would lose the inheritance signal and still look like a clean run.
    v, reg, item = _setup(tmp_path, {"vehicle.md": {"title": "Alpha", "programme": "ALPHA"}})
    env = dict(os.environ, VAULT_ROOT=str(v), IDENTIFIER_REGISTER=str(tmp_path / "absent.yaml"))
    r = subprocess.run([sys.executable, ENGINE, "--item-file", str(item)],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 2, r.stdout
