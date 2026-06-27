"""Tests for the morphological tag reconciler: scripts/vault-tag-reconcile.py.

Locks: case/plural/hyphen variants merge (source/sources, red-team/redteam, SIAM/siam);
EXCLUDE_NORMS protects pac/pacs; the trailing-s guard keeps CIS/CI separate (over-merge
regression lock); dry-run default never writes.
"""
import json

ENGINE = "vault-tag-reconcile.py"


def _members(proposal):
    return {proposal["canonical"]} | {m[0] for m in proposal["merge"]}


def test_dry_run_default_changes_nothing(mini_vault, run_engine, hash_tree):
    before = hash_tree(mini_vault["root"])
    assert run_engine(ENGINE, env=mini_vault["env"]).returncode == 0
    assert run_engine(ENGINE, "--json", env=mini_vault["env"]).returncode == 0
    assert hash_tree(mini_vault["root"]) == before


def test_proposals(mini_vault, run_engine):
    r = run_engine(ENGINE, "--json", env=mini_vault["env"])
    assert r.returncode == 0, r.stderr
    props = json.loads(r.stdout)["proposals"]
    all_members = [_members(p) for p in props]

    # source/sources merge (canonical is a count tie -> only membership asserted)
    assert any(m == {"source", "sources"} for m in all_members)
    # red-team/redteam merge -> kebab-case canonical
    assert any(_members(p) == {"red-team", "redteam"} and p["canonical"] == "red-team"
               for p in props)
    # SIAM/siam merge -> lowercase canonical
    assert any(_members(p) == {"SIAM", "siam"} and p["canonical"] == "siam"
               for p in props)

    # EXCLUDE_NORMS: pac / pacs never auto-merged
    assert all("pac" not in m and "pacs" not in m for m in all_members)
    # over-merge regression lock: CIS / CI must stay distinct (short-code trailing-s guard)
    assert all("CIS" not in m and "CI" not in m for m in all_members)
