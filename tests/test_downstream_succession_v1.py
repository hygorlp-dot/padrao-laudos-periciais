"""F7 (#252), cascata a jusante: Analise Tecnica e Analise de Vicios tem sucessora.

Reproducao (superficie normal): com a Analise Tecnica iniciada, uma edicao legitima
da Vistoria (confirmar os fatos da visita, registrar uma foto esquecida) a deixava
stale; ela recusa escrita e iniciar outra respondia 409. A Analise de Vicios (PAT)
tinha o mesmo beco. O modelo e o do planejamento: sucessora vazia sobre as
autoridades vigentes, anterior imutavel no historico, nada transportado.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _runtime(path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN

    runtime = build_local_api(path / "f7c.db", token=TOKEN, private_root=path / "private")
    runtime.start()
    return runtime


def _http(runtime, *args, **kwargs):
    from tests.test_product_integration_oracle_v1 import _http as call

    return call(runtime, *args, **kwargs)


def _technical_snapshot_then_normal_inspection_edit(runtime):
    from tests.test_inspection_visit_context_v1 import visit_values
    from tests.test_property_record_v1 import _text_pdf

    status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Cadeia técnica sintética"})
    root = f"/v1/workspaces/{workspace['workspace_id']}"
    profile = json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
    assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
    assert _http(runtime, "POST", root + "/materials", raw_body=_text_pdf(["QUESITOS DA PARTE AUTORA", "01) A parede apresenta umidade?"]), headers={"Content-Type": "application/pdf", "X-Document-Filename": "q.pdf"})[0] == 201
    assert _http(runtime, "POST", root + "/case-analysis", {})[0] == 201
    status, proposed = _http(runtime, "GET", root + "/case-analysis/intake")
    question = proposed["questions"][0]
    status, case = _http(runtime, "POST", root + "/case-analysis/questions", {"selections": [{"proposal_id": question["proposal_id"], "origin": question["source"]["origin"]}], "expected_revision": proposed["revision"]})
    for item in case["snapshot"]["questions"]:
        status, case = _http(runtime, "POST", root + "/case-analysis/reviews", {"expected_revision": case["revision"], "target_item_id": item["item_id"], "action": "CONFIRM", "corrected_value": None, "reviewer": profile["profile_id"], "reason": "Fonte conferida."})
    status, plan = _http(runtime, "POST", root + "/pericial-planning", {"title": "Plano"})
    for name in ("issues", "inspection_requirements", "question_links"):
        for item in plan["snapshot"][name]:
            status, plan = _http(runtime, "POST", root + "/pericial-planning/decisions", {"expected_revision": plan["revision"], "target_item_id": item["item_id"], "action": "APPROVE", "reviewer": profile["profile_id"], "reason": "Ok.", "decided_value": None})
    status, inspection = _http(runtime, "POST", root + "/inspection-session", {"responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
    status, technical = _http(runtime, "POST", root + "/technical-snapshot", {})
    assert status == 201
    status, _ = _http(runtime, "POST", root + "/inspection-session/visit-context", {"expected_revision": inspection["revision"], "values": visit_values()})
    assert status == 200
    return root, technical


def test_stale_technical_snapshot_has_an_explicit_empty_successor(tmp_path):
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, http_request

    runtime = _runtime(tmp_path)
    try:
        root, technical_v1 = _technical_snapshot_then_normal_inspection_edit(runtime)
        status, stale = _http(runtime, "GET", root + "/technical-snapshot")
        assert stale["snapshot"]["upstream_stale"] is True
        # O beco anterior: a rota inicial nao recria a cadeia tecnica.
        assert _http(runtime, "POST", root + "/technical-snapshot", {})[0] == 409
        assert _http(runtime, "POST", root + "/technical-snapshot/successor", {"expected_revision": stale["revision"] + 1})[0] == 409

        status, successor = _http(runtime, "POST", root + "/technical-snapshot/successor", {"expected_revision": stale["revision"]})
        assert status == 200, successor
        snapshot = successor["snapshot"]
        assert snapshot["upstream_stale"] is False and snapshot["snapshot_id"] != technical_v1["snapshot"]["snapshot_id"]
        assert snapshot["evidence_items"] == [] and snapshot["findings"] == [] and snapshot["decisions"] == []
        status, inspection = _http(runtime, "GET", root + "/inspection-session")
        assert snapshot["source_snapshot"]["inspection_session_revision"] == inspection["revision"]
        # Cadeia vigente nao pode ser sucedida.
        assert _http(runtime, "POST", root + "/technical-snapshot/successor", {"expected_revision": successor["revision"]})[0] == 400
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
    finally:
        runtime.close()
    verified = VerifyWorkspaceBackup().execute(backup)
    history = sorted((item for item in verified.artifact_revisions if item["artifact_kind"] == "TECHNICAL_SNAPSHOT_V1"), key=lambda item: item["revision"])
    assert history[0]["payload"] == technical_v1["snapshot"], "a cadeia tecnica anterior foi reescrita"
    assert history[-1]["payload"]["snapshot_id"] == successor["snapshot"]["snapshot_id"]
    runtime = _runtime(tmp_path)
    try:
        status, reopened = _http(runtime, "GET", root + "/technical-snapshot")
        assert reopened["revision"] == successor["revision"] and reopened["snapshot"]["upstream_stale"] is False
    finally:
        runtime.close()


def test_technical_succession_authority_is_explicit_and_proposal_free():
    from types import SimpleNamespace

    from scripts.backend_contract.application.technical_findings import SaveTechnicalSnapshot
    from scripts.backend_contract.technical_findings import technical_snapshot_from_mapping

    fixture = json.loads((Path(__file__).parent / "fixtures/technical-snapshot-v1.json").read_text(encoding="utf-8"))
    snapshot = technical_snapshot_from_mapping(fixture)
    service = SaveTechnicalSnapshot(*(SimpleNamespace() for _ in range(7)))
    workspace = snapshot.workspace_id
    with pytest.raises(ValueError, match="stale predecessor revision"):
        service.execute(workspace, snapshot, None, mutation_authority="SUCCESSION")
    assert snapshot.evidence_items, "fixture deve ter conteudo para provar a recusa"
    with pytest.raises(ValueError, match="canonical start command"):
        service.execute(workspace, snapshot, 3, mutation_authority="SUCCESSION")


def test_stale_construction_defect_analysis_has_an_explicit_successor_without_reviews():
    from types import SimpleNamespace

    from tests.test_construction_defect_product_integration_v1 import WORKSPACE_ID, _application_context, _application_services
    from scripts.backend_contract.application.construction_defect_analysis import StartSuccessorConstructionDefectAnalysis

    services = _application_services()
    first_record, _proposal = services.start.execute(WORKSPACE_ID, observation_contexts=(_application_context(),))
    reviewed_record, reviewed = services.review.execute(
        WORKSPACE_ID, pat_id="PAT-001", action="APPROVE", professional_id="PROFESSIONAL-001",
        reason="Revisao profissional sintetica.", expected_revision=first_record.revision,
    )
    successor = StartSuccessorConstructionDefectAnalysis(services.get, services.start, services.save)
    # Vigente: nao ha o que suceder.
    with pytest.raises(ValueError, match="only a stale"):
        successor.execute(WORKSPACE_ID, expected_revision=reviewed_record.revision, observation_contexts=(_application_context(),))
    # Mudanca legitima a montante (nova revisao da vistoria com o mesmo conteudo).
    services.inspection.record = SimpleNamespace(**{**vars(services.inspection.record), "revision": services.inspection.record.revision + 1, "checksum_sha256": "f" * 64})
    _record, stale = services.get.execute(WORKSPACE_ID)
    assert stale.upstream_stale is True
    record, snapshot = successor.execute(WORKSPACE_ID, expected_revision=reviewed_record.revision, observation_contexts=(_application_context(),))
    assert record.revision == reviewed_record.revision + 1
    assert snapshot.reviews == () and snapshot.effective_pat_ids == () and snapshot.snapshot_id != reviewed.snapshot_id
    assert services.store.history[1].payload["reviews"], "a revisao profissional anterior permanece no historico"
    _record, current = services.get.execute(WORKSPACE_ID)
    assert current.upstream_stale is False
