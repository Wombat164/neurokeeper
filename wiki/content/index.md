---
title: claude-harness
description: A portable-core harness for agentic coding and knowledge work.
tags:
  - overview
---

**claude-harness** is a portable-core harness for agentic coding and knowledge work. The load-bearing
logic lives in harness-agnostic **engines** (deterministic scripts) plus **prompt templates** plus
**versioned contracts**; a thin **adapter** binds them to a specific runtime. The Claude Code plugin is
*one* adapter -- the same core runs from a plain CLI, from CI, or from any other LLM harness.

> [!tip] The one idea
> A capability is **not** a plugin feature. It is a portable core (engine + prompt + contract) that a
> thin, swappable adapter binds to a runtime. The core is the reusable asset; the adapter is glue.

## Why a portable core

Runtime-specific constructs (skills, plugins, hooks) are not portable. Putting the real logic in
**engines + prompts** makes a capability:

- **portable** -- the same engine runs as a CLI, in CI, or behind any LLM harness;
- **vendor-neutral** -- no lock-in to a single agent runtime;
- **safe to open-source** -- the deterministic core has no runtime secrets baked in;
- **token-thrifty** -- an adapter can point the same engine at a self-hosted open model.

## The shape of a capability

```
portable core (this repo)                       adapters (bind the core to a runtime)
  scripts/<engine>.py   deterministic, --json     plugin + skills  -> Claude Code
  prompts/<engine>.md   harness-neutral judgment   mcp server      -> any MCP client
  (contract = the engine's --json / CLI)           run directly    -> CLI / CI / any LLM
```

Each engine carries a machine-parseable metadata header (`@capability` / `@compute` / `@effect` /
`@portability` / ...). A generator scans those headers and emits the [[reference/index|capability
registry]] -- so the catalog can never rot out of sync with the code.

## Start here (organised by [Diataxis](https://diataxis.fr/))

| Quadrant | For when you want to... | Go to |
|---|---|---|
| **Tutorials** | *learn by doing* -- install it and run your first engine | [Tutorials](tutorials/) |
| **How-to guides** | *get a specific task done* -- a recipe you can follow | [How-to guides](how-to/) |
| **Reference** | *look up a fact* -- the engine catalog, contracts, env vars | [Reference](reference/) |
| **Explanation** | *understand the design* -- the portable-core model + doctrine | [Explanation](explanation/) |

New here? Start with the [[tutorials/index|getting-started tutorial]], then skim
[[explanation/index|the portable-core explanation]] to understand *why* it is shaped this way.
