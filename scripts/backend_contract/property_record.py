"""Confirmed property facts; proposals never become facts merely by extraction."""

from bisect import bisect_right
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
    r"\b(?:residente|domiciliad\w*|com endereco|com sede|sede (?:na|no|em)|escritorio|oab|advogad\w*|patrono|"
    r"procurador\w*|forum|vara|juizo|tribunal|secao judiciaria|justica federal|justica estadual|poder judiciario)\b"
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


def _context_proposals(page, document_kind, folded, indices, label_spans=()):
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


def property_proposals(workspace_id, document_id, checksum, filename, pages, *, include_legacy_labels=False, logical_document_for=None):
    """Rotulo explicito, padroes por tipo de peca e propostas ligadas ao contexto.

    O nivel de rotulo e byte-identico ao V1: o fecho do backup reextrai essa
    evidencia para conferi-la. Endereco de parte, de advogado, de juizo ou de
    precedente nunca vira endereco do imovel. `include_legacy_labels` existe so
    para a verificacao de backup: aceita a evidencia de rotulo confirmada antes
    do filtro de endereco de parte, sem oferece-la de novo como proposta.
    `logical_document_for(pagina)` delimita a peca do export PJe: o tipo de
    peca pertinente (contrato, matricula, laudo) nao vaza para a peca seguinte.
    """
    aliases = {_normalized(alias): field for field, _label, _kind, labels in PROPERTY_FIELDS for alias in labels}
    proposals = []
    seen = set()

    def add(field, value, excerpt, method, strength, page):
        if _DEFINITIONS[field][1] == "decimal":
            value = re.sub(r"\s*m[²2]\s*$", "", value).removeprefix("R$").strip()
        try:
            _value(field, value)
        except ValueError:
            return
        evidence = PropertyEvidence(str(document_id), checksum, filename, page.number, excerpt, method, page.confidence, value)
        identity = json.dumps([str(workspace_id), field, asdict(evidence)], ensure_ascii=False, sort_keys=True)
        proposal = PropertyProposal(sha256(identity.encode()).hexdigest(), str(workspace_id), field, value, evidence, strength)
        if proposal.proposal_id not in seen:
            seen.add(proposal.proposal_id)
            proposals.append(proposal)

    document_kind = ""
    current_piece = None
    for page in pages:
        mode = page.extraction_mode.value
        if mode not in {"NATIVE_TEXT", "OCR"}:
            continue
        if logical_document_for is not None:
            piece = logical_document_for(page.number)
            if piece != current_piece:
                current_piece, document_kind = piece, ""
        folded_page, page_indices = _folded(page.text)
        kind = next((item for item in _PERTINENT_DOCUMENTS if item in folded_page[:600]), "")
        if kind:
            document_kind = kind
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
            add(field, match[2].strip(), line.strip(), f"LABEL_{mode}_V1", "STRONG", page)
        for field, value, excerpt, method, strength in _context_proposals(page, document_kind, folded_page, page_indices, tuple(label_spans)):
            add(field, value, excerpt, method, strength, page)
    return tuple(proposals)
