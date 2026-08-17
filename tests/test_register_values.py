"""How one frontmatter value becomes zero, one or several identifiers.

Measured on a real 3000-note collection: 418 findings, of which 270 were the literal text `[]`.
An empty list is an ABSENT value, not a wrong one - the same absent-versus-empty confusion the exit
contract fixes one layer down - and a report that is 84% artefact is a report nobody opens, which is
the documented way a check gets switched off. After this: 111 findings, with all 95 enforceable ones
unchanged.
"""
import importlib.util
import os

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def sv():
    spec = importlib.util.spec_from_file_location(
        "_rl", os.path.join(HARNESS, "scripts", "register-lint.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.split_values


@pytest.mark.parametrize("raw", ["[]", "", "none", "None", "TBD", "n/a", "-", "null", "{}"])
def test_absent_values_yield_nothing(sv, raw):
    # An author writing `programme: none` has ANSWERED the question. Reporting it as an unknown
    # identifier tells them their answer is a typo.
    assert sv(raw) == []


def test_a_list_is_several_identifiers(sv):
    # Checking "[A, B]" as one name reports a thing nobody wrote, and misses whichever member is
    # actually misfiled.
    assert sv("[ALPHA, BRAVO]") == ["ALPHA", "BRAVO"]


def test_a_list_drops_its_empty_members(sv):
    assert sv("[ALPHA, , none]") == ["ALPHA"]


def test_a_wikilink_is_the_identifier_it_references(sv):
    assert sv("[[ALPHA]]") == ["ALPHA"]


def test_a_wikilink_beats_the_list_shape(sv):
    """`[[A]]` also matches the inline-list pattern.

    Letting the list branch win strips one bracket pair and yields the literal `[A]`, which resolves
    to nothing - so a link to a note the register knows was reported as an unknown identifier.
    """
    assert sv("[[CLM-fase-2]]") == ["CLM-fase-2"]


def test_a_piped_or_anchored_wikilink_resolves_to_its_target(sv):
    assert sv("[[ALPHA|display text]]") == ["ALPHA"]
    assert sv("[[ALPHA#section]]") == ["ALPHA"]


def test_wikilinks_inside_a_list_resolve(sv):
    assert sv("[[[ALPHA]], [[BRAVO]]]") == ["ALPHA", "BRAVO"]


def test_a_plain_value_is_itself(sv):
    assert sv("ALPHA-1") == ["ALPHA-1"]
    assert sv("  'ALPHA-1'  ") == ["ALPHA-1"]


def test_a_value_containing_brackets_is_not_mangled(sv):
    # Negative control: bracket handling must not eat ordinary text.
    assert sv("Prio COM MAR (Marine ACINT)") == ["Prio COM MAR (Marine ACINT)"]
