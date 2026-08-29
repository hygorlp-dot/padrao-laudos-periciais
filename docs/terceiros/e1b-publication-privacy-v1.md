# E1B publication privacy V1

## Autoridades separadas

- `scripts/quality/publication_privacy.py`: regra first-party bloqueante para
  caminhos privados e proveniência de fixtures. A suíte explícita de
  repository safety a executa no workflow obrigatório `core-safety`.
- `.gitleaks.toml` + `scripts/quality/run_gitleaks.ps1`: detector advisory de
  segredos e padrões complementares.
- `tests/fixtures/core-fixtures.json`: declaração positiva e auditável de que
  cada fixture é sintética.

Gitleaks não decide se uma fixture é aceitável e não substitui a política
first-party. Nenhuma allowlist de commit ou finding foi criada.

Por decisão humana na Issue #137, `scripts/quality/verify_core.py` permanece
byte-idêntico ao `main` protegido. A execução dos dois modos pelo teste
first-party integra o mesmo caminho requerido de `core-safety`: qualquer
finding faz o pytest retornar status não zero e bloqueia o merge. A colocação
fora de `GateResult` não reduz a cobertura nem converte a violação em aviso.

`GATE_PLACEMENT != SECURITY_STRENGTH`: neste desenho, o boundary de merge é o
mesmo, a falha é fechada e o oracle exercitado é o mesmo.

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
