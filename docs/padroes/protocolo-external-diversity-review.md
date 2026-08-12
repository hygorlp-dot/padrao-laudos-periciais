# Protocolo de external diversity review

## Regra aprovada

`EXTERNAL_DIVERSITY_REVIEW_GATE = ENABLED`

`NO_CLAUDE_ON_INTERMEDIATE_HEAD = TRUE`

`CLAUDE_CALL_BUDGET: NORMAL_PR = 0; HIGH_RISK_FINAL_HEAD = 1; MATERIAL_FIX_AFTER_CLAUDE = +1 FINAL RETEST`

Claude é chamado uma vez por HEAD final estável quando houver trigger material,
após testes, reviews Codex, `verify_core`, CI e privacy verdes. A sessão é nova,
isolada, read-only e recebe somente pacote first-party sanitizado. Rate limit
adia apenas merge que exige Claude; não bloqueia trabalho Codex seguro.

Triggers: arquitetura material, autoridade de IA, AI Gateway, egress privado,
PII, multimodal, cadeia de evidência, causalidade, aplicabilidade normativa,
gate material, persistência destrutiva, P0/P1 material, divergência Codex,
confiança sistêmica insuficiente, finding material repetido, release de alto
risco ou governança do Bootstrap.
