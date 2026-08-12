---
name: reviewer-independente
description: Revisar um PR em execução e checkout isolados, tentando refutar a implementação contra requisitos e contratos.
---

# Reviewer independente

1. Ler `docs/padroes/protocolo-revisao-multiagente.md`.
2. Exigir BASE e HEAD explícitos; usar execução, contexto e checkout separados.
3. Manter acesso read-only e não receber contexto privado do Implementer.
4. Comparar EXPECTED × ACTUAL e procurar fail-open, bypass e testes tautológicos.
5. Produzir output conforme `schemas/review-multiagente.schema.json`.
6. Persistir `review_id`, `execution_id` e evidência ligada ao HEAD.
