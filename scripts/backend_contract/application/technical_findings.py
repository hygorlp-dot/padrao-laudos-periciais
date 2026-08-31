"""Application authority for upstream-bound Technical Snapshot revisions."""

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..case_analysis import CaseAnalysisSnapshot, case_analysis_to_mapping
from ..technical_findings import (
    ConflictStatus,
    DecisionAction,
    EvidenceAssessment,
    EvidenceItem,
    EvidenceReviewState,
    EvidenceSourceLink,
    FindingConflict,
    FindingLimitation,
    FindingUncertainty,
    MethodApplication,
    MethodInput,
    MethodOutput,
    ProfessionalDecision,
    ProposalOrigin,
    TECHNICAL_SNAPSHOT_ARTIFACT_ID,
    TECHNICAL_SNAPSHOT_ARTIFACT_KIND,
    TechnicalCoverage,
    TechnicalSnapshot,
    TechnicalFinding,
    TechnicalFindingProposal,
    TechnicalSourceSnapshot,
    technical_snapshot_from_mapping,
    technical_snapshot_to_mapping,
)
from ..vistoria import InspectionSession, inspection_session_to_mapping
from .models import thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "technical-snapshot-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker())


def technical_upstream_digest(value: object) -> str:
    if type(value) is CaseAnalysisSnapshot:
        mapping = case_analysis_to_mapping(value)
    elif type(value) is InspectionSession:
        mapping = inspection_session_to_mapping(value)
    else:
        raise TypeError("unsupported Technical Snapshot upstream authority")
    encoded = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validated_technical_snapshot_from_mapping(value: object) -> TechnicalSnapshot:
    try:
        _VALIDATOR.validate(value)
        return technical_snapshot_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Technical Snapshot payload") from exc


def technical_snapshot_to_validated_mapping(value: object) -> dict[str, object]:
    if type(value) is not TechnicalSnapshot:
        raise RepositoryIntegrityError("Technical Snapshot persisted state is invalid")
    return technical_snapshot_to_mapping(value)


def _binding(*, workspace_id, case_record, case, inspection_record, inspection) -> TechnicalSourceSnapshot:
    if (
        type(case) is not CaseAnalysisSnapshot
        or type(inspection) is not InspectionSession
        or case.workspace_id != str(workspace_id)
        or inspection.workspace_id != str(workspace_id)
    ):
        raise ValueError("Technical Snapshot upstream workspace mismatch")
    return TechnicalSourceSnapshot(
        workspace_id=str(workspace_id),
        case_analysis_snapshot_id=case.snapshot_id,
        case_analysis_revision=case_record.revision,
        case_analysis_digest=technical_upstream_digest(case),
        inspection_session_id=inspection.session_id,
        inspection_session_revision=inspection_record.revision,
        inspection_session_digest=technical_upstream_digest(inspection),
        source_revision=inspection.source_revision,
    )


def _reconcile(snapshot: TechnicalSnapshot, *, current: TechnicalSourceSnapshot) -> TechnicalSnapshot:
    bound = snapshot.source_snapshot
    reasons = []
    comparisons = (
        (bound.case_analysis_snapshot_id, current.case_analysis_snapshot_id, "case analysis snapshot identity changed"),
        (bound.case_analysis_revision, current.case_analysis_revision, "case analysis artifact revision changed"),
        (bound.case_analysis_digest, current.case_analysis_digest, "case analysis content changed"),
        (bound.inspection_session_id, current.inspection_session_id, "inspection session identity changed"),
        (bound.inspection_session_revision, current.inspection_session_revision, "inspection session artifact revision changed"),
        (bound.inspection_session_digest, current.inspection_session_digest, "inspection session content changed"),
        (bound.source_revision, current.source_revision, "upstream source revision changed"),
    )
    reasons.extend(reason for actual, expected, reason in comparisons if actual != expected)
    coverage = replace(snapshot.coverage, complete=False) if reasons and snapshot.coverage.complete else snapshot.coverage
    return replace(snapshot, coverage=coverage, upstream_stale=bool(reasons), upstream_stale_reasons=tuple(reasons))


