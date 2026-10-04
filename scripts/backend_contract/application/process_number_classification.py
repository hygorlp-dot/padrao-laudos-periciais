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
from bisect import bisect_left, bisect_right
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
    # A capa ou o cabeçalho existe, mas só em OCR de baixa confiança.
    LOW_CONFIDENCE_OCR = "LOW_CONFIDENCE_OCR"


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
    r"|NUMERO(?:\s+(?:DO\s+PROCESSO|UNICO))?"
    r")"
    r"(?:\s*(?:N(?:UMERO|O|[.°])|NUMERO)\s*\.?)?"
    r"\s*[:\-]?\s*$"
)
# Marcadores de citação de outro julgado. Palavras inteiras.
# Decisivos: só aparecem citando julgado alheio, mesmo num cabeçalho.
_DECISIVE_CITATION = (
    r"RESP|ARESP|AGINT|AGRG|EDCL|TEMA|STJ|STF|TNU|JULGADO\s+EM|JULGAMENTO\s+EM|DJE|"
    r"PRECEDENTES?|JURISPRUDENCIA|EMENTA|NESSE\s+SENTIDO|NO\s+MESMO\s+SENTIDO|VEJA-SE|CONFIRA-SE|CF\."
)
# De classe ou de órgão: um cabeçalho de apelação traz "Apelação Cível",
# "Relator: Des. ...", "TRF5" sobre o PRÓPRIO processo.
_CLASS_CITATION = (
    r"AC|APELACAO|APELACAO\s+CIVEL|AGRAVO\s+INTERNO|REL|RELATOR|RELATORA|DES|DESEMBARGADOR|DESEMBARGADORA|"
    r"MIN|MINISTRO|MINISTRA|TRF\s*\d?|TJ[A-Z]{2}|ACORDAO|DJ"
)
_DECISIVE = re.compile(r"(?<![A-Z0-9])(?:" + _DECISIVE_CITATION + r")(?![A-Z0-9])")
_CITATION = re.compile(r"(?<![A-Z0-9])(?:" + _DECISIVE_CITATION + "|" + _CLASS_CITATION + r")(?![A-Z0-9])")
# Título de peça: o cabeçalho do processo termina nele; "PROCESSO: X" depois
# do título já está no corpo da peça (onde também se citam julgados).
_PIECE_TITLE = re.compile(
    r"^\s*(?:SENTENCA|DECISAO|DESPACHO|ACORDAO|VOTO|RELATORIO|EMENTA|FUNDAMENTACAO|DISPOSITIVO|"
    r"ATO\s+ORDINATORIO|CERTIDAO|INTIMACAO|MANDADO|PETICAO|EXCELENTISSIM\w*|DOS\s+FATOS|"
    r"I\s*[-.]\s*RELATORIO)\b"
)
# A zona de cabeçalho é feita só de linhas com forma de cabeçalho (#286):
# timbre institucional ("Tribunal...", "2ª Vara...", "Seção Judiciária..."),
# endereço do juízo, "Rótulo: valor" de rótulo processual conhecido ou a linha
# da classe com o número. A primeira linha de outra forma (prosa, transcrição,
# "Cito o julgado:") encerra a zona: dali em diante nada é cabeçalho primário.
_INSTITUTIONAL_START = re.compile(
    r"^\s*(?:PODER\s+JUDICIARIO|JUSTICA\s+(?:FEDERAL|ESTADUAL|DO\s+TRABALHO|ELEITORAL|MILITAR|COMUM)\b|TRIBUNAL\b|"
    r"SECAO\b|SUBSECAO\b|COMARCA\b|JUIZO\b|JUIZADO\b|FORUM\b|JUIZA?\s+(?:FEDERAL|DE\s+DIREITO)\b|"
    r"GABINETE\b|ESTADO\s+D[EOA]\b|REPUBLICA\b|PJE\b|PROCESSO\s+JUDICIAL\s+ELETRONICO|"
    r"\d{1,3}\s*A?\s+(?:VARA|TURMA|CAMARA|JUIZADO|SECAO)\b|(?:VARA|TURMA|CAMARA)\b)"
)
_ADDRESS_START = re.compile(r"^\s*(?:RUA|AV\.?|AVENIDA|PRACA|CEP|FONE|TELEFONE|TEL\.?|E-?MAIL|SITE|HTTPS?)\b")
_HEADER_LABELS = frozenset({
    "PROCESSO", "AUTOS", "NUMERO", "N", "NO", "CLASSE", "ASSUNTO", "ASSUNTOS", "AUTOR", "AUTORA", "AUTORES", "REU", "REUS", "RE",
    "REQUERENTE", "REQUERENTES", "REQUERIDO", "REQUERIDA", "REQUERIDOS", "EXEQUENTE", "EXECUTADO", "EXECUTADA",
    "APELANTE", "APELANTES", "APELADO", "APELADA", "APELADOS", "AGRAVANTE", "AGRAVADO", "AGRAVADA", "RECORRENTE",
    "RECORRIDO", "RECORRIDA", "IMPETRANTE", "IMPETRADO", "EMBARGANTE", "EMBARGADO", "RELATOR", "RELATORA", "ORGAO",
    "JUIZ", "JUIZA", "JUIZO", "VARA", "VALOR", "POLO", "ADVOGADO", "ADVOGADA", "ADVOGADOS", "PROCURADOR",
    "PROCURADORA", "DATA", "ENDERECO", "PARTES", "DISTRIBUICAO", "DISTRIBUIDO", "PRIORIDADE", "SEGREDO",
    "COMPETENCIA", "CHAVE", "ID", "INTERESSADO", "INTERESSADA", "TERCEIRO", "PERITO", "PERITA", "ORIGEM",
})
_CASE_CLASS_LINE = re.compile(
    r"^\s*(?:PROCEDIMENTO|ACAO|CUMPRIMENTO|EXECUCAO|APELACAO|AGRAVO|RECURSO|EMBARGOS|MANDADO|PROCESSO|AUTOS|"
    r"RECLAMACAO|INCIDENTE|TUTELA|PRODUCAO|CAUTELAR)\b"
)


