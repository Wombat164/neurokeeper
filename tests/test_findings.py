"""Unit tests for the Findings IR + SARIF renderer (scripts/_findings.py).

Locks the canonical schema and a valid SARIF 2.1.0 shape, so the one IR really is the single seam that
output formats render over.
"""
from _findings import Finding, to_sarif


def test_to_sarif_shape():
    fs = [Finding("ref-audit", "broken-link", "warning", "a.md", None, "link to X broken", "broken_link|X"),
          Finding("ref-audit", "orphan", "note", "b.md", 12, "no inbound", "orphan|b.md"),
          Finding("ref-audit", "orphan", "note", "c.md", None, "no inbound", "orphan|c.md")]
    s = to_sarif(fs, tool_version="1.2.3")
    assert s["version"] == "2.1.0"
    drv = s["runs"][0]["tool"]["driver"]
    assert drv["name"] == "neurokeeper" and drv["version"] == "1.2.3"
    assert sorted(r["id"] for r in drv["rules"]) == ["broken-link", "orphan"]   # deduped by rule id

    results = s["runs"][0]["results"]
    assert len(results) == 3
    r0 = results[0]
    assert r0["ruleId"] == "broken-link" and r0["level"] == "warning"
    assert r0["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "a.md"
    assert r0["partialFingerprints"]["neurokeeper/v1"] == "broken_link|X"
    # line -> region.startLine only when present
    assert results[1]["locations"][0]["physicalLocation"]["region"]["startLine"] == 12
    assert "region" not in results[2]["locations"][0]["physicalLocation"]


def test_to_sarif_empty():
    s = to_sarif([])
    assert s["version"] == "2.1.0"
    assert s["runs"][0]["results"] == [] and s["runs"][0]["tool"]["driver"]["rules"] == []
