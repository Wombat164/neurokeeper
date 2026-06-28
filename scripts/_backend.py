#!/usr/bin/env python3
# @capability:  backend-contract
# @compute:     deterministic
# @effect:      read-only
# @engine:      scripts/_backend.py
# @prompt:      (none)
# @adapters:    import (shared helper)
# @portability: L1a-generic
# @forbidden:   n/a
# @audit:       none
# @status:      experimental
# @doc:         docs/pattern-portable-core-and-adapters.md
r"""Backend contract: the small, documented seam that makes the vault engines backend-agnostic.

PROOF-FIRST. This module abstracts the FIVE places where the deterministic engines were coupled to
Obsidian, so the same engines can run over a different note store (plain-markdown / Foam tomorrow) by
swapping ONE object. It is deliberately tiny -- a proof that the coupling is real and isolable, not a
framework.

The five coupling seams (the interface):
  1. LINK     -- parse/emit internal links. find_links(text) -> [(span, Link)]; render_link(Link) -> str;
                 make_link_rewriter(rename_map) -> callable(text) -> (new_text, n) for the rename use-case.
  2. METADATA -- read_frontmatter(text) -> dict|None ; split(text) -> (fm_text, body). YAML `---` default,
                 with the 64KB alias-bomb cap (delegated to _vault_lib).
  3. TAGS     -- find_tags(text) -> set[str]  (frontmatter tags + inline #tags).
  4. STORE    -- iter_notes() / read(path) / write(path, text) / rename(src, dst). Filesystem-markdown
                 default; write() routes through the existing safe_write (symlink/out-of-vault guard).
  5. GUARD    -- assert_safe_to_write(force=False) -- the editor-write preflight capability.

Two reference adapters, dispatched by `get_backend(name=None)` on env VAULT_BACKEND (default "obsidian"):
  * ObsidianBackend ("obsidian", DEFAULT) -- the REFERENCE adapter. WRAPS the existing _vault_lib regexes
    / md_files / safe_write and _vault_guard.assert_obsidian_closed so behaviour is byte-identical to the
    pre-contract engines. It does NOT rewrite that logic; it adapts it.
  * MarkdownBackend ("markdown") -- plain-markdown links `[alias](target.md#anchor)` / `![alt](img.png)`,
    YAML frontmatter, filesystem store, NO editor guard (files-on-disk are always safe to write).

NB the canonical Link model is intentionally lossy (target/anchor/alias/embed only). Obsidian's escaped-pipe
table syntax `[[t\|a]]` cannot survive a parse-and-reemit round-trip through it, so ObsidianBackend OVERRIDES
make_link_rewriter with a target-only substring rewrite (the hardened verbatim regex moved here from the
engine) -- that is what preserves byte-identity + the table-link / slash-decoy / clobber regressions. The
generic find_links/render_link splice (base class) is used by stores where parse-and-reemit is safe.
"""
import os
import re
from collections import namedtuple

from _vault_lib import (  # the shared deterministic core -- the Obsidian adapter wraps these
    VAULT,
    md_files,
    safe_write,
    parse_frontmatter,
    split_frontmatter,
    folder_suffixes,
)

try:
    from _vault_guard import assert_obsidian_closed
except Exception:  # pragma: no cover -- guard helper optional (mirrors the engines' own fallback)
    def assert_obsidian_closed(force=False):
        pass

# Canonical internal link model. Exactly the four fields named in the contract; deliberately lossy
# (it does NOT capture Obsidian's escaped-pipe backslash -- see module docstring).
Link = namedtuple("Link", ["target", "anchor", "alias", "embed"])

# Tag grammar (shared default; mirrors vault-tag-reconcile's inline-tag + code-fence handling).
_INLINE_TAG = re.compile(r"(?:^|\s)#([A-Za-z][\w/\-]+)")
_FENCE = re.compile(r"```.*?```", re.S)

# Extensions the GENERIC (markdown) rename rewriter treats as a NOTE link. Markdown internal links carry
# an explicit ext `[a](foo.md)`, so we REQUIRE one -- extension-less/bare targets and external URLs are
# NOT repointed (the `""` here was the external-URL-corruption bug the red-team found). An image
# `Foo Bar.png` sharing a renamed note's stem is excluded by the same rule. (Obsidian's extension-less
# wikilinks are handled by ObsidianBackend's verbatim override, which does not use this set.)
_NOTE_EXTS = {".md", ".markdown"}
# A target carrying a URI scheme (http:, https:, mailto:, obsidian:, ...) is external -- never repoint it.
_URI_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.I)


