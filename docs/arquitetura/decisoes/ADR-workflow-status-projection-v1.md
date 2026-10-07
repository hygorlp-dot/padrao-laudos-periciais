# ADR — Projeção read-only da situação do fluxo pericial (UX inc-2, #291)

Status: aceito (decisão de produto (a) do mantenedor, 2026-10-07).

## Contexto

O Início de uma perícia só confirmava que ela existe. A navegação lateral não
dizia o que já foi feito, o que espera conferência profissional nem o que ficou
desatualizado. Cada etapa já tem uma autoridade de leitura (`Get*` na camada de
aplicação) que reconcilia a revisão persistida com as autoridades de montante.
O que faltava era uma leitura agregada que respondesse, de uma vez:
**qual é a situação, o que precisa de atenção e qual é a próxima ação disponível**.

## Decisão

`GetWorkflowStatus` (`scripts/backend_contract/application/workflow_status.py`)
é uma **projeção de leitura**. Ela é exposta em
`GET /v1/workspaces/{id}/workflow-status` na Local API e na Product Bridge
(`/app-api/v1/...`). Limites:

- Ela só chama as autoridades de leitura existentes. Não grava nada, não decide
  nada, não aprova nada e não dispara OCR, renderização, derivação nem
  extração de texto. Não cria tabela, migração, agendador, evento, cache nem
  estado global persistido.
- A leitura é feita sob `consistent_reads`: a trava da autoridade privada mais
  a trava da conexão SQLite. São as mesmas travas que toda gravação deste
  processo usa, na mesma ordem. Por isso nenhuma revisão concorrente é
  confirmada no meio da projeção, e duas etapas nunca mostram estados de
  instantes diferentes.
- A falha de uma etapa vira `UNAVAILABLE` **só nessa etapa** e não vira estado
  vazio. Uma perícia inexistente é 404. Cada etapa é lida pelo
  `workspace_id` da requisição, sem cache.
- A resposta traz códigos (`reasons`) e referências de revisão. O texto ao
  usuário fica no frontend. Motivos internos em texto livre
  (`upstream_stale_reasons`) não são repassados: só a contagem deles.

### Dimensões separadas

Cada etapa traz quatro campos independentes, além de `state`, que só resume a
situação para leitura rápida:

| campo | valores | pergunta |
|---|---|---|
| `availability` | `AVAILABLE`, `UNAVAILABLE` | a consulta foi possível? |
| `currency` | `CURRENT`, `STALE`, `NOT_EVALUATED` | a base de montante ainda é a mesma? |
| `decision` | `NOT_TRACKED`, `NONE`, `PARTIAL`, `COMPLETE`, `REVIEWED`, `APPROVED` | o que o profissional já decidiu (histórico) |
| `revision` / `updated_at` | inteiro / instante | qual revisão sustenta a leitura |

Assim, um laudo **aprovado** sobre fonte que mudou aparece com
`decision=APPROVED`, `currency=STALE` e `state=REVIEW_REQUIRED`. A aprovação
histórica não some, mas também não aparece como vigente.

### Estados (conjunto fechado)

Precedência, do mais forte ao mais fraco:
`UNAVAILABLE` > `ATTENTION` > `REVIEW_REQUIRED` > `PROCESSING` >
`AWAITING_REVIEW` > `IN_PROGRESS` > `APPROVED` / `READY` / `RECORDED` >
`NOT_STARTED` / `NOT_TRACKED`.

