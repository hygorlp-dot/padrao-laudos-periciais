# Core Stable Baseline Candidate V1

## Identidade e finalidade

- `BASELINE_VERSION`: `V1`
- `CORE_BASE_SHA`: `8530584c82061fb35018afd6638032ba8798b105`
- `BASELINE_FINGERPRINT_SHA256`: `c832b3179c523cd97cf355b34b19a0d2ffdbe0dbd7fd60aaef0821ceefb683ef`
- `ANALYZER_VERSION`: `1.0.0`
- `BASELINE_IS_OBSERVATIONAL`: `TRUE`
- `CORE_FEATURE_FREEZE`: `TRUE`
- `CORE_RUNTIME_SEMANTICS_CHANGED`: `FALSE`
- `PERICIAL_SCHEMA_CHANGED`: `FALSE`
- `REFACTOR_PERFORMED`: `FALSE`
- `DEPENDENCIES_ADDED`: `NONE`

Esta baseline registra o Core e sua fronteira de assurance tal como existem no
SHA acima. Ela não declara a arquitetura futura, não corrige riscos observados e
não transforma métricas em gatilhos automáticos de refatoração.

## Método reproduzível

`scripts/quality/core_baseline.py` resolve um commit exato, enumera somente
blobs tracked e lê seu conteúdo pela object database do Git. A worktree, paths
absolutos, arquivos não rastreados, `referencias/privadas/`, horários, durações,
IDs de CI e UUIDs não entram no payload semântico. Paths são POSIX relativos,
listas e chaves são ordenadas, bytes são hasheados crus e a serialização é JSON
UTF-8 compacta com newline final.

O arquivo `config/core-stable-baseline-v1.sha256` é o SHA-256 da serialização
canônica do payload semântico, isto é, o JSON sem o campo
`semanticFingerprint`. O arquivo JSON completo inclui esse valor para consulta,
mas seus bytes integrais naturalmente possuem outro hash. Os três artefatos da
baseline são excluídos do manifesto para impedir autorreferência. Assim:

`SAME_SHA + SAME_TRACKED_CONTENT + SAME_BASELINE_VERSION + SAME_ANALYZER_VERSION + SAME_EVIDENCE_RECEIPT = SAME_BASELINE_FINGERPRINT`.

`baselineVersion=V1` aceita somente `analyzerVersion=1.0.0`. Resultados de
execução não são presumidos pelo analisador: são lidos do receipt
`config/core-stable-baseline-evidence-v1.json`, cujo `coreBaseSha` deve coincidir
com o commit analisado. Sem receipt, o resultado é `NOT_YET_PROVEN`.

Comando de reprodução:

```powershell
python -m scripts.quality.core_baseline `
  --sha 8530584c82061fb35018afd6638032ba8798b105 `
  --evidence config/core-stable-baseline-evidence-v1.json `
  --output config/core-stable-baseline-v1.json `
  --fingerprint config/core-stable-baseline-v1.sha256 `
  --check
