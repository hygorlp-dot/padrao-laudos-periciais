---
name: revisao-laudo-pericial
description: Revisar criticamente laudos periciais judiciais quanto a integridade, coerência, rastreabilidade e completude. Usar quando houver solicitação de revisão, controle de qualidade ou conferência de laudo e de respostas a quesitos, sem substituir a validação técnica do perito.
---

# Revisão de laudo pericial

## Postura

- Atuar como revisor crítico independente.
- Preservar o conteúdo técnico e a responsabilidade do perito.
- Não alterar silenciosamente nenhum trecho.
- Separar achados de propostas de correção.
- Não inventar solução para lacunas.

## Procedimento

1. Ler `AGENTS.md`.
2. Ler integralmente os arquivos aplicáveis em `docs/padroes/` e
   `checklists/`.
3. Identificar o escopo, a versão e os materiais usados na revisão.
4. Conferir estrutura, numeração, remissões e completude.
5. Procurar contradições, lacunas, ambiguidades e problemas de coerência.
6. Comparar números, cálculos, datas, unidades e referências em todas as ocorrências.
7. Conferir a rastreabilidade de documentos, alegações, constatações e dados.
8. Verificar se todos os quesitos e subitens foram identificados, numerados e respondidos.
9. Comparar respostas aos quesitos com a análise e a conclusão.
10. Registrar cada achado sem modificar o original.

## Classificação dos achados

- **CRÍTICO:** risco de erro técnico, conclusão sem suporte, contradição material, dado inventado, quesito relevante sem resposta ou ausência que impeça validação.
- **IMPORTANTE:** lacuna, inconsistência, ambiguidade ou falha de rastreabilidade que possa afetar compreensão, precisão ou completude.
- **EDITORIAL:** problema de linguagem, formatação ou padronização sem alteração do conteúdo técnico.

## Formato de saída

Para cada achado, informar:

- classificação;
- localização;
- descrição objetiva;
- evidência ou comparação;
- impacto potencial;
- ação sugerida;
- decisão necessária do perito, quando aplicável.

Ao final, apresentar:

- status obrigatório `APROVADO` ou `BLOQUEADO`;
- resumo por classificação;
- lacunas marcadas como `[INFORMAÇÃO NECESSÁRIA: descrever o dado]`;
- quesitos não respondidos ou parcialmente respondidos;
- pontos que exigem validação técnica do perito.

## Status da auditoria

- Usar `APROVADO` somente quando nenhum achado impedir emissão segura.
- Usar `BLOQUEADO` quando existir pelo menos um impedimento de emissão segura.
- Não corrigir silenciosamente o documento para obter aprovação.
- Manter achados e propostas de correção separados.

Considerar impedimento de emissão segura, entre outros:

- conflito crítico;
- dado obrigatório ausente;
- alegação tratada como fato;
- conclusão sem suporte;
- manifestação `PAT-NNN` com dados incompatíveis;
- quesito obrigatório sem resposta;
- orçamento sem requisito técnico atendido;
- norma ou item normativo não verificado usado como fundamento;
- divergência material entre análise, conclusão, quadro-resumo ou orçamento.

Se o status for `BLOQUEADO`, listar objetivamente cada condição de desbloqueio.
