"""Extração determinística e auditável de identificação processual."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from .models import PrivateContentId, WorkspaceId, canonical_payload_json, thaw_payload
from .judicial_unit_directory import resolve_judicial_unit
from .pje_party_table import PjePartyPole, parse_pje_party_table


PROCESS_METADATA_FIELDS = (
    "numero_processo",
    "ramo_justica",
    "tribunal",
    "vara",
    "municipio_sede",
    "subsecao_judiciaria",
    "comarca_municipio",
    "uf",
    "parte_requerente",
    "parte_requerida",
)
_LEGACY_PROCESS_METADATA_FIELDS = tuple(
    field
    for field in PROCESS_METADATA_FIELDS
    if field not in {"municipio_sede", "subsecao_judiciaria"}
)
_CNJ_PATTERN = re.compile(
    r"(?<!\d)(\d{7})-(\d{2})\.(\d{4})\.([1-9])\.(\d{2})\.(\d{4})(?!\d)"
)
_OCR_CNJ_PATTERN = re.compile(
    r"(?<![0-9A-Z])([0-9OILSB]{7})-([0-9OILSB]{2})\."
    r"([0-9OILSB]{4})\.([0-9OILSB])\.([0-9OILSB]{2})\."
    r"([0-9OILSB]{4})(?![0-9A-Z])",
    re.IGNORECASE,
)
_OCR_DIGIT_CONFUSIONS = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"})
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
_FEDERAL_TRIBUNAL_REGIONS = {
    "01": 1,
    "02": 2,
    "03": 3,
    "04": 4,
    "05": 5,
    "06": 6,
}
_BRAZILIAN_UF_CODES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
    "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
    "RR", "SC", "SP", "SE", "TO",
}


class PdfTextExtractionState(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    TEXT_EXTRACTION_UNAVAILABLE = "TEXT_EXTRACTION_UNAVAILABLE"
    ERROR = "ERROR"


class FieldExtractionState(StrEnum):
    CONFIDENT = "CONFIDENT"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    CONFLICTING = "CONFLICTING"


class ProcessMetadataSourceRole(StrEnum):
    PRIMARY_PROCESS_COVER = "PRIMARY_PROCESS_COVER"
    PRIMARY_PROCESS_HEADER = "PRIMARY_PROCESS_HEADER"
    PRIMARY_PARTY_STRUCTURE = "PRIMARY_PARTY_STRUCTURE"
    PRIMARY_PROCESS_DOCUMENT = "PRIMARY_PROCESS_DOCUMENT"
    REFERENCED_CASE = "REFERENCED_CASE"
    CITED_JURISPRUDENCE = "CITED_JURISPRUDENCE"
    ANNEX_DOCUMENT = "ANNEX_DOCUMENT"
    UNKNOWN_SOURCE_CONTEXT = "UNKNOWN_SOURCE_CONTEXT"


class PageExtractionMode(StrEnum):
    NATIVE_TEXT = "NATIVE_TEXT"
    OCR = "OCR"


class PageProcessingStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    TRUNCATED = "TRUNCATED"
    OCR_FAILED = "OCR_FAILED"
    NOT_PROCESSED = "NOT_PROCESSED"


@dataclass(frozen=True, slots=True)
class PageTextBlock:
    text: str
    confidence: float | None = None
    bounding_box: tuple[float, float, float, float] | None = None

    def __post_init__(self):
        if type(self.text) is not str or not self.text.strip():
            raise ValueError("bloco textual de página inválido")
        if self.confidence is not None and (
            type(self.confidence) is not float or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confiança de OCR inválida")
        if self.bounding_box is not None and (
            type(self.bounding_box) is not tuple
            or len(self.bounding_box) != 4
            or any(type(value) is not float for value in self.bounding_box)
        ):
            raise ValueError("bounding box de OCR inválida")


@dataclass(frozen=True, slots=True)
class PdfTextPage:
    number: int
    text: str
    extraction_mode: PageExtractionMode = PageExtractionMode.NATIVE_TEXT
    engine: str = "pypdf"
    engine_version: str = ""
    model_version: str = ""
    config_version: str = "PDF_TEXT_V1"
    confidence: float | None = None
    blocks: tuple[PageTextBlock, ...] = ()
    processing_status: PageProcessingStatus = PageProcessingStatus.AVAILABLE

    def __post_init__(self):
        if type(self.number) is not int or self.number < 1:
            raise ValueError("página PDF inválida")
        if type(self.text) is not str:
            raise TypeError("texto PDF inválido")
        if type(self.extraction_mode) is not PageExtractionMode:
            raise TypeError("modo de extração da página inválido")
        for value, name in (
            (self.engine, "engine"),
            (self.engine_version, "engine_version"),
            (self.model_version, "model_version"),
            (self.config_version, "config_version"),
        ):
            if type(value) is not str:
                raise TypeError(f"{name} da página inválido")
        if self.confidence is not None and (
            type(self.confidence) is not float or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confiança da página inválida")
        if type(self.blocks) is not tuple or any(
            type(block) is not PageTextBlock for block in self.blocks
        ):
            raise TypeError("blocos textuais da página inválidos")
        if type(self.processing_status) is not PageProcessingStatus:
            raise TypeError("status de processamento da página inválido")
        if self.processing_status in {
            PageProcessingStatus.AVAILABLE,
            PageProcessingStatus.TRUNCATED,
        } and not self.text.strip():
            raise ValueError("página textual exige texto")
        if self.processing_status is PageProcessingStatus.OCR_FAILED and (
            self.extraction_mode is not PageExtractionMode.OCR
            or self.text
            or self.blocks
            or self.confidence is not None
        ):
            raise ValueError("falha de OCR possui evidência textual divergente")
        if self.processing_status is PageProcessingStatus.NOT_PROCESSED and (
            self.text or self.blocks or self.confidence is not None
        ):
            raise ValueError("página não processada possui evidência textual")


@dataclass(frozen=True, slots=True)
class PdfTextResult:
    state: PdfTextExtractionState
    pages: tuple[PdfTextPage, ...]
    document_sha256: str = ""
    ocr_pages_processed: int = 0
    native_pages_skipped: int = 0
    cache_hits: int = 0

    def __post_init__(self):
        if type(self.state) is not PdfTextExtractionState:
            raise TypeError("estado de texto PDF inválido")
        if type(self.pages) is not tuple or any(
            type(page) is not PdfTextPage for page in self.pages
        ):
            raise TypeError("páginas PDF inválidas")
        if self.document_sha256 and (
            len(self.document_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.document_sha256)
        ):
            raise ValueError("checksum do documento inválido")
        for value, name in (
            (self.ocr_pages_processed, "ocr_pages_processed"),
            (self.native_pages_skipped, "native_pages_skipped"),
            (self.cache_hits, "cache_hits"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} inválido")
        available = tuple(
            page for page in self.pages
            if page.processing_status is PageProcessingStatus.AVAILABLE
        )
        truncated = tuple(
            page for page in self.pages
            if page.processing_status is PageProcessingStatus.TRUNCATED
        )
        failed = tuple(
            page for page in self.pages
            if page.processing_status is PageProcessingStatus.OCR_FAILED
        )
        not_processed = tuple(
            page for page in self.pages
            if page.processing_status is PageProcessingStatus.NOT_PROCESSED
        )
        textual = available + truncated
        if self.state is PdfTextExtractionState.AVAILABLE and not available:
            raise ValueError("estado disponível exige página textual")
        if self.state is PdfTextExtractionState.AVAILABLE and (
            truncated or failed or not_processed
        ):
            raise ValueError("estado disponível não aceita perda parcial de página")
        if self.state is PdfTextExtractionState.PARTIAL and (
            not textual or not (truncated or failed or not_processed)
        ):
            raise ValueError("estado parcial exige texto e página incompleta")
        if self.state is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE and textual:
            raise ValueError("estado indisponível diverge das páginas")
        if self.state is PdfTextExtractionState.ERROR and (
            textual or failed or not_processed
        ):
            raise ValueError("estado de erro não aceita páginas")


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
    extraction_mode: PageExtractionMode
    ocr_engine: str
    engine_version: str
    model_version: str
    ocr_confidence: float | None
    bounding_box: tuple[float, float, float, float] | None
    source_text: str = ""
    source_start: int = 0
    requires_source_selection: bool = False
    source_role: ProcessMetadataSourceRole = (
        ProcessMetadataSourceRole.UNKNOWN_SOURCE_CONTEXT
    )
    derivation_authority: str = ""
    derivation_reference: str = ""

    def __post_init__(self):
        if type(self.source_page) is not int or self.source_page < 1:
            raise ValueError("página da proveniência inválida")
        if type(self.extraction_mode) is not PageExtractionMode:
            raise TypeError("modo da proveniência inválido")
        if any(
            type(value) is not str
            for value in (
                self.extraction_method,
                self.ocr_engine,
                self.engine_version,
                self.model_version,
                self.normalized_text_span,
                self.source_text,
            )
        ):
            raise TypeError("proveniência textual inválida")
        if type(self.source_start) is not int or self.source_start < 0:
            raise ValueError("offset da proveniência inválido")
        if type(self.requires_source_selection) is not bool:
            raise TypeError("contrato de seleção da proveniência inválido")
        if type(self.source_role) is not ProcessMetadataSourceRole:
            raise TypeError("papel da fonte inválido")
        if (
            type(self.derivation_authority) is not str
            or type(self.derivation_reference) is not str
            or bool(self.derivation_authority) != bool(self.derivation_reference)
        ):
            raise ValueError("proveniência da derivação inválida")
        if self.requires_source_selection and (
            not self.source_text or self.extracted_value
        ):
            raise ValueError("evidência não segmentada possui candidato automático")
        if self.bounding_box is not None and (
            type(self.bounding_box) is not tuple
            or len(self.bounding_box) != 4
            or any(type(value) is not float for value in self.bounding_box)
        ):
            raise ValueError("bounding box da proveniência inválida")
        native = (
            self.extraction_mode is PageExtractionMode.NATIVE_TEXT
            and self.extraction_method == "LOCAL_PDF_TEXT_V1"
            and not self.ocr_engine
            and not self.model_version
            and self.ocr_confidence is None
            and self.bounding_box is None
        )
        ocr = (
            self.extraction_mode is PageExtractionMode.OCR
            and self.extraction_method == "LOCAL_OCR_V1"
            and bool(self.ocr_engine)
            and bool(self.engine_version)
            and bool(self.model_version)
            and type(self.ocr_confidence) is float
            and 0.0 <= self.ocr_confidence <= 1.0
        )
        if not native and not ocr:
            raise ValueError("identidade da proveniência diverge do modo de extração")

    @property
    def evidence_id(self) -> str:
        return self._identity(include_authority=True)

    @property
    def legacy_v5_evidence_id(self) -> str:
        return self._identity(include_authority=False)

    def _identity(self, *, include_authority: bool) -> str:
        identity = {
            "workspace_id": str(self.workspace_id),
            "document_id": str(self.document_id),
            "field_name": self.field_name,
            "extracted_value": self.extracted_value,
            "source_page": self.source_page,
            "extraction_method": self.extraction_method,
            "extraction_timestamp": self.extraction_timestamp,
            "source_filename": self.source_filename,
            "normalized_text_span": self.normalized_text_span,
            "extraction_mode": self.extraction_mode.value,
            "ocr_engine": self.ocr_engine,
            "engine_version": self.engine_version,
            "model_version": self.model_version,
            "ocr_confidence": self.ocr_confidence,
            "bounding_box": (
                list(self.bounding_box) if self.bounding_box is not None else None
            ),
            "source_text": self.source_text,
            "source_start": self.source_start,
            "requires_source_selection": self.requires_source_selection,
        }
        if include_authority:
            identity.update(
                {
                    "source_role": self.source_role.value,
                    "derivation_authority": self.derivation_authority,
                    "derivation_reference": self.derivation_reference,
                }
            )
        return hashlib.sha256(
            canonical_payload_json(identity).encode("utf-8")
        ).hexdigest()

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
            "extraction_mode": self.extraction_mode.value,
            "ocr_engine": self.ocr_engine,
            "engine_version": self.engine_version,
            "model_version": self.model_version,
            "ocr_confidence": self.ocr_confidence,
            "bounding_box": list(self.bounding_box) if self.bounding_box is not None else None,
            "evidence_id": self.evidence_id,
            "source_text": self.source_text,
            "source_start": self.source_start,
            "requires_source_selection": self.requires_source_selection,
            "source_role": self.source_role.value,
            "derivation_authority": self.derivation_authority,
            "derivation_reference": self.derivation_reference,
        }


@dataclass(frozen=True, slots=True)
class ExtractedField:
    state: FieldExtractionState
    value: str
    evidence: tuple[FieldEvidence, ...]


@dataclass(frozen=True, slots=True)
class _CnjCandidate:
    number: CnjNumber
    evidence: FieldEvidence
    page: PdfTextPage
    span: str
    start: int
    end: int
    explicit_primary_anchor: bool
    rejects_primary_anchor: bool
    source_role: ProcessMetadataSourceRole


@dataclass(frozen=True, slots=True)
class _FieldCandidate:
    evidence: FieldEvidence
    page: PdfTextPage
    start: int


@dataclass(frozen=True, slots=True)
class DocumentProcessMetadata:
    workspace_id: WorkspaceId
    document_id: PrivateContentId
    source_filename: str
    text_state: PdfTextExtractionState
    fields: MappingProxyType
    document_sha256: str = ""
    page_evidence: tuple[DocumentPageEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class DocumentPageEvidence:
    page_number: int
    extraction_mode: PageExtractionMode
    engine: str
    engine_version: str
    model_version: str
    config_version: str
    confidence: float | None
    bounding_boxes: tuple[tuple[float, float, float, float], ...]
    processing_status: PageProcessingStatus

    def __post_init__(self):
        if type(self.page_number) is not int or self.page_number < 1:
            raise ValueError("número da evidência de página inválido")
        if type(self.extraction_mode) is not PageExtractionMode:
            raise TypeError("modo da evidência de página inválido")
        if any(
            type(value) is not str
            for value in (
                self.engine,
                self.engine_version,
                self.model_version,
                self.config_version,
            )
        ) or not self.engine or not self.config_version:
            raise ValueError("identidade da evidência de página inválida")
        if self.confidence is not None and (
            type(self.confidence) is not float or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confiança da evidência de página inválida")
        if type(self.bounding_boxes) is not tuple or any(
            type(box) is not tuple
            or len(box) != 4
            or any(type(value) is not float for value in box)
            for box in self.bounding_boxes
        ):
            raise ValueError("bounding boxes da evidência de página inválidas")
        if type(self.processing_status) is not PageProcessingStatus:
            raise TypeError("status da evidência de página inválido")
        if self.extraction_mode is PageExtractionMode.OCR and (
            not self.engine_version or not self.model_version
        ):
            raise ValueError("identidade OCR da evidência de página incompleta")


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
    source_expectations: tuple[dict[str, object], ...] = ()


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


def _ascii_upper_with_source_indices(value: str) -> tuple[str, tuple[int, ...]]:
    normalized = []
    source_indices = []
    for index, character in enumerate(value):
        fragment = _ascii_upper(character)
        normalized.append(fragment)
        source_indices.extend(index for _ in fragment)
    return "".join(normalized), tuple(source_indices)


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
    source_start: int | None = None,
    requires_source_selection: bool = False,
    source_role: ProcessMetadataSourceRole = (
        ProcessMetadataSourceRole.UNKNOWN_SOURCE_CONTEXT
    ),
    derivation_authority: str = "",
    derivation_reference: str = "",
) -> FieldEvidence:
    normalized_span = _ascii_upper(" ".join(span.split()))
    matching_block = None
    if source_start is not None and page.blocks:
        cursor = 0
        for block in page.blocks:
            block_end = cursor + len(block.text)
            if cursor <= source_start < block_end:
                matching_block = block
                break
            cursor = block_end + 1
    elif source_start is None:
        matching_block = next(
            (
                block
                for block in page.blocks
                if normalized_span
                and normalized_span in _ascii_upper(" ".join(block.text.split()))
            ),
            None,
        )
    confidence = (
        matching_block.confidence
        if matching_block is not None
        else page.confidence
    )
    return FieldEvidence(
        workspace_id=workspace_id,
        document_id=document_id,
        field_name=field_name,
        extracted_value=value,
        source_page=page.number,
        extraction_method=(
            "LOCAL_OCR_V1"
            if page.extraction_mode is PageExtractionMode.OCR
            else "LOCAL_PDF_TEXT_V1"
        ),
        extraction_timestamp=extracted_at,
        source_filename=source_filename,
        normalized_text_span=" ".join(span.split())[:240],
        extraction_mode=page.extraction_mode,
        ocr_engine=page.engine if page.extraction_mode is PageExtractionMode.OCR else "",
        engine_version=page.engine_version,
        model_version=page.model_version,
        ocr_confidence=(
            confidence if page.extraction_mode is PageExtractionMode.OCR else None
        ),
        bounding_box=(
            matching_block.bounding_box if matching_block is not None else None
        ),
        source_text=span if requires_source_selection else "",
        source_start=(
            0
            if not requires_source_selection or source_start is None
            else source_start
        ),
        requires_source_selection=requires_source_selection,
        source_role=source_role,
        derivation_authority=derivation_authority,
        derivation_reference=derivation_reference,
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
        key = (
            ("candidate", _ascii_upper(" ".join(candidate.extracted_value.split())))
            if candidate.extracted_value
            else ("source", candidate.evidence_id)
        )
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


def _cnj_line_context(page: PdfTextPage, start: int, end: int) -> tuple[str, str]:
    line_start = page.text.rfind("\n", 0, start) + 1
    line_end = page.text.find("\n", end)
    if line_end < 0:
        line_end = len(page.text)
    return (
        _ascii_upper(page.text[line_start:line_end]),
        _ascii_upper(page.text[line_start:start]),
    )


def _rejects_primary_cnj(page: PdfTextPage, start: int, end: int) -> bool:
    line, _ = _cnj_line_context(page, start, end)
    line_start = page.text.rfind("\n", 0, start)
    preceding_lines = page.text[:line_start].splitlines() if line_start >= 0 else []
    preceding_line = next(
        (_ascii_upper(item) for item in reversed(preceding_lines) if item.strip()),
        "",
    )
    local_context = f"{preceding_line}\n{line}"
    return any(
        marker in local_context
        for marker in ("REFERENC", "RELACION", "VINCUL", "OUTRO FEITO", "ORIGEM")
    )


def _is_explicit_primary_cnj(page: PdfTextPage, start: int, end: int) -> bool:
    _, prefix = _cnj_line_context(page, start, end)
    if _rejects_primary_cnj(page, start, end):
        return False
    return re.fullmatch(
        r"(?:PROCESSO(?:\s+JUDICIAL)?|AUTOS)"
        r"(?:\s+(?:N|NUMERO)[O.]*)?\s*[:\-]?\s*$",
        prefix,
    ) is not None


def _has_primary_header_structure(page: PdfTextPage) -> bool:
    normalized = _ascii_upper(page.text)
    institutional_heading = any(
        marker in normalized
        for marker in (
            "PODER JUDICIARIO",
            "JUSTICA FEDERAL",
            "TRIBUNAL REGIONAL FEDERAL",
        )
    )
    process_structure = any(
        marker in normalized
        for marker in ("ORGAO JULGADOR", "POLO ATIVO", "POLO PASSIVO")
    )
    if not process_structure:
        process_structure = (
            "VARA FEDERAL" in normalized
            and bool(re.search(r"(?m)^\s*(?:AUTOR|AUTORA|REQUERENTE|EXEQUENTE)\s*:", normalized))
            and bool(re.search(r"(?m)^\s*(?:REU|REQUERIDO|REQUERIDA|EXECUTADO|EXECUTADA)\s*:", normalized))
        )
    return institutional_heading and process_structure


def _has_primary_cover_structure(page: PdfTextPage) -> bool:
    normalized = _ascii_upper(page.text)
    return (
        any(
            marker in normalized
            for marker in (
                "PODER JUDICIARIO",
                "JUSTICA FEDERAL",
                "TRIBUNAL REGIONAL FEDERAL",
            )
        )
        and any(marker in normalized for marker in ("PJE", "CAPA DO PROCESSO"))
    )


def _has_primary_document_structure(page: PdfTextPage) -> bool:
    normalized = _ascii_upper(page.text)
    return (
        "VARA FEDERAL" in normalized
        and bool(re.search(r"(?m)^\s*(?:AUTOR|AUTORA|REQUERENTE|EXEQUENTE)\s*:", normalized))
        and bool(re.search(r"(?m)^\s*(?:REU|REQUERIDO|REQUERIDA|EXECUTADO|EXECUTADA)\s*:", normalized))
    )


def _non_primary_heading_role(line: str) -> ProcessMetadataSourceRole | None:
    if re.fullmatch(
        r"(?:JURISPRUDENCIA(?:\s+REFERENCIADA)?|EMENTA|ACORDAO(?:\s+CITADO)?|PRECEDENTE)",
        line,
    ):
        return ProcessMetadataSourceRole.CITED_JURISPRUDENCE
    if re.fullmatch(r"ANEXO(?:\s+[A-Z0-9.-]+)?", line):
        return ProcessMetadataSourceRole.ANNEX_DOCUMENT
    if re.fullmatch(
        r"(?:PROCESSO|AUTOS|FEITO)\s+(?:REFERENCIADO|RELACIONADO|VINCULADO)",
        line,
    ):
        return ProcessMetadataSourceRole.REFERENCED_CASE
    return None


def _declared_non_primary_source_segments(
    page: PdfTextPage,
) -> tuple[tuple[int, ...], tuple[ProcessMetadataSourceRole, ...]]:
    starts = []
    roles = []
    offset = 0
    for raw_line in page.text.splitlines(keepends=True):
        role = _non_primary_heading_role(_ascii_upper(raw_line.strip()))
        if role is not None:
            starts.append(offset)
            roles.append(role)
        offset += len(raw_line)
    return tuple(starts), tuple(roles)


def _declared_non_primary_role_at(
    segments: tuple[tuple[int, ...], tuple[ProcessMetadataSourceRole, ...]],
    start: int,
) -> ProcessMetadataSourceRole | None:
    starts, roles = segments
    index = bisect_right(starts, start) - 1
    return None if index < 0 else roles[index]


def _source_role_for_cnj(
    page: PdfTextPage,
    start: int,
    end: int,
    *,
    declared_non_primary_segments: tuple[
        tuple[int, ...], tuple[ProcessMetadataSourceRole, ...]
    ],
) -> ProcessMetadataSourceRole:
    declared_non_primary_role = _declared_non_primary_role_at(
        declared_non_primary_segments, start
    )
    if declared_non_primary_role is not None:
        return declared_non_primary_role
    if _rejects_primary_cnj(page, start, end):
        return ProcessMetadataSourceRole.REFERENCED_CASE
    if not _is_explicit_primary_cnj(page, start, end):
        return ProcessMetadataSourceRole.UNKNOWN_SOURCE_CONTEXT
    if _has_primary_header_structure(page):
        return ProcessMetadataSourceRole.PRIMARY_PROCESS_HEADER
    if _has_primary_cover_structure(page):
        return ProcessMetadataSourceRole.PRIMARY_PROCESS_COVER
    if _has_primary_document_structure(page):
        return ProcessMetadataSourceRole.PRIMARY_PROCESS_DOCUMENT
    return ProcessMetadataSourceRole.UNKNOWN_SOURCE_CONTEXT


def _resolved_primary_cnj(
    candidates: list[_CnjCandidate],
    *,
    cnj_starts_by_page: dict[int, list[int]],
) -> tuple[ExtractedField, _CnjCandidate | None]:
    if not candidates:
        return ExtractedField(FieldExtractionState.NOT_FOUND, "", ()), None
    eligible_roles = {
        ProcessMetadataSourceRole.PRIMARY_PROCESS_COVER,
        ProcessMetadataSourceRole.PRIMARY_PROCESS_HEADER,
        ProcessMetadataSourceRole.PRIMARY_PROCESS_DOCUMENT,
    }
    strong_values = {
        candidate.number.canonical
        for candidate in candidates
        if candidate.source_role in eligible_roles
        and candidate.explicit_primary_anchor
        and not candidate.rejects_primary_anchor
    }
    unique_values = tuple(
        dict.fromkeys(candidate.number.canonical for candidate in candidates)
    )
    if not strong_values:
        return (
            ExtractedField(
                FieldExtractionState.AMBIGUOUS,
                "",
                tuple(
                    next(
                        candidate.evidence
                        for candidate in candidates
                        if candidate.number.canonical == value
                    )
                    for value in unique_values
                ),
            ),
            None,
        )
    if len(strong_values) > 1:
        return (
            ExtractedField(
                FieldExtractionState.CONFLICTING,
                "",
                tuple(
                    next(
                        candidate.evidence
                        for candidate in candidates
                        if candidate.number.canonical == value
                    )
                    for value in sorted(strong_values)
                ),
            ),
            None,
        )
    selected_value = next(iter(strong_values))
    selected = next(
        candidate
        for candidate in candidates
        if candidate.number.canonical == selected_value
        and candidate.source_role in eligible_roles
        and candidate.explicit_primary_anchor
        and not candidate.rejects_primary_anchor
    )
    if any(
        start < selected.start
        for start in cnj_starts_by_page.get(selected.page.number, [])
    ):
        return (
            ExtractedField(
                FieldExtractionState.AMBIGUOUS,
                "",
                tuple(
                    next(
                        candidate.evidence
                        for candidate in candidates
                        if candidate.number.canonical == value
                    )
                    for value in unique_values
                ),
            ),
            None,
        )
    return (
        ExtractedField(
            FieldExtractionState.CONFIDENT,
            selected.number.canonical,
            (selected.evidence,),
        ),
        selected,
    )


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
    candidates: dict[str, list[_FieldCandidate]] = {
        field: [] for field in PROCESS_METADATA_FIELDS
    }
    invalid_cnj: list[FieldEvidence] = []
    low_confidence: dict[str, list[_FieldCandidate]] = {
        field: [] for field in PROCESS_METADATA_FIELDS
    }
    cnj_candidates: list[_CnjCandidate] = []
    cnj_starts_by_page: dict[int, list[int]] = {}
    declared_non_primary_segments = {
        page.number: _declared_non_primary_source_segments(page)
        for page in text.pages
    }

    def add(
        field: str,
        value: str,
        page: PdfTextPage,
        span: str,
        *,
        source_start: int,
        prepend: bool = False,
    ) -> None:
        cleaned = " ".join(value.strip(" \t:-").split())
        if cleaned:
            evidence = _evidence(
                workspace_id=workspace_id,
                document_id=document_id,
                field_name=field,
                value=cleaned,
                page=page,
                extracted_at=extracted_at,
                source_filename=source_filename,
                span=span,
                source_start=source_start,
            )
            candidate = _FieldCandidate(evidence, page, source_start)
            target = (
                low_confidence[field]
                if page.extraction_mode is PageExtractionMode.OCR
                and (evidence.ocr_confidence or 0.0) < 0.75
                else candidates[field]
            )
            if prepend:
                target.insert(0, candidate)
            else:
                target.append(candidate)

    def add_unsegmented_source(
        field: str,
        page: PdfTextPage,
        span: str,
        *,
        source_start: int,
    ) -> None:
        if not span.strip():
            return
        evidence = _evidence(
            workspace_id=workspace_id,
            document_id=document_id,
            field_name=field,
            value="",
            page=page,
            extracted_at=extracted_at,
            source_filename=source_filename,
            span=span,
            source_start=source_start,
            requires_source_selection=True,
        )
        candidate = _FieldCandidate(evidence, page, source_start)
        target = (
            low_confidence[field]
            if page.extraction_mode is PageExtractionMode.OCR
            and (evidence.ocr_confidence or 0.0) < 0.75
            else candidates[field]
        )
        target.append(candidate)

    def add_cnj(
        cnj: CnjNumber,
        page: PdfTextPage,
        span: str,
        start: int,
        end: int,
    ) -> None:
        source_role = _source_role_for_cnj(
            page,
            start,
            end,
            declared_non_primary_segments=declared_non_primary_segments[page.number],
        )
        evidence = _evidence(
            workspace_id=workspace_id,
            document_id=document_id,
            field_name="numero_processo",
            value=cnj.canonical,
            page=page,
            extracted_at=extracted_at,
            source_filename=source_filename,
            span=span,
            source_start=start,
            source_role=source_role,
        )
        add(
            "ramo_justica",
            cnj.justice_branch,
            page,
            span,
            source_start=start,
        )
        federal_region = _FEDERAL_TRIBUNAL_REGIONS.get(cnj.tribunal_code)
        if cnj.justice_segment == "4" and federal_region is not None:
            add(
                "tribunal",
                f"Tribunal Regional Federal da {federal_region}ª Região",
                page,
                span,
                source_start=start,
            )
        if (
            page.extraction_mode is PageExtractionMode.OCR
            and (evidence.ocr_confidence or 0.0) < 0.75
        ):
            low_confidence["numero_processo"].append(
                _FieldCandidate(evidence, page, start)
            )
            return
        cnj_candidates.append(
            _CnjCandidate(
                cnj,
                evidence,
                page,
                span,
                start,
                end,
                _is_explicit_primary_cnj(page, start, end),
                _rejects_primary_cnj(page, start, end),
                source_role,
            )
        )

    for page in text.pages:
        if page.extraction_mode is PageExtractionMode.OCR:
            normalized_page, ascii_source_indices = _ascii_upper_with_source_indices(
                page.text
            )
        else:
            normalized_page = _ascii_upper(page.text)
            ascii_source_indices = ()
        for cnj_match in _CNJ_PATTERN.finditer(page.text):
            raw = cnj_match.group(0)
            cnj_starts_by_page.setdefault(page.number, []).append(cnj_match.start())
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
                        source_start=cnj_match.start(),
                    )
                )
                continue
            add_cnj(cnj, page, raw, cnj_match.start(), cnj_match.end())

        if page.extraction_mode is PageExtractionMode.OCR:
            for ocr_match in _OCR_CNJ_PATTERN.finditer(normalized_page):
                raw = ocr_match.group(0)
                if _CNJ_PATTERN.fullmatch(raw):
                    continue
                source_start = ascii_source_indices[ocr_match.start()]
                source_end = ascii_source_indices[ocr_match.end() - 1] + 1
                cnj_starts_by_page.setdefault(page.number, []).append(source_start)
                groups = tuple(group.translate(_OCR_DIGIT_CONFUSIONS) for group in ocr_match.groups())
                normalized_cnj = (
                    f"{groups[0]}-{groups[1]}.{groups[2]}."
                    f"{groups[3]}.{groups[4]}.{groups[5]}"
                )
                try:
                    cnj = validate_cnj_number(normalized_cnj)
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
                            source_start=source_start,
                        )
                    )
                    continue
                add_cnj(cnj, page, raw, source_start, source_end)

        for party_row in parse_pje_party_table(page.text).rows:
            add(
                (
                    "parte_requerente"
                    if party_row.pole is PjePartyPole.ACTIVE
                    else "parte_requerida"
                ),
                party_row.name,
                page,
                party_row.source_line,
                source_start=party_row.source_start,
            )

        line_start = 0
        for raw_line in page.text.splitlines(keepends=True):
            line = raw_line.rstrip("\r\n")
            normalized_line = _ascii_upper(line)
            federal_heading_match = re.search(
                r"\bJUSTICA\s+FEDERAL\s+DA\s+(\d{1,2})(?:A)?\s+REGIAO\b",
                normalized_line,
            )
            if federal_heading_match:
                region = int(federal_heading_match.group(1))
                if region in _FEDERAL_TRIBUNAL_REGIONS.values():
                    add(
                        "tribunal",
                        f"Tribunal Regional Federal da {region}\u00aa Regi\u00e3o",
                        page,
                        line,
                        source_start=line_start,
                    )

            tribunal_match = re.search(
                r"TRIBUNAL\s+REGIONAL\s+FEDERAL\s+DA\s+(\d{1,2})(?:A)?\s+REGIAO",
                normalized_line,
            )
            if tribunal_match:
                region = int(tribunal_match.group(1))
                if region in _FEDERAL_TRIBUNAL_REGIONS.values():
                    add(
                        "tribunal",
                        f"Tribunal Regional Federal da {region}ª Região",
                        page,
                        line,
                        source_start=line_start,
                    )

            unit_match = re.search(r"\b(\d{1,3})\s*(?:A)?\s+VARA(?:\s+FEDERAL)?\b", normalized_line)
            if unit_match:
                suffix = " Federal" if "FEDERAL" in unit_match.group(0) else ""
                add(
                    "vara",
                    f"{int(unit_match.group(1))}ª Vara{suffix}",
                    page,
                    line,
                    source_start=line_start,
                )

            judging_body_match = re.search(
                r"\bORGAO\s+JULGADOR\s*:\s*.+?\b([A-Z]{2})\s*$",
                normalized_line,
            )
            if (
                judging_body_match
                and judging_body_match.group(1) in _BRAZILIAN_UF_CODES
            ):
                add(
                    "uf",
                    judging_body_match.group(1),
                    page,
                    line,
                    source_start=line_start,
                )

            location_match = re.search(
                r"(?:SUBSECAO\s+JUDICIARIA|COMARCA|MUNICIPIO)(?:\s+DE)?\s*[:\-]?\s*([A-Z][A-Z '\-]{1,80}?)\s*/\s*([A-Z]{2})\b",
                normalized_line,
            )
            if location_match:
                add(
                    "uf",
                    location_match.group(2),
                    page,
                    line,
                    source_start=line_start,
                )

            party_match = re.match(
                r"\s*(AUTOR(?:A)?|REQUERENTE|EXEQUENTE|REQUERIDO(?:A)?|REU|EXECUTADO(?:A)?)\s*:\s*(.+?)\s*$",
                normalized_line,
            )
            if party_match:
                field = (
                    "parte_requerente"
                    if party_match.group(1) in {"AUTOR", "AUTORA", "REQUERENTE", "EXEQUENTE"}
                    else "parte_requerida"
                )
                add_unsegmented_source(
                    field,
                    page,
                    line,
                    source_start=line_start,
                )
            line_start += len(raw_line)

    number_field, primary_candidate = _resolved_primary_cnj(
        cnj_candidates,
        cnj_starts_by_page=cnj_starts_by_page,
    )
    number_low_confidence = tuple(
        candidate.evidence for candidate in low_confidence["numero_processo"]
    )
    if primary_candidate is None and number_low_confidence:
        number_field = ExtractedField(
            FieldExtractionState.AMBIGUOUS,
            "",
            number_field.evidence + number_low_confidence,
        )
    if primary_candidate is not None:
        primary_cnj = primary_candidate.number
        primary_section_end = min(
            (
                start
                for start in cnj_starts_by_page.get(primary_candidate.page.number, [])
                if start > primary_candidate.start
            ),
            default=len(primary_candidate.page.text),
        )
        add(
            "ramo_justica",
            primary_cnj.justice_branch,
            primary_candidate.page,
            primary_candidate.span,
            source_start=primary_candidate.start,
            prepend=True,
        )
        federal_region = _FEDERAL_TRIBUNAL_REGIONS.get(primary_cnj.tribunal_code)
        if primary_cnj.justice_segment == "4" and federal_region is not None:
            add(
                "tribunal",
                f"Tribunal Regional Federal da {federal_region}ª Região",
                primary_candidate.page,
                primary_candidate.span,
                source_start=primary_candidate.start,
                prepend=True,
            )
        for field in PROCESS_METADATA_FIELDS:
            if field == "numero_processo":
                continue
            source_role = (
                ProcessMetadataSourceRole.PRIMARY_PARTY_STRUCTURE
                if field in {"parte_requerente", "parte_requerida"}
                else primary_candidate.source_role
            )
            candidates[field] = [
                replace(
                    candidate,
                    evidence=replace(candidate.evidence, source_role=source_role),
                )
                for candidate in candidates[field]
                if candidate.page.number == primary_candidate.page.number
                and 0 <= candidate.start < primary_section_end
            ]
            low_confidence[field] = [
                replace(
                    candidate,
                    evidence=replace(candidate.evidence, source_role=source_role),
                )
                for candidate in low_confidence[field]
                if candidate.page.number == primary_candidate.page.number
                and 0 <= candidate.start < primary_section_end
            ]
        primary_uf = next(
            (
                candidate.evidence.extracted_value
                for candidate in candidates["uf"]
                if candidate.evidence.extracted_value in _BRAZILIAN_UF_CODES
            ),
            "",
        )
        unit_candidate = next(
            (
                candidate
                for candidate in candidates["vara"]
                if re.fullmatch(r"(\d{1,3})ª Vara Federal", candidate.evidence.extracted_value)
            ),
            None,
        )
        federal_region = _FEDERAL_TRIBUNAL_REGIONS.get(primary_cnj.tribunal_code)
        if primary_uf and unit_candidate is not None and federal_region is not None:
            unit_number = int(
                re.fullmatch(
                    r"(\d{1,3})ª Vara Federal", unit_candidate.evidence.extracted_value
                ).group(1)
            )
            location = resolve_judicial_unit(
                tribunal=f"TRF{federal_region}",
                uf=primary_uf,
                unit_type="VARA_FEDERAL",
                unit_number=unit_number,
            )
            if location is not None:
                for field, value in (
                    ("municipio_sede", location.municipio_sede),
                    ("subsecao_judiciaria", location.subsecao_judiciaria),
                    ("comarca_municipio", location.municipio_sede),
                ):
                    candidates[field] = [
                        _FieldCandidate(
                            replace(
                                unit_candidate.evidence,
                                field_name=field,
                                extracted_value=value,
                                source_role=(
                                    primary_candidate.source_role
                                ),
                                derivation_authority=location.authority,
                                derivation_reference=location.source_reference,
                            ),
                            unit_candidate.page,
                            unit_candidate.start,
                        )
                    ]
    else:
        for field in PROCESS_METADATA_FIELDS:
            if field == "numero_processo":
                continue
            low_confidence[field].extend(candidates[field])
            candidates[field] = []

    fields = {
        field: _resolved_field(
            [candidate.evidence for candidate in candidates[field]],
            ambiguous=(
                not candidates[field]
                and bool(low_confidence[field] or (field == "numero_processo" and invalid_cnj))
            ),
            combined=field in {"parte_requerente", "parte_requerida"},
        )
        for field in PROCESS_METADATA_FIELDS
    }
    fields["numero_processo"] = number_field
    if invalid_cnj and not cnj_candidates and not low_confidence["numero_processo"]:
        fields["numero_processo"] = ExtractedField(
            FieldExtractionState.AMBIGUOUS,
            "",
            tuple(invalid_cnj),
        )
    for field in PROCESS_METADATA_FIELDS:
        if field == "numero_processo":
            continue
        if not candidates[field] and low_confidence[field]:
            fields[field] = ExtractedField(
                FieldExtractionState.AMBIGUOUS,
                "",
                tuple(candidate.evidence for candidate in low_confidence[field]),
            )
    fields = {
        name: (
            ExtractedField(FieldExtractionState.AMBIGUOUS, "", field.evidence)
            if field.state is FieldExtractionState.CONFIDENT
            else field
        )
        for name, field in fields.items()
    }
    return DocumentProcessMetadata(
        workspace_id=workspace_id,
        document_id=document_id,
        source_filename=source_filename,
        text_state=text.state,
        fields=MappingProxyType(fields),
        document_sha256=text.document_sha256,
        page_evidence=tuple(
            DocumentPageEvidence(
                page.number,
                page.extraction_mode,
                page.engine,
                page.engine_version,
                page.model_version,
                page.config_version,
                page.confidence,
                tuple(
                    block.bounding_box
                    for block in page.blocks
                    if block.bounding_box is not None
                ),
                page.processing_status,
            )
            for page in text.pages
        ),
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
    elif (
        all(field.state is FieldExtractionState.CONFIDENT for field in fields.values())
        and all(
            document.text_state is PdfTextExtractionState.AVAILABLE
            for document in documents
        )
    ):
        state = "EXTRACTED"
    else:
        state = "PARTIAL"
    return ProcessMetadataAggregate(workspace_id, state, MappingProxyType(fields))


def document_metadata_payload(document: DocumentProcessMetadata) -> dict[str, object]:
    if type(document) is not DocumentProcessMetadata:
        raise TypeError("extração documental inválida")
    return {
        "schema_version": 6,
        "workspace_id": str(document.workspace_id),
        "document_id": str(document.document_id),
        "document_sha256": document.document_sha256,
        "source_filename": document.source_filename,
        "text_state": document.text_state.value,
        "page_evidence": [
            {
                "workspace_id": str(document.workspace_id),
                "document_id": str(document.document_id),
                "document_sha256": document.document_sha256,
                "page_number": page.page_number,
                "extraction_mode": page.extraction_mode.value,
                "engine": page.engine,
                "engine_version": page.engine_version,
                "model_version": page.model_version,
                "config_version": page.config_version,
                "confidence": page.confidence,
                "bounding_boxes": [
                    list(box) for box in page.bounding_boxes
                ],
                "processing_status": page.processing_status.value,
            }
            for page in document.page_evidence
        ],
        "fields": {
            name: {
                "state": field.state.value,
                "value": field.value,
                "evidence": [item.as_dict() for item in field.evidence],
            }
            for name, field in document.fields.items()
        },
    }


def document_metadata_from_payload(
    value: object, *, legacy_document_sha256: str = ""
) -> DocumentProcessMetadata:
    payload = thaw_payload(value)
    if type(payload) is not dict or payload.get("schema_version") not in {1, 2, 3, 4, 5, 6}:
        raise ValueError("extração documental persistida inválida")
    schema_version = payload["schema_version"]
    expected_keys = {
        "schema_version",
        "workspace_id",
        "document_id",
        "source_filename",
        "text_state",
        "fields",
    }
    if schema_version in {2, 3, 4, 5, 6}:
        expected_keys |= {"document_sha256", "page_evidence"}
    if set(payload) != expected_keys:
        raise ValueError("extração documental persistida inválida")
    workspace_id = WorkspaceId.parse(payload["workspace_id"])
    document_id = PrivateContentId.parse(payload["document_id"])
    source_filename = _filename(payload["source_filename"])
    text_state = PdfTextExtractionState(payload["text_state"])
    document_sha256 = payload.get("document_sha256", legacy_document_sha256)
    if (
        type(document_sha256) is not str
        or len(document_sha256) != 64
        or any(character not in "0123456789abcdef" for character in document_sha256)
    ):
        raise ValueError("checksum da extração persistida inválido")
    raw_pages = payload.get("page_evidence", [])
    if type(raw_pages) is not list:
        raise ValueError("evidência de página persistida inválida")
    pages = []
    page_keys = {
        "workspace_id",
        "document_id",
        "document_sha256",
        "page_number",
        "extraction_mode",
        "engine",
        "engine_version",
        "model_version",
        "config_version",
        "confidence",
        "bounding_boxes",
        "processing_status",
    }
    for raw_page in raw_pages:
        if type(raw_page) is not dict or set(raw_page) != page_keys:
            raise ValueError("evidência de página persistida inválida")
        if (
            raw_page["workspace_id"] != str(workspace_id)
            or raw_page["document_id"] != str(document_id)
            or raw_page["document_sha256"] != document_sha256
            or type(raw_page["bounding_boxes"]) is not list
        ):
            raise ValueError("identidade da página persistida diverge")
        page = DocumentPageEvidence(
            raw_page["page_number"],
            PageExtractionMode(raw_page["extraction_mode"]),
            raw_page["engine"],
            raw_page["engine_version"],
            raw_page["model_version"],
            raw_page["config_version"],
            raw_page["confidence"],
            tuple(tuple(box) for box in raw_page["bounding_boxes"]),
            PageProcessingStatus(raw_page["processing_status"]),
        )
        pages.append(page)
    raw_fields = payload["fields"]
    expected_field_names = (
        set(PROCESS_METADATA_FIELDS)
        if schema_version == 6
        else set(_LEGACY_PROCESS_METADATA_FIELDS)
    )
    if type(raw_fields) is not dict or set(raw_fields) != expected_field_names:
        raise ValueError("campos de extração persistidos inválidos")
    fields = {}
    for name in expected_field_names:
        raw = raw_fields[name]
        if type(raw) is not dict or set(raw) != {"state", "value", "evidence"}:
            raise ValueError("campo de extração persistido inválido")
        if type(raw["value"]) is not str or type(raw["evidence"]) is not list:
            raise ValueError("campo de extração persistido inválido")
        evidence = []
        for item in raw["evidence"]:
            legacy_evidence_keys = {
                "workspace_id",
                "document_id",
                "field_name",
                "extracted_value",
                "source_page",
                "extraction_method",
                "extraction_timestamp",
                "source_filename",
                "normalized_text_span",
            }
            v2_evidence_keys = legacy_evidence_keys | {
                "extraction_mode",
                "ocr_engine",
                "engine_version",
                "model_version",
                "ocr_confidence",
                "bounding_box",
            }
            v5_evidence_keys = v2_evidence_keys | {
                "evidence_id",
                "source_text",
                "source_start",
                "requires_source_selection",
            }
            v6_evidence_keys = v5_evidence_keys | {
                "source_role",
                "derivation_authority",
                "derivation_reference",
            }
            expected_evidence_keys = (
                legacy_evidence_keys
                if schema_version == 1
                else v6_evidence_keys
                if schema_version == 6
                else v5_evidence_keys
                if schema_version == 5
                else v2_evidence_keys
            )
            if type(item) is not dict or set(item) != expected_evidence_keys:
                raise ValueError("proveniência persistida inválida")
            raw_box = item.get("bounding_box")
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
                extraction_mode=PageExtractionMode(
                    item.get("extraction_mode", PageExtractionMode.NATIVE_TEXT)
                ),
                ocr_engine=item.get("ocr_engine", ""),
                engine_version=item.get("engine_version", ""),
                model_version=item.get("model_version", ""),
                ocr_confidence=item.get("ocr_confidence"),
                bounding_box=tuple(raw_box) if raw_box is not None else None,
                source_text=item.get("source_text", ""),
                source_start=item.get("source_start", 0),
                requires_source_selection=item.get(
                    "requires_source_selection", False
                ),
                source_role=ProcessMetadataSourceRole(
                    item.get("source_role", "UNKNOWN_SOURCE_CONTEXT")
                ),
                derivation_authority=item.get("derivation_authority", ""),
                derivation_reference=item.get("derivation_reference", ""),
            )
            persisted_evidence_id = (
                record.evidence_id
                if schema_version == 6
                else record.legacy_v5_evidence_id
            )
            if schema_version in {5, 6} and persisted_evidence_id != item["evidence_id"]:
                raise ValueError("identidade da evidência persistida diverge")
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
    for name in set(PROCESS_METADATA_FIELDS) - set(fields):
        fields[name] = ExtractedField(FieldExtractionState.NOT_FOUND, "", ())
    if schema_version == 1 and text_state is PdfTextExtractionState.AVAILABLE:
        text_state = PdfTextExtractionState.PARTIAL
    if (
        schema_version == 1
        and text_state in {
            PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE,
            PdfTextExtractionState.ERROR,
        }
        and any(field.evidence for field in fields.values())
    ):
        raise ValueError("estado legado diverge da proveniência de campo")
    if schema_version < 4:
        fields = {
            name: (
                ExtractedField(FieldExtractionState.AMBIGUOUS, "", field.evidence)
                if field.state is FieldExtractionState.CONFIDENT
                else field
            )
            for name, field in fields.items()
        }
    elif any(
        field.state is FieldExtractionState.CONFIDENT for field in fields.values()
    ):
        raise ValueError("schema atual não admite confiança automática")
    document = DocumentProcessMetadata(
        workspace_id,
        document_id,
        source_filename,
        text_state,
        MappingProxyType(fields),
        document_sha256,
        tuple(pages),
    )
    if schema_version in {2, 3, 4, 5, 6}:
        page_numbers = tuple(page.page_number for page in document.page_evidence)
        if page_numbers and page_numbers != tuple(range(1, len(page_numbers) + 1)):
            raise ValueError("cobertura de páginas persistida inválida")
        textual_pages = {
            page.page_number: page
            for page in document.page_evidence
            if page.processing_status in {
                PageProcessingStatus.AVAILABLE,
                PageProcessingStatus.TRUNCATED,
            }
        }
        incomplete_pages = tuple(
            page
            for page in document.page_evidence
            if page.processing_status is not PageProcessingStatus.AVAILABLE
        )
        if document.text_state is PdfTextExtractionState.AVAILABLE and (
            not textual_pages or incomplete_pages
        ):
            raise ValueError("estado disponível diverge da evidência de página")
        if document.text_state is PdfTextExtractionState.PARTIAL and (
            not textual_pages or not incomplete_pages
        ):
            raise ValueError("estado parcial diverge da evidência de página")
        if (
            document.text_state is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
            and textual_pages
        ):
            raise ValueError("estado indisponível diverge da evidência de página")
        if document.text_state is PdfTextExtractionState.ERROR and document.page_evidence:
            raise ValueError("estado de erro diverge da evidência de página")
    else:
        textual_pages = {}
    for name, field in document.fields.items():
        if field.state is FieldExtractionState.CONFIDENT and (
            not field.value.strip() or not field.evidence
        ):
            raise ValueError(f"campo confiante sem proveniência: {name}")
        if field.state is FieldExtractionState.CONFIDENT:
            expected_value = (
                "; ".join(item.extracted_value for item in field.evidence)
                if name in {"parte_requerente", "parte_requerida"}
                else field.evidence[0].extracted_value
            )
            if (
                field.value != expected_value
                or (
                    name not in {"parte_requerente", "parte_requerida"}
                    and len(field.evidence) != 1
                )
            ):
                raise ValueError(f"valor do campo diverge da proveniência: {name}")
        if field.state is FieldExtractionState.NOT_FOUND and (
            field.value or field.evidence
        ):
            raise ValueError(f"campo ausente possui evidência: {name}")
        if field.state in {
            FieldExtractionState.AMBIGUOUS,
            FieldExtractionState.CONFLICTING,
        } and (field.value or not field.evidence):
            raise ValueError(f"campo inconclusivo sem proveniência: {name}")
        for evidence in field.evidence:
            if evidence.source_filename != document.source_filename:
                raise ValueError("arquivo da proveniência diverge do documento")
            if schema_version in {2, 3, 4, 5, 6}:
                page = textual_pages.get(evidence.source_page)
                if (
                    page is None
                    or evidence.extraction_mode is not page.extraction_mode
                    or (
                        evidence.extraction_mode is PageExtractionMode.OCR
                        and (
                            evidence.ocr_engine != page.engine
                            or evidence.engine_version != page.engine_version
                            or evidence.model_version != page.model_version
                            or (
                                evidence.bounding_box is not None
                                and evidence.bounding_box not in page.bounding_boxes
                            )
                        )
                    )
                ):
                    raise ValueError("proveniência de campo diverge da página")
    return document


def review_dto(review: ProcessMetadataReview) -> dict[str, object]:
    return {
        "workspace_id": str(review.workspace_id),
        "state": review.state,
        "confirmed_revision": review.confirmed_revision,
        "extraction_fingerprint": review.extraction_fingerprint,
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
