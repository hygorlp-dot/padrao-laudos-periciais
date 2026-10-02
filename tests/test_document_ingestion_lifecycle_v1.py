"""#266: importacao de PJe realista respondia erro e concluia em background.

Reproducao causal na fronteira real `Product Bridge <-> Local API <->
ImportCaseDocumentWithMetadata`: os bytes eram persistidos primeiro, a derivacao
(extracao/OCR/inventario PJe/metadados) seguia dentro da mesma requisicao e o
bridge desistia no seu timeout de transporte. O navegador recebia 503
("Armazenamento local indisponivel") sobre uma fonte que ja estava salva, e o
processamento terminava sozinho depois.

O atraso e injetado no adaptador PJe real (o leitor do export continua sendo o de
producao); nenhum `sleep` no frontend.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig
from tests.test_product_bridge_v1 import browser_mutation_headers, frontend_build, request

TOKEN = "t" * 43


class SlowPjeIntake:
    """Adaptador PJe de producao com uma derivacao deliberadamente lenta."""

    def __init__(self, delay: float):
        from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

        self._inner = PjeIntakeAdapter()
        self.delay = delay
        self.started = threading.Event()
        self.finished = threading.Event()

    def logical_inventory(self, pdf, workdir):
        self.started.set()
        try:
            time.sleep(self.delay)
            return self._inner.logical_inventory(pdf, workdir)
        finally:
            self.finished.set()


def _synthetic_pje(tmp_path, marker="ingestao-266"):
    from tests.test_pje_multisource_identity_v1 import _distinct_pje_pdf

    return _distinct_pje_pdf(tmp_path / f"{marker}.pdf", marker).read_bytes()


def _workspace(runtime):
    status, _, body = request(runtime, "POST", "/app-api/v1/workspaces", headers=browser_mutation_headers(runtime), body={"name": "Ingestão sintética"})
    assert status == 201, body
    return json.loads(body)["workspace_id"]


def _import(runtime, workspace_id, content, filename="autos.pdf"):
    return request(
        runtime, "POST", f"/app-api/v1/workspaces/{workspace_id}/materials",
        headers={**browser_mutation_headers(runtime), "Content-Type": "application/pdf", "X-Document-Filename": filename},
        raw_body=content,
    )


def _materials(runtime, workspace_id):
    status, _, body = request(runtime, "GET", f"/app-api/v1/workspaces/{workspace_id}/materials")
    assert status == 200, body
    return json.loads(body)["items"]


def test_red_slow_derivation_over_bridge_timeout_is_not_a_terminal_failure(tmp_path):
    """RED de #266: bytes aceitos + derivacao mais longa que o timeout do bridge."""
    slow = SlowPjeIntake(delay=3.0)
    runtime = build_product_runtime(
        tmp_path / "product.db", frontend_build(tmp_path), token=TOKEN, private_root=tmp_path / "private",
        pje_intake=slow, config=ProductBridgeConfig(upstream_timeout_seconds=1.5),
    )
    runtime.start()
    try:
        workspace_id = _workspace(runtime)
        content = _synthetic_pje(tmp_path)
        status, _, body = _import(runtime, workspace_id, content)
        assert slow.finished.wait(30), "a derivacao nunca terminou"
        # A ordem causal do finding: a fonte foi persistida e a derivacao terminou.
        materials = _materials(runtime, workspace_id)
        assert len(materials) == 1
        # Contrato: se a fonte foi aceita, a resposta nao pode ser falha terminal.
        assert status < 500, f"falso erro terminal {status} sobre fonte ja persistida: {body[:200]!r}"
    finally:
        runtime.close()


# ----------------------------------------------------------------- T1-T10 (#266)

import os  # noqa: E402
from pathlib import Path  # noqa: E402

from scripts.backend_contract.local_api.composition import build_local_api  # noqa: E402
from tests.test_document_intake_v1 import provision_private_root  # noqa: E402
from tests.test_product_integration_oracle_v1 import http_request  # noqa: E402

PDF_HEADERS = {"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"}