def _validate_upstream_links(snapshot: TechnicalSnapshot, case: CaseAnalysisSnapshot, inspection: InspectionSession) -> None:
    case_kinds = {"CASE_DOCUMENT", "DOCUMENTED_ALLEGATION", "CASE_CLAIM", "CASE_COUNTERARGUMENT", "CASE_DECISION", "CASE_QUESTION"}
    authority_by_kind = {
        "CASE_DOCUMENT": {item.document_id for item in case.documents},
        "DOCUMENTED_ALLEGATION": {source.occurrence_id for item in case.claims for source in item.provenance},
        "CASE_CLAIM": {item.item_id for item in case.claims},
        "CASE_COUNTERARGUMENT": {item.item_id for item in case.counterarguments},
        "CASE_DECISION": {item.item_id for item in case.decisions},
        "CASE_QUESTION": {item.item_id for item in case.questions},
        "FIELD_RECORD": {item.item_id for item in inspection.items},
        "FIELD_OBSERVATION": {item.observation_id for item in inspection.observations},
        "FIELD_STATEMENT": {item.statement_id for item in inspection.statements},
        "MEASUREMENT": {item.measurement_id for item in inspection.measurements},
        "PHOTO_RECORD": {item.photo_id for item in inspection.photos},
        "ACCESS_OCCURRENCE": {item.occurrence_id for item in inspection.access_occurrences},
        "FIELD_LIMITATION": {item.limitation_id for item in inspection.limitations},
    }
    for link in snapshot.source_links:
        authority = authority_by_kind.get(link.source_kind, set())
        if link.source_id not in authority:
            raise ValueError("Technical Snapshot source identity is absent from bound upstream")
        expected_revision = (
            snapshot.source_snapshot.case_analysis_revision
            if link.source_kind in case_kinds
            else snapshot.source_snapshot.inspection_session_revision
        )
        if link.source_revision != expected_revision:
            raise ValueError("Technical Snapshot source revision differs from bound upstream")
    question_ids = {item.item_id for item in case.questions}
    if any(link.question_id not in question_ids for link in snapshot.question_links):
        raise ValueError("Technical Snapshot question identity is absent from Case Analysis")


