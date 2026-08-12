---
name: external-diversity-review
description: Preparar e executar uma revisão externa Claude somente no HEAD final estável quando o gate determinístico exigir.
---

# External Diversity Review

1. Ler `docs/padroes/protocolo-external-diversity-review.md`.
2. Recalcular triggers; não chamar Claude em HEAD intermediário.
3. Executar External Egress Gate e bloquear PII, secrets, binários, casos e
   qualquer caminho de `referencias/privadas/`.
4. Usar sessão nova, checkout isolado e permissões read-only; nunca resume,
   bypass ou modo perigoso.
5. Solicitar revisão arquitetural, adversarial, ranking, invariantes, gaps e
   APPROVED/BLOCKED em uma única chamada por HEAD final.
6. Persistir review estruturada e vinculada ao SHA; finding material reinicia
   o ciclo first-party antes de nova chamada final.
