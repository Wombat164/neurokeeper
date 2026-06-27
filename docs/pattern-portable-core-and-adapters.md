# Harness Pattern: Portable Core + Adapters

The keystone architecture contract for every capability that acts on the vault or the harness.
Everything downstream (classification, registry, the harness repo, the taxonomy engines, the OSS handoff)
conforms to this. Prose avoids ` -- ` and em-dashes (operator pref).

Grounded in the Claude Code construct definitions (skill/script/Workflow/hook/MCP/subagent are the only
constructs -- there is no "pipeline" construct), the deterministic-engine lesson (never let the LLM state
a fact the engine did not produce), and the portability requirement (the harness must be usable by ANY
open-LLM harness, not just Claude Code).

---

## 1. The one idea: portable core + thin adapters

A capability is NOT a skill. A capability is a **portable core** that a thin, swappable **adapter** binds
to a specific harness. The core is harness-agnostic and is the real OSS asset; the adapter is disposable
glue.

```
PORTABLE CORE  (harness-agnostic; the OSS asset)
  engine    = deterministic script with a CLI + --json contract   -> runs anywhere (human/CI/any LLM)
  prompt    = plain-markdown prompt template                       -> any LLM
  contract  = the engine's versioned JSON/CLI interface            -> the seam
        |
        +-- adapter: Claude Code skill        (slash-command binding)
        +-- adapter: MCP server               (cross-harness / cross-machine / model-mid-reasoning)
        +-- adapter: plain CLI                 (human / CI / cron)
        +-- adapter: open-LLM harness          (Aider / Continue / local agent)
```

**Why:** portability (any harness), vendor-neutrality (no Claude-Code lock-in), OSS reuse (others bring
their own harness), and the token-saving open-LLM handoff (an adapter pointing the same core at a
self-hosted open model). "Skills are not portable" was the gap; this closes it.

Rule: **put all load-bearing logic in the engine + prompt; keep adapters thin.** If logic lives in the
skill markdown, it is locked to Claude Code. If it lives in the engine, it is portable.

---

## 2. The three core artifacts

| Artifact | What | Lives | Portable? |
|---|---|---|---|
| **engine** | deterministic script (Python/JS) that computes facts/candidates/validations or applies a deterministic transform; exposes `--json` + exit codes | `.claude/scripts/` (or harness repo) | yes (any caller) |
| **prompt** | markdown prompt template for the LLM-judgment step (if any); references the engine's output, never restates facts | `.claude/prompts/` | yes (any LLM) |
| **contract** | the engine's documented CLI flags + `--json` output schema, versioned | engine header + a schema file | yes (the seam) |

The engine **cannot hallucinate** (it is code). The prompt does only judgment the engine cannot
(decide/synthesize/classify/prose), bounded by the engine's output. The contract lets adapters and the
prompt depend on a stable interface (change the schema => bump the version => update consumers).

---

## 3. Capability typology (compute x effect)

Not every capability is the full 4-layer hybrid. Classify each on two axes; that decides which layers
apply.

- **compute:** `deterministic` (engine only) | `llm` (prompt only) | `hybrid` (engine feeds prompt)
- **effect:** `read-only` (produces a report/answer; mutates nothing) | `mutating` (writes vault/memory)

The **4-layer max-shape** is for `hybrid` + `mutating`:

```
1. engine        deterministic facts/candidates (--json)        [always, if compute != llm]
2. judgment      LLM decides on the engine's output             [if compute != deterministic]
3. gate          operator confirms mutations (per-row, diff)    [if effect == mutating]
4. apply+audit   deterministic write + append-only audit + verify [if effect == mutating]
```

Subsets:
- `deterministic + read-only` = engine only (e.g., `vault-health.js`, `vault-taxonomy-inventory.py`).
- `hybrid + read-only` = engine + judgment, no gate/audit (e.g., a report/proposal).
- `llm + *` = prompt + (gate/audit if mutating); no engine (e.g., a multi-persona review prompt).
- `* + mutating` = MUST have gate + audit (sections 5, 6).

---

## 4. Adapters and the MCP graduation ladder

The core is fixed; the **binding varies**. Default to on-box (script/CLI/skill). Add an MCP/API binding
only when a trigger fires. MCP is **not** a more-advanced skill; it is a different binding for a different
need, with real cost.

**Stay on-box (script + CLI + optional CC skill) when:** the capability is a local, fast, deterministic
transform; single consumer; no shared state; runs in milliseconds. (e.g. `memory-consolidate`, `gate.py`,
the frontmatter lint.) Wrapping these in MCP is pure overhead + attack surface.

