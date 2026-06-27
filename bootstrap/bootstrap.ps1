#!/usr/bin/env pwsh
# claude-harness fresh-PC bootstrap (Windows-primary). Idempotent: skips what's already present.
# Installs the headless toolchain, then clones the repos listed in your private repos config.
# Run:  pwsh -File bootstrap.ps1 [-ReposFile path\to\repos.txt] [-Root C:\Users\<you>\Projects]
# GUI + auth + Obsidian-plugin steps are MANUAL -- see RUNBOOK.md. Does NOT touch private/sensitive content.
param(
  [string]$ReposFile = "$PSScriptRoot\repos.txt",
  [string]$Root = "$env:USERPROFILE\Projects"
)
$ErrorActionPreference = "Stop"
function Have($n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
function Winget($id) { winget install --id $id -e --accept-source-agreements --accept-package-agreements -h }

Write-Host "== 1. headless toolchain (winget) ==" -ForegroundColor Cyan
$pkgs = @{
  python="Python.Python.3.14"; git="Git.Git"; node="OpenJS.NodeJS"; gh="GitHub.cli";
  pandoc="JohnMacFarlane.Pandoc"; pwsh="Microsoft.PowerShell"; uv="astral-sh.uv"; rg="BurntSushi.ripgrep.MSVC"
}
foreach ($k in $pkgs.Keys) {
  if (Have $k) { Write-Host "  ok  $k" } else { Write-Host "  installing $k..."; Winget $pkgs[$k] }
}
# glab + gitleaks: winget id varies / not always present -> try winget then scoop
if (-not (Have glab))     { try { Winget "GLab.GLab" } catch { Write-Host "  glab: install via scoop/GH release (see manifest)" -ForegroundColor Yellow } }
if (-not (Have gitleaks)) { Write-Host "  gitleaks: scoop install gitleaks (or GH release) -- see manifest" -ForegroundColor Yellow }

Write-Host "== 2. Claude Code + python deps ==" -ForegroundColor Cyan
if (Have npm) { npm install -g "@anthropic-ai/claude-code" } else { Write-Host "  npm missing (reopen shell after Node install)" -ForegroundColor Yellow }
if (Have python) { python -m pip install --quiet --upgrade pyyaml }

Write-Host "== 3. clone repos ==" -ForegroundColor Cyan
if (-not (Test-Path $Root)) { New-Item -ItemType Directory -Force $Root | Out-Null }
if (Test-Path $ReposFile) {
  Get-Content $ReposFile | Where-Object { $_ -and -not $_.StartsWith("#") } | ForEach-Object {
    $url = $_.Trim(); $name = [IO.Path]::GetFileNameWithoutExtension($url)
    $dest = Join-Path $Root $name
    if (Test-Path $dest) { Write-Host "  ok  $name" }
    else { Write-Host "  cloning $name..."; git clone -- $url $dest }
  }
} else {
  Write-Host "  no repos file ($ReposFile) -- copy repos.example.txt -> repos.txt and fill your repo URLs" -ForegroundColor Yellow
}

Write-Host "`n== DONE (automated part). MANUAL steps remain -- see RUNBOOK.md: ==" -ForegroundColor Green
Write-Host "  - auth:  gh auth login ; glab auth login ; claude (login)"
Write-Host "  - install Obsidian (winget Obsidian.Obsidian) + community plugins (Tag Wrangler, Linter[configure!], Frontmatter Smith, Git)"
Write-Host "  - restore Claude memory: clone the memory repo into ~/.claude/projects/<env>/memory ; pull _shared/"
Write-Host "  - install this harness as a plugin: /plugin marketplace add <harness-url> ; /plugin install claude-harness"
