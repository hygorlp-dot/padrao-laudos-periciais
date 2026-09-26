"""Canonical report graph: presentation without upstream authority promotion."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
import json
import re
from typing import Any, TypeVar


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


@dataclass(frozen=True, slots=True)
class ExpertMasterProfile:
    profile_id: str
    revision: int
    full_name: str
    professional_title: str
    registration: str
    court_registration: str
    contact_line: str

    def __post_init__(self):
        _all_text(self, ("profile_id", "full_name", "professional_title", "registration", "court_registration", "contact_line"))
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("expert profile revision is invalid")


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
        # The preset keeps its meaning: its identity names exactly its values.
        if self.profile_id == EDITORIAL_PRESET_ID and (
            (self.font_family, self.alignment, self.body_font_pt, self.table_font_pt, self.caption_font_pt) != ("Arial", "JUSTIFIED", 11, 10, 9)
            or (self.line_spacing, self.first_line_indent_cm) != (1.15, 1.25)
            or margins != (2, 2, 3, 2)
            or self.typography not in (None, DEFAULT_EDITORIAL_TYPOGRAPHY)
        ):
            raise ValueError("editorial preset values cannot change")
        _texts(self.overrides)

    @property
    def effective_typography(self) -> EditorialTypography:
        return self.typography or DEFAULT_EDITORIAL_TYPOGRAPHY


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

    The row repeats what the pathology record states at capture time; it is
    bound to that record's revision like any claim, so a change upstream makes
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
        if type(self.provenance) is not ReportProvenance or self.provenance.source_kind != "PATHOLOGY":
            raise ValueError("report finding row requires pathology provenance")


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

    def __post_init__(self):
        _all_text(self, ("schema_version", "report_id", "workspace_id"))
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
        if self.findings_table is not None:
            if type(self.findings_table) is not tuple or not self.findings_table or any(type(item) is not ReportFindingRow for item in self.findings_table):
                raise ValueError("report findings table is invalid")
            if len({item.provenance.source_id for item in self.findings_table}) != len(self.findings_table) or len({item.provenance.provenance_id for item in self.findings_table}) != len(self.findings_table):
                raise ValueError("report findings table rows must be unique")
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
    return _construct(EditorialProfile, editorial, tuples={"overrides": None})


def editorial_profile_to_mapping(value: EditorialProfile) -> dict[str, Any]:
    mapping = json.loads(json.dumps(asdict(value), ensure_ascii=False))
    if mapping["typography"] is None:
        del mapping["typography"]
    return mapping


def report_snapshot_from_mapping(value: object) -> ReportSnapshot:
    if type(value) is not dict:
        raise ValueError("ReportSnapshot mapping is invalid")
    allowed = {item.name for item in fields(ReportSnapshot)}
    optional = {"references", "findings_table"}
    if not allowed - optional <= set(value) <= allowed:
        raise ValueError("ReportSnapshot fields are invalid")
    data = dict(value)
    for name in optional:
        if name not in data:
            data[name] = None
        elif type(data[name]) is not list or not data[name]:
            # Absent is written by omission; null or [] would be a second mapping.
            raise ValueError(f"ReportSnapshot {name} is invalid")
    if data["references"] is not None:
        data["references"] = tuple(_construct(ReportReference, item) for item in data["references"])
    if data["findings_table"] is not None:
        data["findings_table"] = tuple(_construct(ReportFindingRow, item, nested={"provenance": ReportProvenance}) for item in data["findings_table"])
    data["source_snapshot"] = _construct(ReportSourceSnapshot, data["source_snapshot"])
    data["expert_profile"] = _construct(ExpertMasterProfile, data["expert_profile"])
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


def expert_profile_from_mapping(value: object) -> ExpertMasterProfile:
    return _construct(ExpertMasterProfile, value)


def expert_profile_to_mapping(value: ExpertMasterProfile) -> dict[str, Any]:
    if type(value) is not ExpertMasterProfile:
        raise TypeError("expected ExpertMasterProfile")
    return asdict(value)


def report_snapshot_to_mapping(value: ReportSnapshot) -> dict[str, Any]:
    if type(value) is not ReportSnapshot:
        raise TypeError("expected ReportSnapshot")
    mapping = json.loads(json.dumps(asdict(value), ensure_ascii=False))
    if mapping["editorial_profile"]["typography"] is None:
        del mapping["editorial_profile"]["typography"]
    for answer in mapping["answers"]:
        if answer["question_text"] is None:
            del answer["question_text"]
    for name in ("references", "findings_table"):
        if mapping[name] is None:
            del mapping[name]
    return mapping
