#!/usr/bin/env pwsh
#Requires -Version 7
<#
  neurokeeper -- cross-platform CI/test for bootstrap.ps1 (Windows).

  NON-INTERACTIVE. Designed for a CLEAN / DISPOSABLE environment: this exercises
  bootstrap.ps1 for real, which installs system packages via winget and `npm i -g`.
  NEVER run it on a daily-driver box. See README.md.

  Checks (mirror of test-bootstrap.sh):
    1. SYNTHETIC repos file (one tiny PUBLIC repo) in a temp dir.
    2. Run  bootstrap.ps1 -ReposFile <file> -Root <temp-root>.
    3. REQUIRED tools present + version: python, git, node (HARD fail).
       OPTIONAL (warn only): gh, glab, gitleaks, pandoc, ripgrep (rg), uv, claude.
    4. The synthetic repo was cloned into <temp-root>.
    5. A SECOND run exits 0 and takes the idempotent "ok" path (tools + repo).
    6. bootstrap.ps1 line-ending sanity (CRLF per .gitattributes).
    7. PASS/FAIL table; nonzero exit on any HARD failure.

  Usage:  pwsh -NoProfile -File bootstrap/test/test-bootstrap.ps1
#>
$ErrorActionPreference = 'Continue'

# ---- locate scripts ----------------------------------------------------------
$Here         = Split-Path -Parent $PSCommandPath
$BootstrapDir = Split-Path -Parent $Here
$BootstrapPs1 = Join-Path $BootstrapDir 'bootstrap.ps1'

