# ADR — Architecture Dynamic Boundary Separation V2

## Estado

ACEITA por decisão humana `ARCHITECTURE_DYNAMIC_BOUNDARY_SEPARATION_V2`.

`GENERAL_DYNAMIC_SEMANTIC_ENUMERATION = EXHAUSTED`.

## Decisão

`ARCHITECTURE_ANALYZER_V1` prova somente arquitetura estrutural determinística:
inventário do Git tree exato, paths e ownership canônicos, imports estáticos,
edges, direção de dependências, imports first-party ordinários não resolvidos,
SCCs, dívida arquitetural exata, policy/config, binding base/HEAD e integridade
do próprio gate.

Aquisição/importação/execução dinâmica, reflexão, loaders, import hooks e aliases
de capacidades sensíveis pertencem exclusivamente a
`CAPABILITY_ACQUISITION_BOUNDARY_V1`, `RESTRICTED_SAFE_PYTHON_SUBSET_V1` e ao
futuro `CAPABILITY_ANALYZER_V1`. A policy default desse boundary é `DENY`.

`CODE_UNDER_REVIEW_CANNOT_CONTROL_ITS_JUDGE = TRUE`: esta separação não altera
o executor protegido, checkout candidato exato, pins, identidade base/HEAD ou
comportamento fail-closed do workflow.

## Transferência dos findings do HEAD 9a7815a

Os quatro P1 foram classificados como `DYNAMIC_CAPABILITY_MATERIAL` e estão
preservados em `config/architecture-capability-transfers-v2.json`. Transferência
não é resolução: cada item permanece aberto até um `CAPABILITY_ANALYZER_V1`
bloqueante detectar seus reproducers no HEAD exato, com CI e revisões frescas.
Não há whitelist, suppression ou exceção de pacote.

