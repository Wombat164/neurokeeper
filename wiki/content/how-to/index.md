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
> **git is the audit trail** - commit before, review the diff after.

---

## Reconcile vault tags

**Goal:** find morphological tag variants (case / plural / hyphen / underscore / slash forms of one
root) and converge them on a single canonical spelling.

1. Point the engine at your vault and run it read-only to see the proposed merge groups:
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   neurokeeper tag-reconcile            # proposal only - writes nothing
   neurokeeper tag-reconcile --json     # same proposal, machine-readable
   ```
2. Review the groups. The engine **detects and proposes**; it does not decide for you. Genuine synonyms
   (two different words meaning the same thing) are intentionally out of scope - supply those yourself.
3. **Apply** the merge. Prefer your notes app's own tag-rename tool for the write - it uses the app's
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
   drifted from the one-line-per-entry telegraphic style. It never blocks (exit 0) - a nudge, not a gate.
2. Read the proposal. Every number is computed from the real filesystem, so it is reproducible and
   cannot be fabricated - this is the whole point of pushing the counting into an engine.
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
3. Reconcile (mutating) - dry-run first, then apply with your notes app closed:
   ```bash
   neurokeeper frontmatter-fix             # dry-run - writes nothing
   neurokeeper frontmatter-fix --apply     # apply (close your notes app first)
   ```
4. Review `git diff`, then commit. The commit *is* the audit record.

> [!tip] If you skip the schema, the engine tells you
> If `FRONTMATTER_SCHEMA` is unset and no schema is found, the frontmatter engines print a one-line
> message explaining how to set it (and fall back to the bundled example where one is locatable),
> instead of failing with a traceback.

---

## Ask whether the vault already covers something

**Goal:** given an incoming item (a mail, a ticket, a transcript), find out whether a note about it
already exists, and get the evidence for that answer. Read-only.

1. Reduce the item to an envelope and pipe it in. Only `title` really matters; the rest sharpens it:
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   echo '{"id":"1","title":"Re: Widget Programme timeline",
          "participants":["ada.lovelace@example.org"],"codes":["PROJ-1"]}' \
     | neurokeeper correlate --stats
   ```
2. Read the `state` and the `evidence`, not just the score:
   - `anchored` - the vault covers this; the top candidate is the note.
   - `correlated` - right neighbourhood; use the candidate list.
   - `weak` - it scored, but on nothing individually convincing. Go and look yourself.
   - `ambiguous` - two candidates point at genuinely different subjects. This is the one worth a
     human or a model look.
   - `topic-known` - a code matched but no note reached the bar.
   - `new` - nothing. Treat as "look at this", not proof of absence.
3. Batch it. Pass a JSON *list* to score a whole backlog in one call; the note index is built once
   and cached, so a second run over the same vault reparses only what changed:
   ```bash
   neurokeeper correlate --item-file backlog.json --top 3 > verdicts.json
   ```
4. Point it at a non-Obsidian vault by mapping the frontmatter keys in a config file:
   ```yaml
   vault:
     include: ["02 - Projects", "MOC"]
     frontmatter_map:
       aliases: [alias]        # Logseq
       codes:   [project, ref]
   ```
   ```bash
   neurokeeper correlate --config vault.yaml --item-file backlog.json
   ```

---

## Enforce your identifiers as documents are written

**Goal:** stop new contradictions entering the collection, without being nagged about the ones
already there.

The whole-collection report (`neurokeeper register-lint`) never blocks, on purpose. Point a new
register at a mature collection and it finds hundreds of things nobody present did; a reader ignores
all of them to reach the one that is theirs, and then stops reading. `--guard` is the half that
enforces, and it only enforces what your edit introduced.

1. Run it against one document, as an author-time check:
   ```bash
   export IDENTIFIER_REGISTER="/path/to/your-register.yaml"
   neurokeeper register-lint --guard "02 - Projects/migration-plan.md"
   ```
   A clean edit prints nothing and exits 0. An edit that touches an existing bad line is still your
   edit, so it blocks; an edit elsewhere in that same document does not.
