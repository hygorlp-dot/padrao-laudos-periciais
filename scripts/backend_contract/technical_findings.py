"""Canonical evidence-to-finding graph with explicit professional authority."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
import json
import re
from typing import Any, TypeVar


TECHNICAL_SNAPSHOT_ARTIFACT_KIND = "TECHNICAL_SNAPSHOT_V1"
TECHNICAL_SNAPSHOT_ARTIFACT_ID = "TECHNICAL-SNAPSHOT"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class EvidenceReviewState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DecisionAction(StrEnum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"


class ProposalOrigin(StrEnum):
    SOURCE_VALUE = "SOURCE_VALUE"
    ENGINE_DECISION = "ENGINE_DECISION"
    AI_PROPOSAL = "AI_PROPOSAL"
    PROFESSIONAL_PROPOSAL = "PROFESSIONAL_PROPOSAL"


class ConflictStatus(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _texts(values: tuple[str, ...], *, allow_empty: bool = True) -> None:
    if type(values) is not tuple or (not allow_empty and not values):
        raise ValueError("identity collection is invalid")
    if any(not _text(value) for value in values) or len(values) != len(set(values)):
        raise ValueError("identity collection is invalid")


def _timestamp(value: object, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not _text(value):
        raise ValueError("timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp requires timezone")


def _all_text(instance: object, names: tuple[str, ...]) -> None:
    if not all(_text(getattr(instance, name)) for name in names):
        raise ValueError(f"{type(instance).__name__} is invalid")


@dataclass(frozen=True, slots=True)
class TechnicalSourceSnapshot:
    workspace_id: str
    case_analysis_snapshot_id: str
    case_analysis_revision: int
    case_analysis_digest: str
    inspection_session_id: str
    inspection_session_revision: int
    inspection_session_digest: str
    source_revision: int

    def __post_init__(self):
        _all_text(self, ("workspace_id", "case_analysis_snapshot_id", "inspection_session_id"))
        if any(type(value) is not int or value < 1 for value in (self.case_analysis_revision, self.inspection_session_revision, self.source_revision)):
            raise ValueError("source revisions are invalid")
        if any(type(value) is not str or _SHA256.fullmatch(value) is None for value in (self.case_analysis_digest, self.inspection_session_digest)):
            raise ValueError("source digest is invalid")


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    proposition: str
    assessment_id: str

    def __post_init__(self):
        _all_text(self, ("evidence_id", "proposition", "assessment_id"))


@dataclass(frozen=True, slots=True)
class EvidenceSourceLink:
    link_id: str
    evidence_id: str
    source_kind: str
    source_id: str
    source_revision: int
    provenance: str

    def __post_init__(self):
        _all_text(self, ("link_id", "evidence_id", "source_kind", "source_id", "provenance"))
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise ValueError("source link revision is invalid")


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    assessment_id: str
    evidence_id: str
    why_relevant: str
    supported_proposition: str
    limitation_ids: tuple[str, ...]
    contrary_evidence_ids: tuple[str, ...]
    source_link_ids: tuple[str, ...]
    review_state: EvidenceReviewState
    reviewer: str | None
    reviewed_at: str | None

    def __post_init__(self):
        _all_text(self, ("assessment_id", "evidence_id", "why_relevant", "supported_proposition"))
        _texts(self.limitation_ids)
        _texts(self.contrary_evidence_ids)
        _texts(self.source_link_ids, allow_empty=False)
        if self.review_state is EvidenceReviewState.APPROVED:
            if not _text(self.reviewer):
                raise ValueError("approved evidence requires reviewer")
            _timestamp(self.reviewed_at)
        elif self.reviewer is not None or self.reviewed_at is not None:
            raise ValueError("unreviewed evidence cannot claim professional review")


@dataclass(frozen=True, slots=True)
class MethodInput:
    input_id: str
    method_application_id: str
    evidence_id: str
    role: str

    def __post_init__(self):
        _all_text(self, ("input_id", "method_application_id", "evidence_id", "role"))


@dataclass(frozen=True, slots=True)
class MethodOutput:
    output_id: str
    method_application_id: str
    description: str
    provenance: str

    def __post_init__(self):
        _all_text(self, ("output_id", "method_application_id", "description", "provenance"))


@dataclass(frozen=True, slots=True)
class MethodApplication:
    method_application_id: str
    method_identity: str
    selection_authority: str
    procedure: str
    parameters: tuple[str, ...]
    input_ids: tuple[str, ...]
    output_ids: tuple[str, ...]
    limitation_ids: tuple[str, ...]
    normative_references: tuple[str, ...]
    execution_revision: int

    def __post_init__(self):
        _all_text(self, ("method_application_id", "method_identity", "selection_authority", "procedure"))
        for values in (self.parameters, self.input_ids, self.output_ids, self.limitation_ids, self.normative_references):
            _texts(values)
        if not self.input_ids:
            raise ValueError("method input is required")
        if not self.output_ids:
            raise ValueError("method output is required")
        if type(self.execution_revision) is not int or self.execution_revision < 1:
            raise ValueError("method execution revision is invalid")


@dataclass(frozen=True, slots=True)
class TechnicalFindingProposal:
    proposal_id: str
    technical_proposition: str
    origin: ProposalOrigin
    method_application_ids: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    contrary_evidence_ids: tuple[str, ...]
    limitation_ids: tuple[str, ...]
    uncertainty_ids: tuple[str, ...]
    scope: str

    def __post_init__(self):
        _all_text(self, ("proposal_id", "technical_proposition", "scope"))
        for values in (self.method_application_ids, self.supporting_evidence_ids, self.contrary_evidence_ids, self.limitation_ids, self.uncertainty_ids):
            _texts(values)
        _texts(self.method_application_ids, allow_empty=False)
        _texts(self.supporting_evidence_ids, allow_empty=False)
        _texts(self.limitation_ids, allow_empty=False)
        _texts(self.uncertainty_ids, allow_empty=False)


@dataclass(frozen=True, slots=True)
class TechnicalFinding:
    finding_id: str
    proposal_id: str
    decision_id: str
    technical_proposition: str
    scope: str

    def __post_init__(self):
        _all_text(self, ("finding_id", "proposal_id", "decision_id", "technical_proposition", "scope"))


@dataclass(frozen=True, slots=True)
class FindingDependency:
    dependency_id: str
    finding_id: str
    depends_on_finding_id: str
    rationale: str

    def __post_init__(self):
        _all_text(self, ("dependency_id", "finding_id", "depends_on_finding_id", "rationale"))
        if self.finding_id == self.depends_on_finding_id:
            raise ValueError("finding cannot depend on itself")


@dataclass(frozen=True, slots=True)
class FindingConflict:
    conflict_id: str
    proposal_id: str
    contrary_evidence_ids: tuple[str, ...]
    status: ConflictStatus
    resolution_reasoning: str | None
    decision_id: str | None

    def __post_init__(self):
        _all_text(self, ("conflict_id", "proposal_id"))
        _texts(self.contrary_evidence_ids, allow_empty=False)
        if self.status is ConflictStatus.RESOLVED:
            if not _text(self.resolution_reasoning) or not _text(self.decision_id):
                raise ValueError("resolved conflict requires reasoning and professional decision")
        elif self.resolution_reasoning is not None or self.decision_id is not None:
            raise ValueError("unresolved conflict cannot claim resolution")


@dataclass(frozen=True, slots=True)
class FindingLimitation:
    limitation_id: str
    owner_kind: str
    owner_id: str
    kind: str
    description: str

    def __post_init__(self):
        _all_text(self, ("limitation_id", "owner_kind", "owner_id", "kind", "description"))


@dataclass(frozen=True, slots=True)
class FindingUncertainty:
    uncertainty_id: str
    proposal_id: str
    kind: str
    description: str
    impact: str

    def __post_init__(self):
        _all_text(self, ("uncertainty_id", "proposal_id", "kind", "description", "impact"))


@dataclass(frozen=True, slots=True)
class QuestionFindingLink:
    link_id: str
    question_id: str
    finding_id: str
    relevance: str

    def __post_init__(self):
        _all_text(self, ("link_id", "question_id", "finding_id", "relevance"))


@dataclass(frozen=True, slots=True)
class ProfessionalDecision:
    decision_id: str
    proposal_id: str
    action: DecisionAction
    professional_id: str
    reason: str
    modified_proposition: str | None
    timestamp: str
    supersedes_decision_id: str | None

    def __post_init__(self):
        _all_text(self, ("decision_id", "proposal_id", "professional_id", "reason", "timestamp"))
        _timestamp(self.timestamp)
        if self.action is DecisionAction.MODIFY and not _text(self.modified_proposition):
            raise ValueError("modified decision requires proposition")
        if self.action is not DecisionAction.MODIFY and self.modified_proposition is not None:
            raise ValueError("only modified decision may replace proposition")
        if self.supersedes_decision_id is not None and not _text(self.supersedes_decision_id):
            raise ValueError("superseded decision identity is invalid")


@dataclass(frozen=True, slots=True)
class TechnicalCoverage:
    evidence_items: int
    approved_evidence: int
    method_applications: int
    finding_proposals: int
    effective_findings: int
    unresolved_conflicts: int
    complete: bool
    reasons: tuple[str, ...]

    def __post_init__(self):
        counts = (self.evidence_items, self.approved_evidence, self.method_applications, self.finding_proposals, self.effective_findings, self.unresolved_conflicts)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("technical coverage counts are invalid")
        _texts(self.reasons)


@dataclass(frozen=True, slots=True)
class TechnicalSnapshot:
    schema_version: str
    snapshot_id: str
    workspace_id: str
    source_snapshot: TechnicalSourceSnapshot
    evidence_items: tuple[EvidenceItem, ...]
    source_links: tuple[EvidenceSourceLink, ...]
    evidence_assessments: tuple[EvidenceAssessment, ...]
    method_applications: tuple[MethodApplication, ...]
    method_inputs: tuple[MethodInput, ...]
    method_outputs: tuple[MethodOutput, ...]
    finding_proposals: tuple[TechnicalFindingProposal, ...]
    findings: tuple[TechnicalFinding, ...]
    dependencies: tuple[FindingDependency, ...]
    conflicts: tuple[FindingConflict, ...]
    limitations: tuple[FindingLimitation, ...]
    uncertainties: tuple[FindingUncertainty, ...]
    question_links: tuple[QuestionFindingLink, ...]
    decisions: tuple[ProfessionalDecision, ...]
    coverage: TechnicalCoverage
    upstream_stale: bool
    upstream_stale_reasons: tuple[str, ...]

    def __post_init__(self):
        _all_text(self, ("schema_version", "snapshot_id", "workspace_id"))
        if self.source_snapshot.workspace_id != self.workspace_id:
            raise ValueError("technical snapshot workspace mismatch")
        _texts(self.upstream_stale_reasons)
        if type(self.upstream_stale) is not bool or self.upstream_stale != bool(self.upstream_stale_reasons):
            raise ValueError("stale status is dishonest")
        self._validate_graph()

    def _validate_graph(self) -> None:
        collections = (self.evidence_items, self.source_links, self.evidence_assessments, self.method_applications, self.method_inputs, self.method_outputs, self.finding_proposals, self.findings, self.dependencies, self.conflicts, self.limitations, self.uncertainties, self.question_links, self.decisions)
        ids: set[str] = set()
        for collection in collections:
            if type(collection) is not tuple:
                raise ValueError("technical graph collection is invalid")
            for record in collection:
                identity = getattr(record, fields(record)[0].name)
                if identity in ids:
                    raise ValueError("technical graph identity is duplicated")
                ids.add(identity)
        evidence = {item.evidence_id: item for item in self.evidence_items}
        assessments = {item.assessment_id: item for item in self.evidence_assessments}
        links = {item.link_id: item for item in self.source_links}
        limitations = {item.limitation_id: item for item in self.limitations}
        for item in self.evidence_items:
            assessment = assessments.get(item.assessment_id)
            if assessment is None or assessment.evidence_id != item.evidence_id or assessment.review_state is not EvidenceReviewState.APPROVED:
                raise ValueError("approved evidence requires explicit approved assessment")
            if item.proposition != assessment.supported_proposition:
                raise ValueError("approved evidence proposition diverges from assessment")
            if any(links.get(link_id) is None or links[link_id].evidence_id != item.evidence_id for link_id in assessment.source_link_ids):
                raise ValueError("source link must be owned by assessed evidence")
            if any(limitations.get(limit_id) is None or limitations[limit_id].owner_id != item.evidence_id for limit_id in assessment.limitation_ids):
                raise ValueError("evidence limitation ownership is invalid")
        methods = {item.method_application_id: item for item in self.method_applications}
        inputs = {item.input_id: item for item in self.method_inputs}
        outputs = {item.output_id: item for item in self.method_outputs}
        for method in self.method_applications:
            if any(inputs.get(input_id) is None or inputs[input_id].method_application_id != method.method_application_id or inputs[input_id].evidence_id not in evidence for input_id in method.input_ids):
                raise ValueError("method input requires owned approved evidence")
            if any(outputs.get(output_id) is None or outputs[output_id].method_application_id != method.method_application_id for output_id in method.output_ids):
                raise ValueError("method output requires owned traceable output")
        proposals = {item.proposal_id: item for item in self.finding_proposals}
        uncertainties = {item.uncertainty_id: item for item in self.uncertainties}
        for proposal in self.finding_proposals:
            if any(method_id not in methods for method_id in proposal.method_application_ids) or any(item_id not in evidence for item_id in proposal.supporting_evidence_ids):
                raise ValueError("finding proposal skips evidence or method")
            conflicts = tuple(item for item in self.conflicts if item.proposal_id == proposal.proposal_id)
            conflict_evidence = {item for conflict in conflicts for item in conflict.contrary_evidence_ids}
            if set(proposal.contrary_evidence_ids) != conflict_evidence:
                raise ValueError("contrary evidence must remain explicit in conflicts")
            if any(item_id not in evidence for item_id in proposal.contrary_evidence_ids):
                raise ValueError("contrary evidence is invalid")
            if any(limitations.get(item_id) is None or limitations[item_id].owner_id != proposal.proposal_id for item_id in proposal.limitation_ids):
                raise ValueError("finding limitation ownership is invalid")
            if any(uncertainties.get(item_id) is None or uncertainties[item_id].proposal_id != proposal.proposal_id for item_id in proposal.uncertainty_ids):
                raise ValueError("finding uncertainty ownership is invalid")
        decisions = {item.decision_id: item for item in self.decisions}
        findings = {item.finding_id: item for item in self.findings}
        for finding in self.findings:
            proposal = proposals.get(finding.proposal_id)
            decision = decisions.get(finding.decision_id)
            if proposal is None or decision is None or decision.proposal_id != finding.proposal_id or decision.action is DecisionAction.REJECT:
                raise ValueError("effective finding requires owned explicit professional decision")
            expected = decision.modified_proposition if decision.action is DecisionAction.MODIFY else proposal.technical_proposition
            if finding.technical_proposition != expected or finding.scope != proposal.scope:
                raise ValueError("effective finding diverges from professional decision")
        for dependency in self.dependencies:
            if dependency.finding_id not in findings or dependency.depends_on_finding_id not in findings:
                raise ValueError("finding dependency is invalid")
        for link in self.question_links:
            if link.finding_id not in findings:
                raise ValueError("question link must target effective finding")
        expected = TechnicalCoverage(
            evidence_items=len(evidence),
            approved_evidence=len(evidence),
            method_applications=len(methods),
            finding_proposals=len(proposals),
            effective_findings=len(findings),
            unresolved_conflicts=sum(item.status is ConflictStatus.UNRESOLVED for item in self.conflicts),
            complete=bool(proposals) and len(findings) == len(proposals) and not self.upstream_stale,
            reasons=self.coverage.reasons,
        )
        if self.coverage != expected:
            raise ValueError("technical coverage is dishonest")


T = TypeVar("T")
_COLLECTION_TYPES = {
    "evidence_items": EvidenceItem,
    "source_links": EvidenceSourceLink,
    "evidence_assessments": EvidenceAssessment,
    "method_applications": MethodApplication,
    "method_inputs": MethodInput,
    "method_outputs": MethodOutput,
    "finding_proposals": TechnicalFindingProposal,
    "findings": TechnicalFinding,
    "dependencies": FindingDependency,
    "conflicts": FindingConflict,
    "limitations": FindingLimitation,
    "uncertainties": FindingUncertainty,
    "question_links": QuestionFindingLink,
    "decisions": ProfessionalDecision,
}


def _record(cls: type[T], value: object) -> T:
    if type(value) is not dict or set(value) != {field.name for field in fields(cls)}:
        raise ValueError(f"invalid {cls.__name__} payload")
    converted = dict(value)
    enum_fields = {
        "review_state": EvidenceReviewState,
        "origin": ProposalOrigin,
        "status": ConflictStatus,
        "action": DecisionAction,
    }
    for name, enum_type in enum_fields.items():
        if name in converted:
            converted[name] = enum_type(converted[name])
    annotations = cls.__annotations__
    for name, annotation in annotations.items():
        if name in converted and ("tuple" in str(annotation) or str(annotation).startswith("tuple")):
            if type(converted[name]) is not list:
                raise ValueError(f"invalid {cls.__name__} payload")
            converted[name] = tuple(converted[name])
    return cls(**converted)


def technical_snapshot_from_mapping(value: object) -> TechnicalSnapshot:
    if type(value) is not dict or set(value) != {field.name for field in fields(TechnicalSnapshot)}:
        raise ValueError("invalid TechnicalSnapshot payload")
    converted: dict[str, Any] = dict(value)
    converted["source_snapshot"] = _record(TechnicalSourceSnapshot, converted["source_snapshot"])
    converted["coverage"] = _record(TechnicalCoverage, converted["coverage"])
    for name, cls in _COLLECTION_TYPES.items():
        records = converted[name]
        if type(records) is not list:
            raise ValueError("invalid TechnicalSnapshot payload")
        converted[name] = tuple(_record(cls, record) for record in records)
    if type(converted["upstream_stale_reasons"]) is not list:
        raise ValueError("invalid TechnicalSnapshot payload")
    converted["upstream_stale_reasons"] = tuple(converted["upstream_stale_reasons"])
    return TechnicalSnapshot(**converted)


def technical_snapshot_to_mapping(snapshot: TechnicalSnapshot) -> dict[str, Any]:
    if type(snapshot) is not TechnicalSnapshot:
        raise TypeError("snapshot must be TechnicalSnapshot")
    return json.loads(json.dumps(asdict(snapshot), ensure_ascii=False))
