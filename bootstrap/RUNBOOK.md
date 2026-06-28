# Fresh-machine reinstall runbook (Linux + macOS + Windows, co-equal)

Rebuild the whole multi-env Claude Code setup on a clean **Linux or Windows** box. Order matters; each
step says **auto** (the bootstrap script does it) or **manual**. Target ~30-45 min. Validate end-to-end
in a throwaway VM/container before trusting it (§8). The engines are cross-platform Python — the only
OS-specific part is this bootstrap kit (`bootstrap.sh` for Linux/macOS, `bootstrap.ps1` for Windows).

## 0. Prereqs (manual)
- Linux (apt/dnf/pacman/zypper) or macOS (brew) or Windows 11 (winget). Internet.
- Secrets to hand: GitHub + GitLab creds/tokens, Anthropic login. **No secret lives in any repo** — they're
  re-entered at auth time (§3).

## 1. Toolchain + repos (auto)
```bash
git clone https://github.com/Wombat164/claude-harness        # or copy bootstrap/ across
cp claude-harness/bootstrap/repos.example.txt claude-harness/bootstrap/repos.txt   # edit: your repo URLs
# Linux / macOS:
bash claude-harness/bootstrap/bootstrap.sh claude-harness/bootstrap/repos.txt ~/Projects
# Windows:
pwsh -File claude-harness/bootstrap/bootstrap.ps1 -Root ~/Projects
```
Installs the headless toolchain (see `tools-manifest.md`), Claude Code, pyyaml; clones every repo in
`repos.txt`. Re-open the shell so PATH picks up Node/Python.

## 2. Fill the gaps the bootstrap warned about (manual)
Distro-specific: a current **Node** (nodesource/nvm — distro node is often too old for Claude Code),
**gh**/**glab** (extra apt repo or `brew`), **gitleaks** (`brew` / GitHub release). Confirm:
`git --version`, `node --version`, `gh --version`, `glab --version`, `gitleaks version`, `python3 --version`.

## 3. Auth (manual — interactive, same on both OSes)
```
gh auth login          # GitHub
glab auth login        # GitLab (private repos)
claude                 # first run -> Anthropic login
git config --global credential.helper store        # Linux
git config --global credential.helper osxkeychain  # macOS
git config --global credential.helper manager      # Windows
```

## 4. Restore Claude memory (manual)
The `.claude/` substrate (settings, hooks, scripts, commands, skills) ships **inside the vault repo** —
cloning the vault restores it. The memory STORE is separate:
```bash
# per env: clone the private memory repo into the env's memory dir
#   Linux:   ~/.claude/projects/<env-slug>/memory
#   Windows: %USERPROFILE%\.claude\projects\<env-slug>\memory
git clone <memory-repo-url> "<that path>"
cd "<that path>/_shared" && git pull        # cross-env shared core
```
Verify: `python3 <vault>/.claude/scripts/memory-consolidate.py --check`.

## 5. Vault GUI (manual)
Install Obsidian — Linux: flatpak/AppImage/snap · macOS: `brew install --cask obsidian` · Windows:
`winget install Obsidian.Obsidian`. Open the
vault, install community plugins: **Tag Wrangler**, **Linter** (⚠ open settings, DISABLE the
YAML-list/frontmatter-array reflow rule — corrupts `parent: [[X]]` on external bulk writes; 2026-06-27
incident), **Frontmatter Smith**, **Git** (mobile). Bases + Properties are core.

## 6. Install the harness (manual, in Claude Code)
```
/plugin marketplace add https://github.com/Wombat164/claude-harness
/plugin install claude-harness
```
Set env (per OS): `VAULT_ROOT`, `CLAUDE_MEMORY_DIR`, `FRONTMATTER_SCHEMA`, `VAULT_SCAN_EXCLUDE`,
`VAULT_NORENAME_ZONES` (see `config.example/`). Export in `~/.bashrc` (Linux) / `~/.zshrc` (macOS); on Windows set user env vars.

## 7. Verify
```
python3 <harness>/scripts/vault-frontmatter-lint.py --terse
python3 <harness>/scripts/memory-consolidate.py --terse
```
Both report cleanly; a vault Base renders.

## 8. From-zero test (do once)
Linux: a clean container/VM (`docker run -it ubuntu` or a fresh LXC). Windows: a throwaway VM. Run §1-§7
from nothing; record any gap back into `tools-manifest.md` / the bootstrap scripts. **This is the only real
proof the runbook is complete** — until done, resilience is "documented, not verified."

## Recovery notes
- The memory store is also its own private git repo (push after consolidation) — a lost machine loses
  nothing committed.
- Private/sensitive content + private model weights are NEVER reinstalled onto a non-private box (sovereignty).
