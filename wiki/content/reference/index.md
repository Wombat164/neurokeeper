---
title: Reference
description: Engine catalog, the metadata-header spec, and environment configuration.
tags:
  - reference
---

> [!note] This is reference (information-oriented)
> Dry, look-it-up technical description. It describes *what is*; it does not teach (see
> [Tutorials](../tutorials/)) or walk you through a task (see [How-to guides](../how-to/)).

## Conventions used in the catalog

- **CLI name** - the dispatcher subcommand: `neurokeeper <name> [args]`.
- **compute x effect** - the [[explanation/index|capability typology]]: *compute* is
  `deterministic` / `llm` / `hybrid`; *effect* is `read-only` / `mutating`.
- **Universal contract** - every engine supports `--json` (machine-readable output) and meaningful
  exit codes, and is **report-by-default**. Mutating engines write only with `--apply`, and bulk vault
  writes refuse to run while a notes app is open unless given `--force`.

---

## Engine catalog

### `taxonomy-inventory`
- **compute x effect:** deterministic x read-only
- **What it does:** produces an inventory of a notes vault's filename conventions, tags, and frontmatter
  fields. The grounding read-only pass before any reconciliation.
- **Contract:** `--json`.
- **Env:** `VAULT_ROOT`, `VAULT_SCAN_EXCLUDE`.

### `ref-audit`
- **compute x effect:** deterministic x read-only
- **What it does:** audits reference integrity across the vault - unresolved links, orphans (no inbound),
  dead-ends (no outbound), broken `.canvas` and `.base` file references, orphan media (attachments
  referenced by nothing), and exact name/stem collisions (a duplicated note basename makes a bare
  `[[stem]]` link ambiguous). The read-only counterpart to `name-reconcile`. Unresolved wikilinks are
  **informational by default** (they are often intentional forward-links to not-yet-created notes);
  broken `.canvas`/`.base` refs are always real defects.
- **Since 2026-07-04:** also resolves `[[note#heading]]` / `[[note#^block]]` anchors (broken anchors
  reported informationally: the file resolves but the heading/block does not exist) and reports the
  **isolated** set (notes that are both orphan AND dead-end, i.e. fully disconnected).
- **Contract:** `--json`, `--check` (exit 1 on broken canvas/base refs), `--strict` (also fail on
  unresolved links), and `--since <git-ref>` (report only findings for notes changed since the ref;
  the scan stays graph-global, only the surfaced findings and the `--check` gate are narrowed, so it
  is ideal for a pre-commit / CI diff run). A bad ref or non-git tree exits 2 rather than silently
  scanning the wrong scope.
- **Env:** `VAULT_ROOT`, `VAULT_REFAUDIT_EXCLUDE`.

### `doctor`
- **compute x effect:** deterministic x read-only
- **What it does:** aggregate health - runs every *applicable* read-only engine (taxonomy-inventory,
  ref-audit, and - when their config is present - frontmatter-lint, memory-consolidate), prints one
  consolidated report, and rolls up an **honest** exit code. Each engine is reported as `ok` / `fail` /
  `skipped`; an engine whose required config is absent is **skipped, never silently counted as a pass**.
  The exit asserts *"an engine errored or a real gate failed"* - NOT *"the vault is healthy"*: advisory
  engines (taxonomy-inventory, frontmatter-lint) contribute numbers but cannot fail the roll-up. The CI
  entrypoint for the pre-commit / GitHub-Action adapters. See [ADR-0002](https://github.com/Wombat164/neurokeeper/blob/main/docs/adr-0002-doctor-exit-semantics.md).
- **Contract:** `--json`, `--check` (exit 1 iff a gating engine failed or any engine errored),
  `--strict` and `--since <git-ref>` (both forwarded to ref-audit; `--since` narrows the reported
  findings and the gate to notes changed since the ref).
- **Run-receipt (since 2026-07-04):** every run emits a `receipt` (`tool`, `version`, `root`,
  `files_scanned`, `engines_run`, `duration_ms`) as a `--json` field and as the header line of the human
  report. A run that scanned 0 files or the wrong root is then visible at a glance instead of passing as a
  silent green, the failure class the byte-cap and walk-exclude drifts fell into.
- **Env:** the union of the engines it runs (`VAULT_ROOT`; `FRONTMATTER_SCHEMA` / `CLAUDE_MEMORY_DIR`
  decide applicability of those two).

### `frontmatter-lint`
- **compute x effect:** deterministic x read-only
- **What it does:** validates notes against your schema-as-code - flags off-vocabulary values, missing
  recommended axes, redundant date fields, and unknown fields. Advisory (reports; does not block).
- **Contract:** `--json`, `--terse`, `--check`, `--schema <path>`, `--vault <path>`.
- **Env:** `VAULT_ROOT`, `FRONTMATTER_SCHEMA`, `VAULT_SCAN_EXCLUDE`.

### `frontmatter-fix`
- **compute x effect:** deterministic x **mutating**
- **What it does:** applies the schema's reconciliation maps (e.g. normalising status / maturity /
  horizon values) by **surgical line-edits** on the frontmatter block, preserving formatting and field
  order (no YAML reparse).