@dataclass(frozen=True, slots=True)
class SaveTechnicalSnapshot:
    revisions: object
    get_latest_revision: object
    get_case_analysis: object
    get_inspection_session: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, snapshot: TechnicalSnapshot, expected_revision: int | None, *, mutation_authority: str | None = None):
        if type(snapshot) is not TechnicalSnapshot or snapshot.workspace_id != str(workspace_id):
            raise ValueError("Technical Snapshot workspace mismatch")
        if snapshot.upstream_stale:
            raise ValueError("stale Technical Snapshot cannot be persisted")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("Technical Snapshot expected revision is invalid")
        if expected_revision is None:
            if mutation_authority != "START" or any((
                snapshot.evidence_items, snapshot.source_links, snapshot.evidence_assessments, snapshot.method_applications,
                snapshot.method_inputs, snapshot.method_outputs, snapshot.finding_proposals, snapshot.findings,
                snapshot.dependencies, snapshot.conflicts, snapshot.limitations, snapshot.uncertainties,
                snapshot.question_links, snapshot.decisions,
            )):
                raise ValueError("initial Technical Snapshot requires the canonical start command")
        elif mutation_authority not in {"PROPOSAL", "PROFESSIONAL"}:
            raise ValueError("Technical Snapshot mutation requires a dedicated command")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Technical Snapshot authority guard is unavailable")
        with self.authority_guard():
            if expected_revision is not None:
                predecessor_record = self.get_latest_revision.execute(
                    workspace_id, TECHNICAL_SNAPSHOT_ARTIFACT_KIND, TECHNICAL_SNAPSHOT_ARTIFACT_ID
                )
                if predecessor_record.revision != expected_revision:
                    raise RepositoryConflict("expected Technical Snapshot revision is not latest")
                predecessor = validated_technical_snapshot_from_mapping(thaw_payload(predecessor_record.payload))
                if snapshot.snapshot_id != predecessor.snapshot_id or snapshot.source_snapshot != predecessor.source_snapshot:
                    raise ValueError("Technical Snapshot immutable identity changed")
                append_only = (
                    "evidence_items", "source_links", "method_applications", "method_inputs", "method_outputs",
                    "finding_proposals", "dependencies", "limitations", "uncertainties",
                )
                if any(getattr(snapshot, name)[:len(getattr(predecessor, name))] != getattr(predecessor, name) for name in append_only):
                    raise ValueError("Technical proposal origin or history cannot be rewritten")
                if snapshot.decisions[:len(predecessor.decisions)] != predecessor.decisions or snapshot.findings[:len(predecessor.findings)] != predecessor.findings:
                    raise ValueError("Technical professional authority history cannot be rewritten")
                prior_assessments = {item.assessment_id: item for item in predecessor.evidence_assessments}
                current_assessments = {item.assessment_id: item for item in snapshot.evidence_assessments}
                if not prior_assessments.keys() <= current_assessments.keys():
                    raise ValueError("Technical evidence review history cannot disappear")
                for assessment_id, previous in prior_assessments.items():
                    current_assessment = current_assessments[assessment_id]
                    if previous.review_state is not EvidenceReviewState.PENDING and current_assessment != previous:
                        raise ValueError("reviewed evidence authority is immutable")
                    if mutation_authority != "PROFESSIONAL" and current_assessment != previous:
                        raise ValueError("evidence review requires a professional command")
                if mutation_authority != "PROFESSIONAL" and (
                    snapshot.decisions != predecessor.decisions or snapshot.findings != predecessor.findings
                    or snapshot.question_links != predecessor.question_links
                ):
                    raise ValueError("professional authority requires a dedicated command")
                if mutation_authority == "PROPOSAL":
                    new_assessments = snapshot.evidence_assessments[len(predecessor.evidence_assessments):]
                    if any(item.review_state is not EvidenceReviewState.PENDING or item.review_id is not None or item.reviewer is not None or item.review_reason is not None or item.reviewed_at is not None for item in new_assessments):
                        raise ValueError("client proposal cannot self-approve evidence")
                    if any(item.selection_authority != "PROPOSAL_ONLY" for item in snapshot.method_applications[len(predecessor.method_applications):]):
                        raise ValueError("method proposal cannot claim professional selection")
                    if snapshot.conflicts[:len(predecessor.conflicts)] != predecessor.conflicts or any(
                        item.status is not ConflictStatus.UNRESOLVED or item.resolution_reasoning is not None or item.decision_id is not None
                        for item in snapshot.conflicts[len(predecessor.conflicts):]
                    ):
                        raise ValueError("proposal conflict cannot claim professional resolution")
            case_record, case = self.get_case_analysis.execute(workspace_id)
            inspection_record, inspection = self.get_inspection_session.execute(workspace_id)
            current = _binding(
                workspace_id=workspace_id, case_record=case_record, case=case,
                inspection_record=inspection_record, inspection=inspection,
            )
            if _reconcile(snapshot, current=current).upstream_stale:
                raise ValueError("Technical Snapshot upstream authority is stale")
            _validate_upstream_links(snapshot, case, inspection)
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Technical Snapshot clock requires timezone")
            dependencies = tuple({
                "artifact_kind": record.artifact_kind,
                "artifact_id": record.artifact_id,
                "revision": record.revision,
                "checksum_sha256": record.checksum_sha256,
            } for record in (case_record, inspection_record))
            return self.revisions.append_if_latest(
                workspace_id=workspace_id,
                artifact_kind=TECHNICAL_SNAPSHOT_ARTIFACT_KIND,
                artifact_id=TECHNICAL_SNAPSHOT_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()),
                created_at=created_at.isoformat(),
                payload=technical_snapshot_to_mapping(snapshot),
                expected_revision=expected_revision,
                expected_dependencies=dependencies,
            )


