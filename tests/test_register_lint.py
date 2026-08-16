"""Tests for the identifier register and register-lint (issues #21, #22, #23, #25; ADR-0005).

Structural validation asks whether a field is KNOWN. These cover the gap it cannot reach: whether a
value is the right KIND of thing.

The load-bearing tests are the provenance ones. `source` is the limit on enforcement, and if a
`harvested` or `inferred` entry can block a write or drive a fix, then a name a tool invented
becomes canonical by being the only spelling that passes a check, and the register has started
writing reality rather than describing it.
"""
import json
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "register-lint.py")
sys.path.insert(0, os.path.join(HARNESS, "scripts"))

yaml = pytest.importorskip("yaml")
from _register import ENFORCEMENT, RegisterError, load  # noqa: E402

REGISTER = {
    "tiers": ["vehicle", "request", "agreement", "platform"],
    "tier_fields": {"vehicle": "programme", "request": "request",
                    "agreement": "contract", "platform": "platform"},
    "entities": {
        "ALPHA": {"tier": "vehicle", "source": "decided", "aliases": ["alpha-programme"]},
        "ALPHA-REQ": {"tier": "request", "source": "harvested"},
        "2026-AG-4": {"tier": "agreement", "source": "harvested"},
        "ACME-DATA": {"tier": "platform", "source": "inferred"},
    },
    "edges": [
        {"from": "ALPHA-REQ", "type": "parent", "to": "ALPHA"},
        {"from": "2026-AG-4", "type": "parent", "to": "ALPHA-REQ"},
    ],
}


def _reg(tmp_path, data=None):
    p = tmp_path / "register.yaml"
    p.write_text(yaml.safe_dump(data or REGISTER), encoding="utf-8")
    return p


def _vault(tmp_path, notes):
    v = tmp_path / "v"
    v.mkdir(exist_ok=True)
    for name, fm in notes.items():
        body = "---\n" + "\n".join(f"{k}: {val}" for k, val in fm.items()) + "\n---\ntext\n"
        (v / name).write_text(body, encoding="utf-8")
    return v


def _run(vault, reg, *args):
    env = dict(os.environ, IDENTIFIER_REGISTER=str(reg), VAULT_ROOT=str(vault))
    return subprocess.run([sys.executable, ENGINE, "--root", str(vault), *args],
                          capture_output=True, text=True, env=env, timeout=90)


def _states(vault, reg):
    r = _run(vault, reg, "--json")
    return [f["state"] for f in json.loads(r.stdout)["findings"]]


# --- configuration contract --------------------------------------------------------------------

def test_unconfigured_is_a_skip(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "IDENTIFIER_REGISTER"}
    r = subprocess.run([sys.executable, ENGINE, "--check"], capture_output=True, text=True, env=env)
    assert r.returncode == 2


def test_register_named_but_missing_is_an_error(tmp_path):
    # A scan against nothing reports zero findings, and zero findings reads as conformant.
    r = _run(_vault(tmp_path, {}), tmp_path / "absent.yaml", "--check")
    assert r.returncode == 3


def test_entry_without_provenance_is_refused(tmp_path):
    bad = {"tiers": ["vehicle"], "entities": {"X": {"tier": "vehicle"}}}
    with pytest.raises(RegisterError, match="source must be one of"):
        load(str(_reg(tmp_path, bad)))


# --- the four classes --------------------------------------------------------------------------

def test_conformant_collection_is_clean(tmp_path):
    v = _vault(tmp_path, {"a.md": {"programme": "ALPHA", "contract": "2026-AG-4"}})
    assert _states(v, _reg(tmp_path)) == []


def test_wrong_category(tmp_path):
    # Both fields are known and both values are strings, so structural validation sees nothing.
    v = _vault(tmp_path, {"a.md": {"request": "2026-AG-4"}})
    assert "wrong-category" in _states(v, _reg(tmp_path))


def test_alias(tmp_path):
    v = _vault(tmp_path, {"a.md": {"programme": "alpha-programme"}})
    assert "alias" in _states(v, _reg(tmp_path))


