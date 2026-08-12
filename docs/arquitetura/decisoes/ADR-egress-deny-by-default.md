# ADR — EGRESS_DENY_BY_DEFAULT

## Decisão

Toda saída de dados é bloqueada sem capability, autorização e sanitização
explícitas. `referencias/privadas/`, PII, secrets e conteúdo de caso são sempre
excluídos de pacotes de revisão externa.
