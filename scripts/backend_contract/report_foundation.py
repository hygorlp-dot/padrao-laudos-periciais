"""Canonical report graph: presentation without upstream authority promotion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, TypeVar
from .property_record import PropertyRecord, property_record_from_mapping
from .process_participants import CaseParticipant, participant_from_mapping, participant_to_mapping
from .professional_report_presentation import ProfessionalReportCapture, capture_from_mapping, professional_report_projection


REPORT_SNAPSHOT_ARTIFACT_KIND = "REPORT_SNAPSHOT_V1"
REPORT_SNAPSHOT_ARTIFACT_ID = "REPORT-SNAPSHOT"
EXPERT_PROFILE_ARTIFACT_KIND = "EXPERT_MASTER_PROFILE_V1"
EXPERT_PROFILE_ARTIFACT_ID = "EXPERT-PROFILE"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class AuthorityClass(StrEnum):
    ALLEGED = "ALLEGED"
    DECIDED_BY_COURT = "DECIDED_BY_COURT"
    DOCUMENTED = "DOCUMENTED"
    OBSERVED = "OBSERVED"
    MEASURED = "MEASURED"
    TECHNICALLY_FOUND = "TECHNICALLY_FOUND"
    PROFESSIONALLY_CONCLUDED = "PROFESSIONALLY_CONCLUDED"


class ReportState(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ReviewAction(StrEnum):
    MARK_REVIEWED = "MARK_REVIEWED"
    APPROVE = "APPROVE"
    SUPERSEDE = "SUPERSEDE"


class ContextStatus(StrEnum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_SOURCE_AUTHORITY = {
    "ALLEGATION": AuthorityClass.ALLEGED,
    "COURT_DECISION": AuthorityClass.DECIDED_BY_COURT,
    "CASE_DOCUMENT": AuthorityClass.DOCUMENTED,
    "FIELD_OBSERVATION": AuthorityClass.OBSERVED,
    "MEASUREMENT": AuthorityClass.MEASURED,
    "PATHOLOGY": AuthorityClass.TECHNICALLY_FOUND,
    "TECHNICAL_FINDING": AuthorityClass.TECHNICALLY_FOUND,
    "PROFESSIONAL_DECISION": AuthorityClass.PROFESSIONALLY_CONCLUDED,
}

_SECTION_ORDER = (
    "IDENTIFICATION", "PROCEDURAL_CONTEXT", "PURPOSE_OBJECT", "SCOPE",
    "DOCUMENTS_EVIDENCE", "METHODOLOGY", "INSPECTION", "TECHNICAL_ANALYSIS",
    "TECHNICAL_FINDINGS", "ANSWERS_TO_QUESTIONS", "CONCLUSIONS",
    "LIMITATIONS_RESERVATIONS", "REFERENCES", "ATTACHMENTS",
)
_CPC473_REQUIRED = {"IDENTIFICATION", "PROCEDURAL_CONTEXT", "PURPOSE_OBJECT", "DOCUMENTS_EVIDENCE", "INSPECTION", "TECHNICAL_ANALYSIS", "TECHNICAL_FINDINGS", "ANSWERS_TO_QUESTIONS"}
_CONTEXT_FIELDS = {"PROCESS_NUMBER", "COURT", "PARTIES", "ADDRESSES", "CLAIM_AND_GROUNDS", "REQUESTS"}


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _texts(values: tuple[str, ...], *, allow_empty: bool = True) -> None:
    if type(values) is not tuple or (not allow_empty and not values) or any(not _text(value) for value in values) or len(values) != len(set(values)):
        raise ValueError("identity collection is invalid")


def _timestamp(value: object) -> None:
    if not _text(value):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp requires timezone")


def _all_text(instance: object, names: tuple[str, ...]) -> None:
    if not all(_text(getattr(instance, name)) for name in names):
        raise ValueError(f"{type(instance).__name__} is invalid")


def report_claim_for_source(*, claim_id: str, provenance_id: str, section_id: str, text: str, source_kind: str, source_id: str, source_revision: int) -> "ReportClaim":
    try:
        authority = _SOURCE_AUTHORITY[source_kind]
    except KeyError as exc:
        raise ValueError("report source kind is invalid") from exc
    return ReportClaim(claim_id, section_id, text, authority, (ReportProvenance(provenance_id, source_kind, source_id, source_revision),))


@dataclass(frozen=True, slots=True)
class ReportSourceSnapshot:
    workspace_id: str
    case_analysis_snapshot_id: str
    case_analysis_revision: int
    case_analysis_digest: str
    inspection_session_id: str
    inspection_session_revision: int
    inspection_session_digest: str
    technical_snapshot_id: str
    technical_snapshot_revision: int
    technical_snapshot_digest: str
    construction_defect_analysis_snapshot_id: str | None
    construction_defect_analysis_revision: int | None
    construction_defect_analysis_digest: str | None
    expert_profile_id: str
    expert_profile_revision: int
    expert_profile_digest: str

    def __post_init__(self):
        _all_text(self, ("workspace_id", "case_analysis_snapshot_id", "inspection_session_id", "technical_snapshot_id", "expert_profile_id"))
        revisions = (self.case_analysis_revision, self.inspection_session_revision, self.technical_snapshot_revision, self.expert_profile_revision)
        if any(type(value) is not int or value < 1 for value in revisions):
            raise ValueError("report source revision is invalid")
        digests = (self.case_analysis_digest, self.inspection_session_digest, self.technical_snapshot_digest, self.expert_profile_digest)
        if any(type(value) is not str or _SHA256.fullmatch(value) is None for value in digests):
            raise ValueError("report source digest is invalid")
        pathology_binding = (
            self.construction_defect_analysis_snapshot_id,
            self.construction_defect_analysis_revision,
            self.construction_defect_analysis_digest,
        )
        if any(value is None for value in pathology_binding):
            if any(value is not None for value in pathology_binding):
                raise ValueError("report pathology binding is incomplete")
        elif (
            not _text(self.construction_defect_analysis_snapshot_id)
            or type(self.construction_defect_analysis_revision) is not int
            or self.construction_defect_analysis_revision < 1
            or type(self.construction_defect_analysis_digest) is not str
            or _SHA256.fullmatch(self.construction_defect_analysis_digest) is None
        ):
            raise ValueError("report pathology binding is invalid")


_UF = re.compile(r"[A-Z]{2}")
_EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}")
_PROFILE_TEXT_LIMIT = 200


def _optional_text(value: object, limit: int = _PROFILE_TEXT_LIMIT) -> bool:
    return value is None or (_text(value) and value == value.strip() and len(value) <= limit)


@dataclass(frozen=True, slots=True)
class CourtRegistration:
    """Um cadastro de perito num tribunal; um profissional atua em varios."""
    court: str
    registration: str
    label: str
    active: bool
    # Entrada vinda do campo unico `court_registration` antigo: o tribunal nao
    # foi informado separadamente e o texto e preservado exatamente.
    legacy: bool = False

    def __post_init__(self):
        if not _optional_text(self.registration) or self.registration is None or not _optional_text(self.label):
            raise ValueError("court registration is invalid")
        if type(self.active) is not bool or type(self.legacy) is not bool:
            raise ValueError("court registration flags are invalid")
        if self.legacy:
            if self.court != "":
                raise ValueError("a legacy court registration has no separate court")
        elif not _optional_text(self.court, 80) or self.court is None:
            raise ValueError("court registration court is invalid")

    @property
    def line(self) -> str:
        return self.registration if self.legacy else f"{self.court} — {self.registration}"


@dataclass(frozen=True, slots=True)
class ProfessionalContact:
    email: str | None
    phone: str | None
    office_name: str | None
    city: str | None
    state: str | None

    def __post_init__(self):
        if not all(_optional_text(getattr(self, name)) for name in ("email", "phone", "office_name", "city", "state")):
            raise ValueError("professional contact is invalid")
        if self.email is not None and _EMAIL.fullmatch(self.email) is None:
            raise ValueError("professional e-mail is invalid")
        if self.state is not None and _UF.fullmatch(self.state) is None:
            raise ValueError("professional contact state is invalid")

    @property
    def line(self) -> str:
        place = "/".join(item for item in (self.city, self.state) if item)
        return " · ".join(item for item in (self.email, self.phone, self.office_name, place) if item)


@dataclass(frozen=True, slots=True)
class ProfilePresentation:
    """O que o documento mostra do perfil; coletar uma vez nao e expor sempre."""
    show_registration_cover: bool
    show_registration_signature: bool
    show_registration_header: bool
    show_court_registration_header: bool
    show_phone_header: bool
    show_email_header: bool
    show_email_footer: bool

    def __post_init__(self):
        if any(type(getattr(self, item.name)) is not bool for item in fields(self)):
            raise ValueError("profile presentation is invalid")


DEFAULT_PROFILE_PRESENTATION = ProfilePresentation(True, True, True, False, False, False, False)


@dataclass(frozen=True, slots=True)
class ExpertMasterProfile:
    profile_id: str
    revision: int
    full_name: str
    professional_title: str
    registration: str
    court_registration: str
    contact_line: str
    # Evolucao compativel (#270): ausente significa perfil anterior, gravado sem
    # estes campos; o mapping omite a chave para preservar o digest antigo.
    signature_name: str | None = None
    professional_council: str | None = None
    council_state: str | None = None
    national_registration: str | None = None
    court_registrations: tuple[CourtRegistration, ...] | None = None
    contact: ProfessionalContact | None = None
    presentation: ProfilePresentation | None = None

    def __post_init__(self):
        _all_text(self, ("profile_id", "full_name", "professional_title", "registration", "court_registration", "contact_line"))
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("expert profile revision is invalid")
        if not all(_optional_text(getattr(self, name), 120) for name in ("signature_name", "professional_council", "national_registration")):
            raise ValueError("expert profile identity is invalid")
        if self.council_state is not None and (type(self.council_state) is not str or _UF.fullmatch(self.council_state) is None):
            raise ValueError("expert profile council state is invalid")
        if self.court_registrations is not None and (
            type(self.court_registrations) is not tuple or not self.court_registrations or len(self.court_registrations) > 32
            or any(type(item) is not CourtRegistration for item in self.court_registrations)
        ):
            raise ValueError("expert court registrations are invalid")
        if self.contact is not None and type(self.contact) is not ProfessionalContact:
            raise ValueError("expert contact is invalid")
        if self.presentation is not None and type(self.presentation) is not ProfilePresentation:
            raise ValueError("expert presentation is invalid")

    @property
    def display_signature_name(self) -> str:
        return self.signature_name or self.full_name

    @property
    def effective_presentation(self) -> ProfilePresentation:
        return self.presentation or DEFAULT_PROFILE_PRESENTATION

    @property
    def active_court_registrations(self) -> tuple[CourtRegistration, ...]:
        if self.court_registrations is None:
            return (CourtRegistration("", self.court_registration, "Cadastro informado", True, True),)
        return tuple(item for item in self.court_registrations if item.active)


def court_registration_line(entries: tuple[CourtRegistration, ...]) -> str:
    """A linha de exibicao derivada da colecao: fonte unica, sem digitar duas vezes."""
    return "; ".join(item.line for item in entries if item.active) or "; ".join(item.line for item in entries)


def legacy_court_registrations(value: str) -> tuple[CourtRegistration, ...]:
    """Migracao explicita: o texto antigo vira uma entrada legada, sem perda."""
    return (CourtRegistration("", value.strip(), "Cadastro informado anteriormente", True, True),)


EDITORIAL_PRESET_ID = "JUSTICA_PLURAL_CHAPTER_4"
EDITORIAL_CUSTOM_ID = "CUSTOM"
EDITORIAL_FONTS = ("Arial", "Calibri", "Cambria", "Georgia", "Times New Roman", "Verdana")
EDITORIAL_ALIGNMENTS = ("JUSTIFIED", "LEFT")
EDITORIAL_LINE_SPACINGS = (1.0, 1.15, 1.5, 2.0)


def _number(value: object) -> bool:
    return type(value) in (int, float) and value == value


def _within(value: object, low: float, high: float) -> bool:
    # Two decimals at most: a profile is a typographic choice, not a measurement.
    return _number(value) and low <= value <= high and round(value * 100) == value * 100


@dataclass(frozen=True, slots=True)
class EditorialTypography:
    """Heading sizes and paragraph spacing; absent means the preset's own."""
    heading1_pt: int
    heading2_pt: int
    heading3_pt: int
    headings_bold: bool
    heading_space_before_pt: int
    heading_space_after_pt: int
    paragraph_space_after_pt: int

    def __post_init__(self):
        sizes = ((self.heading1_pt, 12, 20), (self.heading2_pt, 11, 16), (self.heading3_pt, 10, 14))
        spaces = (self.heading_space_before_pt, self.heading_space_after_pt, self.paragraph_space_after_pt)
        if any(type(value) is not int or not low <= value <= high for value, low, high in sizes):
            raise ValueError("editorial heading sizes are invalid")
        if not self.heading1_pt >= self.heading2_pt >= self.heading3_pt:
            raise ValueError("editorial heading hierarchy is invalid")
        if type(self.headings_bold) is not bool or any(type(value) is not int or not 0 <= value <= 36 for value in spaces):
            raise ValueError("editorial spacing is invalid")


