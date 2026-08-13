# Constituição arquitetural do Core Pericial V1

## Autoridade e direção

O Core Pericial preserva a autoridade de domínio. A direção-alvo é
`UI/API/Infrastructure -> Application -> Core`; governança e quality inspecionam
o sistema, mas não são dependências de produção. UI, integrações e agentes nunca
promovem proposta a decisão técnica.

## Gate executável

`config/core-architecture-v1.json` é o registro canônico de ownership. Cada
módulo Python first-party em `scripts/` possui exatamente um componente. O gate
`scripts/quality/architecture_gate.py` usa AST, não importa nem executa o Core,
e bloqueia source inválido, ownership ausente/ambíguo, import first-party não
resolvido, import dinâmico não literal, direção proibida e nova aresta entre
componentes.

O grafo atual não é declarado ideal. Dependências cross-component observadas
estão enumeradas por módulo e classificadas como `POTENTIAL_VIOLATION`, com
evidência e destino de revisão. Uma exceção não é permissão por package: nova
aresta falha, exceção sem aresta fica stale e também falha. A remoção de dívida
aperta o gate; sua reintrodução exige nova decisão arquitetural.

## Estado atual e programa

O ciclo entre auditoria, motor e planejamento é dívida observada, não mudança
semântica nem gatilho automático de refatoração. Seu saneamento depende de
caracterização e dos PRs específicos de refatoração da Phase B. Esta Constituição
não altera runtime, schemas, resultados periciais ou autoridade profissional.
