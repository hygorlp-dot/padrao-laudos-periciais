"""Canonical, proposal-only contracts for pre-inspection pericial planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

from .case_analysis import CaseAnalysisSnapshot, SourceProvenance, case_analysis_to_mapping


PERICIAL_PLANNING_ARTIFACT_KIND = "PERICIAL_PLANNING_SNAPSHOT_V1"
PERICIAL_PLANNING_ARTIFACT_ID = "PERICIAL-PLANNING"


class ProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"


class ProfessionalReviewStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"
    DEFERRED = "DEFERRED"


class ReviewAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MODIFY = "MODIFY"
    DEFER = "DEFER"


class ReadinessStatus(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PlanningDerivation:
    rationale: str
    case_analysis_item_ids: tuple[str, ...]
    source_provenance: tuple[SourceProvenance, ...]
    question_ids: tuple[str, ...]
    pericial_object_ids: tuple[str, ...]
    court_decision_ids: tuple[str, ...]
    technical_document_reference_ids: tuple[str, ...]
    gap_or_conflict_ids: tuple[str, ...]

    def __post_init__(self):
        if not _text(self.rationale) or not self.case_analysis_item_ids or not self.source_provenance:
            raise ValueError("planning derivation requires rationale, analysis items and provenance")
        for values in (
            self.case_analysis_item_ids,
            self.question_ids,
            self.pericial_object_ids,
            self.court_decision_ids,
            self.technical_document_reference_ids,
            self.gap_or_conflict_ids,
        ):
            if any(not _text(value) for value in values) or len(values) != len(set(values)):
                raise ValueError("planning derivation identities are invalid")
        if any(type(source) is not SourceProvenance for source in self.source_provenance):
            raise ValueError("planning derivation provenance is invalid")


@dataclass(frozen=True, slots=True)
class PlanningItem:
    item_id: str
    title: str
    description: str
    priority: str
    derivation: PlanningDerivation
    proposal_status: ProposalStatus
    professional_review_status: ProfessionalReviewStatus

    def __post_init__(self):
        if not all(_text(value) for value in (self.item_id, self.title, self.description, self.priority)):
            raise ValueError("planning item requires identity and proposal content")
        if type(self.derivation) is not PlanningDerivation or self.proposal_status is not ProposalStatus.PROPOSED:
            raise ValueError("planning item must remain a derived proposal")
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in {
                "item_id",
                "title",
                "description",
                "priority",
                "derivation",
                "proposal_status",
                "professional_review_status",
                "dependency_item_ids",
                "normative_references",
            }:
                continue
            if type(value) is str and not value.strip():
                raise ValueError("planning subtype content cannot be empty")
            if type(value) is tuple and (not value or any(not _text(item) for item in value)):
                raise ValueError("planning subtype list cannot be empty")


@dataclass(frozen=True, slots=True)
class PlanningObjective(PlanningItem):
    pass


@dataclass(frozen=True, slots=True)
class PlanningIssue(PlanningItem):
    pass


@dataclass(frozen=True, slots=True)
class QuestionPlanningLink(PlanningItem):
    question_id: str
    linked_item_ids: tuple[str, ...]
    dependency_item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RequiredDocument(PlanningItem):
    document_description: str
    required_before: str


@dataclass(frozen=True, slots=True)
class RequiredInformation(PlanningItem):
    information_description: str
    requested_from: str


@dataclass(frozen=True, slots=True)
class InspectionRequirement(PlanningItem):
    inspection_target: str
    field_observations_needed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeasurementRequirement(PlanningItem):
    quantity: str
    unit: str
    purpose: str


@dataclass(frozen=True, slots=True)
class PhotoRequirement(PlanningItem):
    subject: str
    purpose: str


@dataclass(frozen=True, slots=True)
class EquipmentRequirement(PlanningItem):
    equipment: str
    purpose: str


@dataclass(frozen=True, slots=True)
class AccessRequirement(PlanningItem):
    access_type: str
    target: str
    responsible_contact: str


@dataclass(frozen=True, slots=True)
class NormativeReference:
    reference_id: str
    title: str
    edition: str
    applicability_status: str

    def __post_init__(self):
        if not all(_text(value) for value in (self.reference_id, self.title, self.edition)):
            raise ValueError("normative reference metadata is invalid")
        if self.applicability_status != "PENDING_PROFESSIONAL_REVIEW":
            raise ValueError("normative applicability cannot be adopted inside a proposal")


@dataclass(frozen=True, slots=True)
class MethodCandidate(PlanningItem):
    method_name: str
    purpose: str
    applicability_rationale: str
    required_inputs: tuple[str, ...]
    limitations: tuple[str, ...]
    normative_references: tuple[NormativeReference, ...]


@dataclass(frozen=True, slots=True)
class ProcedureCandidate(PlanningItem):
    procedure_name: str
    purpose: str
    planned_steps: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SamplingCandidate(PlanningItem):
    population: str
    candidate_strategy: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SafetyRequirement(PlanningItem):
    hazard: str
    precaution: str


@dataclass(frozen=True, slots=True)
class ExternalSupportRequirement(PlanningItem):
    support_type: str
    purpose: str


@dataclass(frozen=True, slots=True)
class PlanningRisk(PlanningItem):
    risk: str
    mitigation: str


@dataclass(frozen=True, slots=True)
class PlanningGap(PlanningItem):
    gap: str
    consequence: str


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    decision_id: str
    target_item_id: str
    action: ReviewAction
    proposal_value: str
    decided_value: str | None
    reviewer: str
    reason: str
    revision: int
    timestamp: str

    def __post_init__(self):
        if not all(
            _text(value)
            for value in (
                self.decision_id,
                self.target_item_id,
                self.proposal_value,
                self.reviewer,
                self.reason,
                self.timestamp,
            )
        ):
            raise ValueError("professional planning decision is invalid")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("professional planning decision revision is invalid")
        if self.action is ReviewAction.MODIFY:
            if not _text(self.decided_value) or self.decided_value == self.proposal_value:
                raise ValueError("modified planning decision requires a distinct value")
        elif self.decided_value is not None:
            raise ValueError("only MODIFY may carry a decided value")


@dataclass(frozen=True, slots=True)
class PlanningCoverage:
    material_items_total: int
    reviewed_items: int
    pending_items: int
    approved_items: int
    rejected_items: int
    modified_items: int
    deferred_items: int
    readiness: ReadinessStatus
    readiness_reasons: tuple[str, ...]

    def __post_init__(self):
        counts = (
            self.material_items_total,
            self.reviewed_items,
            self.pending_items,
            self.approved_items,
            self.rejected_items,
            self.modified_items,
            self.deferred_items,
        )
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("planning coverage counts are invalid")
        if self.reviewed_items + self.pending_items != self.material_items_total:
            raise ValueError("planning coverage total is dishonest")
        if self.approved_items + self.rejected_items + self.modified_items + self.deferred_items != self.reviewed_items:
            raise ValueError("planning review coverage is dishonest")
        if any(not _text(reason) for reason in self.readiness_reasons):
            raise ValueError("planning readiness reasons are invalid")
        if self.readiness is ReadinessStatus.READY and (self.pending_items or self.readiness_reasons):
            raise ValueError("planning readiness cannot be inferred from plan existence")
        if self.readiness is not ReadinessStatus.READY and not self.readiness_reasons:
            raise ValueError("non-ready planning requires explicit reasons")


@dataclass(frozen=True, slots=True)
class PericialPlan:
    plan_id: str
    title: str
    workspace_id: str
    case_analysis_snapshot_id: str
    case_analysis_revision: int
    case_analysis_source_revision: int
    case_analysis_digest: str

    def __post_init__(self):
        if not all(_text(value) for value in (self.plan_id, self.title, self.workspace_id, self.case_analysis_snapshot_id)):
            raise ValueError("pericial plan identity is invalid")
        if type(self.case_analysis_revision) is not int or self.case_analysis_revision < 1:
            raise ValueError("Case Analysis artifact revision is invalid")
        if type(self.case_analysis_source_revision) is not int or self.case_analysis_source_revision < 1:
            raise ValueError("Case Analysis source revision is invalid")
        if type(self.case_analysis_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", self.case_analysis_digest) is None:
            raise ValueError("Case Analysis digest is invalid")


@dataclass(frozen=True, slots=True)
class PlanningSnapshot:
    schema_version: str
    snapshot_id: str
    workspace_id: str
    plan: PericialPlan
    objectives: tuple[PlanningObjective, ...]
    issues: tuple[PlanningIssue, ...]
    question_links: tuple[QuestionPlanningLink, ...]
    required_documents: tuple[RequiredDocument, ...]
    required_information: tuple[RequiredInformation, ...]
    inspection_requirements: tuple[InspectionRequirement, ...]
    measurement_requirements: tuple[MeasurementRequirement, ...]
    photo_requirements: tuple[PhotoRequirement, ...]
    equipment_requirements: tuple[EquipmentRequirement, ...]
    access_requirements: tuple[AccessRequirement, ...]
    method_candidates: tuple[MethodCandidate, ...]
    procedure_candidates: tuple[ProcedureCandidate, ...]
    sampling_candidates: tuple[SamplingCandidate, ...]
    safety_requirements: tuple[SafetyRequirement, ...]
    external_support_requirements: tuple[ExternalSupportRequirement, ...]
    risks: tuple[PlanningRisk, ...]
    gaps: tuple[PlanningGap, ...]
    decisions: tuple[PlanningDecision, ...]
    coverage: PlanningCoverage
    upstream_stale: bool = False
    upstream_stale_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if self.schema_version != "1.0.0":
            raise ValueError("unsupported Pericial Planning schema version")
        if not _text(self.snapshot_id) or not _text(self.workspace_id) or self.plan.workspace_id != self.workspace_id:
            raise ValueError("planning snapshot workspace identity mismatch")
        if type(self.upstream_stale) is not bool or self.upstream_stale != bool(self.upstream_stale_reasons):
            raise ValueError("planning upstream stale state is dishonest")
        if any(not _text(reason) for reason in self.upstream_stale_reasons):
            raise ValueError("planning upstream stale reasons are invalid")
        items = self.material_items
        identities = [item.item_id for item in items]
        if len(identities) != len(set(identities)):
            raise ValueError("planning item identities must be globally unique")
        item_by_id = {item.item_id: item for item in items}
        if any(link.question_id not in link.derivation.question_ids for link in self.question_links):
            raise ValueError("question planning link must derive from its question")
        if any(
            not set((*link.linked_item_ids, *link.dependency_item_ids)) <= set(item_by_id)
            or link.item_id in (*link.linked_item_ids, *link.dependency_item_ids)
            for link in self.question_links
        ):
            raise ValueError("question planning link contains dangling or cyclic references")
        decisions_by_target: dict[str, list[PlanningDecision]] = {}
        decision_ids: set[str] = set()
        for decision in self.decisions:
            if decision.decision_id in decision_ids or decision.target_item_id not in item_by_id:
                raise ValueError("planning decision identity or target is invalid")
            decision_ids.add(decision.decision_id)
            item = item_by_id[decision.target_item_id]
            if decision.proposal_value != item.description:
                raise ValueError("planning decision cannot replace the original proposal")
            decisions_by_target.setdefault(decision.target_item_id, []).append(decision)
        expected_status = {
            ReviewAction.APPROVE: ProfessionalReviewStatus.APPROVED,
            ReviewAction.REJECT: ProfessionalReviewStatus.REJECTED,
            ReviewAction.MODIFY: ProfessionalReviewStatus.MODIFIED,
            ReviewAction.DEFER: ProfessionalReviewStatus.DEFERRED,
        }
        for item in items:
            history = sorted(decisions_by_target.get(item.item_id, ()), key=lambda decision: decision.revision)
            if history and [decision.revision for decision in history] != list(range(1, len(history) + 1)):
                raise ValueError("planning decision history must be contiguous")
            status = ProfessionalReviewStatus.PENDING if not history else expected_status[history[-1].action]
            if item.professional_review_status is not status:
                raise ValueError("planning professional status requires explicit review history")
        statuses = [item.professional_review_status for item in items]
        counts = {
            ProfessionalReviewStatus.PENDING: statuses.count(ProfessionalReviewStatus.PENDING),
            ProfessionalReviewStatus.APPROVED: statuses.count(ProfessionalReviewStatus.APPROVED),
            ProfessionalReviewStatus.REJECTED: statuses.count(ProfessionalReviewStatus.REJECTED),
            ProfessionalReviewStatus.MODIFIED: statuses.count(ProfessionalReviewStatus.MODIFIED),
            ProfessionalReviewStatus.DEFERRED: statuses.count(ProfessionalReviewStatus.DEFERRED),
        }
        expected = (
            len(items),
            len(items) - counts[ProfessionalReviewStatus.PENDING],
            counts[ProfessionalReviewStatus.PENDING],
            counts[ProfessionalReviewStatus.APPROVED],
            counts[ProfessionalReviewStatus.REJECTED],
            counts[ProfessionalReviewStatus.MODIFIED],
            counts[ProfessionalReviewStatus.DEFERRED],
        )
        actual = (
            self.coverage.material_items_total,
            self.coverage.reviewed_items,
            self.coverage.pending_items,
            self.coverage.approved_items,
            self.coverage.rejected_items,
            self.coverage.modified_items,
            self.coverage.deferred_items,
        )
        if actual != expected:
            raise ValueError("planning coverage must derive from proposal review state")

    @property
    def material_items(self) -> tuple[PlanningItem, ...]:
        return (
            *self.objectives,
            *self.issues,
            *self.question_links,
            *self.required_documents,
            *self.required_information,
            *self.inspection_requirements,
            *self.measurement_requirements,
            *self.photo_requirements,
            *self.equipment_requirements,
            *self.access_requirements,
            *self.method_candidates,
            *self.procedure_candidates,
            *self.sampling_candidates,
            *self.safety_requirements,
            *self.external_support_requirements,
            *self.risks,
            *self.gaps,
        )

    def reconcile_upstream(self, *, snapshot_id: str, revision: int, source_revision: int, digest: str):
        reasons = []
        if snapshot_id != self.plan.case_analysis_snapshot_id:
            reasons.append("Case Analysis snapshot changed")
        if revision != self.plan.case_analysis_revision:
            reasons.append("Case Analysis artifact revision changed")
        if source_revision != self.plan.case_analysis_source_revision:
            reasons.append("Case Analysis source revision changed")
        if digest != self.plan.case_analysis_digest:
            reasons.append("Case Analysis content changed")
        return replace(self, upstream_stale=bool(reasons), upstream_stale_reasons=tuple(reasons))


_COLLECTION_TYPES: dict[str, type[PlanningItem]] = {
    "objectives": PlanningObjective,
    "issues": PlanningIssue,
    "question_links": QuestionPlanningLink,
    "required_documents": RequiredDocument,
    "required_information": RequiredInformation,
    "inspection_requirements": InspectionRequirement,
    "measurement_requirements": MeasurementRequirement,
    "photo_requirements": PhotoRequirement,
    "equipment_requirements": EquipmentRequirement,
    "access_requirements": AccessRequirement,
    "method_candidates": MethodCandidate,
    "procedure_candidates": ProcedureCandidate,
    "sampling_candidates": SamplingCandidate,
    "safety_requirements": SafetyRequirement,
    "external_support_requirements": ExternalSupportRequirement,
    "risks": PlanningRisk,
    "gaps": PlanningGap,
}


def pericial_planning_from_mapping(value: object) -> PlanningSnapshot:
    try:
        raw = _object(value, _snapshot_fields())
        plan = PericialPlan(**_object(raw["plan"], _field_names(PericialPlan)))
        collections: dict[str, tuple[PlanningItem, ...]] = {}
        for name, item_type in _COLLECTION_TYPES.items():
            values = raw[name]
            if type(values) is not list:
                raise TypeError(f"{name} must be an array")
            collections[name] = tuple(_item_from_mapping(item_type, item) for item in values)
        decisions = tuple(
            PlanningDecision(
                **{
                    **_object(item, _field_names(PlanningDecision)),
                    "action": ReviewAction(item["action"]),
                }
            )
            for item in _array(raw["decisions"])
        )
        coverage_raw = _object(raw["coverage"], _field_names(PlanningCoverage))
        coverage = PlanningCoverage(
            **{
                **coverage_raw,
                "readiness": ReadinessStatus(coverage_raw["readiness"]),
                "readiness_reasons": tuple(_array(coverage_raw["readiness_reasons"])),
            }
        )
        return PlanningSnapshot(
            schema_version=raw["schema_version"],
            snapshot_id=raw["snapshot_id"],
            workspace_id=raw["workspace_id"],
            plan=plan,
            decisions=decisions,
            coverage=coverage,
            upstream_stale=raw["upstream_stale"],
            upstream_stale_reasons=tuple(_array(raw["upstream_stale_reasons"])),
            **collections,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid Pericial Planning payload") from exc


def pericial_planning_to_mapping(snapshot: PlanningSnapshot) -> dict[str, Any]:
    if type(snapshot) is not PlanningSnapshot:
        raise TypeError("expected PlanningSnapshot")
    return _json_value(asdict(snapshot))


def case_analysis_digest(snapshot: CaseAnalysisSnapshot) -> str:
    if type(snapshot) is not CaseAnalysisSnapshot:
        raise TypeError("expected CaseAnalysisSnapshot")
    canonical = json.dumps(
        case_analysis_to_mapping(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_against_case_analysis(
    planning: PlanningSnapshot,
    analysis: CaseAnalysisSnapshot,
    *,
    artifact_revision: int,
) -> None:
    if type(planning) is not PlanningSnapshot or type(analysis) is not CaseAnalysisSnapshot:
        raise TypeError("canonical planning and Case Analysis snapshots are required")
    if type(artifact_revision) is not int or artifact_revision < 1:
        raise ValueError("Case Analysis artifact revision is invalid")
    if planning.workspace_id != analysis.workspace_id:
        raise ValueError("planning and Case Analysis workspace mismatch")
    if (
        planning.plan.case_analysis_snapshot_id != analysis.snapshot_id
        or planning.plan.case_analysis_revision != artifact_revision
        or planning.plan.case_analysis_source_revision != analysis.source_revision
        or planning.plan.case_analysis_digest != case_analysis_digest(analysis)
    ):
        raise ValueError("planning Case Analysis dependency mismatch")
    by_id = {item.item_id: item for item in analysis.material_items}
    collection_ids = {
        "questions": {item.item_id for item in analysis.questions},
        "objects": {item.item_id for item in analysis.pericial_objects},
        "decisions": {item.item_id for item in analysis.decisions},
        "technical": {item.item_id for item in analysis.technical_document_references},
        "gaps_conflicts": {item.item_id for item in (*analysis.gaps, *analysis.conflicts)},
    }
    linked_questions = {item.question_id for item in planning.question_links}
    required_questions = collection_ids["questions"]
    if linked_questions != required_questions or len(planning.question_links) != len(linked_questions):
        raise ValueError("planning question linkage must cover every Case Analysis question exactly")
    actionable_items = {
        item.item_id: item
        for collection_name in (
            "required_documents", "required_information", "inspection_requirements",
            "measurement_requirements", "photo_requirements", "equipment_requirements",
            "access_requirements", "method_candidates", "procedure_candidates",
            "sampling_candidates", "safety_requirements", "external_support_requirements",
        )
        for item in getattr(planning, collection_name)
    }
    planning_items_by_id = {item.item_id: item for item in planning.material_items}
    if any(
        link.question_id not in link.derivation.question_ids
        or bool(set(link.linked_item_ids) & set(link.dependency_item_ids))
        or not (set((*link.linked_item_ids, *link.dependency_item_ids)) & set(actionable_items))
        or any(
            link.question_id not in planning_items_by_id[item_id].derivation.question_ids
            for item_id in (*link.linked_item_ids, *link.dependency_item_ids)
        )
        for link in planning.question_links
    ):
        raise ValueError("planning question linkage requires a question-derived preparation or inspection action")
    for item in planning.material_items:
        derivation = item.derivation
        referenced = set(derivation.case_analysis_item_ids)
        specialized = {
            *derivation.question_ids,
            *derivation.pericial_object_ids,
            *derivation.court_decision_ids,
            *derivation.technical_document_reference_ids,
            *derivation.gap_or_conflict_ids,
        }
        typed_referenced = referenced & set().union(*collection_ids.values())
        if not referenced <= set(by_id) or specialized != typed_referenced:
            raise ValueError("planning derivation authority does not match Case Analysis item types")
        if (
            not set(derivation.question_ids) <= collection_ids["questions"]
            or not set(derivation.pericial_object_ids) <= collection_ids["objects"]
            or not set(derivation.court_decision_ids) <= collection_ids["decisions"]
            or not set(derivation.technical_document_reference_ids) <= collection_ids["technical"]
            or not set(derivation.gap_or_conflict_ids) <= collection_ids["gaps_conflicts"]
        ):
            raise ValueError("planning derivation uses the wrong Case Analysis authority collection")
        allowed_provenance = {
            source
            for analysis_item_id in referenced
            for source in by_id[analysis_item_id].provenance
        }
        if any(source.workspace_id != planning.workspace_id for source in derivation.source_provenance):
            raise ValueError("planning provenance crosses workspace authority")
        if not set(derivation.source_provenance) <= allowed_provenance:
            raise ValueError("planning provenance is not exact Case Analysis provenance")
        if any(
            not (set(derivation.source_provenance) & set(by_id[analysis_item_id].provenance))
            for analysis_item_id in referenced
        ):
            raise ValueError("planning provenance must cover every referenced Case Analysis item")


def append_professional_decision(snapshot: PlanningSnapshot, decision: PlanningDecision) -> PlanningSnapshot:
    if type(snapshot) is not PlanningSnapshot or type(decision) is not PlanningDecision:
        raise TypeError("canonical planning snapshot and decision are required")
    status_by_action = {
        ReviewAction.APPROVE: ProfessionalReviewStatus.APPROVED,
        ReviewAction.REJECT: ProfessionalReviewStatus.REJECTED,
        ReviewAction.MODIFY: ProfessionalReviewStatus.MODIFIED,
        ReviewAction.DEFER: ProfessionalReviewStatus.DEFERRED,
    }
    target = next((item for item in snapshot.material_items if item.item_id == decision.target_item_id), None)
    if target is None or decision.proposal_value != target.description:
        raise ValueError("professional decision target or proposal is invalid")
    history = [item for item in snapshot.decisions if item.target_item_id == decision.target_item_id]
    if decision.revision != len(history) + 1:
        raise ValueError("professional decision revision must append contiguously")
    collection_updates = {}
    for collection_name in _COLLECTION_TYPES:
        collection = getattr(snapshot, collection_name)
        if any(item.item_id == decision.target_item_id for item in collection):
            collection_updates[collection_name] = tuple(
                replace(item, professional_review_status=status_by_action[decision.action])
                if item.item_id == decision.target_item_id
                else item
                for item in collection
            )
            break
    statuses = [
        item.professional_review_status
        for name in _COLLECTION_TYPES
        for item in collection_updates.get(name, getattr(snapshot, name))
    ]
    pending = statuses.count(ProfessionalReviewStatus.PENDING)
    approved = statuses.count(ProfessionalReviewStatus.APPROVED)
    rejected = statuses.count(ProfessionalReviewStatus.REJECTED)
    modified = statuses.count(ProfessionalReviewStatus.MODIFIED)
    deferred = statuses.count(ProfessionalReviewStatus.DEFERRED)
    if pending:
        readiness = ReadinessStatus.PARTIAL
        reasons = ("Itens materiais aguardam revisão profissional.",)
    elif rejected or deferred:
        readiness = ReadinessStatus.BLOCKED
        reasons = tuple(
            reason
            for count, reason in (
                (rejected, "Itens materiais foram rejeitados pelo profissional."),
                (deferred, "Itens materiais tiveram decisão profissional adiada."),
            )
            if count
        )
    else:
        readiness = ReadinessStatus.READY
        reasons = ()
    coverage = PlanningCoverage(
        material_items_total=len(statuses),
        reviewed_items=len(statuses) - pending,
        pending_items=pending,
        approved_items=approved,
        rejected_items=rejected,
        modified_items=modified,
        deferred_items=deferred,
        readiness=readiness,
        readiness_reasons=reasons,
    )
    return replace(
        snapshot,
        decisions=(*snapshot.decisions, decision),
        coverage=coverage,
        **collection_updates,
    )


def _item_from_mapping(item_type: type[PlanningItem], value: object) -> PlanningItem:
    raw = _object(value, _field_names(item_type))
    derivation_raw = _object(raw["derivation"], _field_names(PlanningDerivation))
    provenance = tuple(
        SourceProvenance(**_object(source, _field_names(SourceProvenance)))
        for source in _array(derivation_raw["source_provenance"])
    )
    derivation = PlanningDerivation(
        rationale=derivation_raw["rationale"],
        case_analysis_item_ids=tuple(_array(derivation_raw["case_analysis_item_ids"])),
        source_provenance=provenance,
        question_ids=tuple(_array(derivation_raw["question_ids"])),
        pericial_object_ids=tuple(_array(derivation_raw["pericial_object_ids"])),
        court_decision_ids=tuple(_array(derivation_raw["court_decision_ids"])),
        technical_document_reference_ids=tuple(_array(derivation_raw["technical_document_reference_ids"])),
        gap_or_conflict_ids=tuple(_array(derivation_raw["gap_or_conflict_ids"])),
    )
    kwargs = {
        **raw,
        "derivation": derivation,
        "proposal_status": ProposalStatus(raw["proposal_status"]),
        "professional_review_status": ProfessionalReviewStatus(raw["professional_review_status"]),
    }
    tuple_fields = {
        "linked_item_ids",
        "dependency_item_ids",
        "field_observations_needed",
        "required_inputs",
        "limitations",
        "planned_steps",
    }
    for name in tuple_fields & kwargs.keys():
        kwargs[name] = tuple(_array(kwargs[name]))
    if item_type is MethodCandidate:
        kwargs["normative_references"] = tuple(
            NormativeReference(**_object(reference, _field_names(NormativeReference)))
            for reference in _array(raw["normative_references"])
        )
    return item_type(**kwargs)


def _snapshot_fields() -> set[str]:
    return _field_names(PlanningSnapshot)


def _field_names(item_type) -> set[str]:
    return {field.name for field in fields(item_type)}


def _object(value: object, exact_fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != exact_fields:
        raise TypeError("object fields are not canonical")
    return value


def _array(value: object) -> list[Any]:
    if type(value) is not list:
        raise TypeError("expected array")
    return value


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _json_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value
