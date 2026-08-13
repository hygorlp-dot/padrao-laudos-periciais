# Migração, cutover e rollback V1

`CUTOVER_MUST_BE_ATOMIC = TRUE`

`NO_DEPLOYED_LEGACY_ORACLE = TRUE`: `main` não contém o gate experimental do PR #44, que permanece apenas como evidência/fixtures e nunca é mesclado. Portanto não se declara uma proteção inexistente nem se depende dele em runtime.

`NO_REDUCED_PROTECTION_WINDOW = TRUE` e `NEW_GATE_BLOCKS_ON_INTRODUCTION = TRUE`. PR-B não altera capability safety. PR-C introduz policy, bootstrap e capability gate juntos, já bloqueantes no mesmo commit; usa a matriz histórica do PR #44 como oracle offline de caracterização, não como código implantado. PR-D apenas consolida baseline e fecha o PR #44 como superseded sem merge.

`ROLLBACK_PER_PR = TRUE` com `REVERSE_ORDER_ROLLBACK = TRUE`. PR-A contém somente contratos; PR-B somente arquitetura; PR-C capability e cutover; PR-D baseline final/supersession. Reverte-se PR-D antes de PR-C e PR-C antes dos contratos dos quais depende. Durante a janela de compatibilidade, PR-C mantém todos os artefatos requeridos pelo rollback; nenhum revert isolado em ordem inválida é prometido.

Extração usa matriz commit → arquivo → hunk → dependência → teste contra `main`; cherry-pick amplo do PR #44 é proibido. Findings históricos viram fixtures por classe, nunca design de dataflow.

Sequência: PR-A contratos → PR-B architecture analyzer → PR-C capability boundary e cutover → PR-D baseline/supersession. Não avançar Phase B antes do post-main green de cada etapa.
