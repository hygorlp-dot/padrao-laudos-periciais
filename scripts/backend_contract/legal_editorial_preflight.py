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

from dataclasses import dataclass
from enum import StrEnum
import re
import unicodedata

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
    # Afirmação (claim_id) ou resposta a quesito ("ANSWER-n") onde está o trecho.
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
            words = list(_WORD.finditer(text))
            for index, match in enumerate(words):
                acronym = match.group()
                if not (2 <= len(acronym) <= 6 and acronym.isalpha() and acronym.isupper()) or acronym in _NOT_ACRONYMS or acronym in seen:
                    continue
                # Nome em caixa-alta ("CAIXA ECONOMICA FEDERAL") não é sigla.
                neighbours = [words[item].group() for item in (index - 1, index + 1) if 0 <= item < len(words)]
                if any(len(item) > 1 and item.isalpha() and item.isupper() for item in neighbours):
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
                for sentence in _SENTENCE_END.split(paragraph):
                    count = len(_WORD.findall(sentence))
                    if count > profile.long_sentence_words:
                        add(PreflightCode.LONG_SENTENCE, PreflightSeverity.WARNING, section, location, _excerpt(sentence, 0, 0, reach=120),
                            f"Frase com {count} palavras (referência: até {profile.long_sentence_words}).",
                            "Divida a frase; uma ideia por frase facilita a leitura.")
    return PreflightReport(profile.profile_id, tuple(findings))


def has_pending_marker(text: str) -> bool:
    return PENDING_MARKER.search(text) is not None


def report_pending_markers(report) -> tuple[str, ...]:
    """Marcadores de pendência em qualquer texto que o Word final apresentaria."""
    from .delivery_renderer import professional_report_blocks
    found = []
    for block in professional_report_blocks(report):
        for text in block.paragraph_texts:
            found.extend(match.group() for match in PENDING_MARKER.finditer(text))
    return tuple(found)