@dataclass(frozen=True, slots=True)
class GetTechnicalSnapshot:
    get_latest_revision: object
    get_case_analysis: object
    get_inspection_session: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id, TECHNICAL_SNAPSHOT_ARTIFACT_KIND, TECHNICAL_SNAPSHOT_ARTIFACT_ID
        )
        snapshot = validated_technical_snapshot_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Technical Snapshot workspace mismatch")
        case_record, case = self.get_case_analysis.execute(workspace_id)
        inspection_record, inspection = self.get_inspection_session.execute(workspace_id)
        current = _binding(
            workspace_id=workspace_id, case_record=case_record, case=case,
            inspection_record=inspection_record, inspection=inspection,
        )
        return record, _reconcile(snapshot, current=current)


@dataclass(frozen=True, slots=True)
class StartTechnicalSnapshot:
    get_case_analysis: object
    get_inspection_session: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id):
        case_record, case = self.get_case_analysis.execute(workspace_id)
        inspection_record, inspection = self.get_inspection_session.execute(workspace_id)
        if case.source_inventory_stale or inspection.upstream_stale:
            raise ValueError("stale upstream cannot start a Technical Snapshot")
        source = _binding(
            workspace_id=workspace_id, case_record=case_record, case=case,
            inspection_record=inspection_record, inspection=inspection,
        )
        snapshot = TechnicalSnapshot(
            schema_version="1.0.0",
            snapshot_id=f"TECHNICAL-SNAPSHOT-{self.ids.new_uuid().hex.upper()}",
            workspace_id=str(workspace_id), source_snapshot=source,
            evidence_items=(), source_links=(), evidence_assessments=(),
            method_applications=(), method_inputs=(), method_outputs=(),
            finding_proposals=(), findings=(), dependencies=(), conflicts=(),
            limitations=(), uncertainties=(), question_links=(), decisions=(),
            coverage=TechnicalCoverage(
                evidence_items=0, approved_evidence=0, method_applications=0,
                finding_proposals=0, effective_findings=0, unresolved_conflicts=0,
                complete=False, reasons=("A cadeia técnica ainda não possui evidências avaliadas.",),
            ),
            upstream_stale=False, upstream_stale_reasons=(),
        )
        record = self.save_snapshot.execute(workspace_id, snapshot, None, mutation_authority="START")
        return record, snapshot


@dataclass(frozen=True, slots=True)
class AddEvidenceProposal:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, source_kind: str, source_id: str, proposition: str, why_relevant: str, expected_revision: int):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.upstream_stale:
            raise RepositoryConflict("Technical Snapshot revision or upstream is stale")
        token = self.ids.new_uuid().hex.upper()
        evidence_id, assessment_id, link_id = f"EVIDENCE-{token}", f"ASSESSMENT-{token}", f"SOURCE-LINK-{token}"
        case_kinds = {"CASE_DOCUMENT", "DOCUMENTED_ALLEGATION", "CASE_CLAIM", "CASE_COUNTERARGUMENT", "CASE_DECISION", "CASE_QUESTION"}
        source_revision = snapshot.source_snapshot.case_analysis_revision if source_kind in case_kinds else snapshot.source_snapshot.inspection_session_revision
        evidence = EvidenceItem(evidence_id, proposition, assessment_id)
        link = EvidenceSourceLink(link_id, evidence_id, source_kind, source_id, source_revision, "Proposta vinculada à autoridade upstream atual.")
        assessment = EvidenceAssessment(assessment_id, evidence_id, why_relevant, proposition, (), (), (link_id,), EvidenceReviewState.PENDING, None, None, None, None)
        coverage = replace(snapshot.coverage, evidence_items=len(snapshot.evidence_items) + 1)
        amended = replace(snapshot, evidence_items=(*snapshot.evidence_items, evidence), source_links=(*snapshot.source_links, link), evidence_assessments=(*snapshot.evidence_assessments, assessment), coverage=coverage)
        return self.save_snapshot.execute(workspace_id, amended, expected_revision, mutation_authority="PROPOSAL"), amended


