# Interfacing neurokeeper with an Obsidian vault

This is the consumer guide for pointing neurokeeper's engines at an Obsidian vault. Read this before
writing any glue code of your own: the wiring you are about to build almost certainly already exists as
the `ObsidianBackend` reference adapter described below.

## TL;DR

**neurokeeper's core is backend-agnostic. Obsidian is a backend, not the core.**

Every engine (`vault-ref-audit.py`, `vault-tag-reconcile.py`, `vault-name-reconcile.py`, ...) is written
against a small, documented interface - the **backend contract** in `scripts/_backend.py` - not against
Obsidian's app, plugin API, or `.obsidian/` config. Obsidian support ships as one concrete implementation
of that interface: `ObsidianBackend`. It happens to be the **default** backend (selected via the
`VAULT_BACKEND` environment variable, default value `"obsidian"`), which is why engines "just work" on an
Obsidian vault out of the box - but nothing in an engine hard-codes wikilinks, YAML frontmatter parsing
rules, or any other Obsidian convention. That logic lives entirely inside the adapter.

The practical consequence for you as a consumer: if you only ever use Obsidian, you do not need to touch
`_backend.py` at all - set `VAULT_ROOT` and go. If you ever need a different note store (plain markdown,
Foam, something else), you write a second adapter class against the same five-method interface; you do
not fork or rewrite the engines.

Full rationale + the "what is/is not decoupled yet" ledger: `docs/adr-0001-backend-contract.md` (ADR-0001).
Reference implementation: `scripts/_backend.py`.

## Setup

