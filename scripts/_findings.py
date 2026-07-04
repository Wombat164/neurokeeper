#!/usr/bin/env python3
# @capability:  findings-ir
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/_findings.py
# @prompt:      (none)
# @adapters:    import (shared helper)
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/adr-0001-backend-contract.md
"""Findings IR: one canonical representation for what an engine found, so output formats (SARIF today;
JUnit / a Bases view later) become thin renderers over the same data instead of an N-engines x M-formats
matrix of bespoke serializers.

A Finding is (engine, rule, severity, path, line, message, fingerprint):
  - engine       the emitting engine, e.g. "ref-audit"
  - rule         a stable kebab rule id, e.g. "broken-link" / "orphan"
  - severity     "error" | "warning" | "note"  (the SARIF levels)
  - path         the note/file the finding is about (vault-relative posix), or None
  - line         a 1-based line number, or None
  - message      one human-readable sentence
  - fingerprint  a stable id for baseline / dedup, or None
"""
from collections import namedtuple

Finding = namedtuple("Finding", "engine rule severity path line message fingerprint")

SEVERITIES = ("error", "warning", "note")

INFO_URI = "https://github.com/Wombat164/neurokeeper"


def pkg_version():
    """neurokeeper version for a report envelope: installed metadata, else '0'."""
    try:
        from importlib.metadata import version
        return version("neurokeeper")
    except Exception:
        return "0"


def to_sarif(findings, tool_version="0"):
    """Render Findings as SARIF 2.1.0 (the GitHub code-scanning format): one run, rules deduped by id."""
    rules, results = {}, []
    for f in findings:
        rules.setdefault(f.rule, {"id": f.rule, "name": f.rule,
                                  "shortDescription": {"text": f.rule.replace("-", " ")}})
        loc = []
        if f.path:
            phys = {"artifactLocation": {"uri": f.path}}
            if f.line:
                phys["region"] = {"startLine": f.line}
            loc = [{"physicalLocation": phys}]
        r = {"ruleId": f.rule, "level": f.severity, "message": {"text": f.message}, "locations": loc}
        if f.fingerprint:
            r["partialFingerprints"] = {"neurokeeper/v1": f.fingerprint}
        results.append(r)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "neurokeeper", "version": str(tool_version),
                                "informationUri": INFO_URI, "rules": list(rules.values())}},
            "results": results,
        }],
    }
