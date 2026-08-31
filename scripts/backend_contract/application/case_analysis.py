"""Application operations for workspace-owned Case Analysis snapshots."""

from dataclasses import dataclass, replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from ..case_analysis import (
    CASE_ANALYSIS_ARTIFACT_ID,
    CASE_ANALYSIS_ARTIFACT_KIND,
    CaseAnalysisSnapshot,
    HumanReviewDecision,
    case_analysis_from_mapping,
    case_analysis_to_mapping,
)
from .models import thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "case-analysis-snapshot-v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_JDM_SCHEMA = json.loads((_SCHEMA_PATH.parent / "judicial-domain-model-v1.schema.json").read_text(encoding="utf-8"))
_REGISTRY = Registry().with_resource(_JDM_SCHEMA["$id"], Resource.from_contents(_JDM_SCHEMA))
_VALIDATOR = Draft202012Validator(_SCHEMA, registry=_REGISTRY)


def validated_case_analysis_from_mapping(value: object) -> CaseAnalysisSnapshot:
    try:
        _VALIDATOR.validate(value)
        return case_analysis_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Case Analysis payload") from exc


@dataclass(frozen=True, slots=True)
class SaveCaseAnalysis:
    revisions: object
    get_latest_revision: object
    clock: object
    ids: object
    list_documents: object | None
    authority_guard: object

    def execute(self, workspace_id, snapshot: CaseAnalysisSnapshot, expected_revision: int | None, *, allow_review_transition: bool = False):
        if type(snapshot) is not CaseAnalysisSnapshot or str(workspace_id) != snapshot.workspace_id:
            raise ValueError("Case Analysis workspace identity mismatch")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        if expected_revision is None and snapshot.human_reviews:
            raise ValueError("initial Case Analysis cannot contain human review authority")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Case Analysis authority guard is unavailable")
        with self.authority_guard():
            return self._execute_guarded(workspace_id, snapshot, expected_revision, allow_review_transition)

    def _execute_guarded(self, workspace_id, snapshot: CaseAnalysisSnapshot, expected_revision: int | None, allow_review_transition: bool):
        if self.list_documents is None:
            raise RepositoryIntegrityError("Case Analysis source inventory is unavailable")
        authoritative = {
            str(document.content_id): document.checksum_sha256
            for document in self.list_documents.execute(workspace_id)
        }
        storage_ids = [document.storage_content_id for document in snapshot.documents]
        if snapshot.source_inventory_stale or set(storage_ids) != set(authoritative) or len(storage_ids) != len(set(storage_ids)) or any(
            authoritative.get(document.storage_content_id) != document.source_sha256
            for document in snapshot.documents
        ):
            raise RepositoryIntegrityError("Case Analysis source inventory mismatch")
        if expected_revision is not None:
            record = self.get_latest_revision.execute(workspace_id, CASE_ANALYSIS_ARTIFACT_KIND, CASE_ANALYSIS_ARTIFACT_ID)
            if record.revision != expected_revision:
                raise RepositoryConflict("expected Case Analysis revision is not latest")
            predecessor = validated_case_analysis_from_mapping(thaw_payload(record.payload))
            if predecessor.material_items != snapshot.material_items or predecessor.documents != snapshot.documents:
                raise ValueError("Case Analysis source extraction is immutable")
            if not allow_review_transition and predecessor.human_reviews != snapshot.human_reviews:
                raise ValueError("Case Analysis reviews require the dedicated review command")
            if snapshot.human_reviews[:len(predecessor.human_reviews)] != predecessor.human_reviews:
                raise ValueError("Case Analysis human review history is append-only")
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
class ReviewCaseAnalysisItem:
    get_analysis: object
    save_analysis: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, target_item_id: str, action: str, corrected_value: str | None, reviewer: str, reason: str, expected_revision: int):
        if action not in {"CONFIRM", "CORRECT", "REJECT"}:
            raise ValueError("Case Analysis review action is invalid")
        record, snapshot = self.get_analysis.execute(workspace_id)
        if record.revision != expected_revision or snapshot.stale_document_ids or snapshot.source_inventory_stale:
            raise RepositoryConflict("Case Analysis review source or revision is stale")
        item = next((candidate for candidate in snapshot.material_items if candidate.item_id == target_item_id), None)
        if item is None:
            raise ValueError("Case Analysis review target is invalid")
        if action == "CORRECT":
            if type(corrected_value) is not str or not corrected_value.strip() or corrected_value == item.text:
                raise ValueError("Case Analysis correction requires a distinct value")
            effective = corrected_value.strip()
        elif corrected_value is not None:
            raise ValueError("only Case Analysis correction may carry a corrected value")
        else:
            effective = item.text
        if type(reviewer) is not str or not reviewer.strip() or type(reason) is not str or not reason.strip():
            raise ValueError("Case Analysis reviewer and reason are required")
        now = self.clock.now()
        history = [review for review in snapshot.human_reviews if review.target_item_id == target_item_id]
        decision = HumanReviewDecision(
            review_id=f"CASE-REVIEW-{self.ids.new_uuid().hex.upper()}", target_item_id=target_item_id,
            original_extraction=item.text, decision=action, corrected_value=effective, reviewer=reviewer.strip(),
            revision=len(history) + 1, timestamp=now.isoformat(), reason=reason.strip(),
        )
        reviewed = replace(snapshot, human_reviews=(*snapshot.human_reviews, decision))
        saved = self.save_analysis.execute(workspace_id, reviewed, expected_revision, allow_review_transition=True)
        return saved, reviewed


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
        reconciled = snapshot.reconcile_sources(current_hashes)
        unindexed = set(authoritative) - {document.storage_content_id for document in snapshot.documents}
        return record, replace(
            reconciled,
            source_inventory_stale=bool(unindexed),
            unindexed_source_count=len(unindexed),
        )
