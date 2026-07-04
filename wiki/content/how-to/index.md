---
title: How-to guides
description: Task-oriented recipes for getting specific jobs done with neurokeeper.
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
   neurokeeper tag-reconcile            # proposal only -- writes nothing
   neurokeeper tag-reconcile --json     # same proposal, machine-readable
   ```
2. Review the groups. The engine **detects and proposes**; it does not decide for you. Genuine synonyms
   (two different words meaning the same thing) are intentionally out of scope -- supply those yourself.
3. **Apply** the merge. Prefer your notes app's own tag-rename tool for the write -- it uses the app's
   parser, updates every usage (including nested tags), and avoids the linter race. The engine's
   `--apply` is a guarded fallback for bulk runs:
   ```bash
   # close your notes app first, then:
   neurokeeper tag-reconcile --apply
   ```
4. Review `git diff`, then commit. The commit *is* the audit record.

---

## Run the memory-audit

**Goal:** get a health report on a file-based memory store (orphans, broken links, staleness, a
multi-metric score) and an evidence-backed consolidation proposal.

1. Tell the engine where the memory store lives, then run the deterministic analyzer (read-only):
   ```bash
   export CLAUDE_MEMORY_DIR="~/.claude/memory"
   neurokeeper memory-consolidate            # human-readable report
   neurokeeper memory-consolidate --json     # machine-readable
   neurokeeper memory-consolidate --terse    # one-line health summary (good for a session hook)
   neurokeeper memory-consolidate --lint     # advisory: is the always-loaded index within its cap + tight?
   ```
   `--lint` is the check to wire into a session-start hook or pre-commit for the *index* file itself:
   it flags an index that has grown past the harness read cap (so the tail is silently dropped) or
   drifted from the one-line-per-entry telegraphic style. It never blocks (exit 0) -- a nudge, not a gate.
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
   neurokeeper frontmatter-lint            # human report
   neurokeeper frontmatter-lint --json     # machine-readable
   ```
3. Reconcile (mutating) -- dry-run first, then apply with your notes app closed:
   ```bash
   neurokeeper frontmatter-fix             # dry-run -- writes nothing
   neurokeeper frontmatter-fix --apply     # apply (close your notes app first)
   ```
4. Review `git diff`, then commit. The commit *is* the audit record.

> [!tip] If you skip the schema, the engine tells you
> If `FRONTMATTER_SCHEMA` is unset and no schema is found, the frontmatter engines print a one-line
> message explaining how to set it (and fall back to the bundled example where one is locatable),
> instead of failing with a traceback.

---

## Audit vault references

**Goal:** find broken links, orphans, dead-ends, broken `.canvas`/`.base` references, and orphan media.
Read-only -- nothing is changed.

1. Point it at your vault and run it:
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   neurokeeper ref-audit            # human report
   neurokeeper ref-audit --json     # machine-readable
   ```
2. Read the report. **Unresolved wikilinks are informational** -- in Obsidian a `[[link]]` to a
   not-yet-created note is a legitimate forward-reference. Only broken `.canvas`/`.base` refs (a board or
   base pointing at a deleted file) fail `--check`; orphans, dead-ends, and orphan media are surfaced for
   review but not gated.
3. Gate it in CI or a pre-commit hook:
   ```bash
   neurokeeper ref-audit --check            # exit 1 only on broken canvas/base refs
   neurokeeper ref-audit --check --strict   # also fail on unresolved links (for strict vaults)
   ```

---

## Run one aggregate health check (`doctor`)

**Goal:** one command + one honest exit code over all the read-only checks -- the thing to wire into CI.

1. Run it (read-only):
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   neurokeeper doctor            # consolidated report
   neurokeeper doctor --json     # machine-readable
   ```
2. Read the tri-state. Each engine is `ok`, `fail`, or `skipped`. **`skipped` means its config is not set**
   (e.g. no `FRONTMATTER_SCHEMA`, no `CLAUDE_MEMORY_DIR`) -- it is *not* counted as a pass. The roll-up exit
   asserts *"an engine errored or a real gate failed,"* not *"the vault is healthy"*: advisory checks
   (taxonomy-inventory, frontmatter-lint) contribute numbers but cannot fail it.