2. Wire it as a pre-commit hook (exit 1 blocks the commit):
   ```yaml
   - repo: local
     hooks:
       - id: register-guard
         name: identifiers conform to the register
         entry: neurokeeper register-lint --guard
         language: system
         files: \.md$
   ```
3. Or as a Claude Code `PostToolUse` hook, which needs exit **2** to block and feed the message back:
   ```bash
   neurokeeper register-lint --guard "$FILE" --hook
   ```
4. To see the backlog you are not being blocked on, add `--verbose`, or run the whole-collection
   report scoped to your change:
   ```bash
   neurokeeper register-lint --staged        # findings in the commit; the rest counted, not listed
   ```

> [!warning] It will not block on an entry it only inferred
> Provenance limits enforcement (ADR-0005). A register entry marked `inferred` reports as advisory
> and never blocks: stopping someone's work over a guess the tool made about their own vocabulary
> is how the tool loses the argument about whether it should exist at all.

---

## Find notes that should link to the one you just wrote

**Goal:** after authoring or heavily editing a note, find the *existing* notes on the same subject
that it is not connected to. Read-only; it proposes links and never writes one.

`ref-audit` tells you your links resolve. It cannot tell you about the note you did not know was
there. That gap is invisible to every structural check: nothing is broken, nothing is orphaned, and
the collection holds two unconnected halves of one subject.

1. Ask about a specific note:
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   neurokeeper semantic-gaps --note "02 - Projects/migration-plan.md"
   ```
2. Or ask about everything you touched, which is the usual case at the end of a session:
   ```bash
   neurokeeper semantic-gaps --since HEAD~1          # or --since main
   neurokeeper semantic-gaps --since HEAD~1 --json   # for an agent to consume
   ```
3. **Read the evidence, not the score.** Each candidate carries why it matched - a shared code, a
   title appearing verbatim, rare tokens in common. A high score with thin evidence is exactly the
   case you should reject.
4. Accept the ones that are genuinely related and write those links yourself. Notes already linked
   in either direction are excluded, so what you see is the remainder.

> [!note] Why it will not fail your build
> It always exits 0 and is not part of `doctor`. Every output is a judgment call, and a suggestion
> engine that can fail a gate is one whose gate gets switched off.

---

## Adopt on an existing collection

Adoption on a clean collection is easy and nobody has one. On a real collection, years old, the
first run reports a number that looks like a verdict on you. Measured on a generated 120-note
collection with realistic decay: **257 findings**, none of which the person running it caused.

The reflex at that point is to close the terminal, and the tool has lost a user over its own
honesty. This is the sequence that avoids that.

**1. Run it once, and expect a large number.**

```sh
neurokeeper ref-audit --check
# ref-audit OK: 0 broken canvas/base refs (120 notes; 28 unresolved links, orphans 97, dead-ends 75)
```

Read it as an inventory of inherited debt, not as a to-do list. Nothing here needs fixing today.

**2. Baseline it.** Everything that exists right now becomes the accepted starting point.

```sh
neurokeeper ref-audit --write-baseline .nk-baseline.json
# ref-audit: wrote 255 accepted findings to baseline
```

Commit that file. It is a record of what the collection looked like on the day you adopted the tool,
and it is the thing that makes the next step quiet.

**3. Gate on net-new only.** From here the check reports what you introduce, and says nothing about
the backlog.

```sh
neurokeeper ref-audit --baseline .nk-baseline.json --check
#     adoption: 2 new, 255 baselined, 0 resolved
```

That line is the whole posture: the past is not billed to you, and the present cannot get worse. Use
`--staged` instead of, or with, the baseline if you want the same behaviour scoped to the commit in
hand rather than to a file.

**4. Clear the backlog opportunistically.** Fix what you touch, when you touch it. Nothing forces a
bulk cleanup, and a bulk cleanup is usually the wrong shape anyway: hundreds of small edits in one
commit are unreviewable.

**5. Re-baseline occasionally and watch it shrink.**

```sh
neurokeeper ref-audit --baseline .nk-baseline.json
#     adoption: 0 new, 255 baselined, 12 resolved
```

`12 resolved` means twelve baselined findings no longer exist. Rewrite the baseline to bank that
progress, and the accepted count drops. The number going down is the only progress metric here that
is not self-reported.

**A note on what the baseline is not.** It is not a suppression file and not a permanent exemption.
Everything in it stays visible in an unscoped run, which is deliberate: a scoped report that hid the
backlog entirely would read as a clean collection and ambush the next person.

## Audit vault references

**Goal:** find broken links, orphans, dead-ends, broken `.canvas`/`.base` references, and orphan media.
Read-only - nothing is changed.

1. Point it at your vault and run it:
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   neurokeeper ref-audit            # human report
   neurokeeper ref-audit --json     # machine-readable
   ```