class Backend:
    """Base backend: filesystem-markdown STORE + YAML METADATA + #tag TAGS + a no-op write GUARD.

    Link grammar (seam 1) is abstract -- a concrete adapter MUST provide find_links + render_link
    (or override make_link_rewriter). Everything else has a working default both adapters share.
    """

    name = "base"
    #: capability flag (seam 5): True iff this store needs an editor-write preflight before bulk writes.
    requires_write_guard = False

    def __init__(self, vault=None):
        self.vault = vault or VAULT

    # --- seam 1: LINK -------------------------------------------------------------------------------
    def find_links(self, text):
        """Return [((start, end), Link), ...] for every internal link in `text`."""
        raise NotImplementedError

    def render_link(self, link):
        """Emit the backend's surface syntax for `link`."""
        raise NotImplementedError

    def make_link_rewriter(self, rename_map):
        """Build a closure(text) -> (new_text, changed_int) that repoints any link whose target BASENAME
        stem is a key of `rename_map` to the mapped stem. Generic parse-and-reemit via find_links /
        render_link; splices in reverse so spans stay valid. ObsidianBackend overrides this for byte
        identity. `changed_int` is 1 if the file changed (the engine counts files, not links)."""
        def rewrite(text):
            # Do not rewrite links inside fenced code blocks (doc examples / dataview queries).
            fences = [(m.start(), m.end()) for m in _FENCE.finditer(text)]
            changed = False
            for (start, end), link in sorted(self.find_links(text), key=lambda x: x[0][0], reverse=True):
                if any(a <= start < b for a, b in fences):
                    continue  # inside a code fence -- leave it
                tgt = link.target
                if not tgt or tgt.startswith("#") or _URI_SCHEME.match(tgt):
                    continue  # anchor-only / external URL / non-target -- never repoint
                base = os.path.basename(tgt)
                stem, ext = os.path.splitext(base)
                new_stem = rename_map.get(stem)
                if new_stem is None or ext.lower() not in _NOTE_EXTS:
                    continue  # only repoint .md NOTE links (skip images/assets/extension-less targets)
                dirpart = tgt[: len(tgt) - len(base)]
                new_link = link._replace(target=dirpart + new_stem + ext)
                text = text[:start] + self.render_link(new_link) + text[end:]
                changed = True
            return text, (1 if changed else 0)
        return rewrite

    # --- seam 2: METADATA ---------------------------------------------------------------------------
    def split(self, text):
        """(frontmatter_text, body) -- YAML `---` default. body includes the closing fence
        (the existing split_frontmatter semantics). (None, text) when there is no frontmatter."""
        return split_frontmatter(text)

    def read_frontmatter(self, text):
        """Parsed frontmatter dict, None if absent, {'__parse_error__': True} on YAML error / >64KB
        (the alias-bomb cap is enforced inside parse_frontmatter)."""
        return parse_frontmatter(text)

    # --- seam 3: TAGS -------------------------------------------------------------------------------
    def find_tags(self, text):
        """Set of tags: frontmatter `tags:` (str or list) + inline `#tags` outside code fences."""
        tags = set()
        fm = parse_frontmatter(text)
        if fm and not fm.get("__parse_error__"):
            t = fm.get("tags")
            if isinstance(t, list):
                tags.update(str(x) for x in t)
            elif isinstance(t, str):
                tags.update(x for x in re.split(r"[,\s]+", t) if x)
        body = text.split("\n---", 1)[-1] if text.startswith("---") else text
        for m in _INLINE_TAG.finditer(_FENCE.sub("", body)):
            tags.add(m.group(1))
        return tags

    # --- seam 4: STORE ------------------------------------------------------------------------------
    def iter_notes(self):
        """Yield (abspath, reldir) for every note (the md_files walk, env-driven exclusions)."""
        return md_files(self.vault)

    def read(self, path):
        """Read a note. newline='' preserves the file's existing CRLF/LF (no reflow on rewrite)."""
        return open(path, encoding="utf-8", newline="").read()

    def write(self, path, text):
        """Write a note through the vault-confined safe_write (raises VaultWriteError on symlink /
        out-of-vault). Preserves CRLF/LF."""
        return safe_write(path, text)

    def rename(self, src, dst):
        """Rename a note file. Vault-confinement / symlink / two-step policy stays in the caller."""
        return os.rename(src, dst)

    # --- seam 5: GUARD ------------------------------------------------------------------------------
    def assert_safe_to_write(self, force=False):
        """Preflight before a bulk write. Base = no-op (files-on-disk are always safe)."""
        return None


