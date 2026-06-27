# Tools manifest — fresh-machine reinstall (Linux + macOS + Windows, co-equal)

Everything the multi-env Claude Code setup depends on, with install source per OS + class. `bootstrap.sh`
(Linux/macOS) and `bootstrap.ps1` (Windows) install the **headless** rows automatically; **gui**/**manual**
rows are done by hand (see `RUNBOOK.md`). The engines themselves are cross-platform Python (paths via
`os`, Obsidian-running check via `pgrep` *or* `tasklist`). Versions = last-known-good 2026-06-27 (floor).

| Tool | Last-good | Purpose | Linux/macOS (apt/dnf/brew) | Windows (winget) | Class |
|---|---|---|---|---|---|
| Python 3 | 3.14 | engines (stdlib + pyyaml) | `python3` / `brew install python` | `Python.Python.3.14` | headless |
| pyyaml | 6.0 | schema/frontmatter parsing | `pip install --user pyyaml` (or pipx) | `pip install pyyaml` | headless |
| Git | 2.54 | everything | `git` | `Git.Git` | headless |
| Node.js | 26 | Claude Code runtime | nodesource / nvm (distro node is old) | `OpenJS.NodeJS` | headless |
| Claude Code | 2.1 | the harness host | `npm i -g @anthropic-ai/claude-code` | (same) | headless |
| GitHub CLI | 2.83 | gh repos/auth | `gh` (apt repo) / `brew install gh` | `GitHub.cli` | headless |
| GitLab CLI (glab) | 1.105 | private repos | `brew install glab` / GitLab release | `GLab.GLab` (verify) | headless |
| gitleaks | 8.30 | secret-scan pre-commit gates | `brew install gitleaks` / GH release | scoop / GH release | headless |
| pandoc | 3.10 | document render pipeline | `pandoc` / `brew install pandoc` | `JohnMacFarlane.Pandoc` | headless |
| ripgrep (rg) | bundled | search (Claude Code bundles its own) | `ripgrep` | `BurntSushi.ripgrep.MSVC` | optional |
| uv | 0.11 | fast python envs (optional) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `astral-sh.uv` | optional |
| PowerShell 7 | 7.6 | shell on Windows; optional on Linux | `brew install powershell` (optional) | `Microsoft.PowerShell` | headless(win) |
| Obsidian (app) | latest | vault GUI (Bases, Linter, Tag Wrangler) | flatpak/AppImage/snap · macOS `brew install --cask obsidian` | `Obsidian.Obsidian` | gui |
| obsidian-cli | n/a | indexed vault ops (needs running GUI) | per its repo | per its repo | manual |

## Obsidian community plugins (in-app, manual — both OSes)
Tag Wrangler (pjeby), Linter (platers — **disable the YAML-list/frontmatter-array reflow rule**, the
2026-06-27 corruption culprit), Frontmatter Smith (stroiman), Git plugin (mobile). Bases + Properties are core.

## Not required / never
- `jq` — engines use Python instead.
- Private model weights / private content — NEVER reinstalled onto a non-private box (sovereignty).