**Graduate to an MCP/API binding when ANY of these triggers fire:**
1. **Shared live state / single source of truth** across multiple consumers (a DB, a CMDB).
2. **It is a service, not a transform** -- stateful, long-running, concurrent, needs auth/rate-limiting,
   or wraps an external system.
3. **Cross-machine / remote** -- must run elsewhere (a self-hosted GPU box) and be called from the
   workstation. (This is the OSS-model handoff: the self-hosted model as an MCP/OpenAI endpoint.)
4. **Cross-harness reuse via one standard** -- one MCP server callable by Claude Code AND other MCP
   clients, no per-harness adapter. (The portability multiplier.)
5. **Model-calls-it-mid-reasoning** -- the LLM must invoke it inline as a typed tool, not as a
   `/command`.

**The cost of MCP (why not by default):** a server to run (lifecycle + 502-when-down), auth, a network
hop, a schema contract, and an OPSEC surface (attack surface + a place sensitive data could egress).
For sensitive/regulated capabilities the OPSEC cost is load-bearing.

Because the core is fixed, graduating later is cheap: design the engine with a clean `--json` contract
NOW, add the MCP binding when a trigger fires. Never MCP-everything; never on-box-everything.

---

## 5. Audit substrates (two stores, two logs)

Mutating capabilities MUST audit. The substrate depends on WHAT is mutated:
- **Vault content** (`.md` notes) -> **git** is the audit trail. A clear commit (message + diff +
  preserved script) IS the audit. No dream-log.
- **Memory store** -> **dream-log** (hash-chained JSONL at `audit/dream-log.jsonl`), per the consolidation
  doctrine.
- **Harness substrate** (`.claude/`) -> git (the vault repo or the harness repo).

Read-only capabilities need no audit. Do not force vault mutations into dream-log (category error) or
memory mutations into bare git (loses the chain).

---

## 6. Mandated enforcement for mutating capabilities

Every `mutating` capability MUST, in the engine (not just in docs):
1. **Load `.claude/forbidden-zones.txt` and hard-stop** on any write whose path matches a forbidden
   prefix (even with operator confirmation), unless the zone is explicitly eligible.
2. **Operator-confirm** the mutation (per-row diff-preview for multi-item; single confirm for atomic).
3. **Write the audit** (section 5) on success.
4. **Verify** post-write (re-run the read-side check; e.g., `--check`).
5. **Preflight guards** relevant to the substrate -- e.g., for bulk VAULT writes, refuse if Obsidian is
   running (the 2026-06-27 linter-corruption lesson; the linter mangles frontmatter on live external
   writes).

---

## 7. Reproducibility + testing

- **Reproducibility:** the engine is reproducible by construction; the LLM-judgment step is not. Where an
  output must be reproducible (audit, compliance, counts), push that logic INTO the engine and keep the
  LLM to genuine judgment. Invariant: the LLM never states a number/filename the engine did not produce
  (the never-hallucinate guard).
- **Testing:** engines get fixtures + a test (e.g. a `tests/` dir with fixtures + a runner for the
  gitleaks rules). A capability without an engine test is experimental until it has one.

---

## 8. Homing (where each part lives) + the metadata header

| Part | Location | L-layer |
|---|---|---|
| generic engine + prompt + contract | harness repo / `.claude/scripts/` + `.claude/prompts/` | L1a portable-core (OSS) |
| a private-domain engine (e.g. a document renderer) | `.claude/` (private repo) | L1b private-mechanism |
| config the engine reads (registries, denylists, paths, personas) | `.claude/config/` | L2 config |
| vault notes, memory facts | vault + memory store | L3 content |
| CC adapter (skill) | `.claude/commands/` or `.claude/skills/` | L1a (or L1b if private-domain) |
| design/runbook | `.claude/docs/` | (doc) |
| audit | `audit/dream-log.jsonl` (memory) / git (vault) | (audit) |

**Memory holds a one-line POINTER to a capability, never its detail.** (Why MEMORY.md was tightened.)

**Per-capability metadata header** (machine-parseable; the registry harvests it; put it at the top of the
engine script):

```
# @capability:   memory-audit
# @compute:      hybrid            # deterministic | llm | hybrid
# @effect:       mutating          # read-only | mutating
# @engine:       .claude/scripts/memory-consolidate.py
# @prompt:       .claude/prompts/memory-audit.md
# @adapters:     skill:vault-memory-audit
# @portability:  L1a-generic       # L1a-generic | L1b-private | L2-config
# @forbidden:    enforced          # n/a | enforced
# @audit:        dream-log         # none | git | dream-log
# @status:       active            # active | experimental | deprecated
# @doc:          .claude/docs/...
```

---

## 9. Terminology (use the real constructs; "pipeline" is informal)