DEFAULT_EDITORIAL_TYPOGRAPHY = EditorialTypography(14, 12, 11, True, 12, 6, 6)


class HeadingCase(StrEnum):
    """Caixa do titulo como politica editorial por nivel, nunca hard-coded."""
    PRESERVE = "PRESERVE"
    UPPER = "UPPER"
    TITLE_CASE = "TITLE_CASE"
    SENTENCE_CASE = "SENTENCE_CASE"


_LOWERCASE_TITLE_WORDS = frozenset({"a", "à", "ao", "aos", "as", "às", "com", "da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos", "o", "os", "ou", "para", "por", "sem", "sob", "sobre"})


def apply_heading_case(text: str, case: HeadingCase) -> str:
    """Aplica a caixa sem mudar palavras; siglas em maiusculas sao preservadas."""
    if case is HeadingCase.PRESERVE:
        return text
    if case is HeadingCase.UPPER:
        return text.upper()
    words = text.split(" ")
    result = []
    for index, word in enumerate(words):
        if len(word) > 1 and word.isupper():
            result.append(word)
        elif case is HeadingCase.SENTENCE_CASE:
            result.append(word[:1].upper() + word[1:].lower() if index == 0 else word.lower())
        elif index > 0 and word.lower() in _LOWERCASE_TITLE_WORDS:
            result.append(word.lower())
        else:
            result.append(word[:1].upper() + word[1:].lower())
    return " ".join(result)


