"""Application authority for exact, append-only delivery revisions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..case_analysis import CaseAnalysisSnapshot, case_analysis_to_mapping
from ..delivery_foundation import (
    DELIVERY_SNAPSHOT_ARTIFACT_ID,
    DELIVERY_SNAPSHOT_ARTIFACT_KIND,
    DeliveryAction,
    DeliveryBinding,
    DeliveryDecision,
    DeliveryArtifact,
    DeliveryFormat,
    DeliveryPackage,
    DeliveryRole,
    DeliverySnapshot,
    DeliveryState,
    delivery_snapshot_from_mapping,
    delivery_snapshot_to_mapping,
)
from ..delivery_renderer import DELIVERY_RENDERING_VERSION, render_final_pdf_candidate, render_word_candidate, validate_final_artifact, validate_supporting_artifact, verify_reopened_artifact
from ..report_template import TemplateBindingManifest, template_binding_manifest_from_mapping
from ..pericial_planning import PlanningSnapshot, pericial_planning_to_mapping
from ..report_foundation import ReportSnapshot, ReportState, report_snapshot_to_mapping
from ..technical_findings import TechnicalSnapshot, technical_snapshot_to_mapping
from ..vistoria import InspectionSession, inspection_session_to_mapping
from .models import thaw_payload
from .models import PrivateContentId, PrivateContentOrigin
from .ports import RepositoryConflict, RepositoryError, RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "delivery-snapshot-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker())


def validated_template_binding_manifest_from_mapping(value: object) -> TemplateBindingManifest:
    """Keep transport dependent on application validation, not the domain parser."""
    return template_binding_manifest_from_mapping(value)


def _digest(mapping: object) -> str:
    encoded = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validated_delivery_snapshot_from_mapping(value: object) -> DeliverySnapshot:
    try:
        _VALIDATOR.validate(value)
        return delivery_snapshot_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Delivery Snapshot payload") from exc


def delivery_snapshot_to_validated_mapping(snapshot: DeliverySnapshot) -> dict:
    mapping = delivery_snapshot_to_mapping(snapshot)
    _VALIDATOR.validate(mapping)
    return mapping


def build_delivery_binding(
    *, workspace_id: object,
    case_record: object, case: CaseAnalysisSnapshot,
    planning_record: object, planning: PlanningSnapshot,
    inspection_record: object, inspection: InspectionSession,
    technical_record: object, technical: TechnicalSnapshot,
    report_record: object, report: ReportSnapshot,
) -> DeliveryBinding:
    expected_workspace = str(workspace_id)
    values = (case, planning, inspection, technical, report)
    if any(getattr(item, "workspace_id", None) != expected_workspace for item in values):
        raise ValueError("Delivery Snapshot upstream workspace mismatch")
    if case.source_inventory_stale or planning.upstream_stale or inspection.upstream_stale or technical.upstream_stale or report.upstream_stale:
        raise ValueError("stale upstream cannot authorize Delivery Snapshot")
    if report.state is not ReportState.APPROVED or not report.review_decisions or report.review_decisions[-1].action.value != "APPROVE":
        raise ValueError("Delivery Snapshot requires an approved Report Snapshot")
    report_source = report.source_snapshot
    if (
        report_source.case_analysis_snapshot_id != case.snapshot_id
        or report_source.case_analysis_revision != case_record.revision
        or report_source.inspection_session_id != inspection.session_id
        or report_source.inspection_session_revision != inspection_record.revision
        or report_source.technical_snapshot_id != technical.snapshot_id
        or report_source.technical_snapshot_revision != technical_record.revision
    ):
        raise ValueError("approved Report Snapshot no longer binds current authorities")
    inventory = tuple((item.document_id, item.source_sha256) for item in case.documents)
    approval = report.review_decisions[-1]
    return DeliveryBinding(
        workspace_id=expected_workspace,
        source_snapshot_id=f"SOURCE-INVENTORY-{case.source_revision}",
        source_revision=case.source_revision,
        source_digest=_digest(inventory),
        case_analysis_snapshot_id=case.snapshot_id,
        case_analysis_revision=case_record.revision,
        case_analysis_digest=_digest(case_analysis_to_mapping(case)),
        planning_snapshot_id=planning.snapshot_id,
        planning_revision=planning_record.revision,
        planning_digest=_digest(pericial_planning_to_mapping(planning)),
        inspection_snapshot_id=inspection.session_id,
        inspection_revision=inspection_record.revision,
        inspection_digest=_digest(inspection_session_to_mapping(inspection)),
        technical_snapshot_id=technical.snapshot_id,
        technical_revision=technical_record.revision,
        technical_digest=_digest(technical_snapshot_to_mapping(technical)),
        report_snapshot_id=report.report_id,
        report_revision=report_record.revision,
        report_digest=_digest(report_snapshot_to_mapping(report)),
        report_approval_id=approval.review_id,
        report_approval_digest=_digest(asdict(approval)),
        professional_id=report.expert_profile.profile_id,
    )


def reconcile_delivery(snapshot: DeliverySnapshot, current: DeliveryBinding) -> DeliverySnapshot:
    reasons = tuple(
        f"{field.upper()}_CHANGED"
        for field in (item.name for item in fields(DeliveryBinding))
        if getattr(snapshot.binding, field) != getattr(current, field)
    )
    if not reasons:
        return snapshot
    origin = snapshot.state if snapshot.state is not DeliveryState.STALE else snapshot.stale_origin_state
    return replace(snapshot, state=DeliveryState.STALE, stale_reasons=reasons, stale_origin_state=origin)


def mark_delivery_authority_unavailable(snapshot: DeliverySnapshot) -> DeliverySnapshot:
    if snapshot.state is DeliveryState.STALE:
        return snapshot
    return replace(
        snapshot, state=DeliveryState.STALE,
        stale_reasons=("UPSTREAM_AUTHORITY_UNAVAILABLE",), stale_origin_state=snapshot.state,
    )


def _current(workspace_id: object, services: tuple[object, ...]):
    records_and_values = tuple(service.execute(workspace_id) for service in services)
    return (*records_and_values, build_delivery_binding(
        workspace_id=workspace_id,
        case_record=records_and_values[0][0], case=records_and_values[0][1],
        planning_record=records_and_values[1][0], planning=records_and_values[1][1],
        inspection_record=records_and_values[2][0], inspection=records_and_values[2][1],
        technical_record=records_and_values[3][0], technical=records_and_values[3][1],
        report_record=records_and_values[4][0], report=records_and_values[4][1],
    ))


@dataclass(frozen=True, slots=True)
class SaveDeliverySnapshot:
    revisions: object
    get_latest_revision: object
    get_case_analysis: object
    get_planning: object
    get_inspection: object
    get_technical: object
    get_report: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, snapshot: DeliverySnapshot, expected_revision: int | None, *, allow_transition: bool = False, allow_initial_create: bool = False, allow_reissue: bool = False, allow_artifacts: bool = False):
        if type(snapshot) is not DeliverySnapshot or snapshot.workspace_id != str(workspace_id) or snapshot.state is DeliveryState.STALE:
            raise ValueError("Delivery Snapshot workspace or stale state is invalid")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("Delivery Snapshot expected revision is invalid")
        if expected_revision is None and (not allow_initial_create or snapshot.state is not DeliveryState.DRAFT):
            raise ValueError("initial Delivery Snapshot requires the canonical start command")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Delivery Snapshot authority guard is unavailable")
        with self.authority_guard():
            current = _current(workspace_id, (self.get_case_analysis, self.get_planning, self.get_inspection, self.get_technical, self.get_report))
            if reconcile_delivery(snapshot, current[-1]).state is DeliveryState.STALE:
                raise ValueError("Delivery Snapshot upstream authority is stale")
            if expected_revision is not None:
                predecessor_record = self.get_latest_revision.execute(workspace_id, DELIVERY_SNAPSHOT_ARTIFACT_KIND, DELIVERY_SNAPSHOT_ARTIFACT_ID)
                if predecessor_record.revision != expected_revision:
                    raise RepositoryConflict("expected Delivery Snapshot revision is not latest")
                predecessor = validated_delivery_snapshot_from_mapping(thaw_payload(predecessor_record.payload))
                if snapshot.revision != predecessor.revision + 1:
                    raise ValueError("Delivery Snapshot revision sequence is invalid")
                if allow_reissue:
                    valid_predecessor = predecessor.state in {DeliveryState.DELIVERED, DeliveryState.SUPERSEDED} or (predecessor.state is DeliveryState.STALE and predecessor.stale_origin_state is DeliveryState.DELIVERED)
                    if not valid_predecessor or snapshot.state is not DeliveryState.DRAFT or snapshot.supersedes_delivery_id != predecessor.delivery_id or snapshot.decisions or snapshot.artifacts:
                        raise ValueError("Delivery reissue predecessor is invalid")
                elif snapshot.delivery_id != predecessor.delivery_id or snapshot.supersedes_delivery_id != predecessor.supersedes_delivery_id:
                    raise ValueError("Delivery Snapshot immutable identity changed")
                if not allow_transition and not allow_reissue and snapshot.decisions != predecessor.decisions:
                    raise ValueError("Delivery decisions require an explicit professional command")
                if not allow_artifacts and not allow_reissue and (snapshot.artifacts != predecessor.artifacts or snapshot.package != predecessor.package):
                    raise ValueError("Delivery artifacts require the protected render command")
                superseding = allow_transition and predecessor.state is DeliveryState.DELIVERED and snapshot.state is DeliveryState.SUPERSEDED
                if predecessor.state in {DeliveryState.DELIVERED, DeliveryState.SUPERSEDED} and not allow_reissue and not superseding:
                    raise ValueError("delivered revisions are immutable; create a reissue")
            now = self.clock.now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("Delivery Snapshot clock requires timezone")
            dependencies = tuple({"artifact_kind": record.artifact_kind, "artifact_id": record.artifact_id, "revision": record.revision, "checksum_sha256": record.checksum_sha256} for record, _ in current[:-1])
            return self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=DELIVERY_SNAPSHOT_ARTIFACT_KIND,
                artifact_id=DELIVERY_SNAPSHOT_ARTIFACT_ID, revision_id=str(self.ids.new_uuid()),
                created_at=now.isoformat(), payload=delivery_snapshot_to_mapping(snapshot),
                expected_revision=expected_revision, expected_dependencies=dependencies,
            )


@dataclass(frozen=True, slots=True)
class GetDeliverySnapshot:
    get_latest_revision: object
    get_case_analysis: object
    get_planning: object
    get_inspection: object
    get_technical: object
    get_report: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, DELIVERY_SNAPSHOT_ARTIFACT_KIND, DELIVERY_SNAPSHOT_ARTIFACT_ID)
        snapshot = validated_delivery_snapshot_from_mapping(thaw_payload(record.payload))
        try:
            current = _current(workspace_id, (self.get_case_analysis, self.get_planning, self.get_inspection, self.get_technical, self.get_report))
        except (ValueError, RepositoryError):
            return record, mark_delivery_authority_unavailable(snapshot)
        return record, reconcile_delivery(snapshot, current[-1])


@dataclass(frozen=True, slots=True)
class GetDeliveryHistory:
    list_revisions: object

    def execute(self, workspace_id):
        records = self.list_revisions.execute(workspace_id, DELIVERY_SNAPSHOT_ARTIFACT_KIND, DELIVERY_SNAPSHOT_ARTIFACT_ID)
        return tuple((record, validated_delivery_snapshot_from_mapping(thaw_payload(record.payload))) for record in records)


@dataclass(frozen=True, slots=True)
class StartDeliverySnapshot:
    get_case_analysis: object
    get_planning: object
    get_inspection: object
    get_technical: object
    get_report: object
    get_private_content: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, template_content_id: PrivateContentId, manifest: TemplateBindingManifest, supersedes_delivery_id: str | None = None):
        current = _current(workspace_id, (self.get_case_analysis, self.get_planning, self.get_inspection, self.get_technical, self.get_report))
        template = self.get_private_content.execute(workspace_id, template_content_id)
        if type(manifest) is not TemplateBindingManifest:
            raise ValueError("Delivery template manifest is invalid")
        snapshot = DeliverySnapshot(
            schema_version="1.0.0", delivery_id=f"DELIVERY-{str(self.ids.new_uuid()).upper()}", revision=1,
            workspace_id=str(workspace_id), binding=current[-1], template_id=manifest.template_id,
            template_content_id=str(template_content_id), template_format=DeliveryFormat(manifest.output_kind), template_revision=1,
            template_digest=template.metadata.checksum_sha256,
            rendering_version=DELIVERY_RENDERING_VERSION, artifacts=(), package=DeliveryPackage("1.0.0", ()),
            decisions=(), state=DeliveryState.DRAFT, stale_reasons=(), stale_origin_state=None, supersedes_delivery_id=supersedes_delivery_id,
        )
        record = self.save_snapshot.execute(workspace_id, snapshot, None, allow_initial_create=True)
        return record, snapshot


@dataclass(frozen=True, slots=True)
class ReviewDeliverySnapshot:
    get_snapshot: object
    save_snapshot: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, action: str, professional_id: str, reason: str, expected_revision: int, integrity_verified: bool = False):
        try:
            requested = DeliveryAction(action)
        except ValueError as exc:
            raise ValueError("Delivery review action is invalid") from exc
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.state is DeliveryState.STALE:
            raise RepositoryConflict("expected Delivery Snapshot revision is not current")
        if professional_id != snapshot.binding.professional_id:
            raise ValueError("Delivery professional authority is invalid")
        if requested in {DeliveryAction.FINALIZE, DeliveryAction.DELIVER} and integrity_verified is not True:
            raise ValueError("Delivery final transition requires reopened artifact verification")
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None or type(reason) is not str or not reason.strip():
            raise ValueError("Delivery professional decision is invalid")
        previous = snapshot.decisions[-1].decision_id if snapshot.decisions else None
        decision = DeliveryDecision(str(self.ids.new_uuid()), requested, professional_id, reason.strip(), now.isoformat(), previous)
        target = {
            DeliveryAction.MARK_READY_FOR_REVIEW: DeliveryState.READY_FOR_REVIEW,
            DeliveryAction.APPROVE: DeliveryState.APPROVED,
            DeliveryAction.FINALIZE: DeliveryState.FINALIZED,
            DeliveryAction.DELIVER: DeliveryState.DELIVERED,
            DeliveryAction.SUPERSEDE: DeliveryState.SUPERSEDED,
        }[requested]
        reviewed = replace(snapshot, revision=snapshot.revision + 1, decisions=(*snapshot.decisions, decision), state=target)
        saved = self.save_snapshot.execute(workspace_id, reviewed, expected_revision, allow_transition=True)
        return saved, reviewed


@dataclass(frozen=True, slots=True)
class ReissueDeliverySnapshot:
    get_snapshot: object
    save_snapshot: object
    get_case_analysis: object
    get_planning: object
    get_inspection: object
    get_technical: object
    get_report: object
    get_private_content: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, template_content_id: PrivateContentId, manifest: TemplateBindingManifest):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        valid_predecessor = predecessor.state is DeliveryState.SUPERSEDED or (predecessor.state is DeliveryState.STALE and predecessor.stale_origin_state is DeliveryState.DELIVERED)
        if record.revision != expected_revision or not valid_predecessor:
            raise RepositoryConflict("Delivery reissue requires the latest superseded revision")
        current = _current(workspace_id, (self.get_case_analysis, self.get_planning, self.get_inspection, self.get_technical, self.get_report))
        template = self.get_private_content.execute(workspace_id, template_content_id)
        if type(manifest) is not TemplateBindingManifest:
            raise ValueError("Delivery template manifest is invalid")
        reissue = DeliverySnapshot(
            schema_version="1.0.0", delivery_id=f"DELIVERY-{str(self.ids.new_uuid()).upper()}",
            revision=predecessor.revision + 1, workspace_id=str(workspace_id), binding=current[-1],
            template_id=manifest.template_id, template_content_id=str(template_content_id),
            template_format=DeliveryFormat(manifest.output_kind), template_revision=1, template_digest=template.metadata.checksum_sha256,
            rendering_version=DELIVERY_RENDERING_VERSION, artifacts=(), package=DeliveryPackage("1.0.0", ()),
            decisions=(), state=DeliveryState.DRAFT, stale_reasons=(), stale_origin_state=None, supersedes_delivery_id=predecessor.delivery_id,
        )
        saved = self.save_snapshot.execute(workspace_id, reissue, expected_revision, allow_reissue=True)
        return saved, reissue


@dataclass(frozen=True, slots=True)
class RenderDeliveryPackage:
    get_snapshot: object
    get_report: object
    get_private_content: object
    store_private_content: object
    save_snapshot: object
    ids: object
    pdf_converter: object

    def execute(self, workspace_id, *, manifest: TemplateBindingManifest, expected_revision: int):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.state is not DeliveryState.DRAFT:
            raise RepositoryConflict("Delivery render requires the latest draft revision")
        if snapshot.rendering_version != DELIVERY_RENDERING_VERSION:
            raise ValueError("Delivery renderer provenance mismatch")
        if type(manifest) is not TemplateBindingManifest or manifest.template_id != snapshot.template_id:
            raise ValueError("Delivery template manifest identity mismatch")
        template = self.get_private_content.execute(workspace_id, PrivateContentId.parse(snapshot.template_content_id))
        if template.metadata.checksum_sha256 != snapshot.template_digest:
            raise ValueError("Delivery template bytes diverge from bound identity")
        _, report = self.get_report.execute(workspace_id)
        if type(report) is not ReportSnapshot or _digest(report_snapshot_to_mapping(report)) != snapshot.binding.report_digest:
            raise ValueError("Delivery report bytes diverge from bound authority")
        word = render_word_candidate(template_bytes=template.content, report=report, manifest=manifest).output_bytes
        pdf = render_final_pdf_candidate(
            word_content=word, word_format=manifest.output_kind, converter=self.pdf_converter,
        )
        word_digest, word_size, word_media = validate_final_artifact(word, manifest.output_kind)
        pdf_digest, pdf_size, pdf_media = validate_final_artifact(pdf, "PDF")
        stem = f"laudo-{snapshot.delivery_id.lower()}-r{snapshot.revision + 1}"
        word_name = f"{stem}.{manifest.output_kind.lower()}"
        pdf_name = f"{stem}.pdf"
        word_metadata = self.store_private_content.execute(
            workspace_id=workspace_id, original_filename=word_name, content=word,
            media_type=word_media, origin=PrivateContentOrigin.LOCAL_IMPORT,
        )
        pdf_metadata = self.store_private_content.execute(
            workspace_id=workspace_id, original_filename=pdf_name, content=pdf,
            media_type=pdf_media, origin=PrivateContentOrigin.LOCAL_IMPORT,
        )
        if (word_metadata.byte_size, word_metadata.checksum_sha256) != (word_size, word_digest) or (pdf_metadata.byte_size, pdf_metadata.checksum_sha256) != (pdf_size, pdf_digest):
            raise RepositoryIntegrityError("private delivery storage changed rendered bytes")
        artifacts = (
            DeliveryArtifact(
                artifact_id=f"ARTIFACT-{str(self.ids.new_uuid()).upper()}", role=DeliveryRole.MAIN_REPORT,
                format=DeliveryFormat(manifest.output_kind), filename=word_name,
                content_id=str(word_metadata.content_id), media_type=word_media,
                byte_size=word_size, checksum_sha256=word_digest,
            ),
            DeliveryArtifact(
                artifact_id=f"ARTIFACT-{str(self.ids.new_uuid()).upper()}", role=DeliveryRole.MAIN_REPORT,
                format=DeliveryFormat.PDF, filename=pdf_name, content_id=str(pdf_metadata.content_id),
                media_type=pdf_media, byte_size=pdf_size, checksum_sha256=pdf_digest,
            ),
            *(item for item in snapshot.artifacts if item.role is not DeliveryRole.MAIN_REPORT),
        )
        rendered = replace(
            snapshot, revision=snapshot.revision + 1, artifacts=artifacts,
            package=DeliveryPackage("1.0.0", tuple(item.artifact_id for item in artifacts)),
        )
        saved = self.save_snapshot.execute(workspace_id, rendered, expected_revision, allow_artifacts=True)
        return saved, rendered


@dataclass(frozen=True, slots=True)
class AttachDeliveryPackageArtifact:
    get_snapshot: object
    get_private_content: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, content_id: PrivateContentId, role: str):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or snapshot.state is not DeliveryState.DRAFT:
            raise RepositoryConflict("Delivery package attachment requires the latest draft")
        try:
            package_role = DeliveryRole(role)
        except ValueError as exc:
            raise ValueError("Delivery package role is invalid") from exc
        if package_role is DeliveryRole.MAIN_REPORT:
            raise ValueError("main report artifacts require protected rendering")
        content = self.get_private_content.execute(workspace_id, content_id)
        media = content.metadata.media_type or "application/octet-stream"
        known = {
            "application/pdf": DeliveryFormat.PDF,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DeliveryFormat.DOCX,
            "application/vnd.ms-word.document.macroenabled.12": DeliveryFormat.DOCM,
            "application/vnd.ms-word.document.macroEnabled.12": DeliveryFormat.DOCM,
        }
        output_format = known.get(media, DeliveryFormat.OTHER)
        if output_format is DeliveryFormat.OTHER:
            validate_supporting_artifact(content.content, media)
        else:
            validate_final_artifact(content.content, output_format.value)
        artifact = DeliveryArtifact(
            artifact_id=f"ARTIFACT-{str(self.ids.new_uuid()).upper()}", role=package_role,
            format=output_format, filename=content.metadata.original_filename,
            content_id=str(content_id), media_type=media, byte_size=content.metadata.byte_size,
            checksum_sha256=content.metadata.checksum_sha256,
        )
        artifacts = (*snapshot.artifacts, artifact)
        attached = replace(
            snapshot, revision=snapshot.revision + 1, artifacts=artifacts,
            package=DeliveryPackage("1.0.0", tuple(item.artifact_id for item in artifacts)),
        )
        saved = self.save_snapshot.execute(workspace_id, attached, expected_revision, allow_artifacts=True)
        return saved, attached


@dataclass(frozen=True, slots=True)
class VerifyDeliveryPackage:
    get_snapshot: object
    get_private_content: object

    def execute(self, workspace_id, *, expected_revision: int):
        record, snapshot = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision or not snapshot.artifacts:
            raise RepositoryConflict("Delivery verification requires the latest rendered revision")
        for artifact in snapshot.artifacts:
            content = self.get_private_content.execute(workspace_id, PrivateContentId.parse(artifact.content_id))
            if content.metadata.original_filename != artifact.filename or content.metadata.media_type != artifact.media_type:
                raise RepositoryIntegrityError("reopened private artifact metadata diverges")
            if artifact.format is DeliveryFormat.OTHER:
                digest, size, media = validate_supporting_artifact(content.content, artifact.media_type)
                if size != artifact.byte_size or digest != artifact.checksum_sha256 or media != artifact.media_type:
                    raise RepositoryIntegrityError("reopened supporting artifact bytes diverge")
            else:
                verify_reopened_artifact(
                    content=content.content, output_format=artifact.format.value,
                    expected_size=artifact.byte_size, expected_sha256=artifact.checksum_sha256,
                )
        return record, snapshot


@dataclass(frozen=True, slots=True)
class FinalizeDeliverySnapshot:
    verify_package: object
    review_snapshot: object

    def execute(self, workspace_id, *, professional_id: str, reason: str, expected_revision: int):
        self.verify_package.execute(workspace_id, expected_revision=expected_revision)
        return self.review_snapshot.execute(
            workspace_id, action=DeliveryAction.FINALIZE.value, professional_id=professional_id,
            reason=reason, expected_revision=expected_revision, integrity_verified=True,
        )


@dataclass(frozen=True, slots=True)
class DeliverDeliverySnapshot:
    verify_package: object
    review_snapshot: object

    def execute(self, workspace_id, *, professional_id: str, reason: str, expected_revision: int):
        self.verify_package.execute(workspace_id, expected_revision=expected_revision)
        return self.review_snapshot.execute(
            workspace_id, action=DeliveryAction.DELIVER.value, professional_id=professional_id,
            reason=reason, expected_revision=expected_revision, integrity_verified=True,
        )
