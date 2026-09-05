"""Extração determinística de requisitos materiais de um quesito.

O texto do quesito NÃO é autoridade de cobertura: aqui ele é apenas segmentado,
com identidade e proveniência estáveis, em requisitos materiais estruturados e
classificados por natureza. A cobertura é decidida a jusante por vínculo
estruturado a um item planejado de tipo apropriado (ver validar_plano).

Classificação (natureza do requisito) — DEFAULT FAIL-CLOSED. O vocabulário abaixo
é a lista canônica; está reproduzido em docs/padroes/padrao-planejamento-vistoria.md.

- INSPECAO — satisfazível por observação de campo. São MODALIDADE-NEUTROS e NÃO
  estabelecem observabilidade por si sós — nenhum decide sem prova POSITIVA NO
  OBJETO: o verbo de REQUISIÇÃO GENÉRICO ("verificar"/"constatar"/"avaliar"/…), o
  conector EXISTENCIAL ("há"/"existe"/"existência de"/"presença de" — "medir se
  HÁ trinca > 0,3 mm" também usa "há"), o verbo de OBSERVAÇÃO DIRETA
  ("registrar"/"descrever"/"fotografar"/"caracterizar"/"localizar"/… — "registrar
  o assentamento diferencial" exige nivelamento topográfico) E o qualificador de
  MODO ("visualmente"/"fotograficamente"/"aparente"/… — modo, não objeto).
  INSPECAO existe por UM funil conjuntivo: prova de objeto observável é condição
  necessária em todo ramo — (i) substantivo de fenômeno inequivocamente visual
  ("fissura", "infiltração", "mancha", "descolamento", "mofo", "eflorescência",
  …); ou (ii) objeto descritivo-qualitativo ("padrão construtivo", "acabamento",
  "estado de conservação", "revestimento", …) combinado com verbo de observação
  direta ou qualificador de modo — E ausência de qualquer sinal de medição. A
  demanda é contabilizada cláusula a cláusula (coordenação nunca atravessa PP
  locativo nem de-complemento — V12) e um complemento desconhecido ("de X") só
  entra na contagem quando a própria cláusula também traz um qualificador de
  modo/suficiência visual explícito; sem essa prova, permanece resíduo.
  Objeto técnico desconhecido NUNCA vira INSPECAO, qualquer que seja o verbo ou
  marcador de modo: o modo de falha do funil é SOBRE-BLOQUEIO, nunca falso-verde.
- MEDICAO  — exige leitura instrumental, ensaio ou cálculo (verbo de medição,
  grandeza inerentemente dimensional, propriedade ensaiável, patologia
  ensaiável, critério numérico/quantidade dimensionada, ou quantificador
  sobre grandeza quantificável).
- DOCUMENTO — verbo documental + artefato documental. Verificada ANTES de MEDICAO.
- INDETERMINADA — nenhum sinal positivo de INSPECAO nem de MEDICAO/DOCUMENTO
  (ex.: "verificar"/"constatar"/"avaliar" sem enquadramento observacional nem
  fenômeno visual, ou cláusula sem verbo). Tratada pelo gate como MEDICAO
  estrita: "na dúvida, MEDICAO".
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from scripts.triagem_pericial.semantica import normalizar, termos

# Ruído estrutural reconhecido por FORMATO, nunca por valores concretos do caso.
_RUIDO = [
    re.compile(r"(?im)\bn(?:um|º|o)\.?\s*\d+\s*[-–—]\s*p[áa]g(?:ina)?\.?\s*\d+\b"),
    re.compile(r"(?im)^\s*p[áa]gina\s+complementar\b.*$"),
    re.compile(r"(?im)^\s*(?:f?ls?\.?|folhas?)\s*\d+.*$"),
    re.compile(r"(?im)\bn[úu]mero\s+do\s+documento:.*$"),
    re.compile(r"(?im)\bassinado\s+eletronicamente\b.*$"),
    re.compile(r"https?://\S+"),
    re.compile(r"(?im)^\s*[\d\W_]+\s*$"),
]
_VERBO_TECNICO = re.compile(
    r"(?i)\b(?:verificar|avaliar|analis(?:ar|e|es|a|ou|ando|ad[oa]s?|amos|em|ava(?:m|mos)?)|"
    r"estimar|medir|caracterizar|quantificar|"
    r"constatar|identificar|localizar|classificar|determinar|apurar|aferir|mensurar|"
    r"dimensionar|calcular|conferir|inspecionar|documentar|descrever|registrar|apontar|"
    r"indicar|ensaiar|testar|examinar|observar|solicitar|juntar|apresentar|requisitar|existir|haver)\b"
)
_SEPARADOR_FORTE = re.compile(r"(?:[.;?!]+\s+)|(?:\s*\n[-–—•]\s+)|(?:\s*\n\s*\d{1,2}\s*[.)]\s+)")
_CONECTOR = re.compile(r"\s*(?:,|;|\se\s|\seou\s|\sou\s)\s*")

# --- vocabulário de classificação (canônico; ver padrao-planejamento-vistoria.md) ---
# Verbo de REQUISIÇÃO GENÉRICO — modalidade-neutro: sozinho não classifica nada.
# (verificar, constatar, apontar, indicar, avaliar, analisar, determinar, apurar,
#  conferir, informar, esclarecer, dizer…) — cai em INDETERMINADA sem outro sinal.
# Verbo de OBSERVAÇÃO DIRETA. É modalidade-neutro QUANTO AO OBJETO: "registrar o
# assentamento diferencial" / "descrever a resistividade elétrica" exigem
# instrumento. Só estabelece INSPECAO em conjunto com _OBJETO_DESCRITIVO (abaixo);
# sozinho → INDETERMINADA. Mesmo princípio já aplicado ao ramo do fenômeno.
_VERBO_OBSERVACAO_DIRETA = re.compile(
    r"(?i)\b(?:descrever|registrar|fotografar|inspecionar|examinar|observar|"
    r"vistoriar|caracterizar|localizar)\b"
)
# Sufixo flexional PT-BR FECHADO — nunca \w* irrestrito. Cobre pluralização
# regular (-s/-es); derivações específicas (-ção/-ções, -ico/-ica, -l/-is,
# -m/-ns) são escritas por extenso em cada entrada que precisa delas.
# V13.1 (PASS A6 contra ed3e7ee, SAME_CLASS_SURVIVED — 4ª rodada): TODO
# vocabulário fechado desta contabilidade (_OBJETO_DESCRITIVO,
# _FENOMENO_OBSERVAVEL, _COMPLEMENTO_SEGURO) terminava em `\w*` — irrestrito,
# não apenas flexão. "parede"+"\w*" também casa "paredeZETA" por inteiro,
# absorvendo um sufixo desconhecido colado ao radical reconhecido como se
# fosse uma variação morfológica legítima — um artefato plausível de extração
# de PDF/OCR que perde o espaço entre duas palavras reais (mesma classe de
# _RUIDO já reconhecida neste módulo), e que atinge a AUTORIDADE efetiva por
# dentro do próprio TIER 1 que `evidencia_requerida` trata como "sempre
# seguro" — não é gated por `permitir_aberto`. Bounded fecha a classe inteira
# sem exigir enumerar os sufixos maliciosos (que são infinitos): só o que
# está na lista fechada é aceito, o resto vira resíduo.
# V13.2 (PASS A7): só "-s" — todo radical que usa _FLEX termina em vogal
# (plural regular "+s"); os poucos radicais consoante-final (pilar/corredor/
# bolor) têm "(?:es)?" explícito. `(?:s|es)?` aceitava "paredees" (radical +
# "es") — over-aceitação limitada, não open-world, mas eliminada.
_FLEX = r"s?"
# Objeto de natureza DESCRITIVO-QUALITATIVA (não grandeza, não patologia
# instrumental). Só habilita INSPECAO junto de um verbo de observação direta.
# Lista permissiva e gated: sua incompletude causa SOBRE-BLOQUEIO (o requisito cai
# em INDETERMINADA → medição estrita), nunca falso-verde.
_OBJETO_DESCRITIVO = re.compile(
    r"(?i)\b(?:padr[aã]o\s+(?:construtiv[oa]s?|de\s+acabamento|arquitet[oô]nic[oa]s?|de\s+ocupa[cç](?:[aã]o|[oõ]es)|de\s+qualidade)|"
    r"acabament[oa]s?|"
    r"estado\s+(?:geral|de\s+conserva[cç](?:[aã]o|[oõ]es)|aparente|de\s+uso|construtiv[oa]s?)|"
    r"estado\s+d[oa]s?\s+(?:revestiment[oa]s?|acabament[oa]s?|im[óo]ve(?:l|is)|"
    r"edifica[cç](?:[aã]o|[oõ]es)|constru[cç](?:[aã]o|[oõ]es)|benfeitoria" + _FLEX + r"|"
    r"pintura" + _FLEX + r"|forro" + _FLEX + r"|elemento" + _FLEX + r"|componente" + _FLEX + r")|"
    r"conserva[cç][aã]o\s+(?:geral|d[oa]\s+(?:im[óo]ve(?:l|is)|edifica[cç](?:[aã]o|[oõ]es)|constru[cç](?:[aã]o|[oõ]es)|"
    r"revestiment[oa]s?|acabament[oa]s?|pintura" + _FLEX + r"|fachada" + _FLEX + r"|forro" + _FLEX + r"|"
    r"benfeitoria" + _FLEX + r"|be(?:m|ns)))|"
    r"aspecto\s+(?:geral|visual|construtiv[oa]s?|est[eé]tic[oa]s?|arquitet[oô]nic[oa]s?)|"
    r"sistema\s+construtiv[oa]s?|m[eé]todo\s+construtiv[oa]s?|t[eé]cnica\s+construtiv[oa]s?|"
    r"tipologi(?:as?|c[oa]s?)|configura[cç](?:[aã]o|[oõ]es)\s+(?:geral|arquitet[oô]nic[oa]s?|espacial)|"
    r"disposi[cç](?:[aã]o|[oõ]es)\s+d[oe]s?\s+ambientes|"
    r"caracter[íi]sticas\s+(?:gerais|construtiv[oa]s?|arquitet[oô]nic[oa]s?|f[íi]sicas))\b"
)
# Qualificador de MODO que evidencia constatação VISUAL. NUNCA é prova de objeto:
# não habilita INSPECAO sozinho (o verbo "fotografar" casa aqui e é tão
# modalidade-neutro quanto "registrar" — "fotografar o parâmetro omega" não prova
# que o objeto seja observável). Só conta combinado com prova positiva NO OBJETO
# (ver _funil em classificar_requisito). O conector existencial ("há"/"existe"/
# "existência de"/"presença de") NÃO entra aqui: é tão modalidade-neutro quanto o
# verbo genérico ("medir se HÁ trinca > 0,3 mm" também usa "há").
_MARCADOR_VISUAL = re.compile(
    r"(?i)(?:\b(?:visivel|visiveis|aparente|aparentes|visualmente|ocular|oculares|"
    r"perceptivel|perceptiveis|fotograf(?:ar|ad[oa]s?|ic[oa]s?|icamente|ias?)|"
    r"inspecao\s+visual|exame\s+visual|"
    r"aspecto\s+visual)\b|\ba\s+olho\s+nu\b)"
)
# Substantivo de FENÔMENO/anomalia inerentemente avaliável por observação a olho nu
# (NÃO grandeza). Lista permissiva e DELIBERADAMENTE conservadora: só entra o que é
# inequivocamente visual. Termos cuja avaliação usual é instrumental (umidade
# relativa, corrosão/oxidação — profundidade/potencial/taxa) NÃO entram aqui: sem
# outro sinal caem em INDETERMINADA → MEDICAO estrita (sobre-bloqueio seguro).
_FENOMENO_OBSERVAVEL = re.compile(
    r"(?i)\b(?:fissura" + _FLEX + r"|trinca" + _FLEX + r"|rachadura" + _FLEX + r"|fenda" + _FLEX + r"|mancha" + _FLEX + r"|"
    r"infiltra(?:[cç](?:[aã]o|[oõ]es)|d[oa]s?)|mofo" + _FLEX + r"|bolor(?:es)?|efloresc[eê]nci[ae]s?|"
    r"destacamento" + _FLEX + r"|descolamento" + _FLEX + r"|desplacamento" + _FLEX + r"|desprendimento" + _FLEX + r"|"
    r"desagrega(?:[cç](?:[aã]o|[oõ]es)|d[oa]s?)|pulverul(?:ent[oa]s?)|bolha" + _FLEX + r"|empolamento" + _FLEX + r"|ferruge(?:m|ns)|"
    r"vazamento" + _FLEX + r"|goteira" + _FLEX + r"|gotejamento" + _FLEX + r"|"
    r"patologi(?:as?|c[oa]s?)|manifesta[cç](?:[aã]o|[oõ]es)|anomalia" + _FLEX + r"|"
    r"avaria" + _FLEX + r"|deteriora[cç](?:[aã]o|[oõ]es)|desgaste" + _FLEX + r"|"
    r"vegeta[cç](?:[aã]o|[oõ]es)|entulho" + _FLEX + r"|sujidade" + _FLEX + r")\b"
)
_VERBO_MEDICAO = re.compile(r"(?i)\b(?:medir|medi[cç][aã]o|aferir|mensurar|quantificar|dimensionar|calcular|ensai\w+|testar\s+(?:a\s+)?(?:carga|resist|press|estanqu))\b")
# Grandezas inerentemente dimensionais — tolerante a plural/flexão (…\w*) para que
# "flechas"/"cargas"/"desníveis" degradem para MEDICAO, nunca escapem por token exato.
_GRANDEZA_DIMENSIONAL = re.compile(
    r"(?i)\b(?:espessura|recalque|flecha|prumo|aprumo|desaprumo|desvio\s+de\s+prumo|"
    r"nivelamento|desn[íi]ve|inclina[cç][aã]|caimento|declividade|planicidade|planeza|"
    r"deforma[cç][aã]|deslocamento|esquadro|dimens|[aá]rea|volume|cota|dist[aâ]ncia|"
    r"[aâ]ngulo|largura|altura|comprimento|extens[aã]|profundidade|di[aâ]metro|"
    r"abertura\s+d[ae]s?\s+(?:fissur|trinc)|vaz[aã]o|vaz[õo]es|carga|tens[aã]o\s+atuante)\w*"
)
_PROPRIEDADE_ENSAIAVEL = re.compile(
    r"(?i)\b(?:resist[eê]ncia|ader[eê]ncia|desempenho|dureza|absor[cç][aã]o|permeabilidade|"
    r"estanqueidade|isolamento|condutividade|m[óo]dulo|arrancamento|puc?h[- ]?off|pull[- ]?off|"
    r"est[áa]nqu\w+|estabilidade|capacidade\s+(?:de\s+carga|portante|resistente|estrutural)|"
    r"portante|comprometimento\s+estrutural)\b"
)
# Pedir "grau/nível/índice/teor/potencial/magnitude ... DE algo" é um pedido
# quantificado -> MEDICAO, independentemente da grandeza que segue (o verbo não
# desambigua). Não inclui "primeiro/segundo grau" (exige "de/do/dos" depois).
_QUANTIFICADOR = re.compile(
    r"(?i)\b(?:teor|[íi]ndice|n[íi]vel|grau|percentual|coeficiente|taxa|magnitude|"
    r"potencial|intensidade|amplitude|propor[cç][aã]o|quantidade)\s+d[aeo]s?\b"
)
# Patologias cuja caracterização usual é ensaio/instrumento. Sufixo \w* (não \b)
# para casar formas flexionadas ("corrosão das armaduras", "potencial de corrosão").
_PATOLOGIA_ENSAIAVEL = re.compile(
    r"(?i)\b(?:carbonata[cç]\w*|cloret\w*|corros[aã]o\s+d[ae]s?\s+armadur\w*|"
    r"profundidade\s+de\s+carbonata\w*|potencial\s+de\s+corros\w*|"
    r"perda\s+de\s+se[cç][aã]o|se[cç][aã]o\s+resistente\s+d[ae]s?\s+(?:barra|armadur))\b"
)
# Grandezas cuja leitura é inerentemente instrumental (higrotérmica, fotométrica,
# acústica, vibração) — não constatáveis a olho nu mesmo sem número explícito.
_GRANDEZA_INSTRUMENTAL = re.compile(
    r"(?i)\b(?:umidade\s+relativa|umidade\s+do\s+ar|ponto\s+de\s+orvalho|"
    r"temperatura\s+(?:superficial|ambiente|do\s+ar|de\s+bulbo|de\s+orvalho|de\s+contato)|"
    r"iluminanc\w*|luminanc\w*|"
    r"n[íi]vel\s+de\s+(?:ru[íi]do|press[aã]o\s+sonora)|press[aã]o\s+sonora|"
    r"vibra[cç][aã]o|acelera[cç][aã]o|frequ[eê]ncia\s+natural)\b"
)
# Critério numérico sobre texto NORMALIZADO (sem acento): "≤"/"≥" não chegam aqui
# (normalizar faz ascii-strip) — recuperados por _SINAL_NUMERICO_BRUTO. Cobre também
# conectivos comparativos em português ("superior a N", "no mínimo de N", …).
_CRITERIO_NUMERICO = re.compile(
    r"(?i)(?:"
    r"[<>]=?\s*"
    r"|(?:no\s+)?minim\w*\s+(?:de\s+|em\s+)?"
    r"|(?:no\s+)?maxim\w*\s+(?:de\s+|em\s+)?"
    r"|(?:maior|menor|superior|inferior)\s+(?:ou\s+igual\s+)?(?:a|que|do\s+que)\s+"
    r"|acima\s+de\s+|abaixo\s+de\s+"
    r"|tolerancia\s+de\s+|limite\s+de\s+"
    r")\d"
)
# Operadores unicode e quantidade DIMENSIONADA sobre o texto CRU (pré-ascii-strip):
# "≤ 0,3 mm", "5 kN", "30°", "2%" são sinais de medição independentemente do verbo.
_SINAL_NUMERICO_BRUTO = re.compile(
    r"[<>≤≥]\s*=?\s*\d"
    r"|\d\s*(?:°|graus?\b)"
    r"|\d[\d.,]*\s*(?:mm|cm|m²|m³|m2|m3|km|kn|kgf|tf|mpa|kpa|pa|%)(?![a-zà-ÿ])",
    re.IGNORECASE,
)
_DOC_VERBO = re.compile(r"(?i)\b(?:solicitar|requisitar|juntar|apresentar|obter|anexar|exibir)\b")
_DOC_ARTEFATO = re.compile(r"(?i)\b(?:documento|projeto|memorial|planta|art\b|rrt\b|laudo|contrato|nota\s+fiscal|as\s*built|caderno|especifica[cç][aã]o\s+t[eé]cnica|habite-se|alvar[aá]|di[aá]rio\s+de\s+obra)\b")

# --- contabilidade observacional (V11; reparo de AUTORIDADE, P0-A2-1) ---------
# Prova de objeto por OCORRÊNCIA bastava ao fenômeno INCIDENTAL: "verificar o
# cobrimento das armaduras JUNTO ÀS FISSURAS" casava _FENOMENO_OBSERVAVEL dentro
# do PP locativo e concedia INSPECAO a objeto metrológico/desconhecido. A
# concessão de INSPECAO passa a exigir CONTABILIDADE OBSERVACIONAL INTEGRAL da
# demanda: PP locativo é removido por inteiro (seu conteúdo NÃO conta — o local
# da observação não é a demanda), NPs observacionais são consumidos com seus
# de-complementos e qualificadores de modo, e QUALQUER token de conteúdo residual
# derruba a cláusula para INDETERMINADA. UNKNOWN NEVER BECOMES INSPECAO EFFECTIVE.
#
# V12 (reparo ESTRUTURAL de AUTORIDADE, não lexical — PASS A3+B3 contra 00bf26b,
# SAME_CLASS_SURVIVED, AUTONOMOUS_CAUSAL_REPAIR_LOOP_V1): o PP locativo tinha
# fronteira de parada ASSIMÉTRICA (só " e " ou fim de string) — coordenação com
# "ou"/vírgula fazia o PP engolir um objeto coordenado desconhecido até o fim da
# string ("no forro OU o parâmetro omega" → PP consome tudo). O de-complemento
# "de X" do NP também era IRRESTRITO — qualquer palavra após "de/do/da" virava
# prova de objeto por FORMA sintática, sem qualquer verificação de conteúdo
# ("a fissura DO ZETA" → "zeta" absorvido cegamente). Ambos os vazamentos
# compartilham a MESMA classe causal (conteúdo desconhecido anexado a um
# fenômeno real, absolvido por uma regra de consumo sem limite) — o reparo é
# estrutural em ambos os pontos, não mais um substantivo/lookahead isolado:
#   (a) a demanda é primeiro partida em CLÁUSULAS COORDENADAS pelo mesmo
#       conector canônico já usado por _segmentar (_CONECTOR — fonte única, não
#       um lookahead ad hoc); cada cláusula é contabilizada de forma ISOLADA —
#       um PP locativo NUNCA pode atravessar uma fronteira de coordenação.
#   (b) o de-complemento só é absorvido sem exigência adicional quando o
#       substantivo pertence a um vocabulário FECHADO de elemento/local
#       construtivo ou atribuição de causa comum na observação a olho nu
#       (_COMPLEMENTO_SEGURO — nunca introduz conteúdo técnico novo, só
#       localiza/atribui o MESMO fenômeno já reconhecido); um de-complemento
#       FORA desse vocabulário só é absorvido quando há prova de modo/
#       suficiência visual EXPLÍCITA em algum ponto da demanda (o mesmo sinal
#       `modo_observacional` já usado para habilitar o ramo descritivo — verbo
#       de observação direta ou marcador visual) — a prova de que a
#       MANIFESTAÇÃO em si é diretamente visível/registrada, independentemente
#       do nome técnico atribuído a ela (mantém "FOTOGRAFAR a fissura DE
#       LAMBDA" e "REGISTRAR a mancha DE ZETA VISÍVEL" = INSPECAO); sem essa
#       prova em lugar nenhum da demanda, o complemento desconhecido permanece
#       resíduo ("VERIFICAR a fissura DO ZETA", nenhum marcador, →
#       INDETERMINADA — este é exatamente o P0 confirmado por PASS B3).
#
# V12.2 (reparo ESTRUTURAL — PASS A5+B5 contra 8438104, SAME_CLASS_SURVIVED
# pela 3ª vez consecutiva na mesma classe; AUTONOMOUS_CAUSAL_REPAIR_LOOP_V1):
# o span capturado pelo PP locativo era uma DELEÇÃO INCONDICIONAL de até 3
# tokens — nunca confrontada com nenhuma verificação de conteúdo. Isso permitia
# que um de-complemento "de X" aparecesse DENTRO do próprio span do PP (não
# coordenado a ele, não em outra cláusula — literalmente as palavras seguintes
# à preposição) e fosse descartado junto com o substantivo do local, sem NUNCA
# alcançar a contabilidade de resíduo: "verificar a fissura NA PAREDE DO ZETA"
# — "parede do zeta" inteiro virava "local", com "zeta" absolvido só por
# posição sintática, não por prova de conteúdo. Mesma classe causal de sempre
# (conteúdo desconhecido absolvido por uma regra de consumo sem verificação),
# agora dentro do próprio mecanismo que V12/V12.1 usaram para reparar as duas
# classes anteriores. O PP locativo NUNCA MAIS consome uma continuação "de X":
# ele só remove a preposição + o substantivo do local, ponto — qualquer "de X"
# que viesse a seguir permanece no texto e, após a remoção do PP, fica
# diretamente adjacente ao head do fenômeno (o mesmo texto que antes ficava
# "atrás" do PP), sendo então julgado pelo MESMO mecanismo de complemento já
# usado em todo o resto da contabilidade (_COMPLEMENTO_SEGURO/_MARCADOR_VISUAL)
# — nunca mais por uma deleção cega e paralela. Este é o repair mínimo
# (§13 do LOOP BREAKER): remove do PP locativo o poder de fabricar completude,
# sem introduzir framework, sem NLP, sem nova entidade de dados.
#
# V13.1 (PASS A6 contra ed3e7ee, SAME_CLASS_SURVIVED — 4ª rodada, mesmo após a
# separação SUGESTÃO/AUTORIDADE já confirmada genuína pelas duas revisões):
# o V12.2 limitou o span do PP a UMA palavra, mas ainda a deletava
# INCONDICIONALMENTE — sem NENHUMA verificação de conteúdo, ao contrário de
# todo outro ponto de absorção deste módulo. "verificar a fissura NO ZETA"
# tinha "zeta" inteiramente descartado como "nome do local", nunca alcançando
# a contabilidade de resíduo — e isso valia tanto para a SUGESTÃO quanto para
# o modo ESTRITO de `evidencia_requerida` (a deleção acontece ANTES de
# qualquer split TIER1/TIER2, então nenhum dos dois modos jamais via o
# conteúdo). O PP locativo agora só remove a preposição quando a palavra
# seguinte pertence ao MESMO vocabulário fechado já usado para o
# de-complemento (_COMPLEMENTO_SEGURO, definido abaixo) — um substantivo de
# local desconhecido não é mais removido "de graça": permanece no texto e
# vira resíduo, IDÊNTICO ao que já acontecia com um de-complemento
# desconhecido fora de um PP.
# Qualificador admitido DENTRO do NP observacional (modo/aspecto, nunca objeto).
# Só se ancora APÓS um head consumido — não cria prova de objeto por si só.
_QUALIFICADOR_NP = (
    r"visivel|visiveis|aparente|aparentes|visualmente|ocular|oculares|perceptivel|perceptiveis|"
    r"fotograf(?:ar|ad[oa]s?|ic[oa]s?|icamente|ias?)|superficial|superficiais|pontual|pontuais|"
    r"localizad[oa]s?|generalizad[oa]s?|alegad[oa]s?")
# Complemento SEMPRE seguro (independe de modo_observacional): elemento/local
# construtivo, ou atribuição de causa cuja manifestação típica já é uma marca
# visível por definição (umidade→mancha, bolor, sujidade — o head já garante
# isso; o complemento só nomeia a causa aparente, não introduz medição). Lista
# permissiva e DELIBERADAMENTE fechada (mesmo padrão de
# _FENOMENO_OBSERVAVEL/_OBJETO_DESCRITIVO): sua incompletude causa
# SOBRE-BLOQUEIO seguro (P2), nunca falso-verde. Sufixos FECHADOS (_FLEX ou
# alternativa explícita), nunca `\w*` irrestrito (V13.1 — ver nota acima e no
# topo do módulo sobre _FLEX: "paredeZETA" não pode mais ser absorvido como
# se fosse uma flexão de "parede").
_COMPLEMENTO_SEGURO = (
    r"parede" + _FLEX + r"|teto" + _FLEX + r"|piso" + _FLEX + r"|laje" + _FLEX + r"|viga" + _FLEX + r"|"
    r"pilar(?:es)?|muro" + _FLEX + r"|telhado" + _FLEX + r"|telha" + _FLEX + r"|"
    r"forro" + _FLEX + r"|calha" + _FLEX + r"|rodap[eé]" + _FLEX + r"|esquadria" + _FLEX + r"|porta" + _FLEX + r"|"
    r"janela" + _FLEX + r"|escada" + _FLEX + r"|"
    r"corredor(?:es)?|ambiente" + _FLEX + r"|c[oô]modo" + _FLEX + r"|im[óo]ve(?:l|is)|"
    r"edifica[cç](?:[aã]o|[oõ]es)|edif[íi]cio" + _FLEX + r"|"
    r"estrutura" + _FLEX + r"|fachada" + _FLEX + r"|alvenaria" + _FLEX + r"|revestiment[oa]s?|"
    r"acabament[oa]s?|cobertura" + _FLEX + r"|"
    r"elemento" + _FLEX + r"|componente" + _FLEX + r"|"
    r"contrapiso" + _FLEX + r"|funda[cç](?:[aã]o|[oõ]es)|platibanda" + _FLEX + r"|beira(?:l|is)|"
    r"guarda[- ]?corpo" + _FLEX + r"|"
    r"peitori(?:l|s)?|batente" + _FLEX + r"|soleira" + _FLEX + r"|junta" + _FLEX + r"|drywall|gesso" + _FLEX + r"|"
    r"banheiro" + _FLEX + r"|"
    r"cozinha" + _FLEX + r"|varanda" + _FLEX + r"|sacada" + _FLEX + r"|garage(?:m|ns)|terra[cç]o" + _FLEX + r"|"
    r"umidade" + _FLEX + r"|bolor(?:es)?|mofo" + _FLEX + r"|"
    r"detalhe" + _FLEX + r"|contexto" + _FLEX + r"|aproxima[cç](?:[aã]o|[oõ]es)|"
    r"pintura" + _FLEX + r"|benfeitoria" + _FLEX
)
_PP_LOCATIVO = re.compile(
    r"(?i)\b(?:em|n[ao]s?|numa?|junto\s+a[s]?|proximo\s+a[s]?|perto\s+d[aeo]s?)"
    r"\s+(?:" + _COMPLEMENTO_SEGURO + r")\b")
_CADEIA_NP_SEGURA = (
    r"(?:\s+(?:(?:" + _QUALIFICADOR_NP + r")\b|d[aeo]s?\s+(?:" + _COMPLEMENTO_SEGURO + r")\b))*")
# de-complemento ABERTO (substantivo qualquer): só disponível quando a demanda
# já tem prova de modo/suficiência visual explícita em algum ponto (parâmetro
# `modo_observacional`, calculado sobre o texto integral — o mesmo sinal que já
# habilita o ramo descritivo; não é um eixo novo).
_CADEIA_NP_ABERTA = r"(?:\s+(?:(?:" + _QUALIFICADOR_NP + r")\b|d[aeo]s?\s+\w+))*"
_NP_FENOMENO_SEGURO = re.compile(_FENOMENO_OBSERVAVEL.pattern + _CADEIA_NP_SEGURA)
_NP_DESCRITIVO_SEGURO = re.compile(_OBJETO_DESCRITIVO.pattern + _CADEIA_NP_SEGURA)
_NP_FENOMENO_ABERTO = re.compile(_FENOMENO_OBSERVAVEL.pattern + _CADEIA_NP_ABERTA)
_NP_DESCRITIVO_ABERTO = re.compile(_OBJETO_DESCRITIVO.pattern + _CADEIA_NP_ABERTA)
# Scaffolding da demanda: conectores existenciais (nome E verbo conjugado —
# "existe fissura" tem tanto valor scaffold quanto "existência de fissura"; a
# forma verbal não vira prova de objeto sozinha, mas também não é conteúdo
# residual que derruba um fenômeno genuíno já contabilizado) e marcador processual.
# V13.2 (PASS A7+B7 contra a5626b7, SAME_CLASS_SURVIVED — 5ª rodada): sufixos
# FECHADOS, nunca `\w*` irrestrito — mesmo reparo que V13.1 aplicou aos três
# vocabulários de objeto, agora estendido a TODA primitiva que a
# `_contabilidade_observacional` remove (`.sub`) ou consome antes da checagem de
# resíduo: "presencaZETA"/"alegadaZETA" eram apagados como scaffold e o token
# desconhecido nunca virava resíduo.
_SCAFFOLD = re.compile(r"(?i)\b(?:presen[cç]as?|ausen[cç]ias?|alegad[oa]s?|"
                        r"exist[eê]nci[ae]s?|existe|existem|existir|ha|houve|havia)\b")
# Classes fechadas — nunca são demanda material.
_CLASSE_FECHADA = frozenset({
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "num", "numa", "ao", "aos", "por", "pelo",
    "pela", "pelos", "pelas", "com", "sem", "sob", "sobre", "entre", "ate", "apos",
    "conforme", "perante", "para", "pra", "e", "ou", "nem", "se", "como", "que",
    "porque", "pois", "quando", "onde", "ser", "estar", "haver", "ter", "sao", "era",
    "eram", "foi", "esta", "estao", "esteja", "estiver", "seja", "sejam", "ha",
    "mais", "menos", "muito",
})

_MIN_TERMOS = 1

# Pontuação de SENTENÇA — estrutural, aparece em texto de requisito normal e
# não carrega conteúdo material: o requisito termina em ".", listas usam ","/
# ";", apostos entre parênteses/aspas. QUALQUER outro caractere não-espaço
# não-alfanumérico que sobreviva à contabilidade da AUTORIDADE (`@`, `+`, `~`,
# `%`, `&`, `=`, `#`, `$`, `^`, `|`, `<`, `>`, `\`, backtick, `*` — e também
# "/" e "-" isolados) é resíduo material não contabilizado — V13.4, PASS A9+B9
# contra e3a8afc; V13.5, PASS A11 restaura "/"/"-" fora daqui. "/" e "-" NÃO
# são pontuação de sentença para a AUTORIDADE: um objeto único "/" ("Verificar
# a fissura do /.") não pode virar OBSERVACIONAL. Custo assumido (P2, mesma
# direção fail-closed): "e/ou" idiomático e radicais hifenizados fora do
# vocabulário fechado caem para DESCONHECIDA — SAFE_OVERBLOCKING aceitável,
# FALSE_APTO não. Objeto fragmentado ("x/y") já cai pelos fragmentos `\w+`.
_PONTUACAO_SENTENCA = frozenset(".,;:!?()[]{}\"'")


def remover_ruido_estrutural(texto: str) -> str:
    limpo = str(texto or "")
    for padrao in _RUIDO:
        limpo = padrao.sub(" ", limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def _contabilidade_observacional(base, permitir_aberto=True):
    """Contabilidade integral da demanda (V11+V12+V12.1+V13). Retorna (heads, residual).

    `permitir_aberto=False` desativa o TIER 2 (de-complemento aberto licenciado
    por marcador visual) em TODA a demanda — usado por `evidencia_requerida`
    (V13) para calcular a autoridade EFETIVA, mais estrita que a sugestão
    (`classificar_requisito`, sempre `permitir_aberto=True`): um marcador visual
    é uma prova textual forte o bastante para a SUGESTÃO, mas o objeto
    continua, por definição, desconhecido — a autoridade efetiva exige que TODO
    o conteúdo se reduza a vocabulário fechado, nunca a uma palavra confiada só
    por causa de um marcador em outro lugar da frase.

    A demanda (após o verbo inicial removido) é partida em CLÁUSULAS coordenadas
    pelo mesmo conector canônico de _segmentar (_CONECTOR: ,/;/e/ou/eou) — um PP
    locativo ou de-complemento NUNCA atravessa fronteira de coordenação. Cada
    cláusula é contabilizada de forma ISOLADA, incluindo os sinais habilitadores
    (V12.1, PASS A4+B4 contra daaceac: um marcador em uma cláusula NÃO pode
    liberar prova de objeto em outra cláusula coordenada sem marcador próprio —
    "fotografar a mancha E a fissura do zeta" não absolve "zeta" só porque
    "fotografar" está na cláusula vizinha):
      - o ramo descritivo (_OBJETO_DESCRITIVO) exige, NESTA cláusula, verbo de
        observação direta OU marcador visual (condição original, inalterada);
      - o de-complemento ABERTO (qualquer palavra) exige, NESTA cláusula,
        marcador visual EXPLÍCITO (_MARCADOR_VISUAL) — NUNCA o verbo de
        observação direta genérico sozinho (V12.1, PASS B4: o próprio módulo já
        documenta esses verbos como "modalidade-neutros QUANTO AO OBJETO";
        usá-los para justificar o objeto do complemento contradiz essa própria
        premissa — "registrar a fissura DO ZETA" não pode provar que "zeta" é
        observável só porque "registrar" é um verbo de observação direta).
        "fotografar" continua suficiente sozinho por já estar em
        _MARCADOR_VISUAL — é definicionalmente um ato visual/fotográfico, não
        apenas um verbo de documentação genérico (mantém a contraparte
        positiva pré-existente: "fotografar a fissura DE LAMBDA" = INSPECAO).
        Sem marcador nesta cláusula, só o complemento SEMPRE seguro
        (_COMPLEMENTO_SEGURO) é absorvido.
    Em cada cláusula: PP locativo removido por inteiro E BOUNDED (um punhado de
    palavras após a preposição — nunca até o fim da cláusula: um NP locativo
    real é curto; delimitar por comprimento fecha qualquer coordenador de
    português não enumerado em _CONECTOR — "bem como"/"assim como"/"além
    de"/parênteses/travessão/"/" — sem precisar enumerá-los um a um, V12.1,
    PASS A4 contra daaceac), NP observacional consumido (head de fenômeno
    sempre; head descritivo só com prova de modo desta cláusula) com
    de-complemento e qualificador de modo, scaffolding descartado. QUALQUER
    token de conteúdo residual fora de classe fechada OU cláusula sem nenhum
    head derruba a demanda INTEIRA para INDETERMINADA — coordenar um fenômeno
    real a uma cláusula não resolvida NUNCA absolve a cláusula não resolvida.

    O piso de comprimento do token residual depende do MODO (V13.3, PASS B8
    contra 527af78): na SUGESTÃO (`permitir_aberto=True`) o piso é \\w{2,} —
    tokens de 1 caractere são ruído de segmentação e não derrubam a sugestão;
    na AUTORIDADE efetiva (`permitir_aberto=False`, caminho de
    `evidencia_requerida`) o piso é \\w+ (cardinalidade ≥1) — um token
    desconhecido de 1 caractere ("x", "5") ou fragmentado por pontuação
    ("a-b" → "a","b"; "x/y" → "x","y") NÃO pode desaparecer silenciosamente da
    contabilidade e virar prova de completude; "/" e "-" isolados (objeto único
    "do /.") também são resíduo — não são pontuação de sentença para a
    AUTORIDADE (V13.5, PASS A11). SAFE_OVERBLOCKING de "eixo A" ou de "e/ou"
    fora do vocabulário é P2 aceitável; FALSE_APTO é P0.
    `ABSENCE_AFTER_LOSSY_NORMALIZATION != PROOF_OF_SEMANTIC_COMPLETENESS`."""
    t = base.strip()
    partes = t.split(None, 1)
    verbo_lider = ""
    if partes and _VERBO_TECNICO.fullmatch(re.sub(r"\W+", "", partes[0])):
        verbo_lider = partes[0]
        t = partes[1] if len(partes) > 1 else ""
        # V13.5 (PASS B10 contra 9d65973): o token do verbo-líder é descartado
        # de `t` INTEIRO — um símbolo material FUNDIDO ao verbo ("verificar@"/
        # "@verificar"/"veri@ficar") sumia sem virar resíduo (`re.sub(\W+)` o
        # remove só para o match). Na AUTORIDADE, qualquer não-espaço não-
        # alfanumérico colado ao verbo — exceto pontuação de sentença plausível
        # (`.,;:` de "Verificar," / "Verificar:") — derruba a promoção.
        if not permitir_aberto and any(
                not s.isspace() and not s.isalnum() and s not in ".,;:"
                for s in verbo_lider):
            return 0, True
    clausulas = [c.strip() for c in _CONECTOR.split(t) if c and c.strip()]
    if not clausulas:
        clausulas = [t]
    heads_total = 0
    for indice, clausula in enumerate(clausulas):
        # O verbo inicial (já descartado de `t`) só é reintegrado à checagem de
        # modo da PRIMEIRA cláusula — a única que efetivamente o tinha; uma
        # cláusula coordenada seguinte nunca herda o verbo de outra.
        texto_modo = f"{verbo_lider} {clausula}" if indice == 0 else clausula
        habilita_descritivo = bool(_VERBO_OBSERVACAO_DIRETA.search(texto_modo)
                                    or _MARCADOR_VISUAL.search(texto_modo))
        habilita_aberto = permitir_aberto and bool(_MARCADOR_VISUAL.search(texto_modo))
        if habilita_aberto:
            padroes = [_NP_DESCRITIVO_ABERTO, _NP_FENOMENO_ABERTO] if habilita_descritivo else [_NP_FENOMENO_ABERTO]
        else:
            padroes = [_NP_DESCRITIVO_SEGURO, _NP_FENOMENO_SEGURO] if habilita_descritivo else [_NP_FENOMENO_SEGURO]
        c = _PP_LOCATIVO.sub(" ", clausula)
        heads_clausula = 0
        for padrao in padroes:
            while True:
                c, n = padrao.subn(" ", c, count=1)
                if not n:
                    break
                heads_clausula += 1
        c = _SCAFFOLD.sub(" ", _MARCADOR_VISUAL.sub(" ", c))
        if permitir_aberto:
            residual_clausula = [tok for tok in re.findall(r"\w{2,}", c) if tok not in _CLASSE_FECHADA]
        else:
            # AUTORIDADE: cardinalidade ≥1 para token-palavra E qualquer símbolo
            # não-espaço não-alfanumérico que não seja pontuação de sentença —
            # "@"/"+"/"~"/"′" (sobrevive à normalização ou nem chega a ser \w)
            # não pode desaparecer silenciosamente (V13.4, PASS A9+B9).
            residual_clausula = [tok for tok in re.findall(r"\w+", c) if tok not in _CLASSE_FECHADA]
            residual_clausula += [s for s in c if not s.isspace() and not s.isalnum()
                                  and s not in _PONTUACAO_SENTENCA]
        if not heads_clausula or residual_clausula:
            return heads_total + heads_clausula, True
        heads_total += heads_clausula
    return heads_total, False


def classificar_requisito(texto: str) -> str:
    """MEDICAO | DOCUMENTO | INSPECAO | INDETERMINADA.

    Default fail-closed. Verbo de requisição genérico ("verificar"/"constatar"/…),
    conector existencial ("há"/"existe"/"existência de"), verbo de observação
    direta ("registrar"/"descrever"/"fotografar"/…) e qualificador de MODO
    ("visualmente"/"fotograficamente"/"aparente"/…) são MODALIDADE-NEUTROS —
    nenhum estabelece INSPECAO sem prova POSITIVA NO OBJETO.

    FUNIL DE AUTORIDADE (V11+V12, estrutural, não lexical): INSPECAO exige
    CONTABILIDADE OBSERVACIONAL INTEGRAL da demanda, cláusula a cláusula — a
    demanda é partida por coordenação (,/;/e/ou/eou) ANTES de qualquer remoção,
    de modo que um PP locativo ou de-complemento NUNCA atravesse fronteira de
    coordenação (V12: "no forro OU o parâmetro omega" não absolve "o parâmetro
    omega"). Em cada cláusula: PP locativo removido por inteiro (fenômeno
    INCIDENTAL não absolve: "o cobrimento das armaduras junto às fissuras" é
    INDETERMINADA), ≥1 NP observacional consumido (fenômeno inequivocamente
    visual sempre; objeto descritivo-qualitativo só com verbo de observação
    direta ou qualificador de modo) E ZERO token de conteúdo residual. O
    de-complemento do NP ("de X") só é absorvido sem exigência adicional quando X
    é um elemento/local construtivo conhecido (_COMPLEMENTO_SEGURO); um
    complemento desconhecido só é absorvido quando ESTA MESMA cláusula (nunca
    uma cláusula vizinha, V12.1) também traz MARCADOR VISUAL EXPLÍCITO
    (_MARCADOR_VISUAL — "visível"/"aparente"/"fotografar"/…) — NUNCA o verbo de
    observação direta genérico sozinho (V12.1, PASS B4: esses verbos já são
    documentados aqui mesmo como modalidade-neutros quanto ao objeto; "a
    fissura DO ZETA" sozinho é INDETERMINADA mesmo com "registrar"/
    "descrever"/"caracterizar"; "a mancha DE ZETA VISÍVEL" e "fotografar a
    fissura DE LAMBDA" continuam INSPECAO — o marcador visual, não o verbo
    genérico, prova que a manifestação em si é diretamente visível,
    independentemente do nome técnico atribuído a ela). Objeto desconhecido NUNCA
    vira INSPECAO sem essa prova, qualquer que seja o verbo, o marcador de modo
    ou o fenômeno coordenado/locativo. E ausência de qualquer sinal de medição;
    senão → INDETERMINADA (o gate trata como MEDICAO estrita). O modo de falha do
    funil é sobre-bloqueio, nunca falso-verde."""
    base = " " + normalizar(texto) + " "
    bruto = " " + str(texto or "").lower().strip() + " "
    mede = bool(_VERBO_MEDICAO.search(base) or _GRANDEZA_DIMENSIONAL.search(base)
                or _PROPRIEDADE_ENSAIAVEL.search(base) or _PATOLOGIA_ENSAIAVEL.search(base)
                or _GRANDEZA_INSTRUMENTAL.search(base)
                or _CRITERIO_NUMERICO.search(base) or _QUANTIFICADOR.search(base)
                or _SINAL_NUMERICO_BRUTO.search(bruto))
    if _DOC_VERBO.search(base) and _DOC_ARTEFATO.search(base):
        return "DOCUMENTO"
    if mede:
        return "MEDICAO"
    heads, residual = _contabilidade_observacional(base)
    if heads and not residual:
        return "INSPECAO"
    return "INDETERMINADA"


# --- autoridade efetiva de cobertura (V13; AUTONOMOUS_CAUSAL_REPAIR_LOOP_V1) --
# A classe causal recorrente ao longo de V7-V12.2 nunca foi realmente "o
# classificador erra"; foi "a saída do classificador É autoridade efetiva de
# cobertura" — mesmo quando SEMPRE RE-DERIVADA do texto (nunca confiada de
# forma persistida), uma classificação incorreta ainda vira apto=True direto,
# porque `classe == "INSPECAO"` e "cobertura por atividade genérica aceita"
# são a MESMA decisão. Re-derivar fecha adulteração; não fecha ambiguidade
# textual. TEXT_CLASSIFIER_OUTPUT != EFFECTIVE_COVERAGE_AUTHORITY:
#   - classificar_requisito(texto) é SUGESTÃO (suggested_evidence_kind) —
#     inclui o TIER 2 (de-complemento aberto licenciado por marcador visual,
#     ver _contabilidade_observacional): um marcador é prova textual forte o
#     bastante para SUGERIR observação, mas não o bastante para tornar a
#     cobertura efetiva, porque o objeto em si permanece fora de qualquer
#     vocabulário fechado — a promoção desse caso a autoridade seria, de novo,
#     confiar cegamente numa palavra nunca vista por causa de um marcador em
#     outro lugar da frase (a mesma classe de vazamento de sempre, um nível
#     acima).
#   - evidencia_requerida(texto) é a AUTORIDADE (required_evidence_kind) — a
#     única consultada por validar_plano.py (cobertura e execução), pelo motor
#     de vícios e pela redação. Promove MEDICAO/DOCUMENTO diretamente (sinais
#     concretos e de vocabulário fechado — nunca foram a origem de um
#     fail-open nesta issue) e promove INSPECAO a OBSERVACIONAL SOMENTE
#     quando a MESMA demanda também resolve em modo ESTRITO (permitir_aberto=
#     False, só TIER 1): ou seja, só quando TODO o conteúdo — sem exceção —
#     já pertence a vocabulário fechado, nunca quando a promoção dependeu de
#     confiar num marcador para absolver uma palavra desconhecida. Sem essa
#     prova determinística, a demanda é DESCONHECIDA — nunca cobre, nunca
#     fica completa, mesmo que a sugestão diga INSPECAO. Ambiguidade nunca
#     vira completude; sobre-bloqueio (uma demanda genuinamente observacional
#     que só resolveu via TIER 2 cair em DESCONHECIDA) é o modo de falha
#     aceito — nunca o inverso.
_MAPA_EVIDENCIA_REQUERIDA = {"MEDICAO": "METROLOGICA", "DOCUMENTO": "DOCUMENTAL"}


def _perda_na_normalizacao(texto: str) -> bool:
    """True quando `normalizar()` (NFKD + encode('ascii','ignore')) APAGARIA um
    glifo VISÍVEL não-ASCII — qualquer caractere que, após NFKD, não seja ASCII,
    não seja marca combinante (acento do português: `á→a`, `ç→c`, `ã→a`, `õ→o` —
    removível sem apagar conteúdo), não seja espaço e não seja formatação
    invisível (categoria Cf/Cc — zero-width, joiners, bidi). Ex.: `σ` `λ` `µ`
    `Ø` (letras), `′` `″` `·` `•` `‰` `†` (pontuação/símbolo), `£` `×` `∑`,
    caractere de área de uso privado (artefato de extração de PDF/OCR — o
    modelo de ameaça já reconhecido neste módulo em _RUIDO).

    V13.3→V13.4→V13.5 (PASS B8/527af78; PASS A9+B9/e3a8afc; PASS A10+B10/9d65973):
    `ABSENCE_AFTER_LOSSY_NORMALIZATION != PROOF_OF_SEMANTIC_COMPLETENESS`. A
    autoridade NUNCA pode ler "não vejo resíduo" como "provei que não há
    resíduo" quando a normalização apagou/transformou conteúdo sem registrar a
    perda. O V13.3 keyou por CATEGORIA `(L,N,S)` — deixava passar `Po`/`Pd`/`Co`
    (`′ ″ · • – — †`, PUA). O predicado correto NÃO é categoria: um caractere
    não-ASCII só é INÓCUO quando é (i) marca combinante isolada (texto já em
    NFD — acento sem base ainda é acento, não perda, V13.5/PASS A10), ou (ii)
    formatação invisível/espaço, ou (iii) letra latina acentuada — decomposição
    CANÔNICA (sem tag `<…>`) que reduz a UMA letra ASCII —, ou (iv) indicador
    ordinal do português `ª`/`º`. Qualquer outro (símbolo, pontuação
    tipográfica, ligadura, fração, sobrescrito/subscrito, forma de
    compatibilidade `<font>`/`<super>`/`<sub>`/`<circle>`/`<wide>`, alias de
    unidade singleton `Å`/`Ω`/`K`, PUA) é perda. NÃO hardcode símbolos."""
    for ch in str(texto or ""):
        if ord(ch) < 128 or unicodedata.combining(ch):
            continue
        if unicodedata.category(ch) in ("Cf", "Cc", "Zs", "Zl", "Zp"):
            continue  # formatação invisível / espaço (NBSP e afins)
        if ch in ("ª", "º"):
            continue  # indicador ordinal PT ("1º andar", "3ª laje")
        deco = unicodedata.decomposition(ch)
        if deco and " " not in deco:
            return True  # SINGLETON: canônico = alias de unidade (Å/Ω/K);
                         # ou tag `<…>` de compatibilidade sobre 1 codepoint
        if "<" in deco:
            return True  # forma de compatibilidade (`ᵃ` `ℯ` `𝑎` `½`→"1 2"): o
                         # glifo carregava significado próprio, não é acento
        nucleo = "".join(c for c in unicodedata.normalize("NFKD", ch)
                         if not unicodedata.combining(c))
        if len(nucleo) == 1 and nucleo.isascii() and nucleo.isalpha():
            continue  # letra latina acentuada: á→a, ç→c, ã→a, õ→o
        return True
    return False


def evidencia_requerida(texto: str) -> str:
    """METROLOGICA | DOCUMENTAL | OBSERVACIONAL | DESCONHECIDA.

    Autoridade EFETIVA de cobertura — nunca `classificar_requisito` isolado.
    MEDICAO/DOCUMENTO promovem direto (vocabulário fechado, nunca a origem de
    um fail-open). INSPECAO só promove a OBSERVACIONAL quando (a) NENHUM
    conteúdo material foi apagado pela normalização (`_perda_na_normalizacao`,
    V13.3) E (b) a MESMA demanda também é INSPECAO em modo ESTRITO — sem o
    de-complemento aberto licenciado por marcador (permitir_aberto=False) e com
    o piso de resíduo em cardinalidade ≥1, de modo que um token desconhecido de
    1 caractere ou fragmentado por pontuação também derrube a promoção. Sem
    QUALQUER das duas provas, e em qualquer INDETERMINADA, a autoridade é
    DESCONHECIDA. DESCONHECIDA nunca cobre, nunca fica completa: `na dúvida,
    DESCONHECIDA`, não `na dúvida, aceitar a sugestão`. Perda silenciosa nunca
    vira certeza."""
    sugerida = classificar_requisito(texto)
    if sugerida in _MAPA_EVIDENCIA_REQUERIDA:
        return _MAPA_EVIDENCIA_REQUERIDA[sugerida]
    if sugerida != "INSPECAO":
        return "DESCONHECIDA"
    if _perda_na_normalizacao(texto):
        return "DESCONHECIDA"
    base = " " + normalizar(texto) + " "
    heads, residual = _contabilidade_observacional(base, permitir_aberto=False)
    return "OBSERVACIONAL" if (heads and not residual) else "DESCONHECIDA"


def _identidade(quesito_id: str, texto: str) -> str:
    numero = quesito_id.split("-")[-1]
    base = " ".join(sorted(termos(texto))) or normalizar(texto)
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8].upper()
    return f"REQ-{numero}-{digest}"


def _norma_exibicao(fragmento: str) -> str:
    return re.sub(r"^\W+|\W+$", "", normalizar(fragmento)).strip()


def _segmentar(texto_limpo: str) -> list[str]:
    brutos = [p.strip(" \t\n-–—•,;") for p in _SEPARADOR_FORTE.split(texto_limpo) if p and p.strip(" \t\n-–—•,;")]
    fragmentos: list[str] = []
    for bruto in brutos:
        partes = _CONECTOR.split(bruto)
        atual = partes[0].strip() if partes else ""
        for cont in partes[1:]:
            cont = cont.strip()
            if cont and _VERBO_TECNICO.match(cont):
                if atual:
                    fragmentos.append(atual)
                atual = cont
            else:
                atual = f"{atual}, {cont}".strip(", ") if atual else cont
        if atual:
            fragmentos.append(atual)
    saneados: list[str] = []
    pendente = ""
    for parte in fragmentos:
        if pendente:
            parte = f"{pendente} {parte}".strip()
            pendente = ""
        if len(parte) < 8 or len(termos(parte)) < _MIN_TERMOS:
            if saneados:
                saneados[-1] = f"{saneados[-1]} {parte}".strip()
            else:
                pendente = parte  # sem predecessor: funde ADIANTE, nunca descarta
            continue
        saneados.append(parte)
    if pendente:
        if saneados:
            saneados[-1] = f"{saneados[-1]} {pendente}".strip()
        else:
            saneados.append(pendente)
    return saneados or ([texto_limpo] if texto_limpo else [])


def extrair_requisitos_materiais(quesito: dict) -> list[dict]:
    """Requisitos materiais estruturados de um quesito pertinente.

    Cada item: requirement_id, quesito, requisito (cláusula-fonte), texto_normalizado,
    classe (MEDICAO|DOCUMENTO|INSPECAO|INDETERMINADA — SUGESTÃO, ver
    classificar_requisito), evidencia_requerida (METROLOGICA|DOCUMENTAL|
    OBSERVACIONAL|DESCONHECIDA — AUTORIDADE efetiva, ver evidencia_requerida,
    V13), proveniencia, status ∈ {MATERIAL, EXTRACAO_INDETERMINADA}.
    Fail-closed: quesito pertinente cujo texto não produz cláusula material
    rende um requisito EXTRACAO_INDETERMINADA (evidencia_requerida DESCONHECIDA).
    """
    quesito_id = quesito["id"]
    proveniencia = quesito.get("proveniencia") or quesito.get("paginas") or []
    fontes = [str(x) for x in quesito.get("subitens", []) if str(x).strip()]
    if not fontes:
        bruto = quesito.get("materia_tecnica") or quesito.get("texto_integral") or ""
        fontes = [str(bruto)] if str(bruto).strip() else []
    requisitos: list[dict] = []
    vistos: set[str] = set()
    for fonte in fontes:
        for fragmento in _segmentar(remover_ruido_estrutural(fonte)):
            rid = _identidade(quesito_id, fragmento)
            if rid in vistos:
                continue
            vistos.add(rid)
            requisitos.append({
                "requirement_id": rid, "quesito": quesito_id, "requisito": fragmento,
                "texto_normalizado": _norma_exibicao(fragmento), "classe": classificar_requisito(fragmento),
                "evidencia_requerida": evidencia_requerida(fragmento),
                "proveniencia": proveniencia, "status": "MATERIAL",
            })
    if not requisitos:
        norma = _norma_exibicao(remover_ruido_estrutural(" ".join(fontes)))
        requisitos.append({
            "requirement_id": _identidade(quesito_id, norma or quesito_id),
            "quesito": quesito_id, "requisito": (" ".join(fontes)).strip() or quesito_id,
            "texto_normalizado": norma, "classe": "INDETERMINADA", "evidencia_requerida": "DESCONHECIDA",
            "proveniencia": proveniencia, "status": "EXTRACAO_INDETERMINADA",
        })
    return requisitos