| estado | significado | quando aparece |
|---|---|---|
| `NOT_STARTED` | nada registrado | o artefato da etapa não existe |
| `IN_PROGRESS` | rascunho ou registro parcial | o domínio tem critério de conclusão ainda não atingido |
| `PROCESSING` | processamento local em curso | derivação de material em execução |
| `AWAITING_REVIEW` | proposta à espera de decisão profissional | proposta extraída ou de engine sem decisão |
| `REVIEW_REQUIRED` | base de montante mudou depois do registro | `upstream_stale` ou `STALE` no domínio |
| `ATTENTION` | falha, interrupção, conflito ou bloqueio | estado explícito do domínio |
| `READY` | critério objetivo do domínio atingido | ex.: `readiness=READY` do planejamento |
| `APPROVED` | ato explícito de aprovação | laudo/entrega `APPROVED` |
| `RECORDED` | fatos registrados, sem critério objetivo de conclusão | ex.: identificação do processo |
| `NOT_TRACKED` | ferramenta sem situação de etapa | Recuperação (fundamento: `MANAGEMENT_TOOL`) |
| `UNAVAILABLE` | não foi possível verificar | exceção na autoridade, serviço ausente |

A projeção **não** conclui etapa sozinha. Existir um registro não significa
etapa concluída. Não há botão genérico de "concluir etapa". `READY` e
`APPROVED` só aparecem quando o próprio domínio já tem esse estado.

## Matriz por etapa

As chaves de etapa são os segmentos de rota do catálogo
(`frontend/src/routes/routeCatalog.ts`). A ação de navegação é sempre o link da
própria etapa, e o frontend escolhe o texto a partir do estado.