class GatedPjeIntake:
    """Adaptador PJe de producao cuja derivacao so termina quando liberada."""

    def __init__(self, *, fail=False):
        from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

        self._inner = PjeIntakeAdapter()
        self.started = threading.Event()
        self.release = threading.Event()
        self.fail = fail
        self.calls = 0

    def logical_inventory(self, pdf, workdir):
        self.calls += 1
        self.started.set()
        assert self.release.wait(60), "derivacao nunca liberada"
        if self.fail:
            raise RuntimeError("falha sintetica do leitor")
        return self._inner.logical_inventory(pdf, workdir)


def _local(tmp_path, name, adapter, grace=0.5):
    private = tmp_path / f"{name}-private"
    if not private.exists():
        provision_private_root(private)
    runtime = build_local_api(
        tmp_path / f"{name}.sqlite3", private_root=private, token=TOKEN, pje_intake=adapter,
        ingestion_grace_seconds=grace,
    )
    runtime.start()
    return runtime


def _api(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})}, timeout=30.0,
    )
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw


def _ws(runtime, name="Caso"):
    status, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": name})
    assert status == 201
    return workspace["workspace_id"]


def _post(runtime, workspace_id, content):
    return _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=content, headers=PDF_HEADERS)


def _states(runtime, workspace_id):
    status, envelope = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/material-processing")
    assert status == 200, envelope
    return {item["content_id"]: item["state"] for item in envelope["items"]}


