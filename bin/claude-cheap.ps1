# claude-cheap (Windows) -- the CHEAP LANE of the two-lane model handoff.
# See docs/two-lane-model-handoff.md. Runs `claude` against a SELF-HOSTED, Anthropic-/v1/messages-
# compatible endpoint for batch/mechanical work; your default `claude` is untouched.
#
# Config (env, or a file at $env:CLAUDE_CHEAP_ENV / ~/.config/neurokeeper/cheap-lane.env, KEY=VALUE):
#   CLAUDE_CHEAP_BASE_URL [required] | CLAUDE_CHEAP_MODEL [optional] | CLAUDE_CHEAP_TOKEN [default: local]
#
# WARNING (billing): exporting ANTHROPIC_BASE_URL + a token routes THIS invocation off your subscription
# (intended: it goes to YOUR box). WARNING (data egress): everything in this lane goes to your endpoint --
# keep it on a host you control for sensitive content.
$ErrorActionPreference = "Stop"

$cfg = if ($env:CLAUDE_CHEAP_ENV) { $env:CLAUDE_CHEAP_ENV } else { "$HOME/.config/neurokeeper/cheap-lane.env" }
$allow = @("CLAUDE_CHEAP_BASE_URL", "CLAUDE_CHEAP_MODEL", "CLAUDE_CHEAP_TOKEN")
if (Test-Path $cfg) {
  Get-Content $cfg | Where-Object { $_ -and -not $_.StartsWith("#") -and $_.Contains("=") } | ForEach-Object {
    $k, $v = $_.Split("=", 2); $k = $k.Trim()
    if ($allow -contains $k) { Set-Item -Path "Env:$k" -Value $v.Trim() }  # ignore any other key (no env injection)
  }
}

if (-not $env:CLAUDE_CHEAP_BASE_URL) {
  Write-Error "claude-cheap: set CLAUDE_CHEAP_BASE_URL (your self-hosted /v1/messages endpoint) -- via env or $cfg. See docs/two-lane-model-handoff.md"
  exit 2
}
if ($env:CLAUDE_CHEAP_BASE_URL -notmatch '^https?://') {
  Write-Error "claude-cheap: CLAUDE_CHEAP_BASE_URL must be an http(s) URL (got: $($env:CLAUDE_CHEAP_BASE_URL))"
  exit 2
}

$env:ANTHROPIC_BASE_URL = $env:CLAUDE_CHEAP_BASE_URL
$env:ANTHROPIC_AUTH_TOKEN = if ($env:CLAUDE_CHEAP_TOKEN) { $env:CLAUDE_CHEAP_TOKEN } else { "local" }
if ($env:CLAUDE_CHEAP_MODEL) { $env:ANTHROPIC_MODEL = $env:CLAUDE_CHEAP_MODEL }

& claude @args
exit $LASTEXITCODE
