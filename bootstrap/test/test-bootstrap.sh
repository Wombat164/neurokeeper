#!/usr/bin/env bash
# neurokeeper -- cross-platform CI/test for bootstrap.sh (Linux + macOS, co-equal).
#
# NON-INTERACTIVE. Designed for a CLEAN / DISPOSABLE environment: this exercises
# bootstrap.sh for real, which installs system packages via sudo (apt/dnf/pacman/
# zypper/brew) and `npm i -g`. NEVER run it on a daily-driver box. See README.md.
#
# What it asserts:
#   1. Builds a SYNTHETIC repos file (one tiny PUBLIC repo) in a temp dir.
#   2. Runs  bootstrap.sh <repos-file> <temp-root>.
#   3. REQUIRED tools present + version printed: python3, git, node (HARD fail).
#      OPTIONAL (warn only -- CI may lack them): gh, glab, gitleaks, pandoc,
#      ripgrep (rg), uv, claude.
#   4. The synthetic repo was cloned into <temp-root>.
#   5. A SECOND run exits 0 and takes the idempotent "ok" path (repo skipped,
#      not re-cloned).
#   6. bootstrap.sh itself has LF line endings (no CR).
#   7. Prints a PASS/FAIL table; exits 1 on any HARD failure.
#
# Usage:  bash bootstrap/test/test-bootstrap.sh
set -u

# ---- locate scripts ----------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_DIR="$(cd "$HERE/.." && pwd)"
BOOTSTRAP_SH="$BOOTSTRAP_DIR/bootstrap.sh"

# ---- result table ------------------------------------------------------------
ROWS=()
HARD_FAIL=0
pass() { ROWS+=("PASS|$1|${2:-}"); }
fail() { ROWS+=("FAIL|$1|${2:-}"); HARD_FAIL=$((HARD_FAIL + 1)); }
warn() { ROWS+=("WARN|$1|${2:-}"); }
ver()  { "$@" 2>&1 | head -n 1; }

# ---- temp workspace + cleanup ------------------------------------------------
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/neurokeeper-test.XXXXXX")"
cleanup() { [ -n "${WORKDIR:-}" ] && rm -rf "$WORKDIR"; }
trap cleanup EXIT INT TERM

REPOS_FILE="$WORKDIR/repos.txt"
ROOT="$WORKDIR/root"
REPO_URL="https://github.com/octocat/Hello-World.git"   # tiny PUBLIC throwaway repo
REPO_NAME="Hello-World"

cat > "$REPOS_FILE" <<EOF
# synthetic test repos file -- public, tiny, throwaway (no private URLs)
$REPO_URL
EOF

echo "== neurokeeper bootstrap.sh test =="
echo "  bootstrap : $BOOTSTRAP_SH"
echo "  workdir   : $WORKDIR"
echo "  repos     : $REPOS_FILE"
echo "  root      : $ROOT"
echo

# ---- pre-flight: bootstrap.sh exists -----------------------------------------
if [ -f "$BOOTSTRAP_SH" ]; then
  pass "bootstrap.sh present" "$BOOTSTRAP_SH"
else
  fail "bootstrap.sh present" "missing: $BOOTSTRAP_SH"
fi

# ---- check: LF line endings (no CR) ------------------------------------------
if [ -f "$BOOTSTRAP_SH" ]; then
  CR_COUNT="$(tr -cd '\r' < "$BOOTSTRAP_SH" | wc -c | tr -d '[:space:]')"
  if [ "${CR_COUNT:-0}" -eq 0 ]; then
    pass "bootstrap.sh LF endings" "0 CR bytes"
  else
    fail "bootstrap.sh LF endings" "$CR_COUNT CR byte(s) -- would fail on Linux"
  fi
fi

# ---- run 1 (cold) ------------------------------------------------------------
LOG1="$WORKDIR/run1.log"
echo "-- run 1 (cold) ... installs packages, this can take a few minutes --"
bash "$BOOTSTRAP_SH" "$REPOS_FILE" "$ROOT" > "$LOG1" 2>&1
RC1=$?
if [ "$RC1" -eq 0 ]; then
  pass "run 1 exit code" "exit 0"
else
  # Outcome checks below are authoritative; surface the tail for debugging.
  warn "run 1 exit code" "exit $RC1 (see tail; outcome checks below are authoritative)"
  echo "   --- run1.log tail ---"
  tail -n 25 "$LOG1" | sed 's/^/   /'
