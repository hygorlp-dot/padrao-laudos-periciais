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
  direta ou qualificador de modo — E ausência de qualquer sinal de medição.
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
    r"(?i)\b(?:verificar|avaliar|analis\w+|estimar|medir|caracterizar|quantificar|"
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
# Objeto de natureza DESCRITIVO-QUALITATIVA (não grandeza, não patologia
# instrumental). Só habilita INSPECAO junto de um verbo de observação direta.
# Lista permissiva e gated: sua incompletude causa SOBRE-BLOQUEIO (o requisito cai
# em INDETERMINADA → medição estrita), nunca falso-verde.
_OBJETO_DESCRITIVO = re.compile(
    r"(?i)\b(?:padr[aã]o\s+(?:construtiv\w*|de\s+acabamento|arquitet\w*|de\s+ocupa[cç]\w*|de\s+qualidade)|"
    r"acabament\w*|"
    r"estado\s+(?:geral|de\s+conserva[cç]\w*|aparente|de\s+uso|construtiv\w*)|"
    r"estado\s+d[oa]s?\s+(?:revestiment|acabament|im[óo]vel|edifica|constru|benfeitoria|"
    r"pintura|forro|elemento|componente)\w*|"
    r"conserva[cç][aã]o\s+(?:geral|d[oa]\s+(?:im[óo]vel|edifica\w*|constru\w*|"
    r"revestiment\w*|acabament\w*|pintura\w*|fachada\w*|forro\w*|benfeitoria\w*|bem))|"
    r"aspecto\s+(?:geral|visual|construtiv\w*|est[eé]tic\w*|arquitet\w*)|"
    r"sistema\s+construtiv\w*|m[eé]todo\s+construtiv\w*|t[eé]cnica\s+construtiv\w*|"
    r"tipologi\w*|configura[cç]\w*\s+(?:geral|arquitet\w*|espacial)|"
    r"disposi[cç]\w*\s+d[oe]s?\s+ambientes|"
    r"caracter[íi]sticas\s+(?:gerais|construtiv\w*|arquitet\w*|f[íi]sicas))\b"
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
    r"perceptivel|perceptiveis|fotograf\w*|inspecao\s+visual|exame\s+visual|"
    r"aspecto\s+visual)\b|\ba\s+olho\s+nu\b)"
)
# Substantivo de FENÔMENO/anomalia inerentemente avaliável por observação a olho nu
# (NÃO grandeza). Lista permissiva e DELIBERADAMENTE conservadora: só entra o que é
# inequivocamente visual. Termos cuja avaliação usual é instrumental (umidade
# relativa, corrosão/oxidação — profundidade/potencial/taxa) NÃO entram aqui: sem
# outro sinal caem em INDETERMINADA → MEDICAO estrita (sobre-bloqueio seguro).
_FENOMENO_OBSERVAVEL = re.compile(
    r"(?i)\b(?:fissura\w*|trinca\w*|rachadura\w*|fenda\w*|mancha\w*|"
    r"infiltra\w*|mofo\w*|bolor\w*|efloresc\w*|"
    r"destacamento\w*|descolamento\w*|desplacamento\w*|desprendimento\w*|"
    r"desagrega\w*|pulverul\w*|bolha\w*|empolamento\w*|ferrugem\w*|"
    r"vazamento\w*|goteira\w*|gotejamento\w*|"
    r"patologi\w*|manifestac\w*|anomalia\w*|"
    r"avaria\w*|deterioracao\w*|desgaste\w*|"
    r"vegetacao\w*|entulho\w*|sujidade\w*)\b"
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
_PP_LOCATIVO = re.compile(
    r"(?i)\b(?:em|n[ao]s?|numa?|junto\s+a[s]?|proximo\s+a[s]?|perto\s+d[aeo]s?)\s+.*?(?=$|\s+e\s+)")
# Qualificador admitido DENTRO do NP observacional (modo/aspecto, nunca objeto).
# Só se ancora APÓS um head consumido — não cria prova de objeto por si só.
_QUALIFICADOR_NP = (
    r"visivel|visiveis|aparente|aparentes|visualmente|ocular|oculares|perceptivel|perceptiveis|"
    r"fotograf\w*|superficial|superficiais|pontual|pontuais|localizad\w*|generalizad\w*|alegad\w*")
_CADEIA_NP = r"(?:\s+(?:(?:" + _QUALIFICADOR_NP + r")\b|d[aeo]s?\s+\w+))*"
_NP_FENOMENO = re.compile(_FENOMENO_OBSERVAVEL.pattern + _CADEIA_NP)
_NP_DESCRITIVO = re.compile(_OBJETO_DESCRITIVO.pattern + _CADEIA_NP)
# Scaffolding da demanda: conectores existenciais (nome E verbo conjugado —
# "existe fissura" tem tanto valor scaffold quanto "existência de fissura"; a
# forma verbal não vira prova de objeto sozinha, mas também não é conteúdo
# residual que derruba um fenômeno genuíno já contabilizado) e marcador processual.
_SCAFFOLD = re.compile(r"(?i)\b(?:presenc\w*|ausenc\w*|alegad\w*|"
                        r"existenc\w*|existe|existem|existir|ha|houve|havia)\b")
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


def remover_ruido_estrutural(texto: str) -> str:
    limpo = str(texto or "")
    for padrao in _RUIDO:
        limpo = padrao.sub(" ", limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def _contabilidade_observacional(base, modo_observacional):
    """Contabilidade integral da demanda (V11). Retorna (heads, residual).

    Remove o verbo inicial, os PPs locativos (por inteiro — fenômeno citado como
    LOCAL não é demanda) e o scaffolding; consome NPs observacionais (head de
    fenômeno sempre; head descritivo SÓ com modo observacional) com seus
    de-complementos e qualificadores de modo. `residual` é True se sobra QUALQUER
    token de conteúdo (\\w{3,} fora de classe fechada) — e nesse caso a cláusula
    NÃO é INSPECAO, mesmo com head consumido."""
    t = base.strip()
    partes = t.split(None, 1)
    if partes and _VERBO_TECNICO.fullmatch(re.sub(r"\W+", "", partes[0])):
        t = partes[1] if len(partes) > 1 else ""
    t = _PP_LOCATIVO.sub(" ", t)
    heads = 0
    for padrao in ([_NP_DESCRITIVO, _NP_FENOMENO] if modo_observacional else [_NP_FENOMENO]):
        while True:
            t, n = padrao.subn(" ", t, count=1)
            if not n:
                break
            heads += 1
    t = _SCAFFOLD.sub(" ", _MARCADOR_VISUAL.sub(" ", t))
    residual = [tok for tok in re.findall(r"\w{3,}", t) if tok not in _CLASSE_FECHADA]
    return heads, bool(residual)


def classificar_requisito(texto: str) -> str:
    """MEDICAO | DOCUMENTO | INSPECAO | INDETERMINADA.

    Default fail-closed. Verbo de requisição genérico ("verificar"/"constatar"/…),
    conector existencial ("há"/"existe"/"existência de"), verbo de observação
    direta ("registrar"/"descrever"/"fotografar"/…) e qualificador de MODO
    ("visualmente"/"fotograficamente"/"aparente"/…) são MODALIDADE-NEUTROS —
    nenhum estabelece INSPECAO sem prova POSITIVA NO OBJETO.

    FUNIL DE AUTORIDADE (V11, estrutural, não lexical): INSPECAO exige
    CONTABILIDADE OBSERVACIONAL INTEGRAL da demanda — PP locativo removido por
    inteiro (fenômeno INCIDENTAL não absolve: "o cobrimento das armaduras junto
    às fissuras" é INDETERMINADA), ≥1 NP observacional consumido (fenômeno
    inequivocamente visual sempre; objeto descritivo-qualitativo só com verbo de
    observação direta ou qualificador de modo) E ZERO token de conteúdo residual.
    Objeto desconhecido NUNCA vira INSPECAO, qualquer que seja o verbo, o
    marcador de modo ou o fenômeno coordenado/locativo. E ausência de qualquer
    sinal de medição; senão → INDETERMINADA (o gate trata como MEDICAO estrita).
    O modo de falha do funil é sobre-bloqueio, nunca falso-verde."""
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
    modo_observacional = bool(_VERBO_OBSERVACAO_DIRETA.search(base) or _MARCADOR_VISUAL.search(base))
    heads, residual = _contabilidade_observacional(base, modo_observacional)
    if heads and not residual:
        return "INSPECAO"
    return "INDETERMINADA"


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
    classe (MEDICAO|DOCUMENTO|INSPECAO|INDETERMINADA), proveniencia,
    status ∈ {MATERIAL, EXTRACAO_INDETERMINADA}. Fail-closed: quesito pertinente
    cujo texto não produz cláusula material rende um requisito EXTRACAO_INDETERMINADA.
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
                "proveniencia": proveniencia, "status": "MATERIAL",
            })
    if not requisitos:
        norma = _norma_exibicao(remover_ruido_estrutural(" ".join(fontes)))
        requisitos.append({
            "requirement_id": _identidade(quesito_id, norma or quesito_id),
            "quesito": quesito_id, "requisito": (" ".join(fontes)).strip() or quesito_id,
            "texto_normalizado": norma, "classe": "INDETERMINADA", "proveniencia": proveniencia,
            "status": "EXTRACAO_INDETERMINADA",
        })
    return requisitos
