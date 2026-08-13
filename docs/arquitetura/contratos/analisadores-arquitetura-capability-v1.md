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
