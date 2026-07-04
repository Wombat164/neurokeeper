#!/usr/bin/env python3
# @capability:  audit-log
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/_audit.py
# @prompt:      (none)
# @adapters:    import (shared helper)
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      active
# @doc:         docs/pattern-portable-core-and-adapters.md
"""Reusable, tamper-evident audit substrate: an append-only JSONL log where each entry chains the
previous entry's hash, so any mutating engine can leave a verifiable record of what it applied. This is
the generic form of the memory-audit dream-log, available to every apply-engine (not just memory): the
hash chain makes a silent after-the-fact edit or reorder detectable.

Each line is one JSON object: the caller's record fields plus `prev_hash` and `hash`, where
`hash = sha256(prev_hash + canonical(record))`. verify() walks the chain and returns the first break.
"""
import hashlib
import json
import os

GENESIS = "0" * 64


def _canonical(record):
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _hash(prev_hash, record):
    return hashlib.sha256((prev_hash + _canonical(record)).encode("utf-8")).hexdigest()


def _last_hash(log_path):
    prev = GENESIS
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    prev = json.loads(line).get("hash", prev)
    return prev


def append(log_path, record):
    """Append `record` (a dict) as a chained entry; return the new entry's hash. Creates the log + dirs."""
    prev = _last_hash(log_path)
    h = _hash(prev, record)
    entry = dict(record)
    entry["prev_hash"] = prev
    entry["hash"] = h
    parent = os.path.dirname(log_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(_canonical(entry) + "\n")
    return h


def verify(log_path):
    """Walk the chain. Return (ok, broken_line_index_or_None). A tampered or reordered entry breaks it."""
    prev = GENESIS
    with open(log_path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            record = {k: v for k, v in entry.items() if k not in ("prev_hash", "hash")}
            if entry.get("prev_hash") != prev or entry.get("hash") != _hash(prev, record):
                return False, i
            prev = entry["hash"]
    return True, None
