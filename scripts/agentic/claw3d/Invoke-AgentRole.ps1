param(
    [Parameter(Mandatory=$true)][ValidateSet('implementer','researcher','reviewer','auditor','claude')][string]$Role,
    [Parameter(Mandatory=$true,ValueFromRemainingArguments=$true)][string[]]$Command,
    [string]$WorkingDirectory = (Get-Location).Path,
    [int]$Port = 8787
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
if ($env:CLAW3D_LIVE_PRESENCE_ENABLED -eq '1') {
    & (Join-Path $PSScriptRoot 'Start-Claw3DAgentBridge.ps1') -Port $Port | Out-Null
}
Push-Location $root
try {
    python -m scripts.agentic.claw3d.cli run $Role --cwd $WorkingDirectory -- @Command
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
