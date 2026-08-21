# MAINTAINABILITY_REFACTORING_V1 -- Convenções de decomposição

Parte do Stage 3 (#80). Registrado após HOTSPOT-01 (`motor.py::executar`, PR #82)
por recomendação do `EXTERNAL_DIVERSITY_REVIEWER`: nenhum guia existia para
"como decompor um hotspot" além dos alvos numéricos de complexidade em
`config/quality-baseline.json`, e faltam 4 PRs no mesmo estilo de trabalho --
sem uma convenção mínima, cada hotspot corre o risco de inventar seu próprio
padrão de extração, dificultando a leitura cruzada entre eles.

Este documento registra o que HOTSPOT-01 realmente fez, para os hotspots
seguintes seguirem (ou divergirem deliberadamente, com justificativa) em vez
de reinventar.

## Regras aplicadas

1. **Funções extraídas são sempre top-level do módulo, nunca aninhadas
   (closures internas).** `scripts/quality/metrics.py::_function_complexity`
   conta complexidade via `ast.walk` sobre o `FunctionDef` inteiro --
   qualquer `def`/`lambda` aninhado dentro da função original continua
   contando para a complexidade dela. Extrair para top-level é o que
   efetivamente reduz o número medido, não apenas move a leitura.
2. **Uma função extraída por fase semântica do algoritmo original**, não por
   contagem de linhas. Cada corpo de loop vira uma função nomeada pelo que
   ele decide/constrói (`_construir_manifestacao_e_patologia`,
   `_recalcular_patologia`, `_sanear_questao`), não por posição no arquivo.
3. **Estado é roteado explicitamente por parâmetro**, nunca por closure
   sobre variáveis do escopo pai. Onde o original lia/escrevia um dict
   mutável compartilhado (`r`), a função extraída recebe `r` como parâmetro
   e o autor confirma explicitamente (por leitura + teste) que ela não lê
   nenhuma chave que o chamador ainda não populou naquele ponto da execução.
4. **Ordem de side-effects observáveis é preservada exatamente.** Quando uma
   função passa a *retornar* valores que o código original efeitava
   diretamente em uma estrutura compartilhada (ex: `r["manifestacoes"].append(...)`
   passou a acontecer no chamador, após o retorno, em vez de inline no meio
   do cálculo), isso só é aceitável se nada entre o ponto original e o novo
   ponto de efeito *lê de volta* a estrutura alterada -- verificado, não
   assumido.
5. **Nenhuma otimização de cálculo duplicado antes de a decomposição estar
   provada.** A regra do programa (`docs/stabilization/hotspot-characterization-v1.md`,
   instrução do Stage 3) é: primeiro preservar a estrutura (incluindo
   passadas duplicadas/redundantes já caracterizadas), só reduzir
   duplicação depois, e apenas se a saída exata permanecer idêntica e a
   equivalência for provada -- não nesta rodada.
6. **Parar de fatiar quando a fronteira deixa de ser natural.** O alvo
   "prefer <=15" para helpers é uma preferência, não um piso obrigatório
   (`Stage 3` é explícito: "do not metric-game these thresholds"). Quando
   uma função extraída ainda concentra muitas variáveis locais
   interdependentes alimentando um único literal de saída (HOTSPOT-01:
   `_construir_manifestacao_e_patologia`=41, `_sanear_questao`=32, ~30-35
   variáveis cada), fatiar mais tende a exigir passar um número grande de
   parâmetros ou empacotar estado em um dict/namespace só para viabilizar a
   divisão -- isso é fragmentação de conveniência métrica, não redução real
   de complexidade cognitiva, e não deve ser feito só para bater o número.
   Registre a decisão e a razão no commit; deixe para uma revisão dedicada
   de legibilidade, separada da extração orientada a métrica, se o time
   decidir que vale a pena.
7. **Toda função extraída acima do limiar de rastreamento entra no ratchet
   de `config/quality-baseline.json::hotspots`.** `validate_quality_baseline`
   (`scripts/quality/metrics.py`) só compara `(path, function)` que já
   estejam listados ali -- não existe teto global de complexidade por
   arquivo. Reduzir `executar` de 130 para 13 não protege automaticamente
   contra as ~93 unidades de complexidade que migraram para os helpers
   extraídos: se eles não entrarem no baseline, podem crescer sem limite
   sem que nenhum gate reclame, reabrindo exatamente o problema que a
   extração resolveu. HOTSPOT-01 registrou `_construir_manifestacao_e_patologia`
   (41), `_sanear_questao` (32) e `_recalcular_patologia` (20) -- helpers
   triviais (`_agrupar_por_manifestacao`=3, `_calcular_autonomia`=5, etc.)
   não precisam de entrada própria, seguindo o mesmo padrão implícito já
   usado no baseline para o resto do repositório (só funções de porte
   comparável às já rastreadas, ex. `executar_pipeline_redacao`=41,
   `executar_pipeline_motor`=27, entram). Faça o mesmo em HOTSPOT-02..05:
   depois de decompor, rode `analyze_complexity` no arquivo inteiro e
   adicione ao baseline qualquer helper novo cujo valor fique na faixa das
   entradas já existentes -- não deixe complexidade real ficar invisível ao
   ratchet só porque mudou de nome de função. (Achado do `PR_REVIEWER` na
   revisão da PR #82.)

8. **Toda prova de equivalência é por execução real, não por leitura.**
   Além dos 49 casos do Golden Forensic Corpus e da suíte completa, provou-se
   adicionalmente equivalência OLD-vs-NEW rodando as duas implementações
   (antiga via `git show <base>:<arquivo>` carregado como módulo, nova via
   import normal) lado a lado, no mesmo processo, comparando saída via JSON
   canônico -- inclusive para ramos que nenhum caso golden pré-existente
   exercitava (`GC-MOTOR-008`/`009`/`010`, adicionados durante a revisão da
   PR #82 depois que `EXTERNAL_DIVERSITY` apontou a lacuna).
9. **Nomeação**: `_verbo_substantivo` em português, minúsculas com
   underscore, prefixo `_` (privado ao módulo). Nome descreve a decisão
   central da função, não apenas "processa X" -- ex:
   `_construir_manifestacao_e_patologia` (constrói dois objetos a partir de
   um grupo de observações), não `_processar_grupo`.

## O que este documento não é

Não é um gate mecânico -- nada valida automaticamente que um hotspot futuro
siga isto. É uma referência para quem for implementar HOTSPOT-02..05,
revisada por leitura humana/revisor, não por CI.
