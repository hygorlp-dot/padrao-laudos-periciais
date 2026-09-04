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
  `comprimento`, `extensão`, `profundidade`, `diâmetro`, `planicidade`/`planeza`,
  `abertura de fissura/trinca`, `vazão`, `carga`, `tensão atuante`); **ou**
  propriedade ensaiável (`resistência`, `aderência`, `desempenho`, `dureza`,
  `absorção`, `permeabilidade`, `estanqueidade`, `isolamento`, `condutividade`,
  `módulo`, `arrancamento`, `pull-off`, `estabilidade`, `capacidade portante/
  resistente/de carga/estrutural`, `comprometimento estrutural`); **ou** patologia
  ensaiável (`carbonatação`, `cloretos`, `corrosão de armadura` — em qualquer
  flexão, `potencial de corrosão`, `perda de seção` das barras/armaduras); **ou**
  grandeza inerentemente instrumental (`umidade relativa`/`umidade do ar`, `ponto
  de orvalho`, `temperatura superficial/ambiente/do ar/de bulbo/de orvalho`,
  `iluminância`/`luminância`, `nível de ruído`/`pressão sonora`, `vibração`/
  `aceleração`/`frequência natural`) — não constatável a olho nu mesmo sem número;
  **ou** critério numérico explícito — operadores (`<`, `>`, `≤`, `≥`),
  conectivos comparativos com número (`superior a N`, `inferior a N`, `maior/menor
  que N`, `no mínimo de N`, `no máximo de N`, `acima de N`, `abaixo de N`,
  `tolerância de N`, `limite de N`) ou quantidade dimensionada (`N mm`, `N cm`,
  `N %`, `N MPa`, `N kPa`, `N kN`, `N °`); **ou** um marcador de quantificação
  seguido de `de/do/da` (`teor de`, `índice de`, `nível de`, `grau de`,
  `percentual de`, `magnitude de`, `intensidade de`, `amplitude de`, `proporção
  de`, `quantidade de`) — independentemente da grandeza que segue, porque pedir o
  *grau/nível/extensão* de algo é um pedido quantificado que o verbo de requisição
  não desambigua. Coberto só por `medicoes` ou `ensaios`.