@dataclass(frozen=True, slots=True)
class ReviewTechnicalEvidence:
    get_snapshot: object
    save_snapshot: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, evidence_id: str, action: str, professional_id: str, reason: str, expected_revision: int):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.upstream_stale or action not in {"APPROVE", "REJECT"}:
            raise RepositoryConflict("Technical evidence review authority is stale or invalid")
        evidence = next((item for item in snapshot.evidence_items if item.evidence_id == evidence_id), None)
        if evidence is None:
            raise ValueError("Technical evidence review target is invalid")
        current = next(item for item in snapshot.evidence_assessments if item.assessment_id == evidence.assessment_id)
        if current.review_state is not EvidenceReviewState.PENDING or not professional_id.strip() or not reason.strip():
            raise ValueError("Technical evidence already reviewed or professional input is invalid")
        now = self.clock.now()
        reviewed = replace(current, review_state=EvidenceReviewState.APPROVED if action == "APPROVE" else EvidenceReviewState.REJECTED, review_id=f"EVIDENCE-REVIEW-{self.ids.new_uuid().hex.upper()}", reviewer=professional_id.strip(), review_reason=reason.strip(), reviewed_at=now.isoformat())
        assessments = tuple(reviewed if item.assessment_id == reviewed.assessment_id else item for item in snapshot.evidence_assessments)
        approved = sum(item.review_state is EvidenceReviewState.APPROVED for item in assessments)
        amended = replace(snapshot, evidence_assessments=assessments, coverage=replace(snapshot.coverage, approved_evidence=approved))
        return self.save_snapshot.execute(workspace_id, amended, expected_revision, mutation_authority="PROFESSIONAL"), amended


@dataclass(frozen=True, slots=True)
class SelectTechnicalMethod:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, evidence_id: str, method_identity: str, procedure: str, output: str, professional_id: str, expected_revision: int):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        assessment = next((item for item in snapshot.evidence_assessments if item.evidence_id == evidence_id), None)
        if record.revision != expected_revision or snapshot.upstream_stale or assessment is None or assessment.review_state is not EvidenceReviewState.APPROVED:
            raise RepositoryConflict("approved current evidence is required for method selection")
        if any(not isinstance(value, str) or not value.strip() for value in (method_identity, procedure, output, professional_id)):
            raise ValueError("method selection input is invalid")
        token = self.ids.new_uuid().hex.upper(); method_id = f"METHOD-{token}"; input_id = f"METHOD-INPUT-{token}"; output_id = f"METHOD-OUTPUT-{token}"
        method_input = MethodInput(input_id, method_id, evidence_id, "PRIMARY_INPUT")
        method_output = MethodOutput(output_id, method_id, output.strip(), "Saída rastreável do método selecionado.")
        method = MethodApplication(method_id, method_identity.strip(), f"PROFESSIONAL:{professional_id.strip()}", procedure.strip(), (), (input_id,), (output_id,), (), (), expected_revision + 1)
        amended = replace(snapshot, method_applications=(*snapshot.method_applications, method), method_inputs=(*snapshot.method_inputs, method_input), method_outputs=(*snapshot.method_outputs, method_output), coverage=replace(snapshot.coverage, method_applications=len(snapshot.method_applications) + 1))
        return self.save_snapshot.execute(workspace_id, amended, expected_revision, mutation_authority="PROFESSIONAL"), amended


