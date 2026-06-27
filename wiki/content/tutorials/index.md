---
title: Getting started
description: Install claude-harness and run your first engine -- as a CLI and as a Claude Code plugin.
tags:
  - tutorial
  - getting-started
---

> [!note] This is a tutorial (learning-oriented)
> Follow it start to finish on a scratch checkout. It teaches the shape of the tool by *doing*; it is
> not a complete reference. When you need to look something up, see [Reference](../reference/); when you
> have a specific task in mind, see [How-to guides](../how-to/).

By the end you will have installed claude-harness, listed its engines, and run a read-only engine that
produces a JSON report -- without touching any of your files.

## Prerequisites

- **Python 3.9+** (the engines are plain Python; they run on Linux, macOS, and Windows).
- A terminal. That is all you need for the CLI path.
- *(Optional)* **Claude Code**, if you want to try the plugin adapter in the last step.

## Step 1 -- Get the code

Either install the published package, or work from a checkout:

```bash
# from a checkout (editable, with test/lint deps):
git clone <claude-harness-repo-url>
cd claude-harness
pip install -e ".[dev]"

# or, once published:
pipx install claude-harness        # or: uv tool install claude-harness
```

This puts a single console command, `claude-harness`, on your PATH. That command is a **dispatcher**: it
runs the same engine files the plugin and CI use -- one codebase, no fork.

## Step 2 -- List the engines

```bash
claude-harness --list
```

You should see the available engines (for example `taxonomy-inventory`, `frontmatter-lint`,
`memory-consolidate`, `registry-generate`). Each name maps to one deterministic script. Full descriptions
live in the [Reference engine catalog](../reference/).

## Step 3 -- Run your first engine (read-only)

Every engine defaults to **report-only**: it never writes anything unless you explicitly pass `--apply`.
Run the capability registry generator, which just prints the catalog of engines as markdown:

```bash
claude-harness registry-generate
```

Now ask an engine for machine-readable output -- the `--json` flag is part of every engine's contract:

```bash
claude-harness registry-generate --json
```

You just exercised the core contract: a deterministic engine, a `--json` output, and zero side effects.

## Step 4 -- Point an engine at some content

Engines that work over a notes vault read their target from the environment, so the same binary works
against any vault:

```bash
export VAULT_ROOT="/path/to/your/notes"     # Windows PowerShell: $env:VAULT_ROOT = "C:\path\to\notes"
claude-harness taxonomy-inventory --json
```

This produces a read-only inventory of naming / tags / frontmatter. Still nothing is written -- inventory
is a read-only capability. (For the env vars each engine reads, see the
[Reference: environment configuration](../reference/).)

> [!note] The frontmatter engines also need a schema
> `frontmatter-lint` and `frontmatter-fix` validate notes against your schema-as-code, so they read a
> second variable, `FRONTMATTER_SCHEMA`. Copy the shipped example and point at it:
> ```bash
> cp config.example/frontmatter-schema.example.yaml my-frontmatter-schema.yaml   # then edit
> export FRONTMATTER_SCHEMA="$PWD/my-frontmatter-schema.yaml"
> ```
> If it is unset and no schema is found, those engines print a one-line message telling you how to set
> it (instead of a traceback). The `taxonomy-inventory` engine you ran above needs no schema.

## Step 5 -- Try the Claude Code adapter (optional)

The CLI you just used is one face of the core. The Claude Code plugin is another -- the *same* engines,
exposed as skills and hooks:

```text
/plugin marketplace add <harness-url>
/plugin install claude-harness
```

Inside Claude Code you can then invoke the bundled capability (for example the memory-audit skill), which
runs the identical engine and adds an LLM-judgment step on top of the engine's output.

## What you learned

- claude-harness installs as **one dispatcher CLI** that runs deterministic engines.
- Every engine speaks the same **contract**: `--json` output, exit codes, **report-by-default**.
- The **same engines** back the CLI, CI, and the Claude Code plugin -- different adapters, one core.

## Next steps

- Do a real task: [How-to guides](../how-to/) (reconcile tags, run the memory-audit, add an engine).
- Understand the design: [[explanation/index|the portable-core model and layer doctrine]].
