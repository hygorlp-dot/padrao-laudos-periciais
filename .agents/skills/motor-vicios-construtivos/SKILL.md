---
name: motor-vicios-construtivos
description: Ingerir evidências reais de vistoria, estruturar vistoria.json, organizar manifestações, testar hipóteses causais, gerar PAT-NNN, sanear QT-NNN, cobrir quesitos e aplicar gate de redação em perícias de vícios construtivos. Usar depois do planejamento e da diligência, sem antecipar fatos ausentes, redigir o laudo completo ou aplicar este motor a outro tipo pericial.
---

# Motor de vícios construtivos

## Fluxo

1. Ler `AGENTS.md` e os padrões de patologia, classificação, quesitos,
   planejamento e terminologia.
2. Confirmar que `git ls-files "referencias/privadas/*"` está vazio.
3. Inventariar `referencias/privadas/vistorias/<processo>/` por hash com
   `scripts/vistoria_estruturada/inventariar_vistoria.py`.
4. Preservar anotação, declaração, imagem, medição e observação em
   categorias distintas. Nunca transformar texto ambíguo em `OBS-NNN`.
   Preservar também a polaridade `AFIRMADO`, `NEGADO`, `INCERTO` ou
   `HIPOTETICO` por trecho e localização. Uma negativa pode constituir
   contraevidência, mas nunca o correspondente fato positivo.
   Em fotografia, manter `finalidade_planejada` separada de
   `descricao_visual_observada`. Sem análise visual humana ou multimodal,
   registrar `NAO_INTERPRETADA` e não atribuir poder probatório. A análise
   visual pode descrever ambiente, elemento, manifestação e características
   visíveis, escala, limitações e confiança; nunca concluir causa, origem ou
   vício diretamente da imagem.
5. Gerar `vistoria.json` com `scripts/vistoria_estruturada/gerar_vistoria.py`.
   Se não houver dados de campo, retornar `AGUARDANDO_DADOS_DE_VISTORIA`.
6. Executar o motor somente se `tipo_pericia = VICIOS_CONSTRUTIVOS`; para os
   demais tipos, retornar `MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO`.
7. Organizar `ALEGAÇÃO → EVIDÊNCIA → CONSTATAÇÃO → MANIFESTAÇÃO →
   MECANISMO → HIPÓTESES → CAUSA → ORIGEM → CLASSIFICAÇÃO → CONCLUSÃO`.
8. Testar cada `HIP-NNN` com evidências favoráveis, contrárias e ausentes;
   não usar hipótese como lista decorativa.
   Consultar o registro de capacidade causal do sistema. Quando não houver
   motor causal especializado, preservar a constatação, não fabricar hipótese
   genérica e responder perguntas causais com
   `MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO`. Perguntas de existência continuam
   saneáveis pela evidência observacional disponível.
9. Recuperar normas privadas com proveniência. Se uma `NOR` material estiver
   ausente: detectar a necessidade, acionar o `SearchProvider` disponível,
   priorizar fonte oficial, estruturar e reconciliar os resultados, devolvê-los
   ao pipeline e continuar a análise. Conferir identidade, versão, vigência e
   aplicabilidade antes do uso e registrar o derivado apenas na área privada.
   Em teste usar `MockSearchProvider`; sem ferramenta externa registrar
   `SEARCH_PROVIDER_INDISPONIVEL` e manter o gate conservador.
   Uma norma verificada sustenta somente o requisito normativo. Conformidade
   exige método e critério verificáveis, evidência do caso e comparação
   explícita por `avaliar_conformidade_normativa`; sem esses elementos, usar
   `INCONCLUSIVO`.
   Norma, literatura ou critério não comprovam que um fato físico ocorreu no
   caso. Manifestação, mecanismo e causa exigem evidência própria do caso.
   Proveniência e acessibilidade não demonstram autoridade. Classificar a
   fonte por identidade institucional verificável e separar metadados da
   norma do conteúdo efetivamente consultado.
10. Gerar `PAT-NNN`, atualizar QT, cobertura dos quesitos, autoauditoria e gate.
11. Validar contratos e relações antes de disponibilizar o resultado.

## Regras causais

- Distinguir manifestação, mecanismo, causa e origem.
- Estado observado repetidamente não demonstra origem. Origem
  `ENDOGENA_CONSTRUTIVA` exige nexo com evidência de projeto, execução,
  material, especificação ou outra dimensão construtiva verificável.
- Não concluir causa exclusivamente por fotografia, palavra-chave, idade,
  garantia, alegação ou caso anterior.
- Usar `NAO_CONSTATADA` para manifestação não observada dentro dos limites;
  não converter em inexistência.
- Caracterizar tecnicamente o vício com manifestação constatada, causa
  sustentada e origem `ENDOGENA_CONSTRUTIVA`. Tratar a aprovação profissional
  final do perito como metadado posterior, nunca como entrada causal.
- Fundamentar criticidade; não classificá-la por palavra-chave.
- Tornar item elegível ao futuro orçamento de vício somente com todos os
  requisitos cumulativos. Não gerar composição final nesta etapa.

## Autonomia e pesquisa

Decidir e prosseguir quando a evidência permitir conclusão conservadora ou
ressalvada. Perguntar apenas diante de bloqueio material irresolúvel, registrando
fontes verificadas, pesquisa, tentativas, impacto e pergunta mínima.

Tratar fonte secundária apenas como instrumento de descoberta. Não inventar
item, requisito, tolerância, vigência ou sucessão normativa. Se a pesquisa não
estiver disponível, registrar `PESQUISA_ONLINE_INDISPONIVEL`.

## Gates

- `APTO_PARA_REDACAO`: questões materiais saneadas, causalidade coerente e
  nenhum achado bloqueante.
- `APTO_PARA_REDACAO_COM_RESSALVAS`: limitações explicáveis permitem redação
  tecnicamente honesta.
- `BLOQUEADO_PARA_REDACAO`: redigir produziria resultado enganoso,
  contraditório ou indefensável.

## Limites

Não gerar laudo completo, respostas finais formatadas, orçamento final,
Word, PDF, assinatura ou protocolo. Manter todos os dados e derivados reais em
`referencias/privadas/`.
