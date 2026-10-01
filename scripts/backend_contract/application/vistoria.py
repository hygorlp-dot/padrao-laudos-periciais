"""Application authority for workspace-owned Inspection Session revisions."""

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..pericial_planning import ProfessionalReviewStatus, pericial_planning_to_mapping
from ..vistoria import (
    INSPECTION_SESSION_ARTIFACT_ID,
    INSPECTION_SESSION_ARTIFACT_KIND,
    AccessOutcome,
    ExecutionState,
    InspectionCoverage,
    InspectionItem,
    InspectionPlanSnapshot,
    InspectionSession,
    LocationReference,
    ObservationType,
    inspection_session_from_mapping,
    inspection_session_to_mapping,
)
from .models import PrivateContentId, thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError
from ..visit_context import VisitContext


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "inspection-session-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker())


def validated_inspection_session_from_mapping(value: object) -> InspectionSession:
    try:
        _VALIDATOR.validate(value)
        return inspection_session_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Inspection Session payload") from exc


def inspection_session_to_validated_mapping(value: object) -> dict[str, object]:
    if type(value) is not InspectionSession:
        raise RepositoryIntegrityError("Inspection Session persisted state is invalid")
    return inspection_session_to_mapping(value)


def inspection_planning_digest(snapshot) -> str:
    encoded = json.dumps(
        pericial_planning_to_mapping(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _executable_planning_item_ids(snapshot) -> tuple[str, ...]:
    executable_types = {
        "InspectionRequirement", "MeasurementRequirement", "PhotoRequirement", "AccessRequirement",
    }
    return tuple(
        item.item_id for item in snapshot.material_items
        if type(item).__name__ in executable_types
        and item.professional_review_status in {
            ProfessionalReviewStatus.APPROVED, ProfessionalReviewStatus.MODIFIED
        }
    )


def _reconcile(session: InspectionSession, *, planning_record, planning) -> InspectionSession:
    reasons = []
    binding = session.plan_snapshot
    if binding.planning_snapshot_id != planning.snapshot_id:
        reasons.append("planning snapshot identity changed")
    if binding.planning_revision != planning_record.revision:
        reasons.append("planning artifact revision changed")
    if binding.planning_digest != inspection_planning_digest(planning):
        reasons.append("planning content digest changed")
    if binding.source_revision != planning.plan.case_analysis_source_revision:
        reasons.append("planning source revision changed")
    if planning.upstream_stale:
        reasons.append("planning is stale against Case Analysis")
    if tuple(binding.approved_item_ids) != _executable_planning_item_ids(planning):
        reasons.append("approved executable planning items changed")
    return replace(session, upstream_stale=bool(reasons), upstream_stale_reasons=tuple(reasons))


def _validate_execution_against_planning(session: InspectionSession, planning) -> None:
    planning_by_id = {item.item_id: item for item in planning.material_items}
    for item in session.items:
        planned = planning_by_id[item.planning_item_id]
        if item.state is not ExecutionState.PENDING and not (item.note and item.note.strip()):
            raise ValueError("executed inspection item requires an explicit professional note")
        if item.state in {ExecutionState.PARTIAL, ExecutionState.NOT_EXECUTED, ExecutionState.BLOCKED} and not item.limitation_ids:
            raise ValueError("incomplete inspection item requires an explicit limitation")
        if item.state is not ExecutionState.COMPLETED:
            continue
        name = type(planned).__name__
        if name == "InspectionRequirement" and not any(
            record.inspection_item_id == item.item_id and record.observation_type is ObservationType.DIRECT_OBSERVATION
            for record in session.observations
        ):
            raise ValueError("completed inspection requirement requires field observation")
        if name == "MeasurementRequirement" and not item.measurement_ids:
            raise ValueError("completed measurement requirement requires measurement")
        if name == "PhotoRequirement" and not item.photo_ids:
            raise ValueError("completed photo requirement requires private photo record")
        if name == "AccessRequirement" and not any(
            record.inspection_item_id == item.item_id and record.outcome is AccessOutcome.FULL_ACCESS
            for record in session.access_occurrences
        ):
            raise ValueError("completed access requirement requires full access occurrence")


@dataclass(frozen=True, slots=True)
class SaveInspectionSession:
    revisions: object
    get_latest_revision: object
    get_planning: object
    get_private_content: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, session: InspectionSession, expected_revision: int | None, *, allow_initial_create: bool = False, allow_visit_confirmation: bool = False):
        if type(session) is not InspectionSession or str(workspace_id) != session.workspace_id:
            raise ValueError("Inspection Session workspace identity mismatch")
        if session.upstream_stale:
            raise ValueError("stale Inspection Session cannot be persisted")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        if expected_revision is None and not allow_initial_create:
            raise ValueError("initial Inspection Session requires the canonical start command")
        if expected_revision is None and session.visit_context is not None:
            raise ValueError("visit facts require the dedicated confirmation command")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Inspection Session authority guard is unavailable")
        with self.authority_guard():
            if expected_revision is not None:
                predecessor_record = self.get_latest_revision.execute(
                    workspace_id, INSPECTION_SESSION_ARTIFACT_KIND, INSPECTION_SESSION_ARTIFACT_ID
                )
                if predecessor_record.revision != expected_revision:
                    raise RepositoryConflict("expected Inspection Session revision is not latest")
                predecessor = validated_inspection_session_from_mapping(thaw_payload(predecessor_record.payload))
                immutable = ("session_id", "workspace_id", "plan_snapshot", "started_at", "responsible_professional", "source_revision")
                if any(getattr(session, name) != getattr(predecessor, name) for name in immutable):
                    raise ValueError("Inspection Session immutable authority changed")
                if {(item.item_id, item.planning_item_id): item.title for item in session.items} != {
                    (item.item_id, item.planning_item_id): item.title for item in predecessor.items
                }:
                    raise ValueError("Inspection Session planned item identity or title changed")
                if session.visit_context != predecessor.visit_context and not allow_visit_confirmation:
                    raise ValueError("visit facts require the dedicated confirmation command")
                if allow_visit_confirmation and session.reviews:
                    raise ValueError("changed visit facts invalidate prior inspection review")
                if session.reviews != predecessor.reviews and not allow_visit_confirmation:
                    raise ValueError("Inspection Session reviews require a dedicated professional command")
                append_only = (
                    "observations", "statements", "measurements", "measurement_series", "methods", "instruments",
                    "instrument_statuses", "photos", "videos", "sketches", "locations", "environmental_conditions",
                    "access_occurrences", "limitations", "missing_items", "evidence_candidates",
                )
                if any(getattr(session, name)[:len(getattr(predecessor, name))] != getattr(predecessor, name) for name in append_only):
                    raise ValueError("Inspection Session field history cannot be rewritten")
            planning_record, planning = self.get_planning.execute(workspace_id)
            reconciled = _reconcile(session, planning_record=planning_record, planning=planning)
            if reconciled.upstream_stale:
                raise ValueError("Inspection Session does not bind the latest approved planning authority")
            _validate_execution_against_planning(session, planning)
            self._verify_photos(workspace_id, session)
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Inspection Session clock requires timezone")
            # Mesma regra da Analise do Caso: a escrita valida o schema que a leitura
            # valida. Sem isso, um valor que o dominio aceita e o schema recusa era
            # gravado com 200 e toda leitura seguinte falhava (sessao perdida).
            payload = inspection_session_to_mapping(session)
            try:
                _VALIDATOR.validate(payload)
            except ValidationError as exc:
                raise ValueError("Inspection Session payload violates its published schema") from exc
            return self.revisions.append_if_latest(
                workspace_id=workspace_id,
                artifact_kind=INSPECTION_SESSION_ARTIFACT_KIND,
                artifact_id=INSPECTION_SESSION_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()),
                created_at=created_at.isoformat(),
                payload=payload,
                expected_revision=expected_revision,
                expected_dependencies=({
                    "artifact_kind": getattr(planning_record, "artifact_kind", "PERICIAL_PLANNING_SNAPSHOT_V1"),
                    "artifact_id": getattr(planning_record, "artifact_id", "PERICIAL-PLANNING"),
                    "revision": planning_record.revision,
                    "checksum_sha256": getattr(planning_record, "checksum_sha256", inspection_planning_digest(planning)),
                },),
            )

    def _verify_photos(self, workspace_id, session: InspectionSession) -> None:
        for photo in session.photos:
            record = self.get_private_content.execute(workspace_id, PrivateContentId.parse(photo.private_content_id))
            metadata = getattr(record, "metadata", None)
            if (
                metadata is None or metadata.workspace_id != workspace_id
                or str(metadata.content_id) != photo.private_content_id
                or metadata.checksum_sha256 != photo.original_sha256
                or type(metadata.media_type) is not str or not metadata.media_type.startswith("image/")
            ):
                raise ValueError("photo record diverges from private original authority")


