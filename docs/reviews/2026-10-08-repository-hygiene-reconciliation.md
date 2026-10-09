# REPOSITORY_HYGIENE_V1 — reconciliação #279/#280

STATUS: HISTORICAL ENGINEERING RECORD

## Base e estratégia

A autoridade observada para esta reconciliação foi main
`0e71469934f7d70f76b5471930769a0218703126`, após a #276 terminal.
Os cinco commits do HEAD histórico `81a413f5d08495ef37521cf855041ebe28474f66`
foram preservados por merge normal da main, sem rebase mecânico ou force-push.
A comparação semântica dos 15 caminhos originais encontrou documentação ainda
necessária, a mesma lacuna de maturidade e nenhum auditor equivalente integrado.

O plano local não rastreado `2026-10-08-higiene-profunda-retomada.md` permaneceu
intacto (SHA-256 `de552b6959345d64090923656c7a5b7eb32c278ced5a894302e308483ef5b429`).
É preparação histórica, não autoridade: não foram portados novos analisadores
de símbolos, TypeScript ou infraestrutura de trust.

## Resultado material

- PRODUCT acompanha as rotas, workspaces, Local API e Application Layer vivos.
  Shell V1 aparece somente como origem histórica; capacidades futuras não são promessas.
- README mantém arquitetura, execução, autoridades, privacidade e validação;
  estado temporal remete às autoridades de maturidade/roadmap/Human RC.
- Schemas são documentados por famílias; contratos legados continuam preservados.
- `evidence_base_sha` conserva evidência histórica. HEAD vivo vem de `.git`.
  `human_rc_ready=false`, candidato atual nulo e aceite humano falso; o candidato
  histórico conserva sua antiga readiness sem promovê-la ao estado operacional.
- O mapa de autoridade distingue documentos atuais, histórico, assurance,
  runtime, configuração, referência e legado ainda vivo.
- O auditor continua read-only, sem subprocess/network ou remoção. Índice público
  é filtrado lexicalmente antes de I/O; links/reparse points são recusados antes
  de abrir bytes. Fixtures reutilizam o registry existente com leitor/inventário
  públicos, mantendo o comportamento dos chamadores anteriores.
- `--check` rejeita apenas quebra determinística do contrato. Candidatos são advisory.

## Limites de reachability

Python usa imports, pacotes, `__main__`, roots e referências literais; frontend
usa imports/reexports, CSS, HTML e testes. Esses grafos conservadores preservam
possíveis consumidores, sem provar execução ou resolver reflexão/aliases dinâmicos.
Referência textual a schema em Python é `PYTHON_REFERENCE`, nunca prova de
`RUNTIME_VALIDATOR`. Ausência de referência não é prova positiva de remoção.
Skills são classificadas pelo router atual integrado pela #276; não há nova integração.

O relatório JSON contém o inventário público completo e os consumidores por
família; o Markdown também lista cada caminho classificado. Reproduzir com:

```powershell
python -m scripts.quality.repository_hygiene --format json --check
python -m scripts.quality.repository_hygiene --format markdown --check
python -m scripts.quality.product_maturity
```

A execução antes do commit deste registro observou 1109 arquivos públicos,
zero violações, zero Skills sem rota, zero schemas órfãos e zero findings de
fixtures. Este registro será ele próprio classificado como histórico quando
indexado; números são evidência dessa execução, não uma constante do produto.
Resultados do HEAD final, reviews e CI ficam no checkpoint da PR #280.

`AUTO_DELETE=FALSE`; `FILES_DELETED=0`; `PRODUCT_RUNTIME_BEHAVIOR_CHANGE=FALSE`;
`PRIVATE_EGRESS=FALSE`; `HUMAN_RC_READY=FALSE`. Sem dados reais ou leitura privada.
