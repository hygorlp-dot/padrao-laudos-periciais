"""Application authority for workspace-owned Inspection Session revisions."""

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from ..pericial_planning import ProfessionalReviewStatus, pericial_planning_to_mapping
from ..vistoria import (
    INSPECTION_SESSION_ARTIFACT_ID,
    INSPECTION_SESSION_ARTIFACT_KIND,
    InspectionSession,
    inspection_session_from_mapping,
    inspection_session_to_mapping,
)
from .models import PrivateContentId, thaw_payload
from .ports import RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "inspection-session-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


def validated_inspection_session_from_mapping(value: object) -> InspectionSession:
    try:
        _VALIDATOR.validate(value)
        return inspection_session_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Inspection Session payload") from exc


def inspection_planning_digest(snapshot) -> str:
    encoded = json.dumps(
        pericial_planning_to_mapping(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _executable_planning_item_ids(snapshot) -> tuple[str, ...]:
    executable_types = {
        "InspectionRequirement", "MeasurementRequirement", "PhotoRequirement",
        "EquipmentRequirement", "AccessRequirement", "SafetyRequirement",
        "ProcedureCandidate", "SamplingCandidate", "MethodCandidate",
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


@dataclass(frozen=True, slots=True)
class SaveInspectionSession:
    revisions: object
    get_planning: object
    get_private_content: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, session: InspectionSession, expected_revision: int | None):
        if type(session) is not InspectionSession or str(workspace_id) != session.workspace_id:
            raise ValueError("Inspection Session workspace identity mismatch")
        if session.upstream_stale:
            raise ValueError("stale Inspection Session cannot be persisted")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Inspection Session authority guard is unavailable")
        with self.authority_guard():
            planning_record, planning = self.get_planning.execute(workspace_id)
            reconciled = _reconcile(session, planning_record=planning_record, planning=planning)
            if reconciled.upstream_stale:
                raise ValueError("Inspection Session does not bind the latest approved planning authority")
            self._verify_photos(workspace_id, session)
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Inspection Session clock requires timezone")
            return self.revisions.append_if_latest(
                workspace_id=workspace_id,
                artifact_kind=INSPECTION_SESSION_ARTIFACT_KIND,
                artifact_id=INSPECTION_SESSION_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()),
                created_at=created_at.isoformat(),
                payload=inspection_session_to_mapping(session),
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
