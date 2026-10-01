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


def question_evidence(source):
    """O que os bytes do documento comprovam: numero, paginas, trecho literal e metodo.

    A ORIGEM nao esta aqui: a extracao so a propoe e o perito a confirma no aceite
    (proposta != decisao). Verificacao de backup e deduplicacao comparam a evidencia.
    """
    return (source.original_number, source.page_start, source.page_end, source.excerpt, source.method)


@dataclass(frozen=True, slots=True)
class QuestionProposal:
    proposal_id: str
    document_id: str
    text: str
    source: QuestionSource
    # So para o perito conferir ANTES do aceite (nao sao persistidos nem entram na
    # identidade): a linha do titulo que sugeriu a origem e o que vem logo depois do bloco
    # no documento. Um erro de fronteira da heuristica fica visivel, nao silencioso.
    section_heading: str | None = None
    section_page: int | None = None
    context_after: str = ""


_ORIGINS = {
    "JUIZO": "COURT",
    "PARTE AUTORA": "CLAIMANT", "AUTOR": "CLAIMANT", "AUTORA": "CLAIMANT", "AUTORES": "CLAIMANT", "AUTORAS": "CLAIMANT",
    "PARTE REQUERENTE": "CLAIMANT", "REQUERENTE": "CLAIMANT",
    "PARTE RE": "DEFENDANT", "REU": "DEFENDANT", "RE": "DEFENDANT", "REUS": "DEFENDANT", "RES": "DEFENDANT",
    "PARTE REQUERIDA": "DEFENDANT", "REQUERIDA": "DEFENDANT", "REQUERIDO": "DEFENDANT",
}
QUESTION_ORIGINS = frozenset(_ORIGINS.values())
# Linhas ESTRUTURAIS (cabecalho, dispositivo, espaco de resposta) comecam com maiuscula
# ou enumerador; continuacao em minuscula nunca muda a secao.
_STRUCTURAL_START = re.compile(r"\s*(?:[A-ZÀ-Ý0-9]|(?:[ivxlcdm]+|[a-z])\s*[.)\-–—]\s)")
# Marcas tipograficas antes/depois de um titulo: "(b) Quesitos...", "- QUESITOS...", aspas.
_TITLE_MARKS = re.compile("^[\\s\"'“”‘’(\\-–—•*]+|[\\s\"'“”‘’]+$")
# Cabecalho de quesitos: enumerador opcional ("II -", "III.", "b)", "1.") e, so quando a
# linha termina em ":", ate tres palavras de introducao ("Seguem os quesitos da re:").
_ENUMERATOR = r"(?:(?:[IVXLCDM]+|\d+(?:\.\d+)*|[A-Z])\s*[.)\-–—]\s*)?"
_DESIGNATION = (
    r"QUESITOS\s+(?:(?:FORMULADOS|APRESENTADOS)\s+PEL[OA]S?\s+|(?:SUPLEMENTARES|COMPLEMENTARES)\s+D[OA]S?\s+|D[OA]S?\s+)(.+?)"
)
_HEADING = re.compile(
    rf"{_ENUMERATOR}{_DESIGNATION}\s*:?"
    rf"|{_ENUMERATOR}(?:[A-Z]+\s+){{1,3}}{_DESIGNATION}\s*:"
)
_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)*\s*[.)º°-])\s+(.+)$")
# A origem de um quesito so vale dentro da secao "QUESITOS ..." que a declara. A parte
# dispositiva do ato (lista FECHADA) encerra a secao; "DISPOSITIVO"/"PROVIDENCIAS" so
# como titulo isolado -- no meio de um quesito sao vocabulario tecnico ("dispositivo de
# descarga", "providencias necessarias").
_DISPOSITIVE = re.compile(
    r"(?:ANTE O EXPOSTO|DIANTE DO EXPOSTO|PELO EXPOSTO|POR TODO O EXPOSTO|ISTO POSTO|ISSO POSTO|POSTO ISSO"
    r"|DETERMINO|DECIDO|DEFIRO|INDEFIRO|INTIMEM-SE|INTIME-SE|CUMPRA-SE|PUBLIQUE-SE)\b.*"
    r"|.*\b(?:DETERMINO|DECIDO)\s*:?\s*"
    r"|(?:DISPOSITIVO|PROVIDENCIAS)\s*:?\s*"
)
# Fecham o quesito em curso sem encerrar a secao: fecho da peca e espaco de resposta.
_QUESTION_BREAKS = ("NESTES TERMOS", "TERMOS EM QUE", "PEDE DEFERIMENTO", "RESPOSTA")
# Rodape/cabecalho de pagina do PJe, no formato real e so nas bordas da pagina: nao e
# texto do quesito nem o encerra. No meio da pagina a mesma expressao e conteudo.
_PJE_PAGE_MARK = re.compile(
    r"ASSINADO ELETRONICAMENTE POR\b.*|NUMERO DO DOCUMENTO:\s*\d*\s*|HTTPS?://\S*PJE\S*\s*|NUM\.\s*\d+\s*-\s*PAG\.?\s*\d+\s*"
)
_PAGE_EDGE = 4
# Palavras que nao fecham uma frase: a linha que termina nelas continua na seguinte.
_FUNCTION_WORDS = frozenset(
    "A AS O OS AO AOS DE DA DAS DO DOS E EM NA NAS NO NOS PARA PELA PELAS PELO PELOS POR COM QUE SE UM UMA SOBRE ENTRE OU".split()
)
# Limite de `$defs/text` em schemas/case-analysis-snapshot-v1.schema.json: um bloco
# maior nao cabe na Analise do Caso, entao nao e oferecido como proposta.
QUESTION_TEXT_MAX = 4096


