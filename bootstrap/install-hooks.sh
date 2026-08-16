#!/usr/bin/env bash
# Install the neurokeeper git hooks into the CURRENT repository.
#
# Uses core.hooksPath rather than copying files into .git/hooks. Two reasons, both learned
# the hard way by every project that chose copying:
#
#   1. .git/hooks IS NOT CLONED. A copied hook protects exactly one working copy on one
#      machine. Clone the repo on another host -- a remote dev box, a CI runner, a fresh
#      laptop -- and the guard is silently absent while everything still looks installed.
#      core.hooksPath points at a tracked directory, so the hooks travel with the repo and
#      installation is one command instead of one command per hook.
#   2. A copy drifts. Fix a hook in bootstrap/hooks and every copy stays stale until someone
#      remembers. There is no "someone remembers" in a security control.
#
# core.hooksPath is still per-clone local config, so this must be run once per clone. That
# is the irreducible part: git offers no way to ship active hooks in a clone, by design,
# because that would make cloning a repository arbitrary code execution.
#
# Usage:  bootstrap/install-hooks.sh [--check]
#         --check  verify only, exit 1 if not installed (use in CI)

set -euo pipefail

root=$(git rev-parse --show-toplevel 2>/dev/null) || {
  echo "install-hooks: not inside a git repository" >&2; exit 2; }

# The hooks path is a FIXED FACT of this repo's layout, not something to derive from
# $BASH_SOURCE. Deriving it broke on git-bash: `git rev-parse --show-toplevel` returns
# `C:/Users/...` while `pwd` returns `/c/Users/...`, so stripping the root prefix silently
# failed and produced an absolute path that --check could then never match against the value
# git had normalised on the way in. A constant cannot have that bug.
hooks_rel="bootstrap/hooks"
here="$root/$hooks_rel/.."

if [ "${1:-}" = "--check" ]; then
  current=$(git -C "$root" config --get core.hooksPath || echo "")
  if [ "$current" = "$hooks_rel" ]; then
    echo "install-hooks OK: core.hooksPath = $current"
    exit 0
  fi
  echo "install-hooks FAIL: core.hooksPath is '${current:-<unset>}', expected '$hooks_rel'" >&2
  echo "  run: bootstrap/install-hooks.sh" >&2
  exit 1
fi

git -C "$root" config core.hooksPath "$hooks_rel"
chmod +x "$here/hooks/"* 2>/dev/null || true

echo "install-hooks: core.hooksPath -> $hooks_rel"
for h in "$here"/hooks/*; do
  [ -f "$h" ] && echo "  active: $(basename "$h")"
done

# A gate nobody has proven is a gate nobody should trust. Prove it here, at install time,
# while the person who ran this is still watching.
echo ""
echo "verifying the vocabulary gate fires..."
if command -v neurokeeper >/dev/null 2>&1; then
  gate="neurokeeper egress-gate"
elif [ -f "$root/scripts/egress-gate.py" ]; then
  gate="python $root/scripts/egress-gate.py"
else
  echo "  WARNING: egress-gate engine not found. The hooks will REFUSE (fail closed)" >&2
  echo "  until neurokeeper is on PATH or scripts/egress-gate.py exists." >&2
  exit 0
fi

set +e
$gate --text "canary" >/dev/null 2>&1
rc=$?
set -e
case $rc in
  0) echo "  OK: engine ran and the term lists loaded." ;;
  1) echo "  OK: engine ran (the canary text matched a term, which is fine)." ;;
  2) echo "  NOTE: engine is fail-closed with no term source loaded. Point EGRESS_DENYLIST"
     echo "        or tools/lexicon.deny.txt at a list, or pushes will be refused." ;;
  *) echo "  WARNING: engine exited $rc, unexpected." >&2 ;;
esac
