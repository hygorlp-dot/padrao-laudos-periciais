# ADR — PROPOSAL_NOT_EFFECTIVE_WITHOUT_DECISION

## Status

APROVADA.

## Contexto

Uma proposta produzida por IA é conteúdo auxiliar auditável, não decisão do
domínio. Promovê-la automaticamente poderia alterar estado material sem uma
fonte ou decisão autorizada.

## Decisão

A resolução efetiva segue exclusivamente:

`PROFESSIONAL_OVERRIDE > ENGINE_DECISION > SOURCE_VALUE`.

`AI_PROPOSAL` pode ser armazenada e consultada por `pending_proposals()`, mas
não é valor efetivo por si só. Sem fonte ou decisão, `effective()` falha
fechado. Uma decisão posterior não apaga o histórico da proposta.

## Consequências

- futuras integrações de IA devem produzir propostas, nunca decisões;
- decisões do motor e overrides profissionais permanecem explícitos;
- rollback anterior à decisão retorna à fonte, sem promover proposta;
- o histórico continua append-only e profundamente imutável.
