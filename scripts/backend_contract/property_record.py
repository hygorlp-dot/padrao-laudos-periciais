"""Confirmed property facts; proposals never become facts merely by extraction."""

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
        if self.method not in ("LABEL_NATIVE_TEXT_V1", "LABEL_OCR_V1"):
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


def _normalized(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(c)).strip()


def property_proposals(workspace_id, document_id, checksum, filename, pages):
    """Explicit labels only; conflicting documents stay separate proposals."""
    aliases = {_normalized(alias): field for field, _label, _kind, labels in PROPERTY_FIELDS for alias in labels}
    proposals = []
    for page in pages:
        for line in page.text.splitlines():
            match = re.fullmatch(r"\s*([^:]{1,80}):\s*(.{1,1000}?)\s*", line)
            field = aliases.get(_normalized(match[1])) if match else None
            if field is None:
                continue
            value = match[2].strip()
            if _DEFINITIONS[field][1] == "decimal":
                value = re.sub(r"\s*m[²2]\s*$", "", value).removeprefix("R$").strip()
            try:
                _value(field, value)
            except ValueError:
                continue
            mode = page.extraction_mode.value
            if mode not in {"NATIVE_TEXT", "OCR"}:
                continue
            evidence = PropertyEvidence(str(document_id), checksum, filename, page.number, line.strip(), f"LABEL_{mode}_V1", page.confidence, value)
            identity = json.dumps([str(workspace_id), field, asdict(evidence)], ensure_ascii=False, sort_keys=True)
            proposal = PropertyProposal(sha256(identity.encode()).hexdigest(), str(workspace_id), field, value, evidence)
            if proposal not in proposals:
                proposals.append(proposal)
    return tuple(proposals)
