"""Local, literal case intake proposals; no adjudication or automatic facts."""

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from hashlib import sha256
import json
import re
import unicodedata


def folded(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)).upper().strip()


def document_pages(document, pages):
    if not document.content_available or document.analysis_revision < 1:
        return ()
    span = re.fullmatch(r"p\. (\d+)(?:-(\d+))? \| PJe .+", document.page_count_or_span)
    if span:
        first, last = int(span[1]), int(span[2] or span[1])
        return tuple(page for page in pages if first <= page.number <= last)
    return tuple(pages) if document.page_count_or_span == "Documento completo" else ()


@dataclass(frozen=True, slots=True)
class QuestionSource:
    origin: str
    original_number: str
    page_start: int
    page_end: int
    excerpt: str
    method: str

    def __post_init__(self):
        if self.origin not in {"COURT", "CLAIMANT", "DEFENDANT"} or self.method not in {"NUMBERED_NATIVE_TEXT_V1", "NUMBERED_OCR_V1"}:
            raise ValueError("question source origin or method is invalid")
        if any(type(value) is not str or not value.strip() for value in (self.original_number, self.excerpt)) or not self.excerpt.lstrip().startswith(self.original_number):
            raise ValueError("original question number must remain in source excerpt")
        if type(self.page_start) is not int or type(self.page_end) is not int or self.page_start < 1 or self.page_end < self.page_start:
            raise ValueError("question source pages are invalid")

    @classmethod
    def from_mapping(cls, value):
        if type(value) is not dict or set(value) != {f.name for f in fields(cls)}:
            raise ValueError("question source payload is invalid")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class QuestionProposal:
    proposal_id: str
    document_id: str
    text: str
    source: QuestionSource


_ORIGINS = {
    "JUIZO": "COURT",
    "PARTE AUTORA": "CLAIMANT", "AUTOR": "CLAIMANT", "AUTORA": "CLAIMANT", "AUTORES": "CLAIMANT", "AUTORAS": "CLAIMANT",
    "PARTE REQUERENTE": "CLAIMANT", "REQUERENTE": "CLAIMANT",
    "PARTE RE": "DEFENDANT", "REU": "DEFENDANT", "RE": "DEFENDANT", "REUS": "DEFENDANT", "RES": "DEFENDANT",
    "PARTE REQUERIDA": "DEFENDANT", "REQUERIDA": "DEFENDANT", "REQUERIDO": "DEFENDANT",
}
# Cabecalho de quesitos: enumerador opcional ("II -", "III.", "b)", "1.") e, so quando a
# linha termina em ":", ate tres palavras de introducao ("Seguem os quesitos da re:").
# Sem o ":" final, uma linha de continuacao que mencione "quesitos" nao vira cabecalho.
_ENUMERATOR = r"(?:(?:[IVXLCDM]+|\d+(?:\.\d+)*|[A-Z])\s*[.)\-–—]\s*)?"
_DESIGNATION = r"QUESITOS\s+(?:(?:FORMULADOS|APRESENTADOS)\s+PEL[OA]S?\s+|SUPLEMENTARES\s+D[OA]S?\s+|D[OA]S?\s+)(.+?)"
_HEADING = re.compile(
    rf"{_ENUMERATOR}{_DESIGNATION}\s*:?"
    rf"|{_ENUMERATOR}(?:[A-Z]+\s+){{1,3}}{_DESIGNATION}\s*:"
)
_SECTION = re.compile(rf"{_ENUMERATOR}QUESITOS\b.*|{_ENUMERATOR}(?:[A-Z]+\s+){{1,3}}QUESITOS\b.*:")
_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*\s*[.)º°-])\s+(.+)$")


# A origem de um quesito so vale dentro da secao "QUESITOS ..." que a declara. A
# parte dispositiva do ato (lista FECHADA de marcadores) encerra a secao: sem isso,
# um despacho numerado seria proposto como quesito da ultima origem vista. Rotulos
# genericos ("o seguinte:", "Dos vicios construtivos:") NAO encerram -- sao parte
# do quesito ou da propria secao.
_DISPOSITIVE = re.compile(
    r"(?:ANTE O EXPOSTO|DIANTE DO EXPOSTO|PELO EXPOSTO|ISTO POSTO|ISSO POSTO|POSTO ISSO"
    r"|DETERMINO|DECIDO|INTIMEM-SE|CUMPRA-SE|PUBLIQUE-SE)\b.*"
    r"|.*\b(?:DETERMINO|DECIDO)\s*:?\s*"
)
# Fecham o quesito em curso sem encerrar a secao: espaco de resposta e rodape PJe.
_QUESTION_BREAKS = ("NESTES TERMOS", "TERMOS EM QUE", "PEDE DEFERIMENTO", "RESPOSTA", "NUMERO DO DOCUMENTO", "ASSINADO ELETRONICAMENTE")
# Limite de `$defs/text` em schemas/case-analysis-snapshot-v1.schema.json: um bloco
# maior nao cabe na Analise do Caso, entao nao e oferecido como proposta.
QUESTION_TEXT_MAX = 4096