def test_compound(tmp_path):
    v = _vault(tmp_path, {"a.md": {"contract": "ALPHA/2026-AG-4"}})
    assert "compound" in _states(v, _reg(tmp_path))


def test_unknown(tmp_path):
    v = _vault(tmp_path, {"a.md": {"programme": "NOT-A-THING"}})
    assert "unknown" in _states(v, _reg(tmp_path))


def test_a_date_is_not_a_compound(tmp_path):
    # NEGATIVE control. The compound rule must not fire on ordinary hyphenated values; both parts
    # have to resolve against the register before anything is claimed.
    v = _vault(tmp_path, {"a.md": {"programme": "2026-08-16"}})
    assert "compound" not in _states(v, _reg(tmp_path))


# --- provenance: the limit on enforcement ------------------------------------------------------

def test_inferred_entries_are_never_enforceable(tmp_path):
    # The failure this prevents: a tool's guess becoming canonical by being the only spelling that
    # passes a check.
    v = _vault(tmp_path, {"a.md": {"programme": "ACME-DATA"}})
    r = _run(v, _reg(tmp_path), "--json")
    findings = json.loads(r.stdout)["findings"]
    assert findings, "expected a wrong-category finding"
    assert all(f["enforceable"] is False for f in findings), findings
    assert all(f["fixable"] is False for f in findings), findings


def test_harvested_is_enforceable_but_never_fixable(tmp_path):
    # It may be the REGISTER that is wrong, so a fixer must not rewrite the document toward it.
    v = _vault(tmp_path, {"a.md": {"programme": "2026-AG-4"}})
    f = json.loads(_run(v, _reg(tmp_path), "--json").stdout)["findings"][0]
    assert f["enforceable"] is True
    assert f["fixable"] is False


def test_decided_is_both(tmp_path):
    v = _vault(tmp_path, {"a.md": {"contract": "ALPHA"}})
    f = json.loads(_run(v, _reg(tmp_path), "--json").stdout)["findings"][0]
    assert f["enforceable"] is True and f["fixable"] is True


def test_message_hedges_for_harvested_and_asserts_for_decided(tmp_path):
    # Wording is part of the contract: asserting the DOCUMENT is wrong, when the register is the
    # weaker party, is how a register stops being questioned and starts being obeyed.
    v = _vault(tmp_path, {"a.md": {"contract": "ALPHA"}, "b.md": {"programme": "2026-AG-4"}})
    out = json.loads(_run(v, _reg(tmp_path), "--json").stdout)["findings"]
    decided = [f for f in out if f["value"] == "ALPHA"][0]
    harvested = [f for f in out if f["value"] == "2026-AG-4"][0]
    assert decided["detail"].startswith("the register says")
    assert "possibly wrong" in harvested["detail"]


def test_enforcement_table_is_the_single_source(tmp_path):
    # Three consumers read this. A limit re-implemented three times is one applied twice.
    assert ENFORCEMENT["inferred"]["enforce"] is False
    assert ENFORCEMENT["harvested"]["fix"] is False
    assert ENFORCEMENT["decided"]["fix"] is True


# --- hierarchy (the half correlate consumes) ---------------------------------------------------

def test_parents_walks_the_chain(tmp_path):
    reg = load(str(_reg(tmp_path)))
    assert reg.parents("2026-AG-4") == ["ALPHA-REQ", "ALPHA"]
    assert reg.parents("ALPHA") == []


def test_parents_is_cycle_safe(tmp_path):
    data = dict(REGISTER)
    data = json.loads(json.dumps(REGISTER))
    data["edges"] = [{"from": "ALPHA", "type": "parent", "to": "ALPHA-REQ"},
                     {"from": "ALPHA-REQ", "type": "parent", "to": "ALPHA"}]
    reg = load(str(_reg(tmp_path, data)))
    assert reg.parents("ALPHA") == ["ALPHA-REQ"]        # stops rather than looping
