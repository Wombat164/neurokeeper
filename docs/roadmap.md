# Roadmap: repository-agnostic direction, seams, and output adapters

- Status: living document (directions + trigger conditions, NOT a schedule; see ADR-0001 for the
  trigger-gated posture this extends)
- Created: 2026-07-04, from a production vault's obsidian-integration analysis (a full audit of how
  that env's skills/scripts/MCP/memory interact with Obsidian, and where they fail)

## Field evidence that shaped this roadmap (2026-07-04)

1. **The Obsidian CLI is not a headless path and never will be.** It is an IPC client into a running
   GUI; with the GUI closed, invoking it BOOTS the full Electron app instead of failing fast
   (verified live). Consequence: engines must never shell out to the `obsidian` CLI. Anything the
   engines need beyond files-on-disk must come through an optional capability with filesystem
   degradation (see INDEX seam below).
2. **A second production consumer exists.** A production vault wired `doctor` + `ref-audit`
   as the mandatory headless fallback inside its `/health`, `/maintenance` and `/closeday` commands
   (its eval-JS diagnostics are GUI-bound and its scheduled morning maintenance failed whenever the
   GUI was closed). This partially fires ADR-0001's third trigger ("a specific engine needs the seam
   for a concrete headless use") and raises the value of the opportunistic migration rule.
3. **The GUARD is bimodal in practice.** Editors need to be OPEN for their CLIs/plugins and CLOSED
   for external bulk writes. The reference deployment now runs a local `obsidian-preflight.py` process-check
   before any CLI call; that logic is generic and belongs here, not copy-pasted per vault.
4. **Both directions of the ecosystem-borrow doctrine got validated.** Engines detect+propose;
   Obsidian-native surfaces (Bases, Tag Wrangler, Linter) apply/query/input. Bases in particular are
   headless-WRITABLE (plain YAML files) while being GUI-rendered live, which makes them the natural
   dashboard output channel for engine results.

## Roadmap items

### R1. Engines onto the backend seam (opportunistic, now higher-value)
Only `name-reconcile` and `ref-audit` consume `_backend.py` today; the other nine engines hit
`_vault_lib`/`_vault_guard` directly. Keep ADR-0001 rule 4 (swap in passing, mechanical), but treat
the three mutators (`tag-reconcile`, `frontmatter-fix`, `set-note-type`) as the priority queue: they
need the missing tag-rewrite and frontmatter-write seams before any second backend can be honest.

### R2. Config out of code (prerequisite for any agnosticism claim)
Per-vault values currently live inside engine code: `memory-consolidate.py` hardcodes a wikilink
regex and a deployment-specific folder-exclude list (non-English folder names); `_vault_lib.py` hardcodes
`.obsidian` in scan-excludes. Move vault values (excludes, folder maps, taxonomy enums) into the
per-vault config (`config.example/` already exists) and link grammar into the backend. A backend
switch must never require editing an engine.

### R3. Backend capability descriptors + RESOLVE seam
Each backend declares: link grammar (parser/renderer), editor process names for the GUARD (e.g.
`Obsidian.exe`, `Logseq.exe`, none), config-dir name (`.obsidian`, `.logseq`), and whether a live
index exists. Add the RESOLVE seam ADR-0001 already flags (shortest-path/basename wikilink
resolution) -- `ref-audit`'s new anchor resolution (2026-07-04) deepened LINK usage and makes the
missing seam more visible.

### R4. Editor-state preflight as a first-class utility
Generalize `_vault_guard.py` into a `neurokeeper preflight` capability with BOTH directions:
`--for-write` (editor must be CLOSED; today's guard) and `--for-editor-cli` (editor must be OPEN;
what consumers calling editor CLIs/plugins need). Upstream the reference deployment's
`obsidian-preflight.py` here so every env stops hand-rolling it. Output contract: one
`MODE=...` line + exit code, stdlib only, sub-second.

### R5. INDEX seam (optional capability, never a CLI shell-out)
Some data is better from a live index (backlink graph, search index) than from an FS scan. Model it
as an optional backend capability with mandatory filesystem degradation. Explicit non-goal: calling
the `obsidian` CLI from engines (GUI-bound, boots the app when closed -- see field evidence 1). If a
live-index transport is ever wanted, the obsidian-mcp REST/FS server is the candidate carrier, not
the CLI.

