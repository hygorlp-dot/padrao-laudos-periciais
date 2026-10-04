"""Classificação do número do processo principal entre os números dos autos (#286).

Os autos citam muitos números CNJ: o do próprio processo, precedentes
(AC, REsp, Tema...), processos relacionados ou de origem. Contar ocorrências
não distingue um do outro -- um precedente repetido vinte vezes continua sendo
um precedente. Aqui cada ocorrência é classificada pela ESTRUTURA onde está:

1. capa PJe com o rótulo "Número:"/"Processo:" (nível 1);
2. "PROCESSO:" no cabeçalho de uma peça judicial (nível 2);
3. linha com marcador de citação (Rel., Des., STJ, AC, Apelação...) -> citado;
4. relação declarada (relacionado, vinculado, origem, dependência) -> relacionado.

Um único valor com evidência de nível 1 ou 2 é o número principal proposto.
Dois valores primários diferentes, ou nenhum, deixam o principal sem
resolução: nada é inventado e nada é salvo; o perito decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .process_metadata import (
    _CNJ_PATTERN,
    _OCR_CNJ_PATTERN,
    _OCR_DIGIT_CONFUSIONS,
    _ascii_upper_with_source_indices,
    validate_cnj_number,
)


class ProcessNumberClass(StrEnum):
    PRIMARY = "PRIMARY"
    CITED_CASE = "CITED_CASE"
    RELATED_CASE = "RELATED_CASE"
    UNKNOWN = "UNKNOWN"


class OccurrenceContext(StrEnum):
    PJE_COVER = "PJE_COVER"
    JUDICIAL_HEADER = "JUDICIAL_HEADER"
    CITATION = "CITATION"
    DECLARED_RELATION = "DECLARED_RELATION"
    UNQUALIFIED = "UNQUALIFIED"


class PrimaryResolution(StrEnum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    NOT_FOUND = "NOT_FOUND"


class UnresolvedReason(StrEnum):
    CONFLICTING_PRIMARY_SOURCES = "CONFLICTING_PRIMARY_SOURCES"
    NO_PRIMARY_SOURCE = "NO_PRIMARY_SOURCE"
    READING_INCOMPLETE = "READING_INCOMPLETE"
    SOURCES_UNAVAILABLE = "SOURCES_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ProcessNumberOccurrence:
    value: str
    content_id: str
    filename: str
    page: int
    source_start: int
    source_end: int
    excerpt: str
    extraction_mode: str
    context: OccurrenceContext
    logical_document_id: str | None


@dataclass(frozen=True, slots=True)
class ProcessNumberCandidate:
    value: str
    classification: ProcessNumberClass
    # Há evidência estrutural de número principal (nível 1 ou 2), mesmo que o
    # principal tenha ficado sem resolução por conflito.
    primary_evidence: bool
    occurrence_count: int
    document_count: int
    occurrences: tuple[ProcessNumberOccurrence, ...]


@dataclass(frozen=True, slots=True)
class ProcessNumberClassification:
    resolution: PrimaryResolution
    primary_value: str | None
    # "HIGH": capa PJe, ou cabeçalho judicial em mais de uma página.
    # "MEDIUM": um único cabeçalho judicial.
    confidence: str | None
    unresolved_reason: UnresolvedReason | None
    candidates: tuple[ProcessNumberCandidate, ...]
    pending_documents: tuple[str, ...]
    unread_pages: tuple[tuple[str, int], ...]
    # Números com forma CNJ e dígito verificador inválido (truncados, OCR).
    invalid_occurrences: tuple[tuple[str, int], ...]


_EXCERPT_LIMIT = 240
_OCR_MIN_CONFIDENCE = 0.75
_UNREAD_STATUSES = frozenset({"OCR_FAILED", "NOT_PROCESSED", "TRUNCATED"})

# Rótulo que, sozinho antes do número, o declara como o número DESTES autos.
_PRIMARY_LABEL = re.compile(
    r"^[\s:;,.|\-]*"
    r"(?:"
    r"(?:N(?:UMERO|O|[.°])\s*\.?\s*(?:DO\s+)?)?PROCESSO(?:\s+JUDICIAL)?(?:\s+ELETRONICO)?"
    r"|AUTOS"
    r"|NUMERO(?:\s+DO\s+PROCESSO)?"
    r")"
    r"(?:\s*(?:N(?:UMERO|O|[.°])|NUMERO)\s*\.?)?"
    r"\s*[:\-]?\s*$"
)
# Marcadores de citação de outro julgado. Palavras inteiras, na linha do número.
_CITATION = re.compile(
    r"(?<![A-Z0-9])(?:"
    r"AC|APELACAO|APELACAO\s+CIVEL|RESP|ARESP|AGINT|AGRG|EDCL|AGRAVO\s+INTERNO|"
    r"TEMA|REL|RELATOR|RELATORA|DES|DESEMBARGADOR|DESEMBARGADORA|MIN|MINISTRO|MINISTRA|"
    r"STJ|STF|TNU|TRF\s*\d?|TJ[A-Z]{2}|JULGADO\s+EM|JULGAMENTO\s+EM|DJE|DJ|"
    r"PRECEDENTES?|JURISPRUDENCIA|EMENTA|ACORDAO|NESSE\s+SENTIDO|NO\s+MESMO\s+SENTIDO|"
    r"VEJA-SE|CONFIRA-SE|CF\."
    r")(?![A-Z0-9])"
)
# Relação declarada com outro processo.
_RELATION = re.compile(
    r"(?<![A-Z0-9])(?:"
    r"(?:PROCESSOS?|AUTOS|FEITOS?)\s+(?:RELACIONADOS?|VINCULADOS?|REFERENCIADOS?|ASSOCIADOS?|"
    r"DE\s+ORIGEM|ORIGINARIOS?|PRINCIPAIS|APENSOS?|APENSADOS?)|"
    r"REFERENCIA(?:\s+DOCUMENTAL)?|DEPENDENCIA|PREVENCAO|PREVENTO|"
    r"OUTRO\s+(?:PROCESSO|FEITO)|ANEXO\s+DE\s+OUTRO\s+FEITO|APENSO|APENSADO"
    r")(?![A-Z0-9])"
)
# Título de seção que abre jurisprudência citada até o fim da página.
_CITED_SECTION = re.compile(
    r"^\s*(?:JURISPRUDENCIA(?:\s+\w+)?|PRECEDENTES?|EMENTA|ACORDAO(?:\s+CITADO)?)\s*:?\s*$"
)
_INSTITUTIONAL = ("PODER JUDICIARIO", "JUSTICA FEDERAL", "TRIBUNAL REGIONAL FEDERAL", "TRIBUNAL DE JUSTICA", "JUSTICA DO TRABALHO")
_JUDICIAL_STRUCTURE = re.compile(
    r"(?m)^\s*(?:ORGAO\s+JULGADOR|POLO\s+ATIVO|POLO\s+PASSIVO|CLASSE(?:\s+JUDICIAL)?\s*:"
    r"|(?:AUTOR|AUTORA|REQUERENTE|EXEQUENTE|REU|REQUERIDO|REQUERIDA|EXECUTADO|EXECUTADA)\s*:)"
)


def _is_pje_cover(normalized_page: str) -> bool:
    return "PROCESSO JUDICIAL ELETRONICO" in normalized_page or (
        re.search(r"(?<![A-Z])PJE(?![A-Z])", normalized_page) is not None
        and any(marker in normalized_page for marker in _INSTITUTIONAL)
    )


def _is_judicial_piece(normalized_page: str) -> bool:
    return (
        any(marker in normalized_page for marker in _INSTITUTIONAL)
        or re.search(r"\bVARA\b|\bJUIZADO\b", normalized_page) is not None
    ) and _JUDICIAL_STRUCTURE.search(normalized_page) is not None


def _page_occurrences(page_text: str, ocr: bool):
    """(valor bruto normalizado, início, fim) na página, sem sobreposição."""
    normalized, indices = _ascii_upper_with_source_indices(page_text)
    found = []
    taken: list[tuple[int, int]] = []
    for match in _CNJ_PATTERN.finditer(page_text):
        found.append((match.group(0), match.start(), match.end()))
        taken.append((match.start(), match.end()))
    if ocr:
        for match in _OCR_CNJ_PATTERN.finditer(normalized):
            start = indices[match.start()]
            end = indices[match.end() - 1] + 1
            if any(start < other_end and other_start < end for other_start, other_end in taken):
                continue
            groups = tuple(group.translate(_OCR_DIGIT_CONFUSIONS) for group in match.groups())
            found.append((f"{groups[0]}-{groups[1]}.{groups[2]}.{groups[3]}.{groups[4]}.{groups[5]}", start, end))
    return sorted(found, key=lambda item: item[1])


def _line_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return line_start, len(text) if line_end < 0 else line_end


def _upper(value: str) -> str:
    return _ascii_upper_with_source_indices(value)[0]


def _context(page_text: str, start: int, end: int, *, cover: bool, judicial: bool, cited_from: int | None) -> OccurrenceContext:
    line_start, line_end = _line_bounds(page_text, start, end)
    prefix = _upper(page_text[line_start:start])
    line = _upper(page_text[line_start:line_end])
    previous_end = line_start - 1
    previous = ""
    while previous_end > 0 and not previous.strip():
        previous_start = page_text.rfind("\n", 0, previous_end) + 1
        previous = page_text[previous_start:previous_end]
        previous_end = previous_start - 1
    previous = _upper(previous).strip()
    if _RELATION.search(prefix) or (previous.endswith(":") and _RELATION.search(previous)):
        return OccurrenceContext.DECLARED_RELATION
    labelled = _PRIMARY_LABEL.fullmatch(prefix) is not None
    # Na capa PJe a linha "Número: X" é a identidade do processo; a classe
    # processual ("Apelação Cível") pode estar na mesma linha sem ser citação.
    if cover and labelled and cited_from is None:
        return OccurrenceContext.PJE_COVER
    if cited_from is not None and start >= cited_from:
        return OccurrenceContext.CITATION
    if _CITATION.search(line):
        return OccurrenceContext.CITATION
    if judicial and labelled:
        return OccurrenceContext.JUDICIAL_HEADER
    return OccurrenceContext.UNQUALIFIED


def _cited_section_start(page_text: str) -> int | None:
    offset = 0
    for raw_line in page_text.splitlines(keepends=True):
        if _CITED_SECTION.fullmatch(_upper(raw_line.rstrip("\r\n"))):
            return offset
        offset += len(raw_line)
    return None


def _excerpt(page_text: str, start: int, end: int) -> str:
    line_start, line_end = _line_bounds(page_text, start, end)
    return " ".join(page_text[line_start:line_end].split())[:_EXCERPT_LIMIT]


_PRIMARY_CONTEXTS = frozenset({OccurrenceContext.PJE_COVER, OccurrenceContext.JUDICIAL_HEADER})


def classify_process_numbers(documents) -> ProcessNumberClassification:
    occurrences: list[ProcessNumberOccurrence] = []
    pending: list[str] = []
    unread: list[tuple[str, int]] = []
    invalid: list[tuple[str, int]] = []
    for document in documents:
        if document.reading_pending:
            pending.append(document.filename)
            continue
        for page in document.pages:
            if document.excluded(page.number):
                continue
            if page.processing_status.value in _UNREAD_STATUSES:
                unread.append((document.filename, page.number))
            mode = page.extraction_mode.value
            if mode not in ("NATIVE_TEXT", "OCR") or not page.text:
                continue
            ocr = mode == "OCR"
            # OCR de baixa confiança é mostrado, mas nunca sustenta o principal.
            weak = ocr and (page.confidence is None or page.confidence < _OCR_MIN_CONFIDENCE)
            normalized_page = _upper(page.text)
            cover = _is_pje_cover(normalized_page)
            judicial = _is_judicial_piece(normalized_page)
            cited_from = _cited_section_start(page.text)
            logical = document.logical_document_for(page.number)
            for raw, start, end in _page_occurrences(page.text, ocr):
                try:
                    value = validate_cnj_number(raw).canonical
                except ValueError:
                    invalid.append((document.filename, page.number))
                    continue
                context = _context(page.text, start, end, cover=cover, judicial=judicial, cited_from=cited_from)
                if weak and context in _PRIMARY_CONTEXTS:
                    context = OccurrenceContext.UNQUALIFIED
                occurrences.append(ProcessNumberOccurrence(
                    value, document.content_id, document.filename, page.number, start, end,
                    _excerpt(page.text, start, end), mode, context,
                    logical.document_id if logical is not None else None,
                ))
    return _resolve(occurrences, tuple(pending), tuple(unread), tuple(dict.fromkeys(invalid)))


def _resolve(occurrences, pending, unread, invalid) -> ProcessNumberClassification:
    by_value: dict[str, list[ProcessNumberOccurrence]] = {}
    for item in occurrences:
        by_value.setdefault(item.value, []).append(item)
    cover_values = {value for value, items in by_value.items() if any(i.context is OccurrenceContext.PJE_COVER for i in items)}
    header_values = {value for value, items in by_value.items() if any(i.context is OccurrenceContext.JUDICIAL_HEADER for i in items)}
    primary_values = cover_values | header_values
    reading_incomplete = bool(pending or unread)
    primary: str | None = None
    confidence: str | None = None
    reason: UnresolvedReason | None = None
    if len(primary_values) == 1:
        primary = next(iter(primary_values))
        header_pages = {
            (item.content_id, item.page) for item in by_value[primary]
            if item.context is OccurrenceContext.JUDICIAL_HEADER
        }
        confidence = "HIGH" if primary in cover_values or len(header_pages) > 1 else "MEDIUM"
    elif len(primary_values) > 1:
        reason = UnresolvedReason.CONFLICTING_PRIMARY_SOURCES
    elif by_value:
        reason = UnresolvedReason.READING_INCOMPLETE if reading_incomplete else UnresolvedReason.NO_PRIMARY_SOURCE
    elif reading_incomplete:
        reason = UnresolvedReason.READING_INCOMPLETE

    candidates = []
    for value, items in by_value.items():
        contexts = {item.context for item in items}
        if value == primary:
            classification = ProcessNumberClass.PRIMARY
        elif value in primary_values:
            classification = ProcessNumberClass.UNKNOWN
        elif OccurrenceContext.DECLARED_RELATION in contexts:
            classification = ProcessNumberClass.RELATED_CASE
        elif OccurrenceContext.CITATION in contexts:
            classification = ProcessNumberClass.CITED_CASE
        else:
            classification = ProcessNumberClass.UNKNOWN
        candidates.append(ProcessNumberCandidate(
            value, classification, value in primary_values, len(items),
            len({item.content_id for item in items}), tuple(items),
        ))
    rank = {
        ProcessNumberClass.PRIMARY: 0, ProcessNumberClass.RELATED_CASE: 2,
        ProcessNumberClass.UNKNOWN: 3, ProcessNumberClass.CITED_CASE: 4,
    }
    # Ordem de leitura dentro de cada classe; nunca por frequência.
    order = {value: index for index, value in enumerate(by_value)}
    candidates.sort(key=lambda item: (rank[item.classification] - (1 if item.primary_evidence and item.classification is not ProcessNumberClass.PRIMARY else 0), order[item.value]))
    if primary is not None:
        resolution = PrimaryResolution.RESOLVED
    elif reason is None:
        resolution = PrimaryResolution.NOT_FOUND
    else:
        resolution = PrimaryResolution.UNRESOLVED
    return ProcessNumberClassification(
        resolution, primary, confidence, reason, tuple(candidates), pending, unread, invalid,
    )


@dataclass(frozen=True, slots=True)
class GetProcessNumberClassification:
    """Releitura das fontes do caso; falha de leitura é dita, nunca vira "nada"."""
    texts: object

    def execute(self, workspace_id) -> ProcessNumberClassification:
        from .process_participants import _READ_FAILURES as read_failures
        try:
            documents = self.texts.execute(workspace_id)
        except read_failures:
            return ProcessNumberClassification(
                PrimaryResolution.UNRESOLVED, None, None, UnresolvedReason.SOURCES_UNAVAILABLE, (), (), (), (),
            )
        return classify_process_numbers(documents)


_MAX_LISTED_OCCURRENCES = 5


def process_number_classification_dto(value: ProcessNumberClassification) -> dict[str, object]:
    def occurrence(item: ProcessNumberOccurrence) -> dict[str, object]:
        return {
            "filename": item.filename, "page": item.page, "excerpt": item.excerpt,
            "source_start": item.source_start, "source_end": item.source_end,
            "extraction_mode": item.extraction_mode, "context": item.context.value,
            "logical_document_id": item.logical_document_id,
        }

    def ordered(items):
        # Evidência estrutural primeiro: a capa e o cabeçalho explicam a proposta.
        weight = {OccurrenceContext.PJE_COVER: 0, OccurrenceContext.JUDICIAL_HEADER: 1}
        return sorted(items, key=lambda item: weight.get(item.context, 2))

    return {
        "resolution": value.resolution.value,
        "primary_value": value.primary_value,
        "confidence": value.confidence,
        "unresolved_reason": value.unresolved_reason.value if value.unresolved_reason else None,
        "candidates": [
            {
                "value": item.value, "classification": item.classification.value,
                "primary_evidence": item.primary_evidence,
                "occurrence_count": item.occurrence_count, "document_count": item.document_count,
                "occurrences": [occurrence(o) for o in ordered(item.occurrences)[:_MAX_LISTED_OCCURRENCES]],
            }
            for item in value.candidates
        ],
        "pending_documents": list(value.pending_documents),
        "unread_pages": [{"filename": f, "page": p} for f, p in value.unread_pages],
        "invalid_occurrences": [{"filename": f, "page": p} for f, p in value.invalid_occurrences],
    }
