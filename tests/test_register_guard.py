"""The author-time guard: block on what THIS edit introduced, count the rest.

Firing on pre-existing violations is the documented way a linter gets switched off. Applying a
register to a mature collection produces findings on day one that nobody present caused; a reader
ignores all of them to reach the one that is theirs, and then stops reading.

So the two assertions that matter are opposites, and both are here: a file with an old finding must
NOT block when you edit an unrelated line, and the same file MUST block the moment the edit adds a
bad value.
"""
import json
import os
import subprocess
import sys

import pytest

HARNESS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(HARNESS, "scripts", "register-lint.py")

REGISTER = """
tiers: [request, agreement]
tier_fields:
  request: request
  agreement: contract
entities:
  ALPHA-1:
    tier: agreement
    source: decided
    aliases: [alpha1]
  BRAVO-2:
    tier: request
    source: decided
  CHARLIE-3:
    tier: agreement
    source: inferred
"""


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=120)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "collection"
    r.mkdir()
    (tmp_path / "register.yaml").write_text(REGISTER, encoding="utf-8")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.org")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "commit.gpgsign", "false")
    return r


def _commit(repo, name, body):
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x", "--no-verify")


def _run(repo, tmp_path, *args):
    env = dict(os.environ)
    env["IDENTIFIER_REGISTER"] = str(tmp_path / "register.yaml")
    env["VAULT_ROOT"] = str(repo)
    r = subprocess.run([sys.executable, ENGINE, "--root", str(repo), *args],
                       capture_output=True, text=True, env=env, timeout=180)
    return r


# A document that is already wrong: ALPHA-1 is an agreement, declared under `request`.
OLD_BAD = "---\nrequest: ALPHA-1\ntitle: old\n---\n\nbody line\n"


