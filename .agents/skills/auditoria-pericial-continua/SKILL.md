---
name: auditoria-pericial-continua
description: Executar detector pericial determinístico e auditoria profunda sobre PAT, questões técnicas, quesitos, evidências e fontes. Usar durante alterações do pipeline e antes de gates, sem processar automaticamente referencias/privadas nem corrigir conclusões silenciosamente.
---

# Auditoria pericial contínua

1. Ler `AGENTS.md` e `docs/padroes/padrao-auditoria-pericial.md`.
2. Executar `scripts.auditoria_pericial.executar_detector` sobre artefatos sintéticos ou dados locais explicitamente autorizados.
3. Deduplicar achados por tipo e conjunto de evidências.
4. Classificar achados como `CRITICO`, `IMPORTANTE` ou `EDITORIAL`.
5. Executar `executar_deep_audit` para causalidade, extrapolação e claims materiais.
6. Não alterar o artefato silenciosamente; apresentar achado, evidência e ação necessária.
7. Bloquear o gate quando uma claim material exceder a evidência.

Não aplicar regras visuais do Impeccable a contratos ou conclusões periciais. Manter auditoria manual enquanto a interface oficial de hooks do Codex não estiver confirmada.