def _dangling(line):
    """A linha nao fecha a frase (termina em ",;:-" ou em palavra funcional): a seguinte
    e continuacao, qualquer que seja a caixa -- inclusive em PDF todo em maiusculas."""
    stripped = folded(line).rstrip()
    if not stripped or stripped[-1] in "?.!)":
        return False
    if stripped[-1] in ",;:-–—":
        return True
    words = re.findall(r"[A-Z]+", stripped)
    return bool(words) and words[-1] in _FUNCTION_WORDS


def _document_lines(selected):
    """Linhas do documento sem as marcas de pagina do PJe (so nas bordas da pagina)."""
    lines = []
    for page in selected:
        raw = page.text.splitlines()
        previous_mark = False
        for index, line in enumerate(raw):
            text_line = folded(line)
            edge = index < _PAGE_EDGE or index >= len(raw) - _PAGE_EDGE
            mark = edge and (_PJE_PAGE_MARK.fullmatch(text_line) or (previous_mark and re.fullmatch(r"\d{10,}", text_line)))
            previous_mark = bool(mark)
            if not mark:
                lines.append((page, line))
    return lines


def extract_questions(document, pages):
    lines = _document_lines(document_pages(document, pages))
    proposals = []
    origin = None
    heading_line = None
    active = []
    number = None

    def flush(next_index):
        nonlocal active, number
        if active and origin and number:
            excerpt = "\n".join(line for _page, line in active)
            match = _NUMBER.match(active[0][1])
            text = "\n".join([match[2], *(line for _page, line in active[1:])]).rstrip()
            if len(excerpt) <= QUESTION_TEXT_MAX and len(text) <= QUESTION_TEXT_MAX:
                method = "NUMBERED_OCR_V1" if any("OCR" in str(page.extraction_mode) for page, _line in active) else "NUMBERED_NATIVE_TEXT_V1"
                source = QuestionSource(origin, number, active[0][0].number, active[-1][0].number, excerpt, method)
                identity = json.dumps([document.document_id, document.source_sha256, text, asdict(source)], ensure_ascii=False, sort_keys=True)
                proposals.append(QuestionProposal(
                    sha256(identity.encode()).hexdigest(), document.document_id, text, source,
                    section_heading=heading_line[1] if heading_line else None,
                    section_page=heading_line[0] if heading_line else None,
                    context_after="\n".join(line for _page, line in lines[next_index:next_index + 2]),
                ))
        active, number = [], None

    for index, (page, line) in enumerate(lines):
        numbered = _NUMBER.match(line)
        if active and not numbered and _dangling(active[-1][1]):
            active.append((page, line))  # a linha anterior nao fechou a frase
            continue
        text_line = folded(line)
        title = _TITLE_MARKS.sub("", text_line)
        structural = _STRUCTURAL_START.match(line) is not None or title != text_line.strip()
        sentence = text_line.rstrip().endswith(("?", ".", ";", "!"))
        # O dispositivo prevalece sobre o cabecalho: "Indefiro os seguintes quesitos da
        # re:" encerra a secao, nao abre uma secao da re.
        dispositive = structural and _DISPOSITIVE.fullmatch(title)
        heading = _HEADING.fullmatch(title) if structural and not dispositive else None
        if heading and numbered and heading.group(2) is not None:
            # Linha numerada so e titulo na forma pura ("1. QUESITOS DO JUIZO"); com
            # introducao ("2. Quanto aos quesitos do juizo:") e o proprio quesito.
            heading = None
        # Titulo de quesitos nao reconhecido -- inclusive numerado ("2. Quesitos
        # complementares da parte re, deferidos:") ou em prosa ("A re apresentou os
        # seguintes quesitos"): zera a origem. Falha fechada: omissao com aviso na UI,
        # nunca origem herdada da secao anterior.
        unrecognized = structural and not sentence and re.search(r"\bQUESITOS\b", title) is not None and (
            not numbered or title.split(maxsplit=1)[-1].startswith("QUESITOS")
        )
        if heading or dispositive or unrecognized:
            flush(index)
            designation = next((group for group in heading.groups() if group), "") if heading else ""
            # "Quesitos da re (fls. 120):" -- o complemento entre parenteses nao e parte
            # da designacao da parte.
            origin = _ORIGINS.get(re.sub(r"\s*\(.*\)\s*$", "", designation.rstrip(":").strip()))
            heading_line = (page.number, line.strip()) if origin else None
            continue
        if not line.strip() or (structural and text_line.startswith(_QUESTION_BREAKS)):
            flush(index + 1)
            continue
        if origin and numbered:
            flush(index)
            number = numbered[1]
            active = [(page, line)]
        elif active:
            active.append((page, line))
    flush(len(lines))
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
