"""Application authority for immutable construction-defect PAT revisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from ..case_analysis import CaseAnalysisSnapshot
from ..construction_defect_analysis import (
    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
    ConstructionDefectAnalysisProposal,
    ConstructionDefectAnalysisSnapshot,
    ConstructionDefectSourceSnapshot,
    ObservationContext,
    PathologyReview,
    PathologyReviewAction,
    construction_defect_analysis_from_mapping,
    construction_defect_analysis_to_mapping,
    observation_context_from_mapping,
    thaw_json_payload,
)
from ..pericial_planning import PlanningSnapshot
from ..vistoria import InspectionSession
from .models import ProcessCaseData, thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError


_ROOT = Path(__file__).resolve().parents[3]
_WRAPPER_SCHEMA_PATH = _ROOT / "schemas" / "construction-defect-analysis-v1.schema.json"
_ENGINE_SCHEMA_PATH = _ROOT / "schemas" / "analise-motor-vicios.schema.json"
_WRAPPER_VALIDATOR = Draft202012Validator(
    json.loads(_WRAPPER_SCHEMA_PATH.read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


def _build_engine_validator():
    registry = Registry()
    selected = None
    for path in (_ROOT / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        if path == _ENGINE_SCHEMA_PATH:
            selected = schema
    if selected is None:  # pragma: no cover - repository corruption guard
        raise RuntimeError("construction-defect engine schema is unavailable")
    validator = validator_for(selected)
    validator.check_schema(selected)
    return validator(selected, registry=registry, format_checker=FormatChecker())


_ENGINE_VALIDATOR = _build_engine_validator()


def validated_construction_defect_analysis_from_mapping(
    value: object,
) -> ConstructionDefectAnalysisSnapshot:
    try:
        _WRAPPER_VALIDATOR.validate(value)
        snapshot = construction_defect_analysis_from_mapping(value)
        _ENGINE_VALIDATOR.validate(thaw_json_payload(snapshot.analysis_final))
        return snapshot
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Construction Defect Analysis payload") from exc


def construction_defect_analysis_to_validated_mapping(
    value: object,
) -> dict[str, object]:
    if type(value) is not ConstructionDefectAnalysisSnapshot:
        raise RepositoryIntegrityError(
            "Construction Defect Analysis persisted state is invalid"
        )
    mapping = construction_defect_analysis_to_mapping(value)
    try:
        _WRAPPER_VALIDATOR.validate(mapping)
        _ENGINE_VALIDATOR.validate(mapping["analysis_final"])
    except ValidationError as exc:
        raise RepositoryIntegrityError(
            "Construction Defect Analysis persisted state is invalid"
        ) from exc
    return mapping


def validated_observation_contexts_from_mapping(
    value: object,
) -> tuple[ObservationContext, ...]:
    if type(value) is not list or not value:
        raise ValueError("invalid Construction Defect Analysis observation contexts")
    try:
        return tuple(observation_context_from_mapping(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid Construction Defect Analysis observation contexts"
        ) from exc


@dataclass(frozen=True, slots=True)
class _Authorities:
    process_record: object
    process_case: ProcessCaseData
    case_record: object
    case_analysis: CaseAnalysisSnapshot
    planning_record: object
    planning: PlanningSnapshot
    inspection_record: object
    inspection: InspectionSession

    @property
    def records(self) -> tuple[object, ...]:
        return (
            self.process_record,
            self.case_record,
            self.planning_record,
            self.inspection_record,
        )


def _authorities(
    workspace_id,
    *,
    get_latest_revision,
    get_process_case,
    get_case_analysis,
    get_planning,
    get_inspection,
) -> _Authorities:
    process_snapshot = get_process_case.execute(workspace_id)
    if process_snapshot.revision is None or type(process_snapshot.data) is not ProcessCaseData:
        raise ValueError("construction-defect analysis requires Process Case authority")
    process_record = get_latest_revision.execute(
        workspace_id, "PROCESS_CASE", "PROCESS_CASE"
    )
    case_record, case_analysis = get_case_analysis.execute(workspace_id)
    planning_record, planning = get_planning.execute(workspace_id)
    inspection_record, inspection = get_inspection.execute(workspace_id)
    if (
        process_record.revision != process_snapshot.revision
        or type(case_analysis) is not CaseAnalysisSnapshot
        or type(planning) is not PlanningSnapshot
        or type(inspection) is not InspectionSession
    ):
        raise RepositoryIntegrityError(
            "construction-defect upstream authority is inconsistent"
        )
    expected_workspace = str(workspace_id)
    if {
        case_analysis.workspace_id,
        planning.workspace_id,
        inspection.workspace_id,
    } != {expected_workspace}:
        raise ValueError("construction-defect upstream workspace mismatch")
    return _Authorities(
        process_record,
        process_snapshot.data,
        case_record,
        case_analysis,
        planning_record,
        planning,
        inspection_record,
        inspection,
    )


def _binding(workspace_id, authorities: _Authorities) -> ConstructionDefectSourceSnapshot:
    case = authorities.case_analysis
    planning = authorities.planning
    inspection = authorities.inspection
    return ConstructionDefectSourceSnapshot(
        workspace_id=str(workspace_id),
        process_case_revision=authorities.process_record.revision,
        process_case_digest=authorities.process_record.checksum_sha256,
        case_analysis_snapshot_id=case.snapshot_id,
        case_analysis_revision=authorities.case_record.revision,
        case_analysis_digest=authorities.case_record.checksum_sha256,
        planning_snapshot_id=planning.snapshot_id,
        planning_revision=authorities.planning_record.revision,
        planning_digest=authorities.planning_record.checksum_sha256,
        inspection_session_id=inspection.session_id,
        inspection_revision=authorities.inspection_record.revision,
        inspection_digest=authorities.inspection_record.checksum_sha256,
        source_revision=inspection.source_revision,
    )


def _reconcile(
    snapshot: ConstructionDefectAnalysisSnapshot,
    *,
    current: ConstructionDefectSourceSnapshot,
) -> ConstructionDefectAnalysisSnapshot:
    bound = snapshot.source_snapshot
    comparisons = (
        (bound.process_case_revision, current.process_case_revision, "Process Case revision changed"),
        (bound.process_case_digest, current.process_case_digest, "Process Case content changed"),
        (bound.case_analysis_snapshot_id, current.case_analysis_snapshot_id, "Case Analysis snapshot identity changed"),
        (bound.case_analysis_revision, current.case_analysis_revision, "Case Analysis artifact revision changed"),
        (bound.case_analysis_digest, current.case_analysis_digest, "Case Analysis content changed"),
        (bound.planning_snapshot_id, current.planning_snapshot_id, "Pericial Planning snapshot identity changed"),
        (bound.planning_revision, current.planning_revision, "Pericial Planning artifact revision changed"),
        (bound.planning_digest, current.planning_digest, "Pericial Planning content changed"),
        (bound.inspection_session_id, current.inspection_session_id, "Inspection Session identity changed"),
        (bound.inspection_revision, current.inspection_revision, "Inspection Session artifact revision changed"),
        (bound.inspection_digest, current.inspection_digest, "Inspection Session content changed"),
        (bound.source_revision, current.source_revision, "upstream source revision changed"),
    )
    reasons = tuple(reason for actual, expected, reason in comparisons if actual != expected)
    return replace(
        snapshot,
        upstream_stale=bool(reasons),
        upstream_stale_reasons=reasons,
    )


def _dependencies(authorities: _Authorities) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "artifact_kind": record.artifact_kind,
            "artifact_id": record.artifact_id,
            "revision": record.revision,
            "checksum_sha256": record.checksum_sha256,
        }
        for record in authorities.records
    )


@dataclass(frozen=True, slots=True)
class SaveConstructionDefectAnalysis:
    revisions: object
    get_latest_revision: object
    get_process_case: object
    get_case_analysis: object
    get_planning: object
    get_inspection: object
    authority_guard: object
    clock: object
    ids: object

    def execute(
        self,
        workspace_id,
        snapshot: ConstructionDefectAnalysisSnapshot,
        expected_revision: int | None,
        *,
        mutation_authority: str,
    ):
        if (
            type(snapshot) is not ConstructionDefectAnalysisSnapshot
            or snapshot.workspace_id != str(workspace_id)
        ):
            raise ValueError("Construction Defect Analysis workspace mismatch")
        if snapshot.upstream_stale:
            raise ValueError("stale Construction Defect Analysis cannot be persisted")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("Construction Defect Analysis expected revision is invalid")
        if expected_revision is None:
            if mutation_authority != "START" or snapshot.reviews:
                raise ValueError(
                    "initial Construction Defect Analysis requires the start command"
                )
        elif mutation_authority != "PROFESSIONAL":
            raise ValueError(
                "Construction Defect Analysis mutation requires professional authority"
            )
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError(
                "Construction Defect Analysis authority guard is unavailable"
            )
        with self.authority_guard():
            if expected_revision is not None:
                predecessor_record = self.get_latest_revision.execute(
                    workspace_id,
                    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
                    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
                )
                if predecessor_record.revision != expected_revision:
                    raise RepositoryConflict(
                        "expected Construction Defect Analysis revision is not latest"
                    )
                predecessor = validated_construction_defect_analysis_from_mapping(
                    thaw_payload(predecessor_record.payload)
                )
                immutable = (
                    "schema_version",
                    "snapshot_id",
                    "workspace_id",
                    "source_snapshot",
                    "observation_contexts",
                    "identity_links",
                    "analysis_final",
                    "gate",
                )
                if any(
                    getattr(snapshot, name) != getattr(predecessor, name)
                    for name in immutable
                ):
                    raise ValueError(
                        "Construction Defect Analysis immutable proposal changed"
                    )
                if (
                    snapshot.reviews[: len(predecessor.reviews)]
                    != predecessor.reviews
                    or len(snapshot.reviews) != len(predecessor.reviews) + 1
                ):
                    raise ValueError("pathology review history cannot be rewritten")
            authorities = _authorities(
                workspace_id,
                get_latest_revision=self.get_latest_revision,
                get_process_case=self.get_process_case,
                get_case_analysis=self.get_case_analysis,
                get_planning=self.get_planning,
                get_inspection=self.get_inspection,
            )
            if _reconcile(snapshot, current=_binding(workspace_id, authorities)).upstream_stale:
                raise ValueError("Construction Defect Analysis upstream authority is stale")
            now = self.clock.now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("Construction Defect Analysis clock requires timezone")
            return self.revisions.append_if_latest(
                workspace_id=workspace_id,
                artifact_kind=CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
                artifact_id=CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()),
                created_at=now.isoformat(),
                payload=construction_defect_analysis_to_validated_mapping(snapshot),
                expected_revision=expected_revision,
                expected_dependencies=_dependencies(authorities),
            )


@dataclass(frozen=True, slots=True)
class GetConstructionDefectAnalysis:
    get_latest_revision: object
    get_process_case: object
    get_case_analysis: object
    get_planning: object
    get_inspection: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id,
            CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
            CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
        )
        snapshot = validated_construction_defect_analysis_from_mapping(
            thaw_payload(record.payload)
        )
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Construction Defect Analysis workspace mismatch")
        authorities = _authorities(
            workspace_id,
            get_latest_revision=self.get_latest_revision,
            get_process_case=self.get_process_case,
            get_case_analysis=self.get_case_analysis,
            get_planning=self.get_planning,
            get_inspection=self.get_inspection,
        )
        return record, _reconcile(
            snapshot, current=_binding(workspace_id, authorities)
        )


@dataclass(frozen=True, slots=True)
class StartConstructionDefectAnalysis:
    get_latest_revision: object
    get_process_case: object
    get_case_analysis: object
    get_planning: object
    get_inspection: object
    runner: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, observation_contexts: tuple):
        if not callable(getattr(self.runner, "execute", None)):
            raise RepositoryIntegrityError(
                "Construction Defect Analysis runner is unavailable"
            )
        process_snapshot = self.get_process_case.execute(workspace_id)
        case_record, case_analysis = self.get_case_analysis.execute(workspace_id)
        planning_record, planning = self.get_planning.execute(workspace_id)
        inspection_record, inspection = self.get_inspection.execute(workspace_id)
        if (
            process_snapshot.revision is None
            or case_analysis.source_inventory_stale
            or planning.upstream_stale
            or inspection.upstream_stale
        ):
            raise ValueError("stale upstream cannot start construction-defect analysis")
        proposal = self.runner.execute(
            process_case=process_snapshot.data,
            case_analysis=case_analysis,
            planning=planning,
            inspection=inspection,
            observation_contexts=observation_contexts,
        )
        if type(proposal) is not ConstructionDefectAnalysisProposal:
            raise RepositoryIntegrityError(
                "Construction Defect Analysis runner returned an invalid proposal"
            )
        process_record = self.get_latest_revision.execute(
            workspace_id, "PROCESS_CASE", "PROCESS_CASE"
        )
        authorities = _Authorities(
            process_record,
            process_snapshot.data,
            case_record,
            case_analysis,
            planning_record,
            planning,
            inspection_record,
            inspection,
        )
        snapshot = ConstructionDefectAnalysisSnapshot(
            schema_version="1.0.0",
            snapshot_id=(
                f"CONSTRUCTION-DEFECT-ANALYSIS-{self.ids.new_uuid().hex.upper()}"
            ),
            workspace_id=str(workspace_id),
            source_snapshot=_binding(workspace_id, authorities),
            observation_contexts=proposal.observation_contexts,
            identity_links=proposal.identity_links,
            analysis_final=proposal.analysis_final,
            gate=proposal.gate,
            reviews=(),
            upstream_stale=False,
            upstream_stale_reasons=(),
        )
        record = self.save_snapshot.execute(
            workspace_id, snapshot, None, mutation_authority="START"
        )
        return record, snapshot


@dataclass(frozen=True, slots=True)
class ReviewPathology:
    get_snapshot: object
    save_snapshot: object
    get_inspection: object
    clock: object
    ids: object

    def execute(
        self,
        workspace_id,
        *,
        pat_id: str,
        action: str,
        professional_id: str,
        reason: str,
        expected_revision: int,
    ):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict(
                "expected Construction Defect Analysis revision is not latest"
            )
        if snapshot.upstream_stale:
            raise RepositoryConflict("Construction Defect Analysis upstream is stale")
        if snapshot.gate == "BLOQUEADO_PARA_REDACAO":
            raise ValueError("blocked PAT cannot receive professional approval")
        _inspection_record, inspection = self.get_inspection.execute(workspace_id)
        claimed = professional_id.strip() if type(professional_id) is str else ""
        if not claimed or claimed != inspection.responsible_professional:
            raise ValueError("professional is not the bound inspection authority")
        reason = reason.strip() if type(reason) is str else ""
        if not reason:
            raise ValueError("pathology review reason is required")
        try:
            review_action = PathologyReviewAction(action)
        except (TypeError, ValueError) as exc:
            raise ValueError("pathology review action is invalid") from exc
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("pathology review clock requires timezone")
        latest = next(
            (item for item in reversed(snapshot.reviews) if item.pat_id == pat_id),
            None,
        )
        amended = replace(
            snapshot,
            reviews=(
                *snapshot.reviews,
                PathologyReview(
                    review_id=f"PAT-REVIEW-{self.ids.new_uuid().hex.upper()}",
                    pat_id=pat_id,
                    action=review_action,
                    professional_id=inspection.responsible_professional,
                    reason=reason,
                    reviewed_at=now.isoformat(),
                    supersedes_review_id=(latest.review_id if latest is not None else None),
                ),
            ),
        )
        saved = self.save_snapshot.execute(
            workspace_id,
            amended,
            expected_revision,
            mutation_authority="PROFESSIONAL",
        )
        return saved, amended
