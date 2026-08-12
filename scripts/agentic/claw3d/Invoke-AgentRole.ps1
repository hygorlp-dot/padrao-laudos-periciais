param(
    [Parameter(Mandatory=$true)][ValidateSet('implementer','researcher','reviewer','auditor','claude')][string]$Role,
    [Parameter(Mandatory=$true,ValueFromRemainingArguments=$true)][string[]]$Command,
    [string]$WorkingDirectory = (Get-Location).Path,
    [int]$Port = 8787
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
if ($env:CLAW3D_LIVE_PRESENCE_ENABLED -ne '1') {
    if ($Command.Count -eq 1) { & $Command[0] }
    else { & $Command[0] $Command[1..($Command.Count - 1)] }
    exit $LASTEXITCODE
}
try {
    & (Join-Path $PSScriptRoot 'Start-Claw3DAgentBridge.ps1') -Port $Port | Out-Null
} catch {
    Write-Warning 'Claw3D bridge unavailable; managed process will continue.'
}
Push-Location $root
try {
    python -m scripts.agentic.claw3d.cli run $Role --cwd $WorkingDirectory -- $Command
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
