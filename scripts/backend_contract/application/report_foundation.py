"""Application authority for upstream-bound canonical report revisions."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..case_analysis import CaseAnalysisSnapshot, case_analysis_to_mapping
from ..construction_defect_analysis import (
    ConstructionDefectAnalysisSnapshot,
    construction_defect_analysis_to_mapping,
)
from ..report_foundation import (
    ContextCompletenessItem,
    ContextStatus,
    EditorialProfile,
    ExpertMasterProfile,
    EXPERT_PROFILE_ARTIFACT_ID,
    EXPERT_PROFILE_ARTIFACT_KIND,
    REPORT_SNAPSHOT_ARTIFACT_ID,
    REPORT_SNAPSHOT_ARTIFACT_KIND,
    ReportCoverage,
    ReportAnswer,
    ReportFindingRow,
    ReportProvenance,
    ReportReference,
    ReportReviewDecision,
    ReportSection,
    ReportSnapshot,
    ReportSourceSnapshot,
    ReportState,
    ReviewAction,
    report_snapshot_from_mapping,
    report_snapshot_to_mapping,
    expert_profile_from_mapping,
    expert_profile_to_mapping,
    report_claim_for_source,
    editorial_profile_from_mapping,
)
from ..technical_findings import TechnicalSnapshot, technical_snapshot_to_mapping
from ..vistoria import InspectionSession, inspection_session_to_mapping
from .models import thaw_payload
from .ports import ArtifactRevisionNotFound, RepositoryConflict, RepositoryIntegrityError


SERVER_EXPERT_PROFILE_ID = "EXPERT-PROFILE-001"


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "report-snapshot-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker())

_SECTIONS = (
    ("IDENTIFICATION", "Identificação", True), ("PROCEDURAL_CONTEXT", "Contexto Processual", True),
    ("PURPOSE_OBJECT", "Objeto da Perícia", True), ("SCOPE", "Escopo", False),
    ("DOCUMENTS_EVIDENCE", "Documentos e Evidências Examinados", True), ("METHODOLOGY", "Metodologia", False),
    ("INSPECTION", "Vistoria", True), ("TECHNICAL_ANALYSIS", "Análise Técnica", True),
    ("TECHNICAL_FINDINGS", "Achados Técnicos", True), ("ANSWERS_TO_QUESTIONS", "Respostas aos Quesitos", True),
    ("CONCLUSIONS", "Conclusões", False), ("LIMITATIONS_RESERVATIONS", "Limitações e Ressalvas", False),
    ("REFERENCES", "Referências", False), ("ATTACHMENTS", "Anexos", False),
)
_CONTEXT_FIELDS = ("PROCESS_NUMBER", "COURT", "PARTIES", "ADDRESSES", "CLAIM_AND_GROUNDS", "REQUESTS")


def report_upstream_digest(value: object) -> str:
    if type(value) is CaseAnalysisSnapshot:
        mapping = case_analysis_to_mapping(value)
    elif type(value) is InspectionSession:
        mapping = inspection_session_to_mapping(value)
    elif type(value) is TechnicalSnapshot:
        mapping = technical_snapshot_to_mapping(value)
    elif type(value) is ConstructionDefectAnalysisSnapshot:
        mapping = construction_defect_analysis_to_mapping(value)
    elif type(value) is ExpertMasterProfile:
        mapping = asdict(value)
    else:
        raise TypeError("unsupported Report Snapshot upstream authority")
    encoded = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validated_report_snapshot_from_mapping(value: object) -> ReportSnapshot:
    try:
        _VALIDATOR.validate(value)
        return report_snapshot_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Report Snapshot payload") from exc


def report_snapshot_to_validated_mapping(snapshot: ReportSnapshot) -> dict:
    mapping = report_snapshot_to_mapping(snapshot)
    _VALIDATOR.validate(mapping)
    return mapping


def validated_expert_profile_from_mapping(value: object) -> ExpertMasterProfile:
    return expert_profile_from_mapping(value)


def expert_profile_to_validated_mapping(profile: ExpertMasterProfile) -> dict:
    return expert_profile_to_mapping(profile)


def _binding(
    *,
    workspace_id,
    case_record,
    case,
    inspection_record,
    inspection,
    technical_record,
    technical,
    profile_record,
    profile,
    pathology_record=None,
    pathology=None,
) -> ReportSourceSnapshot:
    if any((type(case) is not CaseAnalysisSnapshot, type(inspection) is not InspectionSession, type(technical) is not TechnicalSnapshot, type(profile) is not ExpertMasterProfile)):
        raise ValueError("Report Snapshot upstream authority type mismatch")
    if case.workspace_id != str(workspace_id) or inspection.workspace_id != str(workspace_id) or technical.workspace_id != str(workspace_id):
        raise ValueError("Report Snapshot upstream workspace mismatch")
    if (pathology_record is None) != (pathology is None):
        raise ValueError("Report Snapshot pathology authority is incomplete")
    if pathology is not None and (
        type(pathology) is not ConstructionDefectAnalysisSnapshot
        or pathology.workspace_id != str(workspace_id)
    ):
        raise ValueError("Report Snapshot pathology authority mismatch")
    effective_pathology = (
        pathology
        if pathology is not None
        and not pathology.upstream_stale
        and bool(pathology.effective_pat_ids)
        else None
    )
    return ReportSourceSnapshot(
        workspace_id=str(workspace_id), case_analysis_snapshot_id=case.snapshot_id, case_analysis_revision=case_record.revision,
        case_analysis_digest=report_upstream_digest(case), inspection_session_id=inspection.session_id,
        inspection_session_revision=inspection_record.revision, inspection_session_digest=report_upstream_digest(inspection),
        technical_snapshot_id=technical.snapshot_id, technical_snapshot_revision=technical_record.revision,
        technical_snapshot_digest=report_upstream_digest(technical),
        construction_defect_analysis_snapshot_id=(
            effective_pathology.snapshot_id if effective_pathology is not None else None
        ),
        construction_defect_analysis_revision=(
            pathology_record.revision if effective_pathology is not None else None
        ),
        construction_defect_analysis_digest=(
            report_upstream_digest(effective_pathology)
            if effective_pathology is not None
            else None
        ),
        expert_profile_id=profile.profile_id,
        expert_profile_revision=profile_record.revision, expert_profile_digest=report_upstream_digest(profile),
    )


def _reconcile(snapshot: ReportSnapshot, current: ReportSourceSnapshot) -> ReportSnapshot:
    reasons = []
    for name, reason in (
        ("case_analysis_snapshot_id", "case analysis identity changed"), ("case_analysis_revision", "case analysis revision changed"),
        ("case_analysis_digest", "case analysis content changed"), ("inspection_session_id", "inspection identity changed"),
        ("inspection_session_revision", "inspection revision changed"), ("inspection_session_digest", "inspection content changed"),
        ("technical_snapshot_id", "technical snapshot identity changed"), ("technical_snapshot_revision", "technical snapshot revision changed"),
        ("technical_snapshot_digest", "technical snapshot content changed"),
        ("construction_defect_analysis_snapshot_id", "pathology snapshot identity changed"),
        ("construction_defect_analysis_revision", "pathology snapshot revision changed"),
        ("construction_defect_analysis_digest", "pathology snapshot content changed"),
        ("expert_profile_id", "expert profile identity changed"),
        ("expert_profile_revision", "expert profile revision changed"), ("expert_profile_digest", "expert profile content changed"),
    ):
        if getattr(snapshot.source_snapshot, name) != getattr(current, name):
            reasons.append(reason)
    if not reasons:
        return snapshot
    return replace(
        snapshot, state=ReportState.DRAFT, review_decisions=(),
        coverage=replace(snapshot.coverage, complete=False), upstream_stale=True, upstream_stale_reasons=tuple(reasons),
    )


def _validate_answer_chains(snapshot: ReportSnapshot, technical: TechnicalSnapshot) -> None:
    findings = {item.finding_id: item for item in technical.findings}
    proposals = {item.proposal_id: item for item in technical.finding_proposals}
    decisions = {item.decision_id: item for item in technical.decisions}
    question_pairs = {(item.question_id, item.finding_id) for item in technical.question_links}
    for answer in snapshot.answers:
        finding = findings.get(answer.finding_id)
        if finding is None or (answer.question_id, answer.finding_id) not in question_pairs or finding.decision_id != answer.decision_id:
            raise ValueError("Report Snapshot answer traceability is invalid")
        proposal = proposals.get(finding.proposal_id)
        decision = decisions.get(answer.decision_id)
        if proposal is None or decision is None or set(answer.method_ids) != set(proposal.method_application_ids):
            raise ValueError("Report Snapshot answer traceability is invalid")
        classified = set(proposal.supporting_evidence_ids) | set(proposal.contrary_evidence_ids)
        if set(answer.evidence_ids) != classified:
            raise ValueError("Report Snapshot answer traceability is invalid")
        expected_claims = {
            claim.claim_id
            for claim in snapshot.claims
            if any(
                (item.source_kind == "TECHNICAL_FINDING" and item.source_id == answer.finding_id)
                or (item.source_kind == "PROFESSIONAL_DECISION" and item.source_id == answer.decision_id)
                for item in claim.provenance
            )
        }
        if not expected_claims or set(answer.claim_ids) != expected_claims:
            raise ValueError("Report Snapshot answer claim traceability is invalid")


def _validate_claim_provenance(
    snapshot: ReportSnapshot,
    case: CaseAnalysisSnapshot,
    inspection: InspectionSession,
    technical: TechnicalSnapshot,
    pathology: ConstructionDefectAnalysisSnapshot | None,
) -> None:
    pathology_ids = set(pathology.effective_pat_ids) if pathology is not None else set()
    sources = {
        "ALLEGATION": ({item.item_id for item in case.claims}, snapshot.source_snapshot.case_analysis_revision),
        "COURT_DECISION": ({item.item_id for item in case.decisions}, snapshot.source_snapshot.case_analysis_revision),
        "CASE_DOCUMENT": ({item.document_id for item in case.documents}, snapshot.source_snapshot.case_analysis_revision),
        "FIELD_OBSERVATION": ({item.observation_id for item in inspection.observations}, snapshot.source_snapshot.inspection_session_revision),
        "MEASUREMENT": ({item.measurement_id for item in inspection.measurements}, snapshot.source_snapshot.inspection_session_revision),
        "PATHOLOGY": (
            pathology_ids,
            snapshot.source_snapshot.construction_defect_analysis_revision,
        ),
        "TECHNICAL_FINDING": ({item.finding_id for item in technical.findings}, snapshot.source_snapshot.technical_snapshot_revision),
        "PROFESSIONAL_DECISION": ({item.decision_id for item in technical.decisions}, snapshot.source_snapshot.technical_snapshot_revision),
    }
    bound = [provenance for claim in snapshot.claims for provenance in claim.provenance]
    bound.extend(row.provenance for row in snapshot.findings_table or ())
    for provenance in bound:
        identities, revision = sources[provenance.source_kind]
        if provenance.source_id not in identities or provenance.source_revision != revision:
            raise ValueError("Report Snapshot claim provenance is not present in bound upstream authority")
    documents = {item.document_id for item in case.documents}
    claims = {item.item_id for item in case.claims}
    decisions = {item.item_id for item in case.decisions}
    participants = {item.participant_id for item in case.judicial_context.participants}
    questions = {item.item_id for item in case.questions} | {item.question_id for item in technical.question_links}
    context_sources = {
        "PROCESS_NUMBER": documents | decisions,
        "COURT": documents | decisions,
        "PARTIES": participants | documents,
        "ADDRESSES": documents,
        "CLAIM_AND_GROUNDS": claims | documents,
        "REQUESTS": questions | decisions | documents,
    }
    for item in snapshot.context_matrix:
        if item.status is ContextStatus.PRESENT and item.source_id not in context_sources[item.field]:
            raise ValueError("Report Snapshot context provenance is not present in bound upstream authority")
    if snapshot.state is ReportState.APPROVED and {item.question_id for item in snapshot.answers} != {item.question_id for item in technical.question_links}:
        raise ValueError("approved Report Snapshot must answer every bound technical question")


def _optional_pathology(workspace_id, service):
    if service is None:
        return None, None
    try:
        return service.execute(workspace_id)
    except ArtifactRevisionNotFound:
        return None, None


def _current(workspace_id, services, get_construction_defect_analysis=None):
    case_record, case = services[0].execute(workspace_id)
    inspection_record, inspection = services[1].execute(workspace_id)
    technical_record, technical = services[2].execute(workspace_id)
    profile_record, profile = services[3].execute(workspace_id)
    pathology_record, pathology = _optional_pathology(
        workspace_id, get_construction_defect_analysis
    )
    binding = _binding(
        workspace_id=workspace_id, case_record=case_record, case=case, inspection_record=inspection_record,
        inspection=inspection, technical_record=technical_record, technical=technical,
        profile_record=profile_record, profile=profile,
        pathology_record=pathology_record, pathology=pathology,
    )
    return (
        case_record,
        case,
        inspection_record,
        inspection,
        technical_record,
        technical,
        profile_record,
        profile,
        pathology_record,
        pathology,
        binding,
    )


def _draft_coverage(snapshot: ReportSnapshot, *, claims=None, answers=None, context=None) -> ReportCoverage:
    claims = snapshot.claims if claims is None else claims
    answers = snapshot.answers if answers is None else answers
    context = snapshot.context_matrix if context is None else context
    required = sum(item.required_by_cpc473 for item in snapshot.sections)
    present = sum(item.required_by_cpc473 and any(claim.section_id == item.section_id for claim in claims) for item in snapshot.sections)
    context_required = sum(item.required for item in context)
    context_present = sum(item.required and item.status is ContextStatus.PRESENT for item in context)
    return ReportCoverage(len(snapshot.sections), len(claims), len(claims), len(answers), len(answers), required, present, context_required, context_present, False, ("Report draft requires complete CPC 319, CPC 473 and professional approval.",))


@dataclass(frozen=True, slots=True)
class SaveReportSnapshot:
    revisions: object
    get_case_analysis: object
    get_inspection_session: object
    get_technical_snapshot: object
    get_expert_profile: object
    get_latest_revision: object
    authority_guard: object
    clock: object
    ids: object
    get_construction_defect_analysis: object | None = None

    def execute(self, workspace_id, snapshot: ReportSnapshot, expected_revision: int | None, *, allow_review_transition: bool = False, allow_initial_create: bool = False):
        if type(snapshot) is not ReportSnapshot or snapshot.workspace_id != str(workspace_id) or snapshot.upstream_stale:
            raise ValueError("Report Snapshot workspace or stale state is invalid")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("Report Snapshot expected revision is invalid")
        if expected_revision is None and (not allow_initial_create or snapshot.state is not ReportState.DRAFT or snapshot.review_decisions):
            raise ValueError("initial Report Snapshot requires the canonical start command")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Report Snapshot authority guard is unavailable")
        with self.authority_guard():
            current = _current(
                workspace_id,
                (
                    self.get_case_analysis,
                    self.get_inspection_session,
                    self.get_technical_snapshot,
                    self.get_expert_profile,
                ),
                self.get_construction_defect_analysis,
            )
            if _reconcile(snapshot, current[-1]).upstream_stale:
                raise ValueError("Report Snapshot upstream authority is stale")
            _validate_answer_chains(snapshot, current[5])
            _validate_claim_provenance(
                snapshot, current[1], current[3], current[5], current[9]
            )
            if expected_revision is not None:
                predecessor_record = self.get_latest_revision.execute(workspace_id, REPORT_SNAPSHOT_ARTIFACT_KIND, REPORT_SNAPSHOT_ARTIFACT_ID)
                predecessor = validated_report_snapshot_from_mapping(thaw_payload(predecessor_record.payload))
                if not allow_review_transition and snapshot.review_decisions != predecessor.review_decisions:
                    raise ValueError("Report Snapshot review decisions require the professional review command")
                material_fields = ("source_snapshot", "expert_profile", "editorial_profile", "context_matrix", "sections", "claims", "answers", "references", "findings_table")
                if predecessor.review_decisions and any(getattr(predecessor, name) != getattr(snapshot, name) for name in material_fields):
                    raise ValueError("Report Snapshot material change requires a new draft before professional review")
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Report Snapshot clock requires timezone")
            records = [current[0], current[2], current[4], current[6]]
            if (
                current[-1].construction_defect_analysis_snapshot_id is not None
                and current[8] is not None
            ):
                records.append(current[8])
            dependencies = tuple({"artifact_kind": item.artifact_kind, "artifact_id": item.artifact_id, "revision": item.revision, "checksum_sha256": item.checksum_sha256} for item in records)
            return self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=REPORT_SNAPSHOT_ARTIFACT_KIND, artifact_id=REPORT_SNAPSHOT_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()), created_at=created_at.isoformat(), payload=report_snapshot_to_mapping(snapshot),
                expected_revision=expected_revision, expected_dependencies=dependencies,
            )


@dataclass(frozen=True, slots=True)
class GetReportSnapshot:
    get_latest_revision: object
    get_case_analysis: object
    get_inspection_session: object
    get_technical_snapshot: object
    get_expert_profile: object
    get_construction_defect_analysis: object | None = None

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, REPORT_SNAPSHOT_ARTIFACT_KIND, REPORT_SNAPSHOT_ARTIFACT_ID)
        snapshot = validated_report_snapshot_from_mapping(thaw_payload(record.payload))
        current = _current(
            workspace_id,
            (
                self.get_case_analysis,
                self.get_inspection_session,
                self.get_technical_snapshot,
                self.get_expert_profile,
            ),
            self.get_construction_defect_analysis,
        )
        return record, _reconcile(snapshot, current[-1])


@dataclass(frozen=True, slots=True)
class ReviewReportSnapshot:
    get_snapshot: object
    save_snapshot: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, action: str, professional_id: str, reason: str, expected_revision: int):
        try:
            review_action = ReviewAction(action)
        except ValueError as exc:
            raise ValueError("Report review action is invalid") from exc
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.upstream_stale or professional_id != snapshot.expert_profile.profile_id:
            raise ValueError("Report review authority or revision is invalid")
        allowed = {ReportState.DRAFT: {ReviewAction.MARK_REVIEWED}, ReportState.REVIEWED: {ReviewAction.APPROVE, ReviewAction.SUPERSEDE}, ReportState.APPROVED: {ReviewAction.SUPERSEDE}, ReportState.SUPERSEDED: set()}
        if review_action not in allowed[snapshot.state]:
            raise ValueError("Report review transition is invalid")
        timestamp = self.clock.now()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None or type(reason) is not str or not reason.strip():
            raise ValueError("Report review decision is invalid")
        previous = snapshot.review_decisions[-1].review_id if snapshot.review_decisions else None
        decision = ReportReviewDecision(str(self.ids.new_uuid()), review_action, professional_id, reason.strip(), timestamp.isoformat(), previous)
        state = {ReviewAction.MARK_REVIEWED: ReportState.REVIEWED, ReviewAction.APPROVE: ReportState.APPROVED, ReviewAction.SUPERSEDE: ReportState.SUPERSEDED}[review_action]
        required = snapshot.coverage.cpc473_required_sections
        present = snapshot.coverage.cpc473_present_sections
        context_required = snapshot.coverage.context_required_fields
        context_present = snapshot.coverage.context_present_fields
        complete = bool(snapshot.claims) and present == required and context_present == context_required and review_action is ReviewAction.APPROVE
        reviewed = replace(snapshot, review_decisions=(*snapshot.review_decisions, decision), state=state, coverage=replace(snapshot.coverage, complete=complete, reasons=() if complete else snapshot.coverage.reasons))
        saved = self.save_snapshot.execute(workspace_id, reviewed, expected_revision, allow_review_transition=True)
        return saved, reviewed


@dataclass(frozen=True, slots=True)
class AmendReportDraft:
    get_snapshot: object
    save_snapshot: object
    ids: object
    # Upstream readers let the answer command derive its chain from the bound
    # authorities instead of asking the expert for internal identities.
    get_case_analysis: object | None = None
    get_technical_snapshot: object | None = None
    get_construction_defect_analysis: object | None = None

    def execute(self, workspace_id, *, expected_revision: int, action: str, values: dict):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.state is not ReportState.DRAFT or snapshot.review_decisions or snapshot.upstream_stale or type(values) is not dict:
            raise ValueError("Report draft amendment is invalid")
        if action == "ANSWER_QUESTION":
            if set(values) != {"question_id", "finding_id", "text"} or any(type(values[name]) is not str or not values[name].strip() for name in values):
                raise ValueError("Report answer amendment is invalid")
            if self.get_case_analysis is None or self.get_technical_snapshot is None:
                raise ValueError("Report answer derivation is unavailable")
            case_record, case = self.get_case_analysis.execute(workspace_id)
            technical_record, technical = self.get_technical_snapshot.execute(workspace_id)
            bound = snapshot.source_snapshot
            if (
                case_record.revision != bound.case_analysis_revision
                or report_upstream_digest(case) != bound.case_analysis_digest
                or technical_record.revision != bound.technical_snapshot_revision
                or report_upstream_digest(technical) != bound.technical_snapshot_digest
            ):
                raise ValueError("Report answer upstream authority is stale")
            if any(item.question_id == values["question_id"] for item in snapshot.answers):
                raise ValueError("Report question is already answered")
            answer = _answer_for_question(
                snapshot, case, technical, answer_id=f"ANSWER-{str(self.ids.new_uuid()).upper()}",
                question_id=values["question_id"], finding_id=values["finding_id"], text=values["text"].strip(),
            )
            answers = (*snapshot.answers, answer)
            amended = replace(snapshot, answers=answers, coverage=_draft_coverage(snapshot, answers=answers))
        elif action == "ADD_REFERENCE":
            if set(values) != {"kind", "author", "title", "year", "identifier", "details"}:
                raise ValueError("Report reference amendment is invalid")
            def optional_text(value):
                if value is None or (type(value) is str and not value.strip()):
                    return None
                if type(value) is not str:
                    raise ValueError("Report reference amendment is invalid")
                return value.strip()
            if any(type(values[name]) is not str for name in ("kind", "author", "title")) or (values["year"] is not None and type(values["year"]) is not int):
                raise ValueError("Report reference amendment is invalid")
            reference = ReportReference(
                f"REFERENCE-{str(self.ids.new_uuid()).upper()}", values["kind"], values["author"].strip(), values["title"].strip(),
                values["year"], optional_text(values["identifier"]), optional_text(values["details"]),
            )
            amended = replace(snapshot, references=(*(snapshot.references or ()), reference))
        elif action == "REMOVE_REFERENCE":
            if set(values) != {"reference_id"} or not any(item.reference_id == values["reference_id"] for item in snapshot.references or ()):
                raise ValueError("Report reference amendment is invalid")
            remaining = tuple(item for item in snapshot.references if item.reference_id != values["reference_id"])
            amended = replace(snapshot, references=remaining or None)
        elif action == "SET_FINDINGS_TABLE":
            if values != {}:
                raise ValueError("Report findings table amendment is invalid")
            amended = replace(snapshot, findings_table=self._findings_rows(workspace_id, snapshot))
        elif action == "REMOVE_FINDINGS_TABLE":
            if values != {} or snapshot.findings_table is None:
                raise ValueError("Report findings table amendment is invalid")
            amended = replace(snapshot, findings_table=None)
        elif action == "SET_EDITORIAL_PROFILE":
            if set(values) != {"editorial_profile"}:
                raise ValueError("Report editorial amendment is invalid")
            profile = editorial_profile_from_mapping(values["editorial_profile"])
            amended = replace(snapshot, editorial_profile=profile)
        elif action == "UPDATE_ANSWER_TEXT":
            if set(values) != {"answer_id", "text"} or type(values["text"]) is not str or not values["text"].strip():
                raise ValueError("Report answer amendment is invalid")
            if not any(item.answer_id == values["answer_id"] for item in snapshot.answers):
                raise ValueError("Report answer is unknown")
            answers = tuple(replace(item, text=values["text"].strip()) if item.answer_id == values["answer_id"] else item for item in snapshot.answers)
            amended = replace(snapshot, answers=answers)
        elif action == "REMOVE_ANSWER":
            if set(values) != {"answer_id"} or not any(item.answer_id == values["answer_id"] for item in snapshot.answers):
                raise ValueError("Report answer amendment is invalid")
            answers = tuple(item for item in snapshot.answers if item.answer_id != values["answer_id"])
            amended = replace(snapshot, answers=answers, coverage=_draft_coverage(snapshot, answers=answers))
        elif action == "UPDATE_CLAIM_TEXT":
            if set(values) != {"claim_id", "text"} or type(values["text"]) is not str or not values["text"].strip():
                raise ValueError("Report claim amendment is invalid")
            if not any(item.claim_id == values["claim_id"] for item in snapshot.claims):
                raise ValueError("Report claim is unknown")
            # Only the presentation text changes; authority and provenance stay.
            claims = tuple(replace(item, text=values["text"].strip()) if item.claim_id == values["claim_id"] else item for item in snapshot.claims)
            amended = replace(snapshot, claims=claims)
        elif action == "REMOVE_CLAIM":
            if set(values) != {"claim_id"} or not any(item.claim_id == values["claim_id"] for item in snapshot.claims):
                raise ValueError("Report claim amendment is invalid")
            if any(values["claim_id"] in item.claim_ids for item in snapshot.answers):
                raise ValueError("Report claim supports an answer to a question")
            claims = tuple(item for item in snapshot.claims if item.claim_id != values["claim_id"])
            amended = replace(snapshot, claims=claims, coverage=_draft_coverage(snapshot, claims=claims))
        elif action == "ADD_CLAIM":
            if set(values) != {"section_id", "text", "source_kind", "source_id"}:
                raise ValueError("Report claim amendment is invalid")
            source_kind = values["source_kind"]
            if source_kind == "PATHOLOGY":
                revision = snapshot.source_snapshot.construction_defect_analysis_revision
                if revision is None:
                    raise ValueError("Report claim has no bound pathology authority")
            else:
                revision = snapshot.source_snapshot.technical_snapshot_revision if source_kind in {"TECHNICAL_FINDING", "PROFESSIONAL_DECISION"} else (snapshot.source_snapshot.inspection_session_revision if source_kind in {"FIELD_OBSERVATION", "MEASUREMENT"} else snapshot.source_snapshot.case_analysis_revision)
            token = str(self.ids.new_uuid()).upper()
            claim = report_claim_for_source(claim_id=f"CLAIM-{token}", provenance_id=f"PROVENANCE-{token}", section_id=values["section_id"], text=values["text"], source_kind=source_kind, source_id=values["source_id"], source_revision=revision)
            claims = (*snapshot.claims, claim)
            amended = replace(snapshot, claims=claims, coverage=_draft_coverage(snapshot, claims=claims))
        elif action == "UPDATE_CONTEXT":
            if set(values) != {"field", "status", "source_id", "note"}:
                raise ValueError("Report context amendment is invalid")
            try:
                status = ContextStatus(values["status"])
            except ValueError as exc:
                raise ValueError("Report context status is invalid") from exc
            context = tuple(replace(item, status=status, source_id=values["source_id"], note=values["note"]) if item.field == values["field"] else item for item in snapshot.context_matrix)
            if context == snapshot.context_matrix:
                raise ValueError("Report context field is invalid")
            amended = replace(snapshot, context_matrix=context, coverage=_draft_coverage(snapshot, context=context))
        elif action == "ADD_ANSWER":
            required = {"section_id", "question_id", "text", "finding_id", "evidence_ids", "method_ids", "decision_id", "claim_ids"}
            if set(values) != required or any(type(values[name]) is not list for name in ("evidence_ids", "method_ids", "claim_ids")):
                raise ValueError("Report answer amendment is invalid")
            answer = ReportAnswer(f"ANSWER-{str(self.ids.new_uuid()).upper()}", values["section_id"], values["question_id"], values["text"], values["finding_id"], tuple(values["evidence_ids"]), tuple(values["method_ids"]), values["decision_id"], tuple(values["claim_ids"]))
            answers = (*snapshot.answers, answer)
            amended = replace(snapshot, answers=answers, coverage=_draft_coverage(snapshot, answers=answers))
        else:
            raise ValueError("Report draft amendment action is invalid")
        saved = self.save_snapshot.execute(workspace_id, amended, expected_revision)
        return saved, amended

    def _findings_rows(self, workspace_id, snapshot: ReportSnapshot) -> tuple[ReportFindingRow, ...]:
        """One row per approved pathology, in the analysis order, as recorded.

        Nothing is inferred: a pathology without a described manifestation or
        an observed (or concluded) finding refuses the table instead of filling
        a cell the record does not support.  The save re-checks the bound
        revision, so a table captured from stale authority is refused there.
        """
        revision = snapshot.source_snapshot.construction_defect_analysis_revision
        if revision is None or self.get_construction_defect_analysis is None:
            raise ValueError("Report findings table has no bound pathology authority")
        _, pathology = _optional_pathology(workspace_id, self.get_construction_defect_analysis)
        effective = set(pathology.effective_pat_ids) if pathology is not None else set()
        rows = []
        for item in (pathology.analysis_final.get("patologias", ()) if pathology is not None else ()):
            if not isinstance(item, Mapping) or item.get("id") not in effective:
                continue
            observed = item.get("constatacao") if isinstance(item.get("constatacao"), Mapping) else {}
            finding = observed.get("descricao") or item.get("conclusao_tecnica")
            manifestation = item.get("manifestacao")
            if not isinstance(manifestation, str) or not manifestation.strip() or not isinstance(finding, str) or not finding.strip():
                raise ValueError("Report findings table requires described pathologies")
            environment = item.get("ambiente")
            situation = observed.get("situacao")
            rows.append(ReportFindingRow(
                manifestation.strip(), environment.strip() if isinstance(environment, str) and environment.strip() else None,
                finding.strip(), situation if isinstance(situation, str) else None,
                ReportProvenance(f"PROVENANCE-{str(self.ids.new_uuid()).upper()}", "PATHOLOGY", item["id"], revision),
            ))
        if not rows:
            raise ValueError("Report findings table requires approved pathologies")
        return tuple(rows)


def _answer_for_question(snapshot: ReportSnapshot, case: CaseAnalysisSnapshot, technical: TechnicalSnapshot, *, answer_id: str, question_id: str, finding_id: str, text: str) -> ReportAnswer:
    """The whole answer chain follows from the question and the effective finding.

    Evidence, methods and the decision are the ones the finding already carries;
    the cited claims are the report paragraphs that cite that finding or its
    decision.  Nothing here is inferred: a link that does not exist is refused.
    """
    if (question_id, finding_id) not in {(item.question_id, item.finding_id) for item in technical.question_links}:
        raise ValueError("Report answer requires an effective finding linked to the question")
    finding = next((item for item in technical.findings if item.finding_id == finding_id), None)
    proposal = next((item for item in technical.finding_proposals if finding is not None and item.proposal_id == finding.proposal_id), None)
    if finding is None or proposal is None:
        raise ValueError("Report answer requires an effective finding linked to the question")
    evidence_ids = tuple(dict.fromkeys((*proposal.supporting_evidence_ids, *proposal.contrary_evidence_ids)))
    claim_ids = tuple(
        claim.claim_id
        for claim in snapshot.claims
        if any(
            (item.source_kind == "TECHNICAL_FINDING" and item.source_id == finding_id)
            or (item.source_kind == "PROFESSIONAL_DECISION" and item.source_id == finding.decision_id)
            for item in claim.provenance
        )
    )
    if not claim_ids:
        raise ValueError("Report answer requires the finding to be cited in the report")
    section = next(item for item in snapshot.sections if item.kind == "ANSWERS_TO_QUESTIONS")
    question_text = next((item.text for item in case.questions if item.item_id == question_id), None)
    return ReportAnswer(
        answer_id, section.section_id, question_id, text, finding_id, evidence_ids,
        tuple(proposal.method_application_ids), finding.decision_id, claim_ids, question_text,
    )


def _pathology_labels(pathology: ConstructionDefectAnalysisSnapshot | None) -> list[dict]:
    if pathology is None:
        return []
    effective = set(pathology.effective_pat_ids)
    items = []
    for item in pathology.analysis_final.get("patologias", ()):
        if isinstance(item, Mapping) and item.get("id") in effective:
            items.append({"kind": "PATHOLOGY", "id": item["id"], "label": f"{item['id']} · {item.get('manifestacao') or 'manifestação sem descrição'}"})
    return items


@dataclass(frozen=True, slots=True)
class ListReportSources:
    """Everything the expert may cite, labelled by content, never by identity.

    The list is read from the same authorities the report binds, so a source
    offered here is one the save command will accept.
    """
    get_case_analysis: object
    get_inspection_session: object
    get_technical_snapshot: object
    get_construction_defect_analysis: object | None = None

    def execute(self, workspace_id) -> dict:
        _, case = self.get_case_analysis.execute(workspace_id)
        _, inspection = self.get_inspection_session.execute(workspace_id)
        _, technical = self.get_technical_snapshot.execute(workspace_id)
        _, pathology = _optional_pathology(workspace_id, self.get_construction_defect_analysis)
        documents = [
            {"kind": "CASE_DOCUMENT", "id": item.document_id, "label": f"{item.sequence:02d} · {item.raw_type} · páginas {item.page_count_or_span}"}
            for item in case.documents if item.content_available
        ]
        sources = [
            *({"kind": "ALLEGATION", "id": item.item_id, "label": item.text} for item in case.claims),
            *({"kind": "COURT_DECISION", "id": item.item_id, "label": item.text} for item in case.decisions),
            *documents,
            *({"kind": "FIELD_OBSERVATION", "id": item.observation_id, "label": item.raw_observation} for item in inspection.observations),
            *({"kind": "MEASUREMENT", "id": item.measurement_id, "label": f"{item.quantity}: {item.raw_value} {item.raw_unit}"} for item in inspection.measurements),
            *_pathology_labels(pathology),
            *({"kind": "TECHNICAL_FINDING", "id": item.finding_id, "label": item.technical_proposition} for item in technical.findings),
            *({"kind": "PROFESSIONAL_DECISION", "id": item.decision_id, "label": f"Decisão sobre: {next((finding.technical_proposition for finding in technical.findings if finding.decision_id == item.decision_id), item.reason)}"} for item in technical.decisions if any(finding.decision_id == item.decision_id for finding in technical.findings)),
        ]
        entities = {item.entity_id: item for item in case.judicial_context.entities}
        participants = [
            {"id": item.participant_id, "label": getattr(entities.get(item.entity_id), "raw_name", item.participant_id)}
            for item in case.judicial_context.participants
        ]
        document_options = [{"id": item["id"], "label": item["label"]} for item in documents]
        decisions = [{"id": item.item_id, "label": item.text} for item in case.decisions]
        claims = [{"id": item.item_id, "label": item.text} for item in case.claims]
        questions_text = {item.item_id: item.text for item in case.questions}
        question_ids = list(dict.fromkeys(item.question_id for item in technical.question_links))
        question_options = [{"id": question_id, "label": questions_text.get(question_id, question_id)} for question_id in question_ids]
        findings = {item.finding_id: item for item in technical.findings}
        questions = [
            {
                "question_id": question_id,
                "text": questions_text.get(question_id),
                "findings": [
                    {"finding_id": link.finding_id, "label": findings[link.finding_id].technical_proposition}
                    for link in technical.question_links
                    if link.question_id == question_id and link.finding_id in findings
                ],
            }
            for question_id in question_ids
        ]
        return {
            "sources": sources,
            "context_sources": {
                "PROCESS_NUMBER": document_options + decisions,
                "COURT": document_options + decisions,
                "PARTIES": participants + document_options,
                "ADDRESSES": document_options,
                "CLAIM_AND_GROUNDS": claims + document_options,
                "REQUESTS": question_options + decisions + document_options,
            },
            "questions": questions,
        }


@dataclass(frozen=True, slots=True)
class ExportReportAuditTrail:
    """The canonical audit trail of the current report, offered apart from the document."""
    get_snapshot: object

    def execute(self, workspace_id) -> dict:
        from ..delivery_renderer import canonical_report_audit_lines

        record, snapshot = self.get_snapshot.execute(workspace_id)
        return {"report_id": snapshot.report_id, "revision": record.revision, "lines": list(canonical_report_audit_lines(snapshot))}


@dataclass(frozen=True, slots=True)
class StartReportSnapshot:
    get_case_analysis: object
    get_inspection_session: object
    get_technical_snapshot: object
    get_expert_profile: object
    save_snapshot: object
    ids: object
    get_construction_defect_analysis: object | None = None

    def execute(self, workspace_id):
        current = _current(
            workspace_id,
            (
                self.get_case_analysis,
                self.get_inspection_session,
                self.get_technical_snapshot,
                self.get_expert_profile,
            ),
            self.get_construction_defect_analysis,
        )
        case, inspection, technical, profile = current[1], current[3], current[5], current[7]
        if case.source_inventory_stale or inspection.upstream_stale or technical.upstream_stale:
            raise ValueError("stale upstream cannot start a Report Snapshot")
        sections = tuple(ReportSection(f"SECTION-{index:03d}", kind, title, index, required) for index, (kind, title, required) in enumerate(_SECTIONS, 1))
        context = tuple(ContextCompletenessItem(f"CONTEXT-{index:03d}", field, True, ContextStatus.MISSING, None, f"[INFORMAÇÃO NECESSÁRIA: {field.lower()}]") for index, field in enumerate(_CONTEXT_FIELDS, 1))
        snapshot = ReportSnapshot(
            schema_version="1.0.0", report_id=f"REPORT-{str(self.ids.new_uuid()).upper()}", workspace_id=str(workspace_id),
            source_snapshot=current[-1], expert_profile=profile,
            editorial_profile=EditorialProfile("JUSTICA_PLURAL_CHAPTER_4", "Arial", 11, 10, 9, "JUSTIFIED", 1.15, 1.25, "A4", 2, 2, 3, 2, False, ()),
            context_matrix=context, sections=sections, claims=(), answers=(), review_decisions=(), state=ReportState.DRAFT,
            coverage=ReportCoverage(14, 0, 0, 0, 0, sum(item.required_by_cpc473 for item in sections), 0, 6, 0, False, ("Report draft has no material claims.",)),
            upstream_stale=False, upstream_stale_reasons=(),
        )
        record = self.save_snapshot.execute(workspace_id, snapshot, None, allow_initial_create=True)
        return record, snapshot


@dataclass(frozen=True, slots=True)
class SaveExpertProfile:
    revisions: object
    get_latest_revision: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, profile: ExpertMasterProfile, expected_revision: int | None):
        if type(profile) is not ExpertMasterProfile:
            raise ValueError("expert profile is invalid")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expert profile expected revision is invalid")
        if profile.profile_id != SERVER_EXPERT_PROFILE_ID:
            raise ValueError("expert profile identity is server-owned")
        if expected_revision is None:
            if profile.revision != 1:
                raise ValueError("initial expert profile revision is server-owned")
        else:
            record = self.get_latest_revision.execute(
                workspace_id, EXPERT_PROFILE_ARTIFACT_KIND, EXPERT_PROFILE_ARTIFACT_ID
            )
            predecessor = expert_profile_from_mapping(thaw_payload(record.payload))
            if record.revision != expected_revision or profile.revision != predecessor.revision + 1:
                raise RepositoryConflict("expected expert profile revision is not latest")
            immutable = ("profile_id", "full_name", "professional_title", "registration", "court_registration")
            if any(getattr(profile, name) != getattr(predecessor, name) for name in immutable):
                raise ValueError("expert professional identity cannot be rewritten")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("expert profile authority guard is unavailable")
        with self.authority_guard():
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("expert profile clock requires timezone")
            return self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=EXPERT_PROFILE_ARTIFACT_KIND, artifact_id=EXPERT_PROFILE_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()), created_at=created_at.isoformat(), payload=expert_profile_to_mapping(profile),
                expected_revision=expected_revision,
            )


@dataclass(frozen=True, slots=True)
class GetExpertProfile:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, EXPERT_PROFILE_ARTIFACT_KIND, EXPERT_PROFILE_ARTIFACT_ID)
        return record, expert_profile_from_mapping(thaw_payload(record.payload))
