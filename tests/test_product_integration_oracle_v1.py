from __future__ import annotations

import json
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import os
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

import pytest

from scripts.backend_contract.application.delivery_foundation import reconcile_delivery
from scripts.backend_contract.application.ports import RepositoryIntegrityError
from scripts.backend_contract.budget_foundation import budget_snapshot_from_mapping
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.delivery_foundation import DeliveryState, delivery_snapshot_from_mapping
from scripts.backend_contract.infrastructure.productization import CreateWorkspaceBackup, RecoveryStaging, RestoreWorkspaceBackup, VerifyWorkspaceBackup
from scripts.backend_contract.application.models import PrivateContentId, WorkspaceId, thaw_payload
from scripts.backend_contract.application.ocr_cache import RevisionOcrPageCache
from scripts.backend_contract.pericial_planning import pericial_planning_from_mapping
from scripts.backend_contract.report_foundation import report_snapshot_from_mapping
from scripts.backend_contract.technical_findings import technical_snapshot_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping
from scripts.backend_contract.local_api.composition import build_local_api
from scripts.planejamento_pericial.app_composition import build_pericial_application
from tests.test_local_api_v1 import FixedClock, TOKEN, http_request
from tests.test_document_intake_v1 import provision_private_root
from tests.test_final_closure_r7 import pdf_sintetico
from tests.test_product_bridge_v1 import browser_mutation_headers, frontend_build, request as bridge_request


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"

WINDOWS_MUTABLE_RECOVERY = pytest.mark.skipif(
    os.name != "nt",
    reason="mutable Recovery V1 is supported only on Windows",
)


def _http(runtime, method: str, path: str, value: object | None = None, raw_body: bytes | None = None, headers: dict | None = None):
    supplied = {"X-Local-API-Token": TOKEN, **(headers or {})}
    status, _response_headers, body = http_request(runtime.server, method, path, value=value, raw_body=raw_body, headers=supplied)
    return status, (json.loads(body) if body else None)


def _bridge_http(runtime, method: str, path: str, value: object | None = None, raw_body: bytes | None = None, headers: dict | None = None):
    supplied = {**browser_mutation_headers(runtime), **(headers or {})}
    status, _response_headers, body = bridge_request(runtime, method, path, body=value, raw_body=raw_body, headers=supplied)
    return status, (json.loads(body) if body else None)


def _bridge_raw(runtime, method: str, path: str, value: object | None = None, raw_body: bytes | None = None, headers: dict | None = None):
    supplied = {**browser_mutation_headers(runtime), **(headers or {})}
    return bridge_request(runtime, method, path, body=value, raw_body=raw_body, headers=supplied)


def _pdf_sintetico_com_jdm(path: Path) -> None:
    """Synthetic PJe export with plural principals and representatives only."""
    base = path.with_name(f"base-{path.name}")
    pdf_sintetico(base)
    writer = PdfWriter(clone_from=str(base))
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    stream = StreamObject()
    stream.set_data((
        "BT /F1 10 Tf 40 730 Td (PARTES PROCURADOR TERCEIRO VINCULADO) Tj "
        "0 -20 Td (MARIA DA SILVA (AUTORA) JOAO ADVOGADO (ADVOGADO)) Tj "
        "0 -20 Td (CARLOS DE SOUZA (AUTOR) ANA PROCURADORA (PROCURADOR)) Tj "
        "0 -20 Td (BANCO EXEMPLO (REU) BRUNO ADVOGADO (ADVOGADO)) Tj ET"
    ).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)


