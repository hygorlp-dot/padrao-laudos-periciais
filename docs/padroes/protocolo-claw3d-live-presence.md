# Protocolo Claw3D Live Agent Presence

## Regra aprovada

Claw3D é exclusivamente uma camada local de observabilidade e visualização.
Não possui autoridade de domínio, orquestração, safety ou merge.

`CLAW3D_IS_NON_AUTHORITATIVE = TRUE`

`CLAW3D_FAILURE = NON_BLOCKING`

O modo desta integração é `REMOTE_CLAW3D_PRESENCE_ENDPOINT`. O snapshot público
é reconstruído por whitelist first-party e contém somente identificador, nome,
estado operacional e timestamp dos cinco papéis. `workspaceId` é sempre a
constante `padrao-laudos-periciais`; nenhum valor persistido ou recebido é
refletido. Campos e agentes desconhecidos são descartados.

Estados permitidos são `idle`, `working`, `meeting` e `error`. Finding técnico
é resultado válido e não representa erro operacional.

O bridge usa `127.0.0.1:8787`, estado atômico local e diretório compartilhado
por `CLAW3D_AGENT_STATE_DIR`. Falha do bridge é diagnosticada localmente e
nunca propagada ao Core ou ao exit code do processo observado.

## Operação local

```powershell
$env:CLAW3D_LIVE_PRESENCE_ENABLED='1'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\agentic\claw3d\Start-Claw3DAgentBridge.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\agentic\claw3d\Get-Claw3DAgentState.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\agentic\claw3d\Stop-Claw3DAgentBridge.ps1
```

No Claw3D: habilitar o segundo escritório, selecionar `Remote Claw3D presence
endpoint` e usar `http://127.0.0.1:8787/presence`. O alias
`/api/office/presence` também é aceito. `/state`, `/registry` e
`/v1/chat/completions` pertencem ao custom runtime seam e estão fora desta V1.

## Execução gerenciada

Presença `working` somente é publicada para subprocessos reais iniciados pelo
`ManagedAgentRunner`. Cada execução possui lease própria, PID quando disponível,
horários, worktree, HEAD opcional e exit code internos. Esses dados não são
expostos pelo endpoint. Duas execuções do mesmo papel coexistem sem uma encerrar
a outra.

Threads e processos não gerenciados não são inferidos e aparecem `idle`. CPU,
Git, UI, nomes de worktree e arquivos alterados nunca fabricam atividade.

```powershell
$env:CLAW3D_LIVE_PRESENCE_ENABLED='1'
.\scripts\agentic\claw3d\Invoke-AgentRole.ps1 -Role reviewer `
    -Command @('python', '-c', 'print("READY")')
```

O wrapper inicia o bridge quando habilitado e devolve o exit code real. O
adapter Claude faz uma única tentativa: rate limit é erro operacional, sem loop
automático de retry.

## Capacidade local observada

Em 2026-08-12, a instalação local reportou `codex-cli 0.147.0-alpha.6.5` e
ofereceu `codex exec` não interativo. A detecção é fail-closed e não envia dados:

```powershell
python -m scripts.agentic.claw3d.cli codex-capability
```