2. Read the report. **Unresolved wikilinks are informational** - in Obsidian a `[[link]]` to a
   not-yet-created note is a legitimate forward-reference. Only broken `.canvas`/`.base` refs (a board or
   base pointing at a deleted file) fail `--check`; orphans, dead-ends, and orphan media are surfaced for
   review but not gated.
3. Gate it in CI or a pre-commit hook:
   ```bash
   neurokeeper ref-audit --check            # exit 1 only on broken canvas/base refs
   neurokeeper ref-audit --check --strict   # also fail on unresolved links (for strict vaults)
   neurokeeper ref-audit --check --since origin/main   # only fail on defects in notes changed vs main
   ```
   `--since <git-ref>` scopes the reported findings (and the `--check` gate) to notes changed since the
   ref, so a PR is judged on the debt it introduces, not the vault's whole backlog. The scan stays
   graph-global; a bad ref or non-git tree exits 2 rather than silently scanning the wrong scope.
4. Adopt on an already-dirty vault without a wall of failures: baseline the current debt once, then
   gate on net-new only.
   ```bash
   neurokeeper ref-audit --write-baseline .neurokeeper-baseline   # accept today's findings, once
   neurokeeper ref-audit --check --baseline .neurokeeper-baseline # CI fails only on NEW debt
   ```
   Commit the baseline file. The run tells you how many baselined findings you have since fixed, so
   you can re-run `--write-baseline` to shrink it, rather than letting it become permanent debt.
5. Surface findings in GitHub's Security tab (code-scanning) via SARIF:
   ```yaml
   - run: neurokeeper ref-audit --sarif --since origin/main > ref-audit.sarif
   - uses: github/codeql-action/upload-sarif@v3
     with: { sarif_file: ref-audit.sarif }
   ```
   `--sarif` renders through the Findings IR, so the same findings can later drive JUnit or a Bases view
   without touching the engines. It composes with `--since` / `--baseline` (the SARIF reflects the
   scoped set).

## Run one aggregate health check (`doctor`)

**Goal:** one command + one honest exit code over all the read-only checks - the thing to wire into CI.

1. Run it (read-only):
   ```bash
   export VAULT_ROOT="/path/to/your/notes"
   neurokeeper doctor            # consolidated report
   neurokeeper doctor --json     # machine-readable
   ```
2. Read the tri-state. Each engine is `ok`, `fail`, or `skipped`. **`skipped` means its config is not set**
   (e.g. no `FRONTMATTER_SCHEMA`, no `CLAUDE_MEMORY_DIR`) - it is *not* counted as a pass. The roll-up exit
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

**Goal:** fail a commit / PR when the vault has real reference defects - composing neurokeeper with the
existing markdown ecosystem instead of duplicating it.

1. **pre-commit** - in your vault repo's `.pre-commit-config.yaml`:
   ```yaml
   repos:
     - repo: https://github.com/Wombat164/neurokeeper
       rev: v0.9.0
       hooks: [{ id: neurokeeper-doctor }]   # or: neurokeeper-ref-audit
   ```
   pre-commit installs the package in an isolated venv and runs the CLI against the repo root.