@WINDOWS_MUTABLE_RECOVERY
def test_d1_d11_normal_composed_product_path_delivers_closes_and_recovers_without_ai(tmp_path: Path) -> None:
    runtime = build_local_api(tmp_path / "product.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    try:
        status, created = _http(runtime, "POST", "/v1/workspaces", {"name": "Caso longitudinal sintético"})
        assert status == 201
        workspace_id = created["workspace_id"]
        status, foreign = _http(runtime, "POST", "/v1/workspaces", {"name": "Workspace sentinela"})
        assert status == 201 and foreign["workspace_id"] != workspace_id

        source = b"%PDF-1.7\nsynthetic longitudinal source\n%%EOF\n"
        status, _ = _http(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", raw_body=source,
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "fonte-sintetica.pdf"},
        )
        assert status == 201
        status, analysis = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", {})
        assert status == 201
        document_id = analysis["snapshot"]["documents"][0]["document_id"]
        question_id = None
        for kind, text in (("PERICIAL_OBJECT", "Objeto técnico sintético."), ("PERICIAL_QUESTION", "Qual é a condição observável?")):
            status, analysis = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/items", {
                "expected_revision": analysis["revision"], "item_kind": kind, "text": text,
                "source_document_id": document_id, "page_or_span": "p. 1", "technical_subjects": ["tema sintético"], "values": {},
            })
            assert status == 200
            target = analysis["snapshot"][{"PERICIAL_OBJECT": "pericial_objects", "PERICIAL_QUESTION": "questions"}[kind]][-1]["item_id"]
            if kind == "PERICIAL_QUESTION":
                question_id = target
            status, analysis = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis/reviews", {
                "expected_revision": analysis["revision"], "target_item_id": target, "action": "CONFIRM",
                "corrected_value": None, "reviewer": "PROFESSIONAL-001", "reason": "Revisão humana sintética.",
            })
            assert status == 200

        injection_status, _ = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", {"snapshot": analysis["snapshot"]})
        assert injection_status == 400
        foreign_status, _ = _http(runtime, "GET", f"/v1/workspaces/{foreign['workspace_id']}/case-analysis")
        assert foreign_status == 404

        status, planning = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning", {"title": "Plano longitudinal"})
        assert status == 201
        item = planning["snapshot"]["inspection_requirements"][0]
        status, planning = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/pericial-planning/decisions", {
            "expected_revision": planning["revision"], "target_item_id": item["item_id"], "action": "APPROVE",
            "reviewer": "PROFESSIONAL-001", "reason": "Proposta aprovada para execução sintética.", "decided_value": None,
        })
        assert status == 200

        status, inspection = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/inspection-session", {
            "responsible_professional": "PROFESSIONAL-001", "location_context": "Local sintético", "participant_references": [],
        })
        assert status == 201 and inspection["snapshot"]["responsible_professional"] == "PROFESSIONAL-001"
        status, offline = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/offline-inspection", {
            "device_session_id": "SESSION-SYNTHETIC-001",
        })
        assert status == 201
        offline = offline["package"]
        photo_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        status, photo = _http(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/inspection-photos", raw_body=photo_bytes,
            headers={"Content-Type": "image/png", "X-Document-Filename": "campo.png"},
        )
        assert status == 201
        field = offline["inspection_snapshot"]
        field_item = field["items"][0]
        field_item.update(state="COMPLETED", observation_ids=["OBS-LONGITUDINAL-001"], photo_ids=["PHOTO-LONGITUDINAL-001"],
                          note="Execução offline sintética registrada pelo profissional.")
        field["locations"].append({"location_id": "LOCATION-LONGITUDINAL-001", "description": "Local sintético offline.", "parent_location_id": None})
        field["observations"] = [{
            "observation_id": "OBS-LONGITUDINAL-001", "inspection_item_id": field_item["item_id"],
            "observation_type": "DIRECT_OBSERVATION", "raw_observation": "Registro de campo offline sintético.",
            "location_id": "LOCATION-LONGITUDINAL-001", "timestamp": "2026-09-01T12:05:00+00:00",
            "operator": "PROFESSIONAL-001", "provenance": "Captura offline local sintética.",
        }]
        field["photos"] = [{
            "photo_id": "PHOTO-LONGITUDINAL-001", "inspection_item_id": field_item["item_id"],
            "private_content_id": photo["content_id"], "original_sha256": photo["checksum_sha256"],
            "reliable_capture_timestamp": "2026-09-01T12:06:00+00:00", "capture_timestamp_reliability": "RELIABLE",
            "location_id": "LOCATION-LONGITUDINAL-001", "caption": "Foto de campo sintética.",
            "device": "DEVICE-SYNTHETIC", "provenance": "Bytes originais preservados localmente.",
        }]
        field["evidence_candidates"] = [{
            "candidate_id": "EVIDENCE-CANDIDATE-LONGITUDINAL-001", "inspection_item_id": field_item["item_id"],
            "source_record_ids": ["OBS-LONGITUDINAL-001", "PHOTO-LONGITUDINAL-001"],
            "description": "Observação e mídia candidatas à análise técnica.", "provenance": "Captura offline sincronizada.",
        }]
        field["coverage"] = {"total_items": 1, "pending_items": 0, "completed_items": 1, "partial_items": 0,
                             "not_executed_items": 0, "not_applicable_items": 0, "blocked_items": 0,
                             "complete": True, "limitation_ids": [], "reasons": []}
        status, offline = _http(runtime, "PUT", f"/v1/workspaces/{workspace_id}/offline-inspection", {
            "package_id": offline["package_id"], "expected_package_revision": offline["package_revision"],
            "snapshot": field,
        })
        assert status == 201
        offline = offline["package"]
        assert offline["package_revision"] == 2
        status, sync = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/offline-sync", {
            "package_id": offline["package_id"],
        })
        assert status == 200, sync
        assert sync["accepted"] is True and sync["conflicts"] == []
        status, inspection = _http(runtime, "GET", f"/v1/workspaces/{workspace_id}/inspection-session")
        assert status == 200
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot", {})
        assert status == 201 and technical["snapshot"]["source_snapshot"]["inspection_session_id"] == inspection["snapshot"]["session_id"]

        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/evidence-proposals", {
            "source_kind": "FIELD_OBSERVATION", "source_id": "OBS-LONGITUDINAL-001",
            "proposition": "A observação offline sincronizada integra a cadeia técnica.",
            "why_relevant": "Fonte de campo do caso sintético.", "expected_revision": technical["revision"],
        })
        assert status == 200
        evidence_id = technical["snapshot"]["evidence_items"][0]["evidence_id"]
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/evidence-reviews", {
            "evidence_id": evidence_id, "action": "APPROVE", "professional_id": "PROFESSIONAL-001",
            "reason": "Evidência sintética conferida.", "expected_revision": technical["revision"],
        })
        assert status == 200
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/method-selections", {
            "evidence_id": evidence_id, "method_identity": "Análise documental sintética",
            "procedure": "Conferência da fonte vinculada.", "output": "Fonte confirmada.",
            "professional_id": "PROFESSIONAL-001", "expected_revision": technical["revision"],
        })
        assert status == 200
        method_id = technical["snapshot"]["method_applications"][0]["method_application_id"]
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/finding-proposals", {
            "method_application_id": method_id, "technical_proposition": "A fonte sintética foi tecnicamente vinculada.",
            "scope": "Caso longitudinal sintético.", "limitation": "Sem uso de dados reais.",
            "uncertainty": "Fixture controlada.", "uncertainty_impact": "Não afeta o teste de autoridade.",
            "contrary_evidence_ids": [], "expected_revision": technical["revision"],
        })
        assert status == 200
        proposal_id = technical["snapshot"]["finding_proposals"][0]["proposal_id"]
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/finding-reviews", {
            "proposal_id": proposal_id, "action": "APPROVE", "professional_id": "PROFESSIONAL-001",
            "reason": "Conclusão técnica sintética aprovada.", "modified_proposition": None,
            "resolve_conflicts": False, "expected_revision": technical["revision"],
        })
        assert status == 200, technical
        assert technical["snapshot"]["coverage"]["effective_findings"] == 1
        field_finding = technical["snapshot"]["findings"][0]
        field_evidence_id = evidence_id
        assert technical["snapshot"]["source_links"][0]["source_kind"] == "FIELD_OBSERVATION"

        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/evidence-proposals", {
            "source_kind": "CASE_QUESTION", "source_id": question_id,
            "proposition": "O quesito sintético integra a cadeia de resposta.",
            "why_relevant": "Autoridade processual do quesito.", "expected_revision": technical["revision"],
        })
        assert status == 200
        evidence_id = technical["snapshot"]["evidence_items"][-1]["evidence_id"]
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/evidence-reviews", {
            "evidence_id": evidence_id, "action": "APPROVE", "professional_id": "PROFESSIONAL-001",
            "reason": "Quesito sintético conferido.", "expected_revision": technical["revision"],
        })
        assert status == 200
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/method-selections", {
            "evidence_id": evidence_id, "method_identity": "Análise do quesito sintético",
            "procedure": "Vinculação ao achado de campo aprovado.", "output": "Resposta técnica rastreável.",
            "professional_id": "PROFESSIONAL-001", "expected_revision": technical["revision"],
        })
        assert status == 200
        method_id = technical["snapshot"]["method_applications"][-1]["method_application_id"]
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/finding-proposals", {
            "method_application_id": method_id, "technical_proposition": "O quesito possui resposta técnica sintética.",
            "scope": "Caso longitudinal sintético.", "limitation": "Sem dados reais.",
            "uncertainty": "Fixture controlada.", "uncertainty_impact": "Não afeta a autoridade testada.",
            "contrary_evidence_ids": [], "expected_revision": technical["revision"],
        })
        assert status == 200
        proposal_id = technical["snapshot"]["finding_proposals"][-1]["proposal_id"]
        status, technical = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/technical-snapshot/finding-reviews", {
            "proposal_id": proposal_id, "action": "APPROVE", "professional_id": "PROFESSIONAL-001",
            "reason": "Resposta técnica sintética aprovada.", "modified_proposition": None,
            "resolve_conflicts": False, "expected_revision": technical["revision"],
        })
        assert status == 200
        assert technical["snapshot"]["coverage"]["effective_findings"] == 2
        finding = technical["snapshot"]["findings"][-1]
        decision = technical["snapshot"]["decisions"][-1]
        assert technical["snapshot"]["question_links"][0]["question_id"] == question_id

        profile = _fixture("report-snapshot-v1.json")["expert_profile"]
        status, _ = _http(runtime, "PUT", f"/v1/workspaces/{workspace_id}/expert-profile", {
            "expected_revision": None, "profile": profile,
        })
        assert status == 200
        status, report = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/report-snapshot", {})
        assert status == 201
        for context in report["snapshot"]["context_matrix"]:
            status, report = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/report-snapshot/draft-amendments", {
                "expected_revision": report["revision"], "action": "UPDATE_CONTEXT",
                "values": {"field": context["field"], "status": "PRESENT", "source_id": document_id, "note": "Fonte sintética."},
            })
            assert status == 200
        for section in report["snapshot"]["sections"]:
            if not section["required_by_cpc473"]:
                continue
            status, report = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/report-snapshot/draft-amendments", {
                "expected_revision": report["revision"], "action": "ADD_CLAIM",
                "values": {"section_id": section["section_id"], "text": "Conteúdo profissional sintético.", "source_kind": "CASE_DOCUMENT", "source_id": document_id},
            })
            assert status == 200
        answer_section = report["snapshot"]["sections"][0]["section_id"]
        status, report = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/report-snapshot/draft-amendments", {
            "expected_revision": report["revision"], "action": "ADD_CLAIM",
            "values": {"section_id": answer_section, "text": "Achado originado da captura offline sincronizada.",
                       "source_kind": "TECHNICAL_FINDING", "source_id": field_finding["finding_id"]},
        })
        assert status == 200
        status, report = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/report-snapshot/draft-amendments", {
            "expected_revision": report["revision"], "action": "ADD_CLAIM",
            "values": {"section_id": answer_section, "text": "Achado técnico efetivo sintético.", "source_kind": "TECHNICAL_FINDING", "source_id": finding["finding_id"]},
        })
        assert status == 200
        assert field_evidence_id in technical["snapshot"]["finding_proposals"][0]["supporting_evidence_ids"]
        finding_claim_id = report["snapshot"]["claims"][-1]["claim_id"]
        status, report = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/report-snapshot/draft-amendments", {
            "expected_revision": report["revision"], "action": "ADD_ANSWER",
            "values": {"section_id": answer_section, "question_id": question_id, "text": "Resposta sintética rastreável.",
                       "finding_id": finding["finding_id"], "evidence_ids": [evidence_id], "method_ids": [method_id],
                       "decision_id": decision["decision_id"], "claim_ids": [finding_claim_id]},
        })
        assert status == 200
        for action in ("MARK_REVIEWED", "APPROVE"):
            status, report = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/report-snapshot/reviews", {
                "expected_revision": report["revision"], "action": action, "professional_id": profile["profile_id"],
                "reason": "Revisão profissional sintética.",
            })
            assert status == 200, (action, report)
        assert report["snapshot"]["state"] == "APPROVED" and report["snapshot"]["coverage"]["complete"] is True

        manifest = _fixture("report-template-manifest-v1.json")
        template_bytes = _bound_template_docm(manifest["template_id"])
        status, template = _http(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/delivery-templates", raw_body=template_bytes,
            headers={"Content-Type": "application/vnd.ms-word.document.macroenabled.12", "X-Document-Filename": "modelo.docm"},
        )
        assert status == 201
        status, delivery = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/delivery-snapshot", {
            "template_content_id": template["content_id"], "manifest": manifest,
        })
        assert status == 201, delivery
        status, delivery = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/delivery-snapshot/render", {
            "expected_revision": delivery["revision"], "manifest": manifest,
        })
        assert status == 200, delivery
        for action in ("MARK_READY_FOR_REVIEW", "APPROVE"):
            status, delivery = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/delivery-snapshot/reviews", {
                "expected_revision": delivery["revision"], "action": action, "professional_id": profile["profile_id"],
                "reason": "Entrega Word sintética revisada.",
            })
            assert status == 200
        for action in ("finalize", "deliver"):
            status, delivery = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/delivery-snapshot/{action}", {
                "expected_revision": delivery["revision"], "professional_id": profile["profile_id"],
                "reason": "Integridade Word sintética verificada.",
            })
            assert status == 200
        assert delivery["snapshot"]["state"] == "DELIVERED"
        assert delivery["snapshot"]["artifacts"][0]["format"] == "DOCM"

        status, budget = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/budget-snapshot", {"process_id": None, "appointment_id": None})
        assert status == 201
        assert "technical_snapshot_id" not in budget["snapshot"]
        budget_commands = (
            ("proposals", {"amount": "3000.00", "currency": "BRL", "rationale": "Proposta sintética."}),
            ("court-approvals", {"external_court_decision_reference": "Mov. 42, decisão sintética.", "amount": "2500.00", "currency": "BRL", "decided_on": "2026-09-01"}),
            ("expenses", {"category": "TRAVEL", "amount": "100.00", "currency": "BRL", "incurred_on": "2026-09-01", "description": "Deslocamento sintético."}),
            ("payments", {"amount": "2500.00", "currency": "BRL", "received_on": "2026-09-02", "reference": "Depósito sintético."}),
            ("close", {}),
        )
        for action, values in budget_commands:
            status, budget = _http(runtime, "POST", f"/v1/workspaces/{workspace_id}/budget-snapshot/{action}", {
                "expected_revision": budget["revision"], **values,
            })
            assert status == 200, (action, budget)
        assert budget["snapshot"]["status"] == "CLOSED"

        package = CreateWorkspaceBackup(
            runtime._store.workspaces, runtime._store.revisions, runtime._private_store,
            FixedClock(), lambda _: None,
        ).execute(WorkspaceId.parse(workspace_id))
        verified = VerifyWorkspaceBackup().execute(package)
        kinds = {item["artifact_kind"] for item in verified.artifact_revisions}
        assert {"PROCESS_METADATA_EXTRACTION", "CASE_ANALYSIS_SNAPSHOT_V1", "PERICIAL_PLANNING_SNAPSHOT_V1",
                "INSPECTION_SESSION_V1", "TECHNICAL_SNAPSHOT_V1", "REPORT_SNAPSHOT_V1",
                "DELIVERY_SNAPSHOT_V1", "BUDGET_SNAPSHOT_V1"} <= kinds
        metadata_records = [item for item in verified.artifact_revisions if item["artifact_kind"] == "PROCESS_METADATA_EXTRACTION"]
        assert metadata_records and all(item["artifact_id"] == item["payload"]["document_id"] for item in metadata_records)
        staging = RecoveryStaging.create(tmp_path / "recovery")
        try:
            receipt = RestoreWorkspaceBackup(staging).execute(package)
            assert receipt.workspace_id == workspace_id
            reopened = staging.revisions.list_workspace(WorkspaceId.parse(workspace_id))
            assert len(reopened) == len(verified.artifact_revisions)
        finally:
            staging.close()
    finally:
        runtime.close()