_PARTY_LABELS = frozenset({
    "AUTOR", "AUTORA", "AUTORES", "REU", "REUS", "RE", "REQUERENTE", "REQUERENTES", "REQUERIDO", "REQUERIDA",
    "REQUERIDOS", "EXEQUENTE", "EXECUTADO", "EXECUTADA", "APELANTE", "APELANTES", "APELADO", "APELADA", "APELADOS",
    "AGRAVANTE", "AGRAVADO", "AGRAVADA", "RECORRENTE", "RECORRIDO", "RECORRIDA", "IMPETRANTE", "IMPETRADO",
    "EMBARGANTE", "EMBARGADO", "POLO", "ADVOGADO", "ADVOGADA", "ADVOGADOS", "PROCURADOR", "PROCURADORA",
    "INTERESSADO", "INTERESSADA", "TERCEIRO", "PARTES",
})
# Assinatura, paginação e endereço eletrônico do PJe: nem abrem nem fecham.
_PAGE_FURNITURE = re.compile(
    r"^\s*(?:ASSINADO\s+ELETRONICAMENTE|DOCUMENTO\s+ASSINADO|NUM\.\s*\d+\s*-\s*PAG|HTTPS?://|"
    r"ESTE\s+DOCUMENTO\s+FOI\s+GERADO|IMPRESSO\s+POR)"
)


def _party_line(line: str) -> bool:
    label = re.match(r"^\s*([A-Z]+)[A-Z0-9()/ .-]{0,40}?:", line)
    return label is not None and label.group(1) in _PARTY_LABELS


