$runtime = if ($env:CLAW3D_AGENT_STATE_DIR) { $env:CLAW3D_AGENT_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'padrao-laudos-periciais\claw3d' }
$pidFile = Join-Path $runtime 'bridge.pid'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'Claw3D bridge is not running.'; exit 0 }
$bridgePid = [int](Get-Content -LiteralPath $pidFile -Raw)
$process = Get-Process -Id $bridgePid -ErrorAction SilentlyContinue
if ($process) { Stop-Process -Id $bridgePid -ErrorAction SilentlyContinue; $process.WaitForExit(5000) | Out-Null }
Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
Write-Output 'Claw3D bridge stopped.'
