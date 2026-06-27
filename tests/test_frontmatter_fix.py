"""Tests for the frontmatter reconciler: scripts/vault-frontmatter-fix.py.

Locks: status off-vocab remaps; approved => maturity move + status active; outbox
`pending` preserved BOTH via note_type AND via path (order-independence); --dates drops
`date` only when it equals `created`; dry-run default never writes; idempotency.
"""
import json

ENGINE = "vault-frontmatter-fix.py"


def _read(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def test_dry_run_default_changes_nothing(mini_vault, run_engine, hash_tree):
    before = hash_tree(mini_vault["root"])
    assert run_engine(ENGINE, env=mini_vault["env"]).returncode == 0
    # --dates without --apply still must not write
    assert run_engine(ENGINE, "--dates", env=mini_vault["env"]).returncode == 0
    assert hash_tree(mini_vault["root"]) == before


def test_apply_status_maturity_and_outbox(mini_vault, run_engine):
    root, env = mini_vault["root"], mini_vault["env"]
    r = run_engine(ENGINE, "--apply", "--force", "--json", env=env)
    assert r.returncode == 0, r.stderr
    stats = json.loads(r.stdout)
    assert stats["status_remap"] == 2     # open->active, in-review->review
    assert stats["maturity_move"] == 1    # approved -> maturity:approved + status:active
    assert stats["horizon_remap"] == 1    # past -> timeless
    assert stats["files_changed"] == 3
    assert stats["date_dropped"] == 0     # no --dates

    open_note = _read(root, "02 - Projects/status-open.md")
    assert "status: active" in open_note
    assert "horizon: timeless" in open_note
    assert "status: review" in _read(root, "02 - Projects/status-in-review.md")

    appr = _read(root, "02 - Projects/status-approved.md")
    assert "status: active" in appr
    assert "maturity: approved" in appr

    # outbox pending preserved via BOTH derivation paths
    assert "status: pending" in _read(root, "00 - Inbox/outbox-typed.md")   # via note_type
    assert "status: pending" in _read(root, "11 - Outbox/mail/x.md")        # via path


def test_dates_drop_only_when_equal_created(mini_vault, run_engine):
    root, env = mini_vault["root"], mini_vault["env"]
    r = run_engine(ENGINE, "--apply", "--dates", "--force", "--json", env=env)
    assert r.returncode == 0, r.stderr
    stats = json.loads(r.stdout)
    assert stats["date_dropped"] == 1
    assert stats["date_kept_diff"] == 1

    eq = _read(root, "02 - Projects/date-equal.md")
    assert "date: 2026-06-01" not in eq      # redundant date dropped
    assert "created: 2026-06-01" in eq        # created retained

    diff = _read(root, "02 - Projects/date-diff.md")
    assert "date: 2026-05-15" in diff         # genuinely different date retained


def test_apply_is_idempotent(mini_vault, run_engine, hash_tree):
    env = mini_vault["env"]
    assert run_engine(ENGINE, "--apply", "--force", env=env).returncode == 0
    after_first = hash_tree(mini_vault["root"])
    r2 = run_engine(ENGINE, "--apply", "--force", "--json", env=env)
    assert r2.returncode == 0
    assert json.loads(r2.stdout)["files_changed"] == 0
    assert hash_tree(mini_vault["root"]) == after_first


def test_forbidden_zones_skip_on_apply(mini_vault, run_engine):
    # VAULT_FORBIDDEN_ZONES (opt-in) makes the mutator skip files under the listed reldirs.
    # All reconcilable notes in the fixture live under "02 - Projects", so forbidding it = zero writes.
    env = dict(mini_vault["env"]); env["VAULT_FORBIDDEN_ZONES"] = "02 - Projects"
    root = mini_vault["root"]
    before = _read(root, "02 - Projects/status-open.md")
    r = run_engine(ENGINE, "--apply", "--force", "--json", env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["files_changed"] == 0      # forbidden zone -> nothing reconciled
    assert _read(root, "02 - Projects/status-open.md") == before   # untouched
    assert "status: open" in before
