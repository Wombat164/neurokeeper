"""Layered config: engine defaults with a site config merged over them.

Two properties carry the whole module, and both are asserted in each direction.

ADDITIVE BY DEFAULT: extending must not discard the built-ins, because a merge that silently
replaced them would disable checks the engine advertises while reporting success.

EVERY COMPLAINT NAMES ITS KEY: a bad regex or an unknown key reported without the config location
sends the reader to search a file for a value they cannot see.
"""
import importlib.util
import os
import re

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def cfg():
    spec = importlib.util.spec_from_file_location(
        "_cfg", os.path.join(HARNESS, "scripts", "_config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- compile_pattern ---------------------------------------------------------------------------

def test_a_bad_regex_names_the_config_key(cfg):
    with pytest.raises(cfg.ConfigError) as e:
        cfg.compile_pattern("[unclosed", "people.members.vip")
    assert "people.members.vip" in str(e.value)
    assert "[unclosed" in str(e.value)


def test_a_good_regex_compiles_case_insensitively(cfg):
    assert cfg.compile_pattern("hello", "x").search("HELLO")


# --- load_yaml ---------------------------------------------------------------------------------

def test_an_absent_config_is_not_an_error_and_says_so(cfg, tmp_path):
    """"No site config" and "your config was ignored" look identical from the outside otherwise."""
    raw, notes = cfg.load_yaml(tmp_path / "nope.yaml", {"a"})
    assert raw == {}
    assert any("no site config" in n for n in notes)


def test_a_known_section_loads(cfg, tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("people:\n  members: {}\n", encoding="utf-8")
    raw, notes = cfg.load_yaml(p, {"people"})
    assert raw == {"people": {"members": {}}}
    assert any("loaded" in n for n in notes)


def test_an_unknown_section_is_REPORTED_not_ignored(cfg, tmp_path):
    """The classic config failure: the file parses, the engine runs, the rule never fires."""
    p = tmp_path / "c.yaml"
    p.write_text("peopel:\n  members: {}\n", encoding="utf-8")
    _, notes = cfg.load_yaml(p, {"people"})
    assert any("peopel" in n and "unknown" in n for n in notes)


def test_strict_promotes_an_unknown_section_to_a_refusal(cfg, tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("peopel: {}\n", encoding="utf-8")
    with pytest.raises(cfg.ConfigError):
        cfg.load_yaml(p, {"people"}, strict=True)


def test_invalid_yaml_names_the_file(cfg, tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("a: [unclosed\n", encoding="utf-8")
    with pytest.raises(cfg.ConfigError) as e:
        cfg.load_yaml(p, {"a"})
    assert str(p) in str(e.value)


def test_a_top_level_list_is_refused(cfg, tmp_path):
    # A list parses fine and then every section lookup silently misses.
    p = tmp_path / "c.yaml"
    p.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(cfg.ConfigError) as e:
        cfg.load_yaml(p, {"a"})
    assert "mapping" in str(e.value)


# --- merge_named_patterns ----------------------------------------------------------------------

def test_a_new_name_is_ADDED_and_defaults_survive(cfg):
    defaults = [("greet", re.compile("hello"))]
    merged, note = cfg.merge_named_patterns(defaults, {"farewell": "bye"}, "actions")
    assert {k for k, _ in merged} == {"greet", "farewell"}
    assert "+1 new" in note


def test_a_matching_name_OVERRIDES_that_default_only(cfg):
    defaults = [("greet", re.compile("hello")), ("other", re.compile("x"))]
    merged, note = cfg.merge_named_patterns(defaults, {"greet": "hi"}, "actions")
    by = dict(merged)
    assert by["greet"].pattern == "hi"
    assert "other" in by
    assert "1 overridden" in note


def test_replace_true_discards_the_defaults_and_says_so(cfg):
    defaults = [("greet", re.compile("hello"))]
    merged, note = cfg.merge_named_patterns(defaults, {"only": "x", "replace": True}, "actions")
    assert {k for k, _ in merged} == {"only"}
    assert "REPLACED" in note


def test_an_empty_section_changes_nothing(cfg):
    defaults = [("greet", re.compile("hello"))]
    merged, note = cfg.merge_named_patterns(defaults, None, "actions")
    assert merged is defaults and note == ""


def test_a_bad_regex_inside_a_section_names_the_full_path(cfg):
    with pytest.raises(cfg.ConfigError) as e:
        cfg.merge_named_patterns([], {"vip": "[bad"}, "people.members")
    assert "people.members.vip" in str(e.value)


# --- merge_regex_union -------------------------------------------------------------------------

def test_extra_alternatives_are_UNIONED_with_the_default(cfg):
    merged, note = cfg.merge_regex_union(re.compile("alpha"), ["bravo"], False, "urgency")
    assert merged.search("alpha") and merged.search("bravo")
    assert "extended" in note


def test_replace_drops_the_built_in_alternatives(cfg):
    merged, note = cfg.merge_regex_union(re.compile("alpha"), ["bravo"], True, "urgency")
    assert merged.search("bravo") and not merged.search("alpha")
    assert "REPLACED" in note


def test_no_patterns_returns_the_default_untouched(cfg):
    d = re.compile("alpha")
    merged, note = cfg.merge_regex_union(d, None, False, "urgency")
    assert merged is d and note == ""


# --- merge_scalars -----------------------------------------------------------------------------

def test_a_known_scalar_is_overridden(cfg):
    d = {"weight": 10}
    assert cfg.merge_scalars(d, {"weight": 25}, "weights") == []
    assert d["weight"] == 25


def test_an_unknown_scalar_is_reported_and_left_out(cfg):
    """A mistyped weight silently dropped leaves an operator convinced they have tuned something."""
    d = {"weight": 10}
    notes = cfg.merge_scalars(d, {"wieght": 25}, "weights")
    assert any("wieght" in n for n in notes)
    assert d == {"weight": 10}


def test_strict_refuses_an_unknown_scalar(cfg):
    with pytest.raises(cfg.ConfigError):
        cfg.merge_scalars({"weight": 10}, {"wieght": 1}, "weights", strict=True)


def test_the_module_ships_no_vocabulary(cfg):
    """It configures anything and knows what none of it means.

    A default value, a section name or a pattern appearing here would make this the wrong file, and
    would be the first step back toward each engine growing its own merge.
    """
    src = open(os.path.join(HARNESS, "scripts", "_config.py"), encoding="utf-8").read()
    body = src.split('"""', 2)[-1]
    assert "re.compile(" not in body.replace("re.compile(pattern, re.I)", "")
