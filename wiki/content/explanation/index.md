---
title: Explanation
description: The portable-core + adapters model, the layer doctrine, and the ecosystem-borrow division.
tags:
  - explanation
  - architecture
---

> [!note] This is explanation (understanding-oriented)
> Discursive background on *why* neurokeeper is shaped the way it is. It does not give steps (see
> [How-to guides](../how-to/)) or exhaustive field lists (see [Reference](../reference/)).

## The problem: runtime-specific logic is not portable

Agent runtimes give you constructs -- skills, plugins, hooks, slash commands -- and it is tempting to put
your capability's logic *in* them. The catch: that logic is then locked to one runtime. Move to a
different harness, or want to run the same capability in CI or behind a self-hosted model, and you are
rewriting it. "Skills are not portable" is the gap this project closes.

## The one idea: portable core + thin adapters

A capability is **not** a skill. A capability is a **portable core** that a thin, swappable **adapter**
binds to a specific runtime. The core is harness-agnostic and is the real reusable asset; the adapter is
disposable glue.

```
PORTABLE CORE  (harness-agnostic; the reusable asset)
  engine    = deterministic script with a CLI + --json contract   -> runs anywhere (human / CI / any LLM)
  prompt    = plain-markdown prompt template                       -> any LLM
  contract  = the engine's versioned JSON / CLI interface          -> the seam
        |
        +-- adapter: a plugin skill        (slash-command binding for one agent runtime)
        +-- adapter: an MCP server          (cross-harness / cross-machine / called mid-reasoning)
        +-- adapter: a plain CLI            (human / CI / cron)
        +-- adapter: another LLM harness    (a different agent framework)
```

The rule that makes it work: **put all load-bearing logic in the engine + prompt; keep adapters thin.**
If logic lives in the skill markdown, it is locked to one runtime. If it lives in the engine, it is
portable. The payoff is portability, vendor-neutrality, open-source reuse (others bring their own
harness), and a token-saving handoff -- an adapter can point the same engine at a self-hosted open model.

### The three core artifacts

- **engine** -- a deterministic script that computes facts / candidates / validations, or applies a
  deterministic transform. It exposes `--json` and exit codes. It **cannot hallucinate**: it is code.
- **prompt** -- a markdown template for the LLM-judgment step, *if any*. It references the engine's
  output and restates no facts. It does only the judgment the engine cannot: decide, synthesize,
  classify, write prose -- bounded by the engine's output.
- **contract** -- the engine's documented CLI flags and `--json` schema, versioned. It is the stable
  seam adapters and prompts depend on. Change the schema -> bump the version -> update consumers.

A load-bearing invariant follows: *the LLM never states a number or filename the engine did not produce.*
Anything that must be reproducible (counts, audits, compliance) is pushed into the engine; the LLM is
kept to genuine judgment.

## The capability typology (compute x effect)

Not every capability needs the full machinery. Classify each on two axes, and that decides which layers
apply:

- **compute:** `deterministic` (engine only) / `llm` (prompt only) / `hybrid` (engine feeds prompt).
- **effect:** `read-only` (produces a report; mutates nothing) / `mutating` (writes content or state).

The **four-layer maximum shape** is reserved for `hybrid` + `mutating`:

```
1. engine        deterministic facts / candidates (--json)         [unless compute is llm-only]
2. judgment      the LLM decides on the engine's output            [unless compute is deterministic]
3. gate          the operator confirms mutations (per-row, diff)   [only if effect is mutating]
4. apply+audit   deterministic write + append-only audit + verify  [only if effect is mutating]
```

Common subsets: a `deterministic + read-only` capability is engine-only; a `hybrid + read-only` one is
engine + judgment with no gate; an `llm + *` one has a prompt and no engine. Anything `mutating` **must**
have the gate and the audit.

## The layer model: L1a / L1b / L2 / L3

A clean separation of *what is generic and publishable* from *what is private*. It is what lets the core
be open-sourced while the sensitive material never leaves home.

| Layer | What lives here | Publishable? |
|---|---|---|
| **L1a -- portable core** | The generic engines, prompts, and contracts. The reusable asset. | Yes (open-source). |
| **L1b -- private mechanism** | Domain-specific engines (for example a bespoke document renderer for one organisation's templates). Same pattern, private content. | No. |
| **L2 -- config** | The config the engines read: registries, denylists, paths, vocabularies, schemas. Schema-as-code. | Schemas/examples only. |
| **L3 -- content** | The actual notes and memory facts the engines act on. | No -- never. |

This split mirrors the "public base + private overlay" idea from dotfiles managers (chezmoi, GNU stow,
yadm): a public, generic base plus a private overlay that never enters the public repo. The harness
**ships L1a plus L2 schemas and examples** -- never real config (L2 values) and never content (L3). A
consumer supplies their own private config and content. Memory holds only a one-line *pointer* to a
capability, never its detail.

## The ecosystem-borrow doctrine: DETECT + PROPOSE vs APPLY

A capability does not have to do everything itself. The division this project follows:

> **Custom engines DETECT + PROPOSE (the genuine gaps); mature tools do APPLY + QUERY + INPUT.**

The genuinely missing piece is usually the *detection and proposal* logic -- finding the tag-merge
groups, computing the health score, deriving the rename. The *apply*, *query*, and *input* steps are
already solved well by mature ecosystem tools (a tag-rename tool that uses the app's own parser; a query
plugin for dashboards; a frontmatter-input plugin with controlled-vocabulary dropdowns). So the engine
detects and proposes; the mature tool applies. Don't reinvent the apply.

This is also why attribution is first-class: whenever a capability borrows, wraps, or recommends an
external project, it is cited by name, author, licence, and URL -- in both the code and a single sources
list. Good citizenship, and a precondition for publishing.

## Adapters and the MCP graduation ladder

The core is fixed; the **binding varies**. Default to on-box (a script / CLI / a plugin skill). An MCP or
HTTP binding is **not** a more advanced skill -- it is a different binding for a different need, and it
has real cost.

**Stay on-box** when the capability is a local, fast, deterministic transform with a single consumer and
no shared state. Wrapping that in a server is pure overhead and attack surface.

**Graduate to an MCP / API binding** only when a trigger fires:

1. **Shared live state** -- a single source of truth across multiple consumers (a database).
2. **It is a service, not a transform** -- stateful, long-running, concurrent, needs auth or
   rate-limiting, or wraps an external system.
3. **Cross-machine** -- it must run elsewhere (for example a remote GPU host) and be called from your
   workstation. This is the self-hosted-model handoff.
4. **Cross-harness reuse via one standard** -- one server callable by many clients with no per-harness
   adapter.
5. **Called mid-reasoning** -- the model must invoke it inline as a typed tool, not as a slash command.

Because the core is fixed, graduating later is cheap: give the engine a clean `--json` contract now, add
the binding when a trigger fires. Never MCP-everything; never on-box-everything. The MCP cost -- a server
to run, auth, a network hop, and an egress surface -- is exactly why it is opt-in.

## Audit substrates: two stores, two logs

Mutating capabilities must audit, and the *substrate decides the trail*:

- **Markdown content** -> **git**. A clear commit (message + diff) *is* the audit. No extra log.
- **A memory store** -> an **append-only, hash-chained log**. The chain detects tampering and lets the
  consolidation history be replayed and verified.

Read-only capabilities need no audit. Forcing content mutations into the chained log (or memory
mutations into bare git) is a category error.

## See also

- Do it: [How-to guides](../how-to/) · Learn it: [[tutorials/index|Getting started]] · Look it up:
  [Reference](../reference/).