### R6. Bases / dashboard output adapter (operator-requested 2026-07-04)
Engines gain an optional `--emit-base <path>` (or a small `dashboards` engine) that renders results
as Obsidian Bases / dashboard notes: `ref-audit` -> broken-links + orphans views, `doctor` -> health
rollup note, `memory-consolidate` -> stale-review queue. Rationale: headless-writable, GUI renders
live, zero CLI dependency, and it keeps the detect+propose doctrine (the Base IS the proposal
surface). Backend descriptor gates it (Bases are Obsidian-only; the markdown backend emits a plain
table note instead). Related STORE gap from ADR-0001: rename should also update `.canvas`/`.base`
references -- same file formats, do them together.

### R7. Third adapter, trigger-gated (unchanged posture)
Best validating target remains Logseq (`[[Page]]` + `((block-ref))` + journal-file STORE semantics)
or a plain Foam/Dendron dir. Build exactly one, and only when an ADR-0001 trigger fires fully. R2 +
R3 are the prerequisites that make this a bounded task.

### R8. Inbound/backlink query engine (operator-requested 2026-07-04)
A read-only `vault-inbound` engine: given note path(s), return who links in, classified by
resolution mode (exact-stem / path-qualified / markdown-link / alias-text-only = relink backlog),
single filesystem pass, `--json`. Rationale: during a real orphan-resolution run this query was
hand-rolled twice (a per-note grep loop that timed out on a cloud-synced drive, then an ad-hoc
single-pass script). The 2026-05-30 lesson generalizes: ad-hoc query invention diverges and wastes
tokens; maintained engines do not. Same code path serves ref-audit internally, so building it
mostly extracts what exists.

### R9. Fully-scripted tag governance loop (operator-requested 2026-07-04, worked example banked)
Formalize the 2026-07-04 production-vault tag optimization (2383 -> 905 distinct tags) into a
repeatable engine pipeline where fuzzy logic resolves most verdicts deterministically and an agent
lane is invoked ONLY for the gated residue:

1. **Census stage**: full tag inventory (count, zones, frozen-residue flag, sample notes) --
   either `taxonomy-inventory --tags-full` or a `tag-census` engine. Today this was an improvised
   scratchpad script; it belongs in the engine suite.
2. **Deterministic verdict stage (fuzzy logic, inside the engine)**: confidence-scored rules --
   morphological merge (exists in tag-reconcile, score 1.0), pattern classes (frontmatter-enum
   values, dates, hex colours, dossier/annex/person/org code shapes), per-vault synonym
   dictionary across locales (config), edit-distance + token-overlap against registry members, frequency-band
   priors (head tags never auto-drop; singletons default-drop unless code-shaped). Verdicts above
   threshold apply without any model.
3. **Gated agent handoff (below threshold only)**: the engine EMITS handoff packets (chunk files +
   strict tag/DROP/MERGE/KEEP schema + legal-merge-target list) and later RE-INGESTS verdict files
   through a validation gate (line-count reconciliation, target-legality, pattern downgrades,
   conservative default for missing verdicts). The LLM never runs inside the engine -- packets out,
   validated files in, per the two-lane-model-handoff doctrine. Field-proven contract: 8 parallel
   haiku-class agents, ~90s/203-tag chunk, 100% coverage; agents MUST write verdict files
   themselves (final-message-only output was lost once when transcripts were not persisted).
4. **Apply + verify stage**: deterministic rewrite (frontmatter lists + inline arrays + body tags,
   frozen-zone skips, digit-leading-tag regex hazards handled), census re-run as the verifier,
   registry regeneration (the canonical band-grouped tag registry note).
5. **Guard stage**: registry doubles as `frontmatter-lint` allowed-tags config so doctor//health
   flag novel tags on every run -- prevention instead of periodic cleanup.
6. **Operator gates**: one confirm before mass apply when drops exceed a configurable threshold or
   the run touches more than N files; frozen zones never rewritten regardless of confirmation.
   Prior art for the gating tiers: a production vault's impact-class agent-action-gating doctrine.

### R10. MCP lane stays separate
neurokeeper is the deterministic engine layer. The obsidian-mcp fork (cyanheads lineage, REST+FS
pluggable backend) is the designated MCP server lineage; a thin read-only MCP adapter over
neurokeeper engines is possible later per the portable-core graduation ladder, but engines never
grow MCP transport themselves.

