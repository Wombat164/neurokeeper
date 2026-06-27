---
title: How-to guides
description: Task-oriented recipes for getting specific jobs done with claude-harness.
tags:
  - how-to
---

> [!note] These are how-to guides (task-oriented)
> Each recipe assumes you already installed the tool (see the [[tutorials/index|getting-started
> tutorial]]) and gets you to one concrete outcome. For exhaustive flags and contracts, see
> [Reference](../reference/); for the *why*, see [Explanation](../explanation/).

A quick safety model that applies to every recipe below:

> [!warning] Report by default; mutate only on `--apply`
> Mutating engines do nothing destructive until you pass `--apply`. Bulk vault writes additionally
> **refuse to run while your notes app is open** (a linter running in the app can mangle frontmatter
> mid-write). Close the app first, or pass `--force` to override deliberately. For mutating engines,
> **git is the audit trail** -- commit before, review the diff after.

---

## Reconcile vault tags

**Goal:** find morphological tag variants (case / plural / hyphen / underscore / slash forms of one
root) and converge them on a single canonical spelling.

1. Point the engine at your vault and run it read-only to see the proposed merge groups:
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   claude-harness tag-reconcile            # proposal only -- writes nothing
   claude-harness tag-reconcile --json     # same proposal, machine-readable
   ```
2. Review the groups. The engine **detects and proposes**; it does not decide for you. Genuine synonyms
   (two different words meaning the same thing) are intentionally out of scope -- supply those yourself.
3. **Apply** the merge. Prefer your notes app's own tag-rename tool for the write -- it uses the app's
   parser, updates every usage (including nested tags), and avoids the linter race. The engine's
   `--apply` is a guarded fallback for bulk runs:
   ```bash
   # close your notes app first, then:
   claude-harness tag-reconcile --apply
   ```
4. Review `git diff`, then commit. The commit *is* the audit record.

---

## Run the memory-audit

**Goal:** get a health report on a file-based memory store (orphans, broken links, staleness, a
multi-metric score) and an evidence-backed consolidation proposal.

1. Tell the engine where the memory store lives, then run the deterministic analyzer (read-only):
   ```bash
   export CLAUDE_MEMORY_DIR="~/.claude/memory"
   claude-harness memory-consolidate            # human-readable report
   claude-harness memory-consolidate --json     # machine-readable
   claude-harness memory-consolidate --terse    # one-line health summary (good for a session hook)
   ```
2. Read the proposal. Every number is computed from the real filesystem, so it is reproducible and
   cannot be fabricated -- this is the whole point of pushing the counting into an engine.
3. To act on it with judgment + confirmation, use the **memory-audit** capability through an adapter
   (for example the Claude Code skill). The adapter runs this same engine, then applies the
   consolidation prompt, gates each change, and writes an append-only audit entry.

> [!tip] Why a hash-chained audit for memory, but git for the vault?
> Different substrates get different audit trails. Markdown notes -> git (the diff is the record).
> A memory store consolidated by an agent -> an append-only, hash-chained log. See
> [[explanation/index|the explanation]] for the reasoning.

---

## Lint or reconcile frontmatter

**Goal:** validate your notes' frontmatter against your schema-as-code, then optionally reconcile
off-vocabulary values.

1. Point the engines at your vault **and** at a schema file. The frontmatter engines need a schema --
   copy the shipped example and edit it for your own vocabularies:
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   cp config.example/frontmatter-schema.example.yaml my-frontmatter-schema.yaml   # then edit
   export FRONTMATTER_SCHEMA="$PWD/my-frontmatter-schema.yaml"
   ```
   (Windows PowerShell: `$env:FRONTMATTER_SCHEMA = "C:\path\to\my-frontmatter-schema.yaml"`.)
2. Lint read-only to see off-vocab values, missing axes, and unknown fields:
   ```bash
   claude-harness frontmatter-lint            # human report
   claude-harness frontmatter-lint --json     # machine-readable
   ```
3. Reconcile (mutating) -- dry-run first, then apply with your notes app closed:
   ```bash
   claude-harness frontmatter-fix             # dry-run -- writes nothing
   claude-harness frontmatter-fix --apply     # apply (close your notes app first)
   ```
4. Review `git diff`, then commit. The commit *is* the audit record.

> [!tip] If you skip the schema, the engine tells you
> If `FRONTMATTER_SCHEMA` is unset and no schema is found, the frontmatter engines print a one-line
> message explaining how to set it (and fall back to the bundled example where one is locatable),
> instead of failing with a traceback.

---

## Add a new engine

**Goal:** add a new portable capability that the registry will pick up automatically.

1. **Write the engine first.** A single deterministic script that computes facts/candidates (or applies
   a deterministic transform). Make it speak the contract: a `--json` flag and meaningful exit codes,
   and **report-by-default** (no writes unless `--apply`).
2. **Classify it** on two axes -- *compute* (`deterministic` / `llm` / `hybrid`) and *effect*
   (`read-only` / `mutating`). That decides which layers you need; see
   [[explanation/index|the capability typology]].
3. **If it mutates:** wire in the forbidden-zones check, an operator confirmation (per-row diff for
   multi-item changes), the audit write, a post-write verify, and any substrate preflight guard.
4. **Add the metadata header** at the top of the script (the `@capability` / `@compute` / `@effect` /
   ... block -- see the [Reference: metadata-header spec](../reference/)). This is what makes the engine
   discoverable.
5. **Regenerate the registry** so the catalog reflects the new engine:
   ```bash
   claude-harness registry-generate            # preview
   claude-harness registry-generate --write     # write the registry doc
   ```
6. **Add a test/fixture.** An engine without a test is experimental until it has one.
7. **Add the adapter you use now** (e.g. a Claude Code skill that defers all logic to the engine). Add
   an MCP binding only if a graduation trigger fires -- see [[explanation/index|the MCP ladder]].

---

## Make an engine cross-platform

**Goal:** ensure a new engine runs on Windows / MSYS as well as POSIX.

- **Force UTF-8 on subprocess text:** pass `encoding="utf-8", errors="replace"` to `subprocess.run` --
  the OS default codepage will choke on non-ASCII bytes in command output.
- **Never pass leading-slash paths to git/MSYS tools:** MSYS rewrites `/foo` into a Windows path. Use
  bare/relative paths.
- **File I/O:** always `open(..., encoding="utf-8")`; write with `newline=""` to preserve the file's
  existing line endings instead of reflowing them.
