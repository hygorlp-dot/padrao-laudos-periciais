"""Situacao do fluxo pericial: projecao somente leitura (#291, UX inc-2).

Dois niveis:
- unidade: `GetWorkflowStatus` sobre snapshots REAIS de dominio (fixtures
  sinteticas validadas), com autoridades falsas so na borda de leitura;
- integracao: runtime real (SQLite + armazenamento privado + Local API + Product
  Bridge), sem nenhuma substituicao do caminho sob teste.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.backend_contract.application.document_ingestion import FAILED, INTERRUPTED, PROCESSING, READY
from scripts.backend_contract.application.models import _freeze_payload
from scripts.backend_contract.application.ports import ArtifactRevisionNotFound, RepositoryError, WorkspaceNotFound
from scripts.backend_contract.application.workflow_status import (
    STAGES,
    GetWorkflowStatus,
    StageReason,
    StageStatus,
    workflow_status_to_mapping,
)
from scripts.backend_contract.budget_foundation import budget_snapshot_from_mapping
from scripts.backend_contract.case_analysis import (
    CASE_ANALYSIS_ARTIFACT_KIND,
    case_analysis_from_mapping,
)
from scripts.backend_contract.construction_defect_analysis import (
    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
    construction_defect_analysis_from_mapping,
)
from scripts.backend_contract.delivery_foundation import (
    DELIVERY_SNAPSHOT_ARTIFACT_KIND,
    DeliveryRole,
    DeliveryState,
)
from scripts.backend_contract.pericial_planning import PERICIAL_PLANNING_ARTIFACT_KIND, pericial_planning_from_mapping
from scripts.backend_contract.report_foundation import REPORT_SNAPSHOT_ARTIFACT_KIND, ReportState, report_snapshot_from_mapping
from scripts.backend_contract.technical_findings import TECHNICAL_SNAPSHOT_ARTIFACT_KIND, technical_snapshot_from_mapping
from scripts.backend_contract.vistoria import INSPECTION_SESSION_ARTIFACT_KIND, inspection_session_from_mapping
from scripts.backend_contract.application.budget_foundation import BUDGET_SNAPSHOT_ARTIFACT_KIND

FIXTURES = Path(__file__).resolve().parent / "fixtures"
WS = "11111111-1111-4111-8111-111111111111"


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _record(revision=1, payload=None):
    return SimpleNamespace(
        revision=revision, created_at="2026-10-07T12:00:00Z",
        payload=_freeze_payload(payload) if payload is not None else None,
    )


class _Reads:
    """`consistent_reads` observavel: toda leitura tem de acontecer aqui dentro."""

    def __init__(self):
        self.depth = 0
        self.entered = 0

    @contextmanager
    def __call__(self):
        self.depth += 1
        self.entered += 1
        try:
            yield
        finally:
            self.depth -= 1


class _Getter:
    def __init__(self, reads, value=None, error=None):
        self._reads, self._value, self._error = reads, value, error
        self.calls = 0

    def execute(self, workspace_id):
        assert self._reads.depth == 1, "leitura fora da janela consistente"
        assert str(workspace_id) == WS
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._value


class _Revisions:
    def __init__(self, reads, present):
        self._reads, self._present = reads, dict(present)

    def latest(self, workspace_id, kind, artifact_id):
        assert self._reads.depth == 1, "leitura fora da janela consistente"
        return self._present.get(kind)


class _Ingestion:
    def __init__(self, reads, states):
        self._reads, self._states = reads, states

    def states(self, workspace_id):
        assert self._reads.depth == 1
        return tuple((SimpleNamespace(), state) for state in self._states)


def _service(*, present=None, getters=None, materials=(), metadata="WAITING_FOR_DOCUMENTS", process_revision=None,
             with_delivery=True, workspace_error=None):
    reads = _Reads()
    getters = getters or {}

    def getter(name):
        value = getters.get(name)
        if isinstance(value, Exception):
            return _Getter(reads, error=value)
        return _Getter(reads, value=value)

    workspace = _Getter(reads, value=SimpleNamespace(workspace_id=WS), error=workspace_error)
    service = GetWorkflowStatus(
        get_workspace=workspace,
        revisions=_Revisions(reads, present or {}),
        consistent_reads=reads,
        get_process_case=_Getter(reads, value=SimpleNamespace(
            revision=process_revision, updated_at=None if process_revision is None else "2026-10-07T12:00:00Z",
        )),
        get_case_analysis=getter("analise"),
        get_pericial_planning=getter("planejamento"),
        get_inspection_session=getter("vistoria"),
        get_technical_snapshot=getter("tecnico"),
        get_construction_defect_analysis=getter("analise-tecnica"),
        get_report_snapshot=getter("laudo"),
        get_budget_snapshot=getter("orcamento"),
        get_process_metadata_review=_Getter(reads, value=SimpleNamespace(state=metadata)),
        ingestion=_Ingestion(reads, materials),
        get_delivery_snapshot=getter("exportar") if with_delivery else None,
    )
    return service, reads


def _by_stage(status):
    return {item.stage: item for item in status.stages}


def _codes(stage):
    return {reason.code: reason.count for reason in stage.reasons}


# --------------------------------------------------------------------------- unidade


def test_first_open_reports_every_catalog_stage_without_inventing_progress():
    service, reads = _service()
    status = service.execute(WS)
    stages = _by_stage(status)

    assert tuple(stages) == STAGES
    assert reads.entered == 1 and reads.depth == 0
    assert {item.state for item in status.stages} == {"NOT_STARTED", "NOT_TRACKED"}
    assert stages["recuperacao"].state == "NOT_TRACKED" and "MANAGEMENT_TOOL" in _codes(stages["recuperacao"])
    assert "OPTIONAL_STAGE" in _codes(stages["orcamento"])
    assert "NO_PROCESS_DATA" in _codes(stages["processo"])
    assert "REPORT_NOT_STARTED" in _codes(stages["revisao"])
    assert all(item.revision is None for item in status.stages)


def test_record_existence_is_never_promoted_to_completion():
    report = report_snapshot_from_mapping(_fixture("report-snapshot-v1"))
    draft = replace(report, state=ReportState.DRAFT, review_decisions=(), coverage=replace(report.coverage, complete=False))
    planning = pericial_planning_from_mapping(_fixture("pericial-planning-snapshot-v1"))
    persisted_draft = _fixture("report-snapshot-v1")
    persisted_draft |= {"state": "DRAFT", "review_decisions": [], "coverage": persisted_draft["coverage"] | {"complete": False}}
    service, _ = _service(
        present={REPORT_SNAPSHOT_ARTIFACT_KIND: _record(3, persisted_draft), PERICIAL_PLANNING_ARTIFACT_KIND: _record(2)},
        getters={"laudo": (_record(3, persisted_draft), draft), "planejamento": (_record(2), planning)},
    )
    stages = _by_stage(service.execute(WS))

    assert stages["laudo"].state == "IN_PROGRESS" and stages["laudo"].decision == "NONE"
    assert stages["revisao"].state == "NOT_STARTED" and "REPORT_NOT_REVIEWED" in _codes(stages["revisao"])
    # 16 itens materiais aguardam decisao: plano existente nao e plano pronto.
    assert stages["planejamento"].state == "AWAITING_REVIEW"
    assert _codes(stages["planejamento"])["ITEMS_AWAITING_REVIEW"] == 16
    assert stages["planejamento"].decision == "PARTIAL"
    assert not any(item.state in {"READY", "APPROVED"} for item in stages.values())


def test_approved_report_over_changed_source_keeps_history_but_requires_review():
    persisted = _fixture("report-snapshot-v1")
    report = report_snapshot_from_mapping(persisted)
    assert report.state is ReportState.APPROVED
    # Exatamente o que a reconciliacao do dominio devolve quando a base muda.
    reconciled = replace(
        report, state=ReportState.DRAFT, review_decisions=(),
        coverage=replace(report.coverage, complete=False), upstream_stale=True,
        upstream_stale_reasons=("case analysis content changed", "inspection revision changed"),
    )
    record = _record(7, persisted)
    service, _ = _service(present={REPORT_SNAPSHOT_ARTIFACT_KIND: record}, getters={"laudo": (record, reconciled)})
    stages = _by_stage(service.execute(WS))

    for key in ("laudo", "revisao"):
        stage = stages[key]
        assert (stage.state, stage.currency, stage.decision) == ("REVIEW_REQUIRED", "STALE", "APPROVED")
        assert _codes(stage)["UPSTREAM_CHANGED"] == 2 and "REPORT_APPROVED" in _codes(stage)
        assert stage.revision == 7
    # Texto livre interno nao sai da projecao: so codigos e contagens.
    assert "case analysis" not in json.dumps(workflow_status_to_mapping(service.execute(WS)))


def test_current_approved_report_is_approved_in_both_stages():
    persisted = _fixture("report-snapshot-v1")
    record = _record(4, persisted)
    service, _ = _service(present={REPORT_SNAPSHOT_ARTIFACT_KIND: record},
                          getters={"laudo": (record, report_snapshot_from_mapping(persisted))})
    stages = _by_stage(service.execute(WS))
    assert stages["laudo"].state == stages["revisao"].state == "APPROVED"
    assert stages["laudo"].currency == "CURRENT"


def test_stale_planning_is_review_required_and_keeps_partial_decisions():
    planning = pericial_planning_from_mapping(_fixture("pericial-planning-snapshot-v1"))
    stale = replace(planning, upstream_stale=True, upstream_stale_reasons=("Case Analysis content changed",))
    service, _ = _service(present={PERICIAL_PLANNING_ARTIFACT_KIND: _record(5)}, getters={"planejamento": (_record(5), stale)})
    stage = _by_stage(service.execute(WS))["planejamento"]
    assert (stage.state, stage.currency, stage.decision) == ("REVIEW_REQUIRED", "STALE", "PARTIAL")
    assert _codes(stage) == {"UPSTREAM_CHANGED": 1, "ITEMS_AWAITING_REVIEW": 16}


@pytest.mark.parametrize(
    ("metadata", "materials", "confirmation", "expected", "code"),
    [
        ("EXTRACTED", (READY,), False, "AWAITING_REVIEW", "METADATA_AWAITING_CONFIRMATION"),
        ("PARTIAL", (READY,), False, "AWAITING_REVIEW", "METADATA_PARTIAL_AWAITING_CONFIRMATION"),
        ("CONFIRMED", (READY,), True, "RECORDED", "METADATA_CONFIRMED"),
        ("EXTRACTED", (READY,), True, "REVIEW_REQUIRED", "METADATA_CONFIRMATION_OUTDATED"),
        ("CONFLICT", (READY,), False, "ATTENTION", "METADATA_CONFLICT"),
        # Extracao ausente durante a derivacao NAO e erro: ainda esta processando.
        ("ERROR", (PROCESSING,), False, "PROCESSING", "MATERIALS_PROCESSING"),
        ("ERROR", (FAILED,), False, "ATTENTION", "METADATA_EXTRACTION_FAILED"),
    ],
)
def test_process_stage_separates_extraction_review_and_confirmation(metadata, materials, confirmation, expected, code):
    present = {"PROCESS_METADATA_CONFIRMATION": _record(1)} if confirmation else {}
    service, _ = _service(present=present, materials=materials, metadata=metadata, process_revision=2)
    stage = _by_stage(service.execute(WS))["processo"]
    assert stage.state == expected and code in _codes(stage)
    if expected == "REVIEW_REQUIRED":
        assert stage.currency == "STALE" and stage.decision == "COMPLETE"


def test_manual_process_data_without_documents_is_a_recorded_fact():
    service, _ = _service(process_revision=1)
    stage = _by_stage(service.execute(WS))["processo"]
    assert stage.state == "RECORDED" and "PROCESS_DATA_RECORDED" in _codes(stage)


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ((READY, READY), "RECORDED"),
        ((READY, PROCESSING), "PROCESSING"),
        ((READY, PROCESSING, FAILED), "ATTENTION"),
        ((INTERRUPTED,), "ATTENTION"),
    ],
)
def test_material_states_are_counted_not_collapsed(states, expected):
    service, _ = _service(materials=states)
    stage = _by_stage(service.execute(WS))["materiais"]
    assert stage.state == expected
    assert sum(reason.count for reason in stage.reasons) == len(states)


def test_case_analysis_pending_conflict_and_changed_sources():
    case = case_analysis_from_mapping(_fixture("case-analysis-snapshot-v1"))
    service, _ = _service(present={CASE_ANALYSIS_ARTIFACT_KIND: _record(2)}, getters={"analise": (_record(2), case)})
    stage = _by_stage(service.execute(WS))["analise"]
    assert stage.state == "AWAITING_REVIEW" and _codes(stage)["CONFLICTS_AWAITING_REVIEW"] == 1
    assert "COVERAGE_PARTIAL" in _codes(stage)

    changed = replace(case, source_inventory_stale=True, unindexed_source_count=2)
    service, _ = _service(present={CASE_ANALYSIS_ARTIFACT_KIND: _record(2)}, getters={"analise": (_record(2), changed)})
    stage = _by_stage(service.execute(WS))["analise"]
    assert (stage.state, stage.currency) == ("REVIEW_REQUIRED", "STALE")
    assert _codes(stage)["SOURCES_NOT_INDEXED"] == 2


def test_inspection_limitations_are_recorded_facts_not_failures():
    session = inspection_session_from_mapping(_fixture("inspection-session-v1"))
    service, _ = _service(present={INSPECTION_SESSION_ARTIFACT_KIND: _record(3)}, getters={"vistoria": (_record(3), session)})
    stage = _by_stage(service.execute(WS))["vistoria"]
    assert stage.state == "RECORDED"
    assert _codes(stage) == {"ITEMS_COMPLETED": 1, "ITEMS_PARTIAL": 1, "ITEMS_BLOCKED": 1}


def test_technical_snapshot_feeds_evidence_and_findings_separately():
    technical = technical_snapshot_from_mapping(_fixture("technical-snapshot-v1"))
    service, _ = _service(present={TECHNICAL_SNAPSHOT_ARTIFACT_KIND: _record(4)}, getters={"tecnico": (_record(4), technical)})
    stages = _by_stage(service.execute(WS))
    assert stages["evidencias"].state == "RECORDED" and _codes(stages["evidencias"])["EVIDENCE_APPROVED"] == 2
    assert stages["constatacoes"].state == "ATTENTION" and _codes(stages["constatacoes"])["CONFLICTS_UNRESOLVED"] == 1


def test_construction_defect_gate_is_reported_and_blocking_gate_needs_attention():
    analysis = construction_defect_analysis_from_mapping(_fixture("construction-defect-analysis-v1"))
    present = {CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND: _record(2)}
    service, _ = _service(present=present, getters={"analise-tecnica": (_record(2), analysis)})
    stage = _by_stage(service.execute(WS))["analise-tecnica"]
    assert stage.state == "RECORDED" and "GATE_APTO_PARA_REDACAO_COM_RESSALVAS" in _codes(stage)


def _delivery(state=DeliveryState.APPROVED, roles=(DeliveryRole.MAIN_REPORT,)):
    # So o papel dos artefatos e o estado interessam a projecao; o resto da
    # entrega e validado pelo dominio nos testes proprios dela.
    return SimpleNamespace(
        state=state, artifacts=tuple(SimpleNamespace(role=role) for role in roles),
        stale_reasons=(), stale_origin_state=None,
    )


@pytest.mark.parametrize(
    ("snapshot", "expected", "decision", "codes"),
    [
        (_delivery(), "APPROVED", "APPROVED", {"WORD_PRESENT", "PDF_ABSENT"}),
        (_delivery(roles=(DeliveryRole.MAIN_REPORT, DeliveryRole.DERIVED_PDF)), "APPROVED", "APPROVED", {"WORD_PRESENT", "PDF_PRESENT"}),
        (_delivery(state=DeliveryState.DRAFT, roles=()), "IN_PROGRESS", "NONE", {"NO_ARTIFACTS"}),
        (_delivery(state=DeliveryState.READY_FOR_REVIEW), "AWAITING_REVIEW", "NONE", {"PDF_ABSENT"}),
    ],
)
def test_delivery_states_and_partial_delivery_are_explicit(snapshot, expected, decision, codes):
    service, _ = _service(present={DELIVERY_SNAPSHOT_ARTIFACT_KIND: _record(2)}, getters={"exportar": (_record(2), snapshot)})
    stage = _by_stage(service.execute(WS))["exportar"]
    assert (stage.state, stage.decision) == (expected, decision)
    assert codes <= set(_codes(stage))


def test_stale_delivered_package_keeps_origin_decision():
    stale = SimpleNamespace(
        state=DeliveryState.STALE, artifacts=_delivery().artifacts,
        stale_reasons=("REPORT_DIGEST_CHANGED",), stale_origin_state=DeliveryState.DELIVERED,
    )
    service, _ = _service(present={DELIVERY_SNAPSHOT_ARTIFACT_KIND: _record(2)}, getters={"exportar": (_record(2), stale)})
    stage = _by_stage(service.execute(WS))["exportar"]
    assert (stage.state, stage.currency, stage.decision) == ("REVIEW_REQUIRED", "STALE", "APPROVED")


def test_delivery_with_unverifiable_upstream_is_unavailable_not_current():
    snapshot = SimpleNamespace(
        state=DeliveryState.STALE, artifacts=(), stale_reasons=("UPSTREAM_AUTHORITY_UNAVAILABLE",),
        stale_origin_state=DeliveryState.APPROVED,
    )
    service, _ = _service(present={DELIVERY_SNAPSHOT_ARTIFACT_KIND: _record(2)}, getters={"exportar": (_record(2), snapshot)})
    stage = _by_stage(service.execute(WS))["exportar"]
    assert (stage.state, stage.availability) == ("UNAVAILABLE", "UNAVAILABLE")


def test_query_failure_is_unavailable_in_that_stage_only():
    planning = pericial_planning_from_mapping(_fixture("pericial-planning-snapshot-v1"))
    service, _ = _service(
        present={CASE_ANALYSIS_ARTIFACT_KIND: _record(), PERICIAL_PLANNING_ARTIFACT_KIND: _record(2), TECHNICAL_SNAPSHOT_ARTIFACT_KIND: _record()},
        getters={"analise": RepositoryError("falha"), "planejamento": (_record(2), planning), "tecnico": ValueError("corrompido")},
    )
    stages = _by_stage(service.execute(WS))
    assert stages["analise"].state == "UNAVAILABLE" and "QUERY_FAILED" in _codes(stages["analise"])
    # A leitura tecnica e compartilhada: as duas etapas ficam nao verificadas.
    assert stages["evidencias"].state == stages["constatacoes"].state == "UNAVAILABLE"
    assert stages["planejamento"].state == "AWAITING_REVIEW"


def test_upstream_not_found_inside_a_started_stage_is_not_not_started():
    service, _ = _service(
        present={PERICIAL_PLANNING_ARTIFACT_KIND: _record(2)},
        getters={"planejamento": ArtifactRevisionNotFound("analise ausente")},
    )
    assert _by_stage(service.execute(WS))["planejamento"].state == "UNAVAILABLE"


def test_missing_composition_service_is_unavailable_not_empty():
    service, _ = _service(present={DELIVERY_SNAPSHOT_ARTIFACT_KIND: _record(2)}, with_delivery=False)
    stage = _by_stage(service.execute(WS))["exportar"]
    assert stage.state == "UNAVAILABLE" and "SERVICE_UNAVAILABLE" in _codes(stage)

    service = replace(_service()[0], ingestion=None)
    stage = _by_stage(service.execute(WS))["materiais"]
    assert stage.state == "UNAVAILABLE"


def test_unknown_workspace_propagates_instead_of_empty_projection():
    service, _ = _service(workspace_error=WorkspaceNotFound("x"))
    with pytest.raises(WorkspaceNotFound):
        service.execute(WS)


def test_budget_is_optional_management_fact():
    budget = budget_snapshot_from_mapping(_fixture("budget-snapshot-v1"))
    service, _ = _service(present={BUDGET_SNAPSHOT_ARTIFACT_KIND: _record(6)}, getters={"orcamento": (_record(6), budget)})
    stage = _by_stage(service.execute(WS))["orcamento"]
    assert stage.state == "RECORDED" and {"FINANCIAL_PARTIALLY_RECEIVED", "OPTIONAL_STAGE"} <= set(_codes(stage))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"state": "RECORDED", "currency": "STALE"},
        {"state": "APPROVED", "currency": "STALE"},
        {"state": "REVIEW_REQUIRED", "currency": "CURRENT"},
        {"state": "UNAVAILABLE", "availability": "AVAILABLE"},
        {"state": "APPROVED", "revision": None},
        {"state": "DONE"},
    ],
)
def test_stage_status_rejects_false_success(kwargs):
    base = {"stage": "laudo", "state": "APPROVED", "availability": "AVAILABLE", "currency": "CURRENT",
            "decision": "APPROVED", "reasons": (StageReason("REPORT_APPROVED"),), "revision": 1}
    with pytest.raises(ValueError):
        StageStatus(**(base | kwargs))


# ------------------------------------------------------------------------ integracao

from scripts.backend_contract.product_bridge.composition import build_product_runtime  # noqa: E402
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig  # noqa: E402
from tests.test_local_api_v1 import http_request  # noqa: E402
from tests.test_product_bridge_v1 import browser_mutation_headers, frontend_build, request  # noqa: E402

TOKEN = "workflow-status-local-token-with-sufficient-entropy"


class _GatedPjeIntake:
    """Adaptador PJe de producao cuja derivacao espera um sinal (finito) do teste."""

    def __init__(self):
        from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

        self._inner = PjeIntakeAdapter()
        self.release = threading.Event()
        self.started = threading.Event()
        self.finished = threading.Event()

    def logical_inventory(self, pdf, workdir):
        self.started.set()
        try:
            assert self.release.wait(30), "o teste nunca liberou a derivacao"
            return self._inner.logical_inventory(pdf, workdir)
        finally:
            self.finished.set()


@pytest.fixture
def product(tmp_path):
    intake = _GatedPjeIntake()
    runtime = build_product_runtime(
        tmp_path / "product.db", frontend_build(tmp_path), token=TOKEN, private_root=tmp_path / "private",
        pje_intake=intake, config=ProductBridgeConfig(upstream_timeout_seconds=3.0),
    )
    runtime.start()
    try:
        yield runtime, intake
    finally:
        intake.release.set()
        runtime.close()


def _local(runtime, method, path, value=None):
    return http_request(runtime._local_api.server, method, path, value=value, headers={"X-Local-API-Token": TOKEN})


def _new_workspace(runtime, name):
    status, _, body = _local(runtime, "POST", "/v1/workspaces", {"name": name})
    assert status == 201, body
    return json.loads(body)["workspace_id"]


def _status(runtime, workspace_id):
    status, _, body = request(runtime, "GET", f"/app-api/v1/workspaces/{workspace_id}/workflow-status")
    assert status == 200, body
    value = json.loads(body)
    assert value["workspace_id"] == workspace_id
    assert [item["stage"] for item in value["stages"]] == list(STAGES)
    return {item["stage"]: item for item in value["stages"]}


def _persisted(runtime, workspace_id):
    from scripts.backend_contract.application.models import WorkspaceId

    store = runtime._local_api._store
    return [
        (item.artifact_kind, item.artifact_id, item.revision)
        for item in store.revisions.list_workspace(WorkspaceId.parse(workspace_id))
    ]


def test_bridge_route_is_read_only_and_reports_a_new_workspace(product):
    runtime, _ = product
    workspace_id = _new_workspace(runtime, "Perícia sintética")
    before = _persisted(runtime, workspace_id)
    stages = _status(runtime, workspace_id)
    stages_again = _status(runtime, workspace_id)
    assert _persisted(runtime, workspace_id) == before, "a projecao gravou algo"
    assert stages == stages_again
    assert {item["state"] for item in stages.values()} == {"NOT_STARTED", "NOT_TRACKED"}

    status, _, _ = _local(runtime, "POST", f"/v1/workspaces/{workspace_id}/workflow-status", {})
    assert status == 405
    status, _, _ = request(
        runtime, "POST", f"/app-api/v1/workspaces/{workspace_id}/workflow-status",
        headers={**browser_mutation_headers(runtime), "Content-Type": "application/json"}, body={},
    )
    assert status in {404, 405}
    status, _, _ = request(runtime, "GET", "/app-api/v1/workspaces/22222222-2222-4222-8222-222222222222/workflow-status")
    assert status == 404


def test_processing_material_is_processing_then_ready_and_other_workspace_is_isolated(product, tmp_path):
    from tests.test_document_ingestion_lifecycle_v1 import _synthetic_pje

    runtime, intake = product
    first = _new_workspace(runtime, "Perícia A")
    second = _new_workspace(runtime, "Perícia B")
    status, _, body = request(
        runtime, "POST", f"/app-api/v1/workspaces/{first}/materials",
        headers={**browser_mutation_headers(runtime), "Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"},
        raw_body=_synthetic_pje(tmp_path, "workflow-status"),
    )
    assert status == 202, body
    assert intake.started.wait(10)

    during = _status(runtime, first)
    assert during["materiais"]["state"] == "PROCESSING"
    assert during["materiais"]["reasons"] == [{"code": "MATERIALS_PROCESSING", "count": 1}]
    assert during["processo"]["state"] == "PROCESSING", "extracao ausente durante derivacao virou erro"
    assert _status(runtime, second)["materiais"]["state"] == "NOT_STARTED"

    intake.release.set()
    assert intake.finished.wait(30)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        after = _status(runtime, first)
        if after["materiais"]["state"] != "PROCESSING":
            break
        time.sleep(0.05)
    assert after["materiais"]["state"] == "RECORDED"
    assert after["materiais"]["reasons"] == [{"code": "MATERIALS_READY", "count": 1}]
    assert after["processo"]["state"] not in {"NOT_STARTED", "PROCESSING", "RECORDED"}
    assert _status(runtime, second)["materiais"]["state"] == "NOT_STARTED"


def test_one_failing_authority_is_unavailable_and_the_rest_still_answer(product, monkeypatch):
    runtime, _ = product
    workspace_id = _new_workspace(runtime, "Perícia com falha")
    revisions = runtime._local_api._store.revisions
    original = revisions.latest

    def failing(workspace, kind, artifact_id):
        if kind == CASE_ANALYSIS_ARTIFACT_KIND:
            raise RepositoryError("falha sintetica de leitura")
        return original(workspace, kind, artifact_id)

    monkeypatch.setattr(revisions, "latest", failing)
    stages = _status(runtime, workspace_id)
    assert stages["analise"]["state"] == "UNAVAILABLE"
    assert stages["analise"]["availability"] == "UNAVAILABLE"
    assert stages["planejamento"]["state"] == "NOT_STARTED"


def test_concurrent_write_never_lands_inside_a_projection(product, monkeypatch):
    """Coerencia: uma gravacao concorrente espera a projecao inteira terminar."""
    runtime, _ = product
    workspace_id = _new_workspace(runtime, "Perícia concorrente")
    revisions = runtime._local_api._store.revisions
    inside, resume = threading.Event(), threading.Event()
    # A pausa acontece no meio da projecao (depois de `processo`, antes das etapas seguintes).
    original_latest = revisions.latest

    def latest(workspace, kind, artifact_id):
        if kind == CASE_ANALYSIS_ARTIFACT_KIND:
            inside.set()
            assert resume.wait(10)
        return original_latest(workspace, kind, artifact_id)

    monkeypatch.setattr(revisions, "latest", latest)
    projection = {}
    reader = threading.Thread(target=lambda: projection.setdefault("value", _status(runtime, workspace_id)))
    reader.start()
    assert inside.wait(10)

    written = threading.Event()

    def write():
        data = {key: "" for key in (
            "numero_processo", "ramo_justica", "tribunal", "vara", "municipio_sede", "subsecao_judiciaria",
            "comarca_municipio", "uf", "parte_requerente", "parte_requerida",
        )}
        status, _, body = _local(runtime, "POST", f"/v1/workspaces/{workspace_id}/process-case",
                                 {"expected_revision": None, "data": data | {"vara": "Vara sintética"}})
        assert status == 200, body
        written.set()

    writer = threading.Thread(target=write)
    writer.start()
    # A gravacao nao pode concluir enquanto a projecao segura a janela de leitura.
    assert not written.wait(0.5)
    resume.set()
    reader.join(10)
    writer.join(10)
    assert written.is_set()
    assert projection["value"]["processo"]["state"] == "NOT_STARTED"
    monkeypatch.setattr(revisions, "latest", original_latest)
    assert _status(runtime, workspace_id)["processo"]["state"] == "RECORDED"
