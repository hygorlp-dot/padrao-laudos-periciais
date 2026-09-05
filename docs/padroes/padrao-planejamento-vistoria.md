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

  A contabilidade funciona por eliminação, sobre o texto normalizado, **cláusula
  a cláusula** (V12/V12.1): (0) a demanda é primeiro partida em cláusulas
  coordenadas pelo mesmo conector canônico de `_segmentar` (`,`/`;`/`e`/`ou`/
  `eou`) — um PP locativo ou de-complemento nunca atravessa fronteira de
  coordenação; TODAS as cláusulas precisam resolver para a demanda inteira ser
  `INSPECAO`, **e cada cláusula recalcula seus próprios sinais habilitadores**
  (o verbo de observação direta/marcador visual de uma cláusula NUNCA libera
  prova de objeto em outra cláusula coordenada — `"fotografar a mancha **e** a
  fissura do zeta"` é `INDETERMINADA`: "fotografar" só vale para "a mancha", a
  segunda cláusula não tem marcador próprio; o verbo inicial da demanda só é
  reintegrado à checagem da PRIMEIRA cláusula, a única que efetivamente o
  tinha). Coordenar um fenômeno real a uma cláusula não resolvida nunca absolve
  a cláusula não resolvida (`"registrar a fissura no forro **ou** o parâmetro
  omega"` é `INDETERMINADA` mesmo a primeira cláusula sendo observacional). Em
  cada cláusula: (1) o verbo inicial é descartado; (2) todo **PP locativo**
  (`em/no/na/junto a/próximo a/perto de ...`) é removido, mas **limitado a um
  punhado de palavras** após a preposição (nunca até o fim da cláusula — um NP
  locativo real é curto; isso fecha qualquer coordenador de português não
  enumerado em `_CONECTOR` — `"bem como"`, `"assim como"`, `"além de"`,
  parênteses, travessão, `"/"` — sem precisar enumerá-los um a um: `"verificar
  a fissura na parede **bem como** o parâmetro omega"` é `INDETERMINADA`
  porque o PP para em `"parede"`, deixando `"parâmetro omega"` como resíduo);
  um fenômeno citado como *local* da observação não é a *demanda*: `"verificar
  o cobrimento das armaduras **junto às fissuras**"` não deixa o cobrimento
  (objeto real da frase) virar observável só porque uma fissura foi citada ao
  lado; (3) ao menos um **NP observacional** é consumido com seu
  de-complemento — substantivo de **fenômeno inequivocamente visual**
  (`fissura`, `trinca`, `mancha`, `infiltração`, `mofo`/`bolor`,
  `eflorescência`, `destacamento`/`descolamento`/`desplacamento`,
  `bolha`/`empolamento`, `ferrugem`, `vazamento`/`goteira`, `manifestação
  patológica`, `anomalia`, `avaria`, `deterioração`, `desgaste`,
  `vegetação`/`entulho`/`sujidade`) sempre, ou objeto descritivo-qualitativo
  (`padrão construtivo/de acabamento/arquitetônico`, `acabamento`, `estado
  geral/de conservação/aparente`, `aspecto geral/visual/estético`,
  `sistema/método/técnica construtiv-`, `tipologia`, `configuração
  geral/arquitetônica`) só combinado, NESTA cláusula, com verbo de observação
  direta ou marcador visual. O **de-complemento** (`"de X"`) só é absorvido
  incondicionalmente quando `X` é um elemento/local construtivo conhecido
  (`parede`, `teto`, `piso`, `laje`, `fachada`, `imóvel`, `estrutura`,
  `elemento`, `componente`, `umidade`, `bolor`/`mofo`, …) — nunca introduz
  conteúdo técnico novo, só localiza/atribui o mesmo fenômeno já reconhecido;
  um `X` **fora** desse vocabulário só é absorvido quando ESTA MESMA cláusula
  também tem **marcador visual explícito** (`visível`/`aparente`/`fotografar`/
  … — nunca o verbo de observação direta genérico sozinho: esses verbos já são
  modalidade-neutros quanto ao objeto por definição, usá-los para justificar o
  complemento seria a mesma contradição que o `INDETERMINADA` do parágrafo
  acima existe para evitar) — `"fotografar a fissura **de lambda**"` continua
  `INSPECAO` (`fotografar` já é o próprio marcador visual, ato definicionalmente
  fotográfico), mas `"registrar a fissura **do zeta**"` **sozinho, sem marcador
  visual em lugar nenhum da cláusula, é `INDETERMINADA`** — `registrar` não
  prova que "zeta" seja observável só por ser verbo de observação direta.
  `"registrar a mancha **de zeta visível**"` continua `INSPECAO` porque tem o
  marcador `visível`, não porque tem `registrar`. (4) scaffolding (conector
  existencial, `alegado`) e qualificador de modo são descartados;
  (5) **qualquer token de conteúdo remanescente derruba a cláusula para
  `INDETERMINADA`** — adjetivo desconhecido sobre um fenômeno reconhecido também
  conta como remanescente. E ausência de qualquer sinal de `MEDICAO`. Objeto
  técnico desconhecido **nunca** vira `INSPECAO` sem essa prova de modo, qualquer
  que seja o verbo, o marcador, ou um fenômeno citado incidentalmente/coordenado
  em outra cláusula. Termos cuja avaliação usual é instrumental (`umidade` como
  cabeça da demanda — como complemento de um fenômeno visível ela é permitida —,
  `corrosão`/`oxidação` sem "aparente"/"ferrugem", `assentamento diferencial`,
  `deriva`, `flambagem`, `cobrimento`, `resistividade`, `potencial
  eletroquímico`, `área de infiltração/mancha/fissura` — extensão
  quantificada…) **não** habilitam nenhum ramo como cabeça da demanda. As listas
  de prova de objeto são permissivas e a contabilidade é *fail-closed*: sua
  incompletude (adjetivo real não reconhecido como qualificador, elemento
  construtivo real fora de `_COMPLEMENTO_SEGURO`, p.ex.) causa
  **sobre-bloqueio** (o requisito cai em `INDETERMINADA` → medição estrita),
  **nunca** falso-verde — débito de precisão registrado, não corrigido às cegas
  vocabulário-por-vocabulário. Coberto por atividade, fotografia, medição, ensaio
  ou documento. (V13.1/V13.2: **toda** primitiva que esta contabilidade
  remove ou consome antes da checagem de resíduo — os vocabulários de
  fenômeno/objeto descritivo/complemento seguro, mais `_SCAFFOLD`
  (`presença`/`ausência`/`alegado`/`existência`), `_MARCADOR_VISUAL`
  (`fotograf-`), `_QUALIFICADOR_NP` (`localizado`/`generalizado`/`alegado`) e o
  verbo-líder (`analis-`) — usa sufixo flexional FECHADO, nunca `\w*`
  irrestrito: `"parede"` reconhece `"paredes"`, nunca `"paredeZETA"` colado por
  artefato de extração de PDF/OCR; o PP locativo só remove a preposição quando
  a palavra seguinte é um local do MESMO vocabulário fechado — um local
  desconhecido, sozinho, permanece resíduo em vez de ser descartado sem
  verificação; e um token de 1-2 letras conta como resíduo tanto quanto um
  mais longo.)
