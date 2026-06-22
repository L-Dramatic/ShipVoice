param(
    [string]$EnvFile = "configs\runtime.real.env",
    [string]$SampleId = "A001",
    [int]$Port = 8026
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Invoke-ShipVoiceStep {
    param(
        [string]$Name,
        [string[]]$Command
    )
    Write-Host ""
    Write-Host "==> $Name" -ForegroundColor Cyan
    Write-Host ($Command -join " ")
    $exe = $Command[0]
    $args = @()
    if ($Command.Count -gt 1) {
        $args = $Command[1..($Command.Count - 1)]
    }
    & $exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Invoke-ShipVoiceStep "Real-only source gate" @("python", "scripts\validate_real_only.py")

Invoke-ShipVoiceStep "ShipVoice LoRA real chain check" @(
    "python",
    "scripts\check_real_service_chain.py",
    "--env-file",
    $EnvFile,
    "--sample-id",
    $SampleId,
    "--require-lora"
)

Invoke-ShipVoiceStep "Full project validation with live services" @(
    "python",
    "scripts\validate_project.py",
    "--quick",
    "--with-services",
    "--env-file",
    $EnvFile
)

Invoke-ShipVoiceStep "Rebuild acceptance report" @("python", "scripts\build_acceptance_report.py")
Invoke-ShipVoiceStep "Rebuild evaluation dashboard" @("python", "scripts\build_evaluation_dashboard.py")
Invoke-ShipVoiceStep "Final real-only gate" @("python", "scripts\validate_real_only.py")

Write-Host ""
Write-Host "ShipVoice LoRA final validation finished." -ForegroundColor Green
Write-Host "App command:"
Write-Host "python run_app.py --env-file $EnvFile --port $Port"
Write-Host "Evidence:"
Write-Host "results\real_chain_smoke.json"
Write-Host "results\project_acceptance_report.md"
Write-Host "deliverables\ShipVoice_Evaluation_Dashboard.html"
