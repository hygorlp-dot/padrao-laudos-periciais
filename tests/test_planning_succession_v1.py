"""F7 (#252): plano pericial stale tem caminho explicito de sucessao.

Qualquer escrita na Analise do Caso depois do plano o deixa `upstream_stale`.
Antes desta correcao, decisoes no plano stale respondiam 400 e iniciar outro
plano respondia 409: nao havia caminho normal para um plano atual. O sucessor
nasce so de propostas sobre a analise vigente; o plano anterior e as suas
decisoes continuam como revisoes imutaveis do mesmo artefato.
"""
from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import WorkspaceId
from scripts.backend_contract.application.pericial_planning import SavePericialPlanning
from scripts.backend_contract.pericial_planning import case_analysis_digest, pericial_planning_from_mapping
from tests.test_pericial_planning_v1 import analysis_fixture, artifact, fixture, proposal_only_fixture


def _runtime(tmp_path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN

    runtime = build_local_api(tmp_path / "f7.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    return runtime


def _approved_plan_then_changed_analysis(runtime):
    from tests.test_product_integration_oracle_v1 import _http
    from tests.test_property_record_v1 import _text_pdf

    status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "F7 sintético"})
    assert status == 201
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

    status, v1 = _http(runtime, "POST", root + "/pericial-planning", {"title": "Plano V1"})
    assert status == 201
    v1 = approve_all(v1)
    assert v1["snapshot"]["decisions"]
    status, current = _http(runtime, "GET", root + "/case-analysis")
    accept(second, current["revision"])
    status, stale = _http(runtime, "GET", root + "/pericial-planning")
    assert status == 200 and stale["snapshot"]["upstream_stale"] is True
    return root, profile, v1, stale, approve_all