@WINDOWS_MUTABLE_RECOVERY
def test_longitudinal_oracle_starts_with_synthetic_pje_through_product_bridge(tmp_path: Path) -> None:
    pdf = tmp_path / "autos-longitudinais-sinteticos.pdf"
    _pdf_sintetico_com_jdm(pdf)
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_application(
        tmp_path / "bridge-longitudinal.db",
        frontend_build(tmp_path),
        token=TOKEN,
        private_root=private,
    )
    runtime.start()
    try:
        status, workspace = _bridge_http(runtime, "POST", "/app-api/v1/workspaces", {"name": "Caso PJe longitudinal sintético"})
        assert status == 201
        workspace_id = workspace["workspace_id"]
        root = f"/app-api/v1/workspaces/{workspace_id}"
        status, material = _bridge_http(
            runtime,
            "POST",
            f"{root}/materials",
            raw_body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": pdf.name},
        )
        assert status == 201
        status, intake = _bridge_http(runtime, "GET", f"{root}/pje-intake")
        assert status == 200, intake
        assert intake["intakes"] and intake["intakes"][0]["inventory"]["storage_content_id"] == material["content_id"]
        status, analysis = _bridge_http(runtime, "POST", f"{root}/case-analysis", {})
        assert status == 201
        assert analysis["snapshot"]["documents"]
        assert all(item["storage_content_id"] == material["content_id"] for item in analysis["snapshot"]["documents"])
        context = analysis["snapshot"]["judicial_context"]
        assert len(context["participants"]) == 3
        assert len(context["representation_links"]) == 3
        assert {item["raw_name"] for item in context["entities"]} >= {
            "MARIA DA SILVA", "CARLOS DE SOUZA", "BANCO EXEMPLO",
            "JOAO ADVOGADO", "ANA PROCURADORA", "BRUNO ADVOGADO",
        }
        assert all(
            item["representative_entity_id"] not in {participant["entity_id"] for participant in context["participants"]}
            for item in context["representation_links"]
        )

        document_id = analysis["snapshot"]["documents"][0]["document_id"]
        item_ids = {}
        for kind, text in (
            ("CLAIM", "A parte autora alega infiltração sintética."),
            ("PERICIAL_OBJECT", "Objeto técnico sintético do imóvel."),
            ("PERICIAL_QUESTION", "Qual é a condição observável no local?"),
        ):
            status, analysis = _bridge_http(runtime, "POST", f"{root}/case-analysis/items", {
                "expected_revision": analysis["revision"], "item_kind": kind, "text": text,
                "source_document_id": document_id, "page_or_span": "p. 2",
                "technical_subjects": ["tema sintético"], "values": {},
            })
            assert status == 200, analysis
            collection = {"CLAIM": "claims", "PERICIAL_OBJECT": "pericial_objects", "PERICIAL_QUESTION": "questions"}[kind]
            item_ids[kind] = analysis["snapshot"][collection][-1]["item_id"]
            status, analysis = _bridge_http(runtime, "POST", f"{root}/case-analysis/reviews", {
                "expected_revision": analysis["revision"], "target_item_id": item_ids[kind],
                "action": "CONFIRM", "corrected_value": None, "reviewer": "PROFESSIONAL-001",
                "reason": "Revisão humana sintética efetiva.",
            })
            assert status == 200, analysis
        assert len(analysis["snapshot"]["human_reviews"]) == 3
        question_id = item_ids["PERICIAL_QUESTION"]
        claim_id = item_ids["CLAIM"]

        status, process_case = _bridge_http(runtime, "POST", f"{root}/process-case", {
            "expected_revision": None,
            "data": {
                "numero_processo": "0000001-00.2026.4.00.0001", "ramo_justica": "Justiça Federal",
                "tribunal": "Tribunal sintético", "vara": "Vara sintética", "municipio_sede": "Salvador",
                "subsecao_judiciaria": "Salvador", "comarca_municipio": "Salvador", "uf": "BA",
                "parte_requerente": "MARIA DA SILVA", "parte_requerida": "BANCO EXEMPLO",
            },
        })
        assert status == 200, process_case

        status, planning = _bridge_http(runtime, "POST", f"{root}/pericial-planning", {"title": "Plano longitudinal sintético"})
        assert status == 201, planning
        planned_item = planning["snapshot"]["inspection_requirements"][0]
        status, planning = _bridge_http(runtime, "POST", f"{root}/pericial-planning/decisions", {
            "expected_revision": planning["revision"], "target_item_id": planned_item["item_id"],
            "action": "APPROVE", "reviewer": "PROFESSIONAL-001",
            "reason": "Plano aprovado para captura sintética.", "decided_value": None,
        })
        assert status == 200, planning
        status, inspection = _bridge_http(runtime, "POST", f"{root}/inspection-session", {
            "responsible_professional": "PROFESSIONAL-001", "location_context": "Local sintético",
            "participant_references": [context["participants"][0]["participant_id"]],
        })
        assert status == 201, inspection
        status, offline = _bridge_http(runtime, "POST", f"{root}/offline-inspection", {"device_session_id": "SESSION-SYNTHETIC-001"})
        assert status == 201, offline
        package = offline["package"]
        photo_bytes = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        status, photo = _bridge_http(runtime, "POST", f"{root}/inspection-photos", raw_body=photo_bytes,
                                     headers={"Content-Type": "image/png", "X-Document-Filename": "campo.png"})
        assert status == 201, photo
        field = package["inspection_snapshot"]
        field_item = field["items"][0]
        location_id = field["locations"][0]["location_id"]
        field_item.update(
            state="COMPLETED", observation_ids=["OBS-LONGITUDINAL-001"],
            measurement_ids=["MEASUREMENT-LONGITUDINAL-001"], photo_ids=["PHOTO-LONGITUDINAL-001"],
            note="Execução offline sintética registrada pelo profissional.",
        )
        # Preserve the canonical location created with the inspection session.
        field["methods"] = [{"method_id": "METHOD-LONGITUDINAL-001", "name": "Medição sintética", "procedure": "Leitura direta.", "provenance": "Plano aprovado."}]
        field["instruments"] = [{"instrument_id": "INSTRUMENT-LONGITUDINAL-001", "identity": "Instrumento sintético", "model": "MODEL-001", "serial_number": "SERIAL-001", "capability": "0-2000 mm", "calibration_claimed": True, "certificate_reference": "CERT-001"}]
        field["instrument_statuses"] = [{"status_id": "STATUS-LONGITUDINAL-001", "instrument_id": "INSTRUMENT-LONGITUDINAL-001", "status": "CALIBRATION_VALID", "checked_at": "2026-09-01T12:00:00+00:00", "evidence_reference": "CERT-001"}]
        field["observations"] = [{
            "observation_id": "OBS-LONGITUDINAL-001", "inspection_item_id": field_item["item_id"],
            "observation_type": "DIRECT_OBSERVATION", "raw_observation": "Condição superficial observada em campo.",
            "location_id": location_id, "timestamp": "2026-09-01T12:05:00+00:00",
            "operator": "PROFESSIONAL-001", "provenance": "Captura offline local sintética.",
        }]
        field["measurements"] = [{
            "measurement_id": "MEASUREMENT-LONGITUDINAL-001", "inspection_item_id": field_item["item_id"],
            "quantity": "abertura", "raw_value": "0.20", "raw_unit": "mm", "normalized_value": "0.20",
            "normalized_unit": "mm", "instrument_id": "INSTRUMENT-LONGITUDINAL-001", "method_id": "METHOD-LONGITUDINAL-001",
            "location_id": location_id, "timestamp": "2026-09-01T12:06:00+00:00",
            "operator": "PROFESSIONAL-001", "uncertainty": "±0.01 mm", "raw_observation": "Leitura direta sintética.",
            "provenance": "Registro de medição sintético.",
        }]
        field["measurement_series"] = [{"series_id": "SERIES-LONGITUDINAL-001", "measurement_ids": ["MEASUREMENT-LONGITUDINAL-001"], "purpose": "Preservar a leitura bruta."}]
        field["photos"] = [{
            "photo_id": "PHOTO-LONGITUDINAL-001", "inspection_item_id": field_item["item_id"],
            "private_content_id": photo["content_id"], "original_sha256": photo["checksum_sha256"],
            "reliable_capture_timestamp": "2026-09-01T12:07:00+00:00", "capture_timestamp_reliability": "RELIABLE",
            "location_id": location_id, "caption": "Foto de campo sintética.",
            "device": "DEVICE-SYNTHETIC", "provenance": "Bytes originais preservados localmente.",
        }]
        field["evidence_candidates"] = [{
            "candidate_id": "EVIDENCE-CANDIDATE-LONGITUDINAL-001", "inspection_item_id": field_item["item_id"],
            "source_record_ids": ["OBS-LONGITUDINAL-001", "MEASUREMENT-LONGITUDINAL-001", "PHOTO-LONGITUDINAL-001"],
            "description": "Registros de campo candidatos à análise.", "provenance": "Captura offline sincronizada.",
        }]
        field["coverage"] = {"total_items": 1, "pending_items": 0, "completed_items": 1, "partial_items": 0,
                              "not_executed_items": 0, "not_applicable_items": 0, "blocked_items": 0,
                              "complete": True, "limitation_ids": [], "reasons": []}
        status, offline = _bridge_http(runtime, "PUT", f"{root}/offline-inspection", {
            "package_id": package["package_id"], "expected_package_revision": package["package_revision"], "snapshot": field,
        })
        assert status == 201, offline
        package = offline["package"]
        assert package["package_revision"] == 2
        status, sync = _bridge_http(runtime, "POST", f"{root}/offline-sync", {"package_id": package["package_id"]}, headers={"Content-Type": "application/json"})
        assert status == 200 and sync["accepted"] is True and sync["conflicts"] == [], sync

        status, inspection = _bridge_http(runtime, "GET", f"{root}/inspection-session")
        assert status == 200
        observation_id = inspection["snapshot"]["observations"][0]["observation_id"]
        measurement_id = inspection["snapshot"]["measurements"][0]["measurement_id"]
        photo_id = inspection["snapshot"]["photos"][0]["photo_id"]
        status, pat = _bridge_http(runtime, "POST", f"{root}/construction-defect-analysis", {
            "observation_contexts": [{
                "observation_id": observation_id,
                "manifestation": "Condição superficial observada em campo.",
                "system": "VEDACOES", "element": "Parede", "outcome": "OBSERVED",
                "methods": ["INSPECAO_VISUAL"], "measurement_ids": [measurement_id],
                "photo_ids": [photo_id], "claim_ids": [claim_id], "question_ids": [question_id],
            }],
        })
        assert status == 201, pat
        pat_id = pat["snapshot"]["analysis_final"]["patologias"][0]["id"]
        status, pat = _bridge_http(runtime, "POST", f"{root}/construction-defect-analysis/pathology-reviews", {
            "expected_revision": pat["revision"], "pat_id": pat_id, "action": "APPROVE",
            "professional_id": "PROFESSIONAL-001", "reason": "PAT sintético revisado pelo profissional.",
        })
        assert status == 200, pat
        assert pat["snapshot"]["reviews"][-1]["action"] == "APPROVE"

        status, technical = _bridge_http(runtime, "POST", f"{root}/technical-snapshot", {})
        assert status == 201, technical
        status, technical = _bridge_http(runtime, "POST", f"{root}/technical-snapshot/evidence-proposals", {
            "source_kind": "CASE_QUESTION", "source_id": question_id,
            "proposition": "O quesito sintético requer resposta técnica independente do PAT.",
            "why_relevant": "Autoridade processual do quesito.", "expected_revision": technical["revision"],
        })
        assert status == 200, technical
        technical_evidence_id = technical["snapshot"]["evidence_items"][-1]["evidence_id"]
        status, technical = _bridge_http(runtime, "POST", f"{root}/technical-snapshot/evidence-reviews", {
            "evidence_id": technical_evidence_id, "action": "APPROVE", "professional_id": "PROFESSIONAL-001",
            "reason": "Evidência técnica sintética conferida.", "expected_revision": technical["revision"],
        })
        assert status == 200, technical
        status, technical = _bridge_http(runtime, "POST", f"{root}/technical-snapshot/method-selections", {
            "evidence_id": technical_evidence_id, "method_identity": "Análise técnica sintética",
            "procedure": "Conferência independente do quesito.", "output": "Base técnica confirmada.",
            "professional_id": "PROFESSIONAL-001", "expected_revision": technical["revision"],
        })
        assert status == 200, technical
        method_id = technical["snapshot"]["method_applications"][-1]["method_application_id"]
        status, technical = _bridge_http(runtime, "POST", f"{root}/technical-snapshot/finding-proposals", {
            "method_application_id": method_id, "technical_proposition": "A resposta técnica sintética permanece separada do PAT.",
            "scope": "Caso longitudinal sintético.", "limitation": "Fixture controlada.",
            "uncertainty": "Sem dados reais.", "uncertainty_impact": "Não altera o teste de autoridade.",
            "contrary_evidence_ids": [], "expected_revision": technical["revision"],
        })
        assert status == 200, technical
        finding_proposal_id = technical["snapshot"]["finding_proposals"][-1]["proposal_id"]
        status, technical = _bridge_http(runtime, "POST", f"{root}/technical-snapshot/finding-reviews", {
            "proposal_id": finding_proposal_id, "action": "APPROVE", "professional_id": "PROFESSIONAL-001",
            "reason": "Achado técnico separado aprovado.", "modified_proposition": None,
            "resolve_conflicts": False, "expected_revision": technical["revision"],
        })
        assert status == 200, technical
        assert technical["snapshot"]["coverage"]["effective_findings"] == 1
        technical_finding_id = technical["snapshot"]["findings"][0]["finding_id"]
        decision_id = technical["snapshot"]["decisions"][-1]["decision_id"]

        profile = _fixture("report-snapshot-v1.json")["expert_profile"]
        status, profile_response = _bridge_http(runtime, "PUT", f"{root}/expert-profile", {
            "expected_revision": None, "profile": profile,
        })
        assert status == 200, profile_response
        status, report = _bridge_http(runtime, "POST", f"{root}/report-snapshot", {})
        assert status == 201, report
        for context_item in report["snapshot"]["context_matrix"]:
            status, report = _bridge_http(runtime, "POST", f"{root}/report-snapshot/draft-amendments", {
                "expected_revision": report["revision"], "action": "UPDATE_CONTEXT",
                "values": {"field": context_item["field"], "status": "PRESENT", "source_id": document_id, "note": "Fonte sintética vinculada."},
            })
            assert status == 200, report
        for section in report["snapshot"]["sections"]:
            if not section["required_by_cpc473"]:
                continue
            status, report = _bridge_http(runtime, "POST", f"{root}/report-snapshot/draft-amendments", {
                "expected_revision": report["revision"], "action": "ADD_CLAIM",
                "values": {"section_id": section["section_id"], "text": "Conteúdo profissional sintético.", "source_kind": "CASE_DOCUMENT", "source_id": document_id},
            })
            assert status == 200, report
        answer_section = report["snapshot"]["sections"][0]["section_id"]
        status, report = _bridge_http(runtime, "POST", f"{root}/report-snapshot/draft-amendments", {
            "expected_revision": report["revision"], "action": "ADD_CLAIM",
            "values": {"section_id": answer_section, "text": "Patologia observada e aprovada para análise.", "source_kind": "PATHOLOGY", "source_id": pat_id},
        })
        assert status == 200, report
        assert any(
            provenance["source_kind"] == "PATHOLOGY" and provenance["source_id"] == pat_id
            for claim in report["snapshot"]["claims"]
            for provenance in claim["provenance"]
        )
        status, report = _bridge_http(runtime, "POST", f"{root}/report-snapshot/draft-amendments", {
            "expected_revision": report["revision"], "action": "ADD_CLAIM",
            "values": {"section_id": answer_section, "text": "Achado técnico efetivo sintético.", "source_kind": "TECHNICAL_FINDING", "source_id": technical_finding_id},
        })
        assert status == 200, report
        technical_claim_id = report["snapshot"]["claims"][-1]["claim_id"]
        report_revision_before_answer = report["revision"]
        status, report = _bridge_http(runtime, "POST", f"{root}/report-snapshot/draft-amendments", {
            "expected_revision": report_revision_before_answer, "action": "ADD_ANSWER",
            "values": {"section_id": answer_section, "question_id": question_id, "text": "Resposta sintética rastreável.",
                        "finding_id": technical_finding_id, "evidence_ids": [technical_evidence_id], "method_ids": [method_id],
                                "decision_id": decision_id, "claim_ids": [technical_claim_id]},
        })
        assert status == 200, report
        for action in ("MARK_REVIEWED", "APPROVE"):
            status, report = _bridge_http(runtime, "POST", f"{root}/report-snapshot/reviews", {
                "expected_revision": report["revision"], "action": action, "professional_id": profile["profile_id"],
                "reason": "Revisão profissional sintética do relatório.",
            })
            assert status == 200, report
        assert report["snapshot"]["state"] == "APPROVED"
        report_digest = _digest(report["snapshot"])

        manifest = _fixture("report-template-manifest-v1.json")
        template_bytes = _bound_template_docm(manifest["template_id"])
        status, template = _bridge_http(runtime, "POST", f"{root}/delivery-templates", raw_body=template_bytes,
                                        headers={"Content-Type": "application/vnd.ms-word.document.macroenabled.12", "X-Document-Filename": "modelo.docm"})
        assert status == 201, template
        status, delivery = _bridge_http(runtime, "POST", f"{root}/delivery-snapshot", {
            "template_content_id": template["content_id"], "manifest": manifest,
        })
        assert status == 201, delivery
        status, delivery = _bridge_http(runtime, "POST", f"{root}/delivery-snapshot/render", {
            "expected_revision": delivery["revision"], "manifest": manifest,
        })
        assert status == 200, delivery
        for action in ("MARK_READY_FOR_REVIEW", "APPROVE"):
            status, delivery = _bridge_http(runtime, "POST", f"{root}/delivery-snapshot/reviews", {
                "expected_revision": delivery["revision"], "action": action, "professional_id": profile["profile_id"],
                "reason": "Entrega Word sintética revisada.",
            })
            assert status == 200, delivery
        for action in ("finalize", "deliver"):
            status, delivery = _bridge_http(runtime, "POST", f"{root}/delivery-snapshot/{action}", {
                "expected_revision": delivery["revision"], "professional_id": profile["profile_id"],
                "reason": "Integridade do artefato Word sintético verificada.",
            })
            assert status == 200, delivery
        assert delivery["snapshot"]["state"] == "DELIVERED"
        assert delivery["snapshot"]["artifacts"][0]["format"] in {"DOCX", "DOCM"}
        delivery_digest = _digest(delivery["snapshot"])

        status, budget = _bridge_http(runtime, "POST", f"{root}/budget-snapshot", {"process_id": None, "appointment_id": None})
        assert status == 201, budget
        for action, values in (
            ("items", {"category": "PROFESSIONAL_HOURS", "description": "Horas sintéticas", "quantity": "2.00", "unit_amount": "100.00"}),
            ("effort-estimates", {"professional_id": "PROFESSIONAL-001", "estimated_hours": "2.00", "hourly_amount": "100.00"}),
            ("travel-estimates", {"distance_km": "10.00", "amount_per_km": "2.00", "description": "Deslocamento sintético"}),
            ("third-party-estimates", {"provider_description": "Laboratório sintético", "amount": "50.00", "currency": "BRL"}),
            ("proposals", {"amount": "3000.00", "currency": "BRL", "rationale": "Proposta sintética."}),
            ("court-approvals", {"external_court_decision_reference": "Mov. 42, decisão sintética.", "amount": "2500.00", "currency": "BRL", "decided_on": "2026-09-01"}),
            ("expenses", {"category": "TRAVEL", "amount": "100.00", "currency": "BRL", "incurred_on": "2026-09-01", "description": "Deslocamento sintético."}),
            ("payments", {"amount": "2500.00", "currency": "BRL", "received_on": "2026-09-02", "reference": "Depósito sintético."}),
        ):
            status, budget = _bridge_http(runtime, "POST", f"{root}/budget-snapshot/{action}", {
                "expected_revision": budget["revision"], **values,
            })
            assert status == 200, (action, budget)
        status, budget = _bridge_http(runtime, "POST", f"{root}/budget-snapshot/close", {"expected_revision": budget["revision"]})
        assert status == 200, budget
        assert budget["snapshot"]["status"] == "CLOSED"
        budget_digest = _digest(budget["snapshot"])

        status, process_case_final = _bridge_http(runtime, "GET", f"{root}/process-case")
        assert status == 200, process_case_final
        status, pje_final = _bridge_http(runtime, "GET", f"{root}/pje-intake")
        assert status == 200, pje_final
        pre_recovery = {
            "process_case": process_case_final,
            "pje": pje_final,
            "case_analysis": {"revision": analysis["revision"], "snapshot": analysis["snapshot"], "digest": _digest(analysis["snapshot"])},
            "planning": {"revision": planning["revision"], "snapshot": planning["snapshot"], "digest": _digest(planning["snapshot"])},
            "inspection": {"revision": inspection["revision"], "snapshot": inspection["snapshot"], "digest": _digest(inspection["snapshot"])},
            "pat": {"revision": pat["revision"], "snapshot": pat["snapshot"], "digest": _digest(pat["snapshot"])},
            "technical": {"revision": technical["revision"], "snapshot": technical["snapshot"], "digest": _digest(technical["snapshot"])},
            "report": {"revision": report["revision"], "snapshot": report["snapshot"], "digest": report_digest},
            "delivery": {"revision": delivery["revision"], "snapshot": delivery["snapshot"], "digest": delivery_digest},
            "budget": {"revision": budget["revision"], "snapshot": budget["snapshot"], "digest": budget_digest},
        }
        status, backup_headers, backup = _bridge_raw(runtime, "POST", f"{root}/backup", headers={"Content-Type": "application/json"})
        assert status == 200 and backup_headers["Content-Type"] == "application/octet-stream" and isinstance(backup, bytes) and backup
        status, backup_summary = _bridge_http(runtime, "POST", "/app-api/v1/recovery/verify", raw_body=backup,
                                              headers={"Content-Type": "application/octet-stream"})
        assert status == 200, backup_summary
        assert backup_summary["workspace_id"] == workspace_id
        runtime.close()

        recovered_private = tmp_path / "recovered-private"
        provision_private_root(recovered_private)
        recovered = build_pericial_application(
            tmp_path / "recovered.db", frontend_build(tmp_path / "recovered-frontend"),
            token=TOKEN, private_root=recovered_private,
        )
        recovered.start()
        try:
            status, staged = _bridge_http(recovered, "POST", "/app-api/v1/recovery/staging", raw_body=backup,
                                          headers={"Content-Type": "application/octet-stream"})
            assert status == 201, staged
            recovery_id = staged["recovery_id"]
            status, promoted = _bridge_http(recovered, "POST", f"/app-api/v1/recovery/{recovery_id}/promote", {"confirm": True})
            assert status == 200, promoted
            assert promoted["workspace_id"] == workspace_id
            recovered_root = f"/app-api/v1/workspaces/{workspace_id}"
            status, recovered_case = _bridge_http(recovered, "GET", f"{recovered_root}/case-analysis")
            assert status == 200
            status, recovered_planning = _bridge_http(recovered, "GET", f"{recovered_root}/pericial-planning")
            assert status == 200
            status, recovered_inspection = _bridge_http(recovered, "GET", f"{recovered_root}/inspection-session")
            assert status == 200
            status, recovered_pat = _bridge_http(recovered, "GET", f"{recovered_root}/construction-defect-analysis")
            assert status == 200
            status, recovered_technical = _bridge_http(recovered, "GET", f"{recovered_root}/technical-snapshot")
            assert status == 200
            status, recovered_report = _bridge_http(recovered, "GET", f"{recovered_root}/report-snapshot")
            assert status == 200
            status, recovered_delivery = _bridge_http(recovered, "GET", f"{recovered_root}/delivery-snapshot")
            assert status == 200
            status, recovered_budget = _bridge_http(recovered, "GET", f"{recovered_root}/budget-snapshot")
            assert status == 200
            status, recovered_process_case = _bridge_http(recovered, "GET", f"{recovered_root}/process-case")
            assert status == 200
            status, recovered_pje = _bridge_http(recovered, "GET", f"{recovered_root}/pje-intake")
            assert status == 200
            recovered_values = {
                "case_analysis": recovered_case, "planning": recovered_planning, "inspection": recovered_inspection,
                "pat": recovered_pat, "technical": recovered_technical, "report": recovered_report,
                "delivery": recovered_delivery, "budget": recovered_budget,
            }
            for name, value in recovered_values.items():
                assert value["revision"] == pre_recovery[name]["revision"]
                assert value["snapshot"] == pre_recovery[name]["snapshot"]
                assert _digest(value["snapshot"]) == pre_recovery[name]["digest"]
            assert recovered_process_case == pre_recovery["process_case"]
            assert recovered_pje == pre_recovery["pje"]
            assert recovered_delivery["snapshot"]["artifacts"][0]["format"] in {"DOCX", "DOCM"}
            assert recovered_budget["snapshot"]["status"] == "CLOSED"
        finally:
            recovered.close()
    finally:
        runtime.close()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _fixture(name: str) -> dict:
    return _repair_text(json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")))


def _repair_text(value: object) -> object:
    if type(value) is dict:
        return {key: _repair_text(item) for key, item in value.items()}
    if type(value) is list:
        return [_repair_text(item) for item in value]
    if type(value) is str:
        result = value
        for _ in range(2):
            if not any(token in result for token in ("Ã", "Â", "â€")):
                break
            try:
                result = result.encode("latin1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
        return result
    return value


def _replace_text(value: object, replacements: dict[str, str]) -> object:
    if type(value) is dict:
        return {key: _replace_text(item, replacements) for key, item in value.items()}
    if type(value) is list:
        return [_replace_text(item, replacements) for item in value]
    return replacements.get(value, value) if type(value) is str else value


def _docx(text: str = "Laudo sintético aprovado") -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("word/document.xml", f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def _bound_template_docm(template_id: str) -> bytes:
    document = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>[[EXPERT_FULL_NAME]]</w:t></w:r></w:p><w:p><w:r><w:t>[[EXPERT_REGISTRATION]]</w:t></w:r></w:p><w:p><w:r><w:t>[[REPORT_ID]]</w:t></w:r></w:p>
      <w:sdt><w:sdtPr><w:tag w:val="CANONICAL_REPORT"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>empty</w:t></w:r></w:p></w:sdtContent></w:sdt>
      <w:p><w:bookmarkStart w:id="1" w:name="B"/><w:r><w:instrText>TOC</w:instrText><w:instrText>PAGE</w:instrText><w:instrText>NUMPAGES</w:instrText><w:instrText>SEQ Figure</w:instrText><w:instrText>REF B</w:instrText><w:instrText>PAGEREF B</w:instrText></w:r><w:bookmarkEnd w:id="1"/></w:p>
    </w:body></w:document>'''
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/><Override PartName="/word/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
        package.writestr("word/document.xml", document)
        package.writestr("word/styles.xml", "<styles/>")
        package.writestr("word/numbering.xml", "<numbering/>")
        package.writestr("word/vbaProject.bin", b"synthetic-macro")
        package.writestr("docProps/custom.xml", f'<Properties><property name="TEMPLATE_ID"><value>{template_id}</value></property></Properties>')
    return output.getvalue()


def _private(content_id: str, content: bytes, filename: str, media_type: str) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "content_id": content_id,
        "original_filename": filename,
        "byte_size": len(content),
        "checksum_sha256": hashlib.sha256(content).hexdigest(),
        "media_type": media_type,
        "imported_at": "2026-09-01T12:00:00+00:00",
        "origin": "LOCAL_IMPORT",
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _revision(kind: str, artifact_id: str, payload: dict, revision: int, serial: int) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "artifact_kind": kind,
        "artifact_id": artifact_id,
        "revision_id": f"90000000-0000-4000-8000-{serial:012d}",
        "revision": revision,
        "created_at": "2026-09-01T12:00:00+00:00",
        "checksum_sha256": _digest(payload),
        "payload": deepcopy(payload),
    }


def _reseal(mapping: dict) -> bytes:
    for record in mapping["artifact_revisions"]:
        record["checksum_sha256"] = _digest(record["payload"])
    mapping["member_hashes"] = {
        "artifact_revisions": _digest(mapping["artifact_revisions"]),
        "private_contents": _digest(mapping["private_contents"]),
    }
    mapping["manifest_sha256"] = _digest({key: value for key, value in mapping.items() if key != "manifest_sha256"})
    return _canonical(mapping)


def _longitudinal_backup() -> tuple[bytes, dict[str, dict]]:
    case = _fixture("case-analysis-snapshot-v1.json")
    planning = _fixture("pericial-planning-snapshot-v1.json")
    inspection = _fixture("inspection-session-v1.json")
    technical = _fixture("technical-snapshot-v1.json")
    report = _fixture("report-snapshot-v1.json")
    budget = _fixture("budget-snapshot-v1.json")
    profile = deepcopy(report["expert_profile"])

    source_private = []
    source_replacements = {}
    for index, document in enumerate(case["documents"], 1):
        content = f"fonte processual sintética {index}".encode()
        digest = hashlib.sha256(content).hexdigest()
        source_replacements[document["source_sha256"]] = digest
        source_private.append(_private(document["storage_content_id"], content, f"fonte-{index}.pdf", "application/pdf"))
    case = _replace_text(case, source_replacements)

    media_private = []
    for kind, content, media_type in (("photos", b"photo", "image/jpeg"), ("videos", b"video", "video/mp4"), ("sketches", b"sketch", "image/png")):
        item = inspection[kind][0]
        item["original_sha256"] = hashlib.sha256(content).hexdigest()
        media_private.append(_private(item["private_content_id"], content, f"{kind}.bin", media_type))

    planning["plan"]["case_analysis_digest"] = _digest(case)
    planning["plan"]["case_analysis_revision"] = 3
    inspection["plan_snapshot"]["planning_revision"] = 1
    inspection["plan_snapshot"]["planning_digest"] = _digest(planning)
    technical["source_snapshot"]["case_analysis_snapshot_id"] = case["snapshot_id"]
    technical["source_snapshot"]["case_analysis_digest"] = _digest(case)
    technical["source_snapshot"]["inspection_session_revision"] = 1
    technical["source_snapshot"]["inspection_session_digest"] = _digest(inspection)
    for link in technical["source_links"]:
        if link["source_kind"] in {"FIELD_OBSERVATION", "MEASUREMENT", "PHOTO", "VIDEO", "SKETCH", "PARTICIPANT_STATEMENT"}:
            link["source_revision"] = 1
    report["source_snapshot"]["case_analysis_snapshot_id"] = case["snapshot_id"]
    report["source_snapshot"]["case_analysis_digest"] = _digest(case)
    report["source_snapshot"]["inspection_session_revision"] = 1
    report["source_snapshot"]["inspection_session_digest"] = _digest(inspection)
    report["source_snapshot"]["technical_snapshot_revision"] = 1
    report["source_snapshot"]["technical_snapshot_digest"] = _digest(technical)
    report["source_snapshot"]["expert_profile_digest"] = _digest(profile)
    for claim in report["claims"]:
        for provenance in claim["provenance"]:
            if provenance["source_kind"] in {"FIELD_OBSERVATION", "MEASUREMENT"}:
                provenance["source_revision"] = 1
            elif provenance["source_kind"] in {"TECHNICAL_FINDING", "PROFESSIONAL_DECISION"}:
                provenance["source_revision"] = 1

    word = _docx()
    template = _docx()
    delivery = _fixture("delivery-snapshot-v1.json")
    delivery["workspace_id"] = delivery["binding"]["workspace_id"] = WORKSPACE_ID
    delivery["binding"].update({
        "source_snapshot_id": f"SOURCE-INVENTORY-{case['source_revision']}",
        "source_revision": case["source_revision"],
        "case_analysis_snapshot_id": case["snapshot_id"], "case_analysis_revision": 3, "case_analysis_digest": _digest(case),
        "planning_snapshot_id": planning["snapshot_id"], "planning_revision": 1, "planning_digest": _digest(planning),
        "inspection_snapshot_id": inspection["session_id"], "inspection_revision": 1, "inspection_digest": _digest(inspection),
        "technical_snapshot_id": technical["snapshot_id"], "technical_revision": 1, "technical_digest": _digest(technical),
        "report_snapshot_id": report["report_id"], "report_revision": 1, "report_digest": _digest(report),
        "report_approval_id": report["review_decisions"][-1]["review_id"],
        "professional_id": profile["profile_id"],
    })
    delivery["template_digest"] = hashlib.sha256(template).hexdigest()
    delivery["artifacts"] = [{
        "artifact_id": "ARTIFACT-WORD-001", "role": "MAIN_REPORT", "format": "DOCX",
        "filename": "laudo-sintetico-r1.docx", "content_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "byte_size": len(word), "checksum_sha256": hashlib.sha256(word).hexdigest(),
    }]
    delivery["package"]["artifact_ids"] = ["ARTIFACT-WORD-001"]
    delivery["decisions"] = [
        {"decision_id": "DELIVERY-DECISION-1", "action": "MARK_READY_FOR_REVIEW", "professional_id": profile["profile_id"], "reason": "Revisão sintética.", "timestamp": "2026-09-01T12:01:00+00:00", "supersedes_decision_id": None},
        {"decision_id": "DELIVERY-DECISION-2", "action": "APPROVE", "professional_id": profile["profile_id"], "reason": "Aprovação sintética.", "timestamp": "2026-09-01T12:02:00+00:00", "supersedes_decision_id": "DELIVERY-DECISION-1"},
        {"decision_id": "DELIVERY-DECISION-3", "action": "FINALIZE", "professional_id": profile["profile_id"], "reason": "Finalização sintética.", "timestamp": "2026-09-01T12:03:00+00:00", "supersedes_decision_id": "DELIVERY-DECISION-2"},
        {"decision_id": "DELIVERY-DECISION-4", "action": "DELIVER", "professional_id": profile["profile_id"], "reason": "Entrega sintética.", "timestamp": "2026-09-01T12:04:00+00:00", "supersedes_decision_id": "DELIVERY-DECISION-3"},
    ]
    delivery["state"] = "DELIVERED"

    payloads = {"case": case, "planning": planning, "inspection": inspection, "technical": technical, "profile": profile, "report": report, "delivery": delivery, "budget": budget}
    case_v1 = deepcopy(case)
    case_v1["human_reviews"] = []
    case_v2 = deepcopy(case)
    case_v2["human_reviews"] = case_v2["human_reviews"][:1]
    delivery_v1 = deepcopy(delivery)
    delivery_v1.update(revision=1, artifacts=[], decisions=[], state="DRAFT")
    delivery_v1["package"]["artifact_ids"] = []
    delivery_v2 = deepcopy(delivery)
    delivery_v2.update(revision=2, decisions=[], state="DRAFT")
    delivery_v3 = deepcopy(delivery)
    delivery_v3.update(revision=3, decisions=delivery_v3["decisions"][:1], state="READY_FOR_REVIEW")
    delivery_v4 = deepcopy(delivery)
    delivery_v4.update(revision=4, decisions=delivery_v4["decisions"][:2], state="APPROVED")
    delivery_v5 = deepcopy(delivery)
    delivery_v5.update(revision=5, decisions=delivery_v5["decisions"][:3], state="FINALIZED")
    delivery_v6 = deepcopy(delivery)
    delivery_v6["revision"] = 6
    delivery = delivery_v6
    payloads["delivery"] = delivery
    definitions = (
        ("CASE_ANALYSIS_SNAPSHOT_V1", "CASE-ANALYSIS", (case_v1, case_v2, case)),
        ("PERICIAL_PLANNING_SNAPSHOT_V1", "PERICIAL-PLANNING", (planning,)),
        ("INSPECTION_SESSION_V1", "INSPECTION-SESSION", (inspection,)),
        ("TECHNICAL_SNAPSHOT_V1", "TECHNICAL-SNAPSHOT", (technical,)),
        ("EXPERT_MASTER_PROFILE_V1", "EXPERT-PROFILE", (profile,)),
        ("REPORT_SNAPSHOT_V1", "REPORT-SNAPSHOT", (report,)),
        ("DELIVERY_SNAPSHOT_V1", "DELIVERY-SNAPSHOT", (delivery_v1, delivery_v2, delivery_v3, delivery_v4, delivery_v5, delivery_v6)),
        ("BUDGET_SNAPSHOT_V1", "BUDGET-SNAPSHOT", (budget,)),
    )
    revisions = []
    serial = 1
    for kind, artifact_id, history in definitions:
        for revision, payload in enumerate(history, 1):
            revisions.append(_revision(kind, artifact_id, payload, revision, serial))
            serial += 1
    revisions.sort(key=lambda item: (item["artifact_kind"], item["artifact_id"], item["revision"]))

    private_contents = [*source_private, *media_private]
    private_contents.extend((
        _private(delivery["template_content_id"], template, "template.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        _private(delivery["artifacts"][0]["content_id"], word, "laudo-sintetico-r1.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ))

    mapping = {
        "schema_version": "1.0.0", "format_version": 1, "product_release": "0.11.0", "storage_schema_version": 1,
        "workspace": {"workspace_id": WORKSPACE_ID, "name": "Perícia longitudinal sintética", "created_at": "2026-09-01T11:00:00+00:00"},
        "artifact_revisions": revisions, "private_contents": private_contents,
        "member_hashes": {"artifact_revisions": _digest(revisions), "private_contents": _digest(private_contents)},
        "manifest_sha256": "0" * 64, "created_at": "2026-09-01T13:00:00+00:00",
    }
    mapping["manifest_sha256"] = _digest({key: value for key, value in mapping.items() if key != "manifest_sha256"})
    return _canonical(mapping), payloads


@WINDOWS_MUTABLE_RECOVERY
def test_d1_to_d7_longitudinal_authority_delivery_budget_and_recovery(tmp_path: Path) -> None:
    package, payloads = _longitudinal_backup()
    verified = VerifyWorkspaceBackup().execute(package)
    assert verified.workspace.workspace_id == WORKSPACE_ID

    case = case_analysis_from_mapping(payloads["case"])
    assert case.human_reviews and case.effective_reviewed_value(case.human_reviews[0].target_item_id) is not None
    assert pericial_planning_from_mapping(payloads["planning"]).decisions
    assert inspection_session_from_mapping(payloads["inspection"]).photos
    assert technical_snapshot_from_mapping(payloads["technical"]).decisions
    assert report_snapshot_from_mapping(payloads["report"]).state.value == "APPROVED"
    delivery = delivery_snapshot_from_mapping(payloads["delivery"])
    assert delivery.state is DeliveryState.DELIVERED
    assert delivery.artifacts[0].format.value == "DOCX"
    budget = budget_snapshot_from_mapping(payloads["budget"])
    assert budget.court_approvals and budget.payments
    assert not ({"budget_id", "court_approvals", "payments"} & set(payloads["technical"]))
    assert not ({"budget_id", "court_approvals", "payments"} & set(payloads["delivery"]["binding"]))

    changed_binding = replace(delivery.binding, report_digest="f" * 64)
    stale = reconcile_delivery(delivery, changed_binding)
    assert stale.state is DeliveryState.STALE and stale.stale_origin_state is DeliveryState.DELIVERED

    staging = RecoveryStaging.create(tmp_path / "recovery")
    receipt = RestoreWorkspaceBackup(staging).execute(package)
    assert receipt.artifact_revisions == len(verified.artifact_revisions)
    assert receipt.private_contents == len(verified.private_contents)
    reopened = staging.revisions.list_workspace(WorkspaceId.parse(verified.workspace.workspace_id))
    assert len(reopened) == len(verified.artifact_revisions)
    for actual, expected in zip(reopened, verified.artifact_revisions, strict=True):
        assert (actual.artifact_kind, actual.artifact_id, actual.revision, actual.checksum_sha256) == (
            expected["artifact_kind"], expected["artifact_id"], expected["revision"], expected["checksum_sha256"],
        )
        assert thaw_payload(actual.payload) == expected["payload"]
    for expected in verified.private_contents:
        with staging.private_contents.open_content(
            WorkspaceId.parse(verified.workspace.workspace_id),
            PrivateContentId.parse(expected["content_id"]),
        ) as opened:
            assert opened.stream.read() == base64.b64decode(expected["content_base64"])
    staging.close()


def test_d1_d6_d7_backup_rejects_missing_source_final_word_or_template_bytes() -> None:
    package, payloads = _longitudinal_backup()
    missing_authorities = (
        payloads["case"]["documents"][0]["storage_content_id"],
        payloads["delivery"]["template_content_id"],
        payloads["delivery"]["artifacts"][0]["content_id"],
    )
    for missing_id in missing_authorities:
        mapping = json.loads(package)
        mapping["private_contents"] = [item for item in mapping["private_contents"] if item["content_id"] != missing_id]
        mapping["member_hashes"]["private_contents"] = _digest(mapping["private_contents"])
        mapping["manifest_sha256"] = _digest({key: value for key, value in mapping.items() if key != "manifest_sha256"})
        try:
            VerifyWorkspaceBackup().execute(_canonical(mapping))
        except RepositoryIntegrityError as exc:
            assert "authority" in str(exc)
        else:
            raise AssertionError("missing delivery authority was accepted")


def test_d2_d6_generic_authority_attacks_fail_closed() -> None:
    package, _ = _longitudinal_backup()
    mapping = json.loads(package)
    delivery_record = [item for item in mapping["artifact_revisions"] if item["artifact_kind"] == "DELIVERY_SNAPSHOT_V1"][-1]
    delivery_record["payload"]["binding"]["report_approval_id"] = "NONEXISTENT-APPROVAL"
    delivery_record["payload"]["binding"]["professional_id"] = "NONEXISTENT-PROFESSIONAL"
    try:
        VerifyWorkspaceBackup().execute(_reseal(mapping))
    except RepositoryIntegrityError as exc:
        assert "professional authority" in str(exc)
    else:
        raise AssertionError("forged professional Delivery authority was accepted")

    foreign = json.loads(package)
    budget_record = next(item for item in foreign["artifact_revisions"] if item["artifact_kind"] == "BUDGET_SNAPSHOT_V1")
    budget_record["payload"]["workspace_id"] = "22222222-2222-4222-8222-222222222222"
    try:
        VerifyWorkspaceBackup().execute(_reseal(foreign))
    except RepositoryIntegrityError as exc:
        assert "another workspace" in str(exc)
    else:
        raise AssertionError("cross-workspace canonical payload was accepted")

    substituted = json.loads(package)
    for record in substituted["artifact_revisions"]:
        if record["artifact_kind"] == "CASE_ANALYSIS_SNAPSHOT_V1":
            record["artifact_id"] = "ATTACKER-CONTROLLED-ID"
    try:
        VerifyWorkspaceBackup().execute(_reseal(substituted))
    except RepositoryIntegrityError as exc:
        assert "envelope identity" in str(exc)
    else:
        raise AssertionError("canonical artifact envelope substitution was accepted")

    divergent = json.loads(package)
    final_delivery = [item for item in divergent["artifact_revisions"] if item["artifact_kind"] == "DELIVERY_SNAPSHOT_V1"][-1]
    final_delivery["payload"]["revision"] = 999
    try:
        VerifyWorkspaceBackup().execute(_reseal(divergent))
    except RepositoryIntegrityError as exc:
        assert "envelope revision" in str(exc)
    else:
        raise AssertionError("domain/envelope revision divergence was accepted")


def test_d6_final_word_and_template_bytes_are_revalidated_after_recovery() -> None:
    package, payloads = _longitudinal_backup()
    targets = (
        (payloads["delivery"]["template_content_id"], "template"),
        (payloads["delivery"]["artifacts"][0]["content_id"], "delivery artifact"),
    )
    for content_id, expected_error in targets:
        mapping = json.loads(package)
        private = next(item for item in mapping["private_contents"] if item["content_id"] == content_id)
        forged = b"not-a-docx"
        digest = hashlib.sha256(forged).hexdigest()
        private.update(content_base64=base64.b64encode(forged).decode("ascii"), byte_size=len(forged), checksum_sha256=digest)
        for delivery_record in [item for item in mapping["artifact_revisions"] if item["artifact_kind"] == "DELIVERY_SNAPSHOT_V1"]:
            delivery = delivery_record["payload"]
            if content_id == delivery["template_content_id"]:
                delivery["template_digest"] = digest
            for artifact in delivery["artifacts"]:
                if artifact["content_id"] == content_id:
                    artifact.update(byte_size=len(forged), checksum_sha256=digest)
        try:
            VerifyWorkspaceBackup().execute(_reseal(mapping))
        except RepositoryIntegrityError as exc:
            assert expected_error in str(exc)
        else:
            raise AssertionError(f"invalid Delivery {expected_error} bytes were accepted")


@WINDOWS_MUTABLE_RECOVERY
def test_d6_canonical_ocr_cache_survives_backup_validation_and_runtime_reopen(tmp_path: Path) -> None:
    package, _ = _longitudinal_backup()
    mapping = json.loads(package)
    ocr = {
        "schema_version": 2, "document_sha256": "a" * 64, "page_number": 1,
        "engine": "SYNTHETIC-OCR", "engine_version": "1.0", "model_version": "pt-v1",
        "config_version": "config-v1", "normalized_text": "Texto OCR sintético.", "confidence": 0.99,
        "processing_status": "AVAILABLE",
        "blocks": [{"text": "Texto OCR sintético.", "confidence": 0.99, "bounding_box": [1.0, 2.0, 3.0, 4.0]}],
    }
    key = tuple(ocr[name] for name in ("document_sha256", "page_number", "engine", "engine_version", "model_version", "config_version"))
    artifact_id = hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    mapping["artifact_revisions"].append(_revision("OCR_PAGE_CACHE_V1", artifact_id, ocr, 1, 999))
    mapping["artifact_revisions"].sort(key=lambda item: (item["artifact_kind"], item["artifact_id"], item["revision"]))
    verified = VerifyWorkspaceBackup().execute(_reseal(mapping))
    assert any(item["artifact_kind"] == "OCR_PAGE_CACHE_V1" for item in verified.artifact_revisions)
    staging = RecoveryStaging.create(tmp_path / "ocr-recovery")
    try:
        RestoreWorkspaceBackup(staging).execute(_reseal(mapping))
        reopened = RevisionOcrPageCache(staging.revisions, WorkspaceId.parse(WORKSPACE_ID), object(), object()).get(key)
        assert reopened is not None and reopened.text == ocr["normalized_text"] and reopened.engine == ocr["engine"]
    finally:
        staging.close()

    substituted = json.loads(_reseal(mapping))
    ocr_record = next(item for item in substituted["artifact_revisions"] if item["artifact_kind"] == "OCR_PAGE_CACHE_V1")
    ocr_record["artifact_id"] = "OCR-CACHE-SUBSTITUTED"
    try:
        VerifyWorkspaceBackup().execute(_reseal(substituted))
    except RepositoryIntegrityError as exc:
        assert "internal artifact envelope identity" in str(exc)
    else:
        raise AssertionError("unreachable OCR cache envelope identity was accepted")

    reordered = json.loads(_reseal(mapping))
    reordered["artifact_revisions"][0], reordered["artifact_revisions"][1] = reordered["artifact_revisions"][1], reordered["artifact_revisions"][0]
    try:
        VerifyWorkspaceBackup().execute(_reseal(reordered))
    except RepositoryIntegrityError as exc:
        assert "revision order" in str(exc)
    else:
        raise AssertionError("non-canonical revision order was accepted")


def test_d3_d4_superseded_report_and_invalid_annex_fail_closed() -> None:
    package, _ = _longitudinal_backup()
    superseded = json.loads(package)
    report_record = next(item for item in superseded["artifact_revisions"] if item["artifact_kind"] == "REPORT_SNAPSHOT_V1")
    report = report_record["payload"]
    previous = report["review_decisions"][-1]
    report["review_decisions"].append({
        "review_id": "REPORT-REVIEW-SUPERSEDE", "action": "SUPERSEDE",
        "professional_id": previous["professional_id"], "reason": "Substituição sintética explícita.",
        "timestamp": "2026-09-01T12:30:00+00:00", "supersedes_review_id": previous["review_id"],
    })
    report["state"] = "SUPERSEDED"
    report["coverage"]["complete"] = False
    report["coverage"]["reasons"] = ["Report superseded"]
    report_digest = _digest(report)
    for record in superseded["artifact_revisions"]:
        if record["artifact_kind"] == "DELIVERY_SNAPSHOT_V1":
            record["payload"]["binding"]["report_digest"] = report_digest
    try:
        VerifyWorkspaceBackup().execute(_reseal(superseded))
    except RepositoryIntegrityError as exc:
        assert "professional authority" in str(exc)
    else:
        raise AssertionError("superseded Report remained effective Delivery authority")

    annexed = json.loads(package)
    forged = b"not-an-annex-docx"
    digest = hashlib.sha256(forged).hexdigest()
    annex_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    annexed["private_contents"].append(_private(
        annex_id, forged, "anexo.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ))
    final_delivery = [item for item in annexed["artifact_revisions"] if item["artifact_kind"] == "DELIVERY_SNAPSHOT_V1"][-1]["payload"]
    final_delivery["artifacts"].append({
        "artifact_id": "ARTIFACT-ANNEX-001", "role": "ANNEX", "format": "DOCX", "filename": "anexo.docx",
        "content_id": annex_id, "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "byte_size": len(forged), "checksum_sha256": digest,
    })
    final_delivery["package"]["artifact_ids"].append("ARTIFACT-ANNEX-001")
    try:
        VerifyWorkspaceBackup().execute(_reseal(annexed))
    except RepositoryIntegrityError as exc:
        assert "delivery artifact" in str(exc)
    else:
        raise AssertionError("invalid supporting DOCX was accepted")


def test_d8_runtime_and_persisted_product_text_has_no_mojibake() -> None:
    governed = (
        ROOT / "config" / "core-invariants.json",
        ROOT / "scripts" / "backend_contract",
        ROOT / "scripts" / "auditoria_pericial",
        ROOT / "scripts" / "extracao_pje",
        ROOT / "scripts" / "redacao_pericial",
        ROOT / "scripts" / "vistoria_estruturada",
        ROOT / "frontend" / "src",
    )
    forbidden = ("Ãƒ", "Ã£", "Ã§", "Ã©", "Ã¡", "Ã­", "Ã³", "Ãµ", "Ãª", "Ã´", "Â", "â€", "â‚¬", "�")
    failures: list[str] = []
    for boundary in governed:
        paths = (boundary,) if boundary.is_file() else tuple(boundary.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix not in {".json", ".py", ".ts", ".tsx"} or ".test." in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in forbidden):
                failures.append(str(path.relative_to(ROOT)))
    assert failures == []

    package, payloads = _longitudinal_backup()
    assert not any(token in package.decode("utf-8") for token in forbidden)
    runtime_text = " ".join(
        [item.text for item in case_analysis_from_mapping(payloads["case"]).material_items]
        + [item.text for item in report_snapshot_from_mapping(payloads["report"]).claims]
    )
    assert not any(token in runtime_text for token in forbidden)


def test_d5_pending_offline_authority_blocks_backup_before_workspace_read() -> None:
    class Workspaces:
        def get(self, _workspace_id):
            raise AssertionError("workspace was read before pending-offline refusal")

    service = CreateWorkspaceBackup(Workspaces(), object(), None, object(), lambda _workspace: (_ for _ in ()).throw(ValueError("pending offline")))
    try:
        service.execute(WorkspaceId.parse(WORKSPACE_ID))
    except ValueError as exc:
        assert str(exc) == "pending offline"
    else:
        raise AssertionError("pending offline work did not block backup")


def test_d9_d10_maturity_truth_is_derived_and_stage_10_is_proposal_only() -> None:
    maturity = json.loads((ROOT / "config" / "product-maturity-v1.json").read_text(encoding="utf-8"))
    stages = maturity["stages"]
    assert [item["stage"] for item in stages] == list(range(13))
    stage_10 = stages[10]
    assert stage_10 == {
        "stage": 10,
        "name": "AI_AUTOMATION_FOUNDATION",
        "status": "IMPLEMENTED_PROPOSAL_ONLY",
    }
    derived_complete = all(item["status"] == "COMPLETE" for item in stages)
    assert maturity["product_roadmap_stage_0_to_12_complete"] is derived_complete is False
    assert maturity["stage_10_authorized"] is True

    report = (ROOT / "docs" / "PRODUCT_MATURITY_REPORT_V1.md").read_text(encoding="utf-8")
    assert "Stage 10 is `IMPLEMENTED_PROPOSAL_ONLY`" in report
    assert "PRODUCT_ROADMAP_STAGE_0_TO_12_COMPLETE = FALSE" in report
