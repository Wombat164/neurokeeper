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


def test_lint_flags_caveman_separators_but_not_wikilink_dashes(tmp_path):
    # R11: --lint flags ' -- '/' -> ' separators in entries, but strip_protected() must NOT
    # false-positive on a ' -- ' that is part of a real [[wikilink target]].
    store = _store(tmp_path, {
        "MEMORY.md": (
            "# index\n"
            "- [Good](foo.md) - clean hook\n"
            "- [Bad -- sub](foo.md) -- bad sep with arrow -> here\n"
            "- Legit [[Note -- With Dashes]] should not flag\n"
        ),
        "foo.md": "---\n---\nx\n",
        "Note -- With Dashes.md": "---\n---\nx\n",
    })
    r = _run(store, "--lint")
    assert r.returncode == 0                        # advisory: never blocks
    out = r.stdout
    assert "dash-sep" in out and "arrow" in out      # ' -- ' and ' -> ' are flagged
    assert out.count("dash-sep") == 1                # the [[wikilink]] dashes are NOT flagged


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


def test_per_type_decay_halflife(tmp_path):
    # same age + same (zero) refs: a reference-type note decays slower than a project-type -> higher importance
    store = _store(tmp_path, {
        "MEMORY.md": "# idx\n",
        "ref-note.md": "---\nmetadata:\n  type: reference\n---\nbody\n",
        "proj-note.md": "---\nmetadata:\n  type: project\n---\nbody\n",
    })
    d = _json(store, "--today", "2027-03-01")   # ~245d after the files' mtime, so recency < 1 for both
    imp = {r["file"]: r["importance"] for r in d["lowest_importance"]}
    assert imp["ref-note.md"] > imp["proj-note.md"]   # reference base half-life 270 > project 90


def test_reviewed_ttl_snooze_excludes_from_stale(tmp_path):
    # an old, unreferenced note is stale; a recent `reviewed:` stamp within `ttl:` snoozes it out of stale
    store = _store(tmp_path, {
        "MEMORY.md": "# idx\n",
        "stale-one.md": "---\nmetadata:\n  type: project\n---\nold unreferenced body\n",
        "snoozed-one.md": "---\nreviewed: 2027-02-20\nttl: 90\nmetadata:\n  type: project\n---\nold body\n",
    })
    d = _json(store, "--today", "2027-03-01")   # both ~245d old; snoozed reviewed 9d ago (< ttl 90)
    stale_files = [r["file"] for r in d["stale"]]
    assert "stale-one.md" in stale_files            # old + unreferenced + project half-life -> stale
    assert "snoozed-one.md" not in stale_files       # recent reviewed:/ttl: suppresses staleness
    assert "snoozed-one.md" in d["snoozed"]


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


def test_candidates_detects_merge_and_contradiction(tmp_path):
    store = _store(tmp_path, {
        "MEMORY.md": "# index\n",
        "feedback-cloud-taxonomy-v1.md": "---\nmetadata:\n  type: feedback\n---\nrule\n",
        "feedback-cloud-taxonomy-v2.md": "---\nmetadata:\n  type: feedback\n---\nrule2\n",
        "reference-alpha.md": "---\nmetadata:\n  originSessionId: sess-XYZ\n---\na\n",
        "reference-beta.md": "---\nmetadata:\n  originSessionId: sess-XYZ\n---\nb\n",
        "feedback-indent-tabs.md": "---\nmetadata:\n  type: feedback\n---\nalways use tabs for indent\n",
        "feedback-indent-spaces.md": "---\nmetadata:\n  type: feedback\n---\nnever use tabs for indent\n",
    })
    r = _run(store, "--candidates")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    merges = {frozenset((c["a"], c["b"])) for c in d["merge_candidates"]}
    assert frozenset(("feedback-cloud-taxonomy-v1.md", "feedback-cloud-taxonomy-v2.md")) in merges  # stem overlap
    # issue #31: co-session ALONE no longer qualifies. These two share a session id and nothing
    # else, which means they share a clock, not a subject.
    assert frozenset(("reference-alpha.md", "reference-beta.md")) not in merges
    assert d["suppressed"]["cosession_only"] >= 1
    assert any({c["a"], c["b"]} == {"feedback-indent-tabs.md", "feedback-indent-spaces.md"}
               and "always/never" in c["opposite_stances"] for c in d["contradiction_candidates"])


