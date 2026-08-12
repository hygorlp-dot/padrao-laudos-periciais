# Padrão do Backend Contract V1

## Regra aprovada

O backend adota **monólito modular com Ports & Adapters**. O domínio pericial
não depende de React, Tauri, OpenAI, SQLite, Word, GitHub ou UI. Esta camada
consolida contratos transversais e não reconstrói o Motor Técnico existente.

## Identidade e estado

- `case_id` é UUID interno estável; número CNJ é atributo e nunca chave técnica.
- IDs materiais existentes permanecem rastreáveis.
- o caso percorre uma máquina de estados explícita de `CRIADO` a `ENCERRADO`;
- transição não declarada é rejeitada, sem avanço silencioso.
- avanço e reabertura preservam origem, destino, motivo e timestamp;
- reabertura exige motivo e retorna somente ao estado imediatamente anterior,
  sem saltos arbitrários.

## Revisões e autoridade

Artefato material usa histórico append-only com `revision`, `created_at`,
`supersedes`, `status` e `source`. Nova revisão marca a anterior como
`SUPERSEDED`, sem apagá-la. Payloads e valores históricos são congelados
recursivamente; leituras usam estruturas imutáveis e cópias defensivas impedem
que a mutação do objeto de entrada altere o registro armazenado.

Valores mantêm camadas distintas:

`SOURCE_VALUE → AI_PROPOSAL → ENGINE_DECISION → PROFESSIONAL_OVERRIDE`.

`EFFECTIVE_VALUE` é derivado somente pela precedência
`PROFESSIONAL_OVERRIDE > ENGINE_DECISION > SOURCE_VALUE` e não é armazenado
como nova fonte. `AI_PROPOSAL` permanece no histórico e pode ser consultada
como proposta pendente, mas nunca participa sozinha de `effective()`. Override
profissional exige justificativa explícita e preserva todo o histórico.

## Dependências e STALE

O grafo direcionado relaciona artefatos upstream e downstream, rejeita IDs
órfãos, autodependências e ciclos. Mudança material invalida transitivamente os
derivados como `STALE`. Artefato `STALE` não pode ser lido como atual; sua
atualização exige operação e trilha explícitas.

Fluxo de referência:

`OBS/MED/FOT/DOC → PAT → REDAÇÃO → CONCLUSÃO/QUESITOS → REPARO → ORÇAMENTO → WORD/PDF`.

## Invariantes

O registro first-party torna auditáveis, no mínimo:

- alegação não é constatação;
- declaração de terceiro não é `OBS`;
- norma não é evidência física;
- `NÃO_CONSTATADA` não implica inexistência;
- origem exige suporte causal;
- conclusão de quesito não cria análise nova;
- redação não altera `PAT_FINAL`;
- artefato `STALE` não é atual;
- Professional Override não destrói histórico.

Esse mecanismo não declara corrigidos os bugs P0 conhecidos; eles exigem
Issues e testes adversariais próprios.

## Unidade de trabalho e auditoria

Uma mudança material reúne `update + invalidation + audit event` na mesma
unidade. Falha restaura os participantes ao snapshot anterior. O V1 usa
contratos em memória e não exige banco, fila ou serviço distribuído.

Eventos de auditoria registram identificador, tipo, correlação, instante,
caso/artefato quando aplicáveis e resumo profissional. Não armazenam
chain-of-thought.

## Ports & Adapters

As portas estáveis são `CaseRepository`, `DocumentRepository`,
`EvidenceRepository`, `NormRepository`, `CostRepository`, `MediaStorage`,
`ReportExporter`, `SecretStore` e `AIProvider`. São Protocols sem adaptadores
concretos nesta etapa. A integração OpenAI pertence à Issue do AI Gateway.

## Capabilities, jobs e erros

Capabilities usam `SUPPORTED`, `PARTIALLY_SUPPORTED`, `NOT_APPLICABLE` ou
`NOT_IMPLEMENTED`. Limitação do software permanece tipo distinto de
inconclusão técnica por insuficiência de evidência.

Job local expõe `job_id`, `status`, `progress`, `error` e `result`, sem broker.
Progresso, quando mensurável, fica entre 0 e 100; ausência de mensuração usa
`null`, nunca porcentagem fabricada.

Erro estruturado contém `error_code`, `severity`, `category`, `case_id`,
`artifact_id`, `correlation_id`, `message`, `recoverable` e
`suggested_action`. Categorias: `DOMAIN`, `VALIDATION`, `EVIDENCE`, `AI`,
`NETWORK`, `STORAGE`, `INTEGRATION` e `PRIVACY`.

## Migrações e versões

Documento versionado declara `schema_version`; o registro possui
`migration_version`, versão corrente e passos sequenciais explícitos. Versão
futura, ausente ou salto de migração são rejeitados. Nenhum dado real é
migrado nesta etapa.

## Limitações e riscos residuais

- persistência e adaptadores concretos ainda não existem;
- concorrência entre processos não é tratada pelo Unit of Work em memória;
- o grafo precisa ser integrado gradualmente aos pipelines existentes;
- as invariantes são infraestrutura e não substituem os gates periciais;
- os bugs P0 conhecidos permanecem fora do escopo e não foram corrigidos;
- não há API, UI, AI Gateway, renderer Word/PDF ou motor de orçamento novo.
