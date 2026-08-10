---
name: trilha-auditoria-pericial
description: Registrar execução, fontes, decisões, inferências resumidas, auditorias, correções e validações humanas de atividades periciais. Usar para produzir trilha profissional auditável sem salvar chain-of-thought, scratchpad ou raciocínio oculto.
---

# Trilha de auditoria pericial

1. Usar `registrar_trilha` e validar com `schemas/trilha-auditoria-agente.schema.json`.
2. Registrar decisão, evidência, justificativa técnica resumida e resultado.
3. Identificar Skills, normas, modelos, fontes online, inputs e outputs efetivamente usados.
4. Registrar `AUDITORIA_INDEPENDENTE = SIM` somente quando houver contexto separado real.
5. Registrar alterações humanas sem atribuí-las ao agente.
6. Nunca armazenar chain-of-thought, scratchpad ou raciocínio oculto.
7. Manter trilhas reais em `referencias/privadas/`.
