param([int]$Port = 8787)
$ErrorActionPreference = 'Stop'
$runtime = if ($env:CLAW3D_AGENT_STATE_DIR) { $env:CLAW3D_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'padrao-laudos-periciais\claw3d' }
if (-not [IO.Path]::IsPathRooted($runtime)) { Write-Error 'CLAW3D_AGENT_STATE_DIR must be absolute.'; exit 1 }
$mutex = [Threading.Mutex]::new($false, "Local\padrao-laudos-claw3d-$Port")
$acquired = $false
try {
    $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds(8))
    if (-not $acquired) { throw 'Timed out waiting for the Claw3D lifecycle lock.' }
$pidFile = Join-Path $runtime 'bridge.pid'
if (-not (Test-Path -LiteralPath $pidFile)) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
        if ($health.status -eq 'ok') { Write-Error 'Claw3D orphan bridge detected; no process was stopped.'; exit 1 }
    } catch { if ($_.Exception.Message -like '*orphan*') { throw } }
    Write-Output 'Claw3D bridge is not running.'
    exit 0
}
$identity = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
$bridgePid = [int]$identity.pid
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $bridgePid" -ErrorAction SilentlyContinue
$healthMatches = $false
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($identity.port)/health" -TimeoutSec 1
    $presence = Invoke-RestMethod -Uri "http://127.0.0.1:$($identity.port)/presence" -TimeoutSec 1
    $healthMatches = $health.status -eq 'ok' -and $health.instanceToken -eq $identity.instanceToken -and
        [int]$health.processId -eq $bridgePid -and $presence.workspaceId -eq 'padrao-laudos-periciais'
} catch { }
if ($processInfo -and $healthMatches -and $identity.module -eq 'scripts.agentic.claw3d.bridge' -and
    $processInfo.CommandLine -like '*scripts.agentic.claw3d.bridge*') {
    $process = Get-Process -Id $bridgePid -ErrorAction SilentlyContinue
    if ($process) { Stop-Process -Id $bridgePid -ErrorAction SilentlyContinue; $process.WaitForExit(5000) | Out-Null }
} elseif ($processInfo) {
    Write-Error 'PID file does not identify the ready managed Claw3D bridge; no process was stopped.'
    exit 1
}
Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
Write-Output 'Claw3D bridge stopped.'
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
