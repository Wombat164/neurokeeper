"""Tests for the backend contract: scripts/_backend.py.

Locks the 5-seam abstraction + its two reference adapters:
  * the factory dispatches on VAULT_BACKEND (default obsidian) and rejects unknown backends;
  * the obsidian adapter's grammar parses/emits the wikilink forms;
  * the markdown adapter's grammar parses/emits [alias](target.md#anchor) / ![alt](img.png) and its
    rename rewriter repoints ONLY markdown note links (wikilinks + non-note assets are left alone).
This is the gate-D companion: it proves the markdown seam is real, not cosmetic.
"""
import json
import os

import pytest

from _backend import Link, MarkdownBackend, ObsidianBackend, get_backend


# --- factory (the seam selector) ----------------------------------------------------------------
def test_factory_default_is_obsidian(monkeypatch):
    monkeypatch.delenv("VAULT_BACKEND", raising=False)
    assert get_backend().name == "obsidian"
    assert get_backend().requires_write_guard is True


def test_factory_env_dispatch_and_arg_override(monkeypatch):
    monkeypatch.setenv("VAULT_BACKEND", "markdown")
    b = get_backend()
    assert b.name == "markdown"
    assert b.requires_write_guard is False
    assert get_backend("obsidian").name == "obsidian"   # explicit arg beats env


def test_factory_unknown_backend_raises():
    with pytest.raises(ValueError):
        get_backend("foam")   # not yet implemented -> explicit error, never a silent obsidian fallback


# --- obsidian link grammar ----------------------------------------------------------------------
def test_obsidian_find_links_forms():
    b = ObsidianBackend()
    parsed = [lk for _, lk in b.find_links(
        "[[t]] [[t|a]] [[t#h]] ![[t]] [[02 - Projects/t]]")]
    assert Link("t", None, None, False) in parsed
    assert Link("t", None, "a", False) in parsed
    assert Link("t", "h", None, False) in parsed
    assert Link("t", None, None, True) in parsed
    assert Link("02 - Projects/t", None, None, False) in parsed


def test_obsidian_render_round_trip():
    b = ObsidianBackend()
    for raw in ["[[t]]", "[[t|a]]", "[[t#h]]", "![[t]]"]:
        (_, lk), = b.find_links(raw)
        assert b.render_link(lk) == raw


# --- markdown link grammar (the new seam) -------------------------------------------------------
def test_markdown_find_links_forms():
    b = MarkdownBackend()
    parsed = [lk for _, lk in b.find_links(
        "see [alias](foo.md) then [a2](sub/bar.md#sec) then ![img](pic.png)")]
    assert Link("foo.md", None, "alias", False) in parsed
    assert Link("sub/bar.md", "sec", "a2", False) in parsed
    assert Link("pic.png", None, "img", True) in parsed


def test_markdown_render_round_trip():
    b = MarkdownBackend()
    for raw in ["[a](foo.md)", "[a](foo.md#sec)", "![alt](pic.png)"]:
        (_, lk), = b.find_links(raw)
        assert b.render_link(lk) == raw


def test_markdown_rewriter_repoints_only_md_note_links():
    b = MarkdownBackend()
    text = "[x](Foo Bar.md) [y](Foo Bar.md#h) [[Foo Bar]] ![p](Foo Bar.png)"
    out, n = b.make_link_rewriter({"Foo Bar": "foo-bar"})(text)
    assert n == 1
    assert "[x](foo-bar.md)" in out          # plain md note link repointed
    assert "[y](foo-bar.md#h)" in out        # anchor preserved
    assert "[[Foo Bar]]" in out              # wikilink: NOT markdown grammar -> untouched
    assert "![p](Foo Bar.png)" in out        # image asset sharing the stem -> NOT repointed


