"""Tests for denylist-audit (issue #41).

A gate that scans outbound material is only as good as its list, and nothing audits the list. Two
failures follow, both ending in a green verdict over material that should have been refused.

A partially-listed family certifies its own siblings: the member that IS caught is what makes the
clean verdict on the others credible.

A narrowed entry can be silently dead. That is not hypothetical. Fixing a real false positive (a
short term matching inside an ordinary English word) produced a pattern containing a literal
backspace character, which matched nothing at all. A term silently disabled is worse than one that
over-fires, because over-firing is visible.
"""
import json
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "denylist-audit.py")
BS, BACKSPACE = chr(92), chr(8)


def _denylist(tmp_path, lines):
    p = tmp_path / "denylist.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _run(denylist, *args):
    return subprocess.run([sys.executable, ENGINE, "--denylist", str(denylist), *args],
                          capture_output=True, text=True, timeout=90)


def _states(denylist, *args):
    r = _run(denylist, "--json", *args)
    return [f["state"] for f in json.loads(r.stdout)["findings"]]


def test_no_denylist_is_a_skip(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "EGRESS_DENYLIST"}
    r = subprocess.run([sys.executable, ENGINE, "--check"], capture_output=True, text=True, env=env)
    assert r.returncode == 2


def test_denylist_named_but_missing_is_an_error(tmp_path):
    # Auditing nothing would report a clean list.
    r = _run(tmp_path / "absent.txt", "--check")
    assert r.returncode == 3


def test_a_healthy_list_is_clean(tmp_path):
    d = _denylist(tmp_path, [f"regex:(?i){BS}bACME{BS}b    # example: ACME", "PLAINTERM"])
    assert _states(d) == []


def test_a_pattern_that_matches_nothing_is_caught(tmp_path):
    # The exact bug: a word-boundary fix that wrote a literal backspace instead of \\b.
    d = _denylist(tmp_path, [f"regex:(?i){BACKSPACE}ACME{BACKSPACE}    # example: ACME"])
    assert "dead-pattern" in _states(d)


def test_a_pattern_that_does_not_compile_is_caught(tmp_path):
    d = _denylist(tmp_path, ["regex:(?i)[unclosed    # example: x"])
    assert "dead-pattern" in _states(d)


def test_a_regex_without_an_example_cannot_be_proven_live(tmp_path):
    # Reported rather than assumed strict: liveness that cannot be established is itself a finding.
    d = _denylist(tmp_path, ["regex:(?i)SOMETHING"])
    assert "no-example" in _states(d)


def test_a_plain_literal_needs_no_example(tmp_path):
    # A literal always matches itself, so demanding an example would be noise.
    d = _denylist(tmp_path, ["ACME"])
    assert _states(d) == []


def test_a_partially_listed_family_is_caught(tmp_path):
    yaml = pytest.importorskip("yaml")
    reg = tmp_path / "register.yaml"
    reg.write_text(yaml.safe_dump({
        "tiers": ["vehicle", "agreement"],
        "entities": {
            "ALPHA": {"tier": "vehicle", "source": "decided"},
            "AG-1": {"tier": "agreement", "source": "decided"},
            "AG-2": {"tier": "agreement", "source": "decided"},
            "AG-3": {"tier": "agreement", "source": "decided"},
        },
        "edges": [{"from": f"AG-{i}", "type": "parent", "to": "ALPHA"} for i in (1, 2, 3)],
    }), encoding="utf-8")
    d = _denylist(tmp_path, ["AG-1", "AG-2"])          # AG-3 missing
    findings = json.loads(_run(d, "--json", "--register", str(reg)).stdout)["findings"]
    partial = [f for f in findings if f["state"] == "family-partial"]
    assert partial, findings
    assert partial[0]["unlisted"] == ["AG-3"]
    assert partial[0]["listed"] == ["AG-1", "AG-2"]


def test_a_fully_listed_family_is_clean(tmp_path):
    # NEGATIVE control: completeness must not fire when the list is complete.
    yaml = pytest.importorskip("yaml")
    reg = tmp_path / "register.yaml"
    reg.write_text(yaml.safe_dump({
        "tiers": ["vehicle", "agreement"],
        "entities": {
            "ALPHA": {"tier": "vehicle", "source": "decided"},
            "AG-1": {"tier": "agreement", "source": "decided"},
            "AG-2": {"tier": "agreement", "source": "decided"},
        },
        "edges": [{"from": f"AG-{i}", "type": "parent", "to": "ALPHA"} for i in (1, 2)],
    }), encoding="utf-8")
    d = _denylist(tmp_path, ["AG-1", "AG-2"])
    states = [f["state"] for f in
              json.loads(_run(d, "--json", "--register", str(reg)).stdout)["findings"]]
    assert "family-partial" not in states


def test_an_unlisted_variant_present_in_the_corpus_is_reported(tmp_path):
    # Presence in the corpus is what keeps variant generation from being noise.
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("mentions A-C-M-E in passing\n", encoding="utf-8")
    d = _denylist(tmp_path, ["ACME"])
    states = [f["state"] for f in
              json.loads(_run(d, "--json", "--corpus", str(corpus)).stdout)["findings"]]
    assert "variant-unlisted" in states


def test_variants_absent_from_the_corpus_are_not_reported(tmp_path):
    # NEGATIVE control: generating variants is easy, generating USEFUL ones is not.
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("nothing relevant here\n", encoding="utf-8")
    d = _denylist(tmp_path, ["ACME"])
    states = [f["state"] for f in
              json.loads(_run(d, "--json", "--corpus", str(corpus)).stdout)["findings"]]
    assert "variant-unlisted" not in states