# ---- result table ------------------------------------------------------------
$rows = [System.Collections.Generic.List[object]]::new()
$script:hard = 0
function Add-Row($s, $n, $d) { $rows.Add([pscustomobject]@{ Status = $s; Check = $n; Detail = $d }) | Out-Null }
function Pass($n, $d) { Add-Row 'PASS' $n $d }
function Fail($n, $d) { Add-Row 'FAIL' $n $d; $script:hard++ }
function Warn($n, $d) { Add-Row 'WARN' $n $d }
function Have($n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
function Ver($exe, [string[]]$cmdArgs) {
  try { [string]((& $exe @cmdArgs 2>&1 | Select-Object -First 1)) } catch { 'version-error' }
}

# ---- temp workspace ----------------------------------------------------------
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("neurokeeper-test-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $work | Out-Null
$reposFile = Join-Path $work 'repos.txt'
$root      = Join-Path $work 'root'
$repoUrl   = 'https://github.com/octocat/Hello-World.git'   # tiny PUBLIC throwaway repo
$repoName  = 'Hello-World'

@(
  '# synthetic test repos file -- public, tiny, throwaway (no private URLs)',
  $repoUrl
) | Set-Content -Path $reposFile -Encoding utf8

Write-Host "== neurokeeper bootstrap.ps1 test =="
Write-Host "  bootstrap : $BootstrapPs1"
Write-Host "  workdir   : $work"
Write-Host "  repos     : $reposFile"
Write-Host "  root      : $root"
Write-Host ""

try {
  # ---- pre-flight: bootstrap.ps1 exists --------------------------------------
  if (Test-Path $BootstrapPs1) { Pass 'bootstrap.ps1 present' $BootstrapPs1 }
  else { Fail 'bootstrap.ps1 present' "missing: $BootstrapPs1" }

  # ---- line-ending sanity (repo convention = CRLF for .ps1) ------------------
  if (Test-Path $BootstrapPs1) {
    $bytes = [System.IO.File]::ReadAllBytes($BootstrapPs1)
    $cr = 0; $lf = 0
    foreach ($b in $bytes) { if ($b -eq 13) { $cr++ } elseif ($b -eq 10) { $lf++ } }
    if ($cr -gt 0) { Pass 'bootstrap.ps1 CRLF endings' "$cr CR / $lf LF (CRLF per .gitattributes)" }
    else { Warn 'bootstrap.ps1 CRLF endings' '0 CR (checked out LF; pwsh tolerates, repo convention is CRLF)' }
  }

  # ---- run 1 (cold) ----------------------------------------------------------
  $log1 = Join-Path $work 'run1.log'
  Write-Host "-- run 1 (cold) ... installs packages, this can take a few minutes --"
  & pwsh -NoProfile -File $BootstrapPs1 -ReposFile $reposFile -Root $root *> $log1
  $rc1 = $LASTEXITCODE
  if ($rc1 -eq 0) { Pass 'run 1 exit code' 'exit 0' }
  else {
    Warn 'run 1 exit code' "exit $rc1 (outcome checks below are authoritative)"
    if (Test-Path $log1) {
      Write-Host "   --- run1.log tail ---"
      Get-Content $log1 -Tail 25 | ForEach-Object { Write-Host "   $_" }
    }
  }

  # ---- required tools --------------------------------------------------------
  if (Have python) { Pass 'required: python' (Ver 'python' @('--version')) } else { Fail 'required: python' 'not found after bootstrap' }
  if (Have git)    { Pass 'required: git'    (Ver 'git'    @('--version')) } else { Fail 'required: git'    'not found after bootstrap' }
  if (Have node)   { Pass 'required: node'   (Ver 'node'   @('--version')) } else { Fail 'required: node'   'not found after bootstrap' }

  # ---- optional tools (warn, never fail) -------------------------------------
  $opt = @(
    @{ bin = 'gh';       label = 'gh';       cmdArgs = @('--version') },
    @{ bin = 'glab';     label = 'glab';     cmdArgs = @('--version') },
    @{ bin = 'gitleaks'; label = 'gitleaks'; cmdArgs = @('version')   },
    @{ bin = 'pandoc';   label = 'pandoc';   cmdArgs = @('--version') },
    @{ bin = 'rg';       label = 'ripgrep';  cmdArgs = @('--version') },
    @{ bin = 'uv';       label = 'uv';       cmdArgs = @('--version') },
    @{ bin = 'claude';   label = 'claude';   cmdArgs = @('--version') }
  )
  foreach ($o in $opt) {
    if (Have $o.bin) { Pass "optional: $($o.label)" (Ver $o.bin $o.cmdArgs) }
    else { Warn "optional: $($o.label)" 'absent (CI may lack it)' }
  }

  # ---- repo cloned -----------------------------------------------------------
  $repoDir = Join-Path $root $repoName
  if (Test-Path (Join-Path $repoDir '.git')) { Pass 'repo cloned' $repoDir }
  elseif (Test-Path $repoDir) { Warn 'repo cloned' "$repoDir exists but has no .git" }
  else { Fail 'repo cloned' "missing $repoDir" }

  # ---- run 2 (warm / idempotent) ---------------------------------------------
  $log2 = Join-Path $work 'run2.log'
  Write-Host "-- run 2 (warm / idempotent) --"
  & pwsh -NoProfile -File $BootstrapPs1 -ReposFile $reposFile -Root $root *> $log2
  $rc2 = $LASTEXITCODE
  if ($rc2 -eq 0) { Pass 'run 2 exit code' 'exit 0 (idempotent)' }
  else {
    Fail 'run 2 exit code' "exit $rc2 (expected 0)"
    if (Test-Path $log2) {
      Write-Host "   --- run2.log tail ---"
      Get-Content $log2 -Tail 25 | ForEach-Object { Write-Host "   $_" }
    }
  }

  $out2 = if (Test-Path $log2) { Get-Content $log2 -Raw } else { '' }
  # bootstrap.ps1 prints "  ok  <name>" for already-present TOOLS and already-cloned REPOS.
  if ($out2 -match ("ok\s+" + [regex]::Escape($repoName))) { Pass 'idempotent ok-path (repo)' "'ok  $repoName' present in run 2" }
  else { Fail 'idempotent ok-path (repo)' "no 'ok  $repoName' line in run 2 output" }

  if ($out2 -match 'ok\s+git\b') { Pass 'idempotent ok-path (tool)' "'ok  git' present in run 2" }
  else { Warn 'idempotent ok-path (tool)' "no 'ok  git' line (tool may have been (re)installed)" }

  if ($out2 -match ("cloning\s+" + [regex]::Escape($repoName))) { Fail 'repo not re-cloned' "run 2 re-cloned (saw 'cloning $repoName')" }
  else { Pass 'repo not re-cloned' 'no re-clone in run 2' }
}
finally {
  if (Test-Path $work) { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue }
}

# ---- results table -----------------------------------------------------------
Write-Host ""
($rows | Format-Table -AutoSize Status, Check, Detail | Out-String).TrimEnd() | Write-Host
$p = ($rows | Where-Object Status -eq 'PASS').Count
$f = ($rows | Where-Object Status -eq 'FAIL').Count
$w = ($rows | Where-Object Status -eq 'WARN').Count
Write-Host ""
Write-Host "Summary: $p passed, $f failed, $w warnings."

if ($script:hard -gt 0) { Write-Host 'RESULT: FAIL'; exit 1 }
Write-Host 'RESULT: PASS'
exit 0
