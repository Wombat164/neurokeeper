# Competitive landscape

A 2026-06 survey of the OSS tools adjacent to neurokeeper, and what it means for the project. Methodology:
stars/pushed/contributors/license pulled live from the GitHub API and claims checked by **reading the source,
not the README**. Star counts badly overstate maturity here (several high-star repos are single-commit
blueprints) - this weighs *executed* evidence over stars.

## The field (real competitors only)

### Vault hygiene
- **vault-health-mcp** - deterministic vault-health MCP (orphans / broken-links / frontmatter) + a
  Pro-license-gated `repair_vault`. The closest paid competitor, but **dead on arrival** (0 stars, created +
  last-pushed the same day) and buggy: its orphan check only fires on a bespoke `type: leaf` taxonomy
  (false-negatives on any normal vault), its broken-link check flags every image embed + heading link
  (false-positives), and the paid auto-repair would *strip legitimate links*. MCP-only - **no CI gate.**
- **obsidian-cli-ops** - `obs doctor` / `obs health` (orphans, broken links, tag coverage, PageRank staleness).
  Deterministic, but **no exit codes** (can't gate CI) and a SQLite index that drifts from disk.
- **obsidian-mcp-pro** - closest architecturally: headless disk link-graph, 3-way orphan/dead-end classes,
  unused-attachment detection. But **wikilink-only** broken-link scan; no canvas/base; MCP, no CI gate.
- **istefox/obsidian-mcp-connector**, **cyanheads/obsidian-mcp-server** - broad MCP CRUD; istefox has
  `find_broken_links`/`find_orphaned_notes` but is **GUI-metadataCache-bound** (not headless / not CI).
- **LLM "lint the wiki"** (claude-obsidian ~8k*, llm-knowledge-bases, obsidian-skills) - non-deterministic,
  can't gate CI, mostly prompt prose.
- **Native plugins (the apply layer)** - obsidian-linter (frontmatter *shape*, no controlled-vocab), Tag
  Wrangler (rename, no duplicate *detection*), Broken Links (best heading/block resolution; detect-only),
  find-unlinked-files (canvas-blind). neurokeeper detects + proposes; these apply - complementary, not rivals.
- **Generic link checkers** - lychee / markdown-link-check: external URLs only; wikilink support is experimental
  and can't resolve Obsidian extensionless links.

### Memory / second brain
- **claude-dream** - the closest memory-audit analogue: audit -> propose -> approve -> **verify** over MEMORY.md;
  but LLM-judgement (no score/curve), coarse approval, **no audit log**.
- **claude-memory-compiler** (~1.2k*) - strongest lint design: 7 checks incl. asymmetric-backlink
  (`auto_fixable`), source-hash staleness, LLM contradiction; a `--structural-only` flag toggles to the
  free/deterministic subset.
- **jojoprison/mnemo** - per-note-type staleness budgets + `reviewed:`/`ttl:` snooze + a byte-budget index warning.
- **claude-memory-health** - hot/cold tiering, but a **cron scheduler invoking `--dangerously-skip-permissions`**
  (the exact antipattern neurokeeper exists to avoid). **claude-mem** (~84k*) - a RAG capture engine, a
  different category. **Anthropic Auto Dream / Remember** - background consolidation that **auto-applies with
  no stated guardrail.**

## Where neurokeeper is genuinely differentiated (verified)

1. **Determinism + `--check`/`--strict` exit codes.** Of ~19 tools surveyed, **none** combines deterministic
   detection with a pipeline exit-code gate - the deterministic ones are MCP-only or have no exit codes; the
   rest put an LLM in the loop. This is the headline.
2. **Headless + stateless** - runs on plain files; no GUI cache, no derived index to drift.
3. **`.base` referential integrity - entirely unclaimed.** No surveyed tool lints `.base` references at all.
4. **`.canvas` integrity, vault-wide, CI-gateable.** Precise claim (survives a skeptic): *no tool checks whether
   a canvas node's `file` still exists in the vault, nor does canvas integrity as part of a deterministic
   vault-wide CI scan.* The nearest, `mcp-server-obsidian-jsoncanvas`, is a per-file SDK that validates
   intra-canvas edge->node IDs at construction time but **never file existence**.
5. **Stem-collision detection** - no other tool has it (vault-health-mcp silently *loses data* to collisions).
6. **Memory-audit rigour** - the only design combining a deterministic health score + decay curve + a
   tamper-evident **hash-chained** audit log + **never-auto-apply** + per-row anomaly-gated confirm. Every rival
   auto-applies or is LLM-judged.

## Backlog this surfaced (prioritised)

**High**
- External URL liveness as a *composable* step (compose with lychee; cache + JUnit/JSON) so `doctor` also covers URL rot.
- SARIF + JUnit findings emitters (machine-readable CI reporting on top of the exit codes).
- Heading (`#`) / block (`^`) link-target resolution in ref-audit (a link that resolves the file but not the heading is still broken).
- Deterministic **contradiction / supersession candidate** detector (propose-only) + a `supersedes:` frontmatter field - the #1 feature memory rivals have that we lack, done the determinism-safe way.
- Asymmetric-backlink check (A->B but not B->A; `auto_fixable`).
- `claims-audit.md` gating README/release wording; `SECURITY.md` + private reporting; a safe-by-default plugin permission preset (deny secret-file reads + destructive bash; subprocess env-scrub).

**Medium**
- Per-note-type decay half-lives + `reviewed:`/`ttl:` snooze + a byte-budget (not just line count) for the memory index.
- A read-only **MCP wrapper** over the deterministic engines (captures the agent-editing audience without an LLM in the loop).
- Deterministic stale signals (stale-by-date, title-shadow-tags, orphan sources) + a stateless hub/PageRank report.
- `guards.yaml` (each engine declares the LLM failure mode it addresses + a retirement signal); config SSOT + a CI drift-check.

## Antipatterns we deliberately avoid (validated by the field)
- Pro-license-gated, destructive auto-repair (vault-health-mcp).
- An LLM inside the linter/gate (non-deterministic, can't gate CI, costs money, "skips on API failure").
- Scheduled / auto-apply memory dreaming + `--dangerously-skip-permissions`.
- Derived-index staleness (we recompute statelessly).
- Star-chasing + marketing/code drift (claims gated behind executed evidence).

## Deferrals confirmed
- **RRF / SQLite-FTS5 search:** stay deferred. At index-fits-in-context scale (under ~2,000 notes) a structured
  index beats vector search (the compiler + the Karpathy "LLM-wiki" school skip RAG on principle). Revisit past
  ~1,500-2,000 notes.
- **Bi-temporal / supersedes graph:** stay deferred; adopt only the cheap slice - a `supersedes:` field set on
  operator confirm + the decay curve aging out the loser. Full validity-window modelling belongs to a
  git-versioned audit trail, not the memory store.
