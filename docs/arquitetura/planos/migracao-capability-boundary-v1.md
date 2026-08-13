# Migração, cutover e rollback V1

`CUTOVER_MUST_BE_ATOMIC = TRUE`

`NO_DEPLOYED_LEGACY_ORACLE = TRUE`: `main` não contém o gate experimental do PR #44, que permanece apenas como evidência/fixtures e nunca é mesclado. Portanto não se declara uma proteção inexistente nem se depende dele em runtime.

`NO_REDUCED_PROTECTION_WINDOW = TRUE` e `NEW_GATE_BLOCKS_ON_INTRODUCTION = TRUE`. PR-B não altera capability safety. PR-T, criado de `main` verde após PR-B, instala apenas o trust anchor capability-free: verifier mínimo, carregamento de pins e invocação do workflow em modo `INERT_TRUST_ANCHOR`, sem analyzer, policy decision ou alegação de proteção capability. Depois de mergeado e verde em `main`, esses bytes passam a ser a autoridade protegida anterior ao candidato. PR-C fornece os artefatos candidatos pinados e ativa atomicamente o capability gate já bloqueante; usa a matriz histórica do PR #44 como oracle offline de caracterização, não como código implantado. PR-D apenas consolida baseline e fecha o PR #44 como superseded sem merge.

`ROLLBACK_PER_PR = TRUE` com `REVERSE_ORDER_ROLLBACK = TRUE`. PR-A contém somente contratos; PR-B somente arquitetura; PR-T somente trust anchor inerte; PR-C capability e cutover; PR-D baseline final/supersession. Reverte-se PR-D antes de PR-C, PR-C antes de PR-T, e PR-T antes dos contratos dos quais depende. Durante a janela de compatibilidade, cada etapa mantém os artefatos requeridos pela seguinte; nenhum revert isolado em ordem inválida é prometido.

Extração usa matriz commit → arquivo → hunk → dependência → teste contra `main`; cherry-pick amplo do PR #44 é proibido. Findings históricos viram fixtures por classe, nunca design de dataflow.

Sequência: PR-A contratos → PR-B architecture analyzer → PR-T trust anchor inerte → PR-C capability boundary e cutover → PR-D baseline/supersession. Não avançar antes do post-main green de cada etapa. `TRUST_ANCHOR_MUST_PREEXIST_CUTOVER = TRUE`; PR-C bloqueia se o base protegido não contiver verifier, workflow e pin loader esperados.
