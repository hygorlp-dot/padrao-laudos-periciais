# Protocolo de autonomia do agente

## Regra aprovada

`DEFAULT_ACTION = DECIDE_AND_PROCEED`

`HUMAN_ESCALATION = EXCEPTION_ONLY`

`SELF_RECOVERY = TRUE`

`FAIL_CLOSED = TRUE`

O agente resolve escolhas reversíveis e bem delimitadas com fontes e contratos
do repositório. Escala somente autoridade nova, egress privado, custo novo,
operação destrutiva sem rollback, decisão pericial, login/MFA ou divergência
material irresolúvel.

Mudança material segue reprodução → RED → causa-raiz → correção mínima →
adversariais → regressão → revisão → verificação final.
