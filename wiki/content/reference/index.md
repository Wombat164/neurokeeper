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

- **CLI name** -- the dispatcher subcommand: `claude-harness <name> [args]`.
- **compute x effect** -- the [[explanation/index|capability typology]]: *compute* is
  `deterministic` / `llm` / `hybrid`; *effect* is `read-only` / `mutating`.
- **Universal contract** -- every engine supports `--json` (machine-readable output) and meaningful
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

### `frontmatter-lint`
- **compute x effect:** deterministic x read-only
- **What it does:** validates notes against your schema-as-code -- flags off-vocabulary values, missing
  recommended axes, redundant date fields, and unknown fields. Advisory (reports; does not block).
- **Contract:** `--json`, `--terse`, `--check`, `--schema <path>`, `--vault <path>`.
- **Env:** `VAULT_ROOT`, `FRONTMATTER_SCHEMA`, `VAULT_SCAN_EXCLUDE`.

### `frontmatter-fix`
- **compute x effect:** deterministic x **mutating**
- **What it does:** applies the schema's reconciliation maps (e.g. normalising status / maturity /
  horizon values) by **surgical line-edits** on the frontmatter block, preserving formatting and field
  order (no YAML reparse).
- **Contract:** `--apply`, `--force`, `--json` (report-only without `--apply`).
- **Audit:** git. **Forbidden-zones:** attended by default; optional `VAULT_FORBIDDEN_ZONES` skip.
- **Env:** `VAULT_ROOT`, `FRONTMATTER_SCHEMA`, `VAULT_FORBIDDEN_ZONES`.

### `set-note-type`
- **compute x effect:** deterministic x **mutating**
- **What it does:** additively sets a `note_type` frontmatter field derived from a folder-to-type map.
  Additive and idempotent -- inserts one line, never rewrites content, skips notes that already have it.
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
  separators, keep case) vs the default `kebab` mode (full lowercase-hyphen slug).
- **Audit:** git. **Forbidden-zones:** rename-protected via `VAULT_NORENAME_ZONES`; optional
  `VAULT_FORBIDDEN_ZONES` skip (never writes those files).
- **Env:** `VAULT_ROOT`, `VAULT_NORENAME_ZONES`, `VAULT_FORBIDDEN_ZONES`.

### `memory-consolidate`
- **compute x effect:** the engine is deterministic x read-only; the full **memory-audit** capability is
  hybrid x mutating (engine + judgment + gate + audit via an adapter).
- **What it does:** the deterministic analyzer behind the memory-audit -- computes a multi-metric health
  score, an importance/decay curve, and orphan / broken-link / stale / dead-end detection over a
  file-based memory store, then emits a consolidation proposal. Read-only: it proposes, never writes.
- **Contract:** `--json`, `--check`, `--terse`, `--today YYYY-MM-DD`.
- **Audit (capability):** append-only, hash-chained log (not git -- see [[explanation/index]]).
- **Env:** `CLAUDE_MEMORY_DIR`, optional `VAULT_INBOX_DIR`, `VAULT_ROOT`.

### `registry-generate`
- **compute x effect:** deterministic x read-only
- **What it does:** scans the harness for per-engine metadata headers and emits the capability registry.
  Anti-rot by construction -- the catalog is generated from the source-of-truth headers, never
  hand-maintained. Engines without a header are listed as the classification backlog.
- **Contract:** `--json`, `--write` (writes the registry doc; prints to stdout otherwise).
- **Env:** `HARNESS_ROOT` (defaults to the repo root).

> [!info] Shared internals (not dispatcher subcommands)
> Two helper modules are imported by the engines rather than run directly: a **shared library**
> (vault walk, frontmatter split, slug helpers -- one definition, imported everywhere) and a
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

Engines are config-free by design -- they read their target and options from the environment, so the
same binary works against any vault or memory store. Provide your own values (an example config file
ships with the repo; the harness ships schemas and examples only, never real config or content).

| Variable | Read by | Meaning |
|---|---|---|
| `VAULT_ROOT` | the vault engines | Path to your notes vault (defaults to the current directory). |
| `VAULT_SCAN_EXCLUDE` | the vault engines | Comma-separated directory prefixes to skip while scanning. |
| `VAULT_NORENAME_ZONES` | `name-reconcile` | Comma-separated folders to protect from rename (still scanned as link sources). |
| `VAULT_FORBIDDEN_ZONES` | the mutating engines | Optional. Comma-separated reldir prefixes the mutators skip writing entirely. Unset (default) = no skipping; the operator watching the run plus the git diff is the control. |
| `FRONTMATTER_SCHEMA` | the frontmatter engines | Path to your schema-as-code file. |
| `CLAUDE_MEMORY_DIR` | `memory-consolidate` | Path to the file-based memory store. |
| `VAULT_INBOX_DIR` | `memory-consolidate` | Optional -- enables an inbox-pressure metric. |
| `HARNESS_ROOT` | `registry-generate` | Root to scan for metadata headers (defaults to the repo root). |

### Schema-as-code (the frontmatter engines)

The frontmatter lint and fix validate notes against a schema file you supply. The schema defines your
controlled axes -- for example `note_type`, `status`, `maturity`, `horizon`, and `lang`, plus any
project-specific axes you add and their vocabularies and reconciliation maps. The **engine is
vault-agnostic**; all vocabulary lives in your schema, not in the code.
