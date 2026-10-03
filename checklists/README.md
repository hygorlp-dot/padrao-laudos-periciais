# Checklists

```text
STATUS: CURRENT AUTHORITY para controles humanos de preparação, redação e revisão.
```

Os checklists são controles do perito. A aprovação técnica e a liberação do
laudo são exclusivamente dele. Esta página reconcilia cada checklist com o
produto atual. Nenhum checklist foi removido: um item automatizado continua
listado enquanto a duplicação não induzir erro humano.

Classes: `AUTOMATED` (o produto ou um gate já garante), `HUMAN_REQUIRED`
(decisão ou conferência profissional), `OBSOLETE` (não se aplica mais) e
`PRODUCT_GAP` (revela algo que o produto ainda não cobre).

## `revisao-final.md`

| Item | Classe | Evidência |
|---|---|---|
| Não restam marcadores `[INFORMAÇÃO NECESSÁRIA]` | `AUTOMATED` | A pré-verificação jurídico-editorial (`scripts/backend_contract/legal_editorial_preflight.py`, `PENDING_MARKER`, #272) bloqueia o Word final com `[INFORMAÇÃO NECESSÁRIA` ou `[VALIDAÇÃO DO PERITO` em qualquer lugar do documento. O item continua como conferência humana: mantê-lo não induz erro. |
| Identificação do processo, juízo, partes e perito | `HUMAN_REQUIRED` | O produto propõe a partir da fonte (participantes por polo, #268) e só o perito confirma. |
| Termos e siglas uniformes | `HUMAN_REQUIRED` | A pré-verificação aponta siglas sem definição, latinismos e jargões (`ACRONYM_NOT_DEFINED`, `LATINISM`, `JARGON`) só como sugestão. |
| Valores e cálculos conferidos com as fontes | `HUMAN_REQUIRED` | O produto preserva a proveniência, mas não substitui a conferência. |
| Seções, figuras, tabelas e remissões | `HUMAN_REQUIRED` | O modelo Word gera sumário e numeração; conferir o sentido continua com o perito. |
| Demais itens (consistência textual, documental e validação técnica) | `HUMAN_REQUIRED` | Juízo profissional indelegável (`AGENTS.md`, "Responsabilidade técnica"). |

## `revisao-quesitos.md`

| Item | Classe | Evidência |
|---|---|---|
| Localização, separação e numeração dos quesitos | `HUMAN_REQUIRED` | A Análise do Caso propõe os quesitos com fonte; a confirmação é do perito. |
| Cada quesito com resposta | `HUMAN_REQUIRED` | O Core registra `cobertura_quesitos` (`scripts/motor_vicios/motor.py`), mas não existe verificação de completude de respostas no fluxo do laudo. Candidato a `PRODUCT_GAP`; avaliar no backlog antes de automatizar. |
| Respostas dependentes de dados ausentes com `[INFORMAÇÃO NECESSÁRIA]` | `AUTOMATED` (parcial) | Marcador remanescente bloqueia a emissão (#272); inserir o marcador continua decisão humana. |
| Coerência, quantidades e validação final | `HUMAN_REQUIRED` | Juízo profissional. |

## `pre-vistoria.md`, `vistoria.md`, `redacao.md`

| Item | Classe | Evidência |
|---|---|---|
| Documento estrutural ainda não preenchido | `HUMAN_REQUIRED` | Dependem de definição e validação do perito. Hoje o gate de vistoria do plano (`schemas/plano-vistoria.schema.json`), a vistoria estruturada e o gate de redação do motor (`gate_redacao`) cobrem parte do controle de forma automática. Não preencher por plausibilidade. |

## Follow-up

- Candidato a remoção futura: nenhum. Remover exige PR próprio com evidência individual.
- Candidato a `PRODUCT_GAP`: verificação de completude das respostas aos quesitos no laudo (registrar no backlog P2 antes de implementar).
