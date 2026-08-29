# E1B publication privacy V1

## Autoridades separadas

- `scripts/quality/publication_privacy.py`: regra first-party para caminhos
  privados e proveniência de fixtures. Sua integração direta ao `GateResult`
  exige rotação protegida mínima e separada, ainda dentro da Issue #137.
- `.gitleaks.toml` + `scripts/quality/run_gitleaks.ps1`: detector advisory de
  segredos e padrões complementares.
- `tests/fixtures/core-fixtures.json`: declaração positiva e auditável de que
  cada fixture é sintética.

Gitleaks não decide se uma fixture é aceitável e não substitui a política
first-party. Nenhuma allowlist de commit ou finding foi criada.

Enquanto a rotação protegida sucessora não for mergeada, o teste first-party
é executado de forma bloqueante pela suíte explícita de repository safety do
`verify_core`; esse estado intermediário não constitui conclusão de E1B.

## Modos obrigatórios

1. `current tree`: snapshot exato dos arquivos rastreados;
2. `reachable history`: todos os commits alcançáveis pelos refs presentes;
3. `pre-publication`: os dois modos antes de publicar qualquer ref.

Checkout raso é insuficiente para o segundo modo. O CI aplicável usa
`fetch-depth: 0`. Objetos Git inalcançáveis não integram o contrato de
publicação; refs remotos que serão publicados integram.

## Privacidade dos resultados

Relatórios de Gitleaks existem apenas em diretório temporário e são apagados.
O console recebe contagem, versão e estado, nunca o segredo. Findings
first-party contêm somente regra, caminho e commit quando aplicável.

`PRIVATE_EGRESS = FALSE`: os bytes do repositório não são enviados ao
fornecedor. A única rede é aquisição do binário público oficial pinado.
