param([int]$Port = 8787)
$ErrorActionPreference = 'Stop'
if ($env:CLAW3D_LIVE_PRESENCE_ENABLED -ne '1') {
    Write-Output 'Claw3D live presence is disabled. Set CLAW3D_LIVE_PRESENCE_ENABLED=1 to enable.'
    exit 0
}
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
    if ($health.status -eq 'ok') { Write-Output "Claw3D bridge already running on 127.0.0.1:$Port"; exit 0 }
} catch { }
$root = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$process = Start-Process -FilePath 'python' -ArgumentList @('-m','scripts.agentic.claw3d.bridge','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $root -WindowStyle Hidden -PassThru
$runtime = if ($env:CLAW3D_AGENT_STATE_DIR) { $env:CLAW3D_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'padrao-laudos-periciais\claw3d' }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
Set-Content -LiteralPath (Join-Path $runtime 'bridge.pid') -Value $process.Id -Encoding ascii
Write-Output "Claw3D bridge started on http://127.0.0.1:$Port/presence"
