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
    "TECHNICAL_FINDING": AuthorityClass.TECHNICALLY_FOUND,
    "PROFESSIONAL_DECISION": AuthorityClass.PROFESSIONALLY_CONCLUDED,
}

_SECTION_ORDER = (
    "IDENTIFICATION", "PROCEDURAL_CONTEXT", "PURPOSE_OBJECT", "SCOPE",
    "DOCUMENTS_EVIDENCE", "METHODOLOGY", "INSPECTION", "TECHNICAL_ANALYSIS",
    "TECHNICAL_FINDINGS", "ANSWERS_TO_QUESTIONS", "CONCLUSIONS",
    "LIMITATIONS_RESERVATIONS", "REFERENCES", "ATTACHMENTS",
)


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

    def __post_init__(self):
        _all_text(self, ("profile_id", "font_family", "alignment", "page_size"))
        if self.profile_id != "JUSTICA_PLURAL_CHAPTER_4" or self.font_family != "Arial" or self.alignment != "JUSTIFIED" or self.page_size != "A4":
            raise ValueError("editorial profile default is invalid")
        if (self.body_font_pt, self.table_font_pt, self.caption_font_pt) != (11, 10, 9):
            raise ValueError("editorial typography is invalid")
        if (self.line_spacing, self.first_line_indent_cm) != (1.15, 1.25) or (self.margin_top_cm, self.margin_bottom_cm, self.margin_left_cm, self.margin_right_cm) != (2, 2, 3, 2):
            raise ValueError("editorial geometry is invalid")
        if type(self.hyphenation) is not bool or self.hyphenation:
            raise ValueError("automatic hyphenation must be disabled")
        _texts(self.overrides)


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

    def __post_init__(self):
        _all_text(self, ("answer_id", "section_id", "question_id", "text", "finding_id", "decision_id"))
        try:
            for values in (self.evidence_ids, self.method_ids, self.claim_ids):
                _texts(values, allow_empty=False)
        except ValueError as exc:
            raise ValueError("report answer traceability is incomplete") from exc


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
        claim_ids = {item.claim_id for item in self.claims}
        if len(claim_ids) != len(self.claims) or any(item.section_id not in section_ids for item in self.claims):
            raise ValueError("report claim section is invalid")
        if any(item.section_id not in section_ids or any(claim_id not in claim_ids for claim_id in item.claim_ids) for item in self.answers):
            raise ValueError("report answer traceability is invalid")
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


def report_snapshot_from_mapping(value: object) -> ReportSnapshot:
    if type(value) is not dict:
        raise ValueError("ReportSnapshot mapping is invalid")
    allowed = {item.name for item in fields(ReportSnapshot)}
    if set(value) != allowed:
        raise ValueError("ReportSnapshot fields are invalid")
    data = dict(value)
    data["source_snapshot"] = _construct(ReportSourceSnapshot, data["source_snapshot"])
    data["expert_profile"] = _construct(ExpertMasterProfile, data["expert_profile"])
    data["editorial_profile"] = _construct(EditorialProfile, data["editorial_profile"], tuples={"overrides": None})
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
    data["answers"] = tuple(_construct(ReportAnswer, item, tuples={"evidence_ids": None, "method_ids": None, "claim_ids": None}) for item in data["answers"])
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
    return json.loads(json.dumps(asdict(value), ensure_ascii=False))