class ObsidianBackend(Backend):
    """REFERENCE adapter (DEFAULT). Wraps the existing Obsidian-coupled logic verbatim so refactored
    engines stay byte-identical: wikilinks, the hardened rename regex, and assert_obsidian_closed."""

    name = "obsidian"
    requires_write_guard = True

    # [[t]] | [[t|a]] | [[t#h]] | [[t\|a]] | ![[t]] | [[folder/t]]  (inner is non-greedy, no nested brackets)
    _WIKILINK = re.compile(r"(!?)\[\[([^\[\]]+?)\]\]")

    def find_links(self, text):
        out = []
        for m in self._WIKILINK.finditer(text):
            inner = m.group(2)
            alias = None
            am = re.search(r"\\?\|", inner)          # alias after an optionally-escaped pipe
            if am:
                alias = inner[am.end():]
                inner = inner[:am.start()]
            anchor = None
            if "#" in inner:
                inner, anchor = inner.split("#", 1)
            out.append(((m.start(), m.end()),
                        Link(target=inner, anchor=anchor, alias=alias, embed=(m.group(1) == "!"))))
        return out

    def render_link(self, link):
        s = link.target
        if link.anchor:
            s += "#" + link.anchor
        if link.alias is not None:                   # NB plain pipe -- lossy vs escaped-pipe \| (see docstring)
            s += "|" + link.alias
        return ("!" if link.embed else "") + "[[" + s + "]]"

    def make_link_rewriter(self, rename_map):
        """OVERRIDE: the hardened verbatim rename regex (moved out of vault-name-reconcile unchanged).
        A target-only substring rewrite -- byte-identical to the pre-contract engine, which is what keeps
        the escaped-pipe table link, the TCP/IP slash-decoy, the folder-suffix match and the clobber gap
        all behaving exactly as the regression suite locks them.

        path-prefix may ONLY be a REAL vault folder (folder_suffixes), never arbitrary text-before-'/'
        (the 2026-06-27 TCP/IP corruption bug). Lookahead includes '\\' so escaped-pipe links
        [[stem\\|alias]] (common in tables) are rewritten too."""
        folders = folder_suffixes(self.vault)
        PATH = ("(?:" + "|".join(re.escape(f) for f in sorted(folders, key=len, reverse=True)) + ")?") \
            if folders else ""
        stems_alt = "|".join(re.escape(s) for s in sorted(rename_map, key=len, reverse=True))
        big = re.compile(r"(!?\[\[" + PATH + r")(" + stems_alt + r")(?=[\]|#\\])")

        def rewrite(text):
            nt = big.sub(lambda m: m.group(1) + rename_map[m.group(2)], text)
            return nt, (1 if nt != text else 0)
        return rewrite

    def assert_safe_to_write(self, force=False):
        """Refuse a bulk write while Obsidian is running (the Linter corrupts frontmatter wikilinks on
        live external writes -- the 2026-06-27 incident). Exits 2 unless force."""
        return assert_obsidian_closed(force)


class MarkdownBackend(Backend):
    """Plain-markdown adapter. Links are `[alias](target.md#anchor)` / `![alt](img.png)`; YAML frontmatter
    and filesystem store are inherited; NO editor guard (a files-on-disk store is always safe to write).
    Inherits the generic find_links-based make_link_rewriter (markdown has no escaped-pipe lossiness)."""

    name = "markdown"
    requires_write_guard = False

    # [alias](target)  or  ![alt](target) ; target captured up to the closing paren (may contain spaces).
    _MDLINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)]+)\)")

    def find_links(self, text):
        out = []
        for m in self._MDLINK.finditer(text):
            tgt = m.group(3).strip()
            anchor = None
            if "#" in tgt:
                tgt, anchor = tgt.split("#", 1)
            out.append(((m.start(), m.end()),
                        Link(target=tgt, anchor=anchor, alias=m.group(2), embed=(m.group(1) == "!"))))
        return out

    def render_link(self, link):
        tgt = link.target + ("#" + link.anchor if link.anchor else "")
        return ("!" if link.embed else "") + "[" + (link.alias or "") + "](" + tgt + ")"


_BACKENDS = {"obsidian": ObsidianBackend, "markdown": MarkdownBackend}


def get_backend(name=None, vault=None):
    """Factory: return a backend instance. `name` overrides env VAULT_BACKEND (default 'obsidian')."""
    key = (name or os.environ.get("VAULT_BACKEND") or "obsidian").strip().lower()
    cls = _BACKENDS.get(key)
    if cls is None:
        raise ValueError(f"unknown VAULT_BACKEND {key!r}; known: {', '.join(sorted(_BACKENDS))}")
    return cls(vault=vault)


__all__ = ["Link", "Backend", "ObsidianBackend", "MarkdownBackend", "get_backend"]
