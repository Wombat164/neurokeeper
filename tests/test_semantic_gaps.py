"""semantic-gaps: notes about the same subject that are not linked to each other.

The failure this engine exists for is invisible to ref-audit: every link resolves, nothing is
orphaned, and the collection still holds two unconnected halves of one subject.

Both directions are tested throughout. A suggestion engine that has only ever been observed
returning nothing is not known to detect anything, and one that has only ever been observed
returning something is not known to be quiet when it should be.
"""
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vault-semantic-gaps.py")

NOTE = """---
title: {title}
tags: [{tags}]
---

# {title}

{body}
"""


def _vault(tmp_path, notes):
    v = tmp_path / "vault"
    v.mkdir(exist_ok=True)
    for name, kw in notes.items():
        (v / f"{name}.md").write_text(
            NOTE.format(title=kw.get("title", name), tags=kw.get("tags", ""),
                        body=kw.get("body", "")), encoding="utf-8")
    return v


def _run(vault, tmp_path, *args):
    r = subprocess.run([sys.executable, ENGINE, "--vault", str(vault), "--json",
                        "--cache", str(tmp_path / "cache.json"), *args],
                       capture_output=True, text=True, timeout=180)
    try:
        return r, json.loads(r.stdout)
    except Exception:
        return r, None


def _gaps(data, note):
    for r in data["results"]:
        if r["note"].endswith(note):
            return [g["note"] for g in r["gaps"]]
    return None


# A subject with a distinctive vocabulary, so the match rests on something real rather than on
# words every note in a collection shares.
TOPIC = ("The turbine calibration procedure for the Kestrel assembly depends on the Kestrel "
         "torque table and the calibration jig. Kestrel calibration is revised annually.")


def test_an_unlinked_note_on_the_same_subject_is_reported(tmp_path):
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel, calibration",
                                "body": TOPIC},
        "kestrel-torque-table": {"title": "Kestrel torque table", "tags": "kestrel, calibration",
                                 "body": TOPIC},
        "unrelated-catering": {"title": "Catering rota", "tags": "catering",
                               "body": "Sandwiches on Tuesday."},
    })
    r, data = _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    assert data, r.stderr[:500]
    gaps = _gaps(data, "kestrel-calibration.md")
    assert any("kestrel-torque-table" in g for g in gaps), gaps


def test_an_unrelated_note_is_not_reported(tmp_path):
    # The negative control. An engine that suggests everything has suggested nothing.
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel", "body": TOPIC},
        "unrelated-catering": {"title": "Catering rota", "tags": "catering",
                               "body": "Sandwiches on Tuesday."},
    })
    _, data = _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    assert not any("catering" in g for g in _gaps(data, "kestrel-calibration.md"))


def test_a_note_already_linked_is_not_reported(tmp_path):
    # The whole point: report the gap, not the work already done. An engine that keeps suggesting
    # what you already did teaches you to stop reading it.
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel",
                                "body": TOPIC + "\n\nSee [[kestrel-torque-table]]."},
        "kestrel-torque-table": {"title": "Kestrel torque table", "tags": "kestrel", "body": TOPIC},
    })
    _, data = _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    assert not any("torque" in g for g in _gaps(data, "kestrel-calibration.md"))


def test_an_inbound_link_also_counts_as_linked(tmp_path):
    """The gap is symmetric, so the exclusion must be too.

    If only outbound links were checked, a note that another note already points AT would be
    reported as disconnected from it, which is false.
    """
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel", "body": TOPIC},
        "kestrel-torque-table": {"title": "Kestrel torque table", "tags": "kestrel",
                                 "body": TOPIC + "\n\nSee [[kestrel-calibration]]."},
    })
    _, data = _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    assert not any("torque" in g for g in _gaps(data, "kestrel-calibration.md"))


def test_a_link_written_as_a_title_resolves(tmp_path):
    # Links are written as a stem, a title or an alias. Matching only stems would report a link
    # that plainly exists as a gap.
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel",
                                "body": TOPIC + "\n\nSee [[Kestrel torque table]]."},
        "kestrel-torque-table": {"title": "Kestrel torque table", "tags": "kestrel", "body": TOPIC},
    })
    _, data = _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    assert not any("torque" in g for g in _gaps(data, "kestrel-calibration.md"))


def test_the_note_never_reports_itself(tmp_path):
    v = _vault(tmp_path, {"solo": {"title": "Solo", "tags": "x", "body": TOPIC}})
    _, data = _run(v, tmp_path, "--note", str(v / "solo.md"))
    assert _gaps(data, "solo.md") == []


def test_evidence_travels_with_every_candidate(tmp_path):
    # A suggestion a reader cannot check is one they must take on faith, and this engine is asking
    # them to judge rather than to comply.
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel", "body": TOPIC},
        "kestrel-torque-table": {"title": "Kestrel torque table", "tags": "kestrel", "body": TOPIC},
    })
    _, data = _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    for r in data["results"]:
        for g in r["gaps"]:
            assert g["evidence"], g


def test_no_target_is_exit_2(tmp_path):
    # NOT CONFIGURED, per ADR-0002: nothing was asked for, so nothing is wrong.
    v = _vault(tmp_path, {"a": {"body": "x"}})
    r, _ = _run(v, tmp_path)
    assert r.returncode == 2


def test_an_unreadable_collection_is_exit_3(tmp_path):
    # Configured and unreachable is a defect, distinct from a skip.
    r = subprocess.run([sys.executable, ENGINE, "--vault", str(tmp_path / "nope"),
                        "--note", "x.md"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 3


def test_it_never_exits_nonzero_on_findings(tmp_path):
    # Advisory by construction. A suggestion engine that can fail a gate gets the gate switched off.
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel", "body": TOPIC},
        "kestrel-torque-table": {"title": "Kestrel torque table", "tags": "kestrel", "body": TOPIC},
    })
    r, data = _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    assert data["counts"]["gaps"] > 0
    assert r.returncode == 0


def test_it_writes_nothing(tmp_path):
    """Read-only, asserted rather than assumed: it proposes links, it must never insert one."""
    v = _vault(tmp_path, {
        "kestrel-calibration": {"title": "Kestrel calibration", "tags": "kestrel", "body": TOPIC},
        "kestrel-torque-table": {"title": "Kestrel torque table", "tags": "kestrel", "body": TOPIC},
    })
    before = {p: (v / p).read_text(encoding="utf-8") for p in os.listdir(v)}
    _run(v, tmp_path, "--note", str(v / "kestrel-calibration.md"))
    after = {p: (v / p).read_text(encoding="utf-8") for p in os.listdir(v) if p in before}
    assert before == after
