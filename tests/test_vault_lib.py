"""Unit tests for the importable shared core: scripts/_vault_lib.py.

Locks: code/acronym preservation in kebabify, em/en-dash collapse, kebab idempotency,
frontmatter split/parse (including malformed YAML), md_files honouring VAULT_SCAN_EXCLUDE,
and folder_suffixes path-suffix enumeration.
"""
import importlib
import os

import pytest


def test_kebabify_basic():
    import _vault_lib as vl
    assert vl.kebabify("Foo Bar") == "foo-bar"
    assert vl.kebabify("Foo Bar -- Baz") == "foo-bar-baz"      # '--' collapsed
    assert vl.kebabify("Alpha — Beta") == "alpha-beta"          # em-dash collapsed
    assert vl.kebabify("Alpha – Beta") == "alpha-beta"          # en-dash collapsed


def test_kebabify_preserves_codes_and_acronyms():
    import _vault_lib as vl
    assert vl.kebabify("AB12 Dossier") == "AB12-dossier"        # dossier code preserved
    assert vl.kebabify("CD345 spec") == "CD345-spec"            # dossier code preserved
    assert vl.kebabify("EF6 ref") == "EF6-ref"                 # code-like stem preserved
    assert vl.kebabify("SIAM Note") == "SIAM-note"             # all-caps acronym preserved
    # CODE_RE / acronym recognisers behave as documented
    assert vl.CODE_RE.match("AB12")
    assert vl.CODE_RE.match("CD345")
    assert not vl.CODE_RE.match("Foo")


def test_kebabify_is_idempotent_on_canonical_names():
    import _vault_lib as vl
    assert vl.kebabify("foo-bar-baz") == "foo-bar-baz"
    assert vl.kebabify("AB12-dossier") == "AB12-dossier"
    assert vl.kebabify("SIAM-note") == "SIAM-note"


def test_split_frontmatter():
    import _vault_lib as vl
    fm, rest = vl.split_frontmatter("---\nstatus: active\n---\nbody\n")
    assert "status: active" in fm
    assert rest.startswith("\n---")
    # no frontmatter at all
    assert vl.split_frontmatter("just a body") == (None, "just a body")
    # opening fence but no closing fence -> treated as no frontmatter
    assert vl.split_frontmatter("---\nstatus: active\nbody") == (None, "---\nstatus: active\nbody")


def test_parse_frontmatter():
    import _vault_lib as vl
    assert vl.parse_frontmatter("---\nstatus: active\n---\nbody")["status"] == "active"
    assert vl.parse_frontmatter("plain note, no fm") is None
    # malformed YAML is reported, not raised
    assert vl.parse_frontmatter("---\nfoo: [unclosed\n---\nbody") == {"__parse_error__": True}


def test_md_files_explicit_exclude(tmp_path):
    import _vault_lib as vl
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "g.md").write_text("g", encoding="utf-8")
    (tmp_path / "node").mkdir()
    (tmp_path / "node" / "n.md").write_text("n", encoding="utf-8")
    got = sorted(os.path.basename(p) for p, _ in
                 vl.md_files(vault=str(tmp_path), exclude=(".git", "node")))
    assert got == ["a.md"]


def test_md_files_skips_dot_dirs(tmp_path):
    """Dot-prefixed dirs (.obsidian / .git / tool caches) are skipped even with NO explicit
    exclude - Obsidian ignores them, so they must not inflate lint/inventory counts (issue #3:
    the #2 dot-dir skip had landed only in ref-audit's own walk, not the shared md_files())."""
    import _vault_lib as vl
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "b.md").write_text("b", encoding="utf-8")
    for d in (".extractor_cache", ".obsidian", ".git"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "junk.md").write_text("junk", encoding="utf-8")
    got = sorted(os.path.basename(p) for p, _ in vl.md_files(vault=str(tmp_path), exclude=()))
    assert got == ["a.md", "b.md"], got