@dataclass(frozen=True, slots=True)
class EditorialLayout:
    """Geometria de pagina, controle de paragrafo, caixa dos titulos e citacao longa.

    Ausente no perfil significa comportamento anterior (`LEGACY_EDITORIAL_LAYOUT`):
    cabecalho e rodape a 1,25 cm e titulo 1 em caixa-alta. Os valores padrao novos
    seguem `padrao-visual-word.md` (cabecalho 1,25 cm, rodape 0,87 cm) e
    `padrao-estrutura-laudo.md` (caixa-alta so no titulo de capitulo).
    """
    header_distance_cm: float
    footer_distance_cm: float
    paragraph_space_before_pt: int
    keep_with_next: bool
    widow_orphan_control: bool
    heading1_case: HeadingCase
    heading2_case: HeadingCase
    heading3_case: HeadingCase
    heading1_page_break_before: bool
    long_quote_indent_cm: float
    long_quote_font_pt_delta: int
    long_quote_line_spacing: float

    def __post_init__(self):
        if not _within(self.header_distance_cm, 0.5, 3) or not _within(self.footer_distance_cm, 0.5, 3):
            raise ValueError("editorial header and footer distances are invalid")
        if type(self.paragraph_space_before_pt) is not int or not 0 <= self.paragraph_space_before_pt <= 24:
            raise ValueError("editorial paragraph spacing is invalid")
        if any(type(value) is not bool for value in (self.keep_with_next, self.widow_orphan_control, self.heading1_page_break_before)):
            raise ValueError("editorial paragraph controls are invalid")
        if any(type(value) is not HeadingCase for value in (self.heading1_case, self.heading2_case, self.heading3_case)):
            raise ValueError("editorial heading case is invalid")
        if not _within(self.long_quote_indent_cm, 0, 6) or type(self.long_quote_font_pt_delta) is not int or not 0 <= self.long_quote_font_pt_delta <= 3 or self.long_quote_line_spacing not in EDITORIAL_LINE_SPACINGS:
            raise ValueError("editorial long quote is invalid")


LEGACY_EDITORIAL_LAYOUT = EditorialLayout(1.25, 1.25, 0, True, True, HeadingCase.UPPER, HeadingCase.PRESERVE, HeadingCase.PRESERVE, False, 4.0, 1, 1.0)
DEFAULT_EDITORIAL_LAYOUT = EditorialLayout(1.25, 0.87, 0, True, True, HeadingCase.UPPER, HeadingCase.PRESERVE, HeadingCase.PRESERVE, False, 4.0, 1, 1.0)


@dataclass(frozen=True, slots=True)
class EditorialProfile:
    profile_id: str
    font_family: str
    body_font_pt: int
    table_font_pt: int
    caption_font_pt: int
    alignment: str
    line_spacing: float
    first_line_indent_cm: float
    page_size: str
    margin_top_cm: float
    margin_bottom_cm: float
    margin_left_cm: float
    margin_right_cm: float
    hyphenation: bool
    overrides: tuple[str, ...]
    # Written only when the expert configured it, so every profile persisted
    # before keeps its exact mapping and digest.
    typography: EditorialTypography | None = None
    layout: EditorialLayout | None = None

    def __post_init__(self):
        _all_text(self, ("profile_id", "font_family", "alignment", "page_size"))
        if self.profile_id not in (EDITORIAL_PRESET_ID, EDITORIAL_CUSTOM_ID) or self.page_size != "A4":
            raise ValueError("editorial profile default is invalid")
        if self.font_family not in EDITORIAL_FONTS or self.alignment not in EDITORIAL_ALIGNMENTS:
            raise ValueError("editorial profile default is invalid")
        sizes = ((self.body_font_pt, 10, 14), (self.table_font_pt, 8, 12), (self.caption_font_pt, 8, 11))
        if any(type(value) is not int or not low <= value <= high for value, low, high in sizes):
            raise ValueError("editorial typography is invalid")
        margins = (self.margin_top_cm, self.margin_bottom_cm, self.margin_left_cm, self.margin_right_cm)
        if self.line_spacing not in EDITORIAL_LINE_SPACINGS or not _within(self.first_line_indent_cm, 0, 3) or not all(_within(value, 1.5, 4) for value in margins):
            raise ValueError("editorial geometry is invalid")
        if type(self.hyphenation) is not bool or self.hyphenation:
            raise ValueError("automatic hyphenation must be disabled")
        if self.typography is not None and type(self.typography) is not EditorialTypography:
            raise ValueError("editorial typography is invalid")
        if self.layout is not None and type(self.layout) is not EditorialLayout:
            raise ValueError("editorial layout is invalid")
        # The preset keeps its meaning: its identity names exactly its values.
        if self.profile_id == EDITORIAL_PRESET_ID and (
            (self.font_family, self.alignment, self.body_font_pt, self.table_font_pt, self.caption_font_pt) != ("Arial", "JUSTIFIED", 11, 10, 9)
            or (self.line_spacing, self.first_line_indent_cm) != (1.15, 1.25)
            or margins != (2, 2, 3, 2)
            or self.typography not in (None, DEFAULT_EDITORIAL_TYPOGRAPHY)
            or self.layout not in (None, DEFAULT_EDITORIAL_LAYOUT)
        ):
            raise ValueError("editorial preset values cannot change")
        _texts(self.overrides)

    @property
    def effective_typography(self) -> EditorialTypography:
        return self.typography or DEFAULT_EDITORIAL_TYPOGRAPHY

    @property
    def effective_layout(self) -> EditorialLayout:
        return self.layout or LEGACY_EDITORIAL_LAYOUT


