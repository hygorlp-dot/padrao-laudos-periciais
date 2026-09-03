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
- `INSPECAO` — **exige evidência positiva de observabilidade**. São
  **modalidade-neutros** e **não** classificam sozinhos: o verbo de requisição
  genérico (`verificar`, `constatar`, `apontar`, `indicar`, `avaliar`, `analisar`,
  `determinar`, `apurar`, `conferir`, `informar`) **e** o conector existencial
  (`há`, `existe`, `existência/presença/ausência de`) — `medir se há trinca >
  0,3 mm` também usa "há". `verificar se o piso está nivelado` é medição;
  `verificar se há infiltração aparente` é inspeção — nem o verbo nem o "há"
  decidem, o **objeto** decide. Atribui-se `INSPECAO` quando há (a) verbo de
  **observação direta** (`descrever`, `registrar`, `fotografar`, `inspecionar`,
  `examinar`, `observar`, `vistoriar`, `caracterizar`, `localizar`); **ou** (b)
  qualificador **explicitamente visual** (`visível`, `aparente`, `visualmente`,
  `a olho nu`, `ocular`, `perceptível`, `fotograficamente`, `inspeção/exame
  visual`); **ou** (c) substantivo de **fenômeno inequivocamente visual**
  (`fissura`, `trinca`, `mancha`, `infiltração`, `mofo`/`bolor`, `eflorescência`,
  `destacamento`/`descolamento`/`desplacamento`, `bolha`/`empolamento`,
  `ferrugem`, `vazamento`/`goteira`, `manifestação patológica`, `anomalia`,
  `avaria`, `deterioração`, `desgaste`, `vegetação`/`entulho`/`sujidade`) — **e**
  ausência de qualquer sinal de `MEDICAO`. Termos cuja avaliação usual é
  instrumental (`umidade` sem qualificador visual, `corrosão`/`oxidação` sem
  "aparente"/"ferrugem") **não** entram em (c): sem outro sinal caem em
  `INDETERMINADA`. A lista de fenômenos é permissiva: sua incompletude causa
  **sobre-bloqueio** (o requisito cai em `INDETERMINADA` → medição estrita), nunca
  falso-verde. Coberto por atividade, fotografia, medição, ensaio ou documento.
- `INDETERMINADA` — nenhum sinal positivo de `INSPECAO` nem de `MEDICAO`/
  `DOCUMENTO` (ex.: verbo genérico ou conector existencial sem qualificador visual
  nem fenômeno visual — `verificar se está aprumado`, `constatar se o contrapiso
  está plano`, `verificar se há afundamento de trilha de roda`, `constatar se
  existe assentamento diferencial`; cláusula sem verbo). Tratada como `MEDICAO`
  estrita pelo gate: **na dúvida, exige medição/ensaio.**

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