1. Install neurokeeper (as a plugin, or as a standalone CLI - see the project README's Install section).
2. Point it at your vault via environment variables (no config file required for basic use):
   - `VAULT_ROOT` - absolute path to the vault's root directory. Every engine reads this; there is no
     separate "Obsidian vault path" setting.
   - `VAULT_BACKEND` - which backend adapter to use. **Default: `obsidian`.** You do not need to set this
     for a normal Obsidian vault; it exists so you can switch backends later without touching engine code.
   - `VAULT_SCAN_EXCLUDE` - comma-separated directory prefixes to skip during the file walk. Default:
     `.obsidian,.claude,.git,.trash` - note that `.obsidian` (Obsidian's own config folder) is excluded by
     default, because it is app configuration, not vault content.
3. Run any engine against the vault, e.g.:
   ```
   VAULT_ROOT=/path/to/vault neurokeeper vault-ref-audit --json
   ```
   No Obsidian installation, no Obsidian CLI, and no running Obsidian process is required for this step
   (see "Headless by default" below). `VAULT_BACKEND` may be omitted - `obsidian` is the default and
   matches the vault's own wikilink/frontmatter conventions automatically.

## The five seams, and how the Obsidian adapter fills each one

ADR-0001 identifies exactly five places where the engines could have coupled to a specific note store.
Each is a named seam on the `Backend` base class in `scripts/_backend.py`; `ObsidianBackend` is the
concrete filling for all five. This table is the map from "seam the engine calls" to "what actually
happens when your vault is Obsidian":

| Seam (contract) | What it abstracts | `ObsidianBackend`'s concrete behaviour |
|---|---|---|
| **LINK** | `find_links(text)` / `render_link(link)` / `make_link_rewriter(rename_map)` - parsing and emitting internal links | Wikilink grammar: `[[target]]`, `[[target\|alias]]`, `[[target#heading]]`, embeds `![[target]]`, folder-qualified `[[folder/target]]`, and the escaped-pipe table form `[[target\|alias]]`. Rename-rewriting uses a hardened verbatim regex (not parse-and-reemit) specifically to preserve the escaped-pipe form byte-for-byte, because the generic lossy `Link` model cannot round-trip it. |
| **METADATA** | `split(text)` -> `(frontmatter_text, body)`; `read_frontmatter(text)` -> `dict \| None` | YAML `---`-delimited frontmatter block. Both `ObsidianBackend` and the generic `MarkdownBackend` use the same YAML parsing - this seam is not actually Obsidian-specific, since plain YAML frontmatter is a widely shared convention, not an Obsidian invention. |
| **TAGS** | `find_tags(text)` -> `set[str]` | Obsidian's two tag surfaces: the frontmatter `tags:` field (string or list form) **and** inline `#tag` markers in the body, outside fenced code blocks. |
| **STORE** | `iter_notes()` / `read(path)` / `write(path, text)` / `rename(src, dst)` | Plain filesystem walk over `.md` files under `VAULT_ROOT` (respecting `VAULT_SCAN_EXCLUDE`), read/write via UTF-8 with CRLF/LF preserved, `write()` routed through a symlink/out-of-vault write guard. This is filesystem behaviour, not an Obsidian API call - Obsidian never has to be running. |
| **GUARD** | `assert_safe_to_write(force=False)` | The one seam that is genuinely about the Obsidian *app*: it refuses a bulk write while `Obsidian.exe` (or the `obsidian` process on non-Windows) is running, because Obsidian's Linter plugin has been observed to corrupt frontmatter/wikilinks on live external writes. `ObsidianBackend.requires_write_guard = True` flags this; pass `force=True` to override. |

Two things worth internalising from that table:

- Four of the five seams (LINK, METADATA, TAGS, STORE) are pure text/filesystem operations. Nothing there
  requires Obsidian to be installed or running - they just happen to speak Obsidian's *syntax* when the
  `obsidian` backend is selected.
- Only GUARD is about the *app itself* being open. It is a capability flag
  (`requires_write_guard = True/False`) an adapter opts into, not something baked into every engine.

## Running the engines against an Obsidian vault: headless, no app required

Because STORE/LINK/METADATA/TAGS operate directly on the files under `VAULT_ROOT`, every read-only engine
(inventory, ref-audit, frontmatter-lint, doctor, ...) runs against an Obsidian vault with:

- no Obsidian application installed,
- no Obsidian process running,
- no Obsidian CLI, plugin API, or `.obsidian/` config read.

This is what makes the engines usable in CI / pre-commit / any headless environment: they parse the same
`[[wikilink]]` and YAML-frontmatter text that Obsidian would render, using the adapter's own regexes -
they do not ask Obsidian to do the parsing. The GUARD seam is the only place Obsidian's *running state*
matters at all, and it only fires for mutating (bulk-write) engines, as a safety preflight against the
Linter-corruption issue above - it can be bypassed with `--force` (or is simply a no-op on a backend that
doesn't set `requires_write_guard`, like `MarkdownBackend`).

## What is NOT in the core

The neurokeeper core has no knowledge of, and does not touch:

- the Obsidian application itself (installation, updates, licensing),
- Obsidian's plugin ecosystem (Linter, Tag Wrangler, Properties, Dataview, Bases, etc.) - these remain
  the "apply" layer a human works with in the app; the engines only "detect + propose",
- the `.obsidian/` folder (explicitly excluded from the file walk by default via `VAULT_SCAN_EXCLUDE`),
- Obsidian's rendering, graph view, or any GUI concept at all.

All of that is out of scope for the engines by design - they operate on `VAULT_ROOT` as a plain directory
of markdown files with YAML frontmatter and wikilinks, and the Obsidian *application* is free to be closed,
absent, or replaced by a different editor entirely.

### Adding a different backend instead of Obsidian

If your note store is not Obsidian (plain markdown, Foam, or something else), you do not modify the
engines. You add a new subclass of `Backend` in `_backend.py`-style code and register it, implementing
at minimum the two required LINK methods:

- `find_links(text)` -> list of `((start, end), Link)` spans, where `Link = namedtuple("target", "anchor", "alias", "embed")`,
- `render_link(link)` -> the surface syntax string for that backend's link format,

and, if your store's link grammar cannot safely round-trip through parse-and-reemit (as Obsidian's
escaped-pipe table syntax cannot), overriding `make_link_rewriter` with a targeted, verbatim rewrite the
same way `ObsidianBackend` does. METADATA, TAGS, and STORE have working generic defaults on the `Backend`
base class (YAML frontmatter, `#tag` + frontmatter `tags:`, plain filesystem read/write/rename) that most
markdown-based stores can inherit unchanged; GUARD defaults to a no-op (`requires_write_guard = False`),
appropriate for any store that is always safe to write on disk.

`get_backend(name=None, vault=None)` is the factory every engine calls; it dispatches on the `name`
argument or the `VAULT_BACKEND` environment variable (default `"obsidian"`) to look up the registered
backend class. Adding a backend means adding one class and one entry in that dispatch table - engines
that already call `get_backend()` need no changes to support it.

## Do not reinvent this

If you find yourself writing a regex to strip `[[wikilinks]]`, a YAML-frontmatter splitter, or a "check if
Obsidian is running before I write" guard for use with neurokeeper: stop. That wiring is already specified
and already has a working reference implementation.

- Read the seam definitions first: `docs/adr-0001-backend-contract.md`.
- Read the reference adapter: `ObsidianBackend` in `scripts/_backend.py` - it is the working, byte-identical
  implementation of every Obsidian convention the engines rely on.
- Use `MarkdownBackend` in the same file as the neutral, non-Obsidian reference point if you are building a
  second adapter: it shows exactly which parts of `Backend` you get for free (METADATA, TAGS, STORE, the
  generic `make_link_rewriter`) and which one you must always supply yourself (LINK's `find_links` /
  `render_link`).

As of this writing, ADR-0001 records the Obsidian adapter and `MarkdownBackend` as the two backends that
exist; the TAGS/METADATA seams are read-only (no tag-rewrite or frontmatter-write seam yet), STORE only
tracks `.md` files (not `.canvas`/`.base` references), and there is no link-*resolve* seam (shortest-path
resolution used by orphan/backlink detection still lives inside the Obsidian adapter specifically). If you
need any of those for a new backend, that is the known, documented gap to close - not a sign you should
work around the contract.
