# ADR — CAPABILITY_ACQUISITION_BOUNDARY_V1

## Estado

ACEITA PARA IMPLEMENTAÇÃO EM PRs SEPARADOS. O PR #44 permanece congelado e não será mergeado.

## Contexto e decisão

Rastrear proveniência arbitrária por todo o dataflow Python não convergiu. A segurança passa a bloquear a primeira aquisição de capability ou o primeiro escape de namespace sensível. O código inspecionado nunca é importado ou executado.

`ARCHITECTURE_ANALYZER_V1` e `CAPABILITY_ANALYZER_V1` são autoridades independentes. O primeiro decide somente topologia arquitetural; o segundo decide somente capability safety. Eles não se importam nem se chamam. A composição ocorre apenas em `verify_core`.

O subset Python seguro é restrito e fail-closed. Import dinâmico, execução dinâmica, namespace exclusivamente processual, membro processual conhecido de `os` e escape/reflexão de namespace sensível exigem finding. Código legítimo depende de exceção exata, auditável e vinculada ao baseline.

## Consequências

- Não há interpretação abstrata downstream de containers ou controle de fluxo.
- Um AST pode gerar findings independentes nos dois analisadores.
- A infraestrutura compartilhada é policy-free.
- Não há oracle legado implantado em `main`: o código experimental do PR #44 permanece congelado e nunca é mergeado. O gate novo entra bloqueante atomicamente no PR-C; paridade ou proteção superior é provada contra fixtures offline de caracterização do PR #44, não contra runtime legado.
- O capability analyzer não pode se autoautorizar; bootstrap de integridade é separado.
- A primeira ativação exige um PR-T anterior: trust anchor capability-free e inerte já mergeado no base protegido. O PR-C não pode introduzir a autoridade que valida seus próprios bytes.

## Estado pós-recovery (#67/#68) e cutover final

A autoridade de runtime é o job `capability-protected` executando `capability_bootstrap.py` a partir do base protegido — bloqueante de fato desde que `capability_bootstrap.py` passou a `PRESENT` no registro protegido (pós-#60) e com um conjunto de exceções de baseline funcional (pós-#67/#68). Isso é provado por execução real em `tests/test_capability_base_owned_blocking_topology_v1.py`, não apenas declarado.

`config/capability-policy-v1.json`'s `integrityBootstrap.activationState` permanece textualmente `CONTRACT_ONLY`. Esse campo não é lido por nenhum caminho de enforcement — é rótulo de contrato histórico, não switch de runtime. Ele não foi atualizado no cutover final porque fazê-lo exige editar `capability-policy-v1.json` e seu schema (ambos rastreados pelo registro de capability), o que em cascata exigiria estender o `supportScope` `CAPABILITY_BOOTSTRAP_V1` em `architecture_analyzer.py` — e `CODE_UNDER_REVIEW_CANNOT_CONTROL_ITS_JUDGE` impede que essa extensão valha para o próprio PR que dela precisa. Fechar isso requer um predecessor dedicado; até lá, é dívida documental aceita (P2), não lacuna funcional.