@dataclass(frozen=True, slots=True)
class ProposeTechnicalFinding:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, method_application_id: str, technical_proposition: str, scope: str, limitation: str, uncertainty: str, uncertainty_impact: str, origin: str, contrary_evidence_ids: tuple[str, ...], expected_revision: int):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        method = next((item for item in snapshot.method_applications if item.method_application_id == method_application_id), None)
        if record.revision != expected_revision or snapshot.upstream_stale or method is None:
            raise RepositoryConflict("current selected method is required for finding proposal")
        try: proposal_origin = ProposalOrigin(origin)
        except ValueError as exc: raise ValueError("finding proposal origin is invalid") from exc
        token = self.ids.new_uuid().hex.upper(); proposal_id = f"PROPOSAL-{token}"; limitation_id = f"LIMITATION-{token}"; uncertainty_id = f"UNCERTAINTY-{token}"
        supporting = tuple(item.evidence_id for item in snapshot.method_inputs if item.method_application_id == method_application_id and item.evidence_id not in contrary_evidence_ids)
        proposal = TechnicalFindingProposal(proposal_id, technical_proposition, proposal_origin, (method_application_id,), supporting, contrary_evidence_ids, (limitation_id,), (uncertainty_id,), scope)
        limit = FindingLimitation(limitation_id, "PROPOSAL", proposal_id, "SCOPE_LIMITATION", limitation)
        uncertain = FindingUncertainty(uncertainty_id, proposal_id, "EXPLICIT_UNCERTAINTY", uncertainty, uncertainty_impact)
        conflicts = snapshot.conflicts
        if contrary_evidence_ids:
            conflicts = (*conflicts, FindingConflict(f"CONFLICT-{token}", proposal_id, contrary_evidence_ids, ConflictStatus.UNRESOLVED, None, None))
        amended = replace(
            snapshot, finding_proposals=(*snapshot.finding_proposals, proposal),
            limitations=(*snapshot.limitations, limit), uncertainties=(*snapshot.uncertainties, uncertain), conflicts=conflicts,
            coverage=replace(
                snapshot.coverage, finding_proposals=len(snapshot.finding_proposals) + 1,
                unresolved_conflicts=sum(item.status is ConflictStatus.UNRESOLVED for item in conflicts),
                complete=False, reasons=("A cadeia técnica requer revisão profissional explícita.",),
            ),
        )
        return self.save_snapshot.execute(workspace_id, amended, expected_revision, mutation_authority="PROPOSAL"), amended


@dataclass(frozen=True, slots=True)
class ReviewTechnicalFinding:
    get_snapshot: object
    save_snapshot: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, proposal_id: str, action: str, professional_id: str, reason: str, modified_proposition: str | None, resolve_conflicts: bool, expected_revision: int):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        proposal = next((item for item in snapshot.finding_proposals if item.proposal_id == proposal_id), None)
        if record.revision != expected_revision or snapshot.upstream_stale or proposal is None:
            raise RepositoryConflict("current finding proposal is required for professional review")
        try: decision_action = DecisionAction(action)
        except ValueError as exc: raise ValueError("technical decision action is invalid") from exc
        if not professional_id.strip() or not reason.strip() or (decision_action is DecisionAction.MODIFY) != bool(modified_proposition and modified_proposition.strip()):
            raise ValueError("technical professional review input is invalid")
        history = [item for item in snapshot.decisions if item.proposal_id == proposal_id]
        token = self.ids.new_uuid().hex.upper(); decision_id = f"DECISION-{token}"
        decision = ProfessionalDecision(decision_id, proposal_id, decision_action, professional_id.strip(), reason.strip(), modified_proposition.strip() if modified_proposition else None, self.clock.now().isoformat(), history[-1].decision_id if history else None)
        findings = snapshot.findings
        question_links = tuple(item for item in snapshot.question_links if not any(old.finding_id == item.finding_id for old in snapshot.findings if old.proposal_id == proposal_id))
        if decision_action is not DecisionAction.REJECT:
            findings = (*findings, TechnicalFinding(f"FINDING-{token}", proposal_id, decision_id, modified_proposition.strip() if modified_proposition else proposal.technical_proposition, proposal.scope))
        conflicts = tuple(
            replace(item, status=ConflictStatus.RESOLVED, resolution_reasoning=reason.strip(), decision_id=decision_id)
            if resolve_conflicts and item.proposal_id == proposal_id else item for item in snapshot.conflicts
        )
        decisions = (*snapshot.decisions, decision)
        effective = sum(
            bool(history) and history[-1].action is not DecisionAction.REJECT
            for proposal_item in snapshot.finding_proposals
            for history in [[item for item in decisions if item.proposal_id == proposal_item.proposal_id]]
        )
        complete = bool(snapshot.finding_proposals) and effective == len(snapshot.finding_proposals)
        amended = replace(
            snapshot, decisions=decisions, findings=findings, conflicts=conflicts, question_links=question_links,
            coverage=replace(
                snapshot.coverage, effective_findings=effective,
                unresolved_conflicts=sum(item.status is ConflictStatus.UNRESOLVED for item in conflicts),
                complete=complete,
                reasons=() if complete else ("A cadeia técnica requer revisão profissional explícita.",),
            ),
        )
        return self.save_snapshot.execute(workspace_id, amended, expected_revision, mutation_authority="PROFESSIONAL"), amended