| etapa | autoridade consultada | fatos e revisões | condições → estado | efeito de montante desatualizado |
|---|---|---|---|---|
| `processo` | `GetProcessCase`, `GetProcessMetadataReview` (só extrações persistidas, sem OCR), existência da confirmação, `CaseDocumentIngestion.states` | revisão do processo; estado agregado dos metadados | material em derivação → `PROCESSING`; metadados `CONFLICT` → `ATTENTION`; `ERROR` sem derivação em curso → `ATTENTION`; `EXTRACTED`/`PARTIAL` não confirmados → `AWAITING_REVIEW`; `CONFIRMED` → `RECORDED`; só dados manuais → `RECORDED`; nada → `NOT_STARTED` | confirmação existente mas não vinculada à revisão atual → `REVIEW_REQUIRED` (`METADATA_CONFIRMATION_OUTDATED`) |
| `materiais` | `CaseDocumentIngestion.states` | contagem por estado de derivação | algum `PROCESSING` → `PROCESSING`; algum `FAILED`/`INTERRUPTED` → `ATTENTION`; todos `READY` → `RECORDED`; nenhum → `NOT_STARTED` | não se aplica (é a fonte) |
| `analise` | `GetCaseAnalysis` | revisão, `stale_document_ids`, `source_inventory_stale`, conflitos com `human_review_status=PENDING`, cobertura | fontes alteradas ou novas não indexadas → `REVIEW_REQUIRED`; conflitos pendentes → `AWAITING_REVIEW`; senão `RECORDED` (cobertura parcial vira motivo) | `REVIEW_REQUIRED` |
| `planejamento` | `GetPericialPlanning` | revisão, `upstream_stale`, `coverage` (`pending_items`, `readiness`) | `upstream_stale` → `REVIEW_REQUIRED`; `pending_items>0` → `AWAITING_REVIEW`; `readiness=READY` → `READY`; `BLOCKED` → `ATTENTION`; `PARTIAL` → `IN_PROGRESS` | `REVIEW_REQUIRED`, mantendo `decision` histórico |
| `vistoria` | `GetInspectionSession` | revisão, `upstream_stale`, `coverage` por estado de execução | `upstream_stale` → `REVIEW_REQUIRED`; itens `PENDING` → `IN_PROGRESS`; senão `RECORDED`. Itens bloqueados, parciais, não executados ou não aplicáveis são fatos registrados pelo perito e aparecem como motivos, não como falha | `REVIEW_REQUIRED` |
| `evidencias` | `GetTechnicalSnapshot` | avaliações `PENDING`/`APPROVED`/`REJECTED` | `upstream_stale` → `REVIEW_REQUIRED`; avaliação `PENDING` → `AWAITING_REVIEW`; nenhuma evidência → `IN_PROGRESS`; senão `RECORDED` | `REVIEW_REQUIRED` |
| `constatacoes` | `GetTechnicalSnapshot` | propostas sem decisão, conflitos `UNRESOLVED`, constatações efetivas | `upstream_stale` → `REVIEW_REQUIRED`; conflito não resolvido → `ATTENTION`; proposta sem decisão → `AWAITING_REVIEW`; sem propostas → `NOT_STARTED`; senão `RECORDED` | `REVIEW_REQUIRED` |
| `analise-tecnica` | `GetConstructionDefectAnalysis` | revisão, `gate`, `upstream_stale` | `upstream_stale` → `REVIEW_REQUIRED`; `gate=BLOQUEADO_PARA_REDACAO` → `ATTENTION`; senão `RECORDED` (o `gate` vira motivo) | `REVIEW_REQUIRED` |
| `laudo` | `GetReportSnapshot` | revisão, `state`, `coverage.complete`, `upstream_stale` | `upstream_stale` → `REVIEW_REQUIRED`; `SUPERSEDED` → `ATTENTION`; `DRAFT` → `IN_PROGRESS`; `REVIEWED` → `AWAITING_REVIEW` (aprovação pendente); `APPROVED` → `APPROVED` | `REVIEW_REQUIRED` com `decision` histórico |
| `revisao` | `GetReportSnapshot` | os mesmos fatos, lidos como ato de revisão | sem laudo → `NOT_STARTED` (`REPORT_NOT_STARTED`); `DRAFT` → `NOT_STARTED` (`REPORT_NOT_REVIEWED`); `REVIEWED` → `AWAITING_REVIEW`; `APPROVED` → `APPROVED` | `REVIEW_REQUIRED` |
| `exportar` | `GetDeliverySnapshot` | revisão, `state`, papéis/formatos dos artefatos | `STALE` → `REVIEW_REQUIRED` (com `stale_origin_state`); `SUPERSEDED` → `ATTENTION`; `DRAFT` → `IN_PROGRESS`; `READY_FOR_REVIEW` → `AWAITING_REVIEW`; `APPROVED`/`FINALIZED`/`DELIVERED` → `APPROVED`. Word sem PDF derivado → motivo `PDF_ABSENT` (entrega parcial explícita) | `REVIEW_REQUIRED` |
| `orcamento` | `GetBudgetSnapshot` | revisão, `status` financeiro | ausente → `NOT_STARTED` (`OPTIONAL_STAGE`); presente → `RECORDED` (o status vira motivo). Nunca é etapa técnica obrigatória | não se aplica |
| `recuperacao` | nenhuma (ferramenta) | — | sempre `NOT_TRACKED` (`MANAGEMENT_TOOL`). Exportar backup é uma operação, não uma leitura de situação | não se aplica |

## Início

O Início (`/pericias/{id}`) mostra:

- o nome da perícia como `h2`;
- **Situação**: contagem por estado, em texto;
- **Precisa de atenção**: as etapas em `UNAVAILABLE`, `ATTENTION`,
  `REVIEW_REQUIRED`, `AWAITING_REVIEW` e `PROCESSING`, com link e motivo;
- **Próxima ação disponível**: a primeira etapa técnica, na ordem do catálogo,
  que não está em `RECORDED`, `READY`, `APPROVED` nem `NOT_TRACKED`. Quando não
  há nenhuma, o texto diz que as regras disponíveis não apontam pendência. Não
  diz "concluído".

Se a projeção falhar, o Início diz que a situação não pôde ser verificada e
oferece nova tentativa. A navegação para todas as etapas continua disponível.

## Consequências

- Uma etapa nova exige uma linha nesta matriz e no mapa da projeção.
  Sem isso, ela aparece como `UNAVAILABLE`, nunca como concluída.
- As propostas de participantes e de imóvel não entram em `processo`, porque
  exigem leitura de texto dos autos (custo e OCR). A etapa mostra só fatos
  persistidos e diz isso nos detalhes técnicos.