def _until(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condicao nao alcancada")


def _coverage_incomplete(runtime, workspace_id):
    status, analysis = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
    if status == 409:
        status, analysis = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
    assert status in {200, 201}, analysis
    coverage = analysis["snapshot"]["coverage"]
    return coverage["status"] != "COMPLETE" and coverage["documents_failed"] >= 1


def test_t1_small_document_is_ready_in_the_same_response(tmp_path):
    from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

    runtime = _local(tmp_path, "t1", PjeIntakeAdapter(), grace=10.0)
    try:
        workspace_id = _ws(runtime)
        status, material = _post(runtime, workspace_id, _synthetic_pje(tmp_path))
        assert status == 201, material
        assert _states(runtime, workspace_id) == {material["content_id"]: "READY"}
    finally:
        runtime.close()


def test_t2_t3_t8_slow_document_is_accepted_processing_and_ready_later_through_the_bridge(tmp_path):
    gate = GatedPjeIntake()
    runtime = build_product_runtime(
        tmp_path / "t2.db", frontend_build(tmp_path), token=TOKEN, private_root=tmp_path / "t2-private",
        pje_intake=gate, config=ProductBridgeConfig(upstream_timeout_seconds=1.5),
    )
    runtime.start()
    try:
        workspace_id = _workspace(runtime)
        content = _synthetic_pje(tmp_path)
        began = time.monotonic()
        status, _, body = _import(runtime, workspace_id, content)
        assert status == 202, body
        assert time.monotonic() - began < 1.5, "a resposta tem de chegar antes do timeout do transporte"
        material = json.loads(body)
        root = f"/app-api/v1/workspaces/{workspace_id}"
        # T3: "recarregar a pagina" sao requisicoes novas; o estado persiste.
        for _ in range(2):
            assert [item["content_id"] for item in _materials(runtime, workspace_id)] == [material["content_id"]]
            status, _, raw = request(runtime, "GET", root + "/material-processing")
            assert status == 200 and json.loads(raw)["items"] == [{"content_id": material["content_id"], "state": "PROCESSING"}]
        # Enquanto processa, nao ha inventario logico sobre o qual agir.
        assert request(runtime, "GET", root + "/pje-intake")[0] == 404
        gate.release.set()

        def ready():
            status, _, raw = request(runtime, "GET", root + "/material-processing")
            return json.loads(raw)["items"][0]["state"] == "READY"

        _until(ready)
        # T8: o inventario pronto continua ligado a fonte exata.
        status, _, raw = request(runtime, "GET", root + "/pje-intake")
        inventory = json.loads(raw)["intakes"][0]["inventory"]
        assert status == 200 and inventory["status"] == "OK"
        assert inventory["storage_content_id"] == material["content_id"]
        assert inventory["source_sha256"] == material["checksum_sha256"]
        assert inventory["workspace_id"] == workspace_id
    finally:
        gate.release.set()
        runtime.close()


def test_t4_restart_mid_processing_is_interrupted_never_ready_and_retry_completes(tmp_path):
    from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

    gate = GatedPjeIntake()
    runtime = _local(tmp_path, "t4", gate)
    try:
        workspace_id = _ws(runtime)
        content = _synthetic_pje(tmp_path)
        status, material = _post(runtime, workspace_id, content)
        assert status == 202 and gate.started.wait(10)
        began = time.monotonic()
    finally:
        runtime.close()
    assert time.monotonic() - began < 15, "o encerramento nao pode ficar preso a derivacao"
    # A derivacao sobrevivente e liberada DEPOIS do fechamento: nao pode gravar nada.
    gate.release.set()
    time.sleep(0.5)

    runtime = _local(tmp_path, "t4", PjeIntakeAdapter())
    try:
        assert _states(runtime, workspace_id) == {material["content_id"]: "INTERRUPTED"}
        assert _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")[0] == 404
        assert _coverage_incomplete(runtime, workspace_id)
        status, result = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/material-processing/{material['content_id']}", value={})
        assert status in {200, 202}, result
        _until(lambda: _states(runtime, workspace_id) == {material["content_id"]: "READY"})
        status, materials = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert [item["content_id"] for item in materials["items"]] == [material["content_id"]]
    finally:
        runtime.close()


def test_t5_t10_same_bytes_retry_and_concurrent_imports_share_one_source_authority(tmp_path):
    gate = GatedPjeIntake()
    runtime = _local(tmp_path, "t5", gate)
    try:
        workspace_id = _ws(runtime)
        content = _synthetic_pje(tmp_path)
        results = []
        threads = [threading.Thread(target=lambda: results.append(_post(runtime, workspace_id, content))) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
        assert sorted(status for status, _ in results) == [202, 202, 202]
        assert len({material["content_id"] for _, material in results}) == 1
        status, again = _post(runtime, workspace_id, content)
        assert status == 202 and again["content_id"] == results[0][1]["content_id"]
        gate.release.set()
        _until(lambda: set(_states(runtime, workspace_id).values()) == {"READY"})
        status, after = _post(runtime, workspace_id, content)
        assert status == 200 and after["content_id"] == again["content_id"]
        status, materials = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert len(materials["items"]) == 1
        assert gate.calls == 1, "pedidos repetidos dispararam derivacoes duplicadas"
    finally:
        gate.release.set()
        runtime.close()


def test_t6_real_storage_failure_fails_and_never_becomes_processing(tmp_path, monkeypatch):
    from scripts.backend_contract.application.ports import RepositoryError
    from scripts.backend_contract.infrastructure.private_filesystem import LocalPrivateContentStore
    from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

    runtime = _local(tmp_path, "t6", PjeIntakeAdapter())
    try:
        workspace_id = _ws(runtime)

        def refuse(self, metadata, content):
            raise RepositoryError("disco cheio sintetico")

        monkeypatch.setattr(LocalPrivateContentStore, "store", refuse)
        status, _body = _post(runtime, workspace_id, _synthetic_pje(tmp_path))
        assert status == 503
        assert _states(runtime, workspace_id) == {}
        assert _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")[1]["items"] == []
    finally:
        runtime.close()


def test_t7_extraction_failure_is_failed_preserves_bytes_and_explicit_retry_recovers(tmp_path):
    gate = GatedPjeIntake(fail=True)
    gate.release.set()
    runtime = _local(tmp_path, "t7", gate, grace=10.0)
    try:
        workspace_id = _ws(runtime)
        content = _synthetic_pje(tmp_path)
        status, material = _post(runtime, workspace_id, content)
        assert status == 202, material
        assert _states(runtime, workspace_id) == {material["content_id"]: "FAILED"}
        assert _coverage_incomplete(runtime, workspace_id)
        status, raw = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials/{material['content_id']}")
        assert status == 200 and raw == content, "os bytes da fonte se perderam com a falha"
        gate.fail = False
        status, result = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/material-processing/{material['content_id']}", value={})
        assert status == 200 and result == {"content_id": material["content_id"], "state": "READY"}
        unknown = "00000000-0000-4000-8000-000000000099"
        assert _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/material-processing/{unknown}", value={})[0] == 404
        assert _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/material-processing/{material['content_id']}", value={"force": True})[0] == 400
    finally:
        runtime.close()


def test_t9_same_bytes_in_two_workspaces_are_independent_sources(tmp_path):
    gate = GatedPjeIntake()
    gate.release.set()
    runtime = _local(tmp_path, "t9", gate, grace=10.0)
    try:
        first, second = _ws(runtime, "A"), _ws(runtime, "B")
        content = _synthetic_pje(tmp_path)
        _s, a = _post(runtime, first, content)
        _s, b = _post(runtime, second, content)
        assert a["content_id"] != b["content_id"] and a["checksum_sha256"] == b["checksum_sha256"]
        assert _states(runtime, first) == {a["content_id"]: "READY"}
        assert _states(runtime, second) == {b["content_id"]: "READY"}
        # Uma fonte de A nao e alcancavel pelo workspace B.
        assert _api(runtime, "POST", f"/v1/workspaces/{second}/material-processing/{a['content_id']}", value={})[0] == 404
        for workspace_id, material in ((first, a), (second, b)):
            inventory = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")[1]["intakes"][0]["inventory"]
            assert inventory["workspace_id"] == workspace_id and inventory["storage_content_id"] == material["content_id"]
    finally:
        runtime.close()


def test_f8_delivery_support_file_never_enters_the_case_material_pipeline(tmp_path):
    from tests.test_property_record_v1 import _text_pdf

    gate = GatedPjeIntake()
    gate.release.set()
    runtime = _local(tmp_path, "f8", gate, grace=10.0)
    try:
        workspace_id = _ws(runtime)
        status, support = _api(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/delivery-supporting-files",
            body=_text_pdf(["ANEXO DE APOIO", "Planilha sintética."]),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "apoio.pdf"},
        )
        assert status == 201, support
        assert _states(runtime, workspace_id) == {}
        assert _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/material-processing/{support['content_id']}", value={})[0] == 404
        assert gate.calls == 0
    finally:
        runtime.close()


def test_backup_mid_processing_carries_the_source_and_never_claims_ready(tmp_path):
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

    gate = GatedPjeIntake()
    runtime = _local(tmp_path, "bk", gate, grace=0.5)
    try:
        workspace_id = _ws(runtime)
        content = _synthetic_pje(tmp_path)
        status, material = _post(runtime, workspace_id, content)
        # O backup e tirado COM a derivacao em curso (retida no leitor PJe).
        assert status == 202 and gate.started.wait(10)
        assert _states(runtime, workspace_id) == {material["content_id"]: "PROCESSING"}
        status, _headers, package = http_request(
            runtime.server, "POST", f"/v1/workspaces/{workspace_id}/backup", value={}, headers={"X-Local-API-Token": TOKEN},
        )
        assert status == 200
    finally:
        gate.fail = True
        gate.release.set()
        runtime.close()
    verified = VerifyWorkspaceBackup().execute(package)
    carried = [item for item in verified.private_contents if item.get("content_id") == material["content_id"]]
    assert len(carried) == 1, "o backup perdeu a fonte aceita durante o processamento"
    assert carried[0].get("checksum_sha256", material["checksum_sha256"]) == material["checksum_sha256"]
    kinds = {item["artifact_kind"] for item in verified.artifact_revisions}
    assert "PROCESS_METADATA_EXTRACTION" not in kinds, "o backup afirmaria uma derivacao concluida"
    if os.name != "nt":
        pytest.skip("staging/promote de recovery mutavel e suportado somente no Windows; verify ja provado acima")
    recovered = _local(tmp_path, "bk-recovered", PjeIntakeAdapter(), grace=10.0)
    try:
        status, staged = _api(recovered, "POST", "/v1/recovery/staging", body=package, headers={"Content-Type": "application/octet-stream"})
        assert status == 201, staged
        status, promoted = _api(recovered, "POST", f"/v1/recovery/{staged['recovery_id']}/promote", value={"confirm": True})
        assert status == 200, promoted
        assert _states(recovered, workspace_id) == {material["content_id"]: "INTERRUPTED"}
        status, _r = _api(recovered, "POST", f"/v1/workspaces/{workspace_id}/material-processing/{material['content_id']}", value={})
        assert status in {200, 202}
        _until(lambda: _states(recovered, workspace_id) == {material["content_id"]: "READY"})
    finally:
        recovered.close()


# ------------------------------------------------------- unidades do executor (#266)


class _Record:
    def __init__(self, workspace_id="w", content_id="c"):
        self.workspace_id = workspace_id
        self.content_id = content_id


def test_queue_coalesces_requests_for_the_same_source_and_reports_failure():
    from scripts.backend_contract.application.document_ingestion import DocumentDerivationQueue

    release = threading.Event()
    ran = []

    def derive(record, should_continue):
        ran.append(record.content_id)
        assert release.wait(10)
        if record.content_id == "bad":
            raise RuntimeError("falha")

    queue = DocumentDerivationQueue(derive)
    queue.start()
    try:
        first = queue.submit(_Record())
        assert queue.submit(_Record()) is first, "dois jobs para a mesma fonte"
        assert queue.state_of(_Record()) == "PROCESSING"
        bad = queue.submit(_Record(content_id="bad"))
        release.set()
        assert first.wait(10) and bad.wait(10)
        assert ran == ["c", "bad"]
        assert queue.state_of(_Record()) is None
        assert queue.state_of(_Record(content_id="bad")) == "FAILED"
        # Nova tentativa limpa a falha anterior enquanto roda.
        retry = queue.submit(_Record(content_id="bad"))
        assert retry.wait(10) and queue.state_of(_Record(content_id="bad")) == "FAILED"
    finally:
        queue.close()
    with pytest.raises(RuntimeError):
        queue.submit(_Record(content_id="late"))


def test_cancelled_derivation_commits_no_authoritative_artifact(tmp_path):
    """Cancelada, a derivacao nao grava inventario nem metadados (o cache de paginas
    OCR, que e enderecado pelo SHA da fonte e nao decide nada, pode ter sido gravado)."""
    from scripts.backend_contract.application.document_ingestion import DerivationCancelled
    from scripts.backend_contract.application.models import WorkspaceId
    from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

    runtime = _local(tmp_path, "cancel", PjeIntakeAdapter(), grace=0.0)
    try:
        workspace_id = _ws(runtime)
        # O importador real da composicao (o mesmo que o executor chama).
        importer = runtime._derivations._derive.__self__  # noqa: SLF001
        # So a FASE 1: nenhuma derivacao e agendada por `accept`.
        record, created = importer.accept(
            workspace_id=WorkspaceId.parse(workspace_id), original_filename="autos.pdf",
            content=_synthetic_pje(tmp_path), media_type="application/pdf",
        )
        assert created and not importer.is_derived(record)
        with pytest.raises(DerivationCancelled):
            importer.derive(record, lambda: False)
        assert not importer.is_derived(record)
        assert _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")[0] == 404
    finally:
        runtime.close()


def test_derivation_refuses_to_commit_for_a_source_that_is_no_longer_a_case_document(tmp_path):
    """Entre aceitar e gravar a derivacao passam minutos; a fonte e reconferida sob a
    guarda de autoridade (recuperacao/papeis podem ter mudado). Sem ela, nada e gravado."""
    import dataclasses

    from scripts.backend_contract.application.models import WorkspaceId
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter

    class _NoCaseDocuments:
        def execute(self, workspace_id):
            return ()

    runtime = _local(tmp_path, "vanished", PjeIntakeAdapter(), grace=0.0)
    try:
        workspace_id = _ws(runtime)
        importer = runtime._derivations._derive.__self__  # noqa: SLF001
        record, _created = importer.accept(
            workspace_id=WorkspaceId.parse(workspace_id), original_filename="autos.pdf",
            content=_synthetic_pje(tmp_path), media_type="application/pdf",
        )
        detached = dataclasses.replace(importer, existing_documents=_NoCaseDocuments())
        with pytest.raises(RepositoryIntegrityError, match="documento do caso"):
            detached.derive(record)
        assert not importer.is_derived(record)
        assert _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")[0] == 404
    finally:
        runtime.close()


def test_ready_source_stays_ready_when_a_later_inventory_repair_fails(tmp_path):
    """Metadados gravados sao a autoridade de pronto: uma falha em memoria no reparo
    do inventario PJe nao pode rebaixar a fonte para FAILED."""
    private = tmp_path / "repair-private"
    provision_private_root(private)
    database = tmp_path / "repair.sqlite3"
    legacy = build_local_api(database, private_root=private, token=TOKEN)
    legacy.start()
    try:
        workspace_id = _ws(legacy)
        content = _synthetic_pje(tmp_path)
        status, material = _post(legacy, workspace_id, content)
        assert status == 201 and _states(legacy, workspace_id) == {material["content_id"]: "READY"}
    finally:
        legacy.close()
    broken = GatedPjeIntake(fail=True)
    broken.release.set()
    runtime = _local(tmp_path, "repair", broken, grace=10.0)
    try:
        status, again = _post(runtime, workspace_id, content)
        assert broken.calls == 1, "o reparo do inventario ausente deveria ter sido tentado"
        assert status == 200 and again["content_id"] == material["content_id"]
        assert _states(runtime, workspace_id) == {material["content_id"]: "READY"}
    finally:
        runtime.close()


def test_reimporting_a_complete_source_answers_ready_even_behind_a_long_derivation(tmp_path):
    from tests.test_property_record_v1 import _text_pdf

    gate = GatedPjeIntake()
    gate.release.set()
    runtime = _local(tmp_path, "busy", gate, grace=10.0)
    try:
        workspace_id = _ws(runtime)
        ready_bytes = _synthetic_pje(tmp_path)
        status, ready = _post(runtime, workspace_id, ready_bytes)
        assert status == 201
        gate.release.clear()
        status, slow = _post(runtime, workspace_id, _text_pdf(["OUTRO DOCUMENTO", "Conteudo sintetico."]))
        # Outro documento ocupa o worker unico (leitor PJe retido)...
        assert gate.started.wait(10)
        began = time.monotonic()
        status, again = _post(runtime, workspace_id, ready_bytes)
        # ...e a fonte ja completa responde pronta, sem esperar a fila.
        assert status == 200 and again["content_id"] == ready["content_id"]
        assert time.monotonic() - began < 5
        assert _states(runtime, workspace_id)[ready["content_id"]] == "READY"
    finally:
        gate.release.set()
        runtime.close()



_CLOSE_RACE = """
import pathlib, sys, tempfile, threading, uuid
from scripts.backend_contract.application.models import WorkspaceId
from scripts.backend_contract.application.ports import RepositoryError
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
for _ in range(100):
    store = SQLiteApplicationStore(pathlib.Path(tempfile.mkdtemp()) / "x.sqlite3")
    workspace = WorkspaceId.parse(str(uuid.uuid4()))
    stop = threading.Event()
    def reader():
        while not stop.is_set():
            try:
                store.revisions.latest(workspace, "K", "a")
            except RepositoryError:
                return
    thread = threading.Thread(target=reader)
    thread.start()
    store.close()
    thread.join(5)
    stop.set()
print("CLOSED_CLEANLY")
"""


def test_closing_the_store_under_a_surviving_reader_fails_cleanly_instead_of_crashing():
    """Auditoria da #266 (P1): o worker de derivacao pode sobreviver a espera limitada do
    `close()` e estar dentro de uma chamada SQLite quando a conexao fecha. Fechar sem a
    trava da conexao derrubava o processo (SIGSEGV); fechado sob a trava, o leitor recebe
    um erro de repositorio limpo. Roda num processo filho: o crash nao pode levar junto o
    executor de testes."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", _CLOSE_RACE], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(Path(__file__).resolve().parents[1]), os.environ.get("PYTHONPATH", "")]))},
    )
    assert result.returncode == 0 and "CLOSED_CLEANLY" in result.stdout, (result.returncode, result.stderr[-2000:])


def test_a_base_exception_in_one_job_does_not_kill_the_only_worker():
    """Auditoria da #266 (P2): SystemExit numa derivacao matava o worker unico e todo
    job seguinte ficava PROCESSING para sempre."""
    from scripts.backend_contract.application.document_ingestion import DocumentDerivationQueue

    def derive(record, should_continue):
        if record.content_id == "exit":
            raise SystemExit(3)

    queue = DocumentDerivationQueue(derive)
    queue.start()
    try:
        assert queue.submit(_Record(content_id="exit")).wait(10)
        assert queue.state_of(_Record(content_id="exit")) == "FAILED"
        assert queue.submit(_Record(content_id="next")).wait(10), "o worker morreu"
        assert queue.state_of(_Record(content_id="next")) is None
    finally:
        queue.close()