@dataclass(frozen=True, slots=True)
class ContextCompletenessItem:
    context_id: str
    field: str
    required: bool
    status: ContextStatus
    source_id: str | None
    note: str

    def __post_init__(self):
        _all_text(self, ("context_id", "field", "note"))
        if type(self.required) is not bool:
            raise ValueError("process context requirement is invalid")
        if self.status is ContextStatus.PRESENT:
            if not _text(self.source_id):
                raise ValueError("present process context requires source")
        elif self.source_id is not None:
            raise ValueError("absent process context cannot claim source")


@dataclass(frozen=True, slots=True)
class ReportSection:
    section_id: str
    kind: str
    title: str
    order: int
    required_by_cpc473: bool

    def __post_init__(self):
        _all_text(self, ("section_id", "kind", "title"))
        if self.kind not in _SECTION_ORDER or type(self.order) is not int or self.order < 1 or type(self.required_by_cpc473) is not bool:
            raise ValueError("report section is invalid")


@dataclass(frozen=True, slots=True)
class ReportProvenance:
    provenance_id: str
    source_kind: str
    source_id: str
    source_revision: int

    def __post_init__(self):
        _all_text(self, ("provenance_id", "source_kind", "source_id"))
        if self.source_kind not in _SOURCE_AUTHORITY or type(self.source_revision) is not int or self.source_revision < 1:
            raise ValueError("report provenance is invalid")


@dataclass(frozen=True, slots=True)
class ReportClaim:
    claim_id: str
    section_id: str
    text: str
    authority: AuthorityClass
    provenance: tuple[ReportProvenance, ...]

    def __post_init__(self):
        _all_text(self, ("claim_id", "section_id", "text"))
        if type(self.provenance) is not tuple or not self.provenance or any(type(item) is not ReportProvenance for item in self.provenance):
            raise ValueError("material report claim requires provenance")
        if any(_SOURCE_AUTHORITY[item.source_kind] is not self.authority for item in self.provenance):
            raise ValueError("report text authority promotion is forbidden")


@dataclass(frozen=True, slots=True)
class ReportAnswer:
    answer_id: str
    section_id: str
    question_id: str
    text: str
    finding_id: str
    evidence_ids: tuple[str, ...]
    method_ids: tuple[str, ...]
    decision_id: str
    claim_ids: tuple[str, ...]
    # The question as the case record states it, captured from the bound case
    # analysis when the answer is written, so the report can present it without
    # an internal identity.  Answers written before it existed carry None and
    # keep their exact persisted mapping (the key is omitted, never nulled).
    question_text: str | None = None

    def __post_init__(self):
        _all_text(self, ("answer_id", "section_id", "question_id", "text", "finding_id", "decision_id"))
        if self.question_text is not None and not _text(self.question_text):
            raise ValueError("report answer question text is invalid")
        try:
            for values in (self.evidence_ids, self.method_ids, self.claim_ids):
                _texts(values, allow_empty=False)
        except ValueError as exc:
            raise ValueError("report answer traceability is incomplete") from exc


REFERENCE_KINDS = (
    "TECHNICAL_STANDARD", "LEGAL_REFERENCE", "TECHNICAL_LITERATURE",
    "MANUFACTURER_DOCUMENTATION", "OTHER_REFERENCE",
)
_REFERENCE_LIMITS = {"author": 300, "title": 500, "identifier": 120, "details": 500}


def _sentence(text: str) -> str:
    return text.strip().rstrip(".") + "."


@dataclass(frozen=True, slots=True)
class ReportReference:
    """A standard, law or work the expert relies on -- never a case document.

    Case documents stay evidence under their own authority; a reference is what
    the expert cites for criteria and method, listed in the references section.
    """
    reference_id: str
    kind: str
    author: str
    title: str
    year: int | None
    identifier: str | None
    details: str | None

    def __post_init__(self):
        _all_text(self, ("reference_id", "kind", "author", "title"))
        if self.kind not in REFERENCE_KINDS or (self.year is not None and (type(self.year) is not int or not 1800 <= self.year <= 2200)):
            raise ValueError("report reference is invalid")
        for name, limit in _REFERENCE_LIMITS.items():
            value = getattr(self, name)
            if value is not None and (not _text(value) or value != value.strip() or len(value) > limit):
                raise ValueError("report reference is invalid")

    @property
    def citation(self) -> str:
        """How the text cites it: ``(ABNT NBR 15575-1, 2021)``."""
        name = self.identifier or self.author.partition(",")[0].upper()
        return f"({name}, {self.year})" if self.year is not None else f"({name})"

    @property
    def entry(self) -> str:
        """The references-section entry: AUTHOR. Identifier: Title. Details, year."""
        # A person is written "Surname, Given" and only the surname is set in
        # capitals; an institution has no comma and is capitalised whole.
        surname, comma, given = self.author.partition(",")
        author = surname.upper() + comma + given
        title = f"{self.identifier}: {self.title}" if self.identifier else self.title
        # Without a year nothing is invented: a law carries its date in the title.
        closing = ", ".join(item for item in (self.details.strip().rstrip(".") if self.details else "", str(self.year) if self.year is not None else "") if item)
        return " ".join(_sentence(item) for item in (author, title, closing) if item)


FINDING_SITUATIONS = {
    "CONFORME": "Conforme",
    "ANOMALIA": "Anomalia",
    "FALHA": "Falha",
    "INCONCLUSIVA": "Inconclusiva",
    "NAO_CONSTATADA": "Não constatada",
}


@dataclass(frozen=True, slots=True)
class ReportFindingRow:
    """One row of the findings summary, captured from an approved pathology.

    New rows repeat effective technical findings (scope in the legacy
    ``manifestation`` field). PATHOLOGY rows remain readable for old reports.
    The row is bound to its source revision, so a change upstream makes
    the report stale instead of silently disagreeing with its table.
    """
    manifestation: str
    environment: str | None
    finding: str
    situation: str | None
    provenance: ReportProvenance

    def __post_init__(self):
        _all_text(self, ("manifestation", "finding"))
        if self.environment is not None and not _text(self.environment):
            raise ValueError("report finding row is invalid")
        if self.situation is not None and self.situation not in FINDING_SITUATIONS:
            raise ValueError("report finding row is invalid")
        if type(self.provenance) is not ReportProvenance or self.provenance.source_kind not in {"PATHOLOGY", "TECHNICAL_FINDING"}:
            raise ValueError("report finding row requires finding authority provenance")