- `INSPECAO` — **exige CONTABILIDADE OBSERVACIONAL INTEGRAL da demanda**, não
  apenas a ocorrência de um sinal em algum ponto da cláusula. São
  **modalidade-neutros** e **não** classificam sozinhos: o verbo de requisição
  genérico (`verificar`, `constatar`, `apontar`, `indicar`, `avaliar`, `analisar`,
  `determinar`, `apurar`, `conferir`, `informar`); o conector existencial (`há`,
  `existe`, `existência/presença/ausência de`) — `medir se há trinca > 0,3 mm`
  também usa "há"; o verbo de **observação direta** (`descrever`, `registrar`,
  `fotografar`, `inspecionar`, `examinar`, `observar`, `vistoriar`, `caracterizar`,
  `localizar`) — `registrar o assentamento diferencial` exige nivelamento
  topográfico; **e** o qualificador de **modo** (`visível`, `aparente`,
  `visualmente`, `a olho nu`, `ocular`, `perceptível`, `fotograficamente`,
  `inspeção/exame visual`) — modo não é objeto: `fotografar o parâmetro omega` não
  prova que o objeto seja observável. `verificar se o piso está nivelado` é
  medição; `verificar se há infiltração aparente` é inspeção — **o objeto decide**.

  A contabilidade funciona por eliminação, sobre o texto normalizado: (1) o verbo
  inicial é descartado; (2) todo **PP locativo** (`em/no/na/junto a/próximo a/perto
  de ...`) é removido **por inteiro** — um fenômeno citado como *local* da
  observação não é a *demanda*: `"verificar o cobrimento das armaduras **junto às
  fissuras**"` não deixa o cobrimento (objeto real da frase) virar observável só
  porque uma fissura foi citada ao lado; (3) ao menos um **NP observacional** é
  consumido com seu de-complemento — substantivo de **fenômeno inequivocamente
  visual** (`fissura`, `trinca`, `mancha`, `infiltração`, `mofo`/`bolor`,
  `eflorescência`, `destacamento`/`descolamento`/`desplacamento`,
  `bolha`/`empolamento`, `ferrugem`, `vazamento`/`goteira`, `manifestação
  patológica`, `anomalia`, `avaria`, `deterioração`, `desgaste`,
  `vegetação`/`entulho`/`sujidade`) sempre, ou objeto descritivo-qualitativo
  (`padrão construtivo/de acabamento/arquitetônico`, `acabamento`, `estado
  geral/de conservação/aparente`, `aspecto geral/visual/estético`,
  `sistema/método/técnica construtiv-`, `tipologia`, `configuração
  geral/arquitetônica`) só combinado com verbo de observação direta ou
  qualificador de modo; (4) scaffolding (conector existencial, `alegado`) e
  qualificador de modo são descartados; (5) **qualquer token de conteúdo
  remanescente derruba a cláusula para `INDETERMINADA`** — coordenação
  (`"a fissura e o parâmetro omega"`) e adjetivo desconhecido sobre um fenômeno
  reconhecido também contam como remanescente. E ausência de qualquer sinal de
  `MEDICAO`. Objeto técnico desconhecido **nunca** vira `INSPECAO`, qualquer que
  seja o verbo, o marcador de modo, ou um fenômeno citado incidentalmente em
  outra parte da cláusula. Termos cuja avaliação usual é instrumental (`umidade`
  sem qualificador visual, `corrosão`/`oxidação` sem "aparente"/"ferrugem",
  `assentamento diferencial`, `deriva`, `flambagem`, `cobrimento`,
  `resistividade`, `potencial eletroquímico`, `área de infiltração/mancha/fissura`
  — extensão quantificada…) **não** habilitam nenhum ramo. As listas de prova de
  objeto são permissivas e a contabilidade é *fail-closed*: sua incompletude
  (adjetivo real não reconhecido como qualificador, p.ex.) causa
  **sobre-bloqueio** (o requisito cai em `INDETERMINADA` → medição estrita),
  **nunca** falso-verde — débito de precisão registrado, não corrigido às cegas
  vocabulário-por-vocabulário. Coberto por atividade, fotografia, medição, ensaio
  ou documento.
- `INDETERMINADA` — nenhuma demanda observacional sobra íntegra após a
  contabilidade (ex.: `verificar se está aprumado`, `constatar se o contrapiso
  está plano`, `verificar se há afundamento de trilha de roda`, `registrar o
  assentamento diferencial`, `descrever a resistividade elétrica do concreto`,
  `verificar o cobrimento das armaduras junto às fissuras`; cláusula sem verbo).
  Tratada
  como `MEDICAO` estrita pelo gate: **na dúvida, exige medição/ensaio.**

O `recalcular_execucao` (superfície de recálculo REQUIRED→EXECUTED consumida pelos
pipelines de motor de vícios e de redação) **re-deriva a classe do requisito
material** pelo mesmo `classificar_requisito`: um plano com requisito de medição
sem destino de medição/ensaio nunca é `apto` na execução, mesmo com o vínculo
relacional satisfeito (§18 — uma semântica canônica em todas as superfícies).
A execução efetiva usa **uma única autoridade** (`_item_execucao_satisfeito`) nos
caminhos relacional e semântico: status persistido nunca é autoridade —
`EXECUTADO` exige artefato com back-reference ao item planejado e à questão
técnica; `SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE` exige equivalência válida
(evidence existente, mesmo tipo, capability íntegra, metadados rastreados).
Plano legado sem `requisitos_semanticos` tem cobertura semântica **UNKNOWN**:
é falta explícita também na execução — **UNKNOWN nunca fabrica APTO**.

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
