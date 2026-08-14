# Architecture Trust Anchor Rotation V1 Repair

## Finding

`PR50-PROTECTED-ARTIFACT-EVOLUTION-DEADLOCK` reproduziu
`ARCHITECTURE_PROTECTED_ARTIFACT_MISMATCH` para qualquer atualização futura do
analyzer protegido. O contrato exigia PR dedicado, CI exato e três revisões,
mas não havia caminho determinístico para essa transição.

## Causa-raiz

O verificador do base comparava igualdade absoluta dos blobs protegidos e não
distinguia autoalteração ordinária de uma rotação dedicada e integralmente
pinada.

## Correção delimitada

- [x] RED: rotação exata continuava bloqueada.
- [x] GREEN: manifesto candidato com base e blobs exatos, validado pelo
  executável protegido.
- [x] Adversarial: alteração de produção misturada e remoção de artefato
  protegido permanecem bloqueadas.
- [ ] Regressão integral, revisão fresh, CI do HEAD exato e external diversity
  review antes do merge.

O manifesto não aprova o próprio PR. A autoridade permanece no branch gate,
CI exato e três revisões independentes. Capability analysis e os quatro P1
transferidos continuam fora do Architecture Analyzer e abertos para
`CAPABILITY_ANALYZER_V1`.
