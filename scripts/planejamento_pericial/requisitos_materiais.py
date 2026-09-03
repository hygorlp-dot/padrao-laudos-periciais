"""Extração determinística de requisitos materiais de um quesito.

O texto do quesito NÃO é autoridade de cobertura: aqui ele é apenas segmentado,
com identidade e proveniência estáveis, em requisitos materiais estruturados e
classificados por natureza. A cobertura é decidida a jusante por vínculo
estruturado a um item planejado de tipo apropriado (ver validar_plano).

Classificação (natureza do requisito) — DEFAULT FAIL-CLOSED. O vocabulário abaixo
é a lista canônica; está reproduzido em docs/padroes/padrao-planejamento-vistoria.md.

- INSPECAO — satisfazível por observação de campo. São MODALIDADE-NEUTROS e NÃO
  estabelecem observabilidade por si sós — nenhum decide sem um sinal POSITIVO DE
  OBJETO: o verbo de REQUISIÇÃO GENÉRICO ("verificar"/"constatar"/"avaliar"/…), o
  conector EXISTENCIAL ("há"/"existe"/"existência de"/"presença de" — "medir se
  HÁ trinca > 0,3 mm" também usa "há") E o verbo de OBSERVAÇÃO DIRETA
  ("registrar"/"descrever"/"caracterizar"/"localizar"/… — "registrar o
  assentamento diferencial" exige nivelamento topográfico). Só é atribuída com
  EVIDÊNCIA POSITIVA no OBJETO: (i) substantivo de fenômeno inequivocamente
  visual ("fissura", "infiltração", "mancha", "descolamento", "mofo",
  "eflorescência", …); (ii) qualificador explicitamente visual ("visível",
  "aparente", "visualmente", "a olho nu", "ocular", "fotograficamente"); (iii)
  verbo de observação direta + objeto descritivo-qualitativo ("padrão
  construtivo", "acabamento", "estado de conservação", "revestimento", …) — E
  ausência de qualquer sinal de medição. Todo caminho de INSPECAO tem portão de
  objeto cujo modo de falha é SOBRE-BLOQUEIO, nunca falso-verde.
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
# Qualificador que evidencia que o fato é constatável VISUALMENTE. O conector
# existencial ("há"/"existe"/"existência de"/"presença de") NÃO entra aqui: é tão
# modalidade-neutro quanto o verbo genérico ("medir se HÁ trinca > 0,3 mm" também
# usa "há"). Só qualificador explicitamente visual estabelece INSPECAO.
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
    r"deforma[cç][aã]|deslocamento|esquadro|dimens|"
    r"[aá]rea(?!s?\s+d[eo]s?\s+(?:servi[cç]o|lazer|circula[cç]\w*|conv[íi]v\w*|estar|"
    r"refei[cç]\w*|descolament\w*|destacament\w*|infiltrac\w*|umidade|corros\w*|"
    r"manch\w*|fissur\w*|patologi\w*|dano))|volume|cota|dist[aâ]ncia|"
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

_MIN_TERMOS = 1


def remover_ruido_estrutural(texto: str) -> str:
    limpo = str(texto or "")
    for padrao in _RUIDO:
        limpo = padrao.sub(" ", limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def classificar_requisito(texto: str) -> str:
    """MEDICAO | DOCUMENTO | INSPECAO | INDETERMINADA.

    Default fail-closed. Verbo de requisição genérico ("verificar"/"constatar"/…),
    conector existencial ("há"/"existe"/"existência de") E verbo de observação direta
    ("registrar"/"descrever"/…) são MODALIDADE-NEUTROS — nenhum estabelece INSPECAO
    sem um sinal POSITIVO DE OBJETO. INSPECAO só quando há (i) substantivo de
    fenômeno inequivocamente visual, (ii) qualificador explicitamente visual, ou
    (iii) verbo de observação direta + objeto descritivo-qualitativo — e ausência de
    qualquer sinal de medição; senão → INDETERMINADA (o gate trata como MEDICAO
    estrita). Todo caminho de INSPECAO tem portão de objeto cujo modo de falha é
    sobre-bloqueio, nunca falso-verde."""
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
    if (_FENOMENO_OBSERVAVEL.search(base) or _MARCADOR_VISUAL.search(base)
            or (_VERBO_OBSERVACAO_DIRETA.search(base) and _OBJETO_DESCRITIVO.search(base))):
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
