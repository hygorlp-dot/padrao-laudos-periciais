---
name: auditoria-grounding-pericial
description: Extrair e auditar claims periciais contra evidências documentais, de vistoria, medições e fontes normativas. Usar para verificar causalidade, origem, criticidade, vício, orçamento, conclusão de QT e respostas a quesitos antes do gate.
---

# Grounding pericial

1. Extrair claims sem fundir manifestação, mecanismo, causa e origem.
2. Classificar tipo pericial, natureza `FACTUAL`, `INTERPRETIVE` ou `SYNTHETIC` e saliência.
3. Aplicar máxima verificação a `LOAD_BEARING`.
4. Fornecer ao auditor somente claim, evidências, fontes e limitações.
5. Usar `auditar_claim` e emitir `GROUNDED`, `WEAKLY_GROUNDED`, `INTERPOLATED`, `UNSUBSTANTIATED`, `INSUFFICIENT`, `UNVERIFIABLE` ou `CONTRADICTED`.
6. Não tratar `UNVERIFIABLE` como falso.
7. Reduzir, ressalvar ou remover claim material não sustentada antes do gate.

Somente `EVIDENCIA_PRIMARIA` pode sustentar diretamente uma claim. `HIP`, `PAT`,
`QT`, conclusões e modelos são `INFERENCIA_INTERMEDIARIA`; o suporte deve ser
resolvido até folhas `OBS`, `MED`, `FOT`, `DOC`, `ENS` ou requisito normativo
verificado. Nunca usar o artefato que originou a claim como sua própria prova.
Compatibilizar o tipo da fonte com o tipo da claim: `NOR` pode sustentar
requisito, método, critério, definição, escopo, aplicabilidade temporal e a
comparação normativa explicitamente executada; não pode, isoladamente,
sustentar manifestação, medição, mecanismo, causa ou outro fato físico do caso.

Claim Audit upstream é referência metodológica MIT e não substitui os enums ou critérios periciais canônicos.
