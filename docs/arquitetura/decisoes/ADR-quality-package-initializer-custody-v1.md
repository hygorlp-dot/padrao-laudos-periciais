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
- Nenhum artefato capability, política temporal, produto ou armazenamento é
  alterado.
- Esta decisão não cria judge, allowlist ou handshake cross-control-plane.