# --- issue #30: an unreachable store must not report like an empty one -------------------------

def _run_at(path, *args):
    """Invoke the engine pointed at `path`, which may not exist."""
    env = dict(os.environ, CLAUDE_MEMORY_DIR=str(path))
    return subprocess.run([sys.executable, ENGINE, *args], capture_output=True, text=True, env=env)


def test_missing_store_exits_nonzero_in_every_mode(tmp_path):
    # The point of the issue: a path that does not resolve is an ERROR, not a clean empty result.
    # It used to exit 0, and --terse feeds a SessionStart hook that stays silent on a zero exit, so
    # a moved or mistyped store produced a permanently healthy-looking session.
    missing = tmp_path / "nope" / "not-here"
    for mode in ("--check", "--terse", "--json", "--lint", "--candidates"):
        r = _run_at(missing, mode)
        assert r.returncode != 0, f"{mode} exited 0 for a store that does not exist"
        assert "not found" in r.stderr.lower(), f"{mode} said nothing on stderr: {r.stderr!r}"


def test_missing_store_names_the_source_of_the_path(tmp_path):
    # The operator's next action differs depending on whether they set the variable or inherited
    # the default, so the message has to say which one supplied the path.
    r = _run_at(tmp_path / "nope", "--check")
    assert "CLAUDE_MEMORY_DIR" in r.stderr


def test_empty_but_existing_store_still_exits_zero(tmp_path):
    # The NEGATIVE case, and the one that decides whether the change is safe: a real store with
    # nothing in it is a legitimate new collection. Widening the error must not swallow it.
    empty = tmp_path / "memory"
    empty.mkdir()
    for mode in ("--check", "--terse"):
        r = _run_at(empty, mode)
        assert r.returncode == 0, f"{mode} treated an existing EMPTY store as an error: {r.stderr!r}"


def test_populated_store_is_unaffected(tmp_path):
    # Guards against the new check firing on the ordinary path.
    store = _store(tmp_path, {"MEMORY.md": "# index\n- [a](a.md) - x\n", "a.md": "body\n"})
    r = _run(store, "--check")
    assert r.returncode == 0, r.stderr


# --- issue #31: co-session is a tiebreaker, not evidence ---------------------------------------

def _sess(name, sid, body="text\n"):
    return {name: f"---\nmetadata:\n  originSessionId: {sid}\n---\n{body}"}


def test_cosession_alone_is_suppressed_and_counted(tmp_path):
    # A busy session writes many unrelated memories. Admitting co-session alone made the candidate
    # count quadratic in the size of that session: on a real store, 1806 of 1846 pairs (98%) had no
    # topical relationship whatsoever.
    files = {}
    for n in ("alpha", "bravo", "charlie", "delta"):
        files.update(_sess(f"reference-{n}.md", "sess-SAME"))
    files["MEMORY.md"] = "# index\n"
    d = _json(_store(tmp_path, files), "--candidates")
    assert d["merge_candidates"] == [], d["merge_candidates"]
    # 4 notes pairwise = 6 pairs, all co-session-only
    assert d["suppressed"]["cosession_only"] == 6, d["suppressed"]


def test_cosession_still_rides_along_when_content_agrees(tmp_path):
    # It is a tiebreaker, not banned: when a pair ALREADY overlaps on content, the shared session
    # is real corroboration and must survive on the finding.
    files = {"MEMORY.md": "# index\n"}
    files.update(_sess("feedback-cloud-taxonomy-v1.md", "sess-SAME"))
    files.update(_sess("feedback-cloud-taxonomy-v2.md", "sess-SAME"))
    d = _json(_store(tmp_path, files), "--candidates")
    assert len(d["merge_candidates"]) == 1, d["merge_candidates"]
    sig = d["merge_candidates"][0]["signals"]
    assert "stem_overlap" in sig and "same_session" in sig, sig


def test_suppression_is_reported_not_silent(tmp_path):
    # A silent cap reads as "nothing more to find", which is what makes a narrowing filter
    # dangerous rather than merely noisy. The rule has to travel with the count.
    files = {"MEMORY.md": "# index\n"}
    files.update(_sess("reference-alpha.md", "sess-X"))
    files.update(_sess("reference-beta.md", "sess-X"))
    d = _json(_store(tmp_path, files), "--candidates")
    assert d["suppressed"]["cosession_only"] == 1
    assert "tiebreaker" in d["suppressed"]["rule"]