3. Gate CI on it:
   ```bash
   neurokeeper doctor --check            # exit 1 iff a gating engine failed or any engine errored
   neurokeeper doctor --check --strict   # also fail on unresolved links (forwarded to ref-audit)
   ```
   Set `FRONTMATTER_SCHEMA` / `CLAUDE_MEMORY_DIR` to bring those engines into the gate; leave them unset to skip.

---

## Gate a vault repo in CI (pre-commit + GitHub Action)

**Goal:** fail a commit / PR when the vault has real reference defects -- composing neurokeeper with the
existing markdown ecosystem instead of duplicating it.

1. **pre-commit** -- in your vault repo's `.pre-commit-config.yaml`:
   ```yaml
   repos:
     - repo: https://github.com/Wombat164/neurokeeper
       rev: v0.3.2
       hooks: [{ id: neurokeeper-doctor }]   # or: neurokeeper-ref-audit
   ```
   pre-commit installs the package in an isolated venv and runs the CLI against the repo root.
2. **GitHub Action** -- compose the commoditized checks (style, external links) with the vault-graph-aware
   gate neurokeeper uniquely provides:
   ```yaml
   - uses: actions/checkout@v4
   - uses: DavidAnson/markdownlint-cli2-action@v16    # markdown style (not neurokeeper's job)
   - uses: lycheeverse/lychee-action@v2               # external link existence (not neurokeeper's job)
   - uses: Wombat164/neurokeeper@v0.3.2            # broken wikilinks/.canvas/.base, orphans, health
     with: { vault-path: ".", engine: "doctor", strict: "false" }
   ```
3. Understand what fails it. The exit code follows the doctor contract: broken `.canvas`/`.base` refs or an
   engine error fail it; advisory findings and *skipped* (unconfigured) engines do not. Set
   `frontmatter-schema` / `memory-dir` inputs to widen the gate. Full guide: `docs/ci-adapters.md`.

> [!tip] Try it on the bundled example vault
> `examples/vault/` is a tiny synthetic vault; `VAULT_ROOT=examples/vault neurokeeper doctor` shows a
> clean run (and is the fixture the project's own CI smoke-tests).

---

## Offload cheap work to a self-hosted model (two lanes)

**Goal:** keep hard agentic work on your normal Claude lane, but route mechanical, high-volume turns
(commit messages, summaries, extraction, classification, formatting) to a self-hosted open model so they
cost ~nothing -- without changing your default `claude`.

1. Stand up an endpoint that speaks the Anthropic `/v1/messages` API (vLLM-native, or a LiteLLM /
   claude-code-router gateway in front of an OpenAI-only model). Serving recipes are in the in-repo
   `docs/two-lane-model-handoff.md`.
2. Configure the cheap lane (copy the example; never commit a real internal endpoint):
   ```bash
   cp config.example/cheap-lane.env.example ~/.config/neurokeeper/cheap-lane.env   # then edit
   # CLAUDE_CHEAP_BASE_URL=http://your-host:8000  |  CLAUDE_CHEAP_MODEL=...  |  CLAUDE_CHEAP_TOKEN=local
   ```
3. Run cheap work through the wrapper -- it sets `ANTHROPIC_BASE_URL` to your endpoint **for that
   invocation only**:
   ```bash
   claude-cheap -p "write a conventional-commit message for the staged diff"
   ```

> [!warning] Two warnings that matter
> **Billing:** pointing at a *paid* Anthropic-compatible gateway with a credential moves you off your
> subscription onto per-token billing -- the point here is that traffic goes to *your* box (~zero marginal
> cost). **Data egress:** everything in this lane goes to your endpoint -- keep it on a host you control
> for sensitive content; never send regulated data or private model weights to a cloud you don't control.

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
   neurokeeper registry-generate            # preview
   neurokeeper registry-generate --write     # write the registry doc
   ```
6. **Document it in the docs site.** Any user-facing capability must land in the wiki, not just the
   README -- add a [Reference](../reference/) catalog entry and a How-to recipe. Docs that lag the tool
   are worse than no docs.
7. **Add a test/fixture.** An engine without a test is experimental until it has one.
8. **Add the adapter you use now** (e.g. a Claude Code skill that defers all logic to the engine). Add
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
