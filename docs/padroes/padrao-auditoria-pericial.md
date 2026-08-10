# Padrão de auditoria pericial

## Arquitetura aprovada

`MOTOR → DETECTOR RÁPIDO → GROUNDING AUDIT → DEEP AUDIT → TRILHA → GATE`.

O detector é determinístico, reproduzível e barato. A auditoria profunda examina causalidade, contradições, extrapolação normativa e conclusão além da evidência. Correções não podem ser silenciosas.

O detector reconhece negações e formas explícitas de ausência. Contradições semânticas dependentes de contexto ou antônimos devem ser examinadas pelo deep pass da Skill; não se presume compreensão linguística completa por comparação lexical.

## Claims

Tipos de auditoria: `FATO_PROCESSUAL`, `FATO_DOCUMENTAL`, `CONSTATACAO_DE_VISTORIA`, `MEDICAO`, `MANIFESTACAO_TECNICA`, `MECANISMO`, `CAUSA`, `ORIGEM`, `CRITICIDADE`, `CONFORMIDADE_NORMATIVA`, `VICIO_CONSTRUTIVO`, `REPARABILIDADE`, `ORCAMENTO`, `INFERENCIA_TECNICA`, `LIMITACAO` e `CONCLUSAO_DE_QT`.

Natureza: `FACTUAL`, `INTERPRETIVE` ou `SYNTHETIC`. Saliência: `LOAD_BEARING`, `SUPPORTING` ou `ILLUSTRATIVE`.

Vereditos: `GROUNDED`, `WEAKLY_GROUNDED`, `INTERPOLATED`, `UNSUBSTANTIATED`, `INSUFFICIENT`, `UNVERIFIABLE` e `CONTRADICTED`. São enums de auditoria e não substituem classificações periciais.

Antes de `APTO_PARA_REDACAO`, toda claim material deve estar `GROUNDED`. `WEAKLY_GROUNDED` exige ressalva adequada. Claim material interpolada, não sustentada ou contradita deve ser reduzida ou removida. `UNVERIFIABLE` não significa falso.

PAT, QT e HIP são inferências intermediárias e não constituem prova independente.
O grounding deve resolver o grafo até evidências primárias rastreáveis. Claims
normativas materiais também exigem `PROPOSITION_AUDIT_RESULT`; ausência de fonte
verificável nunca equivale a auditoria concluída.

## Fontes e independência

Priorizar: fonte primária oficial → fonte institucional → norma técnica → literatura científica → referência técnica → fonte secundária. Fonte secundária serve para descoberta, não para inventar item normativo.

Registrar `AUDITORIA_INDEPENDENTE = SIM` somente quando a verificação ocorreu em contexto separado real. A trilha registra decisão, evidência, justificativa resumida e resultado, nunca chain-of-thought.
