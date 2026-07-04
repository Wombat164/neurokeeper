# neurokeeper

[![CI](https://github.com/Wombat164/neurokeeper/actions/workflows/test.yml/badge.svg)](https://github.com/Wombat164/neurokeeper/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/Wombat164/neurokeeper)](https://github.com/Wombat164/neurokeeper/releases)
[![license](https://img.shields.io/github/license/Wombat164/neurokeeper)](LICENSE)
[![docs](https://img.shields.io/badge/docs-wombat164.github.io-blue)](https://wombat164.github.io/neurokeeper/)

A **portable-core** harness for agentic coding/knowledge work. The load-bearing logic lives in
harness-agnostic **engines** (deterministic scripts) + **prompt templates** + **versioned contracts**;
a thin **adapter** binds them to a specific runtime. The Claude Code plugin is *one* adapter — the same
core works from an MCP server, a plain CLI, or any other LLM harness.

> Status: **0.3.0 (alpha).** Licensed **MIT** (see [`LICENSE`](LICENSE)).

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

**As a Claude Code plugin** (engines + skills + hooks; `bin/neurokeeper` on PATH):
```
/plugin marketplace add https://github.com/Wombat164/neurokeeper
/plugin install neurokeeper
```

**As a standalone CLI** (the engines, runnable anywhere / in CI -- no Claude Code needed):
```
pipx install git+https://github.com/Wombat164/neurokeeper   # from GitHub
pip install -e ".[dev]"                                         # from a checkout (editable, with test/lint deps)
```
(The bare PyPI name `neurokeeper` is taken by an unrelated project, so install from GitHub; a future
PyPI release would use a distinct distribution name.)
Then run any engine via the dispatcher:
```
neurokeeper <engine> [args]     # e.g.  neurokeeper taxonomy-inventory --json
neurokeeper --list              # list engines
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

## Gate a vault in CI (pre-commit + GitHub Action)
The same engines run as a commit/CI gate. neurokeeper ships a `.pre-commit-hooks.yaml` and a composite
`action.yml`; both run the **vault-graph-aware** checks it uniquely owns and **compose with** the ecosystem
(markdownlint / lychee / check-jsonschema) for the commoditized ones.
```yaml
# .pre-commit-config.yaml (in your vault repo)
repos:
  - repo: https://github.com/Wombat164/neurokeeper
    rev: v0.3.0
    hooks: [{ id: neurokeeper-doctor }]
```
```yaml
# a GitHub workflow step
- uses: Wombat164/neurokeeper@v0.3.0
  with: { vault-path: ".", engine: "doctor", strict: "false" }
```
Exit semantics follow [ADR-0002](docs/adr-0002-doctor-exit-semantics.md) (fails on broken `.canvas`/`.base`
refs or engine errors; advisory + skipped engines never fail). Full guide + the example vault:
[`docs/ci-adapters.md`](docs/ci-adapters.md) · [`examples/vault/`](examples/vault).

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

neurokeeper builds on a healthy ecosystem; if it doesn't fit, one of these might:
- **[claude-mnemo](https://github.com/jojoprison/claude-mnemo)** — Claude Code plugin: Obsidian-vault memory + a lean `MEMORY.md` index + a `/health` audit (the closest neighbour on the memory side).
- **[claude-memory-health](https://github.com/alexknowshtml/claude-memory-health)** / **[claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler)** — markdown-memory audit + consolidation.
- **[obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server)** — MCP tools for Obsidian (tag / frontmatter primitives).
- **Native Obsidian plugins** — [Tag Wrangler](https://github.com/pjeby/tag-wrangler), [Linter](https://github.com/platers/obsidian-linter), Smart Rename — the GUI "apply" layer this project deliberately defers to (the engines **detect + propose**; these **apply**).

What's different here: the deterministic vault-hygiene **engine suite** (tag / frontmatter / taxonomy / link-aware rename) + memory-audit behind a **portable core** — one codebase running as a Claude Code plugin *and* a standalone CLI/CI tool — rather than any single one of the above. A source-verified survey of the field (and exactly where neurokeeper is differentiated) is in [`docs/competitive-landscape.md`](docs/competitive-landscape.md).

Where this is heading (repository-agnostic backends, editor-state preflight, Bases/dashboard output adapters, and what is deliberately NOT planned) lives in [`docs/roadmap.md`](docs/roadmap.md); the backend-seam contract it builds on is [`docs/adr-0001-backend-contract.md`](docs/adr-0001-backend-contract.md).

## Security & license
- **License:** MIT — see [`LICENSE`](LICENSE).
- **Secret scanning:** CI runs `gitleaks` with its default rules (secret-only) on every push, blocking.
  Maintainers additionally run a private keyword OPSEC scan before publishing; that config enumerates the
  terms it looks for, so it is kept out of the public tree (gitignored, local-only) and is not needed to
  build, test, or use the project. See [`SECURITY.md`](SECURITY.md).