@dataclass(frozen=True, slots=True)
class ReportSiteLocation:
    """The confirmed site location, captured at a revision of its record.

    The report repeats the coordinates the expert confirmed; the revision and
    checksum bind them, so a location changed afterwards makes the report
    stale instead of silently disagreeing with it.
    """
    latitude: float
    longitude: float
    address_label: str | None
    source_revision: int
    source_checksum: str

    def __post_init__(self):
        for name, low, high in (("latitude", -90.0, 90.0), ("longitude", -180.0, 180.0)):
            value = getattr(self, name)
            if type(value) is not float or not low <= value <= high or round(value, 6) != value:
                raise ValueError("report site location is invalid")
        if self.address_label is not None and (not _text(self.address_label) or self.address_label != self.address_label.strip()):
            raise ValueError("report site location is invalid")
        if type(self.source_revision) is not int or self.source_revision < 1 or type(self.source_checksum) is not str or len(self.source_checksum) != 64 or any(ch not in "0123456789abcdef" for ch in self.source_checksum):
            raise ValueError("report site location binding is invalid")

    @property
    def coordinates_text(self) -> str:
        latitude = f"{abs(self.latitude):.6f}".replace(".", ",") + ("° S" if self.latitude < 0 else "° N")
        longitude = f"{abs(self.longitude):.6f}".replace(".", ",") + ("° O" if self.longitude < 0 else "° L")
        return f"{latitude}, {longitude}"


FIGURE_SECTION_KINDS = ("INSPECTION", "TECHNICAL_ANALYSIS", "TECHNICAL_FINDINGS", "ATTACHMENTS")
FIGURE_TOKEN = re.compile(r"\[\[FIGURA:([^\]]*)\]\]")
TABLE_TOKEN = re.compile(r"\[\[TABELA:([^\]]*)\]\]")
FINDINGS_TABLE_KEY = "ACHADOS"
_FIGURE_ID = re.compile(r"^PHOTO-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")


@dataclass(frozen=True, slots=True)
class ReportFigure:
    """A photo the expert chose as a figure, bound to its original's bytes.

    The report presents a derivative (upright, resized, without metadata);
    the original stays intact in private storage and is named by SHA-256, so
    a figure can only ever be rendered from the bytes it was chosen for.
    """
    figure_id: str
    content_id: str
    original_sha256: str
    caption: str
    section_kind: str
    width: int
    height: int

    def __post_init__(self):
        if _FIGURE_ID.fullmatch(self.figure_id or "") is None or not _text(self.content_id) or not _text(self.caption) or self.caption != self.caption.strip() or len(self.caption) > 300:
            raise ValueError("report figure is invalid")
        if type(self.original_sha256) is not str or len(self.original_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.original_sha256):
            raise ValueError("report figure binding is invalid")
        if self.section_kind not in FIGURE_SECTION_KINDS or any(type(value) is not int or not 1 <= value <= 100_000 for value in (self.width, self.height)):
            raise ValueError("report figure is invalid")


@dataclass(frozen=True, slots=True)
class ReportReviewDecision:
    review_id: str
    action: ReviewAction
    professional_id: str
    reason: str
    timestamp: str
    supersedes_review_id: str | None

    def __post_init__(self):
        _all_text(self, ("review_id", "professional_id", "reason"))
        _timestamp(self.timestamp)
        if self.supersedes_review_id is not None and not _text(self.supersedes_review_id):
            raise ValueError("report review supersession is invalid")


@dataclass(frozen=True, slots=True)
class ReportCoverage:
    sections: int
    material_claims: int
    traceable_claims: int
    answers: int
    traceable_answers: int
    cpc473_required_sections: int
    cpc473_present_sections: int
    context_required_fields: int
    context_present_fields: int
    complete: bool
    reasons: tuple[str, ...]

    def __post_init__(self):
        values = (self.sections, self.material_claims, self.traceable_claims, self.answers, self.traceable_answers, self.cpc473_required_sections, self.cpc473_present_sections, self.context_required_fields, self.context_present_fields)
        if any(type(value) is not int or value < 0 for value in values) or type(self.complete) is not bool:
            raise ValueError("report coverage is invalid")
        _texts(self.reasons)


@dataclass(frozen=True, slots=True)
class ReportProcess:
    """Immutable presentation capture of ProcessCase; never a second editor."""
    workspace_id: str
    source_revision: int
    source_checksum: str
    numero_processo: str
    ramo_justica: str
    tribunal: str
    vara: str
    municipio_sede: str
    subsecao_judiciaria: str
    comarca_municipio: str
    uf: str
    parte_requerente: str
    parte_requerida: str
    # Colecao de participantes (#268), capturada com a revisao do registro que
    # a sustenta. Ausente em laudos anteriores e enquanto o perito nao gravou o
    # registro: omitida do mapping, nunca nula, para preservar o digest antigo.
    participants: tuple[CaseParticipant, ...] | None = None
    participants_revision: int | None = None
    participants_checksum: str | None = None

    @property
    def has_identity(self) -> bool:
        return bool(self.numero_processo.strip() and (self.vara.strip() or self.tribunal.strip()))

    @property
    def confirmed_participants(self) -> tuple[CaseParticipant, ...]:
        return tuple(item for item in self.participants or () if item.review_state.value == "CONFIRMED")

    def __post_init__(self):
        if not _text(self.workspace_id):
            raise ValueError("report process workspace is invalid")
        if type(self.source_revision) is not int or self.source_revision < 1 or type(self.source_checksum) is not str or not _SHA256.fullmatch(self.source_checksum):
            raise ValueError("report process binding is invalid")
        binding = (self.participants, self.participants_revision, self.participants_checksum)
        if any(value is None for value in binding):
            if any(value is not None for value in binding):
                raise ValueError("report participants binding is incomplete")
        elif (
            type(self.participants) is not tuple or any(type(item) is not CaseParticipant for item in self.participants)
            or len({item.participant_id for item in self.participants}) != len(self.participants)
            or type(self.participants_revision) is not int or self.participants_revision < 1
            or type(self.participants_checksum) is not str or not _SHA256.fullmatch(self.participants_checksum)
            or any(item.review_state.value == "PROPOSED" for item in self.participants)
        ):
            raise ValueError("report participants binding is invalid")
        for field in fields(self):
            if field.name in {"workspace_id", "source_revision", "source_checksum", "participants", "participants_revision", "participants_checksum"}:
                continue
            value = getattr(self, field.name)
            if type(value) is not str:
                raise ValueError("report process field is invalid")
            value.encode("utf-8")


