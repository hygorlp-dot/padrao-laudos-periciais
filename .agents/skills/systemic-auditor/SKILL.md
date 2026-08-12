---
name: systemic-auditor
description: Auditar sistemicamente boundaries e cadeia vertical afetada em uma terceira execução independente e read-only.
---

# Systemic Auditor

1. Ler `docs/padroes/protocolo-auditoria-sistemica.md`.
2. Não receber findings detalhados do PR Reviewer antes da análise inicial.
3. Auditar diff, consumidores, caminhos alternativos e arquivos não alterados
   relevantes ao boundary.
4. Verificar invariantes globais, schemas/runtime, privacidade, egress e gates.
5. Persistir output estruturado no HEAD exato; bloquear P0/P1 material.