- `INDETERMINADA` — nenhuma demanda observacional sobra íntegra após a
  contabilidade (ex.: `verificar se está aprumado`, `constatar se o contrapiso
  está plano`, `verificar se há afundamento de trilha de roda`, `registrar o
  assentamento diferencial`, `descrever a resistividade elétrica do concreto`,
  `verificar o cobrimento das armaduras junto às fissuras`; cláusula sem verbo).
  Tratada
  como `MEDICAO` estrita pelo gate: **na dúvida, exige medição/ensaio.**

### Autoridade efetiva: sugestão ≠ cobertura (V13)

`classificar_requisito(texto)` (`MEDICAO|DOCUMENTO|INSPECAO|INDETERMINADA`) é
apenas **SUGESTÃO** — nunca a autoridade de cobertura, mesmo sempre re-derivada
do texto a cada chamada. Re-derivar fecha *adulteração* (um `classe` persistido
mentiroso é ignorado); não fecha *ambiguidade* (uma classificação textual
incorreta, mesmo recalculada do zero toda vez, ainda vira `apto=True` direto
se a saída do classificador FOR, ela mesma, a autoridade). Esta foi a classe
causal que atravessou V7-V12.2 (AUTONOMOUS_CAUSAL_REPAIR_LOOP_V1,
`TEXT_CLASSIFIER_OUTPUT != EFFECTIVE_COVERAGE_AUTHORITY`).