2. **GitHub Action** - compose the commoditized checks (style, external links) with the vault-graph-aware
   gate neurokeeper uniquely provides:
   ```yaml
   - uses: actions/checkout@v4
   - uses: DavidAnson/markdownlint-cli2-action@v16    # markdown style (not neurokeeper's job)
   - uses: lycheeverse/lychee-action@v2               # external link existence (not neurokeeper's job)
   - uses: Wombat164/neurokeeper@v0.9.0            # broken wikilinks/.canvas/.base, orphans, health
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
cost ~nothing - without changing your default `claude`.

1. Stand up an endpoint that speaks the Anthropic `/v1/messages` API (vLLM-native, or a LiteLLM /
   claude-code-router gateway in front of an OpenAI-only model). Serving recipes are in the in-repo
   `docs/two-lane-model-handoff.md`.
2. Configure the cheap lane (copy the example; never commit a real internal endpoint):
   ```bash
   cp config.example/cheap-lane.env.example ~/.config/neurokeeper/cheap-lane.env   # then edit
   # CLAUDE_CHEAP_BASE_URL=http://your-host:8000  |  CLAUDE_CHEAP_MODEL=...  |  CLAUDE_CHEAP_TOKEN=local
   ```
3. Run cheap work through the wrapper - it sets `ANTHROPIC_BASE_URL` to your endpoint **for that
   invocation only**:
   ```bash
   claude-cheap -p "write a conventional-commit message for the staged diff"
   ```

> [!warning] Two warnings that matter
> **Billing:** pointing at a *paid* Anthropic-compatible gateway with a credential moves you off your
> subscription onto per-token billing - the point here is that traffic goes to *your* box (~zero marginal
> cost). **Data egress:** everything in this lane goes to your endpoint - keep it on a host you control
> for sensitive content; never send regulated data or private model weights to a cloud you don't control.

---

## Add a new engine

**Goal:** add a new portable capability that the registry will pick up automatically.

> [!tip] First decide whether it belongs here at all
> This recipe is for an engine that goes **into the core**, which means it must be useful to people
> whose collections look nothing like yours. If it encodes your vocabulary, your org's fields, or
> your team's policy, it belongs in **your** repository instead, and it can still be a first-class
> `neurokeeper` command: see [[how-to/extend-with-your-own-engine|Extend with your own engine]].
> The decision test is there too. Getting this wrong in the upstream direction is the expensive
> one: a domain-specific check in a portable core is carried by every user forever.

1. **Write the engine first.** A single deterministic script that computes facts/candidates (or applies
   a deterministic transform). Make it speak the contract: a `--json` flag and meaningful exit codes,
   and **report-by-default** (no writes unless `--apply`).
2. **Classify it** on two axes - *compute* (`deterministic` / `llm` / `hybrid`) and *effect*
   (`read-only` / `mutating`). That decides which layers you need; see
   [[explanation/index|the capability typology]].
3. **If it mutates:** wire in the forbidden-zones check, an operator confirmation (per-row diff for
   multi-item changes), the audit write, a post-write verify, and any substrate preflight guard.
4. **Add the metadata header** at the top of the script (the `@capability` / `@compute` / `@effect` /
   ... block - see the [Reference: metadata-header spec](../reference/)). This is what makes the engine
   discoverable.
5. **Regenerate the registry** so the catalog reflects the new engine:
   ```bash
   neurokeeper registry-generate            # preview
   neurokeeper registry-generate --write     # write the registry doc
   ```
6. **Document it in the docs site.** Any user-facing capability must land in the wiki, not just the
   README - add a [Reference](../reference/) catalog entry and a How-to recipe. Docs that lag the tool
   are worse than no docs.
7. **Add a test/fixture.** An engine without a test is experimental until it has one.
8. **Add the adapter you use now** (e.g. a Claude Code skill that defers all logic to the engine). Add
   an MCP binding only if a graduation trigger fires - see [[explanation/index|the MCP ladder]].

---

## Make an engine cross-platform

**Goal:** ensure a new engine runs on Windows / MSYS as well as POSIX.

- **Force UTF-8 on subprocess text:** pass `encoding="utf-8", errors="replace"` to `subprocess.run` --
  the OS default codepage will choke on non-ASCII bytes in command output.
- **Never pass leading-slash paths to git/MSYS tools:** MSYS rewrites `/foo` into a Windows path. Use
  bare/relative paths.
- **File I/O:** always `open(..., encoding="utf-8")`; write with `newline=""` to preserve the file's
  existing line endings instead of reflowing them.
