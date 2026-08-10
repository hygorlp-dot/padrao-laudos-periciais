---
name: planejamento-pericial-autonomo
description: Gerar autonomamente processo.json, aprofundar delimitacao-pericial.json, recuperar conhecimento privado pertinente, produzir plano-vistoria.json e ficha-pre-vistoria.md rastreáveis. Usar após a extração de manifesto-pje.json e documento-pje.json, antes da vistoria judicial, quando o objetivo for planejar evidências, atividades, medições, fotografias, equipamentos e documentos necessários sem redigir o laudo ou antecipar constatações.
---

# Planejamento pericial autônomo

## Finalidade

Planejar a obtenção de evidências necessárias ao saneamento técnico do tema
controvertido. Decidir e prosseguir por padrão; perguntar ao perito somente por
bloqueio material irresolúvel.

## Fluxo obrigatório

1. Ler `AGENTS.md`, `docs/padroes/padrao-delimitacao-pericial.md` e os schemas
   aplicáveis.
2. Confirmar que `git ls-files "referencias/privadas/*"` está vazio.
3. Inventariar modelos e normas privados com
   `scripts/conhecimento_privado/inventariar.py`; não reprocessar hash igual.
4. Gerar `processo.json` com `scripts/planejamento_pericial/gerar_processo.py`.
5. Regerar `delimitacao-pericial.json` e executar
   `scripts/planejamento_pericial/aprofundar_delimitacao.py`; manter evidência,
   alegação, decisão, norma e inferência semanticamente separadas.
6. Recuperar automaticamente `NOR-NNNN` e `MOD-NNNN` relevantes. Usá-los
   apenas para metodologia ou planejamento, nunca como fato do caso atual.
7. Gerar `plano-vistoria.json` e `ficha-pre-vistoria.md` com
   `scripts/planejamento_pericial/gerar_plano.py`.
8. Validar schemas, relações e cobertura integral dos quesitos pertinentes.

## Planejamento específico

- Para vícios construtivos, relacionar `ALG → sistema → QT → QUE → ATV → MED →
  FOT`, sem concluir origem.
- Para avaliação imobiliária, planejar caracterização física, áreas, padrão,
  conservação, localização e dados do método; não inserir checklist de
  patologias por padrão.
- Para engenharia rodoviária/sinistro, planejar georreferenciamento, geometria,
  pavimento, drenagem, sinalização, iluminação, visibilidade, registros
  históricos e segurança operacional; não inserir roteiro residencial.

## Conhecimento privado

Exigir proveniência por arquivo e hash. Para norma, exigir entidade, número,
edição, página e item quando identificáveis. Marcar dado não verificável como
`PENDENTE_VERIFICACAO_NORMATIVA`; nunca inventar requisito, tolerância, ensaio
ou aplicabilidade temporal.

Manter modelos como `CASO_ANTERIOR` ou `EXPERIENCIA_REFERENCIAL`. Não transferir
nomes, endereços, fatos, valores, causalidade, criticidade, responsabilidade ou
conclusões específicas.

## Gate

- Usar `APTO_PARA_VISTORIA` quando não houver lacuna relevante.
- Usar `APTO_PARA_VISTORIA_COM_RESSALVAS` quando a diligência continuar útil.
- Usar `BLOQUEADO_PARA_VISTORIA` quando uma lacuna material impedir obtenção de
  informação útil.

Registrar decisões autônomas, ressalvas, lacunas tratadas e perguntas. Fazer
pergunta somente após esgotar autos, decisão, documentos, conhecimento,
inferência conservadora, ressalva e planejamento de verificação futura.

## Guardrails

- Não redigir laudo, gerar Word/PDF, preencher vistoria inexistente ou antecipar
  diagnóstico, origem, criticidade, orçamento ou responsabilidade.
- Não tratar `NÃO CONSTATADO` como `INEXISTENTE`.
- Não deixar quesito pertinente sem cobertura planejada.
- Manter todos os derivados reais exclusivamente em
  `referencias/privadas/derivados/` ou `referencias/privadas/conhecimento/`.