def test_stale_plan_has_an_explicit_successor_bound_to_the_current_analysis(tmp_path):
    from tests.test_product_integration_oracle_v1 import _http

    runtime = _runtime(tmp_path)
    try:
        root, profile, v1, stale, approve_all = _approved_plan_then_changed_analysis(runtime)
        # O plano stale continua recusando decisoes e nao e recriado pela rota inicial.
        target = stale["snapshot"]["issues"][0]["item_id"] if stale["snapshot"]["issues"] else stale["snapshot"]["inspection_requirements"][0]["item_id"]
        assert _http(runtime, "POST", root + "/pericial-planning/decisions", {"expected_revision": stale["revision"], "target_item_id": target, "action": "APPROVE", "reviewer": profile["profile_id"], "reason": "x", "decided_value": None})[0] == 400
        assert _http(runtime, "POST", root + "/pericial-planning", {"title": "Plano V2"})[0] == 409
        # Revisao desatualizada nao sucede.
        assert _http(runtime, "POST", root + "/pericial-planning/successor", {"expected_revision": stale["revision"] - 1, "title": "Plano V2"})[0] == 409

        status, v2 = _http(runtime, "POST", root + "/pericial-planning/successor", {"expected_revision": stale["revision"], "title": "Plano V2"})
        assert status == 201 and v2["revision"] == stale["revision"] + 1
        snapshot = v2["snapshot"]
        assert snapshot["upstream_stale"] is False
        assert snapshot["plan"]["plan_id"] != v1["snapshot"]["plan"]["plan_id"]
        assert snapshot["snapshot_id"] != v1["snapshot"]["snapshot_id"]
        assert snapshot["decisions"] == []
        assert all(item["professional_review_status"] == "PENDING" for name in ("issues", "inspection_requirements", "question_links") for item in snapshot[name])
        status, current = _http(runtime, "GET", root + "/case-analysis")
        assert snapshot["plan"]["case_analysis_revision"] == current["revision"]
        # A analise vigente tem dois quesitos; o plano sucessor cobre os dois.
        assert len(snapshot["inspection_requirements"]) == 2

        # Um plano vigente nao pode ser sucedido (nada de substituir decisoes atuais).
        assert _http(runtime, "POST", root + "/pericial-planning/successor", {"expected_revision": v2["revision"], "title": "Plano V3"})[0] == 400
        v2 = approve_all(v2)
        status, inspection = _http(runtime, "POST", root + "/inspection-session", {"responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
        assert status == 201
        assert inspection["snapshot"]["plan_snapshot"]["planning_snapshot_id"] == snapshot["snapshot_id"]
    finally:
        runtime.close()


def test_stale_plan_and_its_decisions_survive_succession_in_history_and_backup(tmp_path):
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN, _http, http_request

    runtime = _runtime(tmp_path)
    try:
        root, _profile, v1, stale, _approve_all = _approved_plan_then_changed_analysis(runtime)
        status, v2 = _http(runtime, "POST", root + "/pericial-planning/successor", {"expected_revision": stale["revision"], "title": "Plano V2"})
        assert status == 201
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
    finally:
        runtime.close()
    verified = VerifyWorkspaceBackup().execute(backup)
    plans = sorted((item for item in verified.artifact_revisions if item["artifact_kind"] == "PERICIAL_PLANNING_SNAPSHOT_V1"), key=lambda item: item["revision"])
    predecessor = plans[stale["revision"] - 1]["payload"]
    assert predecessor["plan"]["plan_id"] == v1["snapshot"]["plan"]["plan_id"]
    assert predecessor["decisions"] == v1["snapshot"]["decisions"]
    assert plans[-1]["payload"]["plan"]["plan_id"] == v2["snapshot"]["plan"]["plan_id"]


def _save_with_previous(previous_snapshot, previous_analysis_revision):
    analysis = analysis_fixture()
    analysis_record = artifact(analysis, kind="CASE_ANALYSIS_SNAPSHOT_V1", artifact_id="CASE-ANALYSIS", revision=2)
    previous = replace(previous_snapshot, plan=replace(previous_snapshot.plan, case_analysis_revision=previous_analysis_revision, case_analysis_digest=case_analysis_digest(analysis)))
    previous_record = artifact(previous, kind="PERICIAL_PLANNING_SNAPSHOT_V1", artifact_id="PERICIAL-PLANNING", revision=5)
    calls = []
    service = SavePericialPlanning(
        SimpleNamespace(append_if_latest=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(revision=6)),
        SimpleNamespace(execute=lambda *_args: previous_record),
        SimpleNamespace(execute=lambda _workspace: (analysis_record, analysis)),
        nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 9, 1, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID("88888888-8888-4888-8888-888888888888")),
    )
    return service, analysis, calls


def _successor(snapshot):
    return replace(snapshot, snapshot_id=snapshot.snapshot_id + "-NEXT", plan=replace(snapshot.plan, plan_id=snapshot.plan.plan_id + "-NEXT", case_analysis_revision=2))


def test_save_accepts_succession_only_over_a_stale_predecessor_with_a_new_proposal_only_plan():
    base = pericial_planning_from_mapping(proposal_only_fixture())
    workspace = WorkspaceId.parse(base.workspace_id)
    successor = _successor(base)

    service, _analysis, calls = _save_with_previous(base, previous_analysis_revision=1)
    assert service.execute(workspace, successor, 5, allow_succession=True).revision == 6
    assert calls[0]["expected_revision"] == 5

    # Predecessor ainda vigente: sucessao recusada sob a guarda, mesmo sem o pre-check do comando.
    service, _analysis, calls = _save_with_previous(base, previous_analysis_revision=2)
    with pytest.raises(ValueError, match="only a stale"):
        service.execute(workspace, successor, 5, allow_succession=True)
    assert calls == []

    service, _analysis, _calls = _save_with_previous(base, previous_analysis_revision=1)
    same_identity = replace(successor, plan=replace(successor.plan, plan_id=base.plan.plan_id))
    with pytest.raises(ValueError, match="new plan identity"):
        service.execute(workspace, same_identity, 5, allow_succession=True)

    decided = _successor(pericial_planning_from_mapping(fixture()))
    with pytest.raises(ValueError, match="proposal-only"):
        service.execute(workspace, decided, 5, allow_succession=True)
    with pytest.raises(ValueError, match="stale predecessor revision"):
        service.execute(workspace, successor, None, allow_succession=True)


def test_ordinary_save_still_cannot_swap_the_plan_identity():
    base = pericial_planning_from_mapping(proposal_only_fixture())
    service, _analysis, _calls = _save_with_previous(base, previous_analysis_revision=2)
    with pytest.raises(ValueError, match="identity cannot be replaced"):
        service.execute(WorkspaceId.parse(base.workspace_id), _successor(base), 5)
