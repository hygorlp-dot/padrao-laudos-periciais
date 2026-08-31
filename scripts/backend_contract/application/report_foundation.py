"""Application authority for upstream-bound canonical report revisions."""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..case_analysis import CaseAnalysisSnapshot, case_analysis_to_mapping
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
)
from ..technical_findings import TechnicalSnapshot, technical_snapshot_to_mapping
from ..vistoria import InspectionSession, inspection_session_to_mapping
from .models import thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError


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


def _binding(*, workspace_id, case_record, case, inspection_record, inspection, technical_record, technical, profile_record, profile) -> ReportSourceSnapshot:
    if any((type(case) is not CaseAnalysisSnapshot, type(inspection) is not InspectionSession, type(technical) is not TechnicalSnapshot, type(profile) is not ExpertMasterProfile)):
        raise ValueError("Report Snapshot upstream authority type mismatch")
    if case.workspace_id != str(workspace_id) or inspection.workspace_id != str(workspace_id) or technical.workspace_id != str(workspace_id):
        raise ValueError("Report Snapshot upstream workspace mismatch")
    return ReportSourceSnapshot(
        workspace_id=str(workspace_id), case_analysis_snapshot_id=case.snapshot_id, case_analysis_revision=case_record.revision,
        case_analysis_digest=report_upstream_digest(case), inspection_session_id=inspection.session_id,
        inspection_session_revision=inspection_record.revision, inspection_session_digest=report_upstream_digest(inspection),
        technical_snapshot_id=technical.snapshot_id, technical_snapshot_revision=technical_record.revision,
        technical_snapshot_digest=report_upstream_digest(technical), expert_profile_id=profile.profile_id,
        expert_profile_revision=profile_record.revision, expert_profile_digest=report_upstream_digest(profile),
    )


def _reconcile(snapshot: ReportSnapshot, current: ReportSourceSnapshot) -> ReportSnapshot:
    reasons = []
    for name, reason in (
        ("case_analysis_snapshot_id", "case analysis identity changed"), ("case_analysis_revision", "case analysis revision changed"),
        ("case_analysis_digest", "case analysis content changed"), ("inspection_session_id", "inspection identity changed"),
        ("inspection_session_revision", "inspection revision changed"), ("inspection_session_digest", "inspection content changed"),
        ("technical_snapshot_id", "technical snapshot identity changed"), ("technical_snapshot_revision", "technical snapshot revision changed"),
        ("technical_snapshot_digest", "technical snapshot content changed"), ("expert_profile_id", "expert profile identity changed"),
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


def _validate_claim_provenance(snapshot: ReportSnapshot, case: CaseAnalysisSnapshot, inspection: InspectionSession, technical: TechnicalSnapshot) -> None:
    sources = {
        "ALLEGATION": ({item.item_id for item in case.claims}, snapshot.source_snapshot.case_analysis_revision),
        "COURT_DECISION": ({item.item_id for item in case.decisions}, snapshot.source_snapshot.case_analysis_revision),
        "CASE_DOCUMENT": ({item.document_id for item in case.documents}, snapshot.source_snapshot.case_analysis_revision),
        "FIELD_OBSERVATION": ({item.observation_id for item in inspection.observations}, snapshot.source_snapshot.inspection_session_revision),
        "MEASUREMENT": ({item.measurement_id for item in inspection.measurements}, snapshot.source_snapshot.inspection_session_revision),
        "TECHNICAL_FINDING": ({item.finding_id for item in technical.findings}, snapshot.source_snapshot.technical_snapshot_revision),
        "PROFESSIONAL_DECISION": ({item.decision_id for item in technical.decisions}, snapshot.source_snapshot.technical_snapshot_revision),
    }
    for claim in snapshot.claims:
        for provenance in claim.provenance:
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


def _current(workspace_id, services):
    case_record, case = services[0].execute(workspace_id)
    inspection_record, inspection = services[1].execute(workspace_id)
    technical_record, technical = services[2].execute(workspace_id)
    profile_record, profile = services[3].execute(workspace_id)
    binding = _binding(
        workspace_id=workspace_id, case_record=case_record, case=case, inspection_record=inspection_record,
        inspection=inspection, technical_record=technical_record, technical=technical,
        profile_record=profile_record, profile=profile,
    )
    return (case_record, case, inspection_record, inspection, technical_record, technical, profile_record, profile, binding)


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
            current = _current(workspace_id, (self.get_case_analysis, self.get_inspection_session, self.get_technical_snapshot, self.get_expert_profile))
            if _reconcile(snapshot, current[-1]).upstream_stale:
                raise ValueError("Report Snapshot upstream authority is stale")
            _validate_answer_chains(snapshot, current[5])
            _validate_claim_provenance(snapshot, current[1], current[3], current[5])
            if expected_revision is not None:
                predecessor_record = self.get_latest_revision.execute(workspace_id, REPORT_SNAPSHOT_ARTIFACT_KIND, REPORT_SNAPSHOT_ARTIFACT_ID)
                predecessor = validated_report_snapshot_from_mapping(thaw_payload(predecessor_record.payload))
                if not allow_review_transition and snapshot.review_decisions != predecessor.review_decisions:
                    raise ValueError("Report Snapshot review decisions require the professional review command")
                material_fields = ("source_snapshot", "expert_profile", "editorial_profile", "context_matrix", "sections", "claims", "answers")
                if predecessor.review_decisions and any(getattr(predecessor, name) != getattr(snapshot, name) for name in material_fields):
                    raise ValueError("Report Snapshot material change requires a new draft before professional review")
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Report Snapshot clock requires timezone")
            records = (current[0], current[2], current[4], current[6])
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

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, REPORT_SNAPSHOT_ARTIFACT_KIND, REPORT_SNAPSHOT_ARTIFACT_ID)
        snapshot = validated_report_snapshot_from_mapping(thaw_payload(record.payload))
        current = _current(workspace_id, (self.get_case_analysis, self.get_inspection_session, self.get_technical_snapshot, self.get_expert_profile))
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

    def execute(self, workspace_id, *, expected_revision: int, action: str, values: dict):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.state is not ReportState.DRAFT or snapshot.review_decisions or snapshot.upstream_stale or type(values) is not dict:
            raise ValueError("Report draft amendment is invalid")
        if action == "ADD_CLAIM":
            if set(values) != {"section_id", "text", "source_kind", "source_id"}:
                raise ValueError("Report claim amendment is invalid")
            source_kind = values["source_kind"]
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


@dataclass(frozen=True, slots=True)
class StartReportSnapshot:
    get_case_analysis: object
    get_inspection_session: object
    get_technical_snapshot: object
    get_expert_profile: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id):
        current = _current(workspace_id, (self.get_case_analysis, self.get_inspection_session, self.get_technical_snapshot, self.get_expert_profile))
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
