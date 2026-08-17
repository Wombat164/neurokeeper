"""Small primitives with sharp edges: content_hash, normalise_marking, load_forbidden_zones.

Each is a few lines and each has one property that, if lost, fails silently rather than loudly.
That is why they are tested at all: nobody re-reads a five-line function, and all three of these
were carrying a lesson in their comments that would have been lost by rewriting them from the
docstring.
"""
import importlib.util
import os

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location(
        "_ic", os.path.join(HARNESS, "scripts", "_ingest_core.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- content_hash ------------------------------------------------------------------------------

def test_the_separator_prevents_a_collision(core):
    """THE property. Without the NUL between parts, ("ab","c") and ("a","bc") hash the same, so two
    different items collide and an idempotency ledger treats one as a re-import of the other."""
    assert core.content_hash("ab", "c") != core.content_hash("a", "bc")


def test_it_is_stable_across_calls(core):
    assert core.content_hash("a", "b") == core.content_hash("a", "b")


def test_none_and_empty_are_handled(core):
    assert core.content_hash(None) == core.content_hash("")


# --- normalise_marking -------------------------------------------------------------------------

@pytest.mark.parametrize("given", ["TLP: Amber", "tlp:amber", "TLP  :  AMBER", "  TLP:AMBER  "])
def test_the_same_marking_written_differently_folds_to_one_form(core, given):
    """A policy comparing markings as raw strings treats these as four different markings, which is
    how a rule permitting one silently fails to permit the others."""
    assert core.normalise_marking(given) == "TLP:AMBER"


def test_internal_spacing_collapses_but_words_survive(core):
    assert core.normalise_marking("  commercial   in confidence ") == "COMMERCIAL IN CONFIDENCE"


def test_empty_is_empty(core):
    assert core.normalise_marking("") == ""
    assert core.normalise_marking(None) == ""


# --- load_forbidden_zones ----------------------------------------------------------------------

def _zones_file(tmp_path, text):
    p = tmp_path / "forbidden-zones.txt"
    p.write_text(text, encoding="utf-8")
    return p


def test_a_rationale_after_a_SINGLE_space_is_not_taken_as_part_of_the_path(core, tmp_path):
    """THE trap, and it is not cosmetic.

    Zone paths legitimately contain single spaces, so a naive split takes the rationale as part of
    the path. Every prefix match then fails, which silently disables the entire write-ban while the
    loader still reports the right number of zones. A ban that is loaded, counted and inert is
    worse than one that is absent, because the count reads as proof it works.
    """
    p = _zones_file(tmp_path, "06 - Procurement/ legal record, do not machine-edit\n")
    assert core.load_forbidden_zones(p) == ["06 - Procurement/"]


def test_a_tab_separated_rationale_works(core, tmp_path):
    p = _zones_file(tmp_path, "Framework/\tsigned contractual criteria\n")
    assert core.load_forbidden_zones(p) == ["Framework/"]


def test_a_multi_space_separated_rationale_works(core, tmp_path):
    p = _zones_file(tmp_path, "05 - Knowledge/    curated doctrine\n")
    assert core.load_forbidden_zones(p) == ["05 - Knowledge/"]


def test_a_bare_path_works(core, tmp_path):
    assert core.load_forbidden_zones(_zones_file(tmp_path, "Sources/\n")) == ["Sources/"]


def test_comments_and_blank_lines_are_skipped(core, tmp_path):
    p = _zones_file(tmp_path, "# why these exist\n\nSources/\n\n  # indented comment\n")
    assert core.load_forbidden_zones(p) == ["Sources/"]


def test_every_prefix_ends_in_exactly_one_slash(core, tmp_path):
    """So a caller cannot accidentally match `06 - Procurementdossier` against `06 - Procurement`."""
    p = _zones_file(tmp_path, "A/\nB//\nC\n")
    assert core.load_forbidden_zones(p) == ["A/", "B/", "C/"]


def test_backslashes_are_normalised(core, tmp_path):
    p = _zones_file(tmp_path, "deep\\nested\\path/\n")
    assert core.load_forbidden_zones(p) == ["deep/nested/path/"]


def test_an_absent_file_is_no_zones_not_an_error(core, tmp_path):
    # An engine with no zones configured must run, not crash: absent config is not a failure.
    assert core.load_forbidden_zones(tmp_path / "nope.txt") == []
    assert core.load_forbidden_zones(None) == []


def test_the_loaded_prefixes_work_with_in_forbidden_zone(core, tmp_path):
    """End to end against the matcher they exist to feed, not just as strings.

    The two have always shipped separately, and a loader whose output shape the matcher does not
    accept is the failure this pairing is meant to make impossible.
    """
    import sys
    sys.path.insert(0, os.path.join(HARNESS, "scripts"))
    from _vault_lib import in_forbidden_zone

    zones = core.load_forbidden_zones(_zones_file(tmp_path, "06 - Procurement/ legal record\n"))
    assert in_forbidden_zone("06 - Procurement", zones)
    assert in_forbidden_zone("06 - Procurement/sub", zones)
    assert not in_forbidden_zone("06 - Procurementdossier", zones)
    assert not in_forbidden_zone("02 - Projects", zones)
