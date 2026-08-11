# Padrão canônico de redação

## Status

**REGRA APROVADA.** Este documento registra o padrão de redação validado a
partir da análise comparativa, sem converter conclusões específicas em regras
gerais.

## Referências

- Usar o laudo privado aprovado como referência visual principal.
- Usar a versão 8 do laudo privado secundário e os demais laudos finalizados como
  referências secundárias de estrutura e redação.
- Não usar a versão 9 do laudo privado secundário como referência de conteúdo
  final.

## Tom e pessoa verbal

- Manter linguagem formal, técnica, objetiva e auditável.
- Preferir construções impessoais ou em terceira pessoa, como `verificou-se`,
  `constatou-se`, `observou-se` e `conclui-se`.
- Evitar afirmação categórica quando os elementos permitirem apenas hipótese,
  possibilidade ou inferência.
- Indicar expressamente o grau de certeza e as limitações relevantes.

## Organização dos parágrafos

- Tratar uma ideia técnica principal por parágrafo.
- Evitar períodos excessivamente longos e repetição de definições gerais.
- Distinguir alegação, documento, constatação, medição, cálculo, inferência e
  conclusão.
- Identificar a fonte de alegações e dados documentais.
- Não apresentar ausência de constatação como prova automática de inexistência.

## Sequência da análise específica

Para cada manifestação, seguir o bloco de
`docs/padroes/padrao-patologia.md` e manter estes títulos:

1. Análise das Alegações e Prováveis Causas.
2. Consequências.
3. Classificação.
4. Conclusão.

## Causas e consequências

- Diferenciar causa constatada, causa provável e causa alternativa.
- Informar suporte documental, visual, instrumental ou normativo.
- Não atribuir causa apenas por plausibilidade.
- Não usar prazo de garantia como substituto do diagnóstico causal.
- Relacionar consequências somente à manifestação efetivamente analisada.

## Conclusões

- Fazer a conclusão decorrer da análise precedente.
- Não introduzir fato, classificação ou causa nova na conclusão.
- Submeter toda conclusão técnica à aprovação do perito.
- Não concluir responsabilidade civil, culpa, legitimidade, prescrição,
  decadência, direito à indenização ou qualificação jurídica de vício
  redibitório.
- Evitar as expressões proibidas em `docs/padroes/terminologia.md`.

## Normas e citações

- Concentrar conceitos e critérios gerais no capítulo metodológico.
- Em cada manifestação, citar apenas norma ou critério necessário à análise.
- Registrar toda norma em `docs/padroes/matriz-normativa.md`.
- Nunca inventar item, título, edição ou conteúdo normativo.

## Lacunas

- Usar `[INFORMAÇÃO NECESSÁRIA: descrever o dado]` para dado ausente.
- Usar `[VALIDAÇÃO DO PERITO: descrever a decisão]` para escolha técnica
  pendente.
- Não transformar marcador pendente em texto conclusivo.

## Pendências de validação do perito

- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** definir limites objetivos de extensão
  para parágrafos e respostas aos quesitos.
- **PENDÊNCIA DE VALIDAÇÃO DO PERITO:** aprovar abreviações e convenções de
  unidades ainda não registradas.

## Linguagem pericial natural

**REGRA APROVADA.** A redação expressa o `PAT_FINAL`; não produz nova verdade
técnica. O texto deve ser formal, preciso, econômico e natural.

- Cada parágrafo deve descrever, comparar, explicar, classificar, concluir ou
  ressalvar algo rastreável.
- Evitar aberturas genéricas, metadiscurso, conectivos repetitivos,
  adjetivação vazia, tom promocional e conclusões hiperbólicas.
- Não variar termo técnico apenas para evitar repetição.
- Não repetir a mesma conclusão em sucessivos parágrafos.
- Uma expressão isolada não constitui erro; considerar frequência, contexto e
  função.
- `CONFIRMADO` admite sustentação afirmativa; `PROVÁVEL` indica
  compatibilidade; `POSSÍVEL` ou `INCONCLUSIVO` exigem linguagem que preserve a
  limitação.
- Não usar detector de IA como critério de qualidade.

Pode haver variação de ritmo, extensão e ordem de frases não materiais. Não
pode variar medida, norma, causa, origem, criticidade, ressalva ou conclusão.

## Redação judicial orientada ao tema

- A síntese processual deve ser curta, neutra e limitada ao necessário para
  formular o tema técnico controvertido.
- Tema, objeto e objetivo têm funções distintas conforme
  [o padrão de estrutura](padrao-estrutura-laudo.md).
- Cada parágrafo técnico deve descrever, fundamentar, comparar, explicar
  mecanismo, ressalvar, classificar, concluir ou responder. Parágrafo sem
  função deve ser sinalizado.
- Evitar texto de apostila e definições elementares que não sejam necessárias
  à compreensão do método, mecanismo, critério ou conclusão.
- O grau de assertividade deve preservar a confiança saneada: confirmação
  admite formulação afirmativa; probabilidade exige compatibilidade; resultado
  possível ou inconclusivo exige limitação expressa.

## Claims da redação

- Toda afirmação material deve possuir `CLAIM-RED-NNN` e proveniência até
  evidência primária, norma verificada, `PAT-NNN`, `QT-NNN` e `QUE-NNN`
  relacionados.
- PAT não fundamenta PAT, texto não fundamenta o próprio texto e resposta a
  quesito não constitui fonte autônoma de verdade.
- Claim que cite norma deve auditar separadamente o componente normativo
  contra `NOR-NNN`; evidência física não comprova conteúdo normativo.
- Claim material nova gera `UNSUPPORTED_REDRAFT_CLAIM` e bloqueia o laudo.
- Autocorreção é exclusivamente editorial e não pode modificar fato, medida,
  causa, origem, criticidade, norma, reparo, quantitativo, ressalva ou
  conclusão.