- **Contract:** `--apply`, `--force`, `--json` (report-only without `--apply`), and `--dates` --
  opt-in `date` -> `created` field dedup (kept opt-in because it ripples into Dataview queries and
  templates that still read `date`).
- **Audit:** git. **Forbidden-zones:** attended by default; optional `VAULT_FORBIDDEN_ZONES` skip.
- **Env:** `VAULT_ROOT`, `FRONTMATTER_SCHEMA`, `VAULT_FORBIDDEN_ZONES`.

### `set-note-type`
- **compute x effect:** deterministic x **mutating**
- **What it does:** additively sets a `note_type` frontmatter field derived from a folder-to-type map.
  Additive and idempotent - inserts one line, never rewrites content, skips notes that already have it.
- **Contract:** `--apply` (report-only otherwise).
- **Audit:** git. **Forbidden-zones:** scoped (folder allowlist); optional `VAULT_FORBIDDEN_ZONES` skip.
- **Env:** `VAULT_ROOT`, `VAULT_FORBIDDEN_ZONES`.

### `tag-reconcile`
- **compute x effect:** deterministic x **mutating**
- **What it does:** detects morphological tag-merge groups (case / plural / hyphen / underscore / slash
  variants of one root) and proposes a single canonical, kebab-case spelling. True synonyms are out of
  scope (supply a curated map). Preferred apply path is a notes-app tag-rename tool; `--apply` is a
  guarded fallback.
- **Contract:** `--json`, `--apply`, `--force` (report-only without `--apply`).
- **Audit:** git. **Forbidden-zones:** attended by default; optional `VAULT_FORBIDDEN_ZONES` skip.
- **Env:** `VAULT_ROOT`, `VAULT_FORBIDDEN_ZONES`.

### `name-reconcile`
- **compute x effect:** deterministic x **mutating**
- **What it does:** detects non-kebab filenames and proposes a kebab-case slug. **Link-aware** apply:
  it first rewrites every wikilink that referenced the old basename across the whole vault, *then*
  renames the file, so links never break. Protected/legal/write-once folders are excluded from rename
  but still scanned as link sources.
- **Contract:** `--json`, `--apply`, `--force`, plus a `dedash` mode (light: only normalise dash
  separators, keep case) vs the default `kebab` mode (full lowercase-hyphen slug). Scope with
  `--under <folder>` to pilot the rename on one subtree, and `--no-exclusions` to override the
  `VAULT_NORENAME_ZONES` guard (rename even protected folders - deliberate, rarely wanted).
- **Audit:** git. **Forbidden-zones:** rename-protected via `VAULT_NORENAME_ZONES`; optional
  `VAULT_FORBIDDEN_ZONES` skip (never writes those files).
- **Env:** `VAULT_ROOT`, `VAULT_NORENAME_ZONES`, `VAULT_FORBIDDEN_ZONES`.

### `memory-consolidate`
- **compute x effect:** the engine is deterministic x read-only; the full **memory-audit** capability is
  hybrid x mutating (engine + judgment + gate + audit via an adapter).
- **What it does:** the deterministic analyzer behind the memory-audit - computes a multi-metric health
  score, an importance/decay curve, and orphan / broken-link / stale / dead-end detection over a
  file-based memory store, then emits a consolidation proposal. Read-only: it proposes, never writes.
- **Decay model (since 2026-07-04):** per-note-type base half-life via frontmatter `metadata.type` --
  `user` 365d / `reference` 270d / `feedback` 180d / `project` 90d; untyped notes keep the prior 90d
  curve exactly. Reference count still multiplies the half-life (`base * (1 + log2(refs + 1))`).
- **Snooze (since 2026-07-04):** a `reviewed: YYYY-MM-DD` frontmatter stamp suppresses the stale flag
  for 120 days (override with `ttl: <days>`). Use it after deliberately re-validating an old note.
- **Index lint (since 2026-07-04):** `--lint` is an advisory, no-model check that a memory *index*
  file - the always-loaded entrypoint that a harness reads first - stays inside its read cap and
  reads as a tight index. Three axes: the two-axis load cap (200 lines OR 25000 bytes, whichever comes
  first, warn at a headroom target); one-line-per-entry telegraphic compression (no ` - ` / ` -> `
  separators, entry-length ceiling); and link integrity. Wikilink targets and backtick paths are
  stripped before the separator check, so a legitimate dash inside a real note name is never flagged.
  Never blocks (exit 0) - a nudge, not a gate.