fi

# macOS: brew installs to /opt/homebrew (Apple silicon) / /usr/local (Intel), off the default non-login
# PATH -- source brew so the checks below see brew-installed tools (bootstrap persists this to ~/.zprofile).
for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)" 2>/dev/null; done

# ---- required tools ----------------------------------------------------------
if command -v python3 >/dev/null 2>&1; then
  pass "required: python3" "$(ver python3 --version)"
else
  fail "required: python3" "not found after bootstrap"
fi

if command -v git >/dev/null 2>&1; then
  pass "required: git" "$(ver git --version)"
else
  fail "required: git" "not found after bootstrap"
fi

# node: accept `node` or the distro `nodejs` alias
if command -v node >/dev/null 2>&1; then
  pass "required: node" "$(ver node --version)"
elif command -v nodejs >/dev/null 2>&1; then
  pass "required: node" "$(ver nodejs --version) (as nodejs)"
else
  fail "required: node" "not found after bootstrap"
fi

# ---- optional tools (warn, never fail) ---------------------------------------
opt_check() { # <binary> <label> <version-cmd...>
  local bin="$1" label="$2"
  shift 2
  if command -v "$bin" >/dev/null 2>&1; then
    pass "optional: $label" "$("$@" 2>&1 | head -n 1)"
  else
    warn "optional: $label" "absent (CI may lack it)"
  fi
}
opt_check gh       gh       gh --version
opt_check glab     glab     glab --version
opt_check gitleaks gitleaks gitleaks version
opt_check pandoc   pandoc   pandoc --version
opt_check rg       ripgrep  rg --version
opt_check uv       uv       uv --version
opt_check claude   claude   claude --version

# ---- repo cloned -------------------------------------------------------------
if [ -d "$ROOT/$REPO_NAME/.git" ]; then
  pass "repo cloned" "$ROOT/$REPO_NAME"
elif [ -d "$ROOT/$REPO_NAME" ]; then
  warn "repo cloned" "$ROOT/$REPO_NAME exists but has no .git"
else
  fail "repo cloned" "missing $ROOT/$REPO_NAME"
fi

# ---- run 2 (warm / idempotent) -----------------------------------------------
LOG2="$WORKDIR/run2.log"
echo "-- run 2 (warm / idempotent) --"
bash "$BOOTSTRAP_SH" "$REPOS_FILE" "$ROOT" > "$LOG2" 2>&1
RC2=$?
if [ "$RC2" -eq 0 ]; then
  pass "run 2 exit code" "exit 0 (idempotent)"
else
  fail "run 2 exit code" "exit $RC2 (expected 0)"
  echo "   --- run2.log tail ---"
  tail -n 25 "$LOG2" | sed 's/^/   /'
fi

# bootstrap.sh prints "  ok  <name>" only for already-cloned repos -- tool installs
# use a silent have()-short-circuit (no "ok" line). So the repo-skip line is the
# authoritative idempotency signal for the .sh path.
if grep -Eq "ok[[:space:]]+$REPO_NAME" "$LOG2"; then
  pass "idempotent ok-path" "'ok  $REPO_NAME' present in run 2"
else
  fail "idempotent ok-path" "no 'ok  $REPO_NAME' line in run 2 output"
fi

if grep -Eq "cloning[[:space:]]+$REPO_NAME" "$LOG2"; then
  fail "repo not re-cloned" "run 2 re-cloned (saw 'cloning $REPO_NAME')"
else
  pass "repo not re-cloned" "no re-clone in run 2"
fi

# ---- results table -----------------------------------------------------------
echo
printf '%-6s  %-26s  %s\n' "STATUS" "CHECK" "DETAIL"
printf '%-6s  %-26s  %s\n' "------" "--------------------------" "------"
P=0; F=0; W=0
for row in "${ROWS[@]}"; do
  st="${row%%|*}"; rest="${row#*|}"; nm="${rest%%|*}"; dt="${rest#*|}"
  printf '%-6s  %-26s  %s\n' "$st" "$nm" "$dt"
  case "$st" in
    PASS) P=$((P + 1)) ;;
    FAIL) F=$((F + 1)) ;;
    WARN) W=$((W + 1)) ;;
  esac
done
echo
echo "Summary: $P passed, $F failed, $W warnings."

if [ "$HARD_FAIL" -gt 0 ]; then
  echo "RESULT: FAIL"
  exit 1
fi
echo "RESULT: PASS"
exit 0
