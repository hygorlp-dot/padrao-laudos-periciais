"""Confirmed property facts; proposals never become facts merely by extraction."""

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
import unicodedata

PROPERTY_RECORD_KIND = "PROPERTY_RECORD_V1"
PROPERTY_RECORD_ID = "PROPERTY-RECORD"

# Coordinates and process parties deliberately have no writable field here.
PROPERTY_FIELDS = (
    ("owner", "Proprietário do imóvel", "text", ("proprietário", "proprietário do imóvel")),
    ("street", "Logradouro", "text", ("logradouro do imóvel", "logradouro")),
    ("number", "Número", "text", ("número do imóvel",)),
    ("complement", "Complemento", "text", ("complemento do imóvel",)),
    ("unit", "Unidade / apartamento", "text", ("unidade do imóvel", "apartamento")),
    ("block", "Bloco", "text", ("bloco",)),
    ("quadra", "Quadra", "text", ("quadra",)),
    ("neighborhood", "Bairro", "text", ("bairro do imóvel", "bairro")),
    ("postal_code", "CEP", "text", ("cep do imóvel", "cep")),
    ("city", "Município do imóvel", "text", ("município do imóvel", "cidade do imóvel")),
    ("state", "UF do imóvel", "text", ("uf do imóvel",)),
    ("development", "Empreendimento", "text", ("empreendimento", "nome do empreendimento")),
    ("floor", "Pavimento", "text", ("pavimento",)),
    ("private_area_m2", "Área privativa (m²)", "decimal", ("área privativa",)),
    ("constructed_area_m2", "Área construída (m²)", "decimal", ("área construída",)),
    ("construction_system", "Sistema construtivo", "text", ("sistema construtivo",)),
    ("construction_company", "Construtora", "text", ("construtora",)),
    ("habite_se_date", "Data do habite-se", "date", ("data do habite-se",)),
    ("use_start_date", "Início de utilização", "date", ("data de início de utilização",)),
    ("contract_number", "Contrato do imóvel", "text", ("número do contrato",)),
    ("contractual_value", "Valor contratual (R$)", "decimal", ("valor contratual",)),
    ("program", "Programa / financiamento", "text", ("programa habitacional", "programa de financiamento")),
)
_DEFINITIONS = {field: (label, kind, aliases) for field, label, kind, aliases in PROPERTY_FIELDS}


def _text(value, limit=1000):
    return type(value) is str and bool(value.strip()) and value == value.strip() and len(value) <= limit


def property_date(value: str):
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    raise ValueError("property date is invalid")


def _value(field, value):
    if type(field) is not str or field not in _DEFINITIONS or not _text(value):
        raise ValueError("property field or value is invalid")
    kind = _DEFINITIONS[field][1]
    if kind == "decimal":
        grouped = re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d+", value)
        numeric = value.replace(".", "").replace(",", ".") if grouped else value.replace(",", ".")
        try:
            number = Decimal(numeric)
        except InvalidOperation as exc:
            raise ValueError("property number is invalid") from exc
        if not number.is_finite() or number < 0 or not (grouped or re.fullmatch(r"\d+(?:[.,]\d+)?", value)):
            raise ValueError("property number is invalid")
    if kind == "date":
        property_date(value)


PROPERTY_EVIDENCE_METHODS = (
    "LABEL_NATIVE_TEXT_V1", "LABEL_OCR_V1",
    "DOCUMENT_PATTERN_NATIVE_TEXT_V2", "DOCUMENT_PATTERN_OCR_V2",
    "CONTEXT_BOUND_NATIVE_TEXT_V2", "CONTEXT_BOUND_OCR_V2",
)


@dataclass(frozen=True, slots=True)
class PropertyEvidence:
    document_id: str
    document_sha256: str
    filename: str
    page: int
    excerpt: str
    method: str
    confidence: float | None
    source_value: str

    def __post_init__(self):
        if any(not _text(getattr(self, name), 2000) for name in ("document_id", "filename", "excerpt", "source_value")):
            raise ValueError("property source text is invalid")
        if type(self.document_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.document_sha256):
            raise ValueError("property source checksum is invalid")
        if type(self.page) is not int or self.page < 1 or self.source_value not in self.excerpt:
            raise ValueError("property source evidence is invalid")
        if self.method not in PROPERTY_EVIDENCE_METHODS:
            raise ValueError("property extraction method is invalid")
        if self.confidence is not None and (type(self.confidence) not in (float, int) or not 0 <= self.confidence <= 1):
            raise ValueError("property confidence is invalid")