### R11. Memory-index compression + verified size-cap lint (operator-requested 2026-07-04)
`memory-consolidate --lint`: a deterministic, no-model check that the always-loaded entrypoint index
stays inside the harness read cap and reads as a tight index. Three axes: (a) the TWO-axis load cap -
the memory loader reads only the first 200 lines OR 25000 bytes (24.4KB), whichever comes first, then
silently drops the rest (warn at a 140-line / 17.5KB headroom target); (b) compression - one line per
entry, telegraphic style, no ` -- `/` -> ` separators, entry-length ceiling; (c) link integrity,
reusing the orphan/broken-link pass. A context-aware `strip_protected()` removes `[[targets]]` /
backtick paths / `](targets)` BEFORE the separator check, so a legitimate dash inside a real note name
is never flagged. Backend-agnostic (applies to any backend's entrypoint index). Field receipt: a
production vault's `memory-consolidate` shipped `BYTES_BUDGET = 45000` (1.8x the real 25000 cap), so it
reported "OK" while the loader truncated the index every session - VERIFY thresholds against the real
harness limit, never hardcode a guess. neurokeeper's own copy carries the same 45000 and should be
recalibrated.

### R12. Shared / cross-env index consolidation (operator-requested 2026-07-04)
When a memory layer is SHARED across environments (a synced cross-env note set behind its own git
remote), the engines skip it today: `memory-consolidate` scans the top-level store only. The same
hygiene applies there - caveman-tight index lines, link integrity, dedup of overlapping notes, archive
of dormant ones - so a `--shared <path>` (or sibling) mode should lint and PROPOSE consolidation over
that layer too. Load-bearing constraint: a shared layer is MULTI-OWNER (other environments write to
it) and gated (scope tags, secret scan), so this stays strictly detect+propose, pull-first,
operator-confirm, and never a silent apply from one environment. Backend-agnostic: a "shared layer" is
any second-brain's synced / multi-owner subtree, not a specific product.

## Shipped this cycle (2026-07-04)

- memory-consolidate: per-note-type base half-lives (user 365 / reference 270 / feedback 180 /
  project 90; untyped identical to the prior curve) + `reviewed:`/`ttl:` snooze stamps.
- ref-audit: `[[note#heading]]` / `[[note#^block]]` anchor resolution (broken anchors,
  informational) + isolated-notes set (orphan AND dead-end).
- Adoption: a production vault wired doctor/ref-audit as the headless fallback path in its
  health/maintenance/closeday commands (first cross-vault consumer of the engines as a fallback
  tier).
- Field run: full tag optimization on a production vault (2383 -> 905 distinct; morphological via
  tag-reconcile + semantic tail via gated haiku fan-out + deterministic validation/apply) -- the
  worked example R9 formalizes. Also surfaced: engines should support argparse `--help` instead of
  running on unknown flags.

## Known engine gaps with field receipts (2026-07-04 orphan run)

A real orphan-resolution run over a 1514-note vault found `ref-audit`'s orphan set is a CANDIDATE
list, not a defect list, until two resolution gaps close:

1. **Resolution semantics diverge from Obsidian's, in both directions (the RESOLVE seam, R3).**
   Corrected 2026-07-04 after a live metadataCache test: Obsidian does NOT resolve raw `[[alias]]`
   links either (aliases only power autocomplete), so alias-text matches identify INTENDED
   references (a relink-on-touch backlog), not resolved ones. In the field run, ~40 of 52 sweep
   matches were exact-stem or markdown-link inbound that ref-audit failed to credit (real
   resolution bugs), and 12 were true Obsidian orphans caused by bare-`mv` renames. The RESOLVE
   seam must replicate Obsidian semantics exactly (stem + shortest-path + case rules, NO alias
   resolution) and expose alias matches separately as "intended but unresolved".
2. **Markdown-link parser misses valid CommonMark forms.** `[text](<path with spaces.md>)`
   angle-bracket targets are not unwrapped, a `)` inside the path (e.g. `(Worksheet).md`) truncates
   the capture, and `[` in filenames breaks the link-text match. 2 of 60 "orphans" were already
   correctly indexed by exactly such links (used deliberately because `[I]` in a filename breaks
   wikilink syntax).

Consumers should treat orphans as candidates pending verification (the production run verified with an
independent alias-aware sweep); fixing 1 belongs to R3, fixing 2 is a standalone `_MDLINK` bug.

## Non-goals (recorded so they stay said)

- No obsidian CLI shell-outs inside engines (ever).
- No LLM steps inside engines (semantic inference is vault-kb's layer).
- No engines x backends test-matrix before a second real backend user exists (ADR-0001).
