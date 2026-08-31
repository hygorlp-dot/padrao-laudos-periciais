from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.delivery_foundation import (
    DeliveryAction,
    DeliveryArtifact,
    DeliveryBinding,
    DeliveryDecision,
    DeliveryFormat,
    DeliveryPackage,
    DeliveryRole,
    DeliverySnapshot,
    DeliveryState,
    delivery_snapshot_from_mapping,
    delivery_snapshot_to_mapping,
)
from scripts.backend_contract.delivery_renderer import (
    validate_final_artifact,
    verify_reopened_artifact,
)
from scripts.backend_contract.application.delivery_foundation import (
    ReviewDeliverySnapshot,
    build_delivery_binding,
    reconcile_delivery,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.pericial_planning import pericial_planning_from_mapping
from scripts.backend_contract.report_foundation import report_snapshot_from_mapping
from scripts.backend_contract.technical_findings import technical_snapshot_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping


SHA_A = "a" * 64
SHA_B = "b" * 64


def binding() -> DeliveryBinding:
    return DeliveryBinding(
        workspace_id="workspace-1",
        source_snapshot_id="SOURCE-1", source_revision=1, source_digest=SHA_A,
        case_analysis_snapshot_id="CASE-1", case_analysis_revision=2, case_analysis_digest=SHA_A,
        planning_snapshot_id="PLAN-1", planning_revision=3, planning_digest=SHA_A,
        inspection_snapshot_id="INSPECTION-1", inspection_revision=4, inspection_digest=SHA_A,
        technical_snapshot_id="TECHNICAL-1", technical_revision=5, technical_digest=SHA_A,
        report_snapshot_id="REPORT-1", report_revision=6, report_digest=SHA_A,
        report_approval_id="REPORT-APPROVAL-1", report_approval_digest=SHA_A,
        professional_id="EXPERT-1",
    )


def artifact() -> DeliveryArtifact:
    return DeliveryArtifact(
        artifact_id="ARTIFACT-1", role=DeliveryRole.MAIN_REPORT,
        format=DeliveryFormat.DOCX, filename="laudo-r1.docx",
        content_id="11111111-1111-4111-8111-111111111111",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        byte_size=123, checksum_sha256=SHA_B,
    )


def snapshot(*, decisions: tuple[DeliveryDecision, ...] = (), artifacts: tuple[DeliveryArtifact, ...] = (), state: DeliveryState = DeliveryState.DRAFT) -> DeliverySnapshot:
    return DeliverySnapshot(
        schema_version="1.0.0", delivery_id="DELIVERY-1", revision=1,
        workspace_id="workspace-1", binding=binding(),
        template_id="TEMPLATE-1", template_content_id="22222222-2222-4222-8222-222222222222",
        template_format=DeliveryFormat.DOCX, template_revision=1, template_digest=SHA_A,
        rendering_version="delivery-renderer/1", artifacts=artifacts,
        package=DeliveryPackage(manifest_version="1.0.0", artifact_ids=tuple(item.artifact_id for item in artifacts)),
        decisions=decisions, state=state, stale_reasons=(), stale_origin_state=None, supersedes_delivery_id=None,
    )


def decision(action: DeliveryAction, *, index: int, previous: str | None) -> DeliveryDecision:
    return DeliveryDecision(
        decision_id=f"DECISION-{index}", action=action, professional_id="EXPERT-1",
        reason="Decisão profissional explícita.", timestamp=f"2026-08-31T12:0{index}:00+00:00",
        supersedes_decision_id=previous,
    )


def test_delivery_snapshot_round_trip_is_strict_and_exactly_bound() -> None:
    value = snapshot()
    assert delivery_snapshot_from_mapping(delivery_snapshot_to_mapping(value)) == value
    assert value.binding.planning_snapshot_id == "PLAN-1"
    payload = delivery_snapshot_to_mapping(value)
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="fields"):
        delivery_snapshot_from_mapping(payload)


