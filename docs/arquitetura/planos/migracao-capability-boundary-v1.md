# Migração, cutover e rollback V1

`CUTOVER_MUST_BE_ATOMIC = TRUE`

`LEGACY_GATE_REMAINS_BLOCKING = TRUE` até o replacement capability gate estar integrado, com matriz completa, paridade ou proteção superior, full Core, CI exato e revisões frescas verdes.

`NO_REDUCED_PROTECTION_WINDOW = TRUE`. PR-B não remove proteção. PR-C introduz o gate novo e executa shadow/parity com o legado. PR-D remove apenas a implementação obsoleta após prova exata e fecha o PR #44 como superseded sem merge.

`ROLLBACK_PER_PR = TRUE`. PR-A contém somente contratos; PR-B somente arquitetura; PR-C capability e cutover; PR-D baseline final e remoção legada. Cada revert restaura o estado anterior sem depender de outro revert.

Extração usa matriz commit → arquivo → hunk → dependência → teste contra `main`; cherry-pick amplo do PR #44 é proibido. Findings históricos viram fixtures por classe, nunca design de dataflow.

Sequência: PR-A contratos → PR-B architecture analyzer → PR-C capability boundary e cutover → PR-D baseline/supersession. Não avançar Phase B antes do post-main green de cada etapa.
