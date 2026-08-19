# Migração, cutover e rollback V1

`CUTOVER_MUST_BE_ATOMIC = TRUE`

`NO_DEPLOYED_LEGACY_ORACLE = TRUE`: `main` não contém o gate experimental do PR #44, que permanece apenas como evidência/fixtures e nunca é mesclado. Portanto não se declara uma proteção inexistente nem se depende dele em runtime.

`NO_REDUCED_PROTECTION_WINDOW = TRUE` e `NEW_GATE_BLOCKS_ON_INTRODUCTION = TRUE`. PR-B não altera capability safety. PR-T, criado de `main` verde após PR-B, instala apenas o trust anchor capability-free: verifier mínimo, carregamento de pins e invocação do workflow em modo `INERT_TRUST_ANCHOR`, sem analyzer, policy decision ou alegação de proteção capability. Depois de mergeado e verde em `main`, esses bytes passam a ser a autoridade protegida anterior ao candidato. PR-C fornece os artefatos candidatos pinados e ativa atomicamente o capability gate já bloqueante; usa a matriz histórica do PR #44 como oracle offline de caracterização, não como código implantado. PR-D apenas consolida baseline e fecha o PR #44 como superseded sem merge.

`ROLLBACK_PER_PR = TRUE` com `REVERSE_ORDER_ROLLBACK = TRUE`. PR-A contém somente contratos; PR-B somente arquitetura; PR-T somente trust anchor inerte; PR-C capability e cutover; PR-D baseline final/supersession. Reverte-se PR-D antes de PR-C, PR-C antes de PR-T, e PR-T antes dos contratos dos quais depende. Durante a janela de compatibilidade, cada etapa mantém os artefatos requeridos pela seguinte; nenhum revert isolado em ordem inválida é prometido.

Extração usa matriz commit → arquivo → hunk → dependência → teste contra `main`; cherry-pick amplo do PR #44 é proibido. Findings históricos viram fixtures por classe, nunca design de dataflow.

Sequência: PR-A contratos → PR-B architecture analyzer → PR-T trust anchor inerte → PR-C capability boundary e cutover → PR-D baseline/supersession. Não avançar antes do post-main green de cada etapa. `TRUST_ANCHOR_MUST_PREEXIST_CUTOVER = TRUE`; PR-C bloqueia se o base protegido não contiver verifier, workflow e pin loader esperados.

## PR-C: estado real pós-recovery

PR #60 instalou os bytes do PR-C de forma não-dispositiva (`NON_DISPOSITIVE_TRUST_BOOTSTRAP`); os PRs #67/#68 fecharam o deadlock de bootstrap dos findings pré-existentes. O gate `capability-protected` já é bloqueante de fato para qualquer PR contra `main` desde então — provado por execução real, incluindo o próprio CI do PR #68 falhando exatamente pelos 16 findings de baseline conhecidos. Esse cutover final consolida essa prova como cobertura de regressão permanente (`tests/test_capability_base_owned_blocking_topology_v1.py`) e não introduz nenhum mecanismo novo.

O único item não fechado é declarativo: `config/capability-policy-v1.json`'s `activationState` continua `CONTRACT_ONLY`, um rótulo não-autoritativo (nenhum código o lê). Corrigi-lo exige um predecessor dedicado que estenda o `supportScope` `CAPABILITY_BOOTSTRAP_V1` em `architecture_analyzer.py` antes que o próprio PR que muda `capability-policy-v1.json` possa ser julgado sob esse escopo — `CODE_UNDER_REVIEW_CANNOT_CONTROL_ITS_JUDGE` proíbe fechar isso no mesmo PR. Rastreado como dívida P2.