A autoridade efetiva é `evidencia_requerida(texto)` — `METROLOGICA|DOCUMENTAL|
OBSERVACIONAL|DESCONHECIDA` — SEMPRE re-derivada do texto (nunca de campo
persistido: `requisitos_semanticos[].evidencia_requerida`, quando presente, é
só informativo/round-trip, exatamente como `classe` já era). Promoção:
`MEDICAO→METROLOGICA` e `DOCUMENTO→DOCUMENTAL` diretas (vocabulário fechado,
nunca a origem de um fail-open nesta issue); `INSPECAO→OBSERVACIONAL` **só**
quando a MESMA demanda também resolve em modo **ESTRITO** — a contabilidade
observacional roda de novo com o de-complemento aberto (TIER 2, licenciado por
marcador visual) **desativado**, exigindo que TODO o conteúdo já pertença a
vocabulário fechado. Uma sugestão que só resolveu via TIER 2 (`"fotografar a
fissura de lambda"`, `"registrar a mancha de zeta visível"`) continua
`INSPECAO` como sugestão, mas vira `DESCONHECIDA` como autoridade — um
marcador visual é prova textual forte o bastante para *sugerir* observação,
não para tornar a cobertura *efetiva*, porque o objeto em si permanece fora de
qualquer vocabulário fechado. `DESCONHECIDA` nunca cobre, nunca fica completa
— sobre-bloqueio de uma demanda genuinamente observacional é o modo de falha
aceito, nunca o inverso. `_cobertura_semantica`, `_execucao_semantica_faltante`
e o gerador (`gerar_plano._mapear_requisitos_semanticos`) consultam
EXCLUSIVAMENTE `evidencia_requerida` — nunca `classificar_requisito` — para
decidir quais coleções (`atividades`/`medicoes`/`ensaios`/`fotografias`/
`documentos`) satisfazem um requisito.

O `recalcular_execucao` (superfície de recálculo REQUIRED→EXECUTED consumida pelos
pipelines de motor de vícios e de redação) **re-deriva a evidência requerida do
requisito material** pela mesma `evidencia_requerida`: um plano com requisito
metrológico sem destino de medição/ensaio nunca é `apto` na execução, mesmo com
o vínculo relacional satisfeito (§18 — uma autoridade canônica em todas as
superfícies).
A execução efetiva usa **uma única autoridade** (`_item_execucao_satisfeito`) nos
caminhos relacional e semântico: status persistido nunca é autoridade —
`EXECUTADO` exige artefato com back-reference ao item planejado e à questão
técnica; `SUBSTITUIDO_POR_EVIDENCIA_EQUIVALENTE` exige equivalência válida
(evidence existente, mesmo tipo, capability íntegra, metadados rastreados).
Plano legado sem `requisitos_semanticos` tem cobertura semântica **UNKNOWN**:
é falta explícita também na execução — **UNKNOWN nunca fabrica APTO**.

A cobertura de um requisito material vem **exclusivamente** do vínculo estruturado
`requisitos_semanticos[].itens_planejados`, validado por: o item existe, está
vinculado relacionalmente à cobertura do quesito e é do tipo apropriado à
evidência requerida (re-derivada). O vínculo relacional (V12) é lido do **próprio item**, nunca de
`cobertura[quesito]` (lista editável, nunca autoridade): para os tipos cujo
schema tem campo `quesitos` (`atividade`/`medicao`/`fotografia`), a declaração
do item é autoridade **única** — presente ou vazia, nunca sobreposta nem
complementada por interseção de questão técnica (um item honestamente declarado
a outro quesito, mesmo reutilizando legitimamente uma questão técnica também
relevante ao quesito atual, nunca é creditado); para `ensaio`/`documentoPlanejado`
— cujo schema **não** tem campo `quesitos` (`additionalProperties: false`) — a
interseção de questão técnica com a cobertura do quesito é a única autoridade
que o próprio schema disponibiliza, não uma inferência de conveniência.
**Semelhança textual não é autoridade de cobertura**; o gerador
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
