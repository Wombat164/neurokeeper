# ADR-0001: Backend contract - Obsidian coupling, posture, and scope

- Status: **Accepted** (proof shipped; full multi-backend is trigger-gated, not scheduled)
- Date: 2026-06-28
- Context engine: `scripts/_backend.py`, `scripts/vault-name-reconcile.py`

## Context

The deterministic vault engines were written against Obsidian conventions. An audit found the coupling
concentrated at **five seams**:

1. **LINK** - wikilink grammar (`[[t]]`, `[[t|a]]`, `[[t#h]]`, `![[t]]`, `[[folder/t]]`, escaped-pipe `[[t\|a]]`)
2. **METADATA** - YAML `---` frontmatter
3. **TAGS** - `#tag` inline + frontmatter `tags:`
4. **STORE** - the markdown file walk / read / write / rename
5. **GUARD** - the "is the editor running" write preflight (the Linter-corruption guard)

Two motivations were raised: (a) an "exit strategy" from Obsidian (the *app* is proprietary, though the
*data* is open markdown), and (b) running the engines over other note stores (plain-markdown, Foam).

## Key finding (load-bearing)

**The engines already survive an Obsidian exit.** Five of six engines never touch a link - they walk the
filesystem, read YAML, and match `#tags`, all identical across Obsidian / Foam / plain-markdown. The only
Obsidian-*app* dependency is the write-GUARD, which is a safety feature for Obsidian users and already a
no-op elsewhere. So the cheap 80% ("do not hard-depend on the app") was already true in how the engines
were written (env-driven `VAULT_ROOT`, filesystem walk, YAML). The data is portable markdown; the "exit"
is "switch editor", not "migrate data".

A second finding bounds the abstraction: the canonical `Link(target, anchor, alias, embed)` model is
**intentionally lossy** - it cannot round-trip Obsidian's escaped-pipe table syntax `[[t\|a]]`. So
link-*rewriting* cannot be a single generic transform; each backend supplies its own. Obsidian uses a
verbatim, byte-identical regex; the generic (markdown) rewriter handles unambiguous `[a](t.md)` links.

## Decision

1. **Posture: files-on-disk is the default substrate; the Obsidian app is an optional accelerator.** The
   write-GUARD is the only app affordance, and it is a capability flag (`requires_write_guard`), not a hard
   dependency. Everything else operates on files directly, so the engines run headless (CI / pre-commit).
2. **Ship the seam, prove it, stop there.** `scripts/_backend.py` provides the contract + `get_backend()`
   (dispatch on `VAULT_BACKEND`, default `obsidian`) + two reference adapters: `ObsidianBackend` (wraps the
   existing logic verbatim -> byte-identical) and `MarkdownBackend` (plain `[a](t.md)` links, no guard).
   `vault-name-reconcile` consumes the STORE + LINK + GUARD seams. This **proves the coupling is isolable**;
   that proof *is* the deliverable.
3. **Do NOT finish the full refactor or build a Foam adapter now.** It is **trigger-gated**: add an adapter
   or move an engine onto the seam only when one of these fires --
   - a real user requests another backend (Foam / plain-markdown), or
   - the owner actually decides to leave Obsidian, or
   - a specific engine needs the STORE/GUARD seam for a concrete headless-CI use.
   Until a trigger fires, the optionality is held for free; building it now is breadth spent before the
   project has earned adoption depth (the multi-backend hygiene-tool user base is currently empty).
4. **Opportunistic only:** when editing one of the not-yet-refactored engines for another reason, swap its
   raw `md_files` / `safe_write` / guard calls for the STORE/GUARD seam in passing (mechanical, low-risk).
   Do not touch the LINK seam beyond `name-reconcile` without a real second wikilink backend in hand.

## Known gaps (deferred by design; documented so they are not surprises)

- **No tag-rewrite or frontmatter-write seam.** The TAGS/METADATA seams are read-only today. The three
  hardest mutators (`tag-reconcile`, `frontmatter-fix`, `set-note-type`) therefore keep their write logic
  engine-local; they are *not* yet backend-decoupled. Add `make_tag_rewriter` / a frontmatter-field writer
  if/when a second backend needs them.
- **STORE is `.md`-only.** `.canvas` (JSON) and `.base` (YAML) references are not updated on rename - a
  rename can leave dangling canvas/base links. Out of scope until a trigger fires; flagged here.
- **No link-RESOLVE seam.** Shortest-path resolution lives inside the Obsidian adapter; link-graph engines
  (orphans/backlinks) would need a `resolve()` seam before they can decouple.
- **`MarkdownBackend` is experimental.** Its rewriter only repoints explicit `.md` note links and skips
  external URLs, anchor-only and extension-less targets, and links inside code fences (hardened after a
  red-team found it corrupted URLs / fenced links). It is not yet validated against a real markdown vault
  at scale.

## Consequences

- The Obsidian exit is held **cheaply** - the insurance was mostly pre-paid by the engines' filesystem +
  YAML design; this ADR records the recipe to add an adapter on demand.
- We avoid an engines x backends test-matrix tax and a near-duplicate Foam adapter for a user base that
  does not exist yet.
- The seam is real and documented, so exercising the option later is a bounded, well-understood task rather
  than a rewrite.
