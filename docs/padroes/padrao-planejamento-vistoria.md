# Padrão de planejamento pericial e pré-vistoria

## Regras aprovadas

- Planejar para obter as evidências ainda necessárias ao saneamento técnico do
  tema controvertido.
- Fazer cada quesito técnico ou parcialmente técnico possuir estratégia de
  cobertura documental, de campo, de medição, de fotografia, de ensaio ou de
  ressalva.
- Separar fatos dos autos, conhecimento referencial, conhecimento normativo e
  atividades futuras.
- Não converter atividade planejada em constatação realizada.
- Não antecipar diagnóstico, origem, criticidade, responsabilidade ou
  orçamento.

## Fluxo

`manifesto-pje.json → documento-pje.json → processo.json →
delimitacao-pericial.json → conhecimento pertinente → plano-vistoria.json →
ficha-pre-vistoria.md`.

O resultado de campo alimentará futuramente `vistoria.json`, o motor técnico e
o laudo. A finalidade permanece o saneamento técnico do tema controvertido.

## Conhecimento privado

O inventário é automático e incremental por SHA-256. Fontes iguais não são
reprocessadas; alterações geram atualização dos derivados privados.

Modelos permanecem como experiência de baixa precedência até aprovação.
Conclusões específicas nunca migram para outro caso. Conhecimento normativo
exige arquivo, hash, identidade, edição, página e item quando verificáveis.
Ausências recebem `PENDENTE_VERIFICACAO_NORMATIVA` ou `TEXTO_INSUFICIENTE`.

## Cobertura: relacional e de requisito material

A cobertura de um quesito tem duas dimensões independentes:

- **Relacional** — o quesito está ligado a questões técnicas e a itens de plano
  do tipo exigido por `requisitos_cobertura`.
- **Requisito material** — cada requisito material do quesito tem destino
  verificável. Os requisitos são extraídos deterministicamente do texto do quesito
  (`requisitos_materiais.py`): ruído estrutural (marcadores de página, folhas,
  assinatura, URLs) é removido por formato; o texto é segmentado de forma
  conservadora; cada cláusula recebe `requirement_id` estável (conjunto de termos
  de conteúdo, invariante à ordem) e classe. Quesito pertinente cujo texto não
  rende cláusula material rende um requisito `EXTRACAO_INDETERMINADA`.

Classe do requisito, por vocabulário técnico canônico (a lista abaixo é
autoritativa; o código em `requisitos_materiais.py` a reproduz). **A classe é
sempre re-derivada do texto pela camada de cobertura — uma classe persistida no
plano nunca é confiada.** O default é **fail-closed**: `INDETERMINADA`.

- `DOCUMENTO` (verificada primeiro) — verbo documental (`solicitar`, `requisitar`,
  `juntar`, `apresentar`, `obter`, `anexar`, `exibir`) **e** artefato documental
  (`documento`, `projeto`, `memorial`, `planta`, `ART`, `RRT`, `laudo`, `contrato`,
  `nota fiscal`, `as built`, `caderno`, `especificação técnica`, `habite-se`,
  `alvará`, `diário de obra`). Coberto só por `documentos_a_solicitar`.
- `MEDICAO` — verbo de medição (`medir`, `aferir`, `mensurar`, `quantificar`,
  `dimensionar`, `calcular`, `ensaiar`, `testar carga/resistência/pressão/
  estanqueidade`); **ou** grandeza inerentemente dimensional (`espessura`,
  `recalque`, `flecha`, `prumo`/`aprumo`/`desaprumo`, `nivelamento`/`desnível`,
  `inclinação`/`caimento`/`declividade`, `deformação`, `deslocamento`, `esquadro`,
  `dimensão`, `área`, `volume`, `cota`, `distância`, `ângulo`, `largura`, `altura`,
  `comprimento`, `profundidade`, `diâmetro`, `abertura de fissura/trinca`, `vazão`,
  `carga`, `tensão atuante`); **ou** propriedade ensaiável (`resistência`,
  `aderência`, `desempenho`, `dureza`, `absorção`, `permeabilidade`,
  `estanqueidade`, `isolamento`, `condutividade`, `módulo`, `capacidade de carga`,
  `arrancamento`, `pull-off`); **ou** patologia ensaiável (`carbonatação`,
  `cloretos`, `corrosão de armadura`, `potencial de corrosão`); **ou** critério
  numérico explícito (`≤`, `≥`, `mínimo de N`, `tolerância de N`…); **ou**
  quantificador (`teor de`, `índice de`, `nível de`, `grau de`, `percentual de`)
  sobre grandeza quantificável (`umidade`, `temperatura`, `pressão`, `pH`,
  `salinidade`, `acidez`). Coberto só por `medicoes` ou `ensaios`.
- `INSPECAO` — **só com sinal positivo**: verbo de constatação/existência
  (`verificar`, `constatar`, `identificar`, `localizar`, `caracterizar`,
  `descrever`, `registrar`, `observar`, `inspecionar`, `examinar`, `apontar`,
  `indicar`, `existe`/`existir`, `há`, `houve`) **e** ausência de qualquer sinal de
  `MEDICAO`. Coberto por atividade, fotografia, medição, ensaio ou documento.
- `INDETERMINADA` — nenhum sinal positivo de `INSPECAO` nem de `MEDICAO`/
  `DOCUMENTO` (ex.: `avaliar`/`determinar`/`analisar` sem enquadramento
  observacional; cláusula sem verbo). Tratada como `MEDICAO` estrita pelo gate:
  **na dúvida, exige medição/ensaio.**

A cobertura de um requisito material vem **exclusivamente** do vínculo estruturado
`requisitos_semanticos[].itens_planejados`, validado por: o item existe, está
vinculado relacionalmente à cobertura do quesito e é do tipo apropriado à classe
(re-derivada). **Semelhança textual não é autoridade de cobertura**; o gerador
**não fabrica destino** — se o perfil pericial não provê item do tipo necessário,
o requisito fica `NAO_MAPEADO`, entra em `pendencias` e o plano é
`BLOQUEADO_PARA_VISTORIA`. Consequência esperada: planos auto-gerados para casos
que exigem ensaio nascem `BLOQUEADO_PARA_VISTORIA` até o perito planejar as
medições/ensaios — isso é o comportamento correto, não uma falha.
Plano legado sem `requisitos_semanticos` tem cobertura de requisito material
desconhecida — nunca 100%.

## Gate automático

- `APTO_PARA_VISTORIA`: relacional 100%, requisito material 100%, zero requisito
  não mapeado, sem ressalva material.
- `APTO_PARA_VISTORIA_COM_RESSALVAS`: limitações conhecidas, mas diligência
  ainda útil.
- `BLOQUEADO_PARA_VISTORIA`: lacuna crítica sem estratégia — inclui qualquer
  requisito material não mapeado — impede resultado útil.

Perguntar ao perito apenas no último caso e somente após registrar as tentativas
autônomas, o impacto e a pergunta mínima necessária.
