# Distribution & listing

How neurokeeper is published and listed. Three channels, in increasing effort.

> [!important] Directory submissions are human-only
> The curated directories require submission **by a human via the web UI**. awesome-claude-code states
> outright that submissions via the `gh` CLI or other programmatic means violate its Code of Conduct and
> are auto-closed. Do **not** script these. The ready-to-paste field values below are for *you* to enter.

## 1. claudemarketplaces.com - automatic (no action)

It crawls public GitHub repos for a valid `.claude-plugin/marketplace.json` daily and lists them. This
repo is public with a valid manifest (`claude plugin validate .` passes), so it is **already eligible** and
will appear automatically. The curated tier filters on install count (~500+); nothing to submit.

## 2. awesome-claude-code - human web form, after the repo is >=1 week old

Eligibility: the list requires a resource be **at least one week old** (first public release was
2026-06-26, so eligible from ~**2026-07-04**). Submit via the repo's "Recommend a resource" **issue form**
in the github.com UI (https://github.com/hesreallyhim/awesome-claude-code/issues/new/choose). Field values:

| Field | Value |
|---|---|
| Display Name | `neurokeeper` |
| Category | `Tooling` |
| Sub-Category | `Tooling: Config Managers` |
| Primary Link | `https://github.com/Wombat164/neurokeeper` |
| Author Name | `Wombat164` |
| Author Link | `https://github.com/Wombat164` |
| License | `MIT` |

Free-text answers the form asks for:
- **Description:** Portable-core harness - deterministic, link-aware Obsidian-vault hygiene engines (tags,
  controlled-vocab frontmatter, taxonomy, link-aware rename, reference-integrity audit incl. broken
  `.canvas`/`.base` + orphans + stem collisions), a deterministic memory-audit, and an aggregate `doctor`.
  Runs as a Claude Code plugin, a standalone CLI, **and** a pre-commit / GitHub-Action CI gate. One core,
  many adapters; engines are deterministic (no LLM in the loop), so they can gate CI.
- **Install:** `/plugin marketplace add https://github.com/Wombat164/neurokeeper` then
  `/plugin install neurokeeper`; or `pipx install neurokeeper` for the CLI.
- **Uninstall:** `/plugin uninstall neurokeeper` (+ `/plugin marketplace remove neurokeeper`); or
  `pipx uninstall neurokeeper`.
- **Network requests (their reviewers ask explicitly):** the core engines make **zero** network requests --
  fully local and deterministic. The **optional** two-lane handoff (`claude-cheap`), only if the user
  explicitly configures and invokes it, sends requests **solely to a self-hosted endpoint the user
  configures** - never to any third party. No telemetry, no auto-update, no `npx @latest`.
- **Elevated access / `--dangerously-skip-permissions`:** none required.
- **Demo:** the docs site (https://wombat164.github.io/neurokeeper/) + the runnable synthetic
  `examples/vault/`.

## 3. Official Anthropic plugin directory - human web form (auth)

Submit at **https://clau.de/plugin-directory-submission** (signed in to claude.ai). Accepted plugins pass
automated security scanning and then appear in the read-only mirror `anthropics/claude-plugins-community`
(direct PRs to that repo are auto-closed - the form is the only path). Provide: name `neurokeeper`,
repository `https://github.com/Wombat164/neurokeeper` (marketplace.json at root), the description above,
category *knowledge management / tooling*, license MIT. The stricter `anthropics/claude-plugins-official`
is a later stretch goal.

## Versioning reminder

Bump `version` in `pyproject.toml`, `.claude-plugin/plugin.json`, and `neurokeeper/__init__.py` together
(it is the plugin cache key); `scripts/check-release.py` enforces this in CI. Tag `vX.Y.Z` and cut a Release.