@dataclass(frozen=True, slots=True)
class PropertyValue:
    field: str
    value: str
    evidence: PropertyEvidence | None
    confirmed_by: str
    confirmed_at: str

    def __post_init__(self):
        _value(self.field, self.value)
        if not _text(self.confirmed_by) or type(self.confirmed_at) is not str:
            raise ValueError("property confirmation is invalid")
        parsed = datetime.fromisoformat(self.confirmed_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("property confirmation requires timezone")
        if self.evidence is not None and (type(self.evidence) is not PropertyEvidence or self.evidence.source_value != self.value):
            raise ValueError("property value diverges from source")


@dataclass(frozen=True, slots=True)
class PropertyRecord:
    schema_version: str
    workspace_id: str
    values: tuple[PropertyValue, ...]

    def __post_init__(self):
        if self.schema_version != "1.0.0" or not _text(self.workspace_id):
            raise ValueError("property identity is invalid")
        if type(self.values) is not tuple or any(type(value) is not PropertyValue for value in self.values):
            raise ValueError("property values are invalid")
        if len({value.field for value in self.values}) != len(self.values):
            raise ValueError("property fields must be unique")

    def get(self, field):
        return next((item for item in self.values if item.field == field), None)

    @property
    def address(self):
        return ", ".join(item.value for field in ("street", "number", "complement", "unit", "block", "quadra", "neighborhood", "city", "state", "postal_code") if (item := self.get(field)) is not None)


def property_record_to_mapping(record):
    if type(record) is not PropertyRecord:
        raise TypeError("expected PropertyRecord")
    mapping = asdict(record)
    mapping["values"] = list(mapping["values"])
    return mapping


def property_record_from_mapping(value):
    if type(value) is not dict or set(value) != {f.name for f in fields(PropertyRecord)} or type(value["values"]) is not list:
        raise ValueError("property mapping is invalid")
    values = []
    for entry in value["values"]:
        if type(entry) is not dict or set(entry) != {f.name for f in fields(PropertyValue)}:
            raise ValueError("property value mapping is invalid")
        evidence = entry["evidence"]
        if evidence is not None:
            if type(evidence) is not dict or set(evidence) != {f.name for f in fields(PropertyEvidence)}:
                raise ValueError("property evidence mapping is invalid")
            evidence = PropertyEvidence(**evidence)
        values.append(PropertyValue(**{**entry, "evidence": evidence}))
    return PropertyRecord(value["schema_version"], value["workspace_id"], tuple(values))


@dataclass(frozen=True, slots=True)
class PropertyProposal:
    proposal_id: str
    workspace_id: str
    field: str
    value: str
    evidence: PropertyEvidence
    # STRONG: o contexto liga o dado ao imovel objeto. POSSIBLE: a peca e
    # pertinente, mas o trecho nao diz de qual imovel fala -- confira a fonte.
    strength: str = "STRONG"
    # Hierarquia documental da peca de origem (#288), so para ordenar e
    # destacar: A matricula/registro, B contrato, C termo de entrega, D laudo
    # ou parecer, E peticao inicial ligada ao imovel objeto, F contestacao,
    # G outras pecas, H contexto apenas possivel. Nunca torna nada efetivo.
    source_rank: str = "G"
    # Peca logica do export PJe (ou None): "M pecas" conta pecas, nao paginas.
    piece_id: str | None = None


def _normalized(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(c)).strip()


# Endereco de parte, de advogado, de juizo ou de precedente nunca vira endereco
# do imovel. Avaliado na frase inteira (as abreviacoes nao a cortam) e com
# limite de palavra; fail-closed: na duvida, o perito preenche manualmente.
_PARTY_ADDRESS_BLOCKERS = re.compile(
    r"\b(?:residente|domiciliad\w*|com endereco|endereco eletronico|com sede|sede (?:na|no|em)|escritorio|oab|"
    r"advogad\w*|patrono|procurador\w*|cpf|cnpj|forum|vara|juizo|tribunal|secao judiciaria|subsecao judiciaria|"
    r"justica federal|justica estadual|poder judiciario|ministerio publico|defensoria|"
    r"apelacao|recurso especial|resp|agravo|julgado|rel|relator\w*|des|desembargador\w*|min|ministro|"
    r"jurisprudencia|precedente|acordao|ementa|"
    r"tel|telefone|fone|fax|celular|whatsapp|e-mail|email|www)\b|@"
)
# Na linha de rotulo (nivel 1) so a qualificacao e o timbre institucional pesam;
# CPF/CNPJ na linha do proprietario ou da construtora nao sao endereco de parte.
_LABEL_QUALIFICATION_BLOCKERS = re.compile(
    r"\b(?:residente|domiciliad\w*|morador\w*|com endereco|com sede|sede (?:na|no|em)|sediad\w*|estabelecid\w*|"
    r"escritorio|oab|advogad\w*|patrono|procurador\w*|"
    r"forum|vara|juizo|tribunal|secao judiciaria|justica federal|justica estadual|poder judiciario)\b"
)
_ADDRESS_FIELDS = frozenset({"street", "number", "complement", "unit", "block", "quadra", "neighborhood", "postal_code", "city", "state"})
_SUBJECT_PROPERTY_CUES = (
    "imovel objeto", "objeto da acao", "objeto da lide", "objeto do contrato", "objeto deste contrato",
    "unidade habitacional", "unidade autonoma", "imovel financiado", "imovel adquirido", "imovel situado",
    "imovel localizado", "imovel vistoriado", "apartamento vistoriado", "imovel em questao", "imovel descrito",
    "imovel da parte autora", "imovel do autor", "imovel da autora", "conjunto habitacional",
)
_PERTINENT_DOCUMENTS = (
    "contrato de compra e venda", "contrato por instrumento particular", "contrato de financiamento",
    "contrato de mutuo", "matricula", "registro de imoveis", "termo de entrega", "termo de recebimento",
    "laudo", "parecer tecnico", "vistoria",
)
# Tipo de peca para o ranking (#288), lido SO no titulo: as duas primeiras
# linhas nao vazias da primeira pagina da peca. Citar um contrato ou uma
# matricula no corpo de uma peticao nunca empresta a ela o peso daquela peca.
_RANK_MARKERS = (
    (re.compile(r"\bmatricula\b|\bregistro de imoveis\b|\bcertidao de inteiro teor\b"), "A"),
    (re.compile(r"\bcontrato (?:de compra e venda|por instrumento particular|de financiamento|de mutuo)\b|\binstrumento particular de compra e venda\b"), "B"),
    (re.compile(r"\btermo de (?:entrega|recebimento)\b"), "C"),
    (re.compile(r"^\s*(?:laudo|parecer tecnico)\b"), "D"),
    (re.compile(r"\bpeticao inicial\b"), "E"),
    (re.compile(r"\bcontestacao\b"), "F"),
)
_TITLE_LINES = 2


def _rank_kind(folded_page):
    title = [line for line in folded_page[:600].split("\n") if line.strip()][:_TITLE_LINES]
    found = []
    for line_number, line in enumerate(title):
        for pattern, rank in _RANK_MARKERS:
            match = pattern.search(line)
            if match:
                found.append((line_number, match.start(), rank))
    return min(found)[2] if found else ""


def _source_rank(kind, method, strength):
    if strength != "STRONG":
        return "H"
    if kind == "E":
        # A inicial so pesa quando o trecho fala do imovel objeto (ou rotula o dado).
        return "E" if method.startswith(("CONTEXT_BOUND_", "LABEL_")) else "G"
    return kind or "G"


# #293: dentro da frase, o vinculo de um endereco e decidido pela oracao. O
# logradouro (e o numero, bairro, CEP... que o seguem na mesma cadeia) pertence
# ao marcador mais proximo antes dele. Dois regimes, para nunca propor mais
# endereco de parte do que antes:
# - frase que a regra anterior ja aceitava: so sai o endereco que um verbo de
#   residencia/sede/deslocamento ("mora na", "estabelecida", "filial") ou um
#   participio de parte ("a vendedora, localizada na") introduz;
# - frase que a regra anterior bloqueava inteira (CPF, telefone, advogado,
#   juizo...): so entra o endereco ligado diretamente ao imovel objeto
#   ("imovel objeto da acao, situado na"), sem bloqueador depois dele.
# Precedente continua bloqueando a frase inteira: o imovel ali e de outro caso.
_PRECEDENT_BLOCKERS = re.compile(
    r"\b(?:apelacao|recurso especial|resp|agravo|julgado|rel|relator\w*|des|desembargador\w*|min|ministro|"
    r"jurisprudencia|precedente|acordao|ementa)\b"
)
_STREET_WORD = r"(?:rua|avenida|av\.|travessa|estrada|rodovia|alameda|praca|largo)\b"
_PARTY_INTRODUCERS = re.compile(
    r"\b(?:(?P<verb>reside|residem|residia\w*|residiu|vive|vivem|vivia\w*|viveu|habita|habitam|habitav\w*|habitou|"
    r"(?:mora|moram|morava|moravam|morou)\s+(?:na|no|nas|nos|em|a|ao))|"
    r"residente\w*|residir|domiciliad\w*|com domicilio|domicilio (?:na|no|em)|morador\w*|morar\s+(?:na|no|em)|"
    r"(?:cuja|sua|seu)\s+(?:residencia|domicilio|endereco)|residencia\s+(?:fica|e)|"
    r"com endereco|endereco (?:residencial|comercial|profissional)|com sede|sede (?:na|no|em)|sediad\w*|"
    r"estabelecid\w*|escritorio|filial|cuja\s+sede|com\s+matriz|matriz\s+(?:na|no|em)|"
    r"(?<!como )(?<!tem )(?<!possui )endereco\s+atual(?=\s*:?\s*" + _STREET_WORD + r")|"
    r"trabalh(?:a|am|ava|avam)\s+(?:na|no|em)(?=\s+" + _STREET_WORD + r")|"
    r"mud(?:ou|aram|ar|ando)-se\s+(?:para|a|ao)|mud(?:ou|aram|ar|ando)\s+para|transferiu-se|"
    r"passou\s+a\s+residir|"
    r"(?:transferid|removid|deslocad)[oa]s?\s+para|realocad[oa]s?)\b"
)
# Uma expressao por pista: "imovel objeto da acao" casa "imovel objeto" e "objeto da acao".
_SUBJECT_CUES = tuple(re.compile(r"\b" + re.escape(cue) + r"\b") for cue in _SUBJECT_PROPERTY_CUES)
# "outra unidade habitacional", "o predio ao lado": outra unidade, nunca a do objeto.
_OTHER_UNIT_BEFORE = re.compile(
    r"\b(?:outr[oa]s?|nov[oa]s?|antig[oa]s?|divers[oa]s?|segund[oa]s?|demais|"
    r"(?P<neighbor>(?:ao lado|em frente|defronte|proximo|perto|vizinh[oa]s?)(?:\s+(?:d[oa]s?|a|ao))?))\s+$"
)
_NEIGHBOR_WORDS = re.compile(
    r"\b(?:vizinh[oa]s?|ao lado|em frente|defronte|diante|proxim[oa]s?|pert[oa]|junto|atras)\b"
)
# Vizinhanca so torna "outra unidade" quando nao tem alvo ("o imovel vizinho") ou
# quando o alvo e uma unidade ("vizinha ao imovel"); vizinho de um marco ("ao
# shopping", "ao Condominio X", "ao centro") nao muda o vinculo.
_NEIGHBOR_AFTER = re.compile(r"\s+(?:vizinh[oa]s?|ao lado|em frente|defronte)\b")
_NEIGHBOR_TARGET = re.compile(r"\s*(?:d[aoe]s?|a|ao|aos|as)\s+")
_UNIT_TARGET = re.compile(
    r"(?:(?:o|a|um|uma|outr[oa]|nov[oa])\s+)?(?:imove(?:l|is)|unidades?|casas?|apartamentos?|sobrados?|lotes?|objeto)\b"
)
# "no bairro vizinho", "outra cidade": o endereco que segue e de outro lugar.
_OTHER_PLACE = re.compile(
    r"\b(?:(?:bairro|cidade|municipio|quadra)\s+vizinh[oa]s?|"
    r"outr[oa]\s+(?:bairro|cidade|municipio|endereco|rua|estado))\b"
)


def _neighbor_of_unit(text, position):
    """A vizinhanca logo em `position` aponta outra unidade (sem alvo, ou alvo unidade)?"""
    after = _NEIGHBOR_AFTER.match(text, position)
    if after is None:
        return False
    target = _NEIGHBOR_TARGET.match(text, after.end())
    return target is None or _UNIT_TARGET.match(text, target.end()) is not None
_PARTICIPLE = re.compile(r"\b(?:situad|localizad)(?P<gender>[oa])s?\b")
_PROPERTY_NOUN = re.compile(
    r"\b(?:imove(?:l|is)|(?P<feminine>unidades?|casas?)|apartamentos?|terrenos?|lotes?|empreendimentos?|"
    r"edificios?|predios?|condominios?|conjuntos?|residencia(?:l|is)|sobrados?|bem|(?P<residence>residencias?))\b"
)
# Parte entre o imovel e o participio ("entregue pela construtora, localizada"):
# se concorda com o participio, e ela que esta localizada (fail-closed).
_PARTY_NOUN = re.compile(
    r"\b(?:(?P<feminine>parte\s+(?:autora|re|requerente|requerida|adversa|contraria)|re|autora|construtora|vendedora|"
    r"compradora|incorporadora|empresa|requerida|empreiteira|imobiliaria|cooperativa|testemunha)|(?P<both>requerente)|"
    r"reu|autor|vendedor|comprador|requerido|banco|agente financeiro)\b"
)
# "imovel da parte autora" e posse, nao a parte qualificada.
_POSSESSIVE_BEFORE = re.compile(r"\bd[aoe]s?\s+(?:parte\s+)?$")
# "adquirida pela autora", "entregue a autora em 2015": agente de um participio
# atributivo do proprio imovel (sem copula), nao a parte que esta localizada.
_ATTRIBUTIVE_AGENT = re.compile(
    r"\b(?:[a-z]+(?:ad|id)[oa]s?|entregues?)\s+(?:pel[oa]s?|por|a|ao|aos|as)\s+(?:[a-z]+\s+){0,2}$"
)
# Sem o "e": no texto sem acento, "é" e a conjuncao "e" se confundem. A copula
# de uma relativa do proprio imovel ("imovel, que foi adquirido pela autora")
# nao conta.
_COPULA = re.compile(r"\b(?:foi|foram|era|eram|sera|serao|esta|estava|seria)\b")
_COPULA_AGENT = re.compile(
    r"\b(?:foi|foram|era|eram|sera|serao|seria)\s+(?:[a-z]+(?:ad|id)[oa]s?|entregues?)\s+(?:pel[oa]s?|por|a|ao|aos|as)\b"
)
# Onde a regra anterior ja aceitava a frase, qualquer relativa aberta depois do
# imovel ("que foi", "(que em 10/05/2015 foi", "o qual no ano de 2015 foi")
# e do proprio imovel: afrouxar ali nunca propoe mais do que antes.
_RELATIVE = re.compile(r"\b(?:que|o qual|a qual|os quais|as quais)\b")


def _bare(pattern, text, start, stop):
    """Ha `pattern` em [start, stop) sem relativa aberta entre start e ele?"""
    return any(not _RELATIVE.search(text, start, item.start()) for item in pattern.finditer(text, start, stop))
_PARTICIPLE_REACH = 160
# SUBJECT_LOOSE: participio ligado a um substantivo de imovel sem pista "objeto";
# basta onde a regra anterior ja aceitava a frase, nunca onde ela bloqueava.
_SUBJECT_KINDS = frozenset({"SUBJECT", "SUBJECT_LOOSE"})
_OBJECT = re.compile(r"\bobjeto\b")
# "mora no imovel", "reside na unidade": o verbo fala de morar num imovel, nao apresenta endereco.
_DWELLING_AHEAD = re.compile(
    r"\s*(?:(?:na|no|nas|nos|em)\s+)?(?:(?:o|a|os|as|um|uma|este|esta|neste|nesta|referid[oa])\s+)?"
    r"(?:imove(?:l|is)|unidades?|casas?|apartamentos?|sobrados?)\b"
)
# "imovel objeto, onde reside, ..." fala do proprio imovel: a relativa tem de
# vir colada a pista do imovel, no presente e sem negacao, com no maximo um
# parentetico participial controlado ("financiada em 2015"); deslocamento,
# cidade ou outra unidade entre eles mantem o marcador de residencia.
_RELATIVE_BEFORE = re.compile(r",\s*(?:onde|que|no qual|na qual|em que)\s+(?:[a-z]+\s+){0,3}$")
_NEGATION = re.compile(r"\b(?:nao|mais|nunca|ja|antes|anteriormente)\b")
_DISPLACEMENT_AFTER = re.compile(r"[\s,]*(?:para|ate)\b")
_CONTROLLED_PARENTHETICAL = re.compile(
    r",\s*(?:(?:adquirid|financiad|construid|comprad|recebid|quitad)[oa]s?|entregues?)"
    r"(?:\s+(?:em|no ano de)\s+[\d/]+|\s+pel[oa]s?\s+(?:autor\w*|re|reu|parte autora|construtora|vendedor\w*))?\s*$"
)
# Ligacao direta da pista do imovel ao endereco, exigida onde a regra anterior bloqueava.
_DIRECT_LINK = re.compile(
    r"[\s,]*(?:(?:que\s+)?(?:fica|esta|situa-se|localiza-se|encontra-se|se\s+situa|se\s+localiza)\s+)?"
    r"(?:(?:situad|localizad)[oa]s?\s+)?(?:na|no|em|a|ao)?[\s,]*"
)
# "mora-\ndora", "resi- dente": hifenizacao do PDF nao esconde o marcador.
_HYPHEN_BREAK = re.compile(r"(?<=[a-z])-(?:[ \t]*\r?\n[ \t]*|[ \t]+)(?=[a-z])")


def _joined(folded):
    """Texto sem hifenizacao de quebra de linha e, para cada posicao, a posicao nele."""
    pieces, forward, cursor, length = [], [], 0, 0
    for item in _HYPHEN_BREAK.finditer(folded):
        piece = folded[cursor:item.start()]
        forward.extend(range(length, length + len(piece)))
        length += len(piece)
        pieces.append(piece)
        forward.extend([length] * (item.end() - item.start()))
        cursor = item.end()
    piece = folded[cursor:]
    forward.extend(range(length, length + len(piece) + 1))
    pieces.append(piece)
    return "".join(pieces), forward


def _participle_kind(text, begin, item, introducers, introducer_ends, subjects, others):
    floor = max(begin, item.start() - _PARTICIPLE_REACH)
    feminine = item.group("gender") == "a"

    def interrupted(start, strict=False):
        position = bisect_right(introducers, start - 1)
        if position < len(introducers) and introducers[position] < item.start():
            return True
        # CPF, CNPJ, OAB, telefone... entre o imovel e o participio: a parte esta no meio.
        if _PARTY_ADDRESS_BLOCKERS.search(text, start, item.start()):
            return True
        # "foi vendida a FULANA, situada na": o agente nomeado pode ser o localizado.
        # A relativa do proprio imovel ("que foi adquirido pela autora") so e
        # isenta onde a regra anterior ja aceitava a frase.
        if (_COPULA_AGENT.search(text, start, item.start()) if strict else _bare(_COPULA_AGENT, text, start, item.start())):
            return True
        for noun in _PARTY_NOUN.finditer(text, start, item.start()):
            agrees = noun.group("both") or (noun.group("feminine") is not None) == feminine
            if strict:
                # Onde a regra anterior bloqueava: qualquer parte que concorde tira a ancora.
                if agrees:
                    return True
                continue
            if _POSSESSIVE_BEFORE.search(text, max(start, noun.start() - 12), noun.start()):
                continue
            if _ATTRIBUTIVE_AGENT.search(text[start:noun.start()]) and not _bare(_COPULA, text, start, noun.start()):
                continue
            if agrees:
                return True
        return False

    nouns = list(_PROPERTY_NOUN.finditer(text, floor, item.start()))
    agreeing = [noun for noun in nouns if (noun.group("feminine") is not None or noun.group("residence") is not None) == feminine]
    if agreeing:
        noun = agreeing[-1]
        position = bisect_right(introducers, noun.start()) - 1
        if position >= 0 and introducer_ends[position] >= noun.end():
            return "PARTY"
        # "novo imovel objeto da acao": a pista "objeto" entre eles diz que e o objeto.
        objeto = _OBJECT.search(text, noun.end(), item.start()) is not None
        # "unidade habitacional vizinha ao imovel, situada": a propria pista e outra unidade.
        position = bisect_left(others, noun.start())
        if not objeto and position < len(others) and others[position] < noun.end():
            return "OTHER"
        # "imovel ao lado do objeto da acao": a unidade vizinha no meio.
        position = bisect_right(others, noun.end() - 1)
        if position < len(others) and others[position] < item.start():
            return "OTHER"
        if not objeto and (
            _OTHER_UNIT_BEFORE.search(text[max(floor, noun.start() - 24):noun.start()])
            or _neighbor_of_unit(text, noun.end())
        ):
            return "OTHER"
        if interrupted(noun.end()):
            return "PARTY"
        # Ancorado: uma pista do imovel objeto entre o substantivo e o participio.
        low = bisect_left(subjects, (noun.start(), -1))
        anchored = any(end <= item.start() for _start, end in subjects[low:bisect_left(subjects, (item.start(), -1))])
        # Onde a regra anterior bloqueava, "objeto da acao ao lado da praca, situada"
        # e ambiguo (o participio pode ser do marco): sem ancora estrita.
        nearby = _NEIGHBOR_WORDS.search(text, noun.end(), item.start()) is not None
        return "SUBJECT" if anchored and not nearby and not interrupted(noun.end(), strict=True) else "SUBJECT_LOOSE"
    if nouns:
        return "PARTY"
    if not text[begin:item.start()].strip(" \t\n,.;:-"):
        # "Situado na Rua X, o imovel objeto..." abre a frase: nada a qualificar.
        return None
    low, high = bisect_left(subjects, (floor, -1)), bisect_left(subjects, (item.start(), -1))
    cues = [(start, end) for start, end in subjects[low:high] if end <= item.start()]
    if cues and not interrupted(cues[-1][1]):
        # "O bem objeto da acao, situado na": a pista do imovel e o sujeito.
        return "SUBJECT_LOOSE" if interrupted(cues[-1][1], strict=True) else "SUBJECT"
    return "PARTY"


def _clause_markers(text):
    """(inicio, fim, tipo) de cada marcador da pagina: PARTY, SUBJECT(_LOOSE) ou OTHER.

    Calculado uma vez por pagina; cada marcador so olha para tras ate o inicio
    da propria frase, com alcance fixo (custo linear no texto).
    """
    markers = []
    subjects = []
    sentence = {}

    def begin_of(position):
        if position not in sentence:
            sentence[position] = _window(text, position, position)[0]
        return sentence[position]

    cues = sorted((item.start(), item.end(), item.group()) for cue in _SUBJECT_CUES for item in cue.finditer(text))
    groups = []
    for start, end, value in cues:
        # "imovel objeto da acao" casa duas pistas sobrepostas: um so sintagma.
        if groups and start <= groups[-1][1] + 1:
            groups[-1][1] = max(groups[-1][1], end)
            groups[-1][2].append((start, end, value))
        else:
            groups.append([start, end, [(start, end, value)]])
    for group_start, group_end, members in groups:
        floor = max(begin_of(group_start), group_start - 24)
        before = _OTHER_UNIT_BEFORE.search(text[floor:group_start])
        neighbor = before is not None and before.group("neighbor") is not None
        if neighbor and not _UNIT_TARGET.match(text, group_start):
            # "proximo ao Conjunto X, na Rua...": o conjunto e marco de localizacao,
            # nem outra unidade nem pista do imovel.
            continue
        objeto = any("objeto" in value for _start, _end, value in members)
        # Vizinhanca depois da pista: "unidade habitacional vizinha ao imovel" e outra
        # unidade; quem esta "ao lado do predio" no "imovel objeto" e o proprio objeto.
        neighbor = neighbor or (not objeto and _neighbor_of_unit(text, group_end))
        # "novo imovel objeto da acao" e o objeto; "ao lado do (imovel) objeto" nao.
        kind = "OTHER" if neighbor or (before is not None and not objeto) else "SUBJECT"
        for start, end, _value in members:
            markers.append((start, end, kind))
            if kind == "SUBJECT":
                subjects.append((start, end))
    for item in _OTHER_PLACE.finditer(text):
        target = _NEIGHBOR_TARGET.match(text, item.end()) if "vizinh" in item.group() else None
        if target is not None and _UNIT_TARGET.match(text, target.end()) is None:
            # "no bairro vizinho ao centro": o marco localiza, nao desloca.
            continue
        markers.append((item.start(), item.end(), "OTHER"))
    subjects.sort()
    subject_ends = {end for _start, end in subjects}
    introducers = []
    for item in _PARTY_INTRODUCERS.finditer(text):
        if item.group("verb") and (
            _relative_of_subject(text, begin_of(item.start()), item.start(), subject_ends, item.end())
            or _DWELLING_AHEAD.match(text, item.end())
        ):
            # "imovel objeto, onde reside, ..." ou "mora no imovel": nao e endereco de parte.
            continue
        markers.append((item.start(), item.end(), "PARTY"))
        introducers.append((item.start(), item.end()))
    introducers.sort()
    starts = [start for start, _end in introducers]
    ends = [end for _start, end in introducers]
    others = sorted(start for start, _end, kind in markers if kind == "OTHER")
    for item in _PARTICIPLE.finditer(text):
        kind = _participle_kind(text, begin_of(item.start()), item, starts, ends, subjects, others)
        if kind is not None:
            markers.append((item.start(), item.end(), kind))
    markers.sort()
    return markers


def _relative_of_subject(text, begin, start, subject_ends, end):
    relative = _RELATIVE_BEFORE.search(text, max(begin, start - _PARTICIPLE_REACH), start)
    if relative is None or _NEGATION.search(text, relative.start(), start) or _DISPLACEMENT_AFTER.match(text, end):
        return False
    floor = max(begin, relative.start() - _PARTICIPLE_REACH)
    before = text[floor:relative.start()]
    parenthetical = _CONTROLLED_PARENTHETICAL.search(before)
    if parenthetical is not None:
        before = before[:parenthetical.start()]
    return floor + len(before.rstrip()) in subject_ends


_INTRINSIC_FIELDS = {"development", "private_area_m2", "constructed_area_m2", "program", "habite_se_date", "contract_number", "contractual_value"}
_SENTENCE_BREAK = re.compile(r"(?:\.\s|;\s|\n\s*\n)")
# "Av. ", "Dr. ", "Rel. ", "nº. " nao terminam a frase.
_ABBREVIATIONS = frozenset({
    "av", "dr", "dra", "sr", "sra", "srs", "rel", "des", "min", "fls", "fl", "art", "arts", "n", "no", "nos",
    "exmo", "exma", "ilmo", "ilma", "prof", "profa", "eng", "adv", "proc", "inc", "cf", "p", "pag", "pg", "r",
    "trav", "rod", "est", "pca", "al", "lt", "qd", "bl", "ap", "apto", "cep", "vol", "ed", "edif",
})
_CONTEXT_REACH = 400
_CONTEXT_AHEAD = 240
_NUMBER_MARK = r"(?:n[o\u00ba\u00b0]\.?|n\.|numero)"


def _folded(value):
    """Minusculas sem acento, com o indice de cada caractere na fonte original."""
    if value.isascii():
        return value.lower(), list(range(len(value)))
    folded, indices = [], []
    for index, character in enumerate(value):
        if character.isascii():
            folded.append(character.lower())
            indices.append(index)
            continue
        for item in unicodedata.normalize("NFKD", character):
            if unicodedata.combining(item):
                continue
            for lowered in item.casefold():
                folded.append(lowered)
                indices.append(index)
    return "".join(folded), indices


def _original(text, indices, start, end):
    if start >= end:
        return ""
    return text[indices[start]:indices[end - 1] + 1].strip(" ,.;:-")


_UF_CODES = ("ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms", "mg", "pa", "pb", "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc", "sp", "se", "to")
# "..., Rua X, nº 10, CEP ..., Caruaru - PE" (#288): municipio e UF saem do
# MESMO achado, logo depois de um trecho de endereco da mesma frase; nunca de
# foro, assinatura com data, orgao ("CREA/PE") ou agencia.
_CITY_UF = re.compile(
    r"(?:,|;)[ \t]+(?:em[ \t]+)?([a-z][a-z' ]{1,40}?[a-z])[ \t]*(?:-|/)[ \t]*(" + "|".join(_UF_CODES) + r")\b(?![-/])"
)
_ADDRESS_ANCHOR = re.compile(
    r"\b(?:rua|avenida|av\.|travessa|estrada|rodovia|alameda|praca|largo|cep|bairro|quadra|lote)\b|" + _NUMBER_MARK + r"\s*\d"
)
_CITY_BLOCKERS = re.compile(
    r"\b(?:comarca|foro|eleit\w*|dirimir|crea|cau|ssp|sds|detran|agencia|cartorio|oficio|registro de imoveis|oab|"
    r"assinad\w*|datad\w*|morador\w*|estabelecid\w*|natural de)\b"
)
_DATE_AFTER = re.compile(r"[ \t]*,?[ \t]*\d{1,2}(?:/|[ \t]+de[ \t]+)")
_CITY_CONNECTIVES = frozenset({"de", "da", "do", "dos", "das", "e"})
_ANCHOR_REACH = 160


_CITY_PREFIX = re.compile(r"^(?:Munic[ií]pio|Cidade|Distrito|MUNIC[IÍ]PIO|CIDADE|DISTRITO)\s+d[eoa]\s+")


def _city_name(value):
    words = value.split()
    named = [word for word in words if word not in _CITY_CONNECTIVES]
    return bool(named) and all(
        word[:1].isupper() and not (word.isupper() and len(word) <= 4) for word in named
    )
_STREET = re.compile(r"\b(?:rua|avenida|av\.|travessa|estrada|rodovia|alameda|praca|largo)\s+[^,;\n]{2,80}?(?=\s*(?:,|;|\n|$|\s" + _NUMBER_MARK + r"|\s-\s))")
_PATTERNS = (
    ("street", _STREET, 0),
    ("number", re.compile(r"(?<=,)\s*" + _NUMBER_MARK + r"\s*(\d{1,6}[a-z]?)\b"), 1),
    ("neighborhood", re.compile(r"\bbairro\s+(?:d[oae]s?\s+)?([^,;\n]{2,60}?)(?=\s*(?:,|;|\n|\.\s|\.$))"), 1),
    ("postal_code", re.compile(r"\bcep\s*:?\s*(\d{5}-?\d{3})\b"), 1),
    ("unit", re.compile(r"\b(?:apartamento|apto\.?|unidade habitacional|unidade|casa)\s*" + _NUMBER_MARK + r"?\s*(\d{1,5}[a-z]?)\b"), 1),
    ("block", re.compile(r"\bbloco\s*" + _NUMBER_MARK + r"?\s*([a-z0-9]{1,4})\b"), 1),
    ("quadra", re.compile(r"\bquadra\s*" + _NUMBER_MARK + r"?\s*([a-z0-9]{1,4})\b"), 1),
    ("development", re.compile(r"\b(?:empreendimento denominado\s+)?((?:condominio residencial|residencial|conjunto habitacional)\s+[^,;\n.]{2,60}?)(?=\s*(?:,|;|\n|\.))"), 1),
    ("private_area_m2", re.compile(r"\barea\s+privativa\s+(?:total\s+|real\s+)?(?:de\s+)?(\d{1,4}(?:[.,]\d{1,4})?)\s*m(?:2|\b)"), 1),
    ("constructed_area_m2", re.compile(r"\barea\s+construida\s+(?:total\s+)?(?:de\s+)?(\d{1,4}(?:[.,]\d{1,4})?)\s*m(?:2|\b)"), 1),
    ("contract_number", re.compile(r"\bcontrato\s+(?:de\s+[a-z ,]{0,60}?\s+)?" + _NUMBER_MARK + r"\s*(\d[\d.\-/]{4,30}\d)"), 1),
    ("contractual_value", re.compile(r"\bvalor\s+(?:de\s+|da\s+|do\s+)?(?:compra\s+e\s+venda|aquisicao|operacao|imovel)\s*(?:de|e de|:)?\s*r\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})"), 1),
    ("program", re.compile(r"\b(programa minha casa,? minha vida|programa casa verde e amarela|fundo de arrendamento residencial)\b"), 1),
    ("habite_se_date", re.compile(r"\bhabite-?se\b[^\n]{0,80}?\b(\d{2}/\d{2}/\d{4})\b"), 1),
)


_PATTERN_BY_FIELD = {field: pattern for field, pattern, _group in _PATTERNS}


def _proper_name_follows(value):
    words = value.split()
    return len(words) >= 2 and words[1][:1].isupper()


def _is_sentence_break(folded, match):
    if not match.group().startswith("."):
        return True
    word_end = match.start()
    word_start = word_end
    while word_start > 0 and folded[word_start - 1].isalpha():
        word_start -= 1
    word = folded[word_start:word_end]
    return not (word in _ABBREVIATIONS or len(word) == 1)


def _window(folded, start, end):
    """A frase do achado, limitada a uma vizinhanca fixa (custo linear por achado)."""
    floor = max(0, start - _CONTEXT_REACH)
    begin = floor
    for item in _SENTENCE_BREAK.finditer(folded, floor, start):
        if _is_sentence_break(folded, item):
            begin = item.end()
    ceiling = min(len(folded), end + _CONTEXT_AHEAD)
    stop = folded.find("\n", end, ceiling)
    stop = ceiling if stop == -1 else stop
    for item in _SENTENCE_BREAK.finditer(folded, end, stop):
        if _is_sentence_break(folded, item):
            stop = item.start() + 1
            break
    return begin, stop


def _context_proposals(page, document_kind, folded, indices, label_spans=(), *, legacy=False):
    found = _clause_rule_proposals(page, document_kind, folded, indices, label_spans)
    if legacy:
        # A reproducao do backup aceita tambem o que a regra anterior propunha:
        # evidencia confirmada antes do #293 continua conferivel nos bytes.
        found.extend(_sentence_rule_proposals(page, document_kind, folded, indices, label_spans))
    found.extend(_city_state_proposals(page, document_kind, folded, indices, label_spans, legacy=legacy))
    return found


def _clause_rule_proposals(page, document_kind, folded, indices, label_spans=()):
    text = page.text
    mode = page.extraction_mode.value
    label_starts = [start for start, _end in label_spans]
    joined, forward = _joined(folded)
    markers = _clause_markers(joined)
    marker_starts = [start for start, _end, _kind in markers]
    streets = list(_STREET.finditer(joined))
    street_ends = [item.end() for item in streets]
    street_starts = [item.start() for item in streets]
    precedents = [item.start() for item in _PRECEDENT_BLOCKERS.finditer(folded)]
    candidates = []
    for field, pattern, group in _PATTERNS:
        for match in pattern.finditer(folded):
            # Linha "Rotulo: valor" ja e evidencia de nivel 1; nao vira segunda proposta.
            source = indices[match.start()]
            position = bisect_right(label_starts, source) - 1
            if position >= 0 and source < label_spans[position][1]:
                continue
            begin, stop = _window(folded, match.start(), match.end())
            context = folded[begin:stop]
            if bisect_right(precedents, stop - 1) > bisect_right(precedents, begin - 1):
                continue
            # A regra anterior (frase inteira) decide qual dos dois regimes vale.
            blocked = _PARTY_ADDRESS_BLOCKERS.search(context) is not None
            if field in _ADDRESS_FIELDS:
                low, reference = forward[begin], forward[match.start()]
                if field != "street":
                    # Numero, bairro, CEP... seguem o logradouro da mesma cadeia.
                    position = bisect_right(street_ends, reference) - 1
                    if position >= 0 and streets[position].start() >= low:
                        street = streets[position]
                        if bisect_right(marker_starts, reference - 1) == bisect_right(marker_starts, street.end() - 1):
                            reference = street.start()
                position = bisect_right(marker_starts, reference) - 1
                nearest = markers[position] if position >= 0 and markers[position][0] >= low else None
                if not blocked:
                    if nearest is not None and nearest[2] not in _SUBJECT_KINDS:
                        continue
                    if nearest is None:
                        # "Na Rua X, nº 10, reside a autora": sem marcador antes,
                        # o primeiro depois da cadeia (antes do proximo logradouro) decide.
                        following = position + 1
                        limit = forward[stop]
                        later = bisect_right(street_starts, reference)
                        if later < len(street_starts):
                            limit = min(limit, street_starts[later])
                        if following < len(markers) and markers[following][0] < limit and markers[following][2] not in _SUBJECT_KINDS:
                            continue
                    bound = any(cue in context for cue in _SUBJECT_PROPERTY_CUES)
                else:
                    # Aqui so vale a pista do imovel objeto (ou participio ancorado nela).
                    if nearest is None or nearest[2] != "SUBJECT":
                        continue
                    if nearest[1] < reference and not _DIRECT_LINK.fullmatch(joined, nearest[1], reference):
                        continue
                    if _PARTY_ADDRESS_BLOCKERS.search(joined, reference, forward[stop]):
                        continue
                    bound = True
            else:
                if blocked:
                    continue
                bound = any(cue in context for cue in _SUBJECT_PROPERTY_CUES)
            value = _original(text, indices, match.start(group), match.end(group))
            if not value:
                continue
            # "residencial" adjetivo ("uso residencial") nao e nome de empreendimento.
            if field == "development" and not _proper_name_follows(value):
                continue
            binding = nearest[0] if field in _ADDRESS_FIELDS and nearest is not None else None
            candidates.append((field, match.start(), begin, stop, value, bound, binding))
    starts = {}
    streets_by_cue = {}
    for field, start, _begin, _stop, value, _bound, binding in candidates:
        starts.setdefault(field, []).append(start)
        if field == "street" and binding is not None:
            streets_by_cue.setdefault(binding, set()).add(value)
    found = []
    for field, start, begin, stop, value, bound, binding in candidates:
        # Mais de uma unidade (ou numero) do imovel na mesma frase, ou dois
        # logradouros presos a mesma pista: o trecho nao diz qual e o do imovel.
        # O que pertence a parte ja ficou de fora.
        ambiguous = field in {"unit", "block", "quadra", "number"} and (
            bisect_right(starts[field], stop - 1) - bisect_right(starts[field], begin - 1)
        ) > 1
        ambiguous = ambiguous or (binding is not None and len(streets_by_cue.get(binding, ())) > 1)
        if bound and not ambiguous:
            strength, method = "STRONG", f"CONTEXT_BOUND_{mode}_V2"
        elif field in _INTRINSIC_FIELDS and document_kind and not ambiguous:
            strength, method = "STRONG", f"DOCUMENT_PATTERN_{mode}_V2"
        elif document_kind or bound or field in _INTRINSIC_FIELDS:
            strength = "POSSIBLE"
            method = f"CONTEXT_BOUND_{mode}_V2" if bound else f"DOCUMENT_PATTERN_{mode}_V2"
        else:
            continue
        excerpt = text[indices[begin]:indices[stop - 1] + 1].strip() if stop > begin else ""
        if value not in excerpt or len(excerpt) > 2000:
            continue
        found.append((field, value, excerpt, method, strength))
    return found


def _sentence_rule_proposals(page, document_kind, folded, indices, label_spans=()):
    """Regra anterior ao #293 (frase inteira), so para reproduzir backup antigo."""
    text = page.text
    mode = page.extraction_mode.value
    found = []
    label_starts = [start for start, _end in label_spans]
    for field, pattern, group in _PATTERNS:
        for match in pattern.finditer(folded):
            # Linha "Rotulo: valor" ja e evidencia de nivel 1; nao vira segunda proposta.
            source = indices[match.start()]
            position = bisect_right(label_starts, source) - 1
            if position >= 0 and source < label_spans[position][1]:
                continue
            begin, stop = _window(folded, match.start(), match.end())
            context = folded[begin:stop]
            if _PARTY_ADDRESS_BLOCKERS.search(context):
                continue
            value = _original(text, indices, match.start(group), match.end(group))
            if not value:
                continue
            # "residencial" adjetivo ("uso residencial") nao e nome de empreendimento.
            if field == "development" and not _proper_name_follows(value):
                continue
            bound = any(cue in context for cue in _SUBJECT_PROPERTY_CUES)
            # Mais de uma unidade na mesma frase: o trecho nao diz qual e a do imovel.
            ambiguous = field in {"unit", "block", "quadra", "number"} and len(_PATTERN_BY_FIELD[field].findall(context)) > 1
            if bound and not ambiguous:
                strength, method = "STRONG", f"CONTEXT_BOUND_{mode}_V2"
            elif field in _INTRINSIC_FIELDS and document_kind and not ambiguous:
                strength, method = "STRONG", f"DOCUMENT_PATTERN_{mode}_V2"
            elif document_kind or bound or field in _INTRINSIC_FIELDS:
                strength = "POSSIBLE"
                method = f"CONTEXT_BOUND_{mode}_V2" if bound else f"DOCUMENT_PATTERN_{mode}_V2"
            else:
                continue
            excerpt = text[indices[begin]:indices[stop - 1] + 1].strip() if stop > begin else ""
            if value not in excerpt or len(excerpt) > 2000:
                continue
            found.append((field, value, excerpt, method, strength))
    return found


def _city_state_proposals(page, document_kind, folded, indices, label_spans, *, legacy=False):
    text = page.text
    mode = page.extraction_mode.value
    found = []
    label_starts = [start for start, _end in label_spans]
    for match in _CITY_UF.finditer(folded):
        source = indices[match.start()]
        position = bisect_right(label_starts, source) - 1
        if position >= 0 and source < label_spans[position][1]:
            continue
        begin, stop = _window(folded, match.start(), match.end())
        context = folded[begin:stop]
        if _PARTY_ADDRESS_BLOCKERS.search(context) or _CITY_BLOCKERS.search(context):
            continue
        # Municipio/UF seguem a frase inteira (fail-closed): residencia ou sede de parte na frase basta.
        if not legacy and _PARTY_INTRODUCERS.search(context):
            continue
        if not _ADDRESS_ANCHOR.search(folded, max(begin, match.start() - _ANCHOR_REACH), match.start()):
            continue
        if _DATE_AFTER.match(folded, match.end()):
            continue
        city = _CITY_PREFIX.sub("", _original(text, indices, match.start(1), match.end(1)))
        state = _original(text, indices, match.start(2), match.end(2))
        if not _city_name(city) or not (len(state) == 2 and state.isupper()):
            continue
        bound = any(cue in context for cue in _SUBJECT_PROPERTY_CUES)
        if bound:
            strength, method = "STRONG", f"CONTEXT_BOUND_{mode}_V2"
        elif document_kind:
            strength, method = "POSSIBLE", f"DOCUMENT_PATTERN_{mode}_V2"
        else:
            continue
        excerpt = text[indices[begin]:indices[stop - 1] + 1].strip() if stop > begin else ""
        if city not in excerpt or state not in excerpt or len(excerpt) > 2000:
            continue
        found.append(("city", city, excerpt, method, strength))
        found.append(("state", state, excerpt, method, strength))
    return found


def property_proposals(workspace_id, document_id, checksum, filename, pages, *, include_legacy_labels=False, logical_document_for=None):
    """Rotulo explicito, padroes por tipo de peca e propostas ligadas ao contexto.

    O nivel de rotulo e byte-identico ao V1: o fecho do backup reextrai essa
    evidencia para conferi-la. Endereco de parte, de advogado, de juizo ou de
    precedente nunca vira endereco do imovel. `include_legacy_labels` existe so
    para a verificacao de backup: aceita a evidencia de rotulo confirmada antes
    do filtro de endereco de parte, e a de contexto da regra anterior a #293
    (frase inteira), sem oferece-las de novo como proposta.
    `logical_document_for(pagina)` delimita a peca do export PJe: o tipo de
    peca pertinente (contrato, matricula, laudo) nao vaza para a peca seguinte.
    """
    aliases = {_normalized(alias): field for field, _label, _kind, labels in PROPERTY_FIELDS for alias in labels}
    proposals = []
    seen = set()

    def add(field, value, excerpt, method, strength, page, rank_kind="", piece=None):
        if _DEFINITIONS[field][1] == "decimal":
            value = re.sub(r"\s*m[²2]\s*$", "", value).removeprefix("R$").strip()
        try:
            _value(field, value)
        except ValueError:
            return
        evidence = PropertyEvidence(str(document_id), checksum, filename, page.number, excerpt, method, page.confidence, value)
        identity = json.dumps([str(workspace_id), field, asdict(evidence)], ensure_ascii=False, sort_keys=True)
        proposal = PropertyProposal(
            sha256(identity.encode()).hexdigest(), str(workspace_id), field, value, evidence, strength,
            _source_rank(rank_kind or "", method, strength), piece,
        )
        if proposal.proposal_id not in seen:
            seen.add(proposal.proposal_id)
            proposals.append(proposal)

    document_kind = ""
    rank_kind = None
    current_piece = None
    for page in pages:
        mode = page.extraction_mode.value
        if mode not in {"NATIVE_TEXT", "OCR"}:
            continue
        if logical_document_for is not None:
            piece = logical_document_for(page.number)
            if piece != current_piece:
                current_piece, document_kind = piece, ""
                rank_kind = None
        folded_page, page_indices = _folded(page.text)
        kind = next((item for item in _PERTINENT_DOCUMENTS if item in folded_page[:600]), "")
        if kind:
            document_kind = kind
        # O peso vem do titulo da primeira pagina da peca; sem pecas do PJe,
        # cada pagina vale pelo proprio titulo e nada se arrasta para a seguinte.
        # Pagina fora de qualquer peca (arquivo sem inventario PJe) tambem.
        if current_piece is None or rank_kind is None:
            rank_kind = _rank_kind(folded_page)
        lines = page.text.splitlines()
        offsets, cursor = [], 0
        for raw in page.text.splitlines(keepends=True):
            offsets.append(cursor)
            cursor += len(raw)
        label_spans = []
        for index, line in enumerate(lines):
            match = re.fullmatch(r"\s*([^:]{1,80}):\s*(.{1,1000}?)\s*", line)
            field = aliases.get(_normalized(match[1])) if match else None
            if field is None:
                continue
            label_spans.append((offsets[index], offsets[index] + len(line)))
            # So rotulo de endereco generico ("Logradouro:", "CEP:") depois de
            # qualificacao de parte ou timbre institucional deixa de ser proposto;
            # rotulo que nomeia o imovel ("Logradouro do imovel:") liga o dado.
            if not include_legacy_labels and field in _ADDRESS_FIELDS and "imovel" not in _normalized(match[1]):
                nearby = _folded(" ".join(lines[max(0, index - 2):index + 1]))[0]
                if _LABEL_QUALIFICATION_BLOCKERS.search(nearby):
                    continue
            add(field, match[2].strip(), line.strip(), f"LABEL_{mode}_V1", "STRONG", page, rank_kind, current_piece)
        for field, value, excerpt, method, strength in _context_proposals(page, document_kind, folded_page, page_indices, tuple(label_spans), legacy=include_legacy_labels):
            add(field, value, excerpt, method, strength, page, rank_kind, current_piece)
    return tuple(proposals)