def test_canonical_synthetic_fixture_matches_strict_schema() -> None:
    root = Path(__file__).parents[1]
    payload = json.loads((root / "tests/fixtures/delivery-snapshot-v1.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "schemas/delivery-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    assert delivery_snapshot_to_mapping(delivery_snapshot_from_mapping(payload)) == payload


def test_lifecycle_requires_linear_explicit_professional_decisions() -> None:
    ready = decision(DeliveryAction.MARK_READY_FOR_REVIEW, index=1, previous=None)
    approved = decision(DeliveryAction.APPROVE, index=2, previous=ready.decision_id)
    finalized = decision(DeliveryAction.FINALIZE, index=3, previous=approved.decision_id)
    delivered = decision(DeliveryAction.DELIVER, index=4, previous=finalized.decision_id)
    value = snapshot(decisions=(ready, approved, finalized, delivered), artifacts=(artifact(),), state=DeliveryState.DELIVERED)
    assert value.state is DeliveryState.DELIVERED
    with pytest.raises(ValueError, match="transition"):
        snapshot(decisions=(delivered,), artifacts=(artifact(),), state=DeliveryState.DELIVERED)


def test_finalization_requires_hashed_main_artifact_and_exact_manifest() -> None:
    ready = decision(DeliveryAction.MARK_READY_FOR_REVIEW, index=1, previous=None)
    approved = decision(DeliveryAction.APPROVE, index=2, previous=ready.decision_id)
    finalized = decision(DeliveryAction.FINALIZE, index=3, previous=approved.decision_id)
    with pytest.raises(ValueError, match="artifact"):
        snapshot(decisions=(ready, approved, finalized), state=DeliveryState.FINALIZED)
    with pytest.raises(ValueError, match="manifest"):
        replace(
            snapshot(decisions=(ready, approved, finalized), artifacts=(artifact(),), state=DeliveryState.FINALIZED),
            package=DeliveryPackage("1.0.0", ()),
        )


def test_stale_overrides_final_state_and_cannot_be_silently_cleared() -> None:
    value = replace(snapshot(), state=DeliveryState.STALE, stale_reasons=("REPORT_DIGEST_CHANGED",), stale_origin_state=DeliveryState.DRAFT)
    assert value.state is DeliveryState.STALE
    with pytest.raises(ValueError, match="stale"):
        replace(value, state=DeliveryState.DRAFT)


def test_artifact_filename_and_content_identity_are_unique() -> None:
    duplicate = replace(artifact(), artifact_id="ARTIFACT-2")
    with pytest.raises(ValueError, match="unique"):
        snapshot(artifacts=(artifact(), duplicate))


def test_application_binding_consumes_current_approved_authorities_and_reconciles_change() -> None:
    root = Path(__file__).parents[1] / "tests/fixtures"
    def load(name: str) -> dict:
        return json.loads((root / name).read_text(encoding="utf-8"))

    def record(revision: int) -> SimpleNamespace:
        return SimpleNamespace(revision=revision)

    report = report_snapshot_from_mapping(load("report-snapshot-v1.json"))
    case = replace(
        case_analysis_from_mapping(load("case-analysis-snapshot-v1.json")),
        snapshot_id=report.source_snapshot.case_analysis_snapshot_id,
        workspace_id=report.workspace_id,
        judicial_context_workspace_id=report.workspace_id,
    )
    planning = replace(pericial_planning_from_mapping(load("pericial-planning-snapshot-v1.json")), workspace_id=report.workspace_id)
    inspection = replace(inspection_session_from_mapping(load("inspection-session-v1.json")), workspace_id=report.workspace_id)
    technical = replace(technical_snapshot_from_mapping(load("technical-snapshot-v1.json")), workspace_id=report.workspace_id)
    current = build_delivery_binding(
        workspace_id=report.workspace_id,
        case_record=record(report.source_snapshot.case_analysis_revision), case=case,
        planning_record=record(3), planning=planning,
        inspection_record=record(report.source_snapshot.inspection_session_revision), inspection=inspection,
        technical_record=record(report.source_snapshot.technical_snapshot_revision), technical=technical,
        report_record=record(6), report=report,
    )
    bound = replace(snapshot(), workspace_id=report.workspace_id, binding=current)
    assert reconcile_delivery(bound, current) == bound
    changed = replace(current, report_digest=SHA_B)
    stale = reconcile_delivery(bound, changed)
    assert stale.state is DeliveryState.STALE
    assert stale.stale_reasons == ("REPORT_DIGEST_CHANGED",)


def test_delivery_review_rejects_professional_identity_outside_bound_authority() -> None:
    class Getter:
        def execute(self, _workspace_id):
            return SimpleNamespace(revision=1), snapshot()

    service = ReviewDeliverySnapshot(Getter(), object(), object(), object())
    with pytest.raises(ValueError, match="professional authority"):
        service.execute(
            "workspace-1", action="MARK_READY_FOR_REVIEW", professional_id="OTHER-EXPERT",
            reason="Tentativa inválida.", expected_revision=1,
        )


def test_final_word_and_pdf_bytes_are_reopened_and_hashed_not_trusted() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
        package.writestr("word/vbaProject.bin", b"synthetic macro")
    word = output.getvalue()
    digest, size, media = validate_final_artifact(word, "DOCM")
    assert media == "application/vnd.ms-word.document.macroEnabled.12"
    verify_reopened_artifact(content=word, output_format="DOCM", expected_size=size, expected_sha256=digest)
    pdf = b"%PDF-1.7\n1 0 obj <</Type /Page>> endobj\n%%EOF"
    pdf_digest, pdf_size, pdf_media = validate_final_artifact(pdf, "PDF")
    assert pdf_media == "application/pdf"
    verify_reopened_artifact(content=pdf, output_format="PDF", expected_size=pdf_size, expected_sha256=pdf_digest)
    with pytest.raises(ValueError, match="diverge"):
        verify_reopened_artifact(content=pdf, output_format="PDF", expected_size=pdf_size, expected_sha256=SHA_A)


def test_artifact_validation_rejects_macro_identity_change_and_malformed_pdf() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
    with pytest.raises(ValueError, match="macro identity"):
        validate_final_artifact(output.getvalue(), "DOCM")
    with pytest.raises(ValueError, match="PDF"):
        validate_final_artifact(b"%PDF-1.7\nno page or eof", "PDF")