Claude Code has: **skill** (capability/slash-command), **script** (the engine), **Workflow** (the
deterministic multi-agent orchestration tool), **hook** (settings.json event command), **MCP tool**
(external bridge), **subagent** (Agent tool). There is NO "pipeline" construct. Say "the `/x` skill backed
by `engine.py`", or "skill with Workflow" for fan-out. Reserve "pipeline" for informal description only.

Use the **Workflow tool** (not a skill calling a plain script) when you need deterministic multi-agent
fan-out (N subagents in parallel/sequence) whose intermediate results should stay out of the main context.
Use a **skill calling a script** when one engine + one judgment + a gate suffices.

---

## 10. Worked example: `/vault-memory-audit`

- **engine:** `memory-consolidate.py` (deterministic: 5-metric score, orphans, importance, `--check`,
  `--terse`, `--json`). Portable: any caller runs it.
- **prompt:** `prompts/memory-audit.md`, the consolidation-judgment template.
- **contract:** `--json` schema + `--check` exit codes; the skill spec mandates "never state a count the
  engine did not produce".
- **adapter:** the `/vault-memory-audit` CC skill (thin: invokes the engine, applies judgment, gates
  per-row, writes dream-log).
- **typology:** hybrid + mutating -> full 4-layer. **audit:** dream-log (memory store).
- This is the reference shape every other capability copies (Phase 2 proof).

---

## 11. Checklist: building a new capability

1. Write the **engine** first (deterministic, `--json`, exit codes). Can it run with no LLM? Push logic in.
2. Classify **compute x effect** -> which layers apply.
3. If LLM-judgment: write a **prompt template** (references engine output; restates no facts).
4. If mutating: wire **forbidden-zones + gate + audit + verify + preflight guards**.
5. Add the **metadata header** (section 8) so the registry picks it up.
6. Add the **adapter** for the harness you use now (CC skill). Add MCP only if a section-4 trigger fires.
7. Add an **engine test/fixture**.
8. Add a **one-line pointer** in MEMORY.md (detail stays in the engine + this-class doc).

## 12. Cross-platform notes (Windows / MSYS gotchas)

Engines + adapters must run on Git-for-Windows / MSYS, not just POSIX. Two gotchas (both hit 2026-06-27):
- **Force UTF-8 on subprocess text.** `subprocess.run(..., text=True)` decodes with the OS locale
  codepage (cp1252 on Windows), which fails on UTF-8 bytes (em-dashes, accents) in git/CLI output ->
  garbled output or `None`. Always pass `encoding="utf-8", errors="replace"`.
- **Never pass leading-slash paths to git/MSYS tools.** MSYS rewrites a leading-slash argument
  (`/foo.md`) into a Windows path (`C:/Program Files/Git/foo.md`) -- POSIX-path conversion that silently
  corrupts e.g. `git sparse-checkout set`. Use bare/relative paths (`git sparse-checkout set foo.md`, not
  `/foo.md`); use `MSYS_NO_PATHCONV=1` only as a last resort.
- File reads/writes: always `open(..., encoding="utf-8")`; write with `newline=""` to preserve a file's
  existing CRLF/LF rather than reflowing every line.

## 13. OSS attribution (when borrowing or recommending)

This harness is publish-destined, so attribution is both good citizenship and a legal precondition.
Whenever a capability **borrows from**, **wraps**, or **recommends** an OSS project:
- Cite it where it appears: **name + author/org + licence + repo URL**, in BOTH the code comment and the
  doc/schema line (e.g. `Tag Wrangler -- pjeby, MIT -- https://github.com/pjeby/tag-wrangler`).
- Keep a single **`docs/SOURCES.md`** (or a Sources section in the wiki) listing every external project,
  spec, or article the harness relies on or learned from -- the OSS wiki's reference list is generated
  from these citations.
- Distinguish clearly in comments: *what is ours* (the detect/propose logic, the KOS vocabs) vs *what is
  borrowed* (the apply/query/input via Obsidian-native tools). Never imply authorship of borrowed work.
- If a capability copies code (not just calls a tool), preserve the upstream licence header + note the
  source commit.

The division this encodes: **custom engines DETECT + PROPOSE (the genuine gaps); mature OSS does
APPLY + QUERY + INPUT** -- Tag Wrangler (tag merge), Obsidian Bases (queries/dashboards), the Linter +
Properties + Frontmatter Smith (frontmatter input/normalisation). Don't reinvent the apply.

## Changelog
- 2026-06-27: created (Phase 1 keystone).
- 2026-06-27: + section 12 cross-platform/MSYS gotchas (UTF-8 subprocess, leading-slash path conversion).
- 2026-06-27: + section 13 OSS attribution convention + the detect/propose-vs-apply/query division.
