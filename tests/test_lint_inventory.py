"""Tests for the read-only reporters: vault-frontmatter-lint.py + vault-taxonomy-inventory.py.

Locks: lint is advisory (exit 0) and counts off-vocab values; outbox `pending` is exempt
only when note_type:outbox (the by-path one is still flagged -> count == 1); inventory
--json keys are stable and fenced inline tags are not counted.
"""
import json

LINT = "vault-frontmatter-lint.py"
INV = "vault-taxonomy-inventory.py"


def test_lint_offvocab_and_outbox_exemption(mini_vault, run_engine):
    r = run_engine(LINT, "--json", env=mini_vault["env"])
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)

    status = res["offvocab"]["status"]
    assert status.get("open") == 1
    assert status.get("in-review") == 1
    assert status.get("approved") == 1
    # Two notes have status:pending; the note_type:outbox one is EXEMPT, so only the
    # by-path outbox note is flagged. Count==1 proves the note_type exemption works.
    assert status.get("pending") == 1

    assert res["counts"]["parse_err"] == 1          # malformed.md
    assert res["counts"]["missing_note_type"] >= 1


def test_lint_check_is_advisory_exit_zero(mini_vault, run_engine):
    r = run_engine(LINT, "--check", env=mini_vault["env"])
    assert r.returncode == 0


def test_inventory_json_keys_stable(mini_vault, run_engine):
    r = run_engine(INV, "--json", env=mini_vault["env"])
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)

    assert {"total_md", "by_top_dir", "naming", "frontmatter", "tags"} <= set(d)
    assert {"with_fm", "field_frequency", "status_values", "coverage_pct"} <= set(d["frontmatter"])
    assert {"distinct_total", "top_30", "merge_candidate_groups"} <= set(d["tags"])
    assert "with_ -- " in d["naming"]
    assert d["naming"]["with_ -- "] >= 1               # Foo Bar -- Baz
    assert d["naming"]["with_emdash_or_endash"] >= 1   # Alpha — Beta

    top = d["tags"]["top_30"]
    assert "project" in top        # inline tag counted
    assert "ignored" not in top    # fenced inline tag NOT counted (code-fence strip)