def test_an_unrelated_edit_does_not_block_on_an_old_finding(repo, tmp_path):
    # THE point of the whole feature.
    _commit(repo, "doc.md", OLD_BAD)
    (repo / "doc.md").write_text(OLD_BAD.replace("body line", "body line edited"), encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"))
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_backlog_is_still_reported_when_asked(repo, tmp_path):
    # Not blocking is not the same as hiding. A backlog nobody can see cannot be worked down.
    _commit(repo, "doc.md", OLD_BAD)
    (repo / "doc.md").write_text(OLD_BAD.replace("body line", "body line edited"), encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"), "--verbose")
    assert "pre-existing" in r.stdout
    assert r.returncode == 0


def test_a_newly_introduced_contradiction_blocks(repo, tmp_path):
    # The opposite direction. A guard that never blocks is not a guard.
    _commit(repo, "doc.md", "---\ntitle: clean\n---\n\nbody\n")
    (repo / "doc.md").write_text("---\ntitle: clean\nrequest: ALPHA-1\n---\n\nbody\n",
                                 encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ALPHA-1" in r.stderr


def test_a_blocking_message_carries_the_remedy(repo, tmp_path):
    # A guard that says only "wrong" gets silenced.
    _commit(repo, "doc.md", "---\ntitle: clean\n---\n\nbody\n")
    (repo / "doc.md").write_text("---\ntitle: clean\nrequest: ALPHA-1\n---\n\nbody\n",
                                 encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"))
    assert "fix:" in r.stderr
    assert "contract" in r.stderr          # names the field it belongs under
    assert "canon:" in r.stderr            # and where to go and argue with the rule


def test_an_alias_is_caught_with_its_canonical_spelling(repo, tmp_path):
    _commit(repo, "doc.md", "---\ntitle: clean\n---\n\nbody\n")
    (repo / "doc.md").write_text("---\ntitle: clean\ncontract: alpha1\n---\n\nbody\n",
                                 encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"))
    assert r.returncode == 1
    assert "ALPHA-1" in r.stderr


def test_an_inferred_entry_never_blocks(repo, tmp_path):
    """ADR-0005: provenance is the limit on enforcement.

    CHARLIE-3 was inferred, not decided. Blocking someone's work on a guess the tool made about
    their own vocabulary is how the tool loses the argument about whether it should exist.
    """
    _commit(repo, "doc.md", "---\ntitle: clean\n---\n\nbody\n")
    (repo / "doc.md").write_text("---\ntitle: clean\nrequest: CHARLIE-3\n---\n\nbody\n",
                                 encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "advisory" in (r.stdout + r.stderr).lower()


def test_hook_mode_blocks_with_exit_2(repo, tmp_path):
    # What a PostToolUse hook requires. Opt-in, because 2 is also this engine's NOT-CONFIGURED code.
    _commit(repo, "doc.md", "---\ntitle: clean\n---\n\nbody\n")
    (repo / "doc.md").write_text("---\ntitle: clean\nrequest: ALPHA-1\n---\n\nbody\n",
                                 encoding="utf-8")
    assert _run(repo, tmp_path, "--guard", str(repo / "doc.md"), "--hook").returncode == 2


def test_an_untracked_file_is_fully_in_scope(repo, tmp_path):
    """"Cannot narrow" must mean every line, never no lines.

    A brand-new file has no diff to compare against. Treating that as "nothing changed" would wave
    through exactly the document most likely to be wrong.
    """
    _commit(repo, "other.md", "---\ntitle: x\n---\n")
    (repo / "new.md").write_text("---\nrequest: ALPHA-1\n---\n\nbody\n", encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "new.md"))
    assert r.returncode == 1, r.stdout + r.stderr


def test_a_clean_edit_says_nothing_and_exits_0(repo, tmp_path):
    _commit(repo, "doc.md", "---\ncontract: ALPHA-1\n---\n\nbody\n")
    (repo / "doc.md").write_text("---\ncontract: ALPHA-1\n---\n\nbody edited\n", encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"))
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_the_whole_collection_report_still_never_blocks_on_scope(repo, tmp_path):
    # The report and the guard are different jobs; --staged narrows the report without hiding.
    _commit(repo, "old.md", OLD_BAD)
    (repo / "new.md").write_text("---\ntitle: clean\n---\n", encoding="utf-8")
    _git(repo, "add", "new.md")
    r = _run(repo, tmp_path, "--staged", "--json")
    data = json.loads(r.stdout)
    assert data["pre_existing_out_of_scope"] == 1     # counted, not discarded
    assert data["findings"] == []


def test_out_of_scope_findings_are_counted_not_discarded(repo, tmp_path):
    # If the backlog were dropped instead of counted it could grow unobserved, which is the failure
    # the scoping family exists to avoid rather than to cause.
    _commit(repo, "old.md", OLD_BAD)
    r = _run(repo, tmp_path, "--since", "HEAD")
    assert "pre-existing" in r.stdout
    assert r.returncode == 0


def test_a_register_with_no_tier_fields_is_not_a_pass(repo, tmp_path):
    """A register naming no field checks nothing, and must not report OK.

    Found on a real register: 141 entities, no tier_fields, and the engine printed "OK: every
    declared identifier is used as the register describes (141 entities)" over a scan of zero
    fields. A clean bill of health from a check that never ran is worse than no check, because it
    is believed.
    """
    (tmp_path / "register.yaml").write_text(
        "tiers: [agreement]\nentities:\n  ALPHA-1:\n    tier: agreement\n    source: decided\n",
        encoding="utf-8")
    _commit(repo, "doc.md", OLD_BAD)
    r = _run(repo, tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "no `tier_fields`" in r.stderr
    assert "OK" not in r.stdout


def test_a_central_alias_map_is_read(repo, tmp_path):
    """Aliases declared centrally, not per entity.

    Both shapes are real: per-entity keeps the name beside the thing, a central map is what you get
    when spellings were collected before entities were. Reading only the first shape lost every
    alias silently -- and alias is the one class exact matching cannot see, so the check looked
    present and caught nothing.
    """
    (tmp_path / "register.yaml").write_text(
        "tiers: [agreement]\ntier_fields:\n  agreement: contract\n"
        "aliases:\n  alpha1: ALPHA-1\n"
        "entities:\n  ALPHA-1:\n    tier: agreement\n    source: decided\n", encoding="utf-8")
    _commit(repo, "doc.md", "---\ntitle: clean\n---\n\nbody\n")
    (repo / "doc.md").write_text("---\ntitle: clean\ncontract: alpha1\n---\n\nbody\n",
                                 encoding="utf-8")
    r = _run(repo, tmp_path, "--guard", str(repo / "doc.md"))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ALPHA-1" in r.stderr


def test_a_central_alias_to_nothing_is_refused(repo, tmp_path):
    # An alias pointing at a missing entity would resolve values to an identifier the register
    # cannot describe, and every verdict about them would be invented.
    (tmp_path / "register.yaml").write_text(
        "tiers: [agreement]\ntier_fields:\n  agreement: contract\n"
        "aliases:\n  ghost: NOT-AN-ENTITY\n"
        "entities:\n  ALPHA-1:\n    tier: agreement\n    source: decided\n", encoding="utf-8")
    r = _run(repo, tmp_path)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "no such entity" in r.stderr


def test_the_report_does_not_block_without_check(repo, tmp_path):
    """It printed "This report never blocks" and returned 1 anyway.

    That contradiction made it impossible to compose as an ADVISORY member of an aggregate: doctor
    added it, and the whole roll-up went red on findings the report itself calls non-blocking.
    """
    _commit(repo, "doc.md", OLD_BAD)
    r = _run(repo, tmp_path)
    assert "finding(s)" in r.stdout          # it DID find something
    assert r.returncode == 0                 # and it still did not block


def test_check_is_what_makes_it_a_gate(repo, tmp_path):
    # The other half: --check must still fail, or the gate is gone entirely.
    _commit(repo, "doc.md", OLD_BAD)
    assert _run(repo, tmp_path, "--check").returncode == 1


def test_json_mode_follows_the_same_rule(repo, tmp_path):
    _commit(repo, "doc.md", OLD_BAD)
    assert _run(repo, tmp_path, "--json").returncode == 0
    assert _run(repo, tmp_path, "--json", "--check").returncode == 1
