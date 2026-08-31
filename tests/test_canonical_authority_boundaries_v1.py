from datetime import UTC, datetime
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import WorkspaceId
from scripts.backend_contract.application.services import AppendArtifactRevision


CANONICAL_ARTIFACTS = (
    ("CASE_ANALYSIS_SNAPSHOT_V1", "CASE-ANALYSIS"),
    ("PERICIAL_PLANNING_SNAPSHOT_V1", "PERICIAL-PLANNING"),
    ("INSPECTION_SESSION_V1", "INSPECTION-SESSION"),
    ("TECHNICAL_SNAPSHOT_V1", "TECHNICAL-SNAPSHOT"),
    ("EXPERT_MASTER_PROFILE_V1", "EXPERT-PROFILE"),
    ("REPORT_SNAPSHOT_V1", "REPORT-SNAPSHOT"),
    ("DELIVERY_SNAPSHOT_V1", "DELIVERY-SNAPSHOT"),
    ("BUDGET_SNAPSHOT_V1", "BUDGET-SNAPSHOT"),
)


class RecordingRevisionRepository:
    def __init__(self):
        self.appended = []

    def append(self, **values):
        self.appended.append(values)
        return values


class Clock:
    def now(self):
        return datetime(2026, 8, 31, tzinfo=UTC)


class Ids:
    def new_uuid(self):
        return UUID("22222222-2222-4222-8222-222222222222")


@pytest.mark.parametrize(("artifact_kind", "artifact_id"), (*CANONICAL_ARTIFACTS, ("ARBITRARY_UNKNOWN", "POISON")))
def test_generic_application_mutation_cannot_write_any_artifact(artifact_kind: str, artifact_id: str) -> None:
    repository = RecordingRevisionRepository()
    with pytest.raises(ValueError, match="generic artifact mutation is disabled"):
        AppendArtifactRevision(repository, Clock(), Ids()).execute(
            workspace_id=WorkspaceId.parse("11111111-1111-4111-8111-111111111111"),
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            payload={"forged": True},
        )
    assert repository.appended == []
