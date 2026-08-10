---
name: triagem-delimitacao-pericial
description: Triar autos judiciais de Engenharia Civil, identificar autonomamente o tipo de perícia, delimitar tema controvertido, objeto, objetivo, questões técnicas, quesitos, ressalvas e conflitos, e gerar delimitacao-pericial.json rastreável. Usar após manifesto-pje.json e documento-pje.json, antes de planejamento de vistoria, processo.json ou redação de laudo.
---

# Triagem e delimitação pericial

## Objetivo

Promover o saneamento técnico preliminar do tema controvertido. Não redigir
laudo, não preencher vistoria inexistente e não emitir conclusão de mérito.

## Fontes

1. Ler `AGENTS.md`, `docs/padroes/padrao-delimitacao-pericial.md` e o schema.
2. Ler manifesto e todos os `documento-pje.json`, inclusive `OUTRO`.
3. Consultar modelos, normas e conhecimento privados quando existirem.
4. Manter derivados reais somente na árvore privada ignorada.

## Procedimento autônomo

1. Localizar decisões, quesitos, peças principais e documentos técnicos por
   conteúdo, sem depender apenas da classe documental.
2. Priorizar decisão delimitadora, quesitos do Juízo e decisões complementares.
3. Delimitar assunto, controvérsia, tema técnico, objeto material e objetivo.
4. Classificar tipo e subtipos por múltiplas evidências; registrar confiança,
   alternativas e fontes. Não presumir `VICIOS_CONSTRUTIVOS`.
5. Criar `QT-NNN` suficientes para sanear o tema.
6. Extrair literalmente todos os quesitos como `QUE-NNN`; separar componente
   técnico de matéria jurídica e mapear pertinência.
7. Construir a matriz quesito–questão técnica–seção futura.
8. Registrar `RES-NNN`, `CNF-NNN`, documentos ausentes e matérias excluídas.
9. Consultar conhecimento referencial/normativo disponível com origem. Se
   ausente, registrar indisponibilidade; nunca inventar norma.
10. Gerar plano preliminar, executar a autoauditoria e validar o JSON.

## Autonomia e gates

Decidir e prosseguir quando autos, decisão, evidência, norma verificada ou
regra canônica forem suficientes. Com confiança média, prosseguir com ressalva.
Com confiança baixa, buscar evidência adicional. Perguntar ao perito apenas se
persistir decisão material irresolúvel ou risco de conclusão falsa, usando
`[VALIDAÇÃO DO PERITO: descrição objetiva]`.

Usar `APTO_PARA_PLANEJAMENTO` somente com tipo, tema, objeto, objetivo,
questões, quesitos, ressalvas e conflitos suficientemente tratados. Bloquear
com conflito material aberto ou tema insuficientemente delimitado.

## Guardrails

- Fazer evidência atual prevalecer sobre modelos e casos anteriores.
- Não tratar alegação como fato, modelo como regra ou assunto como tipo único.
- Não iniciar redação conclusiva ou classificar mérito técnico sem evidência.
- Não aplicar norma sem arquivo, edição, página/item e verificação.
- Não converter `NÃO CONSTATADO` em `INEXISTENTE`.
- Aceitar inconclusividade fundamentada como resultado válido.
- Nunca responder quesito apenas com “vide laudo”.
