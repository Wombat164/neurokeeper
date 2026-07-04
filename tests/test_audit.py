"""Unit tests for the reusable audit substrate (scripts/_audit.py).

Locks the tamper-evidence contract: a clean append-only chain verifies, and any edit or reorder of a
past entry breaks it at that line.
"""
import json

import _audit


def test_append_and_verify_clean(tmp_path):
    log = str(tmp_path / "a.jsonl")
    _audit.append(log, {"engine": "frontmatter-fix", "action": "apply", "n": 1})
    _audit.append(log, {"engine": "frontmatter-fix", "action": "apply", "n": 2})
    assert _audit.verify(log) == (True, None)


def test_tampering_a_past_entry_is_detected(tmp_path):
    log = tmp_path / "a.jsonl"
    _audit.append(str(log), {"engine": "x", "n": 1})
    _audit.append(str(log), {"engine": "x", "n": 2})
    lines = log.read_text(encoding="utf-8").splitlines()
    e = json.loads(lines[0])
    e["n"] = 99                                        # rewrite history
    lines[0] = json.dumps(e)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, idx = _audit.verify(str(log))
    assert ok is False and idx == 0


def test_reordering_entries_is_detected(tmp_path):
    log = tmp_path / "a.jsonl"
    _audit.append(str(log), {"n": 1})
    _audit.append(str(log), {"n": 2})
    lines = log.read_text(encoding="utf-8").splitlines()
    log.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")   # swap order -> chain breaks
    assert _audit.verify(str(log))[0] is False
