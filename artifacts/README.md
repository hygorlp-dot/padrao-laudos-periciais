# Artefatos versionados

```text
STATUS: EVIDENCE / ASSURANCE / HISTORICAL OUTPUT — not current product authority
```

Esta pasta guarda saídas de verificação versionadas. Nenhum arquivo aqui decide
o que o produto é; a autoridade atual fica em [`PRODUCT.md`](../PRODUCT.md), em
[`docs/padroes/`](../docs/padroes/) e em
[`docs/arquitetura/decisoes/`](../docs/arquitetura/decisoes/).

| Caminho | Classe | Consumidor conhecido | Política |
|---|---|---|---|
| `native-word-matrix-v1.json` | `ASSURANCE` | `.github/workflows/capability-protected.yml`, `tests/test_office_word_native_matrix_v1.py`, `tests/test_architecture_capability_word_trust_only_rebind_v1.py` | Artefato protegido da matriz nativa do Word; muda só pelo fluxo que o gera e o protege. |
| `issue-187/BASELINE.md`, `issue-187/LONGITUDINAL.md` | `HISTORICAL` | trilha de auditoria da #187 (oráculo longitudinal) | Preservar. A ausência de referência textual não prova que podem ser removidos: são a evidência registrada daquela entrega. |

Classes:
- `ASSURANCE`: evidência consumida por gate, workflow ou teste. Remover quebra a garantia.
- `HISTORICAL`: saída de uma entrega passada, mantida como trilha de auditoria.
- `GENERATED_EPHEMERAL`: saída regenerável sem valor de auditoria. Não deve ser versionada aqui.
- `CURRENT_AUTHORITY`: nunca deve existir nesta pasta.

Estrutura futura possível (`artifacts/assurance/`, `artifacts/historical/`)
somente quando os consumidores acima forem atualizados no mesmo PR. A
classificação é auditada por `python -m scripts.quality.repository_hygiene`.
