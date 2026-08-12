param([string]$BridgeUrl = $(if ($env:CLAW3D_AGENT_BRIDGE_URL) { $env:CLAW3D_AGENT_BRIDGE_URL } else { 'http://127.0.0.1:8787' }))
try {
    $snapshot = Invoke-RestMethod -Uri "$BridgeUrl/presence" -TimeoutSec 2
    foreach ($agent in $snapshot.agents) { '{0,-25} {1}' -f $agent.name, $agent.state.ToUpperInvariant() }
} catch {
    Write-Output 'Claw3D bridge unavailable (workflow remains unaffected).'
    exit 0
}
