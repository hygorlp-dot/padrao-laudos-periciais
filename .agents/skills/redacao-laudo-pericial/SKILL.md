---
name: redacao-laudo-pericial
description: Redigir o modelo semântico e os blocos do laudo a partir de PAT_FINAL, QT e QUE saneados, preservando integralmente o gate e a responsabilidade técnica do perito.
---

# Redação autônoma do laudo pericial

1. Ler `AGENTS.md` e os padrões aplicáveis em `docs/padroes/`.
2. Identificar o tipo de perícia e selecionar o modelo documental adequado.
3. Consultar o gate técnico; não redigir matéria bloqueada.
4. Montar o plano a partir de processo, delimitação, QT, QUE e `PAT_FINAL`.
5. Redigir a síntese e o tema controvertido; separar tema, objeto e objetivo.
6. Redigir metodologia, vistoria e as quatro seções canônicas de cada PAT sem
   recalcular causa, origem, criticidade ou conclusão.
7. Gerar conclusão, quadro-resumo e resposta final ao tema.
8. Responder quesitos sem criar conclusão e preparar orçamento condicional.
9. Listar somente referências efetivamente utilizadas.
10. Preservar em `CLAIM-RED-NNN` a proveniência de toda afirmação material.
11. Executar grounding, auditoria de fidelidade e auditoria de linguagem.
12. Autocorrigir somente problemas editoriais sem efeito técnico.
13. Aplicar o gate final e gerar o modelo semântico e o Markdown de teste.

## Restrições

- Nunca preencher lacuna por plausibilidade ou criar verdade técnica.
- Nunca fazer o texto retroagir para alterar silenciosamente o `PAT_FINAL`.
- Não transformar alegação ou declaração em constatação.
- Não transformar `NÃO CONSTATADA` em `INEXISTENTE`.
- Não usar norma sem verificação, pertinência e aplicabilidade temporal.
- Não alterar fato, medida, causa, origem, criticidade, ressalva ou conclusão.
- Não buscar enganar detector de IA; buscar precisão, naturalidade e economia.
- A validação e a liberação profissional permanecem exclusivas do perito.
