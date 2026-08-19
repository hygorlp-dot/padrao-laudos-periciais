# Contratos dos analisadores V1

## ARCHITECTURE_ANALYZER_V1

Recebe inventário e ASTs de infraestrutura injetada. Produz módulos, ownership, componentes, layers, dependency edges, unresolved first-party imports, cycles, dívida arquitetural e bypasses exclusivamente arquiteturais. Não decide capability safety e não importa o capability analyzer.

## CAPABILITY_ANALYZER_V1

Recebe o mesmo tipo de inventário/AST independente. Produz somente aquisição de capability, escape de namespace sensível, import/execução dinâmica, desserialização executável/native loading e decisões do registro próprio de exceções. É side-effect free, capability-free e não importa o architecture analyzer.

## POLICY_FREE_SHARED_INFRASTRUCTURE

Pode conter apenas inventário Git do HEAD candidato, canonicalização/validação de path, leitura segura, parsing AST e estrutura normalizada de finding. Não contém taxonomia, allowlist, baseline decision ou policy engine.

Todo finding contém `analyzer`, `policyVersion`, `code`, path/módulo canônicos, localização e AST normalizado. Falhas de inventário, leitura, encoding, arquivo irregular, parse ou política bloqueiam.

## DUAL_FINDINGS_ALLOWED

O mesmo AST pode produzir dois findings independentes. Nenhum analisador filtra ou autoriza o outro. A composição ocorre somente no orquestrador `verify_core`.

## Universo

Todos os Python first-party tracked no HEAD candidato e novos arquivos Python candidatos sob roots versionadas são inventariados. Tests, fixtures, vendor e generated recebem classificação explícita; não desaparecem por heurística de conteúdo.

O input obrigatório é `(candidateCommitSha, candidateTreeSha)`. `COMMIT_TREE_MATCH_REQUIRED = TRUE`: o bootstrap valida que o primeiro objeto é commit, o segundo é tree e `candidateTreeSha == tree(candidateCommitSha)`; qualquer divergência bloqueia. `SAME_CANDIDATE_TREE_BYTES = TRUE`: inventário e conteúdo lido/parsing vêm desse mesmo Git tree exato, nunca da working tree. SHA inválido, objeto ausente, symlink, arquivo não regular, erro de leitura/encoding ou parse bloqueiam.

`MODULE_PATH_CONSISTENCY_REQUIRED = TRUE`: paths são relativos, NFC, separados apenas por `/`, sem segmentos vazios, `.` ou `..`, e sob root de produção; módulo é derivado deterministicamente do path e deve coincidir. A mesma canonicalização vale para findings e exceções.

## Exceções e bootstrap

`BASELINE_MUST_BE_ANCESTOR = TRUE` e o ancestral é designado fora do HEAD candidato. `EXCEPTION_MUST_PREEXIST_IN_BASELINE = TRUE`: o registro, path e blob excepcionados precisam existir no tree do baseline; exceção criada no HEAD analisado não pode autorizá-lo. `EXPIRED_EXCEPTION_BLOCKS = TRUE`, `DUPLICATE_EXCEPTION_BLOCKS = TRUE`; ausência, staleness, divergência de finding/AST/blob/path/módulo/policy/rule/analyzer ou baseline bloqueia. Não há suppressions inline nem curingas.

O bootstrap de integridade é um verificador mínimo separado, sem imports/capabilities cobertos e fora do analyzer e do registro ordinário. Ele compara blobs do analyzer, policy e schema com digests SHA-256 pinados em configuração protegida pelo branch gate. Falha de leitura, digest, pin ou schema bloqueia. O analyzer não pode autorizar o bootstrap. Atualizar pins exige PR próprio, CI exato e as três revisões independentes.

Uma rotação de trust anchor usa `config/architecture-protected-transition-v1.json`,
validado exclusivamente pelo verificador proveniente do base protegido. O manifesto
declara o SHA do base e os blob IDs exatos anterior e candidato de cada artefato
alterado. A transição falha fechada se houver remoção, identidade divergente,
artefato omitido/duplicado ou alteração de produção fora do conjunto protegido;
somente testes e documentação arquitetural podem acompanhar a rotação. O manifesto
não concede autoridade: o PR dedicado continua condicionado a CI exato e às três
revisões independentes.

A TCB mínima inclui o próprio bootstrap, workflow bloqueante, inventário Git, leitor/parser AST, capability analyzer, policy e schemas, adaptador que entrega findings e `verify_core` que os torna bloqueantes. `PROTECTED_BASE_LOADS_AND_EXECUTES_VERIFIER = TRUE`: CI obtém workflow, verifier e pin registry do commit-base protegido, nunca aceita esses bytes do candidato como autoridade sobre si mesmos. Todos os demais artefatos de enforcement no candidato têm SHA-256 individual no registro externo. Ausência, alteração, conjunto divergente, digest divergente ou tentativa de exceção ordinária bloqueia antes da análise.

## Declaração legada versus autoridade de runtime

A autoridade real é o comportamento do bootstrap executado a partir do base protegido, não qualquer campo declarativo em `config/capability-policy-v1.json`. Nenhum código de enforcement lê `integrityBootstrap.activationState`; esse campo é texto de contrato histórico, verificável apenas por leitura, nunca por efeito. A prova de bloqueio real está em execução — `tests/test_capability_base_owned_blocking_topology_v1.py` exercita `capability_bootstrap.run_protected_capability_gate` de ponta a ponta contra um base sintético e confirma: candidato seguro produz `[]`, mutação do próprio registro de exceções falha fechado, e cada reproducer transferido continua bloqueado.
