# Protocolo de autonomia do agente

## Regra aprovada

`DEFAULT_ACTION = DECIDE_AND_PROCEED`

`HUMAN_ESCALATION = EXCEPTION_ONLY`

`SELF_RECOVERY = TRUE`

`FAIL_CLOSED = TRUE`

O agente resolve escolhas reversíveis e bem delimitadas com fontes e contratos
do repositório. Escala somente autoridade nova, egress privado, custo novo,
operação destrutiva sem rollback, decisão pericial, login/MFA ou divergência
material irresolúvel.

Mudança material segue reprodução → RED → causa-raiz → correção mínima →
adversariais → regressão → revisão → verificação final.

## Autonomia operacional durável

Vale somente depois que o usuário autorizou expressamente um objetivo de
engenharia, item de roadmap ou Issue existente. Dentro desse escopo, a
mecânica ordinária de execução não exige confirmação humana passo a passo.

### Ações sempre autônomas

Leitura/análise: inspecionar repositório e histórico Git, estado read-only do
GitHub, CI e logs, pesquisa permitida pelas regras de privacidade, investigar
causa-raiz, comparar alternativas, tomar decisão de implementação reversível.

Engenharia local: criar/trocar branch de feature local, criar worktree
temporário, editar arquivos dentro do escopo da Issue, adicionar/atualizar
teste, depurar, refatorar dentro do escopo aprovado, rodar teste
focado/completo, rodar quality gates, fazer benchmark, commitar mudança
coerente, limpar recurso local temporário quando seguro.

### Ações remotas ordinárias

Autônomas quando todas as precondições abaixo valem: a Issue correspondente
já existe ou o usuário já pediu explicitamente o objetivo sem Issue
duplicada; a branch, o push, o PR, o CI, a revisão proporcional ao risco e o
merge normal permanecem dentro do escopo já autorizado; nenhum limite
humano-apenas (abaixo) é cruzado.

Nessas condições, são autônomos: criar a Issue correspondente; push da
branch aprovada; criação do PR; atualização de descrição/evidência do PR;
publicar evidência factual em PR/Issue; reexecutar CI não-destrutiva quando
justificado; solicitar/rodar o conjunto de revisão delimitado pelo
risco/contrato; merge NORMAL quando os checks obrigatórios passam e
`P0_OPEN = 0` e `P1_OPEN = 0`; fechar a Issue como completa quando seus
critérios de aceite forem satisfeitos; avançar para o próximo item de um
roadmap já autorizado.

Não perguntar "posso continuar?", "posso rodar os testes?", "posso dar
push?", "posso criar o PR?", "posso inspecionar o CI?", "posso chamar o
revisor?", "posso mergear normalmente?" quando a ação já está dentro de um
objetivo autorizado e todas as precondições explícitas estão satisfeitas.

### Limite humano-apenas

Aprovação humana continua obrigatória para: mudança de proteção de branch ou
de required checks, merge admin/bypass, enfraquecer ou desabilitar gate de
segurança protegido, mudança de administração de segurança do repositório,
segredos/credenciais, login/MFA; force push a história compartilhada/
protegida, reescrita de história protegida, operação remota destrutiva sem
rollback confiável, exclusão de trabalho remoto único; nova trust boundary,
nova família de política de segurança, novo judge protegido, novo trust
anchor, nova autoridade de analyzer, novo mecanismo de exceção,
enfraquecimento material de comportamento fail-closed; escolha de direção de
produto com alternativas materialmente viáveis, juízo profissional/pericial,
conclusão jurídica reservada ao Juízo/perito, novo compromisso de custo/
serviço pago, egress de dado privado não já autorizado; novo predecessor
criado só para viabilizar outro predecessor, desvio material de roadmap,
decisão arquitetural não resolvida com trade-off material de longo prazo.

### Congelamento anti-loop pós-bootstrap