@dataclass(frozen=True, slots=True)
class ReportProperty:
    record: PropertyRecord
    source_revision: int
    source_checksum: str

    def __post_init__(self):
        if type(self.record) is not PropertyRecord or type(self.source_revision) is not int or self.source_revision < 1:
            raise ValueError("report property binding is invalid")
        if type(self.source_checksum) is not str or not _SHA256.fullmatch(self.source_checksum):
            raise ValueError("report property checksum is invalid")


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    schema_version: str
    report_id: str
    workspace_id: str
    source_snapshot: ReportSourceSnapshot
    expert_profile: ExpertMasterProfile
    editorial_profile: EditorialProfile
    context_matrix: tuple[ContextCompletenessItem, ...]
    sections: tuple[ReportSection, ...]
    claims: tuple[ReportClaim, ...]
    answers: tuple[ReportAnswer, ...]
    review_decisions: tuple[ReportReviewDecision, ...]
    state: ReportState
    coverage: ReportCoverage
    upstream_stale: bool
    upstream_stale_reasons: tuple[str, ...]
    # Both are optional so a report written before them keeps its exact
    # persisted mapping and digest: an absent value is omitted, never nulled,
    # and an empty collection is written as absent.
    references: tuple[ReportReference, ...] | None = None
    findings_table: tuple[ReportFindingRow, ...] | None = None
    site_location: ReportSiteLocation | None = None
    figures: tuple[ReportFigure, ...] | None = None
    property_record: ReportProperty | None = None
    process_record: ReportProcess | None = None
    presentation: ProfessionalReportCapture | None = None

    def __post_init__(self):
        _all_text(self, ("schema_version", "report_id", "workspace_id"))
        if self.presentation is not None:
            professional_report_projection(self)
        if self.schema_version != "1.0.0" or self.source_snapshot.workspace_id != self.workspace_id:
            raise ValueError("report workspace or schema mismatch")
        if self.source_snapshot.expert_profile_id != self.expert_profile.profile_id or self.source_snapshot.expert_profile_revision != self.expert_profile.revision:
            raise ValueError("expert master profile authority mismatch")
        _texts(self.upstream_stale_reasons)
        if type(self.upstream_stale) is not bool or self.upstream_stale != bool(self.upstream_stale_reasons):
            raise ValueError("report stale status is dishonest")
        if self.upstream_stale and self.state is ReportState.APPROVED:
            raise ValueError("stale report cannot remain approved")
        if self.state is ReportState.APPROVED and any(item.required and item.status is not ContextStatus.PRESENT for item in self.context_matrix):
            raise ValueError("approved report requires complete process context")
        self._validate_graph()

    def _validate_graph(self) -> None:
        section_ids = {item.section_id for item in self.sections}
        if len(section_ids) != len(self.sections) or tuple(item.kind for item in sorted(self.sections, key=lambda item: item.order)) != _SECTION_ORDER or tuple(item.order for item in sorted(self.sections, key=lambda item: item.order)) != tuple(range(1, len(_SECTION_ORDER) + 1)):
            raise ValueError("canonical report section order is invalid")
        if any(item.required_by_cpc473 != (item.kind in _CPC473_REQUIRED) for item in self.sections):
            raise ValueError("CPC 473 required section classification is canonical")
        if {item.field for item in self.context_matrix} != _CONTEXT_FIELDS or len(self.context_matrix) != len(_CONTEXT_FIELDS) or any(not item.required for item in self.context_matrix):
            raise ValueError("CPC 319 context classification is canonical")
        claim_ids = {item.claim_id for item in self.claims}
        if len(claim_ids) != len(self.claims) or any(item.section_id not in section_ids for item in self.claims):
            raise ValueError("report claim section is invalid")
        if any(item.section_id not in section_ids or any(claim_id not in claim_ids for claim_id in item.claim_ids) for item in self.answers):
            raise ValueError("report answer traceability is invalid")
        if len({item.answer_id for item in self.answers}) != len(self.answers) or len({item.question_id for item in self.answers}) != len(self.answers):
            raise ValueError("report answers must be unique per canonical question")
        if self.references is not None:
            if type(self.references) is not tuple or not self.references or any(type(item) is not ReportReference for item in self.references):
                raise ValueError("report references are invalid")
            if len({item.reference_id for item in self.references}) != len(self.references) or len({item.entry.casefold() for item in self.references}) != len(self.references):
                raise ValueError("report references must be unique")
        if self.site_location is not None and type(self.site_location) is not ReportSiteLocation:
            raise ValueError("report site location is invalid")
        if self.process_record is not None and (type(self.process_record) is not ReportProcess or self.process_record.workspace_id != self.workspace_id):
            raise ValueError("report process workspace mismatch")
        if self.state is ReportState.APPROVED and self.process_record is not None and not self.process_record.has_identity:
            raise ValueError("approved report requires complete captured process identity")
        if self.property_record is not None and (type(self.property_record) is not ReportProperty or self.property_record.record.workspace_id != self.workspace_id):
            raise ValueError("report property workspace is invalid")
        if self.figures is not None:
            if type(self.figures) is not tuple or not self.figures or any(type(item) is not ReportFigure for item in self.figures):
                raise ValueError("report figures are invalid")
            if len({item.figure_id for item in self.figures}) != len(self.figures) or len({item.original_sha256 for item in self.figures}) != len(self.figures):
                raise ValueError("report figures must be unique")
        # A cross-reference names something the report presents, or nothing.
        figure_ids = {item.figure_id for item in self.figures or ()}
        texts = [item.text for item in self.claims] + [item.text for item in self.answers]
        for text in texts:
            if any(target not in figure_ids for target in FIGURE_TOKEN.findall(text)):
                raise ValueError("report text cites a figure the report does not present")
            if any(target != FINDINGS_TABLE_KEY or not self.findings_table for target in TABLE_TOKEN.findall(text)):
                raise ValueError("report text cites a table the report does not present")
        if self.findings_table is not None:
            if type(self.findings_table) is not tuple or not self.findings_table or any(type(item) is not ReportFindingRow for item in self.findings_table):
                raise ValueError("report findings table is invalid")
            if len({item.provenance.source_id for item in self.findings_table}) != len(self.findings_table) or len({item.provenance.provenance_id for item in self.findings_table}) != len(self.findings_table):
                raise ValueError("report findings table rows must be unique")
            if len({item.provenance.source_kind for item in self.findings_table}) != 1:
                raise ValueError("report findings table cannot mix technical and legacy pathology presentations")
        reviews = {item.review_id: item for item in self.review_decisions}
        ordered = sorted(self.review_decisions, key=lambda item: datetime.fromisoformat(item.timestamp))
        if len(reviews) != len(self.review_decisions) or len({item.timestamp for item in ordered}) != len(ordered):
            raise ValueError("report review chronology is ambiguous")
        for index, item in enumerate(ordered):
            expected = None if index == 0 else ordered[index - 1].review_id
            if item.supersedes_review_id != expected or item.professional_id != self.expert_profile.profile_id:
                raise ValueError("report review authority is invalid")
        expected_state = ReportState.DRAFT
        if ordered:
            action = ordered[-1].action
            expected_state = {ReviewAction.MARK_REVIEWED: ReportState.REVIEWED, ReviewAction.APPROVE: ReportState.APPROVED, ReviewAction.SUPERSEDE: ReportState.SUPERSEDED}[action]
        if self.state is not expected_state:
            raise ValueError("report state diverges from professional review")
        required = sum(item.required_by_cpc473 for item in self.sections)
        present = sum(item.required_by_cpc473 and any(claim.section_id == item.section_id for claim in self.claims) for item in self.sections)
        context_required = sum(item.required for item in self.context_matrix)
        context_present = sum(item.required and item.status is ContextStatus.PRESENT for item in self.context_matrix)
        if self.state is ReportState.APPROVED and (not self.claims or present != required or context_present != context_required):
            raise ValueError("approved report requires complete CPC 319 and CPC 473 content")
        if self.state is ReportState.APPROVED and not self.answers:
            raise ValueError("approved report requires canonical answers to questions")
        expected_coverage = ReportCoverage(
            sections=len(self.sections), material_claims=len(self.claims), traceable_claims=len(self.claims),
            answers=len(self.answers), traceable_answers=len(self.answers), cpc473_required_sections=required,
            cpc473_present_sections=present,
            context_required_fields=context_required, context_present_fields=context_present,
            complete=bool(self.claims) and present == required and context_present == context_required and not self.upstream_stale and self.state is ReportState.APPROVED,
            reasons=self.coverage.reasons,
        )
        if self.coverage != expected_coverage:
            raise ValueError("report coverage is dishonest")


