# Contratos de dados

> Status: CURRENT AUTHORITY para o papel de cada família de schema. O estado do
> produto está em [`PRODUCT.md`](../PRODUCT.md); esta página não descreve
> limitações do produto.

Os contratos usam JSON Schema Draft 2020-12. Os limites de propriedades e
condicionais são definidos por cada schema, não por esta página. Alegações, documentos, constatações, inferências e resultados
inconclusivos permanecem semanticamente separados.

## `LEGACY_SCHEMA_CAN_STILL_BE_LIVE`

Um schema antigo não é órfão só porque o frontend moderno não o usa. Ele
continua vivo quando é consumido por validadores, fixtures
(`tests/fixtures/core-fixtures.json`), `config/schema-versions.json`, fronteiras
do Core (`config/core-boundaries.json`), baseline estável
(`config/core-stable-baseline-v1.json`), golden corpus, gates ou Skills. A
reachability de cada schema é auditada por
`python -m scripts.quality.repository_hygiene` (seção `schemas`); nenhum schema
é removido sem prova positiva de ausência de todos esses consumidores.

## Famílias

### 1. Contratos semânticos do Core (legados e vivos)

Contratos do Core Pericial protegido, validados por `scripts/validar_schemas.py`,
pelos validadores dos módulos do Core e pelas fronteiras/baseline do Core.

- `pje-comum.schema.json`: definições reutilizáveis de proveniência, confiança,
  paginação, reconciliação, conflitos e elementos extraídos do PJe.
- `manifesto-pje.schema.json`: inventário e segmentação do PDF consolidado.
- `documento-pje.schema.json`: conteúdo estruturado de um documento PJe.
- `processo.schema.json`: dados extraídos dos autos (documentos, alegações,
  quesitos, decisões, conflitos e pendências).
- `delimitacao-pericial.schema.json`: tipo de perícia, delimitação técnica,
  quesitos, cobertura, ressalvas e plano preliminar.
- `inventario-referencias.schema.json`, `conhecimento-referencial.schema.json`,
  `conhecimento-normativo.schema.json`: catálogo por hash e derivados privados
  com níveis e proveniência.
- `fonte-online.schema.json`: proveniência e vigência de fontes técnicas
  pesquisadas online.
- `plano-vistoria.schema.json`, `inventario-vistoria.schema.json`,
  `vistoria.schema.json`: planejamento, arquivos de campo e registro da vistoria.
- `analise-motor-vicios.schema.json`, `patologia.schema.json`: motor de vícios,
  hipóteses e unidade técnica `PAT-NNN`.
- `plano-redacao.schema.json`, `laudo-redacao.schema.json`,
  `laudo.schema.json`: plano de redação, modelo semântico do laudo e agregação
  rastreável (sem layout Word).

### 2. Contratos de snapshot do produto

Revisões append-only gravadas pela Application Layer e expostas pela Local API.

- `judicial-domain-model-v1.schema.json`: domínio judicial plural (polos, papéis,
  representação).
- `case-analysis-snapshot-v1.schema.json`: Análise do Caso.
- `pericial-planning-snapshot-v1.schema.json`: Planejamento.
- `inspection-session-v1.schema.json`: Vistoria.
- `technical-snapshot-v1.schema.json`: cadeia técnica (evidências e constatações).
- `construction-defect-analysis-v1.schema.json`: Análise de vícios (PAT).
- `report-snapshot-v1.schema.json`, `report-template-manifest-v1.schema.json`:
  laudo e vinculação do modelo Word.
- `delivery-snapshot-v1.schema.json`: entrega Word autoritativa e PDF derivado.
- `budget-snapshot-v1.schema.json`: orçamento, financeiramente separado.

### 3. Contratos de backup, recuperação e offline

- `workspace-backup-v1.schema.json`: pacote de backup verificável da perícia.
- `offline-inspection-package-v1.schema.json`: pacote de vistoria offline e sua
  sincronização.

### 4. Contratos de agente, revisão e assurance

- `auditoria-grounding-pericial.schema.json`: claim, evidências e veredito de
  grounding.
- `trilha-auditoria-agente.schema.json`: trilha profissional auditável, sem
  raciocínio privado.
- `review-multiagente.schema.json`: revisão independente vinculada ao HEAD.
- `skill-router-v3.schema.json`: manifesto fechado de roteamento de Skills.
- `architecture-baseline-v1.schema.json`, `capability-policy-v1.schema.json`,
  `capability-exception-v1.schema.json`, `quality-finding-v1.schema.json`:
  gates protegidos de arquitetura e capability.
- `repository-hygiene-v1.schema.json`: saída do auditor
  `REPOSITORY_HYGIENE_V1`.

## Dependência externa

A validação usa o pacote Python `jsonschema`, declarado em `pyproject.toml`. O pacote instala também `referencing`, usado para resolver referências entre os schemas. A resolução exata fica registrada em `uv.lock`.

```powershell
uv lock --check
uv pip sync --system --require-hashes requirements.txt
python scripts/validar_schemas.py
```

O validador confere os próprios schemas e os exemplos em
`tests/fixtures/schemas/` e `tests/fixtures/pje/`. Arquivos com sufixo
`-valido.json` ou `-valida.json` devem ser aceitos; os demais exemplos dessas
pastas são casos negativos e devem ser rejeitados.

## Limites dos contratos

- Os schemas não substituem a validação técnica do perito.
- Relações entre arquivos distintos exigem validação complementar além do
  schema (por exemplo, a integridade da delimitação contra o corpus-fonte).
- Alterações nos enums e nas condicionais dependem de decisão canônica
  documentada; versões suportadas e migradores ficam em
  `config/schema-versions.json` (versão futura falha fechada).

## Histórico

O fluxo inicial previsto era `PDF PJe → manifesto-pje.json → documento-pje.json
→ delimitacao-pericial.json → plano-vistoria.json → processo.json →
vistoria.json → motor técnico → PAT-NNN → gate de redação`, orquestrado por
Skills. Ele permanece como origem dos contratos da família 1; o fluxo atual do
produto está em [`PRODUCT.md`](../PRODUCT.md).