@dataclass(frozen=True, slots=True)
class ConfirmInspectionVisit:
    get_session: object
    save_session: object
    get_expert_profile: object
    clock: object

    def execute(self, workspace_id, *, values, expected_revision):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("visit expected revision is invalid")
        record, session = self.get_session.execute(workspace_id)
        if record.revision != expected_revision or session.upstream_stale:
            raise RepositoryConflict("visit session is stale")
        _, profile = self.get_expert_profile.execute(workspace_id)
        context = VisitContext.from_values(values, confirmed_by=profile.profile_id, confirmed_at=self.clock.now().isoformat())
        updated = replace(session, visit_context=context, participant_references=tuple(dict.fromkeys(person.name for person in context.attendants)), reviews=())
        saved = self.save_session.execute(workspace_id, updated, expected_revision, allow_visit_confirmation=True)
        return saved, updated


@dataclass(frozen=True, slots=True)
class GetInspectionSession:
    get_latest_revision: object
    get_planning: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id, INSPECTION_SESSION_ARTIFACT_KIND, INSPECTION_SESSION_ARTIFACT_ID
        )
        session = validated_inspection_session_from_mapping(thaw_payload(record.payload))
        if session.workspace_id != str(workspace_id):
            raise ValueError("persisted Inspection Session workspace mismatch")
        planning_record, planning = self.get_planning.execute(workspace_id)
        return record, _reconcile(session, planning_record=planning_record, planning=planning)


