---
name: research-ranking
description: Pesquisar alternativas técnicas em fontes primárias e produzir ranking auditável sem chain-of-thought.
---

# Research e ranking

1. Ler `docs/padroes/protocolo-pesquisa-ranking.md` integralmente.
2. Operar em execução separada quando a decisão for material.
3. Para dependência Python material, aplicar `PYTHON_DEPENDENCY_DISCOVERY_V1 = TRUE`:
   necessidade, discovery, candidatos, validação primária, segurança/licença,
   comparação específica do repositório, ranking, recomendação e challenge independente.
4. Tratar catálogos apenas como discovery. Preservar:
   `CATALOG_ENTRY != APPROVAL`, `POPULARITY != QUALITY`,
   `STAR_COUNT != SECURITY` e
   `DISCOVERY_SOURCE != PRIMARY_TECHNICAL_AUTHORITY`.
5. Validar fatos técnicos em documentação oficial, upstream, PyPI e releases.
   `OFFICIAL_DOCS_AND_UPSTREAM_ARE_PRIMARY_FOR_TECHNICAL_FACTS`.
6. Falhar fechado na adoção enquanto não houver licença, segurança,
   compatibilidade Windows e impacto de packaging:
   `NO_DEPENDENCY_ADOPTION_WITHOUT_LICENSE_CHECK`,
   `NO_DEPENDENCY_ADOPTION_WITHOUT_SECURITY_CHECK`,
   `NO_DEPENDENCY_ADOPTION_WITHOUT_WINDOWS_COMPATIBILITY_CHECK` e
   `NO_DEPENDENCY_ADOPTION_WITHOUT_PACKAGING_IMPACT_CHECK`.
7. Não introduzir Go para aproveitar catálogo: `NO_GO_JUST_TO_USE_AWESOME_GO`.
8. Comparar normalmente ao menos três candidatos reais; registrar por que o
   conjunto é menor quando houver poucas opções críveis ou solução canônica.
9. Persistir apenas evidências, síntese, ranking e recomendação auditáveis, sem
   chain-of-thought. `RESEARCH_EVIDENCE_MUST_BE_IDENTIFIABLE = TRUE`,
   `RANKING_MUST_BE_REPRODUCIBLE = TRUE` e
   `MATERIAL_RECOMMENDATION_MUST_BE_REPOSITORY_SPECIFIC = TRUE`.
