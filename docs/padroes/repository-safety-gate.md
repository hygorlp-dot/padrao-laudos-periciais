# Repository Safety Gate

## Finalidade

Converter os invariantes do Core Pericial V1 congelado em verificações
executáveis. O gate não substitui análise causal de bugs nem autoriza mudança
funcional do Core.

## Comandos locais

- Rápido: `python -m scripts.quality.verify_core --fast`.
- Completo: `python -m scripts.quality.verify_core --full`.

O modo rápido valida registros, fixtures, property tests, infraestrutura,
imports e privacidade. O modo completo acrescenta regressão integral, schemas,
fixtures e E2Es positivo e negativo. Todo PR material exige o modo completo.

Localmente, `verify_core --full` continua executando
`tests/test_architecture_analyzer_v1.py` e
`tests/test_private_case_storage_v1.py` como sempre (o arquivo
`scripts/quality/verify_core.py` não muda). Na CI, essas suítes rodam como
etapas próprias antes de `verify_core --full`, fora do orçamento cronometrado
de 60s — a exclusão é aplicada só ali, via `PYTEST_ADDOPTS` no workflow (ver
seção CI abaixo), sem alterar o script.

## Fontes canônicas

- Invariantes: `config/core-invariants.json`.
- Boundaries e impacto: `config/core-boundaries.json`.
- Integridade dos registros: `config/core-registry-lock.json`.
- Fixtures: `tests/fixtures/core-fixtures.json`.

Definições não devem ser copiadas para outros documentos. A Skill e este padrão
apenas apontam para os registros.

## Change impact

`python -m scripts.quality.change_impact caminho/alterado.py`

O resultado informa `BOUNDARIES_TOUCHED`, `INVARIANTS_REQUIRED` e testes locais.
Caminho desconhecido aciona comportamento conservador e seleciona todos os
boundaries e invariantes globais.

## CI

O workflow `.github/workflows/core-safety.yml` executa somente o gate first-party
em pull requests e pushes para `main`. Não usa secrets, não faz deploy e não
acessa referências privadas. A proteção de branch deve tornar `core-safety`
obrigatório por configuração administrativa posterior.

O job `core-safety` roda as suítes de arquitetura
(`tests/test_architecture_analyzer_v1.py`) e armazenamento privado
(`tests/test_private_case_storage_v1.py`) como etapas próprias, antes de
`verify_core --full`: qualquer falha ali também bloqueia o job, mas fora do
orçamento cronometrado de 60s (essas suítes não medem cobertura de nenhum
diretório rastreado por `--source` na etapa de regressão, então sua execução
ali só custava tempo, sem benefício de cobertura). Falhas nessas etapas
aparecem como falha de step do GitHub
Actions, não como finding estruturado do `verify_core` — não têm
`invariant`/`boundary`/`severidade` da mesma taxonomia.

A etapa `Verify frozen Core V1` define `PYTEST_ADDOPTS` com `--ignore` exato
para as duas suítes, excluindo-as somente da regressão cronometrada — a
exclusão vive só no workflow, não em `scripts/quality/verify_core.py`. Isso é deliberado:
`verify_core.py` é também um artefato protegido pelo sistema de capability
(`config/capability-protected-artifacts-v1.json`), separado do de
arquitetura; alterá-lo exigiria uma rotação nesse outro sistema, sem
mecanismo de escopo/support-artifact equivalente ao construído para
arquitetura. Manter o script intacto evita essa segunda autorização para
uma mudança que é puramente de orquestração de CI.

## Evolução

Para adicionar boundary, invariante ou fixture:

1. criar teste RED que demonstre a nova obrigação;
2. incluir uma única definição no registro canônico correspondente;
3. associar paths, consumidores, schemas e testes reais;
4. executar FAST e FULL;
5. bloquear a entrega se o registro ficar órfão ou stale.

Property tests devem provar propriedades, como conservação, invariância ou
fail-closed; não devem ser exemplos aleatórios sem relação metamórfica.

## Política de falhas

P0/P1 material novo recebe Issue própria. Não corrigir silenciosamente na Issue
do gate nem reabrir auditoria fundacional. P2 segue para backlog sem impedir a
V1, salvo se invalidar configuração, privacidade ou reprodutibilidade.

O Core congelado só muda por Issue específica, testes RED e revisão
independente. O Safety Gate audita boundaries tocados e invariantes globais;
não inicia sweep geral por padrão.

## Gates de arquitetura e código morto

A V1 executa compileall, integridade de imports, registros cruzados de
boundaries/consumidores e contratos de schema. Não adiciona analisador de código
morto: o projeto contém módulos de CLI, adapters e integrações carregadas por
entry points, o que elevaria falsos positivos sem configuração adicional.

## Mutation testing

Não é blocker da V1. O piloto para `segmentar_documentos.py`,
`validar_integridade.py` e `validar_plano.py` permanece follow-up da Issue #11.
Os property tests desta entrega exercitam as mutações históricas equivalentes:
perda de página, ownership incorreto e equivalência autodeclarada.
