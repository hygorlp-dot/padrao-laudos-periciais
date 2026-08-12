# Protocolo Claw3D Live Agent Presence

## Regra aprovada

Claw3D é exclusivamente uma camada local de observabilidade e visualização.
Não possui autoridade de domínio, orquestração, safety ou merge.

`CLAW3D_IS_NON_AUTHORITATIVE = TRUE`

`CLAW3D_FAILURE = NON_BLOCKING`

O snapshot público contém somente identificador, nome, estado operacional e
timestamp dos cinco papéis. Estados são derivados de eventos reais:
`idle`, `working`, `meeting` e `error`. Finding técnico é resultado válido e
não representa erro operacional.

O bridge usa `127.0.0.1:8787`, estado atômico local e diretório compartilhado
explicitamente por `CLAW3D_AGENT_STATE_DIR`. `CLAW3D_AGENT_BRIDGE_URL` tem
default `http://127.0.0.1:8787`. Falha de bridge é diagnosticada localmente e
nunca propagada ao Core.

## Operação local

```powershell
$env:CLAW3D_LIVE_PRESENCE_ENABLED='1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\agentic\claw3d\Start-Claw3DAgentBridge.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\agentic\claw3d\Get-Claw3DAgentState.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\agentic\claw3d\Stop-Claw3DAgentBridge.ps1
```

No Claw3D: habilitar o segundo escritório, selecionar a fonte remota compatível
e apontar a presença para `http://127.0.0.1:8787/presence`, sem token. Se a
versão instalada exigir outro contrato de runtime, usar adapter separado;
nunca alterar upstream nem promover o estado visual a fonte autoritativa.
