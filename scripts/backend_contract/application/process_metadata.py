"""Extração determinística e auditável de identificação processual."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from .models import PrivateContentId, WorkspaceId, thaw_payload


PROCESS_METADATA_FIELDS = (
    "numero_processo",
    "ramo_justica",
    "tribunal",
    "vara",
    "comarca_municipio",
    "uf",
    "parte_requerente",
    "parte_requerida",
)
_CNJ_PATTERN = re.compile(
    r"(?<!\d)(\d{7})-(\d{2})\.(\d{4})\.([1-9])\.(\d{2})\.(\d{4})(?!\d)"
)
_JUSTICE_BRANCHES = {
    "1": "Supremo Tribunal Federal",
    "2": "Conselho Nacional de Justiça",
    "3": "Superior Tribunal de Justiça",
    "4": "Justiça Federal",
    "5": "Justiça do Trabalho",
    "6": "Justiça Eleitoral",
    "7": "Justiça Militar da União",
    "8": "Justiça Estadual",
    "9": "Justiça Militar Estadual",
}


class PdfTextExtractionState(StrEnum):
    AVAILABLE = "AVAILABLE"
    TEXT_EXTRACTION_UNAVAILABLE = "TEXT_EXTRACTION_UNAVAILABLE"
    ERROR = "ERROR"


class FieldExtractionState(StrEnum):
    CONFIDENT = "CONFIDENT"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    CONFLICTING = "CONFLICTING"


@dataclass(frozen=True, slots=True)
class PdfTextPage:
    number: int
    text: str

    def __post_init__(self):
        if type(self.number) is not int or self.number < 1:
            raise ValueError("página PDF inválida")
        if type(self.text) is not str:
            raise TypeError("texto PDF inválido")


@dataclass(frozen=True, slots=True)
class PdfTextResult:
    state: PdfTextExtractionState
    pages: tuple[PdfTextPage, ...]

    def __post_init__(self):
        if type(self.state) is not PdfTextExtractionState:
            raise TypeError("estado de texto PDF inválido")
        if type(self.pages) is not tuple or any(
            type(page) is not PdfTextPage for page in self.pages
        ):
            raise TypeError("páginas PDF inválidas")
        if self.state is not PdfTextExtractionState.AVAILABLE and self.pages:
            raise ValueError("estado de texto PDF diverge das páginas")


@dataclass(frozen=True, slots=True)
class CnjNumber:
    canonical: str
    sequential: str
    check_digits: str
    year: str
    justice_segment: str
    tribunal_code: str
    origin_unit: str
    justice_branch: str


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    workspace_id: WorkspaceId
    document_id: PrivateContentId
    field_name: str
    extracted_value: str
    source_page: int
    extraction_method: str
    extraction_timestamp: str
    source_filename: str
    normalized_text_span: str

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace_id": str(self.workspace_id),
            "document_id": str(self.document_id),
            "field_name": self.field_name,
            "extracted_value": self.extracted_value,
            "source_page": self.source_page,
            "extraction_method": self.extraction_method,
            "extraction_timestamp": self.extraction_timestamp,
            "source_filename": self.source_filename,
            "normalized_text_span": self.normalized_text_span,
        }


@dataclass(frozen=True, slots=True)
class ExtractedField:
    state: FieldExtractionState
    value: str
    evidence: tuple[FieldEvidence, ...]


@dataclass(frozen=True, slots=True)
class DocumentProcessMetadata:
    workspace_id: WorkspaceId
    document_id: PrivateContentId
    source_filename: str
    text_state: PdfTextExtractionState
    fields: MappingProxyType


@dataclass(frozen=True, slots=True)
class DocumentExtractionSummary:
    document_id: PrivateContentId
    source_filename: str
    text_state: PdfTextExtractionState


@dataclass(frozen=True, slots=True)
class ProcessMetadataAggregate:
    workspace_id: WorkspaceId | None
    state: str
    fields: MappingProxyType


@dataclass(frozen=True, slots=True)
class ProcessMetadataReview:
    workspace_id: WorkspaceId
    state: str
    confirmed_revision: int | None
    fields: MappingProxyType
    documents: tuple[DocumentExtractionSummary, ...]
    extraction_fingerprint: str
    document_payloads: tuple[object, ...]


def validate_cnj_number(value: str) -> CnjNumber:
    if type(value) is not str:
        raise TypeError("número CNJ inválido")
    match = _CNJ_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("número CNJ inválido")
    sequential, check_digits, year, segment, tribunal, origin = match.groups()
    base = f"{sequential}{year}{segment}{tribunal}{origin}00"
    expected = 98 - (int(base) % 97)
    if int(check_digits) != expected:
        raise ValueError("dígito verificador CNJ inválido")
    return CnjNumber(
        canonical=match.group(0),
        sequential=sequential,
        check_digits=check_digits,
        year=year,
        justice_segment=segment,
        tribunal_code=tribunal,
        origin_unit=origin,
        justice_branch=_JUSTICE_BRANCHES[segment],
    )


def _ascii_upper(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(character for character in decomposed if not unicodedata.combining(character)).upper()


def _timestamp(value: str) -> str:
    if type(value) is not str:
        raise TypeError("timestamp de extração inválido")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp de extração inválido") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp de extração exige timezone")
    return value


def _filename(value: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError("nome de documento inválido")
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\")):
        raise ValueError("filename não pode conter path absoluto")
    return value


def _evidence(
    *,
    workspace_id: WorkspaceId,
    document_id: PrivateContentId,
    field_name: str,
    value: str,
    page: PdfTextPage,
    extracted_at: str,
    source_filename: str,
    span: str,
) -> FieldEvidence:
    return FieldEvidence(
        workspace_id=workspace_id,
        document_id=document_id,
        field_name=field_name,
        extracted_value=value,
        source_page=page.number,
        extraction_method="LOCAL_PDF_TEXT_V1",
        extraction_timestamp=extracted_at,
        source_filename=source_filename,
        normalized_text_span=" ".join(span.split())[:240],
    )


def _resolved_field(
    candidates: list[FieldEvidence],
    *,
    ambiguous: bool = False,
    combined: bool = False,
) -> ExtractedField:
    unique: list[FieldEvidence] = []
    seen = set()
    for candidate in candidates:
        key = _ascii_upper(" ".join(candidate.extracted_value.split()))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    evidence = tuple(unique)
    if not evidence:
        return ExtractedField(FieldExtractionState.NOT_FOUND, "", ())
    if ambiguous:
        return ExtractedField(FieldExtractionState.AMBIGUOUS, "", evidence)
    if combined:
        return ExtractedField(
            FieldExtractionState.CONFIDENT,
            "; ".join(item.extracted_value for item in evidence),
            evidence,
        )
    if len(evidence) > 1:
        return ExtractedField(FieldExtractionState.CONFLICTING, "", evidence)
    return ExtractedField(FieldExtractionState.CONFIDENT, evidence[0].extracted_value, evidence)


def extract_process_metadata(
    *,
    workspace_id: WorkspaceId,
    document_id: PrivateContentId,
    original_filename: str,
    text: PdfTextResult,
    extracted_at: str,
) -> DocumentProcessMetadata:
    if type(workspace_id) is not WorkspaceId or type(document_id) is not PrivateContentId:
        raise TypeError("identidade de extração inválida")
    if type(text) is not PdfTextResult:
        raise TypeError("resultado de texto PDF inválido")
    source_filename = _filename(original_filename)
    extracted_at = _timestamp(extracted_at)
    candidates: dict[str, list[FieldEvidence]] = {
        field: [] for field in PROCESS_METADATA_FIELDS
    }
    invalid_cnj: list[FieldEvidence] = []

    def add(field: str, value: str, page: PdfTextPage, span: str) -> None:
        cleaned = " ".join(value.strip(" \t:-").split())
        if cleaned:
            candidates[field].append(
                _evidence(
                    workspace_id=workspace_id,
                    document_id=document_id,
                    field_name=field,
                    value=cleaned,
                    page=page,
                    extracted_at=extracted_at,
                    source_filename=source_filename,
                    span=span,
                )
            )

    for page in text.pages:
        normalized_page = _ascii_upper(page.text)
        for cnj_match in _CNJ_PATTERN.finditer(page.text):
            raw = cnj_match.group(0)
            try:
                cnj = validate_cnj_number(raw)
            except ValueError:
                invalid_cnj.append(
                    _evidence(
                        workspace_id=workspace_id,
                        document_id=document_id,
                        field_name="numero_processo",
                        value=raw,
                        page=page,
                        extracted_at=extracted_at,
                        source_filename=source_filename,
                        span=raw,
                    )
                )
                continue
            add("numero_processo", cnj.canonical, page, raw)
            add("ramo_justica", cnj.justice_branch, page, raw)
            if cnj.justice_segment == "4":
                add(
                    "tribunal",
                    f"Tribunal Regional Federal da {int(cnj.tribunal_code)}ª Região",
                    page,
                    raw,
                )

        for line, normalized_line in zip(page.text.splitlines(), normalized_page.splitlines()):
            tribunal_match = re.search(
                r"TRIBUNAL\s+REGIONAL\s+FEDERAL\s+DA\s+(\d{1,2})(?:A)?\s+REGIAO",
                normalized_line,
            )
            if tribunal_match:
                region = int(tribunal_match.group(1))
                add("tribunal", f"Tribunal Regional Federal da {region}ª Região", page, line)

            unit_match = re.search(r"\b(\d{1,3})\s*(?:A)?\s+VARA(?:\s+FEDERAL)?\b", normalized_line)
            if unit_match:
                suffix = " Federal" if "FEDERAL" in unit_match.group(0) else ""
                add("vara", f"{int(unit_match.group(1))}ª Vara{suffix}", page, line)

            location_match = re.search(
                r"(?:SUBSECAO\s+JUDICIARIA|COMARCA|MUNICIPIO)(?:\s+DE)?\s*[:\-]?\s*([A-Z][A-Z '\-]{1,80}?)\s*/\s*([A-Z]{2})\b",
                normalized_line,
            )
            if location_match:
                raw_location = location_match.group(1).strip()
                location_words = [word.capitalize() for word in raw_location.split()]
                add("comarca_municipio", " ".join(location_words), page, line)
                add("uf", location_match.group(2), page, line)

            party_match = re.match(
                r"\s*(AUTOR(?:A)?|REQUERENTE|EXEQUENTE|REQUERIDO(?:A)?|REU|EXECUTADO(?:A)?)\s*:\s*(.+?)\s*$",
                normalized_line,
            )
            if party_match:
                original_value = line.split(":", 1)[1].strip()
                field = (
                    "parte_requerente"
                    if party_match.group(1) in {"AUTOR", "AUTORA", "REQUERENTE", "EXEQUENTE"}
                    else "parte_requerida"
                )
                add(field, original_value, page, line)

    fields = {
        field: _resolved_field(
            candidates[field],
            ambiguous=(field == "numero_processo" and bool(invalid_cnj) and not candidates[field]),
            combined=field in {"parte_requerente", "parte_requerida"},
        )
        for field in PROCESS_METADATA_FIELDS
    }
    if invalid_cnj and not candidates["numero_processo"]:
        fields["numero_processo"] = ExtractedField(
            FieldExtractionState.AMBIGUOUS,
            "",
            tuple(invalid_cnj),
        )
    return DocumentProcessMetadata(
        workspace_id=workspace_id,
        document_id=document_id,
        source_filename=source_filename,
        text_state=text.state,
        fields=MappingProxyType(fields),
    )


def aggregate_process_metadata(
    documents: tuple[DocumentProcessMetadata, ...],
) -> ProcessMetadataAggregate:
    if type(documents) is not tuple or any(
        type(document) is not DocumentProcessMetadata for document in documents
    ):
        raise TypeError("extrações documentais inválidas")
    if not documents:
        return ProcessMetadataAggregate(
            workspace_id=None,
            state="WAITING_FOR_DOCUMENTS",
            fields=MappingProxyType(
                {
                    field: ExtractedField(FieldExtractionState.NOT_FOUND, "", ())
                    for field in PROCESS_METADATA_FIELDS
                }
            ),
        )
    workspace_id = documents[0].workspace_id
    if any(document.workspace_id != workspace_id for document in documents):
        raise ValueError("extrações pertencem a workspaces diferentes")
    fields: dict[str, ExtractedField] = {}
    for name in PROCESS_METADATA_FIELDS:
        document_fields = [document.fields[name] for document in documents]
        evidence = tuple(item for field in document_fields for item in field.evidence)
        confident_values = {
            _ascii_upper(field.value): field.value
            for field in document_fields
            if field.state is FieldExtractionState.CONFIDENT and field.value
        }
        if any(field.state is FieldExtractionState.CONFLICTING for field in document_fields) or len(confident_values) > 1:
            fields[name] = ExtractedField(FieldExtractionState.CONFLICTING, "", evidence)
        elif any(field.state is FieldExtractionState.AMBIGUOUS for field in document_fields):
            fields[name] = ExtractedField(FieldExtractionState.AMBIGUOUS, "", evidence)
        elif confident_values:
            fields[name] = ExtractedField(
                FieldExtractionState.CONFIDENT,
                next(iter(confident_values.values())),
                evidence,
            )
        else:
            fields[name] = ExtractedField(FieldExtractionState.NOT_FOUND, "", ())
    if any(field.state is FieldExtractionState.CONFLICTING for field in fields.values()):
        state = "CONFLICT"
    elif all(
        document.text_state is PdfTextExtractionState.ERROR for document in documents
    ):
        state = "ERROR"
    elif all(field.state is FieldExtractionState.CONFIDENT for field in fields.values()):
        state = "EXTRACTED"
    else:
        state = "PARTIAL"
    return ProcessMetadataAggregate(workspace_id, state, MappingProxyType(fields))


def document_metadata_payload(document: DocumentProcessMetadata) -> dict[str, object]:
    if type(document) is not DocumentProcessMetadata:
        raise TypeError("extração documental inválida")
    return {
        "schema_version": 1,
        "workspace_id": str(document.workspace_id),
        "document_id": str(document.document_id),
        "source_filename": document.source_filename,
        "text_state": document.text_state.value,
        "fields": {
            name: {
                "state": field.state.value,
                "value": field.value,
                "evidence": [item.as_dict() for item in field.evidence],
            }
            for name, field in document.fields.items()
        },
    }


def document_metadata_from_payload(value: object) -> DocumentProcessMetadata:
    payload = thaw_payload(value)
    if type(payload) is not dict or set(payload) != {
        "schema_version",
        "workspace_id",
        "document_id",
        "source_filename",
        "text_state",
        "fields",
    } or payload["schema_version"] != 1:
        raise ValueError("extração documental persistida inválida")
    workspace_id = WorkspaceId.parse(payload["workspace_id"])
    document_id = PrivateContentId.parse(payload["document_id"])
    source_filename = _filename(payload["source_filename"])
    text_state = PdfTextExtractionState(payload["text_state"])
    raw_fields = payload["fields"]
    if type(raw_fields) is not dict or set(raw_fields) != set(PROCESS_METADATA_FIELDS):
        raise ValueError("campos de extração persistidos inválidos")
    fields = {}
    for name in PROCESS_METADATA_FIELDS:
        raw = raw_fields[name]
        if type(raw) is not dict or set(raw) != {"state", "value", "evidence"}:
            raise ValueError("campo de extração persistido inválido")
        if type(raw["value"]) is not str or type(raw["evidence"]) is not list:
            raise ValueError("campo de extração persistido inválido")
        evidence = []
        for item in raw["evidence"]:
            if type(item) is not dict or set(item) != {
                "workspace_id",
                "document_id",
                "field_name",
                "extracted_value",
                "source_page",
                "extraction_method",
                "extraction_timestamp",
                "source_filename",
                "normalized_text_span",
            }:
                raise ValueError("proveniência persistida inválida")
            record = FieldEvidence(
                workspace_id=WorkspaceId.parse(item["workspace_id"]),
                document_id=PrivateContentId.parse(item["document_id"]),
                field_name=item["field_name"],
                extracted_value=item["extracted_value"],
                source_page=item["source_page"],
                extraction_method=item["extraction_method"],
                extraction_timestamp=_timestamp(item["extraction_timestamp"]),
                source_filename=_filename(item["source_filename"]),
                normalized_text_span=item["normalized_text_span"],
            )
            if (
                record.workspace_id != workspace_id
                or record.document_id != document_id
                or record.field_name != name
            ):
                raise ValueError("identidade da proveniência persistida diverge")
            evidence.append(record)
        fields[name] = ExtractedField(
            FieldExtractionState(raw["state"]),
            raw["value"],
            tuple(evidence),
        )
    return DocumentProcessMetadata(
        workspace_id,
        document_id,
        source_filename,
        text_state,
        MappingProxyType(fields),
    )


def review_dto(review: ProcessMetadataReview) -> dict[str, object]:
    return {
        "workspace_id": str(review.workspace_id),
        "state": review.state,
        "confirmed_revision": review.confirmed_revision,
        "documents": [
            {
                "document_id": str(document.document_id),
                "source_filename": document.source_filename,
                "text_state": document.text_state.value,
            }
            for document in review.documents
        ],
        "fields": {
            name: {
                "state": field.state.value,
                "value": field.value,
                "evidence": [item.as_dict() for item in field.evidence],
            }
            for name, field in review.fields.items()
        },
    }
