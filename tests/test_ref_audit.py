"""Tests for vault-ref-audit.py -- reference-integrity audit.

Locks: broken-link / orphan / dead-end / orphan-media detection; broken .canvas refs; the --check
semantics (unresolved links are informational by default, --strict makes them fail, canvas/base always
fail); META files (CLAUDE.md) are not audited; external URLs + intra-doc anchors are not "broken".
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "vault-ref-audit.py")
_HAS_GIT = shutil.which("git") is not None


def _vault(root, files):
    root.mkdir(parents=True, exist_ok=True)
    for rel, txt in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return root


def _run(vault, *args):
    return subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True,
                          env=dict(os.environ, VAULT_ROOT=str(vault)))


def _json(vault, *args):
    r = _run(vault, "--json", *args)
    assert r.returncode in (0, 1), r.stderr
    return json.loads(r.stdout)


def test_broken_link_orphan_deadend_media(tmp_path):
    v = _vault(tmp_path / "v", {
        "a.md": "links [[b]] and [[missing]] and ![[img.png]]\n",
        "b.md": "no outbound links here\n",
        "orphan.md": "links [[b]] but nobody links me\n",
        "img.png": "x", "lonely.png": "x",
    })
    d = _json(v)
    assert [b["target"] for b in d["broken_links"]] == ["missing"]
    assert "b.md" in d["dead_ends"] and "a.md" not in d["dead_ends"]
    assert "orphan.md" in d["orphans"] and "b.md" not in d["orphans"]
    assert "lonely.png" in d["orphan_media"] and "img.png" not in d["orphan_media"]


def test_broken_canvas(tmp_path):
    v = _vault(tmp_path / "v", {
        "a.md": "x\n",
        "board.canvas": json.dumps({"nodes": [{"type": "file", "file": "a.md"},
                                               {"type": "file", "file": "gone.md"}]}),
    })
    d = _json(v)
    assert [b["target"] for b in d["broken_canvas"]] == ["gone.md"]


def test_check_semantics(tmp_path):
    unresolved = _vault(tmp_path / "u", {"a.md": "[[missing]]\n"})
    assert _run(unresolved, "--check").returncode == 0          # unresolved is informational
    assert _run(unresolved, "--check", "--strict").returncode == 1
    canvas = _vault(tmp_path / "c", {
        "a.md": "x\n", "c.canvas": json.dumps({"nodes": [{"type": "file", "file": "gone.md"}]})})
    assert _run(canvas, "--check").returncode == 1              # canvas break always fails


def test_meta_files_not_audited(tmp_path):
    v = _vault(tmp_path / "v", {"CLAUDE.md": "see the [[wikilinks]] example syntax\n", "a.md": "real\n"})
    d = _json(v)
    assert d["broken_links"] == []                              # CLAUDE.md's example links skipped
    assert "CLAUDE.md" not in d["orphans"]


def test_external_and_anchor_not_broken(tmp_path):
    v = _vault(tmp_path / "v", {"a.md": "[x](https://example.com/y) and [[#heading]] and [s](#sec)\n"})
    assert _json(v)["broken_links"] == []


def test_stem_collisions(tmp_path):
    v = _vault(tmp_path / "v", {"A/note.md": "x\n", "B/note.md": "y\n", "unique.md": "z\n"})
    d = _json(v)
    stems = [c["stem"] for c in d["stem_collisions"]]
    assert "note" in stems and "unique" not in stems
    coll = next(c for c in d["stem_collisions"] if c["stem"] == "note")
    assert coll["paths"] == ["A/note.md", "B/note.md"]


def _git(vault, *a):
    subprocess.run(["git", "-C", str(vault), *a], check=True, capture_output=True)


@pytest.mark.skipif(not _HAS_GIT, reason="git required for --since")
def test_since_filters_findings_to_changed_notes(tmp_path):
    v = _vault(tmp_path / "v", {"keep.md": "no links\n", "old.md": "no links\n"})
    _git(v, "init", "-q"); _git(v, "config", "user.email", "t@t"); _git(v, "config", "user.name", "t")
    _git(v, "add", "-A"); _git(v, "commit", "-q", "-m", "base")
    (v / "old.md").write_text("no links (touched)\n", encoding="utf-8")   # modify old.md only

    full = _json(v)
    assert {"keep.md", "old.md"} <= set(full["orphans"]) and full["scope"] is None

    scoped = _json(v, "--since", "HEAD")
    assert scoped["orphans"] == ["old.md"]                      # only the changed note is reported
    assert scoped["scope"]["since"] == "HEAD"
    assert scoped["scope"]["scanned_notes"] == 2                # the whole graph was still scanned


@pytest.mark.skipif(not _HAS_GIT, reason="git required for --since")
def test_since_bad_ref_exits_2(tmp_path):
    v = _vault(tmp_path / "v", {"a.md": "x\n"})
    _git(v, "init", "-q")
    r = _run(v, "--json", "--since", "no-such-ref-xyz")
    assert r.returncode == 2, (r.returncode, r.stderr)          # loud failure, never silent wrong-scope