def test_md_files_honours_env_scan_exclude(tmp_path, monkeypatch):
    """The module-level default exclude is derived from VAULT_SCAN_EXCLUDE."""
    (tmp_path / "keepdir").mkdir()
    (tmp_path / "keepdir" / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "skipdir").mkdir()
    (tmp_path / "skipdir" / "b.md").write_text("b", encoding="utf-8")
    monkeypatch.setenv("VAULT_SCAN_EXCLUDE", "skipdir")
    import _vault_lib as vl
    importlib.reload(vl)
    try:
        assert "skipdir" in vl.SCAN_EXCLUDE
        rels = sorted(os.path.relpath(p, str(tmp_path))
                      for p, _ in vl.md_files(vault=str(tmp_path)))
        assert rels == [os.path.join("keepdir", "a.md")]
    finally:
        monkeypatch.delenv("VAULT_SCAN_EXCLUDE", raising=False)
        importlib.reload(vl)   # restore module defaults for other tests


def test_folder_suffixes(tmp_path):
    import _vault_lib as vl
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    (tmp_path / ".git" / "x").mkdir(parents=True)
    sfx = vl.folder_suffixes(vault=str(tmp_path))
    # every path-suffix of the real folder tree is present
    assert {"a/", "a/b/", "a/b/c/", "b/", "b/c/", "c/"} <= sfx
    # excluded dirs contribute no suffixes
    assert not any(s.startswith(".git") for s in sfx)
    assert "x/" not in sfx


# --- write guard: safe_write / within_vault (H4) ---

def test_safe_write_allows_normal_in_vault(tmp_path, monkeypatch):
    import _vault_lib as vl
    monkeypatch.setattr(vl, "VAULT", str(tmp_path))
    p = tmp_path / "note.md"
    p.write_text("old", encoding="utf-8")
    assert vl.safe_write(str(p), "new") == str(p)
    assert p.read_text(encoding="utf-8") == "new"


def test_safe_write_refuses_out_of_vault(tmp_path, monkeypatch):
    import _vault_lib as vl
    vault = tmp_path / "vault"; vault.mkdir()
    outside = tmp_path / "outside.md"
    monkeypatch.setattr(vl, "VAULT", str(vault))
    with pytest.raises(vl.VaultWriteError):
        vl.safe_write(str(outside), "x")
    assert not outside.exists()   # nothing written outside the vault


def test_safe_write_refuses_symlink(tmp_path, monkeypatch):
    import _vault_lib as vl
    vault = tmp_path / "vault"; vault.mkdir()
    target = vault / "real.md"; target.write_text("real", encoding="utf-8")
    link = vault / "link.md"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform")
    monkeypatch.setattr(vl, "VAULT", str(vault))
    with pytest.raises(vl.VaultWriteError):
        vl.safe_write(str(link), "evil")
    assert target.read_text(encoding="utf-8") == "real"   # write never passed through the symlink


def test_within_vault(tmp_path, monkeypatch):
    import _vault_lib as vl
    monkeypatch.setattr(vl, "VAULT", str(tmp_path))
    assert vl.within_vault(str(tmp_path / "a" / "b.md"))
    assert not vl.within_vault(str(tmp_path.parent / "elsewhere.md"))


def test_in_forbidden_zone():
    import _vault_lib as vl
    z = ("06 - Procurement", "Sources")
    assert vl.in_forbidden_zone("06 - Procurement", zones=z)
    assert vl.in_forbidden_zone("06 - Procurement/sub", zones=z)
    assert vl.in_forbidden_zone("Sources", zones=z)
    assert not vl.in_forbidden_zone("02 - Projects", zones=z)
    assert not vl.in_forbidden_zone("anything", zones=())   # unset zones => never forbidden


def test_force_utf8_stdout_is_safe():
    import _vault_lib as vl
    vl.force_utf8_stdout()   # must be a guarded no-op even when streams lack reconfigure()
