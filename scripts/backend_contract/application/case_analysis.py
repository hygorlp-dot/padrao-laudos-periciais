"""Application operations for workspace-owned Case Analysis snapshots."""

from dataclasses import dataclass
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from ..case_analysis import (
    CASE_ANALYSIS_ARTIFACT_ID,
    CASE_ANALYSIS_ARTIFACT_KIND,
    CaseAnalysisSnapshot,
    case_analysis_from_mapping,
    case_analysis_to_mapping,
)
from .models import thaw_payload
from .ports import RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "case-analysis-snapshot-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


def validated_case_analysis_from_mapping(value: object) -> CaseAnalysisSnapshot:
    try:
        _VALIDATOR.validate(value)
        return case_analysis_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Case Analysis payload") from exc


@dataclass(frozen=True, slots=True)
class SaveCaseAnalysis:
    revisions: object
    clock: object
    ids: object
    list_documents: object | None

    def execute(self, workspace_id, snapshot: CaseAnalysisSnapshot, expected_revision: int | None):
        if type(snapshot) is not CaseAnalysisSnapshot or str(workspace_id) != snapshot.workspace_id:
            raise ValueError("Case Analysis workspace identity mismatch")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        if self.list_documents is None:
            raise RepositoryIntegrityError("Case Analysis source inventory is unavailable")
        authoritative = {
            str(document.content_id): document.checksum_sha256
            for document in self.list_documents.execute(workspace_id)
        }
        storage_ids = [document.storage_content_id for document in snapshot.documents]
        if len(storage_ids) != len(set(storage_ids)) or any(
            authoritative.get(document.storage_content_id) != document.source_sha256
            for document in snapshot.documents
        ):
            raise RepositoryIntegrityError("Case Analysis source inventory mismatch")
        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Case Analysis clock requires timezone")
        return self.revisions.append_if_latest(
            workspace_id=workspace_id,
            artifact_kind=CASE_ANALYSIS_ARTIFACT_KIND,
            artifact_id=CASE_ANALYSIS_ARTIFACT_ID,
            revision_id=str(self.ids.new_uuid()),
            created_at=created_at.isoformat(),
            payload=case_analysis_to_mapping(snapshot),
            expected_revision=expected_revision,
        )


@dataclass(frozen=True, slots=True)
class GetCaseAnalysis:
    get_latest_revision: object
    list_documents: object | None

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id,
            CASE_ANALYSIS_ARTIFACT_KIND,
            CASE_ANALYSIS_ARTIFACT_ID,
        )
        snapshot = validated_case_analysis_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Case Analysis workspace mismatch")
        if self.list_documents is None:
            raise RepositoryIntegrityError("Case Analysis source inventory is unavailable")
        authoritative = {
            str(document.content_id): document.checksum_sha256
            for document in self.list_documents.execute(workspace_id)
        }
        current_hashes = {
            document.document_id: authoritative.get(document.storage_content_id)
            for document in snapshot.documents
        }
        return record, snapshot.reconcile_sources(current_hashes)
