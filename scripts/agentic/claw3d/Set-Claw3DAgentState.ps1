param(
    [Parameter(Mandatory=$true)][ValidateSet('implementer','researcher','reviewer','auditor','claude')][string]$AgentId,
    [Parameter(Mandatory=$true)][ValidateSet('idle','error')][string]$State
)
try { python -m scripts.agentic.claw3d.cli set $AgentId $State | Out-Null; Write-Output "$AgentId -> $($State.ToUpperInvariant())" }
catch { Write-Output 'Presence update failed (workflow remains unaffected).'; exit 0 }
