# Matriz de Skills por fase do roadmap

## Regra de precedência

AGENTS.md e contratos first-party prevalecem sempre. Skills de terceiros não
podem redefinir semântica pericial, autoridade, privacidade, trust ou produto.
As categorias são `REQUIRED`, `RECOMMENDED`, `CONDITIONAL` e
`NOT_APPLICABLE`.

## APPLICATION_LAYER_V1

### REQUIRED

- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review e receiving-code-review, conforme aplicável
- revisão independente segundo o classificador de risco

### CONDITIONAL

- systematic-debugging, quando houver defeito/falha
- research-ranking, para decisão material de dependência
- writing-plans e executing-plans, para execução multietapas
- systemic-auditor e external-diversity-review, conforme o classificador

### NOT_APPLICABLE

- ui-pericial
- frontend-design
- design-motion-principles
- workflows de UI do impeccable

## LOCAL_API_V1

### REQUIRED

- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review e receiving-code-review
- revisão independente segundo o classificador

### CONDITIONAL

- systematic-debugging
- research-ranking para avaliar framework/dependência
- writing-plans, executing-plans, systemic-auditor e external-diversity-review

### NOT_APPLICABLE

- frontend-design
- ui-pericial
- design-motion-principles
- workflows de UI do impeccable

## FRONTEND_SHELL_V1

### REQUIRED

- ui-pericial
- frontend-design
- design-motion-principles
- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review e receiving-code-review
- revisão independente segundo o classificador

### RECOMMENDED

- impeccable, somente para crítica, auditoria, refinamento e polish

### CONDITIONAL

- systematic-debugging, writing-plans, executing-plans, systemic-auditor e
  external-diversity-review

## PROCESS_CASE_UI

### REQUIRED

- ui-pericial
- frontend-design
- design-motion-principles
- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review
- receiving-code-review
- revisão independente
- Skills first-party do domínio Processo/Caso

### RECOMMENDED

- impeccable

## VISTORIA_UI

### REQUIRED

- ui-pericial
- frontend-design
- design-motion-principles
- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review
- receiving-code-review
- planejamento-pericial-autonomo
- motor-vicios-construtivos
- revisão independente

### RECOMMENDED

- impeccable

## EVIDENCE_UI

### REQUIRED

- ui-pericial
- frontend-design
- design-motion-principles
- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review
- receiving-code-review
- auditoria-grounding-pericial
- trilha-auditoria-pericial
- revisão independente

### RECOMMENDED

- impeccable

## TECHNICAL_FINDINGS_UI

### REQUIRED

- ui-pericial
- frontend-design
- design-motion-principles
- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review
- receiving-code-review
- auditoria-pericial-integrada
- motor-vicios-construtivos
- revisão independente

### RECOMMENDED

- impeccable

## LAUDO_UI

### REQUIRED

- ui-pericial
- frontend-design
- design-motion-principles
- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review
- receiving-code-review
- redacao-laudo-pericial
- revisao-laudo-pericial
- revisão independente

### RECOMMENDED

- impeccable

## BUDGET_UI

### REQUIRED

- ui-pericial
- frontend-design
- design-motion-principles
- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review
- receiving-code-review
- Skills first-party de orçamento e fidelidade valor/unidade
- revisão independente

### RECOMMENDED

- impeccable

## AI_GATEWAY

### REQUIRED

- engenharia-seguranca-pericial
- test-driven-development
- verification-before-completion
- repository-safety-gate
- requesting-code-review e receiving-code-review
- reviewer-independente
- systemic-auditor
- external-diversity-review quando acionado

### CONDITIONAL

- research-ranking para provider/dependência autorizados

### NOT_APPLICABLE

- frontend-design, ui-pericial, design-motion-principles e impeccable não têm
  autoridade sobre comportamento de IA ou domínio

`AI_PROPOSAL` nunca se torna efetiva sozinha. Ativação de provider, egress,
secrets ou envio de dados exige autorização própria e todos os gates de
privacidade/trust.
