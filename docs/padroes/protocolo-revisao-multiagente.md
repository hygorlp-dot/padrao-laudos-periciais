# Protocolo de revisão multiagente

## Regra aprovada

Implementer, PR Reviewer e Systemic Auditor são execuções distintas. O Reviewer
compara EXPECTED × ACTUAL no diff; o Auditor examina a cadeia vertical afetada
e caminhos alternativos. Ambos são read-only e vinculados ao HEAD exato.

`INDEPENDENT_REVIEW_MUST_BE_PROVEN = TRUE`. Mesma execução, contexto, worktree,
permissão de escrita, contexto privado, HEAD stale ou evidência ausente bloqueiam
o merge.
