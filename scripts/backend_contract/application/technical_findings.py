"""Application authority for upstream-bound Technical Snapshot revisions."""

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..case_analysis import CaseAnalysisSnapshot, case_analysis_to_mapping
from ..technical_findings import (
    TECHNICAL_SNAPSHOT_ARTIFACT_ID,
    TECHNICAL_SNAPSHOT_ARTIFACT_KIND,
    TechnicalCoverage,
    TechnicalSnapshot,
    TechnicalSourceSnapshot,
    technical_snapshot_from_mapping,
    technical_snapshot_to_mapping,
)
from ..vistoria import InspectionSession, inspection_session_to_mapping
from .models import thaw_payload
from .ports import RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "technical-snapshot-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker())


def technical_upstream_digest(value: object) -> str:
    if type(value) is CaseAnalysisSnapshot:
        mapping = case_analysis_to_mapping(value)
    elif type(value) is InspectionSession:
        mapping = inspection_session_to_mapping(value)
    else:
        raise TypeError("unsupported Technical Snapshot upstream authority")
    encoded = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validated_technical_snapshot_from_mapping(value: object) -> TechnicalSnapshot:
    try:
        _VALIDATOR.validate(value)
        return technical_snapshot_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Technical Snapshot payload") from exc


def technical_snapshot_to_validated_mapping(value: object) -> dict[str, object]:
    if type(value) is not TechnicalSnapshot:
        raise RepositoryIntegrityError("Technical Snapshot persisted state is invalid")
    return technical_snapshot_to_mapping(value)


def _binding(*, workspace_id, case_record, case, inspection_record, inspection) -> TechnicalSourceSnapshot:
    if (
        type(case) is not CaseAnalysisSnapshot
        or type(inspection) is not InspectionSession
        or case.workspace_id != str(workspace_id)
        or inspection.workspace_id != str(workspace_id)
    ):
        raise ValueError("Technical Snapshot upstream workspace mismatch")
    return TechnicalSourceSnapshot(
        workspace_id=str(workspace_id),
        case_analysis_snapshot_id=case.snapshot_id,
        case_analysis_revision=case_record.revision,
        case_analysis_digest=technical_upstream_digest(case),
        inspection_session_id=inspection.session_id,
        inspection_session_revision=inspection_record.revision,
        inspection_session_digest=technical_upstream_digest(inspection),
        source_revision=inspection.source_revision,
    )


def _reconcile(snapshot: TechnicalSnapshot, *, current: TechnicalSourceSnapshot) -> TechnicalSnapshot:
    bound = snapshot.source_snapshot
    reasons = []
    comparisons = (
        (bound.case_analysis_snapshot_id, current.case_analysis_snapshot_id, "case analysis snapshot identity changed"),
        (bound.case_analysis_revision, current.case_analysis_revision, "case analysis artifact revision changed"),
        (bound.case_analysis_digest, current.case_analysis_digest, "case analysis content changed"),
        (bound.inspection_session_id, current.inspection_session_id, "inspection session identity changed"),
        (bound.inspection_session_revision, current.inspection_session_revision, "inspection session artifact revision changed"),
        (bound.inspection_session_digest, current.inspection_session_digest, "inspection session content changed"),
        (bound.source_revision, current.source_revision, "upstream source revision changed"),
    )
    reasons.extend(reason for actual, expected, reason in comparisons if actual != expected)
    coverage = replace(snapshot.coverage, complete=False) if reasons and snapshot.coverage.complete else snapshot.coverage
    return replace(snapshot, coverage=coverage, upstream_stale=bool(reasons), upstream_stale_reasons=tuple(reasons))


@dataclass(frozen=True, slots=True)
class SaveTechnicalSnapshot:
    revisions: object
    get_case_analysis: object
    get_inspection_session: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, snapshot: TechnicalSnapshot, expected_revision: int | None):
        if type(snapshot) is not TechnicalSnapshot or snapshot.workspace_id != str(workspace_id):
            raise ValueError("Technical Snapshot workspace mismatch")
        if snapshot.upstream_stale:
            raise ValueError("stale Technical Snapshot cannot be persisted")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("Technical Snapshot expected revision is invalid")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Technical Snapshot authority guard is unavailable")
        with self.authority_guard():
            case_record, case = self.get_case_analysis.execute(workspace_id)
            inspection_record, inspection = self.get_inspection_session.execute(workspace_id)
            current = _binding(
                workspace_id=workspace_id, case_record=case_record, case=case,
                inspection_record=inspection_record, inspection=inspection,
            )
            if _reconcile(snapshot, current=current).upstream_stale:
                raise ValueError("Technical Snapshot upstream authority is stale")
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Technical Snapshot clock requires timezone")
            dependencies = tuple({
                "artifact_kind": record.artifact_kind,
                "artifact_id": record.artifact_id,
                "revision": record.revision,
                "checksum_sha256": record.checksum_sha256,
            } for record in (case_record, inspection_record))
            return self.revisions.append_if_latest(
                workspace_id=workspace_id,
                artifact_kind=TECHNICAL_SNAPSHOT_ARTIFACT_KIND,
                artifact_id=TECHNICAL_SNAPSHOT_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()),
                created_at=created_at.isoformat(),
                payload=technical_snapshot_to_mapping(snapshot),
                expected_revision=expected_revision,
                expected_dependencies=dependencies,
            )


@dataclass(frozen=True, slots=True)
class GetTechnicalSnapshot:
    get_latest_revision: object
    get_case_analysis: object
    get_inspection_session: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id, TECHNICAL_SNAPSHOT_ARTIFACT_KIND, TECHNICAL_SNAPSHOT_ARTIFACT_ID
        )
        snapshot = validated_technical_snapshot_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Technical Snapshot workspace mismatch")
        case_record, case = self.get_case_analysis.execute(workspace_id)
        inspection_record, inspection = self.get_inspection_session.execute(workspace_id)
        current = _binding(
            workspace_id=workspace_id, case_record=case_record, case=case,
            inspection_record=inspection_record, inspection=inspection,
        )
        return record, _reconcile(snapshot, current=current)


@dataclass(frozen=True, slots=True)
class StartTechnicalSnapshot:
    get_case_analysis: object
    get_inspection_session: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id):
        case_record, case = self.get_case_analysis.execute(workspace_id)
        inspection_record, inspection = self.get_inspection_session.execute(workspace_id)
        if case.source_inventory_stale or inspection.upstream_stale:
            raise ValueError("stale upstream cannot start a Technical Snapshot")
        source = _binding(
            workspace_id=workspace_id, case_record=case_record, case=case,
            inspection_record=inspection_record, inspection=inspection,
        )
        snapshot = TechnicalSnapshot(
            schema_version="1.0.0",
            snapshot_id=f"TECHNICAL-SNAPSHOT-{self.ids.new_uuid().hex.upper()}",
            workspace_id=str(workspace_id), source_snapshot=source,
            evidence_items=(), source_links=(), evidence_assessments=(),
            method_applications=(), method_inputs=(), method_outputs=(),
            finding_proposals=(), findings=(), dependencies=(), conflicts=(),
            limitations=(), uncertainties=(), question_links=(), decisions=(),
            coverage=TechnicalCoverage(
                evidence_items=0, approved_evidence=0, method_applications=0,
                finding_proposals=0, effective_findings=0, unresolved_conflicts=0,
                complete=False, reasons=("A cadeia técnica ainda não possui evidências avaliadas.",),
            ),
            upstream_stale=False, upstream_stale_reasons=(),
        )
        record = self.save_snapshot.execute(workspace_id, snapshot, None)
        return record, snapshot
