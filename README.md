# claude-harness

A **portable-core** harness for agentic coding/knowledge work. The load-bearing logic lives in
harness-agnostic **engines** (deterministic scripts) + **prompt templates** + **versioned contracts**;
a thin **adapter** binds them to a specific runtime. The Claude Code plugin is *one* adapter — the same
core works from an MCP server, a plain CLI, or any other LLM harness.

> Status: **0.1.5 (alpha).** Licensed **MIT** (see [`LICENSE`](LICENSE)).

## Why
"Skills" (and plugins, hooks) are runtime-specific and not portable. Putting the real logic in **engines
+ prompts** makes a capability reusable across runtimes, vendor-neutral, and safe to open-source — and it
lets you point the same engine at a self-hosted open model to save tokens. See
[`docs/pattern-portable-core-and-adapters.md`](docs/pattern-portable-core-and-adapters.md) (the keystone).

## The shape of a capability
```
portable core (this repo)                      adapters (bind the core to a runtime)
  scripts/<engine>.py   deterministic, --json    .claude-plugin + skills/  -> Claude Code
  prompts/<engine>.md   harness-neutral judgment  (future) mcp/            -> MCP server
  (contract = the engine's --json/CLI)            scripts run directly     -> plain CLI / CI / any LLM
```
Each engine carries a metadata header (`@capability/@compute/@effect/@portability/...`);
`scripts/registry-generate.py` scans those and emits a registry (anti-rot, never hand-maintained).

## Layout
- `scripts/` — portable engines (deterministic). `_vault_guard.py` is a shared safety preflight.
- `prompts/` — harness-neutral judgment templates.
- `skills/` — Claude Code adapter skills (thin; defer logic to engine+prompt).
- `hooks/hooks.json` — Claude Code hooks (e.g. SessionStart memory-health).
- `.claude-plugin/plugin.json` — the Claude Code plugin manifest.
- `config.example/` — example consumer config (L2). **This repo ships schemas + examples only — never
  real config or content.** Consumers supply their own private config + content.
- `docs/` — the pattern doc + decisions.
- `tools.lock` — runtime tool deps (classified headless / gui / manual).

## Install

**As a Claude Code plugin** (engines + skills + hooks; `bin/claude-harness` on PATH):
```
/plugin marketplace add https://github.com/Wombat164/claude-harness
/plugin install claude-harness
```

**As a standalone CLI** (the engines, runnable anywhere / in CI -- no Claude Code needed):
```
pipx install claude-harness        # or:  uv tool install claude-harness        (once on PyPI)
pip install -e ".[dev]"            # from a checkout (editable, with test/lint deps)
```
Then run any engine via the dispatcher:
```
claude-harness <engine> [args]     # e.g.  claude-harness taxonomy-inventory --json
claude-harness --list              # list engines
```
Either way, set `CLAUDE_MEMORY_DIR` (and optional `VAULT_*`) per `config.example/`. The same engines back
all three faces (plugin / CLI / direct `python scripts/<engine>.py`) -- one codebase, no fork.

## First capability: `memory-audit`
A file-based-memory health check + consolidation: deterministic engine
(`scripts/memory-consolidate.py` — 5-metric score, orphans, broken-links, importance curve,
`--check`/`--terse`/`--json`) + judgment prompt (`prompts/memory-audit.md`) + the `memory-audit` skill
(the Claude Code adapter). The reference shape every other capability copies.

## Vault taxonomy engine suite (L1a)
Deterministic, link-aware, Obsidian-guarded engines for Obsidian-vault KOS hygiene (proven on a ~1,400-note
vault). All read `VAULT_ROOT` + config from the environment (see `config.example/`); dry-run/report by
default, mutating only with `--apply` behind the Obsidian-running guard; git is the audit.

