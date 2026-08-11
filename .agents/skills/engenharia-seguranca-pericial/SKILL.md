---
name: engenharia-seguranca-pericial
description: Aplicar Safety Engineering ao Core Pericial em mudanças materiais, bugs, gates, evidências, medições, causalidade, auditoria e integrações externas. Usar antes de implementar ou revisar código que possa alterar resultado técnico, confiança, rastreabilidade, privacidade ou emissão segura.
---

# Engenharia de Segurança Pericial

## Precedência e proporcionalidade

- AGENTS.md é canônico sobre `using-superpowers` e prevalece diante de
  qualquer conflito com instrução upstream.
- Não tentar invocar Skills não vendorizadas, inclusive `brainstorming`.
- Aplicar Skills proporcionalmente ao risco. O fluxo é obrigatório nas
  mudanças materiais definidas em `AGENTS.md`, sem impor burocracia em
  perguntas e operações triviais.

## Fluxo obrigatório

1. Delimitar a Issue e reproduzir o comportamento material.
2. Aplicar `systematic-debugging` e registrar a causa-raiz observável.
3. Aplicar `test-driven-development`: escrever o teste, confirmar RED e somente
   então implementar a correção mínima.
4. Acrescentar adversarial/property tests proporcionais ao risco.
5. Executar regressão integral e `verification-before-completion`.
6. Solicitar revisão conforme `requesting-code-review`; avaliar achados com
   `receiving-code-review`. Usar subagente independente quando disponível. Se
   indisponível, gerar `review package` contendo requisitos, SHAs base/head,
   arquivos e diff, testes/guards, privacidade e riscos, e exigir revisão
   externa do PR antes do merge. Nunca declarar revisão independente concluída
   sem evidência identificável, como relatório do subagente ou review do PR.
7. Falhar fechado diante de conflito material, evidência insuficiente,
   privacidade incerta ou gate não recalculado.

Para tarefa multietapas, usar `writing-plans` e `executing-plans` quando
compatíveis com a governança e a autorização do usuário.

## Invariantes do Core Pericial

- **isolamento de evidências:** evidência de uma PAT/claim não sustenta outra
  sem vínculo explícito e validado;
- **invariância por ordem:** reordenar entradas equivalentes não altera o
  resultado técnico;
- **evidência irrelevante não altera resultado:** adicionar dado sem vínculo
  material não eleva confiança, classificação ou gate;
- **remoção de evidência essencial reduz confiança/bloqueia:** nunca preservar
  aprovação após retirar suporte indispensável;
- **gates recalculados independentemente:** nenhum status anterior, constante
  ou cache substitui a avaliação atual;
- **valor + unidade inseparáveis:** comparação, medição e orçamento preservam o
  par sem conversão implícita;
- **egress deny-by-default:** rede, telemetria e serviço externo permanecem
  bloqueados sem autorização expressa e sanitização;
- **auditoria nunca aprovada por constante:** o veredito deriva dos artefatos e
  resultados efetivamente auditados;
- **fail-closed:** dúvida material ou contrato inválido bloqueia o avanço;
- **alegação ≠ observação**;
- **norma ≠ evidência física**;
- **NÃO CONSTATADO ≠ INEXISTENTE**.

## Gate de conclusão

Exigir evidência fresca de testes, regressão, privacidade, integridade de
dependências e revisão do diff. Não declarar os P0 conhecidos corrigidos sem
Issue e teste específico. Não armazenar chain-of-thought; registrar somente
causa-raiz, hipótese, evidência, decisão resumida e resultado verificável.