- **Contract:** `--json`, `--check`, `--terse`, `--lint`, `--today YYYY-MM-DD`.
- **Audit (capability):** append-only, hash-chained log (not git - see [[explanation/index]]).
- **Env:** `CLAUDE_MEMORY_DIR`, optional `VAULT_INBOX_DIR`, `VAULT_ROOT`.

### `registry-generate`
- **compute x effect:** deterministic x read-only
- **What it does:** scans the harness for per-engine metadata headers and emits the capability registry.
  Anti-rot by construction - the catalog is generated from the source-of-truth headers, never
  hand-maintained. Engines without a header are listed as the classification backlog.
- **Contract:** `--json`, `--write` (writes the registry doc; prints to stdout otherwise).
- **Env:** `HARNESS_ROOT` (defaults to the repo root).

> [!info] Shared internals (not dispatcher subcommands)
> Two helper modules are imported by the engines rather than run directly: a **shared library**
> (vault walk, frontmatter split, slug helpers - one definition, imported everywhere) and a
> **write-guard** preflight (refuses bulk vault writes while the notes app is open). Both are
> deterministic and read-only.

---

## The metadata-header spec

Every engine carries a machine-parseable header in its top comment block (one field per line, matching
`@field: value`). `registry-generate` harvests these to build the catalog, so a new engine becomes
discoverable the moment it has a header.

```text
# @capability:   <short-name>          # the capability id
# @compute:      hybrid                # deterministic | llm | hybrid
# @effect:       mutating              # read-only | mutating
# @engine:       path/to/engine.py     # the deterministic script
# @prompt:       path/to/prompt.md     # the judgment template, or (none)
# @adapters:     skill:<name>, cli     # which bindings exist
# @portability:  L1a-generic           # L1a-generic | L1b-private | L2-config
# @forbidden:    enforced              # n/a | enforced | scoped
# @audit:        dream-log             # none | git | dream-log
# @status:       active                # active | experimental | deprecated
# @doc:          path/to/design.md     # the design/runbook
```

Field meanings:

| Field | Meaning |
|---|---|
| `@capability` | The capability id (the dispatcher subcommand / registry key). |
| `@compute` | Whether work is done by code, an LLM, or both. |
| `@effect` | Whether it can write (`mutating`) or only reports (`read-only`). |
| `@engine` | Path to the deterministic script. |
| `@prompt` | Path to the LLM-judgment template, or `(none)`. |
| `@adapters` | Which bindings exist (CLI, a plugin skill, MCP, ...). |
| `@portability` | `L1a-generic` (portable core), `L1b-private` (private mechanism), `L2-config`. |
| `@forbidden` | Whether the engine enforces the forbidden-zones denylist. |
| `@audit` | Audit substrate: `none`, `git`, or a hash-chained `dream-log`. |
| `@status` | Lifecycle state. |
| `@doc` | The design/runbook for the capability. |

---

## Environment configuration

Engines are config-free by design - they read their target and options from the environment, so the
same binary works against any vault or memory store. Provide your own values (an example config file
ships with the repo; the harness ships schemas and examples only, never real config or content).

| Variable | Read by | Meaning |
|---|---|---|
| `VAULT_ROOT` | the vault engines | Path to your notes vault (defaults to the current directory). |
| `VAULT_SCAN_EXCLUDE` | the vault engines | Comma-separated directory prefixes to skip while scanning. |
| `VAULT_REFAUDIT_EXCLUDE` | `ref-audit` | Comma-separated dirs the audit never walks (default: system/tool dirs only - attachment dirs ARE walked, to flag orphan media). |
| `VAULT_NORENAME_ZONES` | `name-reconcile` | Comma-separated folders to protect from rename (still scanned as link sources). |
| `VAULT_FORBIDDEN_ZONES` | the mutating engines | Optional. Comma-separated reldir prefixes the mutators skip writing entirely. Unset (default) = no skipping; the operator watching the run plus the git diff is the control. |
| `FRONTMATTER_SCHEMA` | the frontmatter engines | Path to your schema-as-code file. |
| `CLAUDE_MEMORY_DIR` | `memory-consolidate` | Path to the file-based memory store. |
| `VAULT_INBOX_DIR` | `memory-consolidate` | Optional - enables an inbox-pressure metric. |
| `HARNESS_ROOT` | `registry-generate` | Root to scan for metadata headers (defaults to the repo root). |

### Schema-as-code (the frontmatter engines)

The frontmatter lint and fix validate notes against a schema file you supply. The schema defines your
controlled axes - for example `note_type`, `status`, `maturity`, `horizon`, and `lang`, plus any
project-specific axes you add and their vocabularies and reconciliation maps. The **engine is
vault-agnostic**; all vocabulary lives in your schema, not in the code.