`TRUST_INFRASTRUCTURE_PHASE = TERMINATED` uma vez declarado
`ARCHITECTURE_BOOTSTRAP_CLOSED = TRUE` e `CAPABILITY_BOOTSTRAP_CLOSED = TRUE`.
Qualquer proposta futura cujo objetivo principal seja bootstrap de
capability, preparação de trust anchor, plumbing de transição architecture/
capability, redesenho de judge protegido, expansão de supportScope ou "mais
um PR final de hardening" é tratada como `LOOP_REGRESSION_SUSPECTED = TRUE` e
não é implementada automaticamente. Um novo defeito de segurança concreto
pode justificar reabrir a área, somente com evidência explícita e
autorização humana. Issues de rastreamento (`TRACKING_ONLY`) não são
agendadas nem viram PR automaticamente.

### Regra anti-predecessor

`NEW_PREDECESSOR_DEFAULT = PROHIBITED`. Diante de um problema inesperado
dentro de um PR ordinário: determinar se é P0/P1; determinar se cabe corrigir
dentro do PR atual; corrigir no PR atual sempre que seguro. Não criar outro
PR preparatório só porque isso facilitaria a implementação. Só escalar
quando `NEW_MATERIAL_P0_OR_P1 = TRUE` E `CAN_FIX_IN_CURRENT_PR = FALSE` E
`STRUCTURAL_DEVIATION_IS_MATERIAL = TRUE` — e mesmo assim sem criar o
predecessor antes da decisão humana.

### P0/P1/P2

`P0 = NO MERGE`. `P1 material = NO MERGE`. `P2 = dívida não-bloqueante`. P2
não pode mutar um HEAD terminal/pronto para merge só por polimento. Registrar
P2 em Issue apenas quando perdê-lo criaria dívida silenciosa relevante; não
criar Issue de rastreamento para toda observação cosmética.

### Revisão proporcional ao risco

Revisão proporcional ao risco, não automaticamente três revisores em
trabalho ordinário. PR material ordinário usa `PR_REVIEWER` e
`SYSTEMIC_AUDITOR` quando o risco sistêmico é material.
`CLAUDE_EXTERNAL_DIVERSITY_REVIEWER` somente quando o contrato first-party
já exige (ver `docs/padroes/protocolo-external-diversity-review.md`) ou uma
perspectiva externa genuinamente independente mudaria a garantia de forma
material. `NO_REVIEW_LOOP = TRUE`: se os revisores terminais exigidos
retornam `P0=0`/`P1=0`, parar de revisar — sem revisor extra por reasseguro.
Um novo HEAD invalida somente a garantia materialmente afetada por essa
mudança.

### Comportamento de relato

Não narrar comando rotineiro nem progresso intermediário. Manter evidência
suficiente no PR/Issue. Retornar ao usuário somente para: um limite
humano-apenas real; um P0/P1 material não resolvido que exige decisão; ou
sucesso terminal/marco relevante. Esperar CI ordinário não é decisão humana.
Sucesso de teste ordinário não é decisão humana. Mecânica ordinária de
branch/push/PR deixa de ser decisão humana depois que esta política estiver
ativa em `main` protegida.

### Fail-closed antes do merge normal

Antes do merge normal autônomo, verificar estado remoto fresco: repositório
correto, Issue correta, base correta, HEAD exato pretendido, CI obrigatório
verde, revisões obrigatórias completas, `P0_OPEN = 0`, `P1_OPEN = 0`, nenhuma
mudança inesperada de trust/security boundary, branch mergeável normalmente.
Se qualquer item falhar, não mergear; corrigir autonomamente quando dentro do
escopo; escalar somente ao cruzar um limite humano-apenas.

### Relação com outros mecanismos de autonomia

Esta seção governa a operação interativa do agente em chat com o usuário
autorizando objetivos. Não substitui nem satisfaz por si só a prova formal de
independência de `scripts/agentic/gates.py`, que exige raiz de confiança
externa verificável e rejeita evidência de revisão produzida no mesmo
repositório pelo mesmo produtor. Não reabre nem estende a delegação expirada
e de escopo específico de `docs/padroes/protocolo-autonomia-phase-b.md`.
