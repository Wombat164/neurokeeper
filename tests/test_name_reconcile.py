"""Tests for the link-aware filename reconciler: scripts/vault-name-reconcile.py.

THE PRIORITY suite. Locks the red-team hardening:
  * dry-run default never writes
  * --apply rewrites the FULL link matrix (incl. escaped-pipe table links)
  * slash-decoy [[TCP/IP]] is NOT mangled (the 2026-06-27 title-with-slash bug)
  * daily / dotfile / no-rename-zone notes are skipped
  * clobber: a name whose kebab target already exists as a DIFFERENT file is neither
    renamed nor link-repointed
  * fail-closed: --apply with no VAULT_NORENAME_ZONES exits 2
  * idempotency: a second --apply is a no-op
"""
import json
import os

ENGINE = "vault-name-reconcile.py"


def test_dry_run_default_changes_nothing(mini_vault, run_engine, hash_tree):
    before = hash_tree(mini_vault["root"])
    r = run_engine(ENGINE, env=mini_vault["env"])
    assert r.returncode == 0, r.stderr
    assert "proposal" in r.stdout.lower()
    assert hash_tree(mini_vault["root"]) == before   # dry-run-default safety


def test_dry_run_json_counts(mini_vault, run_engine):
    r = run_engine(ENGINE, "--json", env=mini_vault["env"])
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    # Foo Bar -- Baz, AB12 Dossier, Alpha — Beta, Clob Target  (Legal File / Raw excluded)
    assert d["rename_count"] == 4
    assert d["has_dash"] == 2          # Foo Bar -- Baz + Alpha — Beta
    assert d["collisions"] == {}


def test_apply_rewrites_full_link_matrix(mini_vault, run_engine):
    root, env = mini_vault["root"], mini_vault["env"]
    r = run_engine(ENGINE, "--apply", "--force", env=env)
    assert r.returncode == 0, r.stderr

    hub = (root / "00 - Inbox" / "links-hub.md").read_text(encoding="utf-8")
    assert "[[foo-bar-baz]]" in hub
    assert "[[foo-bar-baz|alias]]" in hub
    assert r"[[foo-bar-baz\|tbl]]" in hub          # escaped-pipe (table) link rewritten
    assert "[[foo-bar-baz#h]]" in hub
    assert "![[foo-bar-baz]]" in hub
    assert "[[02 - Projects/foo-bar-baz]]" in hub  # folder-qualified link rewritten
    assert "[[Foo Bar -- Baz" not in hub            # no stale references remain

    # REGRESSION LOCK: title-with-slash decoy must be untouched
    assert "[[TCP/IP]]" in hub
    # CLOBBER: link to the clobbered note must NOT be repointed
    assert "[[Clob Target]]" in hub


def test_apply_renames_files_and_preserves_dossier_code(mini_vault, run_engine):
    root, env = mini_vault["root"], mini_vault["env"]
    assert run_engine(ENGINE, "--apply", "--force", env=env).returncode == 0

    proj = set(os.listdir(root / "02 - Projects"))
    assert "foo-bar-baz.md" in proj
    assert "Foo Bar -- Baz.md" not in proj
    assert "AB12-dossier.md" in proj          # uppercase dossier code preserved
    assert "ab12-dossier.md" not in proj
    assert "AB12 Dossier.md" not in proj
    assert "alpha-beta.md" in set(os.listdir(root / "03 - Domains"))

    # CLOBBER: source not renamed, pre-existing target untouched
    assert "Clob Target.md" in proj
    assert "clob-target.md" in proj


def test_apply_skips_daily_dotfile_and_norename_zones(mini_vault, run_engine):
    root, env = mini_vault["root"], mini_vault["env"]
    assert run_engine(ENGINE, "--apply", "--force", env=env).returncode == 0
    assert (root / "01 - Daily" / "2026-06-27.md").exists()       # daily skipped
    assert (root / ".hidden.md").exists()                             # dotfile skipped
    assert "Legal File.md" in set(os.listdir(root / "06 - Procurement"))  # no-rename zone
    assert "Raw.md" in set(os.listdir(root / "Sources"))             # no-rename zone


def test_apply_fail_closed_without_norename_zones(mini_vault, run_engine, hash_tree):
    env2 = dict(mini_vault["env"])
    env2.pop("VAULT_NORENAME_ZONES", None)
    before = hash_tree(mini_vault["root"])
    r = run_engine(ENGINE, "--apply", "--force", env=env2)
    assert r.returncode == 2
    assert "VAULT_NORENAME_ZONES" in r.stderr
    assert hash_tree(mini_vault["root"]) == before   # nothing written before the refusal


def test_apply_is_idempotent(mini_vault, run_engine, hash_tree):
    env = mini_vault["env"]
    assert run_engine(ENGINE, "--apply", "--force", env=env).returncode == 0
    after_first = hash_tree(mini_vault["root"])
    r2 = run_engine(ENGINE, "--apply", "--force", env=env)
    assert r2.returncode == 0
    assert "nothing to rename" in r2.stdout.lower()
    assert hash_tree(mini_vault["root"]) == after_first
