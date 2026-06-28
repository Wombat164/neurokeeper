#!/usr/bin/env bash
# neurokeeper fresh-machine bootstrap (Linux / macOS, co-equal). Sibling of bootstrap.ps1 (Windows).
# Idempotent: skips what's already present. Installs the headless toolchain, then clones the repos
# listed in your private repos config. Auth + GUI + Obsidian-plugin steps are MANUAL -- see RUNBOOK.md.
# Usage:  ./bootstrap.sh [REPOS_FILE] [ROOT]      (defaults: ./repos.txt  ~/Projects)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOS_FILE="${1:-$HERE/repos.txt}"
ROOT="${2:-$HOME/Projects}"
have() { command -v "$1" >/dev/null 2>&1; }

# --- macOS: ensure Homebrew (clean Apple-silicon images ship WITHOUT it) ---
# Homebrew NEEDS working sudo/admin. On a normal Mac (you're an admin) or a CI macOS runner this is fine;
# on a locked image with password-sudo and no TTY (e.g. a disposable macOS instance), make sure sudo is
# usable (passwordless or already authenticated) before running this script.
if [ "$(uname -s)" = "Darwin" ] && ! have brew; then
  echo "== macOS: installing Homebrew (none present) =="
  if NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
      [ -x "$b" ] || continue
      eval "$("$b" shellenv)"                                 # brew on PATH for this run
      grep -q 'brew shellenv' "$HOME/.zprofile" 2>/dev/null || echo "eval \"\$($b shellenv)\"" >> "$HOME/.zprofile"
    done
  else
    echo "  ERROR: Homebrew install FAILED -- it needs working sudo/admin (passwordless or pre-cached)." >&2
    echo "         Without brew the macOS toolchain CANNOT be installed. Ensure sudo is usable and re-run." >&2
  fi
fi

# --- detect package manager ---
if   have apt-get; then PM="sudo apt-get install -y"; UPD="sudo apt-get update";
elif have dnf;     then PM="sudo dnf install -y"; UPD=":";
elif have pacman;  then PM="sudo pacman -S --noconfirm"; UPD="sudo pacman -Sy";
elif have zypper;  then PM="sudo zypper install -y"; UPD=":";
elif have brew;    then PM="brew install"; UPD="brew update";
else echo "No supported package manager (apt/dnf/pacman/zypper/brew). Install tools manually -- see tools-manifest.md"; PM=""; fi

echo "== 1. headless toolchain =="
if [ -n "$PM" ]; then
  $UPD || true
  for pkg in git python3 pandoc ripgrep jq; do
    have "${pkg/python3/python3}" || $PM "$pkg" || echo "  WARN: $pkg failed (install manually)"
  done
  # gh / glab / node often need extra repos -- try, warn on miss
  have gh   || $PM gh        || echo "  gh: add GitHub apt/dnf repo or 'brew install gh' (see manifest)"
  have glab || $PM glab      || echo "  glab: 'brew install glab' or GitLab release (see manifest)"
  have node || { [ "$PM" = "brew install" ] && brew install node || $PM nodejs; } || echo "  node: prefer nodesource/nvm for a current version (distro node is often old)"
  have gitleaks || { have brew && brew install gitleaks; } || echo "  gitleaks: brew or GitHub release (see manifest)"
fi
have uv || curl -LsSf https://astral.sh/uv/install.sh | sh || echo "  uv: optional; install skipped"

echo "== 2. Claude Code + python deps =="
if have npm; then npm install -g @anthropic-ai/claude-code; else echo "  npm missing -> install Node first"; fi
if have python3; then python3 -m pip install --user --quiet --upgrade pyyaml 2>/dev/null \
  || pipx install pyyaml 2>/dev/null || echo "  pyyaml: install via your python (pip/pipx)"; fi

echo "== 3. clone repos =="
mkdir -p "$ROOT"
if [ -f "$REPOS_FILE" ]; then
  while IFS= read -r line; do
    case "$line" in ''|\#*) continue;; esac
    name="$(basename "$line" .git)"; dest="$ROOT/$name"
    if [ -d "$dest" ]; then echo "  ok  $name"; else echo "  cloning $name..."; git clone -- "$line" "$dest"; fi
  done < "$REPOS_FILE"
else
  echo "  no repos file ($REPOS_FILE) -- copy repos.example.txt -> repos.txt and fill your URLs"
fi

cat <<'EOF'

== DONE (automated part). MANUAL steps remain -- see RUNBOOK.md: ==
  - auth:  gh auth login ; glab auth login ; claude (login)
  - Obsidian (Linux: flatpak/AppImage/snap | macOS: brew install --cask obsidian) + plugins (Tag Wrangler, Linter[configure!], Frontmatter Smith, Git)
  - restore Claude memory: clone the memory repo into ~/.claude/projects/<env>/memory ; pull _shared/
  - install this harness as a plugin: /plugin marketplace add https://github.com/Wombat164/neurokeeper ; /plugin install neurokeeper
EOF
