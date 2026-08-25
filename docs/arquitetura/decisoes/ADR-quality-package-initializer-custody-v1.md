# ADR — QUALITY_PACKAGE_INITIALIZER_CUSTODY_V1

## Status

APROVADA pelo proprietário humano em 2026-08-25 para a Issue #114.

## Contexto

Ao executar `python -m scripts.quality.verify_core`, Python carrega
`scripts/quality/__init__.py` antes do submódulo protegido. Uma alteração
exclusiva no initializer foi reproduzida influenciando o runtime com os bytes
de `verify_core.py` inalterados. Isso permite que código sob revisão interfira
na execução protegida e viola `CODE_UNDER_REVIEW_CANNOT_CONTROL_ITS_JUDGE`.

## Decisão

Adicionar o path canônico exato `scripts/quality/__init__.py` ao conjunto
`PROTECTED_ARCHITECTURE_ARTIFACTS` do Architecture Analyzer V1. O próprio
analyzer é rotacionado pelo manifest V2 existente, validado pelo analyzer da
base protegida. Os bytes do initializer não mudam neste predecessor.

## Limites

- Nenhum prefixo, wildcard ou lookalike é aceito.
- Identidade inclui path, modo Git, tipo de objeto e blob SHA.
- O commit A não altera artefatos capability, política temporal, produto ou
  armazenamento.
- Esta decisão não cria judge, allowlist ou handshake cross-control-plane.

## Rebind conjunto autorizado

`ARCHITECTURE_CAPABILITY_EXCEPTION_REBIND_V1` autoriza um único commit B
sobre `f00bb46f60431376f8fe7bc5bba497aaf09670d9`. O commit B atualiza somente
a identidade exata da exceção preexistente de
`PROCESS_NAMESPACE_ACQUISITION` do Architecture Analyzer e as identidades
protegidas/transições necessárias para que os dois control planes descrevam o
mesmo candidato.

O rebind preserva path, módulo, localização, AST normalizada, finding,
capability, justificativa, owner e disposition. Não adiciona exceção,
wildcard ou autoridade de pacote. O commit A e os bytes do analyzer nele
fixados permanecem imutáveis.