T = TypeVar("T")


def _construct(cls: type[T], value: object, *, nested: dict[str, type] | None = None, tuples: dict[str, type | None] | None = None) -> T:
    if type(value) is not dict:
        raise ValueError(f"{cls.__name__} mapping is invalid")
    allowed = {item.name for item in fields(cls)}
    if set(value) != allowed:
        raise ValueError(f"{cls.__name__} fields are invalid")
    data: dict[str, Any] = dict(value)
    for name, child in (nested or {}).items():
        data[name] = _construct(child, data[name])
    for name, child in (tuples or {}).items():
        if type(data[name]) is not list:
            raise ValueError(f"{name} must be an array")
        data[name] = tuple(_construct(child, item) for item in data[name]) if child else tuple(data[name])
    for item in fields(cls):
        enum_type = item.type
        if enum_type in (AuthorityClass, ReportState, ReviewAction, ContextStatus):
            data[item.name] = enum_type(data[item.name])
    return cls(**data)


def editorial_profile_from_mapping(value: object) -> EditorialProfile:
    if type(value) is not dict:
        raise ValueError("EditorialProfile mapping is invalid")
    editorial = dict(value)
    if "typography" not in editorial:
        editorial["typography"] = None
    elif type(editorial["typography"]) is dict:
        editorial["typography"] = _construct(EditorialTypography, editorial["typography"])
    else:
        # An absent typography is written by omission; an explicit null would
        # give one profile two mappings and two digests.
        raise ValueError("EditorialProfile typography is invalid")
    if "layout" not in editorial:
        editorial["layout"] = None
    elif type(editorial["layout"]) is dict:
        layout = dict(editorial["layout"])
        for name in ("heading1_case", "heading2_case", "heading3_case"):
            layout[name] = HeadingCase(layout[name]) if type(layout.get(name)) is str else layout.get(name)
        for name in ("header_distance_cm", "footer_distance_cm", "long_quote_indent_cm", "long_quote_line_spacing"):
            if type(layout.get(name)) is int:
                layout[name] = float(layout[name])
        editorial["layout"] = _construct(EditorialLayout, layout)
    else:
        raise ValueError("EditorialProfile layout is invalid")
    return _construct(EditorialProfile, editorial, tuples={"overrides": None})


def editorial_profile_to_mapping(value: EditorialProfile) -> dict[str, Any]:
    mapping = json.loads(json.dumps(asdict(value), ensure_ascii=False))
    for name in ("typography", "layout"):
        if mapping[name] is None:
            del mapping[name]
    return mapping


