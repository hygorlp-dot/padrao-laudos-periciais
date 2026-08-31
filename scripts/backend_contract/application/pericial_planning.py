"""Application operations for workspace-owned Pericial Planning snapshots."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from ..pericial_planning import (
    PERICIAL_PLANNING_ARTIFACT_ID,
    PERICIAL_PLANNING_ARTIFACT_KIND,
    PlanningSnapshot,
    PlanningDecision,
    ReviewAction,
    append_professional_decision,
    case_analysis_digest,
    pericial_planning_from_mapping,
    pericial_planning_to_mapping,
    validate_against_case_analysis,
)
from .models import thaw_payload
from .ports import RepositoryConflict


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "pericial-planning-snapshot-v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


def validated_pericial_planning_from_mapping(value: object) -> PlanningSnapshot:
    try:
        _VALIDATOR.validate(value)
        return pericial_planning_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Pericial Planning payload") from exc


@dataclass(frozen=True, slots=True)
class SavePericialPlanning:
    revisions: object
    get_latest_revision: object
    get_case_analysis: object
    clock: object
    ids: object

    def execute(self, workspace_id, snapshot: PlanningSnapshot, expected_revision: int | None):
        if type(snapshot) is not PlanningSnapshot or str(workspace_id) != snapshot.workspace_id:
            raise ValueError("Pericial Planning workspace identity mismatch")
        if snapshot.upstream_stale:
            raise ValueError("stale Pericial Planning snapshots cannot be persisted")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        analysis_record, analysis = self.get_case_analysis.execute(workspace_id)
        if analysis.stale_document_ids or analysis.source_inventory_stale:
            raise ValueError("stale Case Analysis cannot authorize Pericial Planning")
        validate_against_case_analysis(snapshot, analysis, artifact_revision=analysis_record.revision)
        if expected_revision is not None:
            previous_record = self.get_latest_revision.execute(
                workspace_id,
                PERICIAL_PLANNING_ARTIFACT_KIND,
                PERICIAL_PLANNING_ARTIFACT_ID,
            )
            if previous_record.revision != expected_revision:
                raise ValueError("expected Pericial Planning revision is not latest")
            previous = validated_pericial_planning_from_mapping(thaw_payload(previous_record.payload))
            _validate_append_only_history(previous, snapshot)
        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Pericial Planning clock requires timezone")
        return self.revisions.append_if_latest(
            workspace_id=workspace_id,
            artifact_kind=PERICIAL_PLANNING_ARTIFACT_KIND,
            artifact_id=PERICIAL_PLANNING_ARTIFACT_ID,
            revision_id=str(self.ids.new_uuid()),
            created_at=created_at.isoformat(),
            payload=pericial_planning_to_mapping(snapshot),
            expected_revision=expected_revision,
        )


@dataclass(frozen=True, slots=True)
class GetPericialPlanning:
    get_latest_revision: object
    get_case_analysis: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id,
            PERICIAL_PLANNING_ARTIFACT_KIND,
            PERICIAL_PLANNING_ARTIFACT_ID,
        )
        snapshot = validated_pericial_planning_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Pericial Planning workspace mismatch")
        analysis_record, analysis = self.get_case_analysis.execute(workspace_id)
        reconciled = snapshot.reconcile_upstream(
            snapshot_id=analysis.snapshot_id,
            revision=analysis_record.revision,
            source_revision=analysis.source_revision,
            digest=case_analysis_digest(analysis),
        )
        return record, reconciled


@dataclass(frozen=True, slots=True)
class ReviewPericialPlanning:
    get_planning: object
    save_planning: object
    clock: object
    ids: object

    def execute(
        self,
        workspace_id,
        *,
        target_item_id: str,
        action: str,
        reviewer: str,
        reason: str,
        decided_value: str | None,
        expected_revision: int,
    ):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected revision is invalid")
        record, snapshot = self.get_planning.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Pericial Planning revision is not latest")
        if snapshot.upstream_stale:
            raise ValueError("stale Pericial Planning cannot receive professional decisions")
        target = next((item for item in snapshot.material_items if item.item_id == target_item_id), None)
        if target is None:
            raise ValueError("professional decision target is invalid")
        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("professional decision clock requires timezone")
        decision_uuid = self.ids.new_uuid()
        history = [item for item in snapshot.decisions if item.target_item_id == target_item_id]
        decision = PlanningDecision(
            decision_id=f"PLANNING-DECISION-{decision_uuid.hex.upper()}",
            target_item_id=target_item_id,
            action=ReviewAction(action),
            proposal_value=target.description,
            decided_value=decided_value,
            reviewer=reviewer,
            reason=reason,
            revision=len(history) + 1,
            timestamp=created_at.isoformat(),
        )
        reviewed = append_professional_decision(snapshot, decision)
        saved = self.save_planning.execute(workspace_id, reviewed, expected_revision)
        return saved, reviewed


def _validate_append_only_history(previous: PlanningSnapshot, current: PlanningSnapshot) -> None:
    if previous.plan.plan_id != current.plan.plan_id:
        return
    previous_items = {item.item_id: _proposal_signature(item) for item in previous.material_items}
    current_items = {item.item_id: _proposal_signature(item) for item in current.material_items}
    if not previous_items.keys() <= current_items.keys() or any(
        current_items[item_id] != signature for item_id, signature in previous_items.items()
    ):
        raise ValueError("immutable proposal history cannot be replaced")
    previous_decisions = pericial_planning_to_mapping(previous)["decisions"]
    current_decisions = pericial_planning_to_mapping(current)["decisions"]
    if current_decisions[: len(previous_decisions)] != previous_decisions:
        raise ValueError("immutable proposal decision history cannot be replaced")


def _proposal_signature(item) -> dict:
    value = asdict(item)
    value.pop("professional_review_status", None)
    return value
