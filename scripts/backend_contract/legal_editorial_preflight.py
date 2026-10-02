"""Pré-verificação jurídico-editorial do laudo (#272).

Perfil editorial de referência "Sistema Pericial — CNJ/TRF5"
(`LEGAL_EDITORIAL_PROFILE_V1`), apoiado em fontes de natureza diferente:
Recomendação CNJ 144/2023 (recomendatória), Lei 15.263/2025, art. 5º
(obrigatória para a administração pública), Manual Justiça Plural, cap. 4
(institucional) e orientações do TRF5 (institucionais). Nada aqui reescreve o
texto do perito: são avisos com a sugestão e o trecho exato.

Uma exceção não é preferência: marcador de pendência (`[INFORMAÇÃO NECESSÁRIA`,
`[VALIDAÇÃO DO PERITO`) bloqueia a emissão do Word final sempre, com ou sem
perfil, porque emitir um laudo com pendência aberta seria falso sucesso.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
import re
import unicodedata
from zipfile import BadZipFile, ZipFile

from .installation_settings import DEFAULT_LEGAL_EDITORIAL, LegalEditorialProfile


class PreflightSeverity(StrEnum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


class PreflightCode(StrEnum):
    PENDING_MARKER = "PENDING_MARKER"
    ACRONYM_NOT_DEFINED = "ACRONYM_NOT_DEFINED"
    LATINISM = "LATINISM"
    FOREIGN_TERM = "FOREIGN_TERM"
    JARGON = "JARGON"
    LONG_SENTENCE = "LONG_SENTENCE"
    LONG_PARAGRAPH = "LONG_PARAGRAPH"


@dataclass(frozen=True, slots=True)
class PreflightFinding:
    code: PreflightCode
    severity: PreflightSeverity
    section_id: str
    # Afirmação (claim_id), resposta a quesito ("ANSWER-n"), campo de capa ou
    # cabeçalho ("FIELD:COURT"), campo do perfil ("PROFILE:...") ou outro texto
    # do corpo ("BODY") onde está o trecho.
    location_id: str
    excerpt: str
    message: str
    suggestion: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    profile_id: str
    findings: tuple[PreflightFinding, ...]

    @property
    def blocking(self) -> bool:
        return any(item.severity is PreflightSeverity.BLOCKING for item in self.findings)


PENDING_MARKER = re.compile(
    r"\[\s*(?:INFORMA[CÇ][AÃ]O\s+NECESS[AÁ]RIA|(?:PEND[EÊ]NCIA\s+DE\s+)?VALIDA[CÇ][AÃ]O\s+DO\s+PERITO)",
    re.IGNORECASE,
)

# Expressão -> sugestão em linguagem simples.
LATINISMS = {
    "data venia": "com o devido respeito", "data maxima venia": "com o devido respeito",
    "ab initio": "desde o início", "in casu": "neste caso", "ex vi": "por força de", "ad hoc": "para este fim",
    "in loco": "no local", "a priori": "de antemão", "a posteriori": "depois", "ex officio": "de ofício",
    "ipsis litteris": "literalmente", "mutatis mutandis": "com as devidas adaptações",
    "sine qua non": "indispensável", "in fine": "no final", "ex nunc": "a partir de agora",
    "ex tunc": "desde a origem", "id est": "isto é", "exempli gratia": "por exemplo",
    "erga omnes": "para todos", "inaudita altera pars": "sem ouvir a outra parte",
}
FOREIGN_TERMS = {
    "checklist": "lista de verificação", "check-list": "lista de verificação", "layout": "disposição",
    "software": "programa", "feedback": "retorno", "deadline": "prazo", "performance": "desempenho",
    "upgrade": "melhoria", "know-how": "experiência", "design": "projeto", "drone": "aeronave remotamente pilotada",
    "status": "situação", "report": "relatório",
}
JARGON = {
    "outrossim": "além disso", "destarte": "assim", "hodiernamente": "hoje", "mister se faz": "é necessário",
    "precípuo": "principal", "supedâneo": "fundamento", "exordial": "petição inicial",
    "peça vestibular": "petição inicial", "egrégio": "(omitir)", "colendo": "(omitir)",
    "isto posto": "por isso", "ante o exposto": "assim", "consoante": "conforme", "mormente": "principalmente",
}
# Numerais romanos e unidades em maiúsculas não são siglas a desdobrar.
_NOT_ACRONYMS = frozenset({"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "PDF", "UF"})
# Maiúscula ASCII ou acentuada (U+00C0 a U+00DE), dígito, aspas ou parêntese.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u00c0-\u00de0-9\"“(])")
_WORD = re.compile(r"\w+(?:[-']\w+)*")
# Sigla candidata: 2 a 6 maiúsculas soltas. Depois de "/" ou "-" é a UF de
# "Recife/PE" ou "CREA-PE", que não se escreve por extenso.
_ACRONYM = re.compile(r"(?<![\w/\-])[A-Z]{2,6}(?![\w])")
_UPPER_WORD = re.compile(r"[A-Z\u00c0-\u00de]+")
# Abreviações usuais em laudo: o ponto delas não encerra a frase.
_ABBREVIATIONS = frozenset({
    "art", "arts", "inc", "incs", "al", "fl", "fls", "p", "pp", "pág", "págs", "n", "nº", "no", "cf", "ex",
    "sr", "sra", "srs", "dr", "dra", "drs", "prof", "profa", "eng", "arq", "des", "min", "av", "proc", "vol", "cap",
})


def _sentences(paragraph: str) -> list[str]:
    pieces = _SENTENCE_END.split(paragraph)
    sentences: list[str] = []
    for piece in pieces:
        if sentences:
            last = re.search(r"(\w+)\.$", sentences[-1].rstrip())
            if last is not None and last.group(1).casefold() in _ABBREVIATIONS:
                sentences[-1] = f"{sentences[-1]} {piece}"
                continue
        sentences.append(piece)
    return sentences


def _upper_run(text: str, start: int, end: int) -> list[str]:
    """As palavras em maiúsculas vizinhas da sigla, na mesma sequência."""
    words = [match.group() for match in re.finditer(r"\S+", text)]
    spans = [match.span() for match in re.finditer(r"\S+", text)]
    index = next((position for position, (left, right) in enumerate(spans) if left <= start < right), None)
    if index is None:
        return []

    def upper(word: str) -> list[str] | None:
        parts = _UPPER_WORD.findall(word)
        letters = "".join(char for char in word if char.isalpha())
        return parts if letters and letters.isupper() else None

    run = list(upper(words[index]) or [])
    for step in (-1, 1):
        position = index + step
        while 0 <= position < len(words) and (parts := upper(words[position])) is not None:
            run.extend(parts)
            position += step
    return run


def _folded(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(c))


def _excerpt(text: str, start: int, end: int, *, reach: int = 60) -> str:
    left = max(0, start - reach)
    right = min(len(text), end + reach)
    return ("…" if left else "") + text[left:right].strip() + ("…" if right < len(text) else "")


def _terms(text: str, folded: str, table: dict[str, str]):
    for term, suggestion in table.items():
        key = _folded(term)
        for match in re.finditer(r"(?<!\w)" + re.escape(key) + r"(?!\w)", folded):
            yield match.start(), match.end(), term, suggestion


def _units(report) -> list[tuple[str, str, str]]:
    """(seção, local, texto) de cada afirmação e resposta, na ordem do laudo."""
    order = {section.section_id: section.order for section in report.sections}
    units = [(claim.section_id, claim.claim_id, claim.text) for claim in report.claims]
    units.extend((answer.section_id, f"ANSWER-{index}", answer.text) for index, answer in enumerate(report.answers, 1))
    return sorted(units, key=lambda item: order.get(item[0], 0))


def legal_editorial_preflight(report, profile: LegalEditorialProfile | None = None) -> PreflightReport:
    profile = profile or DEFAULT_LEGAL_EDITORIAL
    if type(profile) is not LegalEditorialProfile:
        raise TypeError("expected LegalEditorialProfile")
    findings: list[PreflightFinding] = []
    seen: set[str] = set()

    def add(code, severity, section, location, excerpt, message, suggestion):
        findings.append(PreflightFinding(code, severity, section, location, excerpt, message, suggestion))

    for section, location, text in _units(report):
        folded = _folded(text)
        for match in PENDING_MARKER.finditer(text):
            closing = text.find("]", match.end())
            end = closing + 1 if closing != -1 else match.end()
            add(PreflightCode.PENDING_MARKER, PreflightSeverity.BLOCKING, section, location, text[match.start():end],
                "Pendência aberta no texto. O Word final não é emitido enquanto ela existir.",
                "Complete a informação ou retire o trecho e registre a limitação.")
        if profile.check_latinisms:
            for start, end, term, suggestion in _terms(text, folded, LATINISMS):
                add(PreflightCode.LATINISM, PreflightSeverity.WARNING, section, location, _excerpt(text, start, end),
                    f"Expressão latina “{term}”.", f"Prefira “{suggestion}”.")
        if profile.check_foreign_terms:
            for start, end, term, suggestion in _terms(text, folded, FOREIGN_TERMS):
                add(PreflightCode.FOREIGN_TERM, PreflightSeverity.WARNING, section, location, _excerpt(text, start, end),
                    f"Termo estrangeiro “{term}”.", f"Prefira “{suggestion}” ou destaque o termo em itálico no Word.")
        if profile.check_jargon:
            for start, end, term, suggestion in _terms(text, folded, JARGON):
                add(PreflightCode.JARGON, PreflightSeverity.WARNING, section, location, _excerpt(text, start, end),
                    f"Expressão rebuscada “{term}”.", f"Prefira “{suggestion}”.")
        if profile.check_acronyms:
            for match in _ACRONYM.finditer(text):
                acronym = match.group()
                if acronym in _NOT_ACRONYMS or acronym in seen:
                    continue
                # Nome ou título em caixa-alta ("CAIXA ECONOMICA FEDERAL",
                # "LAUDO PERICIAL") não é sigla; siglas vizinhas ("ABNT NBR") são.
                if any(len(word) >= 7 for word in _upper_run(text, match.start(), match.end())):
                    continue
                seen.add(acronym)
                spelled_after = text[match.end():match.end() + 2] == " ("
                spelled_before = text[match.start() - 1:match.start()] == "(" and text[match.end():match.end() + 1] == ")"
                if spelled_after or spelled_before:
                    continue
                add(PreflightCode.ACRONYM_NOT_DEFINED, PreflightSeverity.WARNING, section, location,
                    _excerpt(text, match.start(), match.end()),
                    f"A sigla “{acronym}” aparece sem o nome por extenso na primeira ocorrência.",
                    f"Escreva o nome completo seguido de ({acronym}) na primeira vez.")
        for paragraph in (item for item in text.split("\n") if item.strip()):
            words = len(_WORD.findall(paragraph))
            if profile.check_long_paragraphs and words > profile.long_paragraph_words:
                add(PreflightCode.LONG_PARAGRAPH, PreflightSeverity.WARNING, section, location, _excerpt(paragraph, 0, 0, reach=120),
                    f"Parágrafo com {words} palavras (referência: até {profile.long_paragraph_words}).",
                    "Divida o parágrafo por assunto.")
            if profile.check_long_sentences:
                for sentence in _sentences(paragraph):
                    count = len(_WORD.findall(sentence))
                    if count > profile.long_sentence_words:
                        add(PreflightCode.LONG_SENTENCE, PreflightSeverity.WARNING, section, location, _excerpt(sentence, 0, 0, reach=120),
                            f"Frase com {count} palavras (referência: até {profile.long_sentence_words}).",
                            "Divida a frase; uma ideia por frase facilita a leitura.")
    for section, location, label, excerpt in _pending_outside_units(report):
        add(PreflightCode.PENDING_MARKER, PreflightSeverity.BLOCKING, section, location, excerpt,
            f"Pendência aberta {label}. O Word final não é emitido enquanto ela existir.",
            "Complete a informação na etapa de origem (processo, participantes, perfil profissional ou laudo).")
    return PreflightReport(profile.profile_id, tuple(findings))


def has_pending_marker(text: str) -> bool:
    return PENDING_MARKER.search(text) is not None


def _marker_excerpts(text: str) -> list[str]:
    excerpts = []
    for match in PENDING_MARKER.finditer(text):
        closing = text.find("]", match.end())
        excerpts.append(text[match.start():closing + 1 if closing != -1 else match.end()])
    return excerpts


_FIELD_LABELS = {
    "PROCESS_NUMBER": "no número do processo (capa)",
    "COURT": "no juízo (capa)",
    "PARTICIPANTS_ACTIVE": "no polo ativo (capa)",
    "PARTICIPANTS_PASSIVE": "no polo passivo (capa)",
    "PARTICIPANTS_OTHER": "em outros participantes (capa)",
    "EXPERT_FULL_NAME": "no nome do perito",
    "EXPERT_TITLE": "no título profissional",
    "EXPERT_REGISTRATION": "no registro profissional",
    "EXPERT_COURT_REGISTRATION": "no cadastro no tribunal",
    "REPORT_ID": "na identificação do laudo",
}


def _strings(value, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}" if path else key)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def _pending_outside_units(report):
    """Marcadores fora das afirmações e respostas: capa, cabeçalho e demais textos.

    O Word final leva também os campos do modelo (juízo, polos, identidade do
    perito) e textos do corpo que não são afirmações (participantes, imóvel,
    referências, legendas, quesitos). Pendência em qualquer um deles bloqueia.
    """
    from .delivery_renderer import professional_report_blocks
    from .report_foundation import expert_profile_to_mapping
    from .report_template import template_field_texts
    fields = template_field_texts(report)
    profile_texts = dict(_strings(expert_profile_to_mapping(report.expert_profile)))
    for field, text in fields.items():
        for excerpt in _marker_excerpts(text):
            yield "COVER", f"FIELD:{field}", _FIELD_LABELS.get(field, f"no campo {field}"), excerpt
    # Linhas de identidade do cabeçalho (nome na assinatura, cadastros, contato)
    # vêm do perfil; o que já saiu por um campo acima não se repete.
    shown = Counter(excerpt for text in fields.values() for excerpt in _marker_excerpts(text))
    for name, text in profile_texts.items():
        for excerpt in _marker_excerpts(text):
            if shown[excerpt]:
                shown[excerpt] -= 1
                continue
            yield "IDENTITY", f"PROFILE:{name}", "no perfil profissional (cabeçalho ou assinatura)", excerpt
    in_units = Counter(excerpt for _section, _location, text in _units(report) for excerpt in _marker_excerpts(text))
    for block in professional_report_blocks(report):
        for text in block.paragraph_texts:
            for excerpt in _marker_excerpts(text):
                if in_units[excerpt]:
                    in_units[excerpt] -= 1
                    continue
                yield "BODY", "BODY", "num texto do laudo fora das afirmações", excerpt


def report_pending_markers(report) -> tuple[str, ...]:
    """Marcadores de pendência em qualquer texto que o Word final apresentaria."""
    found = [excerpt for _section, _location, text in _units(report) for excerpt in _marker_excerpts(text)]
    found.extend(excerpt for *_rest, excerpt in _pending_outside_units(report))
    return tuple(found)


_WORD_TEXT_PARTS = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml")
_PARAGRAPH = re.compile(rb"<w:p[ >].*?</w:p>", re.DOTALL)
_RUN_TEXT = re.compile(rb"<w:t(?: [^>]*)?>([^<]*)</w:t>")


def word_pending_markers(package: bytes) -> tuple[str, ...]:
    """Última barreira: marcadores no Word já vinculado (corpo, cabeçalhos e rodapés).

    Cobre o que nenhuma lista de campos prevê, como texto fixo de um modelo
    personalizado. Um marcador pode estar partido em vários trechos do mesmo
    parágrafo, então o texto é juntado por parágrafo.
    """
    from html import unescape
    try:
        with ZipFile(BytesIO(package)) as archive:
            parts = [archive.read(name) for name in archive.namelist() if _WORD_TEXT_PARTS.fullmatch(name)]
    except (BadZipFile, KeyError) as exc:
        raise ValueError("word package cannot be read for pending markers") from exc
    found = []
    for xml in parts:
        for paragraph in _PARAGRAPH.findall(xml):
            text = unescape(b"".join(_RUN_TEXT.findall(paragraph)).decode("utf-8"))
            found.extend(_marker_excerpts(text))
    return tuple(found)