def extract_questions(document, pages):
    selected = document_pages(document, pages)
    proposals = []
    origin = None
    active = []
    number = None
    def flush():
        nonlocal active, number
        if active and origin and number:
            excerpt = "\n".join(line for _page, line in active)
            match = _NUMBER.match(active[0][1])
            text = "\n".join([match[2], *(line for _page, line in active[1:])]).rstrip()
            if len(excerpt) > QUESTION_TEXT_MAX or len(text) > QUESTION_TEXT_MAX:
                active, number = [], None
                return
            method = "NUMBERED_OCR_V1" if any("OCR" in str(page.extraction_mode) for page, _line in active) else "NUMBERED_NATIVE_TEXT_V1"
            source = QuestionSource(origin, number, active[0][0].number, active[-1][0].number, excerpt, method)
            identity = json.dumps([document.document_id, document.source_sha256, text, asdict(source)], ensure_ascii=False, sort_keys=True)
            proposals.append(QuestionProposal(sha256(identity.encode()).hexdigest(), document.document_id, text, source))
        active, number = [], None
    for page in selected:
        for line in page.text.splitlines():
            heading = _HEADING.fullmatch(folded(line))
            if heading or _SECTION.fullmatch(folded(line)) or _DISPOSITIVE.fullmatch(folded(line)):
                # Cabecalho de quesitos nao reconhecido ou parte dispositiva: a origem
                # anterior NAO se estende a ela -- sem origem explicita, nada e proposto.
                flush()
                designation = next((group for group in heading.groups() if group), "") if heading else ""
                origin = _ORIGINS.get(designation.rstrip(":").strip())
                continue
            if not line.strip() or folded(line).startswith(_QUESTION_BREAKS):
                flush()
                continue
            match = _NUMBER.match(line)
            if origin and match:
                flush()
                number = match[1]
                active = [(page, line)]
            elif active:
                active.append((page, line))
    flush()
    return tuple(proposals)


DOCUMENT_CATEGORIES = (
    ("ARCHITECTURAL_PROJECT", "Projetos arquitetônicos", ("PROJETO ARQUITETONICO", "PROJETOS ARQUITETONICOS")),
    ("COMPLEMENTARY_PROJECT", "Projetos complementares", ("PROJETO ESTRUTURAL", "PROJETO ELETRICO", "PROJETO HIDROSSANITARIO", "PROJETOS COMPLEMENTARES")),
    ("PERMIT", "Alvará", ("ALVARA", "ALVARA DE CONSTRUCAO")),
    ("EXECUTION_ART", "ART/RRT de execução", ("ART DE EXECUCAO", "RRT DE EXECUCAO")),
    ("PROJECT_ART", "ART/RRT de projeto", ("ART DE PROJETO", "RRT DE PROJETO")),
    ("MEMORIAL", "Memorial descritivo", ("MEMORIAL DESCRITIVO",)),
    ("HABITE_SE", "Habite-se", ("HABITE-SE", "HABITE SE")),
    ("USE_MANUAL", "Manual de uso, operação e manutenção", ("MANUAL DE USO", "MANUAL DO PROPRIETARIO", "MANUAL DE OPERACAO E MANUTENCAO")),
    ("MAINTENANCE_REPORT", "Relatório de manutenção", ("RELATORIO DE MANUTENCAO",)),
)


def inventory_proposals(documents, pages_by_document):
    result = []
    for category, label, headings in DOCUMENT_CATEGORIES:
        matches = []
        for document in documents:
            pages = document_pages(document, pages_by_document.get(document.document_id, ()))
            if not pages:
                continue
            # Only document identity/title or leading title lines; body mentions
            # do not prove that the referenced document is actually attached.
            filename = folded(document.raw_type).removesuffix(".PDF").replace("_", " ")
            for page in pages[:1]:
                titles = [line.strip() for line in page.text.splitlines() if line.strip()][:2]
                found = next((line for line in titles if folded(line) in headings), None)
                if found or filename in headings:
                    matches.append({"document_id": document.document_id, "page": page.number, "excerpt": found or document.raw_type, "method": "DOCUMENT_HEADING_V1" if found else "DOCUMENT_TITLE_V1"})
        result.append({"category": category, "label": label, "state": "PROPOSED_PRESENT" if matches else "NOT_FOUND_IN_CURRENT_INGESTED_MATERIAL", "matches": matches})
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DocumentInventoryDecision:
    category: str
    status: str
    source_document_ids: tuple[str, ...]
    reason: str
    confirmed_by: str
    confirmed_at: str

    def __post_init__(self):
        if self.category not in {row[0] for row in DOCUMENT_CATEGORIES} or self.status not in {"PROFESSIONALLY_CONFIRMED_PRESENT", "PROFESSIONALLY_CONFIRMED_ABSENT_FROM_CASE"}:
            raise ValueError("document inventory decision is invalid")
        if type(self.source_document_ids) is not tuple or any(type(v) is not str or not v for v in self.source_document_ids) or len(set(self.source_document_ids)) != len(self.source_document_ids):
            raise ValueError("document inventory sources are invalid")
        if bool(self.source_document_ids) != (self.status == "PROFESSIONALLY_CONFIRMED_PRESENT"):
            raise ValueError("document presence requires sources and absence cannot claim sources")
        if any(type(v) is not str or not v.strip() for v in (self.reason, self.confirmed_by, self.confirmed_at)) or datetime.fromisoformat(self.confirmed_at).utcoffset() is None:
            raise ValueError("document inventory requires professional confirmation")

    @classmethod
    def from_mapping(cls, value):
        if type(value) is not dict or set(value) != {f.name for f in fields(cls)} or type(value["source_document_ids"]) is not list:
            raise ValueError("document inventory payload is invalid")
        return cls(**{**value, "source_document_ids": tuple(value["source_document_ids"])})
