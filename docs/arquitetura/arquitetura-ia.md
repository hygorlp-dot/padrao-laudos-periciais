# Arquitetura de IA

## Regra aprovada

IA é auxiliar. `AI_PROPOSAL` permanece auditável, mas nunca se torna valor
efetivo sem `ENGINE_DECISION` ou `PROFESSIONAL_OVERRIDE`. Egress é negado por
padrão. Nenhum AI Gateway funcional integra esta etapa.

O Claude atua exclusivamente como revisor externo de diversidade quando o
gate determinístico o exigir e somente sobre HEAD final estável e contexto
first-party sanitizado.
