"""The Item and its projections.

`correlate` ships publicly and the definition of the envelope it accepts lived in a private
consumer, so anyone using the engine reverse-engineered the shape from prose, and every new source
reader was free to invent its own. A correlation engine cannot tell a worse envelope from a worse
corpus, which makes that the kind of divergence nobody ever attributes correctly.

The projections are the point of the Item: a source reader should not need to know what the
correlation engine wants.
"""
import importlib.util
import os
from datetime import datetime, timezone

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location(
        "_ic", os.path.join(HARNESS, "scripts", "_ingest_core.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- make_item ---------------------------------------------------------------------------------

def test_an_item_has_every_declared_field(core):
    item = core.make_item(title="A")
    assert set(item) == set(core.ITEM_FIELDS)


def test_list_fields_are_always_lists_never_none(core):
    item = core.make_item()
    for f in ("path", "participants", "codes", "attachments", "loss"):
        assert item[f] == [], f


def test_an_unknown_field_is_refused(core):
    """The refusal is the useful part.

    A typo in a keyword would otherwise create a field nobody reads: the value is silently absent
    everywhere downstream while the caller believes it was set.
    """
    with pytest.raises(ValueError) as e:
        core.make_item(title="A", tilte="typo")
    assert "tilte" in str(e.value)


def test_a_missing_title_gets_a_placeholder_rather_than_none(core):
    assert core.make_item()["title"] == "untitled"


# --- correlation_envelope ----------------------------------------------------------------------

def test_the_envelope_carries_what_correlation_scores_on(core):
    item = core.make_item(title="Annex B", body="text", participants=["a@example.org"],
                          codes=["ALPHA"])
    env = core.correlation_envelope(item)
    assert set(env) == {"title", "body", "participants", "codes", "date"}
    assert env["title"] == "Annex B"
    assert env["participants"] == ["a@example.org"]


def test_declared_codes_and_classified_topics_are_merged(core):
    """Correlation wants every identifier that could anchor a match; which side produced it is not
    its concern, and keeping them apart would make a caller choose."""
    item = core.make_item(title="T", codes=["ALPHA"])
    item["topics"] = ["BRAVO", "ALPHA"]
    assert core.correlation_envelope(item)["codes"] == ["ALPHA", "BRAVO"]


def test_the_body_is_capped(core):
    item = core.make_item(title="T", body="x" * 20000)
    assert len(core.correlation_envelope(item)["body"]) == 8000
    assert len(core.correlation_envelope(item, body_cap=100)["body"]) == 100


def test_a_real_date_is_formatted_and_a_missing_one_is_none(core):
    item = core.make_item(title="T", created=datetime(2026, 8, 17, tzinfo=timezone.utc))
    assert core.correlation_envelope(item)["date"] == "2026-08-17"
    assert core.correlation_envelope(core.make_item(title="T"))["date"] is None


def test_a_non_datetime_date_does_not_crash_the_envelope(core):
    # A source reader that passes a string is wrong, and the correct response is a null date rather
    # than an exception that kills a run at document 1,203.
    item = core.make_item(title="T", created="2026-08-17")
    assert core.correlation_envelope(item)["date"] is None


def test_the_container_chain_is_NOT_in_the_matching_signal(core):
    """The measured negative result, pinned so it is not undone by intuition.

    Qualifying a title with its container looked like free signal and measured WORSE: a container
    name is identical across every item in it, so it discriminates nothing and drags them all
    toward the same notes. It stays available in `path` for an emitter.
    """
    item = core.make_item(title="Todo", path=["Section", "Subsection"])
    assert core.correlation_envelope(item)["title"] == "Todo"
    assert "Section" not in core.correlation_envelope(item)["body"]


# --- read_gate_frontmatter ---------------------------------------------------------------------

def test_a_detected_marking_is_never_reported_as_a_classification(core):
    """A classification is an authority's assertion; a detected marking is a regex hit in prose.

    Measured on a real collection: 164 notes contain high-marking text and almost none are marked.
    Asserting a marking nobody applied leaves a policy unable to tell prose from a real marking.
    """
    item = core.make_item(title="T", raw_ref="ref-1")
    item["markings"] = ["TLP:AMBER"]
    view = core.read_gate_frontmatter(item)
    assert "classification" not in view
    assert view["detected_marking"] == ["TLP:AMBER"]


def test_provenance_and_inherited_marking_are_separate_fields(core):
    """Every item has provenance; only a marked one has an inherited marking. Conflating them makes
    a rule that denies on inheritance deny everything."""
    plain = core.read_gate_frontmatter(core.make_item(title="T", raw_ref="ref-1"))
    assert plain["source_ref"] == ["ref-1"]
    assert "marking_derived_from" not in plain

    marked = core.make_item(title="T", raw_ref="ref-1")
    marked["markings"] = ["TLP:AMBER"]
    assert core.read_gate_frontmatter(marked)["marking_derived_from"] == ["ref-1"]


def test_the_source_default_is_a_parameter_not_a_hardcoded_engine(core):
    # It used to default to one engine's name, which is a per-consumer decision living in shared
    # code: every other consumer inherited a provenance label that was simply wrong.
    assert core.read_gate_frontmatter(core.make_item(title="T"))["source"] == "import"
    assert core.read_gate_frontmatter(core.make_item(title="T"),
                                      default_source="notebook")["source"] == "notebook"


def test_an_explicit_source_wins_over_the_default(core):
    assert core.read_gate_frontmatter(core.make_item(title="T", source="mail"))["source"] == "mail"
