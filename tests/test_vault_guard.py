"""Unit tests for the Obsidian-running preflight: scripts/_vault_guard.py.

Locks the linter-race guard contract: Obsidian running => refuse (SystemExit 2) unless
--force; not running / undeterminable => proceed.
"""
import pytest


def test_running_without_force_exits_2(monkeypatch):
    import _vault_guard as g
    monkeypatch.setattr(g, "obsidian_running", lambda: True)
    with pytest.raises(SystemExit) as exc:
        g.assert_obsidian_closed(force=False)
    assert exc.value.code == 2


def test_running_with_force_proceeds(monkeypatch):
    import _vault_guard as g
    monkeypatch.setattr(g, "obsidian_running", lambda: True)
    # force overrides the refusal -> returns normally, no SystemExit
    assert g.assert_obsidian_closed(force=True) is None


def test_not_running_proceeds(monkeypatch):
    import _vault_guard as g
    monkeypatch.setattr(g, "obsidian_running", lambda: False)
    assert g.assert_obsidian_closed(force=False) is None


def test_undeterminable_proceeds_with_warning(monkeypatch, capsys):
    import _vault_guard as g
    monkeypatch.setattr(g, "obsidian_running", lambda: None)
    assert g.assert_obsidian_closed(force=False) is None
    assert "WARN" in capsys.readouterr().err
