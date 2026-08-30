"""Application operations for workspace-owned Case Analysis snapshots."""

from dataclasses import dataclass

from ..case_analysis import (
    CASE_ANALYSIS_ARTIFACT_ID,
    CASE_ANALYSIS_ARTIFACT_KIND,
    CaseAnalysisSnapshot,
    case_analysis_from_mapping,
    case_analysis_to_mapping,
)
from .models import thaw_payload
from .ports import ArtifactRevisionNotFound, RepositoryConflict


@dataclass(frozen=True, slots=True)
class SaveCaseAnalysis:
    append_revision: object
    get_latest_revision: object

    def execute(self, workspace_id, snapshot: CaseAnalysisSnapshot, expected_revision: int | None):
        if type(snapshot) is not CaseAnalysisSnapshot or str(workspace_id) != snapshot.workspace_id:
            raise ValueError("Case Analysis workspace identity mismatch")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        try:
            current = self.get_latest_revision.execute(
                workspace_id,
                CASE_ANALYSIS_ARTIFACT_KIND,
                CASE_ANALYSIS_ARTIFACT_ID,
            )
        except ArtifactRevisionNotFound:
            current = None
        current_revision = None if current is None else current.revision
        if current_revision != expected_revision:
            raise RepositoryConflict("Case Analysis revision conflict")
        return self.append_revision.execute(
            workspace_id=workspace_id,
            artifact_kind=CASE_ANALYSIS_ARTIFACT_KIND,
            artifact_id=CASE_ANALYSIS_ARTIFACT_ID,
            payload=case_analysis_to_mapping(snapshot),
        )


@dataclass(frozen=True, slots=True)
class GetCaseAnalysis:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id,
            CASE_ANALYSIS_ARTIFACT_KIND,
            CASE_ANALYSIS_ARTIFACT_ID,
        )
        snapshot = case_analysis_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Case Analysis workspace mismatch")
        return record, snapshot
