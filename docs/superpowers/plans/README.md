# Planos de engenharia (registro histórico)

```text
STATUS: HISTORICAL ENGINEERING RECORDS
```

Estes planos registram como cada entrega foi pensada e executada. Eles formam a
trilha de auditoria da engenharia e **não são autoridade atual do produto**: o
escopo, as limitações e as decisões de um plano valem para a data dele e podem
ter sido superados por entregas posteriores.

Não use estes planos para decidir o que o produto é ou deve fazer. A autoridade
atual fica em:

- [`AGENTS.md`](../../../AGENTS.md): como trabalhar;
- [`PRODUCT.md`](../../../PRODUCT.md): o que o produto é agora;
- [`DESIGN.md`](../../../DESIGN.md): como o produto se parece e se comporta;
- [`docs/padroes/`](../../padroes/): regras de domínio, profissionais e de governança;
- [`docs/arquitetura/decisoes/`](../../arquitetura/decisoes/): por que a arquitetura é assim;
- a issue de roadmap canônica no GitHub (atualmente #256).

Os arquivos permanecem no lugar para não quebrar referências existentes:
- `tests/test_frontend_shell_boundaries_v1.py` lê
  `2026-08-23-frontend-shell-v1.md`;
- o analisador protegido de arquitetura aceita este diretório como suporte de
  transição (`scripts/quality/architecture_analyzer.py`).

Qualquer movimentação futura exige que essas referências sejam atualizadas no
mesmo PR. A classificação é auditada por
`python -m scripts.quality.repository_hygiene`.
