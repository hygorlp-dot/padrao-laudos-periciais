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
`tests/test_architecture_analyzer_v1.py` como sempre (o arquivo
`scripts/quality/verify_core.py` não muda). Na CI, essa suíte roda como
etapa própria antes de `verify_core --full`, fora do orçamento cronometrado
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
acessa referências privadas. A proteção de branch torna `core-safety`
obrigatório no mesmo boundary de merge.

O job `core-safety` roda a suíte de arquitetura (`tests/test_architecture_analyzer_v1.py`)
como etapa própria, antes de `verify_core --full`: qualquer falha ali também
bloqueia o job, mas fora do orçamento cronometrado de 60s (essa suíte não
mede cobertura de nenhum diretório rastreado por `--source` na etapa de
regressão, então sua execução ali só custava tempo, sem benefício de
cobertura). Falhas nessa etapa aparecem como falha de step do GitHub
Actions, não como finding estruturado do `verify_core` — não têm
`invariant`/`boundary`/`severidade` da mesma taxonomia.

A suíte explícita `tests/test_repository_safety_gate.py`, executada pelo
`verify_core`, aplica de forma bloqueante o oracle first-party de publicação
ao tree rastreado e a todos os commits alcançáveis pelos refs do checkout.
O checkout usa `fetch-depth: 0`; finding atual ou histórico falha o pytest e,
portanto, o mesmo job requerido. A proveniência sintética das fixtures também
é validada pelo gate. Gitleaks permanece uma evidência advisory separada.

A etapa `Verify frozen Core V1` define `PYTEST_ADDOPTS: --ignore=tests/test_architecture_analyzer_v1.py`
para excluir a suíte da regressão cronometrada — a exclusão vive só no
workflow, não em `scripts/quality/verify_core.py`. Isso é deliberado:
`verify_core.py` é também um artefato protegido pelo sistema de capability
(`config/capability-protected-artifacts-v1.json`), separado do de
arquitetura; alterá-lo exigiria uma rotação nesse outro sistema, sem
mecanismo de escopo/support-artifact equivalente ao construído para
arquitetura. Manter o script intacto evita essa segunda autorização para
uma mudança que é puramente de orquestração de CI.

## Sharding do regression (V7-4A, #259)

O job requerido `core-safety` passou a ser um agregador closed-set sobre jobs
independentes do mesmo SHA, sem alterar `scripts/quality/verify_core.py`
(byte-idêntico, artefato capability-protected) nem as constantes da política
temporal (`full_gate_max_seconds = 60`, `STRICT`/`PR_ADVISORY`):

- `architecture`: a suíte de arquitetura, como antes, em runner próprio;
- `core-gate`: `verify_core --full` inalterado; seu `regression` cobre a
  partição que carrega coverage (complemento do manifest);
- `regression-shard`: o MESMO comando `regression` do juiz (extraído por
  `scripts.quality.core_safety_plan`, nunca copiado) sobre cada shard de
  `config/core-safety-shards-v1.json`, em runner próprio, com coverage e
  inventário de node IDs (`scripts.quality.core_safety_nodes`);
- `inventory`: coleta de referência do regression integral (sem shards) e da
  partição do gate;
- `core-safety`: `python -m scripts.quality.core_safety_shards aggregate`.

O agregador falha fechado quando qualquer job não termina em `success`
(inclusive `skipped`/`cancelled`), quando falta ou sobra shard, quando a
evidência tem SHA, manifest ou schema divergentes, quando um node falha ou não
executa, quando `gate ∪ shards ≠ regression integral` ou há sobreposição
(shards: node IDs exatos contra a coleta integral; gate: mesmo conjunto de
arquivos e contagem exata por arquivo, porque há IDs parametrizados que embutem
bytes dependentes de relógio e mudam entre processos sem mudar o node),
quando o coverage de um shard não está contido no do gate
(`PARTITION_COVERAGE_DRIFT`) ou quando o coverage combinado regride contra
`config/quality-baseline.json`. Ele reconstrói a lista fechada de 16 checks do
`verify_core` e reporta `SEMANTIC_STATUS` e `TIMING_STATUS` separadamente; uma
falha só temporal continua vermelha exatamente como antes.

**Escopo cronometrado (explícito, não silencioso).** Como em #63/#64, o
`OBSERVED_SECONDS` do `verify_core` passa a medir o `verify_core` do job
`core-gate`, cujo `regression` contém só a partição do gate; os shards rodam
fora dessa janela de 60 s, limitados apenas pelo `timeout-minutes` dos jobs, e
seu tempo aparece como `SHARD_DURATION`/`seconds` na evidência e no agregador.
Se o orçamento temporal deve cobrir o wall-clock dos shards é decisão de
política de #109/#111, não desta otimização.

**Premissa residual.** A execução real do `regression` dentro do `verify_core`
não é inventariada por node (o juiz é byte-idêntico e não emite IDs); ela é
provada pelo exit 0 do juiz, como no BASE, e pela coleta independente da mesma
partição no job `inventory` (mesmos arquivos e contagem por arquivo). Falhas
fechadas conhecidas que podem gerar vermelho legítimo exigindo ação: coverage
de um shard fora do gate (mover o arquivo para o gate) e ID parametrizado
dependente de relógio dentro de um shard (manter o arquivo no gate); shard
sem nenhum dado de coverage gravado também falha fechado.

Arquivo de teste novo cai automaticamente na partição do gate (complemento):
nada some silenciosamente. Mover um arquivo para um shard exige que seu
coverage medido já esteja contido no do gate — o que é provado a cada execução,
não presumido. A partição é escolhida por tempo medido
(`.github/workflows/core-safety-profile.yml`, não-dispositivo).

Shards rodam em runners separados (sem `pytest-xdist`, sem workspace
compartilhado). Os testes de Word nativo continuam `skip` nos runners GitHub
sem Microsoft Word/pywin32, como antes; isso não substitui a matriz Word nativa
do Human RC.

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
