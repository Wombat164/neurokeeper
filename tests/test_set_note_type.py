"""Tests for the additive note_type setter: scripts/vault-set-note-type.py.

Locks: note_type derived per folder; outbox via path/folder; kind:Uppercase => spec;
additive only (never touches a note that already has note_type); dry-run default never
writes; idempotency.
"""
ENGINE = "vault-set-note-type.py"


def _head(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def test_dry_run_default_changes_nothing(mini_vault, run_engine, hash_tree):
    before = hash_tree(mini_vault["root"])
    r = run_engine(ENGINE, env=mini_vault["env"])
    assert r.returncode == 0, r.stderr
    assert "DRY-RUN" in r.stdout
    assert hash_tree(mini_vault["root"]) == before


def test_apply_derives_and_is_additive(mini_vault, run_engine):
    root, env = mini_vault["root"], mini_vault["env"]
    r = run_engine(ENGINE, "--apply", "--force", env=env)
    assert r.returncode == 0, r.stderr

    assert "note_type: project" in _head(root, "02 - Projects/missing-axes.md")
    assert "note_type: meeting" in _head(root, "04 - Meetings/meeting-note.md")
    assert "note_type: moc" in _head(root, "MOC/some-moc.md")
    assert "note_type: outbox" in _head(root, "11 - Outbox/mail/x.md")   # by path/folder
    assert "note_type: spec" in _head(root, "03 - Domains/kind-spec.md")  # kind:Uppercase

    # additive: a note that already has note_type is left exactly one note_type line, untouched
    already = _head(root, "02 - Projects/already-typed.md")
    assert already.count("note_type:") == 1
    assert "note_type: project" in already
    assert "title: t" in already


def test_apply_is_idempotent(mini_vault, run_engine, hash_tree):
    env = mini_vault["env"]
    assert run_engine(ENGINE, "--apply", "--force", env=env).returncode == 0
    after_first = hash_tree(mini_vault["root"])
    r2 = run_engine(ENGINE, "--apply", "--force", env=env)
    assert r2.returncode == 0
    assert "TOTAL would-set/set: 0" in r2.stdout
    assert hash_tree(mini_vault["root"]) == after_first
