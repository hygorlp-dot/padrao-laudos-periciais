param([int]$Port = 8787, [int]$TimeoutSeconds = 8)
$ErrorActionPreference = 'Stop'
if ($env:CLAW3D_LIVE_PRESENCE_ENABLED -ne '1') {
    Write-Output 'Claw3D live presence is disabled. Set CLAW3D_LIVE_PRESENCE_ENABLED=1 to enable.'
    exit 0
}
$mutex = [Threading.Mutex]::new($false, 'Local\padrao-laudos-claw3d-lifecycle')
$acquired = $false
try {
    $acquired = $mutex.WaitOne([TimeSpan]::FromSeconds($TimeoutSeconds))
    if (-not $acquired) { throw 'Timed out waiting for the Claw3D startup lock.' }
    $runtime = if ($env:CLAW3D_AGENT_STATE_DIR) { $env:CLAW3D_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'padrao-laudos-periciais\claw3d' }
    if (-not [IO.Path]::IsPathRooted($runtime)) { throw 'CLAW3D_AGENT_STATE_DIR must be absolute.' }
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $pidFile = Join-Path $runtime 'bridge.pid'
    if (Test-Path -LiteralPath $pidFile) {
        $recorded = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        if ([int]$recorded.port -ne $Port) {
            throw "A managed Claw3D bridge is already registered on port $($recorded.port); refusing a second instance."
        }
    }

    $portOccupied = $false
    $client = [Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.ConnectAsync('127.0.0.1', $Port)
        $portOccupied = $connect.Wait(300) -and $client.Connected
    } catch { $portOccupied = $false } finally { $client.Dispose() }
    if ($portOccupied) {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
        $presence = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/presence" -TimeoutSec 1
        if ($health.status -eq 'ok' -and $presence.workspaceId -eq 'padrao-laudos-periciais') {
            if (-not (Test-Path -LiteralPath $pidFile)) { throw 'First-party Claw3D orphan bridge detected; PID metadata is missing.' }
            $identity = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
            if ([int]$health.processId -ne [int]$identity.pid -or $health.instanceToken -ne $identity.instanceToken) {
                throw 'Bridge identity does not match PID metadata.'
            }
            Write-Output "Claw3D bridge already ready on 127.0.0.1:$Port"
            exit 0
        }
        throw 'Port responds but Claw3D readiness is not proven.'
    }

    $root = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
    $instanceToken = [Guid]::NewGuid().ToString('N')
    $process = Start-Process -FilePath 'python' -ArgumentList @('-m','scripts.agentic.claw3d.bridge','--host','127.0.0.1','--port',"$Port",'--instance-token',$instanceToken) -WorkingDirectory $root -WindowStyle Hidden -PassThru
    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
            $presence = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/presence" -TimeoutSec 1
            $ready = $health.status -eq 'ok' -and [int]$health.processId -eq $process.Id -and
                $health.instanceToken -eq $instanceToken -and $presence.workspaceId -eq 'padrao-laudos-periciais'
            if ($ready) { break }
        } catch { }
        Start-Sleep -Milliseconds 100
    }
    if (-not $ready) {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue; $process.WaitForExit(5000) | Out-Null }
        Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
        throw 'Claw3D bridge failed verified readiness.'
    }
    $temporaryPid = Join-Path $runtime ("bridge-{0}.tmp" -f $instanceToken)
    @{ pid=$process.Id; module='scripts.agentic.claw3d.bridge'; port=$Port; instanceToken=$instanceToken } |
        ConvertTo-Json -Compress | Set-Content -LiteralPath $temporaryPid -Encoding ascii
    Move-Item -LiteralPath $temporaryPid -Destination $pidFile -Force
    Write-Output "Claw3D bridge ready on http://127.0.0.1:$Port/presence"
} finally {
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
