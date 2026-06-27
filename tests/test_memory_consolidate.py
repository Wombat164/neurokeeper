"""Regression tests for memory-consolidate.py -- locks the red-team LOW-bug fixes:
inbound() counting alias/heading/escaped-pipe links, broken-link detection of uppercase/subdir refs,
and base_weight matching emoji-tagged whole words (not "higher"/"highlight" prose). Plus the --check
exit-code contract (it gates real commits) and the read-only invariant.
"""
import hashlib
import json
import os
import subprocess
import sys

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "memory-consolidate.py")


def _store(tmp_path, files, name="memory"):
    d = tmp_path / name
    d.mkdir()
    for fn, text in files.items():
        (d / fn).write_text(text, encoding="utf-8")
    return d


def _run(store, *args):
    env = dict(os.environ, CLAUDE_MEMORY_DIR=str(store))
    return subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True, env=env)


def _json(store, *args):
    r = _run(store, "--json", *args)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_inbound_counts_alias_and_heading_links(tmp_path):
    # foo referenced ONLY via alias / heading / escaped-pipe forms -> must count as referenced (not orphan)
    store = _store(tmp_path, {
        "MEMORY.md": "# index\n- [[foo|Foo Alias]] then [[foo#section]] then [[foo\\|tbl]]\n",
        "foo.md": "---\n---\nbody\n",
    })
    d = _json(store)
    assert "foo.md" not in d["orphans"]


def test_broken_link_uppercase_and_subdir(tmp_path):
    store = _store(tmp_path, {
        "MEMORY.md": "- [a](foo.md)\n- [bad](Missing-Upper.md)\n- [sh](_shared/x.md)\n",
        "foo.md": "---\n---\nb\n",
    })
    d = _json(store)
    assert "Missing-Upper.md" in d["broken_links"]    # uppercase-leading now caught
    assert "_shared/x.md" not in d["broken_links"]     # _shared is a valid cross-repo ref


def test_base_weight_word_boundary_no_false_bump(tmp_path):
    # prose "highlight / higher / permanent" with NO emoji tag must keep base_weight 1.0
    store = _store(tmp_path, {
        "MEMORY.md": "- [a](a.md)\n",
        "a.md": "A highlight of higher-level permanent-ish prose, no tag emoji here.\n",
    })
    d = _json(store, "--today", "2026-06-27")
    row = next(r for r in d["lowest_importance"] if r["file"] == "a.md")
    assert row["importance"] <= 1.0 + 1e-9             # fresh file * 1.0; substring-match would give 1.5/2.0


def test_base_weight_emoji_tagged_bumps(tmp_path):
    store = _store(tmp_path, {
        "MEMORY.md": "- [p](p.md)\n",
        "p.md": "⚠️ PERMANENT -- never archive this.\n",   # warning emoji + whole word
    })
    d = _json(store, "--today", "2026-06-27")
    row = next(r for r in d["lowest_importance"] if r["file"] == "p.md")
    assert row["importance"] > 1.5                      # bw 2.0 * (fresh ~1.0)


def test_check_exit_codes(tmp_path):
    clean = _store(tmp_path, {"MEMORY.md": "- [a](a.md)\n", "a.md": "x\n"}, name="clean")
    assert _run(clean, "--check").returncode == 0
    broken = _store(tmp_path, {"MEMORY.md": "- [a](a.md)\n- [b](Nope.md)\n", "a.md": "x\n"}, name="broken")
    assert _run(broken, "--check").returncode == 1     # broken link blocks the commit


def test_read_only_invariant(tmp_path):
    store = _store(tmp_path, {"MEMORY.md": "- [a](a.md)\n", "a.md": "x\n"})
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in store.iterdir()}
    _json(store)
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in store.iterdir()}
    assert before == after                              # the analyzer proposes, never writes
