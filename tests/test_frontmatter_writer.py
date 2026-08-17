"""The writer half of the frontmatter contract.

This library could READ frontmatter and not write it, so every engine emitting a note hand-rolled
the other half and each copy learned the quoting edge cases separately or not at all. A parser
without its writer is half a contract.

The tests that matter are the round trip (what the writer emits, the reader must parse back to the
same values) and determinism (a re-render of unchanged input must be byte-identical, or a content
hash cannot mean "someone edited this").
"""
import pytest

yaml = pytest.importorskip("yaml")

from neurokeeper.lib import parse_frontmatter, render_frontmatter, yaml_scalar  # noqa: E402


def _roundtrip(fields):
    return parse_frontmatter(render_frontmatter(fields) + "\nbody\n")


def test_a_simple_mapping_round_trips():
    fields = {"title": "Ordinary note", "note_type": "note"}
    assert _roundtrip(fields) == fields


def test_a_list_round_trips():
    assert _roundtrip({"tags": ["alpha", "bravo"]}) == {"tags": ["alpha", "bravo"]}


def test_booleans_stay_booleans():
    # Emitted bare, not quoted: "true" as a string would silently change the field's type.
    assert _roundtrip({"draft": True, "final": False}) == {"draft": True, "final": False}


def test_empty_values_are_omitted_not_emitted_blank():
    """A key with no value claims the field was considered and left empty. Absent is different."""
    out = render_frontmatter({"title": "x", "nothing": "", "none": None, "empty_list": []})
    assert "nothing" not in out and "none" not in out and "empty_list" not in out


@pytest.mark.parametrize("value", [
    "A: colon here",
    "- leading dash",
    "-",
    "#hash first",
    "yes",
    "no",
    "null",
    "~",
    'quote " inside',
    "brace { and } and [ bracket ]",
    "percent %s and at @ and backtick `",
    "ampersand & star * bang ! pipe | gt >",
])
def test_values_that_would_change_meaning_survive_the_round_trip(value):
    """Each of these is bare YAML that parses as something OTHER than the string given."""
    assert _roundtrip({"title": value})["title"] == value


@pytest.mark.parametrize("given,expected", [
    (" leading space", "leading space"),
    ("trailing space ", "trailing space"),
    ("double  spaced", "double spaced"),
])
def test_surrounding_whitespace_is_NORMALISED_not_preserved(given, expected):
    """The contract is normalise-then-quote, not byte preservation, and that is the right one.

    An invisible leading space in a title is an artefact of copy-paste, and preserving it produces
    two titles that look identical and do not match, which breaks every link and lookup keyed on the
    title. Asserted explicitly because it is a deliberate loss of fidelity rather than an oversight.
    """
    assert _roundtrip({"title": given})["title"] == expected


def test_a_control_character_is_stripped_rather_than_quoted():
    """Quoting alone does not save a raw control byte: YAML rejects it inside the quotes too.

    Found by emitting real note titles; a vertical tab in a title produced frontmatter the
    collection's own linter could not parse.
    """
    out = render_frontmatter({"title": "before\vafter"})
    assert "\v" not in out
    assert parse_frontmatter(out + "\nbody\n")["title"] == "before after"


def test_newlines_fold_to_spaces():
    assert _roundtrip({"title": "two\nlines"})["title"] == "two lines"


def test_output_is_deterministic():
    """Re-rendering unchanged input must produce identical bytes.

    Without this an idempotency ledger is useless: every re-render reads as a hand-edit, so the
    engine either rewrites files forever or stops trusting its own hash.
    """
    fields = {"title": "A", "tags": ["x", "y"], "draft": False, "n": 3}
    assert render_frontmatter(fields) == render_frontmatter(fields)


def test_insertion_order_is_preserved():
    out = render_frontmatter({"zeta": 1, "alpha": 2, "mid": 3})
    assert out.index("zeta") < out.index("alpha") < out.index("mid")


def test_the_writer_output_is_what_the_reader_expects():
    """End to end against the real parser, not a YAML load of the whole document."""
    doc = render_frontmatter({"title": "Round trip", "tags": ["a"]}) + "\n# Heading\n\nbody\n"
    assert parse_frontmatter(doc) == {"title": "Round trip", "tags": ["a"]}


# --- negative controls: the quoter must not quote everything -----------------------------------

@pytest.mark.parametrize("value", ["plain", "with-hyphens-inside", "CamelCase", "digits123"])
def test_ordinary_values_are_left_bare(value):
    # A quoter that quotes everything round-trips fine and makes every file noisier than it needs
    # to be, so the restraint is worth asserting.
    assert yaml_scalar(value) == value


def test_an_empty_string_becomes_explicit_quotes():
    assert yaml_scalar("") == '""'