def report_snapshot_from_mapping(value: object) -> ReportSnapshot:
    if type(value) is not dict:
        raise ValueError("ReportSnapshot mapping is invalid")
    allowed = {item.name for item in fields(ReportSnapshot)}
    optional = {"references", "findings_table", "site_location", "figures", "property_record", "process_record", "presentation"}
    if not allowed - optional <= set(value) <= allowed:
        raise ValueError("ReportSnapshot fields are invalid")
    data = dict(value)
    data["presentation"] = capture_from_mapping(data["presentation"]) if "presentation" in data else None
    data["process_record"] = report_process_from_mapping(data["process_record"]) if "process_record" in data else None
    if "property_record" not in data:
        data["property_record"] = None
    else:
        capture = data["property_record"]
        if type(capture) is not dict or set(capture) != {"record", "source_revision", "source_checksum"}:
            raise ValueError("report property capture is invalid")
        data["property_record"] = ReportProperty(property_record_from_mapping(capture["record"]), capture["source_revision"], capture["source_checksum"])
    if "site_location" not in data:
        data["site_location"] = None
    elif type(data["site_location"]) is not dict:
        raise ValueError("ReportSnapshot site_location is invalid")
    else:
        site = dict(data["site_location"])
        for name in ("latitude", "longitude"):
            if type(site.get(name)) is int:
                site[name] = float(site[name])
        data["site_location"] = _construct(ReportSiteLocation, site)
    for name in ("references", "findings_table", "figures"):
        if name not in data:
            data[name] = None
        elif type(data[name]) is not list or not data[name]:
            # Absent is written by omission; null or [] would be a second mapping.
            raise ValueError(f"ReportSnapshot {name} is invalid")
    if data["references"] is not None:
        data["references"] = tuple(_construct(ReportReference, item) for item in data["references"])
    if data["figures"] is not None:
        data["figures"] = tuple(_construct(ReportFigure, item) for item in data["figures"])
    if data["findings_table"] is not None:
        data["findings_table"] = tuple(_construct(ReportFindingRow, item, nested={"provenance": ReportProvenance}) for item in data["findings_table"])
    data["source_snapshot"] = _construct(ReportSourceSnapshot, data["source_snapshot"])
    data["expert_profile"] = expert_profile_from_mapping(data["expert_profile"])
    data["editorial_profile"] = editorial_profile_from_mapping(data["editorial_profile"])
    context = []
    for item in data["context_matrix"]:
        record = dict(item)
        record["status"] = ContextStatus(record["status"])
        context.append(_construct(ContextCompletenessItem, record))
    data["context_matrix"] = tuple(context)
    data["sections"] = tuple(_construct(ReportSection, item) for item in data["sections"])
    claims = []
    for item in data["claims"]:
        claim = dict(item)
        claim["authority"] = AuthorityClass(claim["authority"])
        claims.append(_construct(ReportClaim, claim, tuples={"provenance": ReportProvenance}))
    data["claims"] = tuple(claims)
    answers = []
    for item in data["answers"]:
        answer = dict(item) if type(item) is dict else item
        if type(answer) is dict and "question_text" not in answer:
            answer["question_text"] = None
        elif type(answer) is dict and answer["question_text"] is None:
            # An absent question text is written by omission; an explicit null
            # would give one snapshot two mappings and two digests.
            raise ValueError("ReportAnswer question text is invalid")
        answers.append(_construct(ReportAnswer, answer, tuples={"evidence_ids": None, "method_ids": None, "claim_ids": None}))
    data["answers"] = tuple(answers)
    reviews = []
    for item in data["review_decisions"]:
        review = dict(item)
        review["action"] = ReviewAction(review["action"])
        reviews.append(_construct(ReportReviewDecision, review))
    data["review_decisions"] = tuple(reviews)
    data["coverage"] = _construct(ReportCoverage, data["coverage"], tuples={"reasons": None})
    data["upstream_stale_reasons"] = tuple(data["upstream_stale_reasons"])
    data["state"] = ReportState(data["state"])
    return ReportSnapshot(**data)


_PARTICIPANT_CAPTURE = ("participants", "participants_revision", "participants_checksum")


def report_process_from_mapping(value: object) -> ReportProcess:
    if type(value) is not dict:
        raise ValueError("ReportProcess mapping is invalid")
    capture = dict(value)
    present = [name for name in _PARTICIPANT_CAPTURE if name in capture]
    if present and len(present) != len(_PARTICIPANT_CAPTURE):
        raise ValueError("ReportProcess participants capture is incomplete")
    participants = None
    if present:
        if type(capture["participants"]) is not list or any(capture[name] is None for name in _PARTICIPANT_CAPTURE):
            # Ausente e escrito por omissao; nulo seria um segundo mapping.
            raise ValueError("ReportProcess participants capture is invalid")
        participants = tuple(participant_from_mapping(item) for item in capture.pop("participants"))
        revision, checksum = capture.pop("participants_revision"), capture.pop("participants_checksum")
    else:
        revision = checksum = None
    names = {item.name for item in fields(ReportProcess)} - set(_PARTICIPANT_CAPTURE)
    if set(capture) != names:
        raise ValueError("ReportProcess fields are invalid")
    return ReportProcess(**capture, participants=participants, participants_revision=revision, participants_checksum=checksum)


def report_process_to_mapping(value: ReportProcess) -> dict[str, Any]:
    mapping = {item.name: getattr(value, item.name) for item in fields(ReportProcess) if item.name not in _PARTICIPANT_CAPTURE}
    if value.participants is not None:
        mapping["participants"] = [participant_to_mapping(item) for item in value.participants]
        mapping["participants_revision"] = value.participants_revision
        mapping["participants_checksum"] = value.participants_checksum
    return mapping


_PROFILE_OPTIONAL = ("signature_name", "professional_council", "council_state", "national_registration", "court_registrations", "contact", "presentation")


def expert_profile_from_mapping(value: object) -> ExpertMasterProfile:
    if type(value) is not dict:
        raise ValueError("ExpertMasterProfile mapping is invalid")
    data = dict(value)
    required = {item.name for item in fields(ExpertMasterProfile)} - set(_PROFILE_OPTIONAL)
    if not required <= set(data) <= required | set(_PROFILE_OPTIONAL) or any(data.get(name, 0) is None for name in _PROFILE_OPTIONAL):
        # Ausente e escrito por omissao; nulo seria um segundo mapping.
        raise ValueError("ExpertMasterProfile fields are invalid")
    if "court_registrations" in data:
        if type(data["court_registrations"]) is not list:
            raise ValueError("ExpertMasterProfile court registrations are invalid")
        data["court_registrations"] = tuple(_construct(CourtRegistration, item) for item in data["court_registrations"])
    if "contact" in data:
        data["contact"] = _construct(ProfessionalContact, data["contact"])
    if "presentation" in data:
        data["presentation"] = _construct(ProfilePresentation, data["presentation"])
    return ExpertMasterProfile(**data)


def expert_profile_digest(profile: ExpertMasterProfile) -> str:
    """Identidade exata do perfil que gerou um modelo com texto fixo de cabeçalho (#271)."""
    canonical = json.dumps(expert_profile_to_mapping(profile), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def expert_profile_to_mapping(value: ExpertMasterProfile) -> dict[str, Any]:
    if type(value) is not ExpertMasterProfile:
        raise TypeError("expected ExpertMasterProfile")
    mapping = json.loads(json.dumps(asdict(value), ensure_ascii=False))
    for name in _PROFILE_OPTIONAL:
        if mapping[name] is None:
            del mapping[name]
    return mapping


def report_snapshot_to_mapping(value: ReportSnapshot) -> dict[str, Any]:
    if type(value) is not ReportSnapshot:
        raise TypeError("expected ReportSnapshot")
    mapping = json.loads(json.dumps(asdict(value), ensure_ascii=False))
    mapping["expert_profile"] = expert_profile_to_mapping(value.expert_profile)
    mapping["editorial_profile"] = editorial_profile_to_mapping(value.editorial_profile)
    for answer in mapping["answers"]:
        if answer["question_text"] is None:
            del answer["question_text"]
    for name in ("references", "findings_table", "site_location", "figures", "property_record", "process_record", "presentation"):
        if mapping[name] is None:
            del mapping[name]
    if value.process_record is not None:
        mapping["process_record"] = json.loads(json.dumps(report_process_to_mapping(value.process_record), ensure_ascii=False))
    return mapping
