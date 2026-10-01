"""F7 (#252), Vistoria: sucessao explicita com reaproveitamento por decisao do perito.

Decisao humana registrada na #252: opcao B estrita. Quando a Analise do Caso muda
depois da vistoria, o plano V1 e a Vistoria V1 ficam stale. Antes desta correcao a
vistoria nao tinha caminho: iniciar outra respondia 409 e a stale recusava escrita.

Agora a Vistoria V2 nasce vazia sobre o plano vigente; a V1 continua imutavel no
historico. Registros da V1 sao oferecidos por linhagem semantica (tipo do requisito
e itens da Analise de que deriva, nunca o titulo) e so entram por escolha explicita,
preservando o conteudo original e registrando a decisao. O estado do item nao vem.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _runtime(path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN

    runtime = build_local_api(path / "f7.db", token=TOKEN, private_root=path / "private")
    runtime.start()
    return runtime


def _http(runtime, *args, **kwargs):
    from tests.test_product_integration_oracle_v1 import _http as call

    return call(runtime, *args, **kwargs)


def _inspection_v1_with_field_records_then_analysis_change(runtime):
    from tests.test_photo_library_v1 import jpeg
    from tests.test_property_record_v1 import _text_pdf

    status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Vistoria sucessora sintética"})
    root = f"/v1/workspaces/{workspace['workspace_id']}"
    profile = json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
    assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
    data = _text_pdf(["QUESITOS DA PARTE AUTORA", "01) A parede apresenta umidade?", "", "2. Qual a extensão?"])
    assert _http(runtime, "POST", root + "/materials", raw_body=data, headers={"Content-Type": "application/pdf", "X-Document-Filename": "quesitos.pdf"})[0] == 201
    assert _http(runtime, "POST", root + "/case-analysis", {})[0] == 201
    status, proposed = _http(runtime, "GET", root + "/case-analysis/intake")
    first, second = proposed["questions"][:2]

    def accept(proposal, revision):
        status, case = _http(runtime, "POST", root + "/case-analysis/questions", {"selections": [{"proposal_id": proposal["proposal_id"], "origin": proposal["source"]["origin"]}], "expected_revision": revision})
        assert status == 200
        return case

    case = accept(first, proposed["revision"])
    for item in case["snapshot"]["questions"]:
        status, case = _http(runtime, "POST", root + "/case-analysis/reviews", {"expected_revision": case["revision"], "target_item_id": item["item_id"], "action": "CONFIRM", "corrected_value": None, "reviewer": profile["profile_id"], "reason": "Fonte sintética conferida."})
        assert status == 200

    def approve_all(plan):
        for name in ("issues", "inspection_requirements", "question_links"):
            for item in plan["snapshot"][name]:
                status, plan = _http(runtime, "POST", root + "/pericial-planning/decisions", {"expected_revision": plan["revision"], "target_item_id": item["item_id"], "action": "APPROVE", "reviewer": profile["profile_id"], "reason": "Planejamento sintético confirmado.", "decided_value": None})
                assert status == 200
        return plan

    status, plan = _http(runtime, "POST", root + "/pericial-planning", {"title": "Plano V1"})
    approve_all(plan)
    status, v1 = _http(runtime, "POST", root + "/inspection-session", {"responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
    assert status == 201

    # Registros de campo reais na V1: uma observacao e uma foto privada.
    photo_bytes = jpeg()
    status, stored = _http(runtime, "POST", root + "/inspection-photos", raw_body=photo_bytes, headers={"Content-Type": "image/jpeg", "X-Document-Filename": "parede.jpg"})
    assert status == 201
    snapshot = json.loads(json.dumps(v1["snapshot"]))
    item = snapshot["items"][0]
    location = snapshot["locations"][0]["location_id"]
    snapshot["observations"].append({"observation_id": "OBSERVATION-V1-001", "inspection_item_id": item["item_id"], "observation_type": "DIRECT_OBSERVATION", "raw_observation": "Mancha de umidade a 40 cm do piso.", "location_id": location, "timestamp": "2026-09-20T09:30:00-03:00", "operator": profile["profile_id"], "provenance": "Registro sintético de campo."})
    snapshot["photos"].append({"photo_id": "PHOTO-V1-001", "inspection_item_id": item["item_id"], "private_content_id": stored["content_id"], "original_sha256": hashlib.sha256(photo_bytes).hexdigest(), "reliable_capture_timestamp": None, "capture_timestamp_reliability": "UNVERIFIED", "location_id": location, "caption": "Parede com mancha.", "device": "Câmera sintética", "provenance": "Foto sintética."})
    item["observation_ids"], item["photo_ids"] = ["OBSERVATION-V1-001"], ["PHOTO-V1-001"]
    item["state"], item["note"] = "COMPLETED", "Verificado em campo."
    pending = snapshot["coverage"]["pending_items"] - 1
    snapshot["coverage"].update(pending_items=pending, completed_items=1, complete=pending == 0)
    status, v1 = _http(runtime, "PUT", root + "/inspection-session", {"expected_revision": v1["revision"], "snapshot": snapshot})
    assert status == 200, v1

    # Mudanca legitima na Analise do Caso: o segundo quesito e aceito depois da vistoria.
    status, current = _http(runtime, "GET", root + "/case-analysis")
    accept(second, current["revision"])
    status, stale_plan = _http(runtime, "GET", root + "/pericial-planning")
    assert stale_plan["snapshot"]["upstream_stale"] is True
    status, plan_v2 = _http(runtime, "POST", root + "/pericial-planning/successor", {"expected_revision": stale_plan["revision"], "title": "Plano V2"})
    assert status == 201
    approve_all(plan_v2)
    return root, profile, v1, photo_bytes


def test_stale_inspection_has_an_explicit_successor_and_offers_records_only_by_lineage(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        root, profile, v1, photo_bytes = _inspection_v1_with_field_records_then_analysis_change(runtime)
        status, stale = _http(runtime, "GET", root + "/inspection-session")
        assert status == 200 and stale["snapshot"]["upstream_stale"] is True
        # O beco sem saida anterior: nao ha como iniciar outra vistoria pela rota inicial.
        assert _http(runtime, "POST", root + "/inspection-session", {"responsible_professional": profile["profile_id"], "location_context": "x", "participant_references": []})[0] in {400, 409}

        status, v2 = _http(runtime, "POST", root + "/inspection-session/successor", {"expected_revision": stale["revision"], "responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
        assert status == 201, v2
        session = v2["snapshot"]
        assert session["upstream_stale"] is False and session["session_id"] != v1["snapshot"]["session_id"]
        assert session["observations"] == [] and session["photos"] == [] and "reuse_decisions" not in session
        assert all(item["state"] == "PENDING" for item in session["items"]) and len(session["items"]) == len(v1["snapshot"]["items"]) + 1

        # Vistoria vigente nao pode ser sucedida.
        assert _http(runtime, "POST", root + "/inspection-session/successor", {"expected_revision": v2["revision"], "responsible_professional": profile["profile_id"], "location_context": "x", "participant_references": []})[0] == 400

        status, offered = _http(runtime, "GET", root + "/inspection-session/reuse-candidates")
        assert status == 200
        assert {(item["source_session_id"], item["source_revision"]) for item in offered["candidates"]} == {(v1["snapshot"]["session_id"], v1["revision"])}
        # So o item com a mesma linhagem (quesito 01) recebe oferta; o item novo (quesito 2) nao.
        assert {item["source_record_id"] for item in offered["candidates"]} == {"OBSERVATION-V1-001", "PHOTO-V1-001"}
        assert len({item["target_item_id"] for item in offered["candidates"]}) == 1
        target = offered["candidates"][0]["target_item_id"]

        status, reused = _http(runtime, "POST", root + "/inspection-session/reuse", {"expected_revision": v2["revision"], "selections": [{"source_session_id": v1["snapshot"]["session_id"], "source_record_id": "PHOTO-V1-001", "target_item_id": target}]})
        assert status == 200, reused
        session = reused["snapshot"]
        photo = session["photos"][0]
        original = v1["snapshot"]["photos"][0]
        assert photo["photo_id"] != original["photo_id"] and photo["inspection_item_id"] == target
        assert {key: photo[key] for key in ("private_content_id", "original_sha256", "reliable_capture_timestamp", "capture_timestamp_reliability", "caption", "device", "provenance")} == {key: original[key] for key in ("private_content_id", "original_sha256", "reliable_capture_timestamp", "capture_timestamp_reliability", "caption", "device", "provenance")}
        assert photo["original_sha256"] == hashlib.sha256(photo_bytes).hexdigest()
        decision = session["reuse_decisions"][0]
        assert decision["source_session_id"] == v1["snapshot"]["session_id"] and decision["source_session_revision"] == v1["revision"]
        assert decision["source_record_id"] == "PHOTO-V1-001" and decision["target_record_id"] == photo["photo_id"]
        assert decision["decided_by"] == profile["profile_id"] and decision["source_record_kind"] == "PHOTO"
        # O estado do item nao foi promovido: o item atual continua exigindo julgamento.
        assert next(item for item in session["items"] if item["item_id"] == target)["state"] == "PENDING"
        assert session["coverage"]["completed_items"] == 0

        # O mesmo registro nao e oferecido de novo nem aceito duas vezes.
        status, offered = _http(runtime, "GET", root + "/inspection-session/reuse-candidates")
        assert [item["source_record_id"] for item in offered["candidates"]] == ["OBSERVATION-V1-001"]
        assert _http(runtime, "POST", root + "/inspection-session/reuse", {"expected_revision": reused["revision"], "selections": [{"source_session_id": v1["snapshot"]["session_id"], "source_record_id": "PHOTO-V1-001", "target_item_id": target}]})[0] == 400
        # Selecao sem linhagem e recusada.
        other = next(item["item_id"] for item in session["items"] if item["item_id"] != target)
        assert _http(runtime, "POST", root + "/inspection-session/reuse", {"expected_revision": reused["revision"], "selections": [{"source_session_id": v1["snapshot"]["session_id"], "source_record_id": "OBSERVATION-V1-001", "target_item_id": other}]})[0] == 400
        # Decisao de reaproveitamento nao e forjavel pelo save generico.
        forged = json.loads(json.dumps(session))
        forged["reuse_decisions"][0]["decided_by"] = "OUTRO-PERFIL"
        assert _http(runtime, "PUT", root + "/inspection-session", {"expected_revision": reused["revision"], "snapshot": forged})[0] == 400
        forged = json.loads(json.dumps(session))
        forged.pop("reuse_decisions")
        assert _http(runtime, "PUT", root + "/inspection-session", {"expected_revision": reused["revision"], "snapshot": forged})[0] == 400
    finally:
        runtime.close()


def test_a_chain_of_successions_keeps_every_unreused_original_offerable_exactly_once(tmp_path):
    """Revisao independente (P1): V1 -> V2 -> V3 nao pode esconder os registros da V1."""
    runtime = _runtime(tmp_path)
    try:
        root, profile, v1, _photo = _inspection_v1_with_field_records_then_analysis_change(runtime)
        v1_session = v1["snapshot"]["session_id"]

        def succeed():
            status, stale = _http(runtime, "GET", root + "/inspection-session")
            assert stale["snapshot"]["upstream_stale"] is True
            status, session = _http(runtime, "POST", root + "/inspection-session/successor", {"expected_revision": stale["revision"], "responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
            assert status == 201, session
            return session

        def change_analysis_and_plan():
            status, case = _http(runtime, "GET", root + "/case-analysis")
            doc = case["snapshot"]["documents"][0]["document_id"]
            status, case = _http(runtime, "POST", root + "/case-analysis/items", {"expected_revision": case["revision"], "item_kind": "PERICIAL_OBJECT", "text": "Objeto sintético adicional.", "source_document_id": doc, "page_or_span": "p. 1", "technical_subjects": ["Superfície"], "values": {}})
            assert status == 200, case
            status, stale = _http(runtime, "GET", root + "/pericial-planning")
            status, plan = _http(runtime, "POST", root + "/pericial-planning/successor", {"expected_revision": stale["revision"], "title": "Plano seguinte"})
            assert status == 201
            for name in ("issues", "inspection_requirements", "question_links"):
                for item in plan["snapshot"][name]:
                    status, plan = _http(runtime, "POST", root + "/pericial-planning/decisions", {"expected_revision": plan["revision"], "target_item_id": item["item_id"], "action": "APPROVE", "reviewer": profile["profile_id"], "reason": "Ok.", "decided_value": None})
                    assert status == 200

        v2 = succeed()
        status, offered = _http(runtime, "GET", root + "/inspection-session/reuse-candidates")
        photo = next(item for item in offered["candidates"] if item["source_record_id"] == "PHOTO-V1-001")
        status, v2 = _http(runtime, "POST", root + "/inspection-session/reuse", {"expected_revision": v2["revision"], "selections": [{key: photo[key] for key in ("source_session_id", "source_record_id", "target_item_id")}]})
        assert status == 200
        copy_id = v2["snapshot"]["reuse_decisions"][0]["target_record_id"]

        change_analysis_and_plan()
        succeed()
        status, offered = _http(runtime, "GET", root + "/inspection-session/reuse-candidates")
        origins = {(item["source_session_id"], item["source_record_id"]) for item in offered["candidates"]}
        # A observacao da V1, nunca reaproveitada na V2, continua oferecivel; a foto
        # aparece uma vez, pela origem real (V1), nunca pela copia que esta na V2.
        assert origins == {(v1_session, "OBSERVATION-V1-001"), (v1_session, "PHOTO-V1-001")}
        assert all(item["source_record_id"] != copy_id for item in offered["candidates"])
    finally:
        runtime.close()


def test_inspection_succession_survives_backup_and_process_restart(tmp_path):
    from scripts.backend_contract.application.models import canonical_payload_json
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, http_request

    runtime = _runtime(tmp_path)
    try:
        root, profile, v1, _photo = _inspection_v1_with_field_records_then_analysis_change(runtime)
        status, stale = _http(runtime, "GET", root + "/inspection-session")
        status, v2 = _http(runtime, "POST", root + "/inspection-session/successor", {"expected_revision": stale["revision"], "responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
        status, offered = _http(runtime, "GET", root + "/inspection-session/reuse-candidates")
        selections = [{"source_session_id": item["source_session_id"], "source_record_id": item["source_record_id"], "target_item_id": item["target_item_id"]} for item in offered["candidates"]]
        status, reused = _http(runtime, "POST", root + "/inspection-session/reuse", {"expected_revision": v2["revision"], "selections": selections})
        assert status == 200
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
    finally:
        runtime.close()
    verified = VerifyWorkspaceBackup().execute(backup)
    # A decisao de reaproveitamento precisa da vistoria de origem no pacote.
    from tests.test_product_integration_oracle_v1 import _reseal
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    orphan = json.loads(backup)
    for item in orphan["artifact_revisions"]:
        if item["artifact_kind"] == "INSPECTION_SESSION_V1" and "reuse_decisions" in item["payload"]:
            for decision in item["payload"]["reuse_decisions"]:
                decision["source_record_id"] = "REGISTRO-INEXISTENTE"
            item["checksum_sha256"] = hashlib.sha256(canonical_payload_json(item["payload"]).encode("utf-8")).hexdigest()
    with pytest.raises(RepositoryIntegrityError, match="reuse origin"):
        VerifyWorkspaceBackup().execute(_reseal(orphan))
    sessions = sorted((item for item in verified.artifact_revisions if item["artifact_kind"] == "INSPECTION_SESSION_V1"), key=lambda item: item["revision"])
    assert sessions[v1["revision"] - 1]["payload"] == v1["snapshot"], "a Vistoria V1 foi reescrita"
    assert sessions[-1]["payload"]["session_id"] == v2["snapshot"]["session_id"]

    # Reinicio real do servico sobre o mesmo armazenamento.
    runtime = _runtime(tmp_path)
    try:
        status, reopened = _http(runtime, "GET", root + "/inspection-session")
        assert status == 200 and reopened["revision"] == reused["revision"]
        assert reopened["snapshot"]["upstream_stale"] is False
        assert reopened["snapshot"]["reuse_decisions"] == reused["snapshot"]["reuse_decisions"]
    finally:
        runtime.close()


def test_save_refuses_succession_over_a_current_session_or_with_field_records():
    from dataclasses import replace

    from scripts.backend_contract.application.vistoria import SaveInspectionSession
    from scripts.backend_contract.vistoria import InspectionReview

    service = SaveInspectionSession(None, None, None, None, None, None, None)
    session = _minimal_session()
    with pytest.raises(ValueError, match="latest revision"):
        service.execute(session.workspace_id, session, None, allow_succession=True)
    with pytest.raises(ValueError, match="without field records"):
        service.execute(session.workspace_id, replace(session, reviews=(InspectionReview("REVIEW", "PERITO", "2026-09-20T10:00:00-03:00", "OK", "Revisão."),)), 1, allow_succession=True)
    with pytest.raises(ValueError, match="ambiguous"):
        service.execute(session.workspace_id, session, 1, allow_succession=True, allow_reuse=True)


def _minimal_session():
    from scripts.backend_contract.vistoria import (
        ExecutionState, InspectionCoverage, InspectionItem, InspectionPlanSnapshot, InspectionSession, LocationReference,
    )

    workspace = "11111111-1111-4111-8111-111111111111"
    return InspectionSession(
        schema_version="1.0.0", session_id="INSPECTION-SESSION-B", workspace_id=workspace,
        plan_snapshot=InspectionPlanSnapshot("PLAN", "PLANNING-SNAPSHOT", 2, "0" * 64, workspace, ("PLAN-ITEM",), 1),
        started_at="2026-09-20T09:00:00-03:00", ended_at=None, location_context="Imóvel", participant_references=(),
        responsible_professional="PERITO", source_revision=1,
        items=(InspectionItem("ITEM", "PLAN-ITEM", "Item", ExecutionState.PENDING, (), (), (), (), None),),
        observations=(), statements=(), measurements=(), measurement_series=(), methods=(), instruments=(),
        instrument_statuses=(), photos=(), videos=(), sketches=(), locations=(LocationReference("LOC", "Imóvel", None),),
        environmental_conditions=(), access_occurrences=(), limitations=(), missing_items=(), evidence_candidates=(),
        coverage=InspectionCoverage(1, 1, 0, 0, 0, 0, 0, False, (), ("Itens de vistoria aguardam execução.",)),
        reviews=(),
    )


def _save_over(predecessor, *, planning=None):
    from contextlib import nullcontext
    from types import SimpleNamespace

    from scripts.backend_contract.application.vistoria import SaveInspectionSession
    from scripts.backend_contract.vistoria import inspection_session_to_mapping

    from scripts.backend_contract.application.models import _freeze_payload

    record = SimpleNamespace(revision=1, payload=_freeze_payload(inspection_session_to_mapping(predecessor)))
    if planning is None:
        from scripts.backend_contract.pericial_planning import pericial_planning_from_mapping
        from tests.test_pericial_planning_v1 import fixture

        planning = pericial_planning_from_mapping(fixture())
    return SaveInspectionSession(
        SimpleNamespace(), SimpleNamespace(execute=lambda *_a: record),
        SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=9), planning)),
        SimpleNamespace(), nullcontext, SimpleNamespace(), SimpleNamespace(),
    )


def test_succession_under_the_guard_requires_a_new_session_identity():
    # O predecessor minimo nao reflete o planejamento canonico: e stale. Mesmo assim a
    # sucessora nao pode reaproveitar a identidade da sessao anterior.
    session = _minimal_session()
    with pytest.raises(ValueError, match="new session identity"):
        _save_over(session).execute(session.workspace_id, session, 1, allow_succession=True)


def _session_with_reused_observation(*, state):
    from dataclasses import replace

    from scripts.backend_contract.vistoria import (
        ExecutionState, FieldObservation, InspectionCoverage, InspectionReuseDecision, ObservationType, ReusedRecordKind,
    )

    base = _minimal_session()
    observation = FieldObservation("OBSERVATION-NEW", "ITEM", ObservationType.DIRECT_OBSERVATION, "Mancha.", "LOC", "2026-09-20T09:30:00-03:00", "PERITO", "Campo.")
    decision = InspectionReuseDecision("REUSE-1", "INSPECTION-SESSION-A", 3, ReusedRecordKind.OBSERVATION, "OBSERVATION-OLD", "OBSERVATION-NEW", "ITEM", "PERITO", "2026-09-21T10:00:00-03:00")
    completed = state is ExecutionState.COMPLETED
    item = replace(base.items[0], observation_ids=("OBSERVATION-NEW",), state=state, note="Executado." if completed else None)
    coverage = InspectionCoverage(1, 0 if completed else 1, 1 if completed else 0, 0, 0, 0, 0, completed, (), ("x",))
    return replace(base, items=(item,), observations=(observation,), coverage=coverage, reuse_decisions=(decision,))


def test_reuse_save_cannot_promote_the_item_execution_state():
    from scripts.backend_contract.vistoria import ExecutionState

    predecessor = _minimal_session()
    promoted = _session_with_reused_observation(state=ExecutionState.COMPLETED)
    with pytest.raises(ValueError, match="execution state"):
        _save_over(predecessor).execute(predecessor.workspace_id, promoted, 1, allow_reuse=True)


def test_reuse_decision_must_bind_a_record_owned_by_the_target_item():
    from dataclasses import replace

    from scripts.backend_contract.vistoria import ExecutionState

    valid = _session_with_reused_observation(state=ExecutionState.PENDING)
    for broken in (
        replace(valid.reuse_decisions[0], target_record_id="OBSERVATION-INEXISTENTE"),
        replace(valid.reuse_decisions[0], target_item_id="OUTRO-ITEM"),
        replace(valid.reuse_decisions[0], source_session_id=valid.session_id),
    ):
        with pytest.raises(ValueError, match="does not bind"):
            replace(valid, reuse_decisions=(broken,))


def test_reuse_refuses_to_bind_a_copied_record_to_a_different_reference_with_the_same_identity(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        root, profile, v1, _photo = _inspection_v1_with_field_records_then_analysis_change(runtime)
        status, stale = _http(runtime, "GET", root + "/inspection-session")
        status, v2 = _http(runtime, "POST", root + "/inspection-session/successor", {"expected_revision": stale["revision"], "responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
        crafted = json.loads(json.dumps(v2["snapshot"]))
        crafted["locations"].append({"location_id": v1["snapshot"]["locations"][0]["location_id"], "description": "Outro cômodo com a mesma identidade", "parent_location_id": None})
        status, v2 = _http(runtime, "PUT", root + "/inspection-session", {"expected_revision": v2["revision"], "snapshot": crafted})
        assert status == 200, v2
        status, offered = _http(runtime, "GET", root + "/inspection-session/reuse-candidates")
        observation = next(item for item in offered["candidates"] if item["source_record_id"] == "OBSERVATION-V1-001")
        selection = {key: observation[key] for key in ("source_session_id", "source_record_id", "target_item_id")}
        assert _http(runtime, "POST", root + "/inspection-session/reuse", {"expected_revision": v2["revision"], "selections": [selection]})[0] == 400
    finally:
        runtime.close()