def test_markdown_rewriter_noop_when_no_match():
    b = MarkdownBackend()
    text = "[x](other.md) and [[Foo Bar]]"
    out, n = b.make_link_rewriter({"Foo Bar": "foo-bar"})(text)
    assert n == 0 and out == text


def test_markdown_rewriter_skips_urls_anchors_bare_and_fences():
    """Red-team regression: the generic rewriter must NOT corrupt external URLs / extension-less /
    anchor-only targets, nor rewrite links inside code fences -- only real `.md` note links."""
    b = MarkdownBackend()
    text = (
        "[note](Foo Bar.md)\n"                       # real md note link -> repoint
        "[ext](https://example.com/Foo Bar)\n"       # external URL -> leave (was the HIGH bug)
        "[bare](Foo Bar)\n"                          # extension-less target -> leave
        "[anchor](#Foo Bar)\n"                       # anchor-only -> leave
        "```\n[fenced](Foo Bar.md)\n```\n"           # inside a code fence -> leave (was the HIGH bug)
    )
    out, n = b.make_link_rewriter({"Foo Bar": "foo-bar"})(text)
    assert "[note](foo-bar.md)" in out
    assert "https://example.com/Foo Bar" in out
    assert "[bare](Foo Bar)" in out
    assert "[anchor](#Foo Bar)" in out
    assert "[fenced](Foo Bar.md)" in out
    assert n == 1                                    # only the one genuine note link changed


# --- shared seams (metadata + tags inherited by both adapters) -----------------------------------
def test_metadata_split_and_frontmatter():
    b = get_backend("markdown")
    fm_text, body = b.split("---\nstatus: active\ntags: [a, b]\n---\nbody\n")
    assert "status: active" in fm_text and "body" in body
    fm = b.read_frontmatter("---\nstatus: active\ntags: [a, b]\n---\nbody\n")
    assert fm["status"] == "active"
    assert b.split("no frontmatter here")[0] is None


def test_find_tags_frontmatter_and_inline_outside_fence():
    b = get_backend("obsidian")
    text = "---\ntags: [alpha, beta]\n---\nbody #gamma here\n\n```\n#ignored\n```\n"
    assert b.find_tags(text) == {"alpha", "beta", "gamma"}


# --- store seam end-to-end through the engine (markdown) -----------------------------------------
def test_name_reconcile_markdown_backend_end_to_end(tmp_path, run_engine):
    """Run the refactored engine under VAULT_BACKEND=markdown over a markdown-linked vault:
    it walks the store, rewrites the md link, renames the file, and leaves the wikilink + no-rename zone."""
    root = tmp_path / "vault"
    files = {
        "02 - Projects/Foo Bar.md": "---\nstatus: active\n---\nbody\n",
        "00 - Inbox/hub.md": "# Hub\n\n- [go](Foo Bar.md)\n- [[Foo Bar]] keep\n",
        "Sources/Raw Source.md": "---\nstatus: active\n---\nraw\n",
    }
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    env = os.environ.copy()
    env["VAULT_ROOT"] = str(root)
    env["VAULT_NORENAME_ZONES"] = "Sources"
    env["VAULT_BACKEND"] = "markdown"

    j = run_engine("vault-name-reconcile.py", "--json", env=env)
    assert j.returncode == 0, j.stderr
    d = json.loads(j.stdout)
    assert any(s["from"] == "Foo Bar" and s["to"] == "foo-bar" for s in d["sample"])

    r = run_engine("vault-name-reconcile.py", "--apply", "--force", env=env)
    assert r.returncode == 0, r.stderr
    hub = (root / "00 - Inbox" / "hub.md").read_text(encoding="utf-8")
    assert "[go](foo-bar.md)" in hub          # md link repointed by the markdown seam
    assert "[[Foo Bar]]" in hub               # wikilink left alone (grammar genuinely differs)
    assert (root / "02 - Projects" / "foo-bar.md").exists()
    assert "Raw Source.md" in os.listdir(root / "Sources")   # no-rename zone honoured