@dataclass(frozen=True, slots=True)
class StartInspectionSession:
    get_planning: object
    save_session: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, responsible_professional: str, location_context: str, participant_references: tuple[str, ...]):
        if not isinstance(responsible_professional, str) or not responsible_professional.strip():
            raise ValueError("responsible professional is required")
        if not isinstance(location_context, str) or not location_context.strip():
            raise ValueError("inspection location context is required")
        if type(participant_references) is not tuple or any(type(item) is not str or not item.strip() for item in participant_references):
            raise ValueError("inspection participant references are invalid")
        record, planning = self.get_planning.execute(workspace_id)
        if planning.upstream_stale:
            raise ValueError("stale planning cannot start an Inspection Session")
        approved_ids = _executable_planning_item_ids(planning)
        if not approved_ids:
            raise ValueError("approved planning has no executable inspection items")
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Inspection Session clock requires timezone")
        item_by_id = {item.item_id: item for item in planning.material_items}
        # Capture the approved context now, in this bound planning revision.
        # Reopening an old session must never borrow text from a newer plan.
        decisions = {item_id: max((decision for decision in planning.decisions if decision.target_item_id == item_id), key=lambda decision: decision.revision) for item_id in approved_ids}
        contexts = {item_id: decision.decided_value or decision.proposal_value for item_id, decision in decisions.items()}
        location_id = f"LOCATION-{self.ids.new_uuid().hex.upper()}"
        items = tuple(
            InspectionItem(
                item_id=f"INSPECTION-ITEM-{self.ids.new_uuid().hex.upper()}",
                planning_item_id=item_id,
                title=f"{item_by_id[item_id].title} — {contexts[item_id]}" if contexts[item_id] != item_by_id[item_id].title else contexts[item_id],
                state=ExecutionState.PENDING,
                observation_ids=(), measurement_ids=(), photo_ids=(), limitation_ids=(), note=None,
            )
            for item_id in approved_ids
        )
        session = InspectionSession(
            schema_version="1.0.0",
            session_id=f"INSPECTION-SESSION-{self.ids.new_uuid().hex.upper()}",
            workspace_id=str(workspace_id),
            plan_snapshot=InspectionPlanSnapshot(
                plan_id=planning.plan.plan_id, planning_snapshot_id=planning.snapshot_id,
                planning_revision=record.revision, planning_digest=inspection_planning_digest(planning),
                workspace_id=str(workspace_id), approved_item_ids=approved_ids,
                source_revision=planning.plan.case_analysis_source_revision,
            ),
            started_at=now.isoformat(), ended_at=None, location_context=location_context,
            participant_references=participant_references, responsible_professional=responsible_professional,
            source_revision=planning.plan.case_analysis_source_revision, items=items,
            observations=(), statements=(), measurements=(), measurement_series=(), methods=(),
            instruments=(), instrument_statuses=(), photos=(), videos=(), sketches=(),
            locations=(LocationReference(location_id, location_context, None),), environmental_conditions=(),
            access_occurrences=(), limitations=(), missing_items=(), evidence_candidates=(),
            coverage=InspectionCoverage(
                total_items=len(items), pending_items=len(items), completed_items=0, partial_items=0,
                not_executed_items=0, not_applicable_items=0, blocked_items=0, complete=False,
                limitation_ids=(), reasons=("Itens de vistoria aguardam execução.",),
            ),
            reviews=(),
        )
        saved = self.save_session.execute(workspace_id, session, None, allow_initial_create=True)
        return saved, session