```

## Inventário canônico

O manifesto possui 384 arquivos da fronteira Core + assurance:

| Categoria | Quantidade |
|---|---:|
| `CORE_RUNTIME` | 75 |
| `CORE_CONTRACT` | 23 |
| `SCHEMA` | 20 |
| `FIXTURE` | 39 |
| `TEST` | 38 |
| `INVARIANT` | 1 |
| `BOUNDARY` | 1 |
| `QUALITY_CONFIG` | 5 |
| `GOVERNANCE_RELEVANT_TO_CORE` | 182 |

Os 39 itens de categoria `FIXTURE` incluem o próprio registry; há 38 fixtures
registradas. O validador atual exercita 34 fixtures de schema, número distinto
e intencionalmente reportado no baseline comportamental.

Foram extraídos estaticamente 98 módulos Python, 349 símbolos top-level e 127
arestas de import first-party. `EXPORTED` decorre de `__all__`; na ausência dele,
`PUBLIC_BY_CONVENTION` e `INTERNAL` são heurísticas por nome, não promessa nova
de API. Dependências externas observadas em imports são `PIL`, `jsonschema`,
`pdfplumber`, `pypdf` e `referencing`; o inventário não as instala nem afirma
que cada uma é chamada em todo fluxo.

Fontes canônicas compostas, sem duplicação normativa:

- 42 invariantes de `config/core-invariants.json`;
- 23 boundaries de `config/core-boundaries.json`;
- schemas tracked e relações declaradas pelos boundaries;
- 38 fixtures do registry `tests/fixtures/core-fixtures.json`;
- testes associados aos registries e todos os `tests/test*.py` tracked;
- quality configs, workflow `core-safety`, arquitetura e governança aplicável.

## Baseline comportamental e nível da evidência

| Observação | Estado no SHA-base | Nível |
|---|---|---|
| pytest integral | 512 passed, 100 subtests | `PROVEN_BY_TEST` |
| governança | 46 passed | `PROVEN_BY_TEST` |
| schemas | 20 válidos | `PROTECTED_BY_GATE` |
| fixtures validadas | 34 | `PROTECTED_BY_GATE` |
| fixtures registradas | 38 | `DOCUMENTED_ONLY` + validação estrutural |
| `verify_core --full` | PASS | `PROTECTED_BY_GATE` |
| privacy tracked | vazio | `PROTECTED_BY_GATE` |
| property tests | `test_core_properties.py`, `test_core_properties_v2.py` | `PROVEN_BY_TEST` |
| mutações críticas históricas | registry + runner first-party | `PROTECTED_BY_GATE` |
| E2E positivo/negativo | módulos registrados no gate | `PROTECTED_BY_GATE` |
| Golden Forensic Corpus futuro | inexistente | `NOT_YET_PROVEN` |
| replay canônico | inexistente | `NOT_YET_PROVEN` |

Contagens e status acima são evidência da execução do SHA-base; durações e IDs
de CI ficam fora do fingerprint. O payload registra os arquivos e gates que
sustentam a afirmação, não inventa garantias além deles.

## Invariantes de domínio e autoridade

O inventário machine-readable preserva, sem redefinir, onde cada invariante é
declarado, seus boundaries e testes. Entre os conceitos registrados estão
`FAIL_CLOSED`, `PRODUCER_NOT_VALIDATOR`, `NO_SILENT_LOSS`,
`CORRECTION_PERSISTENCE`, `SEMANTIC_MONOTONICITY`, `IDEMPOTENCE`,
`ORDER_INVARIANCE`, fidelidades de valor/unidade/data/norma/grounding,
`NO_CERTAINTY_INFLATION`, `PROVENANCE_FIDELITY` e
`PROPOSAL_NOT_EFFECTIVE_WITHOUT_DECISION`.

O modelo observado permanece:

`SOURCE_VALUE -> AI_PROPOSAL -> ENGINE_DECISION -> PROFESSIONAL_OVERRIDE`, com
precedência efetiva `PROFESSIONAL_OVERRIDE > ENGINE_DECISION > SOURCE_VALUE`.
`AI_PROPOSAL` isolada não é efetiva. A implementação e os testes estão em
`scripts/backend_contract/revisions.py`, `tests/test_proposal_authority.py` e
`tests/test_backend_contract.py`.

## Dependência arquitetural observada

A direção alvo futura é `UI/API/Infrastructure -> Application -> Core`, mas não
é implementada neste PR.

- `ACCEPTED_CURRENT_DEPENDENCY`: `motor.executar` importa somente semântica de
  triagem e módulos first-party de evidência, causalidade, norma e auditoria;
  não possui import direto de DB, rede ou provider.
- `POTENTIAL_VIOLATION`: `gerar_delimitacao.gerar` e `gerar_plano.gerar` leem
  paths derivados do layout do repositório. É acoplamento a filesystem dentro
  de entrypoints produtores, ainda sem constituição arquitetural que permita
  classificá-lo como violação confirmada.
- `POTENTIAL_VIOLATION`: timestamps entram nos artefatos desses produtores e
  `scripts/motor_vicios/pipeline.py` gera UUID quando o caller não fornece ID.
  Isso exige normalização futura em determinismo/replay, não alteração aqui.
- `UNKNOWN`: duplicação sistemática de regra de domínio fora do Core não foi
  provada por esta análise de imports/AST; o sweep não encontrou outro caminho
  de promoção de `AI_PROPOSAL`.

Não foram observados imports diretos de DB, socket/HTTP ou provider nos três
hotspots. A baseline não afirma ausência global fora do conjunto inventariado.

## Hotspots confirmados

Métrica `decisionCountCandidate`: `1 +` nós AST de decisão, operandos booleanos
adicionais e caminhos de `try`. Ela é um sinal versionado, não complexidade
cognitiva universal nem gatilho automático.

| Entrypoint | LOC física | Statements | Decisões | Nesting | Params |
|---|---:|---:|---:|---:|---:|
| `scripts/motor_vicios/motor.py::executar` | 65 | 125 | 130 | 2 | 6 |
| `scripts/triagem_pericial/gerar_delimitacao.py::gerar` | 195 | 107 | 96 | 5 | 1 |
| `scripts/planejamento_pericial/gerar_plano.py::gerar` | 73 | 68 | 57 | 3 | 1 |

### Mapa de caracterização futura

**`motor.executar`** — entradas: processo, delimitação, plano, vistoria e
contextos opcionais; saída: análise com manifestações, hipóteses, PAT/QT,
relações, auditoria e gate; sem I/O direto. Toca evidência, causalidade, normas,
cobertura, proveniência e autoridade de override explícito. Caracterizar early
returns, permutações, evidência essencial/irrelevante, MED/FOT ambígua, normas,
QT e não mutação de inputs.

**`gerar_delimitacao.gerar`** — lê manifesto/documentos e conhecimento pelo
filesystem; produz delimitação, QTs, quesitos, alegações, conflitos,
proveniência, autoauditoria e status. Caracterizar manifesto inválido, ordem de
documentos, isolamento jurídico/técnico, ausência/conflito de conhecimento,
resolução de proveniência e normalização de `gerado_em`.

**`gerar_plano.gerar`** — lê processo/delimitação/conhecimento; produz plano de
atividades/MED/FOT/ENS/DOC, cobertura, proveniência e status. Caracterizar tipos
não suportados, perfis, ordem de QT, gatilhos lexicais, REQUIRED->PLANNED,
conflitos, hashes e separação planejado/executado.

## Registro de riscos

O JSON contém cinco riscos com evidência identificável. Resumo:

1. `HIGH/B/P1-eng`: concentração de regras em `motor.executar`, fortemente
   protegida mas de alto impacto.
2. `HIGH/C/P1-eng`: delimitação combina domínio, filesystem, proveniência,
   classificação e status.
3. `HIGH/B/P2-eng`: planejamento combina perfil, cobertura, proveniência e
   status com filesystem/tempo.
4. `MEDIUM/C/P2-eng`: tempo/UUID exigem normalização futura para replay.
5. `MEDIUM/D/P1-eng`: autoridade do Core é documentada, mas direção de camadas
   ainda não é gate mecânico.

`ENGINEERING_PRIORITY` não é severidade P0/P1. Nenhum risco foi elevado apenas
por LOC ou decisão AST, e nenhum é corrigido neste PR observacional.

## Gap matrix do programa

| Área | Estado atual | Gap | Próxima etapa |
|---|---|---|---|
| Architecture Constitution | autoridade documentada | ownership/direção incompletos | `ARCHITECTURE_CONSTITUTION_AND_GATE_V1` |
| Architecture Gate | registries + change impact | import direction não bloqueada | `ARCHITECTURE_CONSTITUTION_AND_GATE_V1` |
| Hotspot Characterization | métricas + regressões | matriz completa ausente | `HOTSPOT_CHARACTERIZATION_V1` |
| Golden Forensic Corpus | fixtures/E2E sintéticos | corpus dourado ausente | `GOLDEN_FORENSIC_CORPUS_V1` |
| Semantic Determinism | idempotência/ordem | normalização tempo/UUID incompleta | `SEMANTIC_DETERMINISM_V1` |
| Replay | sem harness canônico | identidade/reexecução pendentes | `REPLAY_V1` |
| Critical Mutation | 10 mutantes históricos | expansão futura | `CRITICAL_MUTATION_V1` |
| Fault Injection | testes Quality V2 | matriz de domínio pendente | `FAULT_INJECTION_V1` |
| Terminal Stable Audit | protocolos independentes | executar após demais etapas | `TERMINAL_STABLE_AUDIT_V1` |

## Integridade observacional

- `BASELINE_REFERENCES_EXACT_HEAD = TRUE`
- `BASELINE_USES_ONLY_TRACKED_CONTENT = TRUE`
- `BASELINE_MANIFEST_HASHES_MATCH_GIT_CONTENT = TRUE`
- `BASELINE_REPRODUCIBLE = TRUE`
- `UNCOMMITTED_BYTES_MUST_NOT_AFFECT_BASELINE = TRUE`
- `PRIVATE_CONTENT_INCLUDED = FALSE`

Essas propriedades são cobertas por `tests/test_core_baseline.py`, inclusive em
repositório Git sintético com worktree suja e arquivo não rastreado.
