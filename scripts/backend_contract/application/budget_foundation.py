"""Append-only application authority for the financial Budget Snapshot."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..budget_foundation import PericialBudget, budget_snapshot_from_mapping, budget_snapshot_to_mapping
from .models import thaw_payload
from .ports import RepositoryConflict


BUDGET_SNAPSHOT_ARTIFACT_KIND = "BUDGET_SNAPSHOT_V1"
BUDGET_SNAPSHOT_ARTIFACT_ID = "BUDGET-SNAPSHOT"
_SCHEMA = Path(__file__).resolve().parents[3] / "schemas" / "budget-snapshot-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker())
_HISTORY_FIELDS = (
    "items", "effort_estimates", "travel_estimates", "third_party_estimates", "expenses",
    "proposals", "proposal_revisions", "court_approvals", "payments",
)


def _payload(value: object) -> object:
    return value if type(value) is dict else thaw_payload(value)


def validated_budget_snapshot_from_mapping(value: object) -> PericialBudget:
    try:
        _VALIDATOR.validate(value)
        return budget_snapshot_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Budget Snapshot payload") from exc


def budget_snapshot_to_validated_mapping(value: PericialBudget) -> dict:
    mapping = budget_snapshot_to_mapping(value)
    _VALIDATOR.validate(mapping)
    return mapping


def _preserves_history(predecessor: PericialBudget, candidate: PericialBudget) -> bool:
    return all(getattr(candidate, name)[:len(getattr(predecessor, name))] == getattr(predecessor, name) for name in _HISTORY_FIELDS)


@dataclass(frozen=True, slots=True)
class SaveBudgetSnapshot:
    revisions: object
    get_latest_revision: object
    clock: object
    ids: object

    def execute(self, workspace_id, snapshot: PericialBudget, expected_revision: int | None):
        if type(snapshot) is not PericialBudget or snapshot.workspace_id != str(workspace_id):
            raise ValueError("Budget Snapshot workspace is invalid")
        if expected_revision is None:
            if snapshot.revision != 1:
                raise ValueError("initial Budget Snapshot revision is invalid")
        else:
            if type(expected_revision) is not int or expected_revision < 1:
                raise ValueError("Budget Snapshot expected revision is invalid")
            record = self.get_latest_revision.execute(workspace_id, BUDGET_SNAPSHOT_ARTIFACT_KIND, BUDGET_SNAPSHOT_ARTIFACT_ID)
            if record.revision != expected_revision:
                raise RepositoryConflict("expected Budget Snapshot revision is not latest")
            predecessor = validated_budget_snapshot_from_mapping(_payload(record.payload))
            if snapshot.budget_id != predecessor.budget_id or snapshot.revision != predecessor.revision + 1:
                raise ValueError("Budget Snapshot identity or revision changed")
            if snapshot.process_id != predecessor.process_id or snapshot.appointment_id != predecessor.appointment_id:
                raise ValueError("Budget Snapshot process links are immutable")
            if not _preserves_history(predecessor, snapshot):
                raise ValueError("Budget Snapshot history cannot be rewritten")
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Budget Snapshot clock requires timezone")
        return self.revisions.append_if_latest(
            workspace_id=workspace_id, artifact_kind=BUDGET_SNAPSHOT_ARTIFACT_KIND,
            artifact_id=BUDGET_SNAPSHOT_ARTIFACT_ID, revision_id=str(self.ids.new_uuid()),
            created_at=now.isoformat(), payload=budget_snapshot_to_validated_mapping(snapshot),
            expected_revision=expected_revision, expected_dependencies=(),
        )


@dataclass(frozen=True, slots=True)
class GetBudgetSnapshot:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, BUDGET_SNAPSHOT_ARTIFACT_KIND, BUDGET_SNAPSHOT_ARTIFACT_ID)
        return record, validated_budget_snapshot_from_mapping(_payload(record.payload))


@dataclass(frozen=True, slots=True)
class GetBudgetHistory:
    list_revisions: object

    def execute(self, workspace_id):
        records = self.list_revisions.execute(workspace_id, BUDGET_SNAPSHOT_ARTIFACT_KIND, BUDGET_SNAPSHOT_ARTIFACT_ID)
        return tuple((record, validated_budget_snapshot_from_mapping(_payload(record.payload))) for record in records)
