---
name: ui-pericial
description: Adaptar UI, UX e motion ao aplicativo pericial de produtividade, com estados assíncronos claros, acessibilidade e complexidade progressiva. Usar em React, Tauri, CSS, modais, drawers, toasts, loading, skeleton, progress, hover, press, navegação e microinterações do produto pericial.
---

# UI pericial

1. Ler `../design-motion-principles/SKILL.md` e o workflow aplicável.
2. Tratar o produto como `PRODUCTIVITY_TOOL`.
3. Ponderar Emil Kowalski como `PRIMARY`, Jakub Krehel como `SECONDARY` e
   Jhey Tompkins como `SELECTIVE`, apenas para onboarding, empty states e
   momentos raros de delight.
4. Manter lógica pericial material fora da interface.
5. Organizar informação em nível simples, técnico e auditoria.

## Motion

- Usar movimento funcional, nunca decorativo por padrão.
- Minimizar movimento em ações frequentes e removê-lo de ações por teclado.
- Usar entradas curtas e suaves; saídas mais sutis e normalmente mais curtas.
- Evitar parallax, zoom dramático, spin, bounce excessivo e animação contínua.
- Implementar `prefers-reduced-motion`; a interface deve funcionar sem motion.
- Preferir `transform`, `opacity` e `filter`; evitar propriedades que provoquem
  layout/reflow desnecessário.

## Operações assíncronas

- Representar somente estados aplicáveis entre `IDLE`, `QUEUED`, `LOADING`,
  `PROGRESS`, `SUCCESS`, `ERROR` e `CANCELLED`.
- Usar skeleton com geometria próxima da saída final e lazy loading quando
  pertinente; não usar spinner como resposta universal.
- Mostrar progresso real quando mensurável e estado indeterminado caso
  contrário. Nunca fabricar porcentagem.
- Oferecer retry, cancelamento, success, error e empty state quando cabíveis.
- Traduzir erro interno em mensagem clara e acionável, sem expor stack trace,
  schema ou identificadores internos no nível simples.
