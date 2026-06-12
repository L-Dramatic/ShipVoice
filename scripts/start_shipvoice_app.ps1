param(
  [ValidateSet("mock", "real")]
  [string]$Mode = "mock",
  [string]$EnvFile = "",
  [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not $EnvFile) {
  if ($Mode -eq "real") {
    $EnvFile = Join-Path $Root "configs\runtime.real.env"
  } else {
    $EnvFile = Join-Path $Root "configs\runtime.mock.env"
  }
}

if (-not (Test-Path $EnvFile)) {
  throw "Env file not found: $EnvFile"
}

$python = (Get-Command python).Source
$args = @("run_app.py", "--env-file", $EnvFile)
if ($Port -gt 0) {
  $args += @("--port", "$Port")
}

Write-Host "Starting ShipVoice with env file: $EnvFile"
& $python @args
