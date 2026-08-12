param(
    [Parameter(Mandatory=$true)][ValidateSet('implementer','researcher','reviewer','auditor','claude')][string]$Role,
    [Parameter(Mandatory=$true)][string]$Executable,
    [string[]]$ArgumentList = @(),
    [string]$WorkingDirectory = (Get-Location).Path,
    [int]$Port = 8787
)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
if ($env:CLAW3D_LIVE_PRESENCE_ENABLED -ne '1') {
    & $Executable @ArgumentList
    exit $LASTEXITCODE
}
try {
    & (Join-Path $PSScriptRoot 'Start-Claw3DAgentBridge.ps1') -Port $Port | Out-Null
} catch {
    Write-Warning 'Claw3D bridge unavailable; managed process will continue.'
}
Push-Location $root
try {
    $commandParts = @($Executable) + @($ArgumentList)
    $commandJson = ConvertTo-Json -InputObject $commandParts -Compress
    $commandBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($commandJson))
    $cliArgs = @('-m','scripts.agentic.claw3d.cli','run',$Role,'--cwd',$WorkingDirectory,'--command-base64',$commandBase64)
    & python @cliArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
