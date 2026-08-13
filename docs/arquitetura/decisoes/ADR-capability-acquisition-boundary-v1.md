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
- O cutover é atômico e o gate legado permanece bloqueante até paridade comprovada.
- O capability analyzer não pode se autoautorizar; bootstrap de integridade é separado.