def _header_shaped(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped.endswith(":") and _PRIMARY_LABEL.fullmatch(stripped) is None:
        return False
    label = re.match(r"^([A-Z][A-Z0-9()/ .-]{0,40}?)\s*:", stripped)
    if label:
        first = re.match(r"[A-Z]+", label.group(1))
        return first is not None and first.group(0) in _HEADER_LABELS
    if _INSTITUTIONAL_START.match(stripped) or _ADDRESS_START.match(stripped):
        return True
    return _CASE_CLASS_LINE.match(stripped) is not None and _CNJ_PATTERN.search(stripped) is not None


_HEADER_ZONE_LINES = 30
_PREFIX_REACH = 300
_WINDOW_REACH = 300
_FOLLOWING_LINES = 2

# Relação declarada com outro processo.
_RELATION = re.compile(
    r"(?<![A-Z0-9])(?:"
    r"(?:PROCESSOS?|AUTOS|FEITOS?)\s+(?:RELACIONADOS?|VINCULADOS?|REFERENCIADOS?|ASSOCIADOS?|"
    r"(?:DE\s+)?ORIGEM|ORIGINARIOS?|PRINCIPAIS|APENSOS?|APENSADOS?)|"
    r"REFERENCIA(?:\s+DOCUMENTAL)?|DEPENDENCIA|PREVENCAO|PREVENTO|"
    r"OUTRO\s+(?:PROCESSO|FEITO)|ANEXO\s+DE\s+OUTRO\s+FEITO|APENSO|APENSADO"
    r")(?![A-Z0-9])"
)
# Título de seção que abre jurisprudência citada até o fim da página.
_CITED_SECTION = re.compile(
    r"^\s*(?:(?:JURISPRUDENCIA(?:\s+\w+)?|PRECEDENTES?|EMENTA|ACORDAO(?:\s+CITADO)?)\s*:?\s*$|EMENTA\s*:)"
)
_INSTITUTIONAL = ("PODER JUDICIARIO", "JUSTICA FEDERAL", "TRIBUNAL REGIONAL FEDERAL", "TRIBUNAL DE JUSTICA", "JUSTICA DO TRABALHO")
_JUDICIAL_STRUCTURE = re.compile(
    r"(?m)^\s*(?:ORGAO\s+JULGADOR|POLO\s+ATIVO|POLO\s+PASSIVO|CLASSE(?:\s+JUDICIAL)?\s*:"
    r"|(?:AUTOR|AUTORA|REQUERENTE|EXEQUENTE|REU|REQUERIDO|REQUERIDA|EXECUTADO|EXECUTADA|APELANTE|APELADO|APELADA|"
    r"AGRAVANTE|AGRAVADO|AGRAVADA|RECORRENTE|RECORRIDO|RECORRIDA|IMPETRANTE|IMPETRADO|EMBARGANTE|EMBARGADO)\s*:)"
)


# Capa PJe é estrutura, não a palavra "PJe": o título "Processo Judicial
# Eletrônico" e o bloco de rótulos da capa. URL "pje1g...", "(PJe)" depois da
# classe ou rodapé de documento assinado nunca fazem de uma peça uma capa.
_COVER_LABELS = re.compile(
    r"(?m)^\s*(?:CLASSE(?:\s+JUDICIAL)?|ORGAO\s+JULGADOR|ULTIMA\s+DISTRIBUICAO|VALOR\s+DA\s+CAUSA|ASSUNTOS?|"
    r"SEGREDO\s+DE\s+JUSTICA|JUSTICA\s+GRATUITA|PEDIDO\s+DE\s+LIMINAR|PROCESSO\s+REFERENCIA|AUTUACAO)\s*[:?]"
)
_COVER_MIN_LABELS = 2


def _is_pje_cover(normalized_page: str) -> bool:
    if re.search(r"(?m)^\s*(?:PJE\s*-\s*)?PROCESSO\s+JUDICIAL\s+ELETRONICO\s*$", normalized_page) is None:
        return False
    labels = {match.group(0).split(":")[0].split("?")[0].strip() for match in _COVER_LABELS.finditer(normalized_page)}
    return len(labels) >= _COVER_MIN_LABELS


def _is_judicial_piece(normalized_page: str) -> bool:
    return (
        any(marker in normalized_page for marker in _INSTITUTIONAL)
        or re.search(r"\bVARA\b|\bJUIZADO\b", normalized_page) is not None
    ) and _JUDICIAL_STRUCTURE.search(normalized_page) is not None


class _PageView:
    """Página normalizada UMA vez; todo contexto é fatia limitada dela."""

    def __init__(self, text: str):
        self.text = text
        self.normalized, indices = _ascii_upper_with_source_indices(text)
        self.indices = indices
        self.line_starts = [0] + [index + 1 for index, char in enumerate(self.normalized) if char == "\n"]
        self.cover = _is_pje_cover(self.normalized)
        self.judicial = _is_judicial_piece(self.normalized)
        self.header_end = len(self.normalized)
        self.cited_from: int | None = None
        # Só o PRIMEIRO número rotulado do cabeçalho é candidato a principal.
        self.first_header: int | None = None
        self.first_cover: int | None = None
        parties_seen = False
        for number, line_start in enumerate(self.line_starts):
            line = self._line(number)
            if self.cited_from is None and _CITED_SECTION.match(line):
                self.cited_from = line_start
            if self.header_end != len(self.normalized) or _PAGE_FURNITURE.match(line):
                continue
            party = _party_line(line)
            if (
                number >= _HEADER_ZONE_LINES or _PIECE_TITLE.match(line)
                or not _header_shaped(line)
                # O bloco de partes encerra o cabeçalho: a primeira linha
                # depois dele que não é parte nem advogado já é corpo.
                or (parties_seen and not party and line.strip())
            ):
                self.header_end = line_start
            parties_seen = parties_seen or party

    def _line(self, number: int) -> str:
        start = self.line_starts[number]
        end = self.line_starts[number + 1] - 1 if number + 1 < len(self.line_starts) else len(self.normalized)
        return self.normalized[start:min(end, start + 4 * _WINDOW_REACH)]

    def position(self, source_index: int) -> int:
        return bisect_left(self.indices, source_index)

    def line_number(self, position: int) -> int:
        return bisect_right(self.line_starts, position) - 1

    def line_end(self, number: int) -> int:
        return self.line_starts[number + 1] - 1 if number + 1 < len(self.line_starts) else len(self.normalized)

    def neighbour(self, number: int, step: int, count: int) -> list[str]:
        found = []
        index = number + step
        while 0 <= index < len(self.line_starts) and len(found) < count:
            line = self._line(index).strip()
            if line:
                found.append(line)
            index += step
        return found


def _page_occurrences(view: _PageView, ocr: bool):
    """(valor bruto normalizado, início, fim) na página, sem sobreposição."""
    found = []
    taken: list[tuple[int, int]] = []
    for match in _CNJ_PATTERN.finditer(view.text):
        found.append((match.group(0), match.start(), match.end()))
        taken.append((match.start(), match.end()))
    if ocr:
        for match in _OCR_CNJ_PATTERN.finditer(view.normalized):
            start = view.indices[match.start()]
            end = view.indices[match.end() - 1] + 1
            position = bisect_right(taken, (start, end))
            neighbours = taken[max(0, position - 1):position + 1]
            if any(start < other_end and other_start < end for other_start, other_end in neighbours):
                continue
            groups = tuple(group.translate(_OCR_DIGIT_CONFUSIONS) for group in match.groups())
            found.append((f"{groups[0]}-{groups[1]}.{groups[2]}.{groups[3]}.{groups[4]}.{groups[5]}", start, end))
    return sorted(found, key=lambda item: item[1])


def _upper(value: str) -> str:
    return _ascii_upper_with_source_indices(value)[0]


def _context(view: _PageView, start: int, end: int) -> OccurrenceContext:
    begin = view.position(start)
    finish = view.position(end)
    number = view.line_number(begin)
    line_start = view.line_starts[number]
    line_end = view.line_end(number)
    prefix = view.normalized[max(line_start, begin - _PREFIX_REACH):begin]
    line = view.normalized[max(line_start, begin - _WINDOW_REACH):min(line_end, finish + _WINDOW_REACH)]
    previous = view.neighbour(number, -1, 1)
    previous_line = previous[0] if previous else ""
    if _RELATION.search(prefix) or (previous_line.endswith(":") and _RELATION.search(previous_line)):
        return OccurrenceContext.DECLARED_RELATION
    # Rótulo na mesma linha ("Número: X") ou, na capa em tabela, sozinho na
    # linha anterior ("Número:" / "X").
    labelled = _PRIMARY_LABEL.fullmatch(prefix) is not None or (
        not prefix.strip() and previous_line.endswith(":") and _PRIMARY_LABEL.fullmatch(previous_line) is not None
    )
    cited_section = view.cited_from is not None and begin >= view.cited_from
    # Na capa PJe a linha "Número: X" é a identidade do processo; a classe
    # processual ("Apelação Cível") pode estar na mesma linha sem ser citação.
    following = " ".join(view.neighbour(number, 1, _FOLLOWING_LINES))
    # Na capa só o PRIMEIRO número rotulado, no topo, sem citação vizinha.
    if (
        view.cover and labelled and not cited_section and number < _HEADER_ZONE_LINES
        and not _DECISIVE.search(line) and not _DECISIVE.search(following) and not _DECISIVE.search(previous_line)
    ):
        if view.first_cover is None:
            view.first_cover = begin
        if view.first_cover == begin:
            return OccurrenceContext.PJE_COVER
        # Outro número rotulado na capa (processo de origem sem rótulo de
        # relação, etc.): visível, nunca candidato a principal.
        return OccurrenceContext.UNQUALIFIED
    if cited_section or _DECISIVE.search(line):
        return OccurrenceContext.CITATION
    # Cabeçalho da peça: antes do título (Sentença, Decisão...) e nas primeiras
    # linhas. "PROCESSO: X" no corpo pode ser julgado citado; nunca é principal.
    if view.judicial and labelled and begin < view.header_end:
        # Citação logo antes ou logo depois ("(STJ, julgado em ...)") desfaz o
        # cabeçalho: é julgado citado com rótulo, nunca o número dos autos.
        if _DECISIVE.search(following) or _DECISIVE.search(previous_line):
            return OccurrenceContext.CITATION
        if view.first_header is None:
            view.first_header = begin
        if view.first_header == begin:
            return OccurrenceContext.JUDICIAL_HEADER
        return OccurrenceContext.UNQUALIFIED
    if _CITATION.search(line) or _CITATION.search(following):
        # Rótulo com só a classe na linha ("PROCESSO: X - APELAÇÃO CÍVEL") e
        # nada de citação depois: não se sabe de quem é; não vira precedente.
        if labelled and not _CITATION.search(following):
            return OccurrenceContext.UNQUALIFIED
        return OccurrenceContext.CITATION
    return OccurrenceContext.UNQUALIFIED


def _excerpt(view: _PageView, start: int, end: int) -> str:
    line_start = view.text.rfind("\n", max(0, start - _WINDOW_REACH), start) + 1 or max(0, start - _WINDOW_REACH)
    line_end = view.text.find("\n", end, end + _WINDOW_REACH)
    line_end = min(len(view.text), end + _WINDOW_REACH) if line_end < 0 else line_end
    return " ".join(view.text[line_start:line_end].split())[:_EXCERPT_LIMIT]


_PRIMARY_CONTEXTS = frozenset({OccurrenceContext.PJE_COVER, OccurrenceContext.JUDICIAL_HEADER})


def classify_process_numbers(documents) -> ProcessNumberClassification:
    occurrences: list[ProcessNumberOccurrence] = []
    pending: list[str] = []
    unread: list[tuple[str, int]] = []
    invalid: list[tuple[str, int]] = []
    weak_primary = False
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
            view = _PageView(page.text)
            logical = document.logical_document_for(page.number)
            for raw, start, end in _page_occurrences(view, ocr):
                try:
                    value = validate_cnj_number(raw).canonical
                except ValueError:
                    invalid.append((document.filename, page.number))
                    continue
                context = _context(view, start, end)
                if weak and context in _PRIMARY_CONTEXTS:
                    context = OccurrenceContext.UNQUALIFIED
                    weak_primary = True
                occurrences.append(ProcessNumberOccurrence(
                    value, document.content_id, document.filename, page.number, start, end,
                    _excerpt(view, start, end), mode, context,
                    logical.document_id if logical is not None else None,
                ))
    return _resolve(occurrences, tuple(pending), tuple(unread), tuple(dict.fromkeys(invalid)), weak_primary)


def _resolve(occurrences, pending, unread, invalid, weak_primary=False) -> ProcessNumberClassification:
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
    elif reading_incomplete and (by_value or invalid):
        reason = UnresolvedReason.READING_INCOMPLETE
    elif weak_primary:
        reason = UnresolvedReason.LOW_CONFIDENCE_OCR
    elif by_value:
        reason = UnresolvedReason.NO_PRIMARY_SOURCE
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
