"""Unit tests for the correlation engine: scripts/vault-correlate.py.

Locks the behaviours that separate this from naive filename matching:
IDF token weighting, the single-signal anchor floor, code/phrase/person/tag signals,
the state ladder, the mtime cache, and vault-form agnosticism (no frontmatter at all
must still work). Every fixture here is generic on purpose: the engine ships in a
public repo and must never carry site-specific codes, names or folder names.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ENGINE = SCRIPTS_DIR / "vault-correlate.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture()
def corr_vault(tmp_path):
    """A small generic vault: two distinctive notes, one deliberately generic, plus filler."""
    v = tmp_path / "vault"
    (v / "notes").mkdir(parents=True)

    (v / "notes" / "widget-programme.md").write_text(
        "---\ntitle: Widget Programme\naliases: [Widget Prog]\ntags: [hardware]\n"
        "contract: PROJ-1\nstakeholders: [Ada Lovelace, Grace Hopper]\n---\n"
        "# Widget Programme\nSee [[Sprocket Study]].\n", encoding="utf-8")
    (v / "notes" / "sprocket-study.md").write_text(
        "---\ntitle: Sprocket Study\ntags: [research]\n---\nBody about sprockets.\n",
        encoding="utf-8")
    (v / "notes" / "generic-meeting.md").write_text(
        "---\ntitle: Meeting Notes Update Draft\n---\nNothing distinctive.\n", encoding="utf-8")
    # Filler so 'report' is a common (low-IDF) token while 'sprocket' stays rare.
    for i in range(12):
        (v / "notes" / f"report-{i}.md").write_text(
            f"---\ntitle: Report {i} Update\n---\nRoutine report.\n", encoding="utf-8")
    return v


def run_engine(vault, items, extra=None):
    cmd = [sys.executable, str(ENGINE), "--vault", str(vault),
           "--cache", str(Path(vault) / ".cache.json")] + (extra or [])
    proc = subprocess.run(cmd, input=json.dumps(items), capture_output=True,
                          text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return {r["id"]: r for r in json.loads(proc.stdout)["items"]}


def test_code_match_is_a_strong_signal(corr_vault):
    out = run_engine(corr_vault, [{"id": "a", "title": "About delivery", "codes": ["PROJ-1"]}])
    assert out["a"]["candidates"][0]["note"].endswith("widget-programme.md")
    assert any("code PROJ-1" in e for e in out["a"]["candidates"][0]["evidence"])
    assert out["a"]["state"] in ("correlated", "anchored")


def test_title_phrase_is_the_top_candidate(corr_vault):
    """A note's title appearing verbatim in the item puts that note first.

    It does NOT on its own reach `anchored`: the phrase channel has one budget per note, so a note's
    title and its abbreviation are one match, not two. Anchoring on a title match therefore needs
    corroboration from a genuinely different channel, which is what `anchored` ought to mean.
    """
    out = run_engine(corr_vault, [{"id": "a", "title": "Re: Widget Programme timeline"}])
    assert out["a"]["candidates"][0]["note"].endswith("widget-programme.md")
    assert out["a"]["state"] == "correlated"
    assert out["a"]["score"] >= 40


def test_alias_is_matched_like_a_title(corr_vault):
    out = run_engine(corr_vault, [{"id": "a", "title": "question on Widget Prog scope"}])
    assert out["a"]["candidates"][0]["note"].endswith("widget-programme.md")


def test_person_matches_from_email_local_part(corr_vault):
    """'Ada Lovelace' in frontmatter must meet 'ada.lovelace@example.org' in the item."""
    out = run_engine(corr_vault, [
        {"id": "a", "title": "unrelated subject", "participants": ["ada.lovelace@example.org"]}])
    assert any("lovelace" in e for e in out["a"]["candidates"][0]["evidence"])


def test_person_matches_from_display_name(corr_vault):
    out = run_engine(corr_vault, [
        {"id": "a", "title": "x", "participants": ["Grace Hopper <grace@example.org>"]}])
    assert out["a"]["candidates"][0]["note"].endswith("widget-programme.md")


def test_generic_tokens_do_not_anchor(corr_vault):
    """The classic failure: common words dragging a mail onto an unrelated note."""
    out = run_engine(corr_vault, [{"id": "a", "title": "report update"}])
    assert out["a"]["state"] == "new"
    assert out["a"]["score"] < 40


def test_rare_token_outweighs_common_token(corr_vault):
    """IDF: 'sprocket' appears in one note, 'report' in twelve. Rare must win."""
    out = run_engine(corr_vault, [{"id": "a", "title": "sprocket report"}])
    assert out["a"]["candidates"][0]["note"].endswith("sprocket-study.md")


def test_unrelated_item_is_new(corr_vault):
    out = run_engine(corr_vault, [{"id": "a", "title": "completely unrelated topic"}])
    assert out["a"]["state"] == "new"
    assert out["a"]["candidates"] == [] or out["a"]["score"] < 40


def _pileup_index(mod):
    """A note reachable ONLY by signals that are individually too weak to anchor.

    `_tiny_index` cannot express this: its card carries no tags, no people and
    no codes, so the only signal it can ever produce is a title phrase, which
    is worth more than the floor on its own. A test for the floor needs a note
    whose every available signal is below it.
    """
    return mod.VaultIndex([mod.NoteCard({
        "note": "n/telemetry.md", "reldir": "n", "stem": "telemetry",
        # The title is deliberately absent from the item text below: a phrase
        # hit is W_PHRASE, which is above the floor and would anchor honestly.
        "title": "Quarterly Instrumentation Review", "aliases": [],
        "tags": ["telemetry", "migration", "rollback"],
        "codes": [], "people": ["Ada Harrington", "Grace Okonkwo"],
        "links_out": [], "note_type": None})])


def test_anchor_floor_blocks_weak_signal_pileup():
    """No single signal below MIN_ANCHOR_SIGNAL may anchor, however many pile up.

    THE PILEUP HAS TO BE REAL. The previous version of this test scored 35
    against a threshold of 70, so no candidate ever reached the branch that
    asserts, and its final `state != "anchored" or ...` was satisfied by the
    left side alone. Setting MIN_ANCHOR_SIGNAL to 0 left the whole suite green:
    the floor could be deleted outright and nothing noticed.

    So this builds a note that two people and three tags reach, which sums past
    ANCHORED while no single signal comes near the floor.
    """
    mod = _load_engine_module()
    idx = _pileup_index(mod)
    item = {"id": "x", "title": "sync notes",
            "body": "telemetry migration rollback, all discussed",
            "participants": ["ada.harrington@example.org", "Grace Okonkwo"]}

    res = mod.correlate(item, idx)
    cand = res["candidates"][0]

    # The premise: without the floor this WOULD have anchored. If the fixture
    # ever stops summing past the threshold, the test below proves nothing, so
    # the premise is asserted rather than assumed.
    raw = sum(mod.W_PERSON if e.startswith("person") else mod.W_TAG
              for e in cand["evidence"] if e.startswith(("person", "tag")))
    assert raw >= mod.ANCHORED, (
        f"fixture no longer builds a pileup: {raw} < {mod.ANCHORED}, "
        f"evidence={cand['evidence']}")

    # And every signal in it is individually too weak to carry the conclusion.
    assert mod.W_PERSON < mod.MIN_ANCHOR_SIGNAL
    assert mod.W_TAG < mod.MIN_ANCHOR_SIGNAL

    # The floor therefore has to fire: held below ANCHORED, and SAID SO in the state.
    #
    # This asserts the outcome rather than the wording. The protection used to be an evidence string
    # containing "capped"; it is now a per-channel budget plus a distinct `weak` state, which is
    # strictly stronger, and a test pinned to the old phrasing would have failed on an improvement.
    # What must never change is that a pile of individually-too-weak signals cannot read as a match.
    assert cand["score"] < mod.ANCHORED, cand
    assert res["state"] != "anchored", res
    assert res["state"] == "weak", (
        f"a pileup of sub-floor signals must report `weak`, not {res['state']!r}: "
        f"saying 'correlated' here hands the reader candidates and an invitation to stop looking")


def test_vault_without_any_frontmatter_still_works(tmp_path):
    """Vault-form agnosticism: a flat folder of plain markdown must degrade, not fail."""
    v = tmp_path / "flat"
    v.mkdir()
    (v / "Quarterly Sprocket Review.md").write_text("Plain body, no frontmatter.\n", encoding="utf-8")
    out = run_engine(v, [{"id": "a", "title": "Quarterly Sprocket Review follow-up"}])
    assert out["a"]["candidates"], "title-only matching must still find the note"
    assert out["a"]["candidates"][0]["note"].endswith("Quarterly Sprocket Review.md")


def test_cache_is_reused_and_invalidated(corr_vault):
    cache = Path(corr_vault) / ".cache.json"
    run_engine(corr_vault, [{"id": "a", "title": "x"}])
    assert cache.exists()

    def stats(extra=None):
        cmd = [sys.executable, str(ENGINE), "--vault", str(corr_vault),
               "--cache", str(cache), "--stats"] + (extra or [])
        p = subprocess.run(cmd, input='{"id":"a","title":"x"}', capture_output=True,
                           text=True, encoding="utf-8")
        return p.stderr

    assert "0 parsed" in stats(), "unchanged vault must reparse nothing"
    note = Path(corr_vault) / "notes" / "sprocket-study.md"
    note.write_text(note.read_text(encoding="utf-8") + "\nappended\n", encoding="utf-8")
    os.utime(note, (9e8, 9e8))  # force a distinct mtime
    assert "0 parsed" not in stats(), "a changed note must be reparsed"


def test_engine_never_writes_into_the_vault(corr_vault):
    before = {p: p.stat().st_mtime for p in Path(corr_vault).rglob("*.md")}
    run_engine(corr_vault, [{"id": "a", "title": "Widget Programme"}])
    after = {p: p.stat().st_mtime for p in Path(corr_vault).rglob("*.md")}
    assert before == after


def test_bad_json_input_fails_cleanly(corr_vault):
    proc = subprocess.run([sys.executable, str(ENGINE), "--vault", str(corr_vault)],
                          input="{not json", capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode != 0
    assert "not valid JSON" in (proc.stderr + proc.stdout)


@pytest.fixture()
def schema_vault(tmp_path):
    """A vault whose frontmatter schema declares non-default key names for the correlation roles."""
    v = tmp_path / "sv"
    (v / ".claude" / "data").mkdir(parents=True)
    (v / "notes").mkdir()
    (v / ".claude" / "data" / "frontmatter-schema.yaml").write_text(
        "version: 1\n"
        "axes:\n"
        "  note_type: {values: [note, project]}\n"   # enumerated: a classifier, must NOT become a signal
        "  domain: {open: true}\n"                    # open vocab: topical, must fold into tags
        "correlate:\n"
        "  codes: [dossier_ref]\n"
        "  people: [owner]\n", encoding="utf-8")
    (v / "notes" / "thing.md").write_text(
        "---\ntitle: A Thing\nnote_type: project\ndomain: sprocket-engineering\n"
        "dossier_ref: XY-9\nowner: Ada Lovelace\n---\nbody\n", encoding="utf-8")
    return v


def test_schema_declared_code_key_is_used(schema_vault):
    """`dossier_ref` is not a default code key: only the schema can teach the engine about it."""
    out = run_engine(schema_vault, [{"id": "a", "title": "about it", "codes": ["XY-9"]}])
    assert any("code XY-9" in e for e in out["a"]["candidates"][0]["evidence"])


def test_open_vocab_axis_becomes_a_topical_signal(schema_vault):
    out = run_engine(schema_vault, [{"id": "a", "title": "question re sprocket-engineering"}])
    assert any("sprocket-engineering" in e for e in out["a"]["candidates"][0]["evidence"])


def test_enumerated_axis_is_not_a_signal(schema_vault):
    """`note_type: project` is true of a whole class of notes; using it would match everything."""
    out = run_engine(schema_vault, [{"id": "a", "title": "project"}])
    assert not out["a"]["candidates"] or out["a"]["score"] < 40


def test_no_schema_flag_falls_back_to_engine_defaults(schema_vault):
    out = run_engine(schema_vault, [{"id": "a", "title": "about it", "codes": ["XY-9"]}],
                     extra=["--no-schema"])
    assert not out["a"]["candidates"] or not any(
        "code XY-9" in e for e in out["a"]["candidates"][0]["evidence"])


def test_missing_schema_is_not_an_error(corr_vault):
    """A vault with no schema keeps working on the engine defaults."""
    out = run_engine(corr_vault, [{"id": "a", "title": "Re: Widget Programme timeline"}])
    assert out["a"]["state"] == "correlated"
    assert out["a"]["candidates"][0]["note"].endswith("widget-programme.md")


def test_broken_schema_warns_but_does_not_crash(schema_vault):
    (schema_vault / ".claude" / "data" / "frontmatter-schema.yaml").write_text(
        "axes: [this is not a mapping\n", encoding="utf-8")
    out = run_engine(schema_vault, [{"id": "a", "title": "A Thing"}])
    assert "a" in out          # still produced a verdict


def test_explicit_config_overrides_the_schema(schema_vault, tmp_path):
    """Precedence: defaults < schema < --config."""
    cfg = tmp_path / "vault.yaml"
    cfg.write_text("vault:\n  frontmatter_map:\n    codes: [other_ref]\n", encoding="utf-8")
    out = run_engine(schema_vault, [{"id": "a", "title": "x", "codes": ["XY-9"]}],
                     extra=["--config", str(cfg)])
    assert not out["a"]["candidates"] or not any(
        "code XY-9" in e for e in out["a"]["candidates"][0]["evidence"])


@pytest.fixture()
def channel_vault(tmp_path):
    """A vault built to isolate one scoring channel per note.

    `people-hub` is reachable ONLY through shared participants, `alpha-initiative-review` only
    through a code that lives in its title and filename, `declared-holder` only through a declared
    frontmatter code, and `mixed-signals` only through several individually sub-threshold signals.
    """
    v = tmp_path / "cv"
    (v / "notes").mkdir(parents=True)

    (v / "notes" / "people-hub.md").write_text(
        "---\ntitle: Coordination Hub\n"
        "stakeholders: [Alice Anderson, Bob Brown, Carol Clark, Dave Dawson, Erin Evans]\n"
        "---\nRoutine coordination.\n", encoding="utf-8")
    # Carries the code in filename + title only; declares nothing.
    (v / "notes" / "alpha-initiative-review.md").write_text(
        "---\ntitle: Alpha Initiative Review\n---\nBody text.\n", encoding="utf-8")
    # Declares BETA-9 but never spells it out in title or filename.
    (v / "notes" / "declared-holder.md").write_text(
        "---\ntitle: Quarterly Holder\ncontract: BETA-9\n---\nBody text.\n", encoding="utf-8")
    # Wears BETA-9 in filename + title, declares nothing.
    (v / "notes" / "beta-9-mentioned.md").write_text(
        "---\ntitle: Beta 9 Mentioned\n---\nBody text.\n", encoding="utf-8")
    # Reachable only by sub-threshold signals: token overlap, a tag, and participants. Its people are
    # disjoint from people-hub's, so each note isolates exactly one channel.
    (v / "notes" / "mixed-signals.md").write_text(
        "---\ntitle: Zeppelin Marmalade Quinine\ntags: [thunderclap]\n"
        "stakeholders: [Frank Foster, Gina Grant, Hank Hills]\n---\nBody text.\n",
        encoding="utf-8")
    for i in range(12):
        (v / "notes" / f"filler-{i}.md").write_text(
            f"---\ntitle: Routine Item {i}\n---\nFiller.\n", encoding="utf-8")
    return v


PEOPLE = ["alice.anderson@example.org", "bob.brown@example.org", "carol.clark@example.org",
          "dave.dawson@example.org", "erin.evans@example.org"]
MIXED_PEOPLE = ["frank.foster@example.org", "gina.grant@example.org", "hank.hills@example.org"]


def test_person_channel_alone_cannot_leave_the_new_band(channel_vault):
    """Five shared participants and nothing else must not reach `correlated`.

    Participant overlap is the weakest channel there is in a small organisation, where the same
    handful of people appear on most notes. Uncapped it used to stack into the `correlated` band.
    """
    out = run_engine(channel_vault, [
        {"id": "a", "title": "unrelated subject line", "participants": PEOPLE}])
    top = out["a"]["candidates"][0]
    assert top["note"].endswith("people-hub.md"), "the person channel must still surface the note"
    assert out["a"]["score"] < 40, f"person-only pileup escaped the NEW band: {top}"
    assert out["a"]["state"] == "new"


def test_code_in_title_and_filename_outranks_a_person_only_match(channel_vault):
    """A code the note only WEARS still beats a note that merely shares every participant."""
    out = run_engine(channel_vault, [
        {"id": "a", "title": "", "codes": ["ALPHA-INITIATIVE"], "participants": PEOPLE}])
    notes = [c["note"] for c in out["a"]["candidates"]]
    assert any(n.endswith("alpha-initiative-review.md") for n in notes), notes
    assert notes[0].endswith("alpha-initiative-review.md"), notes
    assert any("(title)" in e for e in out["a"]["candidates"][0]["evidence"])


def test_declared_code_outranks_a_title_only_code(channel_vault):
    """Same token, two notes: the one that DECLARES it must win."""
    out = run_engine(channel_vault, [{"id": "a", "title": "", "codes": ["BETA-9"]}])
    ranked = {c["note"]: c["score"] for c in out["a"]["candidates"]}
    declared = next(n for n in ranked if n.endswith("declared-holder.md"))
    worn = next(n for n in ranked if n.endswith("beta-9-mentioned.md"))
    assert ranked[declared] > ranked[worn], ranked
    assert out["a"]["candidates"][0]["note"] == declared, ranked
    assert any("(declared)" in e for e in out["a"]["candidates"][0]["evidence"])


def test_only_sub_threshold_signals_report_weak_not_correlated(channel_vault):
    """40+ built entirely out of signals below MIN_ANCHOR_SIGNAL is `weak`, never `correlated`."""
    out = run_engine(channel_vault, [
        {"id": "a", "title": "quinine marmalade zeppelin thunderclap",
         "participants": MIXED_PEOPLE}])
    top = out["a"]["candidates"][0]
    assert top["note"].endswith("mixed-signals.md"), top
    assert top["score"] >= 40, top
    assert out["a"]["state"] == "weak", out["a"]
    assert out["a"]["weak"] is True


def test_two_aliases_of_one_note_are_not_two_signals(tmp_path):
    """An alias is another name for the SAME note, so a second name is not corroboration.

    Uncapped this was the one channel strong enough to defeat both guards: two hits scored 70 and
    anchored, and each hit individually cleared MIN_ANCHOR_SIGNAL, so neither the floor rule nor the
    `weak` state saw anything wrong.
    """
    v = tmp_path / "pv"
    (v / "notes").mkdir(parents=True)
    (v / "notes" / "many-names.md").write_text(
        "---\ntitle: Zeppelin Committee\naliases: [Marmalade Working Group]\n---\nBody.\n",
        encoding="utf-8")
    for i in range(12):
        (v / "notes" / f"filler-{i}.md").write_text(
            f"---\ntitle: Routine Item {i}\n---\nFiller.\n", encoding="utf-8")

    out = run_engine(v, [{"id": "a", "title": "Zeppelin Committee and Marmalade Working Group"}])
    top = out["a"]["candidates"][0]
    assert top["note"].endswith("many-names.md"), top
    assert out["a"]["state"] != "anchored", out["a"]
    assert top["score"] < 70, top


def test_abbreviated_alias_inside_a_longer_name_scores_once(corr_vault):
    """'Widget Prog' sits inside 'Widget Programme': one match seen twice, not two matches."""
    out = run_engine(corr_vault, [{"id": "a", "title": "Re: Widget Programme timeline"}])
    top = out["a"]["candidates"][0]
    assert top["note"].endswith("widget-programme.md")
    phrases = [e for e in top["evidence"] if e.startswith("phrase ")]
    assert len(phrases) == 1, phrases


def test_capped_evidence_stays_within_the_declared_width():
    """The `capped:` marker takes a slot inside EVIDENCE_MAX, it does not extend the list."""
    mod = _load_engine_module()
    res = mod.correlate({"id": "x", "title": "alpha beta gamma delta epsilon"}, _tiny_index(mod))
    for cand in res["candidates"]:
        assert len(cand["evidence"]) <= mod.EVIDENCE_MAX, cand


def test_registered_in_neurokeeper_cli():
    from neurokeeper.cli import ENGINES
    assert ENGINES.get("correlate") == "vault-correlate.py"


# --- helpers ---------------------------------------------------------------

def _load_engine_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("vault_correlate_mod", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tiny_index(mod):
    cards = [mod.NoteCard({
        "note": "n/alpha.md", "reldir": "n", "stem": "alpha",
        "title": "Alpha Beta Gamma Delta Epsilon", "aliases": [], "tags": [],
        "codes": [], "people": [], "links_out": [], "note_type": None})]
    return mod.VaultIndex(cards)


# --- record-number patterns ------------------------------------------------------------------

def _register(tmp_path, patterns):
    import yaml
    p = tmp_path / "register.yaml"
    p.write_text(yaml.safe_dump({"identifier_patterns": patterns}), encoding="utf-8")
    return ["--register", str(p)]


def test_record_number_matches_body_text_on_both_sides(corr_vault, tmp_path):
    """The point of the channel: neither side declares anything, both merely mention the number."""
    (corr_vault / "notes" / "order-log.md").write_text(
        "---\ntitle: Order Log\n---\nDelivery for 60B00027 is late.\n", encoding="utf-8")
    reg = _register(tmp_path, {"order": {"match": r"(?<![0-9A-Za-z])\d[0-9A-Z][A-Z][0-9A-Z]{5}(?![0-9A-Za-z])",
                                         "min_digits": 6}})
    out = run_engine(corr_vault, [{"id": "a", "title": "Invoice for 60B00027"}], reg)
    top = out["a"]["candidates"][0]
    assert top["note"].endswith("order-log.md")
    assert any("record 60B00027" in e for e in top["evidence"])


def test_min_digits_rejects_a_word_shaped_match(corr_vault, tmp_path):
    (corr_vault / "notes" / "hashy.md").write_text(
        "---\ntitle: Hashy\n---\nCommit 9AB41235 landed.\n", encoding="utf-8")
    reg = _register(tmp_path, {"order": {"match": r"\b[0-9A-Z]{8}\b", "min_digits": 7}})
    out = run_engine(corr_vault, [{"id": "a", "title": "About 9AB41235"}], reg)
    assert not any("record" in e for c in out["a"]["candidates"] for e in c["evidence"])


def test_record_channel_is_capped_so_an_index_note_cannot_win(corr_vault, tmp_path):
    """A note LISTING many numbers must not outrank one that is about a single one."""
    (corr_vault / "notes" / "tracker.md").write_text(
        "---\ntitle: Tracker\n---\n60B00027 60B00028 60B00029 60B00030 60B00031\n", encoding="utf-8")
    reg = _register(tmp_path, {"order": {"match": r"(?<![0-9A-Za-z])\d[0-9A-Z][A-Z][0-9A-Z]{5}(?![0-9A-Za-z])",
                                         "min_digits": 6}})
    out = run_engine(corr_vault, [{"id": "a", "title": "60B00027 60B00028 60B00029 60B00030 60B00031"}], reg)
    top = out["a"]["candidates"][0]
    assert top["score"] <= 45 + 25, f"record channel exceeded its budget: {top['evidence']}"
    assert any("budget spent" in e for e in top["evidence"])


def test_changing_patterns_invalidates_the_cache(corr_vault, tmp_path):
    """patcodes are baked into the cached card, and the note file has not changed."""
    (corr_vault / "notes" / "order-log.md").write_text(
        "---\ntitle: Order Log\n---\nDelivery for 60B00027.\n", encoding="utf-8")
    item = [{"id": "a", "title": "Invoice for 60B00027"}]
    run_engine(corr_vault, item)                      # no patterns: caches patcodes = []
    reg = _register(tmp_path, {"order": {"match": r"(?<![0-9A-Za-z])\d[0-9A-Z][A-Z][0-9A-Z]{5}(?![0-9A-Za-z])",
                                         "min_digits": 6}})
    out = run_engine(corr_vault, item, reg)           # same cache file, patterns now present
    assert any("record 60B00027" in e for c in out["a"]["candidates"] for e in c["evidence"]), \
        "stale cache swallowed the pattern channel"


def test_a_broken_pattern_is_skipped_not_fatal(corr_vault, tmp_path):
    reg = _register(tmp_path, {"bad": "([unclosed", "ok": r"\bPROJ-\d\b"})
    out = run_engine(corr_vault, [{"id": "a", "title": "About delivery", "codes": ["PROJ-1"]}], reg)
    assert out["a"]["candidates"], "one bad regex sank the whole run"