- `vault-taxonomy-inventory.py` -- naming/tags/frontmatter inventory (read-only)
- `vault-ref-audit.py` -- reference-integrity audit: broken links / orphans / dead-ends / broken `.canvas`+`.base` refs / orphan media / name-stem collisions (read-only; `--check`/`--strict`)
- `vault-doctor.py` -- aggregate health: runs every applicable engine, one report + an honest tri-state roll-up (`ok`/`fail`/`skipped`); `--check`/`--strict` (see [ADR-0002](docs/adr-0002-doctor-exit-semantics.md))
- `vault-frontmatter-lint.py` -- validate notes against the schema (off-vocab / missing-axes / unknown-fields); `--check`
- `vault-frontmatter-fix.py` -- apply the schema reconciliation maps (status/maturity/horizon; surgical line-edits)
- `vault-set-note-type.py` -- additive `note_type` from a folder-derive map
- `vault-tag-reconcile.py` -- detect morphological tag-merge groups (apply via Tag Wrangler)
- `vault-name-reconcile.py` -- de-dash + kebab filenames, link-aware rename
- `_vault_lib.py` -- shared core (walk / frontmatter / folder-suffix / kebab); `_vault_guard.py` -- Obsidian-running guard

Schema-as-code lives in your config; `config.example/frontmatter-schema.example.yaml` is a worked example.

## Fresh-machine reinstall (resilience) — Linux + macOS + Windows, co-equal
`bootstrap/` rebuilds the whole multi-env setup on a clean **Linux, macOS, or Windows** box (the engines are
cross-platform Python; only the bootstrap kit is OS-specific):
- `tools-manifest.md` — toolchain catalog with **per-OS** install source (Linux apt/dnf/brew + Windows winget) + class
- `bootstrap.sh` (Linux/macOS) **/** `bootstrap.ps1` (Windows) — idempotent installers: headless toolchain + Claude Code + clone repos from your `repos.txt`
- `RUNBOOK.md` — end-to-end procedure (both OSes) incl. auth, memory restore, Obsidian + plugins, plugin install + a from-zero VM/container test
- `repos.example.txt` — template for your private repo list (`repos.txt` is gitignored)

Quickstart — Linux: `bash bootstrap/bootstrap.sh bootstrap/repos.txt ~/Projects` · Windows:
`pwsh -File bootstrap/bootstrap.ps1 -Root ~/Projects` — then follow `RUNBOOK.md`.

## Two-lane model handoff (optional, token-saving)

Keep hard agentic work on your normal Claude lane; route mechanical, high-volume work (commit messages,
summaries, extraction, classification, formatting) to a **self-hosted** open model via the `claude-cheap`
wrapper, so cheap work costs ~nothing. It points `ANTHROPIC_BASE_URL` at *your* `/v1/messages`-compatible
endpoint **for that invocation only** -- your default `claude` is untouched.
```
claude-cheap -p "write a conventional-commit message for the staged diff"
```
Config via `config.example/cheap-lane.env.example`. The design, the **billing trap** to avoid (a credentialed
gateway flips you off your subscription onto per-token), the task-class whitelist, the serving recipes
(vLLM-native / LiteLLM / claude-code-router), the **data-egress/sovereignty** warning, and a
measure-before-you-trust plan are in [`docs/two-lane-model-handoff.md`](docs/two-lane-model-handoff.md).

## Related projects

claude-harness builds on a healthy ecosystem; if it doesn't fit, one of these might:
- **[claude-mnemo](https://github.com/jojoprison/claude-mnemo)** — Claude Code plugin: Obsidian-vault memory + a lean `MEMORY.md` index + a `/health` audit (the closest neighbour on the memory side).
- **[claude-memory-health](https://github.com/alexknowshtml/claude-memory-health)** / **[claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler)** — markdown-memory audit + consolidation.
- **[obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server)** — MCP tools for Obsidian (tag / frontmatter primitives).
- **Native Obsidian plugins** — [Tag Wrangler](https://github.com/pjeby/tag-wrangler), [Linter](https://github.com/platers/obsidian-linter), Smart Rename — the GUI "apply" layer this project deliberately defers to (the engines **detect + propose**; these **apply**).

What's different here: the deterministic vault-hygiene **engine suite** (tag / frontmatter / taxonomy / link-aware rename) + memory-audit behind a **portable core** — one codebase running as a Claude Code plugin *and* a standalone CLI/CI tool — rather than any single one of the above.

## Security & license
- **License:** MIT — see [`LICENSE`](LICENSE).
- **Secret scanning:** CI runs `gitleaks` with its default rules (secret-only) on every push, blocking.
  Maintainers additionally run a private keyword OPSEC scan before publishing; that config enumerates the
  terms it looks for, so it is kept out of the public tree (gitignored, local-only) and is not needed to
  build, test, or use the project. See [`SECURITY.md`](SECURITY.md).
