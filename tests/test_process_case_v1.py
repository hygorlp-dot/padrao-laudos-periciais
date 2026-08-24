import http.client
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import (
    PericiaWorkspace,
    ProcessCaseData,
    ProcessCaseSnapshot,
    WorkspaceId,
    thaw_payload,
)
from scripts.backend_contract.application.ports import WorkspaceNotFound
from scripts.backend_contract.application.services import GetProcessCase, SaveProcessCase
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
from scripts.backend_contract.local_api.transport import LocalApi, LocalApiServices
from scripts.backend_contract.product_bridge.composition import build_product_runtime


WORKSPACE_A = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
WORKSPACE_B = WorkspaceId(UUID("22222222-2222-4222-8222-222222222222"))
REVISION_1 = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
REVISION_2 = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
REVISION_3 = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOW_1 = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
NOW_2 = datetime(2026, 8, 24, 15, 1, tzinfo=UTC)
NOW_3 = datetime(2026, 8, 24, 15, 2, tzinfo=UTC)
TOKEN = "process-case-local-token-with-sufficient-entropy"

EMPTY_DATA = {
    "numero_processo": "",
    "tribunal": "",
    "vara": "",
    "comarca_municipio": "",
    "uf": "",
    "parte_requerente": "",
    "parte_requerida": "",
}

DATA_A = {
    "numero_processo": "0000001-00.2026.8.05.0001",
    "tribunal": "  Tribunal de Justiça da Bahia  ",
    "vara": "2ª Vara Cível",
    "comarca_municipio": "Salvador",
    "uf": "BA",
    "parte_requerente": "Pessoa requerente",
    "parte_requerida": "Pessoa requerida",
}

DATA_B = {
    "numero_processo": "0000002-00.2026.8.26.0002",
    "tribunal": "Tribunal de Justiça de São Paulo",
    "vara": "1ª Vara",
    "comarca_municipio": "Campinas",
    "uf": "SP",
    "parte_requerente": "Parte B autora",
    "parte_requerida": "Parte B ré",
}

CORRECTED_A = {
    **DATA_A,
    "vara": "3ª Vara Cível — corrigida",
    "parte_requerida": "Pessoa requerida corrigida",
}


class SequenceClock:
    def __init__(self, *values):
        self._values = iter(values)

    def now(self):
        return next(self._values)


class SequenceIds:
    def __init__(self, *values):
        self._values = iter(values)

    def new_uuid(self):
        return next(self._values)


class RecordingService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class FailingService:
    def __init__(self, error):
        self.error = error

    def execute(self, *_args, **_kwargs):
        raise self.error


def local_api_services(**overrides):
    workspace = PericiaWorkspace(WORKSPACE_A, "Perícia A", NOW_1.isoformat())
    snapshot = ProcessCaseSnapshot(
        workspace_id=WORKSPACE_A,
        revision=1,
        updated_at=NOW_1.isoformat(),
        data=ProcessCaseData.from_mapping(DATA_A),
    )
    defaults = {
        "create_workspace": RecordingService(workspace),
        "get_workspace": RecordingService(workspace),
        "list_workspaces": RecordingService((workspace,)),
        "append_artifact_revision": RecordingService(None),
        "get_latest_artifact": RecordingService(None),
        "get_artifact_revision": RecordingService(None),
        "list_artifact_revisions": RecordingService(()),
        "get_process_case": RecordingService(snapshot),
        "save_process_case": RecordingService(snapshot),
    }
    defaults.update(overrides)
    return LocalApiServices(**defaults)


def local_api_request(api, method, target, *, body=None, token=TOKEN):
    import json

    encoded = b"" if body is None else json.dumps(
        body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    headers = {
        "Host": "127.0.0.1",
        "Content-Length": str(len(encoded)),
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if method == "POST" and token is not None:
        headers["X-Local-API-Token"] = token
    return api.handle(method, target, headers, encoded)


def decoded(response):
    return json.loads(response.body.decode("utf-8"))


def frontend_build(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
    return root


def bridge_request(runtime, method, target, *, body=None):
    encoded = None if body is None else json.dumps(
        body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    headers = {}
    if encoded is not None:
        headers = {
            "Origin": runtime.origin,
            "Sec-Fetch-Site": "same-origin",
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
        }
    connection = http.client.HTTPConnection(*runtime.address, timeout=5)
    try:
        connection.request(method, target, body=encoded, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def bridge_raw_request(runtime, method, target, *, body=None, headers=None):
    encoded = None if body is None else json.dumps(
        body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    request_headers = dict(headers or {})
    if encoded is not None:
        request_headers.setdefault("Content-Type", "application/json")
        request_headers.setdefault("Content-Length", str(len(encoded)))
    connection = http.client.HTTPConnection(*runtime.address, timeout=5)
    try:
        connection.request(method, target, body=encoded, headers=request_headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def create_workspace(store, workspace_id, name, created_at=NOW_1):
    return store.workspaces.create(
        PericiaWorkspace(workspace_id, name, created_at.isoformat())
    )


def test_application_returns_explicit_empty_process_case_for_existing_workspace(tmp_path):
    with SQLiteApplicationStore(tmp_path / "empty-process-case.db") as store:
        create_workspace(store, WORKSPACE_A, "Perícia A")

        snapshot = GetProcessCase(store.workspaces, store.revisions).execute(WORKSPACE_A)

    assert snapshot.workspace_id == WORKSPACE_A
    assert snapshot.revision is None
    assert snapshot.updated_at is None
    assert snapshot.data.as_dict() == EMPTY_DATA


def test_application_saves_reads_and_corrects_without_silent_loss(tmp_path):
    with SQLiteApplicationStore(tmp_path / "correct-process-case.db") as store:
        create_workspace(store, WORKSPACE_A, "Perícia A")
        save = SaveProcessCase(
            store.workspaces,
            store.revisions,
            SequenceClock(NOW_1, NOW_2),
            SequenceIds(REVISION_1, REVISION_2),
        )
        get = GetProcessCase(store.workspaces, store.revisions)

        first = save.execute(WORKSPACE_A, ProcessCaseData.from_mapping(DATA_A))
        second = save.execute(WORKSPACE_A, ProcessCaseData.from_mapping(CORRECTED_A))
        latest = get.execute(WORKSPACE_A)
        persisted_first = store.revisions.get_revision(
            WORKSPACE_A, "PROCESS_CASE", "PROCESS_CASE", 1
        )

    assert first.revision == 1
    assert second.revision == 2
    assert latest == second
    assert latest.data.as_dict() == CORRECTED_A
    assert latest.data.tribunal == "  Tribunal de Justiça da Bahia  "
    assert persisted_first is not None
    assert thaw_payload(persisted_first.payload) == DATA_A


def test_application_missing_workspace_fails_for_get_and_save(tmp_path):
    with SQLiteApplicationStore(tmp_path / "missing-process-case.db") as store:
        get = GetProcessCase(store.workspaces, store.revisions)
        save = SaveProcessCase(
            store.workspaces,
            store.revisions,
            SequenceClock(NOW_1),
            SequenceIds(REVISION_1),
        )

        with pytest.raises(WorkspaceNotFound):
            get.execute(WORKSPACE_A)
        with pytest.raises(WorkspaceNotFound):
            save.execute(WORKSPACE_A, ProcessCaseData.from_mapping(DATA_A))


@pytest.mark.parametrize(
    "invalid",
    (
        {key: value for key, value in DATA_A.items() if key != "uf"},
        {**DATA_A, "unexpected": "value"},
        {**DATA_A, "tribunal": None},
        {**DATA_A, "tribunal": "\ud800"},
    ),
)
def test_application_process_case_contract_fails_closed_for_invalid_data(invalid):
    with pytest.raises((TypeError, ValueError)):
        ProcessCaseData.from_mapping(invalid)


def test_sqlite_reopen_keeps_latest_corrections_and_workspace_isolation(tmp_path):
    database = tmp_path / "process-case-reopen.db"
    with SQLiteApplicationStore(database) as store:
        create_workspace(store, WORKSPACE_A, "Perícia A", NOW_1)
        create_workspace(store, WORKSPACE_B, "Perícia B", NOW_2)
        save = SaveProcessCase(
            store.workspaces,
            store.revisions,
            SequenceClock(NOW_1, NOW_2, NOW_3),
            SequenceIds(REVISION_1, REVISION_2, REVISION_3),
        )
        save.execute(WORKSPACE_A, ProcessCaseData.from_mapping(DATA_A))
        save.execute(WORKSPACE_B, ProcessCaseData.from_mapping(DATA_B))
        save.execute(WORKSPACE_A, ProcessCaseData.from_mapping(CORRECTED_A))

    with SQLiteApplicationStore(database) as reopened:
        get = GetProcessCase(reopened.workspaces, reopened.revisions)
        restored_a = get.execute(WORKSPACE_A)
        restored_b = get.execute(WORKSPACE_B)
        history_a = reopened.revisions.list_all(
            WORKSPACE_A, "PROCESS_CASE", "PROCESS_CASE"
        )
        history_b = reopened.revisions.list_all(
            WORKSPACE_B, "PROCESS_CASE", "PROCESS_CASE"
        )

    assert restored_a.revision == 2
    assert restored_a.data.as_dict() == CORRECTED_A
    assert restored_b.revision == 1
    assert restored_b.data.as_dict() == DATA_B
    assert [thaw_payload(item.payload) for item in history_a] == [DATA_A, CORRECTED_A]
    assert [thaw_payload(item.payload) for item in history_b] == [DATA_B]


def test_local_api_get_process_case_returns_deterministic_snapshot():
    service = RecordingService(
        ProcessCaseSnapshot(
            workspace_id=WORKSPACE_A,
            revision=None,
            updated_at=None,
            data=ProcessCaseData.empty(),
        )
    )
    api = LocalApi(local_api_services(get_process_case=service), token=TOKEN)

    response = local_api_request(
        api,
        "GET",
        f"/v1/workspaces/{WORKSPACE_A}/process-case",
    )

    assert response.status == 200
    assert decoded(response) == {
        "workspace_id": str(WORKSPACE_A),
        "revision": None,
        "updated_at": None,
        "data": EMPTY_DATA,
    }
    assert service.calls == [((WORKSPACE_A,), {})]


def test_local_api_post_process_case_preserves_exact_data_and_returns_revision():
    snapshot = ProcessCaseSnapshot(
        workspace_id=WORKSPACE_A,
        revision=2,
        updated_at=NOW_2.isoformat(),
        data=ProcessCaseData.from_mapping(CORRECTED_A),
    )
    service = RecordingService(snapshot)
    api = LocalApi(local_api_services(save_process_case=service), token=TOKEN)

    response = local_api_request(
        api,
        "POST",
        f"/v1/workspaces/{WORKSPACE_A}/process-case",
        body={"data": CORRECTED_A},
    )

    assert response.status == 200
    assert decoded(response) == {
        "workspace_id": str(WORKSPACE_A),
        "revision": 2,
        "updated_at": NOW_2.isoformat(),
        "data": CORRECTED_A,
    }
    args, kwargs = service.calls[0]
    assert kwargs == {}
    assert args[0] == WORKSPACE_A
    assert args[1].as_dict() == CORRECTED_A


def test_local_api_process_case_maps_missing_workspace_without_leaking_identity():
    api = LocalApi(
        local_api_services(
            get_process_case=FailingService(WorkspaceNotFound("private identity"))
        ),
        token=TOKEN,
    )

    response = local_api_request(
        api,
        "GET",
        f"/v1/workspaces/{WORKSPACE_A}/process-case",
    )

    assert response.status == 404
    assert decoded(response) == {
        "error": {
            "code": "WORKSPACE_NOT_FOUND",
            "message": "workspace não encontrado",
        }
    }


@pytest.mark.parametrize(
    "body",
    (
        {},
        {"data": {key: value for key, value in DATA_A.items() if key != "uf"}},
        {"data": {**DATA_A, "unexpected": "value"}},
        {"data": {**DATA_A, "uf": None}},
        {"data": DATA_A, "unexpected": True},
    ),
)
def test_local_api_process_case_rejects_malformed_body_without_calling_service(body):
    service = RecordingService(None)
    api = LocalApi(local_api_services(save_process_case=service), token=TOKEN)

    response = local_api_request(
        api,
        "POST",
        f"/v1/workspaces/{WORKSPACE_A}/process-case",
        body=body,
    )

    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"
    assert service.calls == []


def test_local_api_process_case_requires_token_and_rejects_unsupported_method():
    bundle = local_api_services()
    api = LocalApi(bundle, token=TOKEN)
    target = f"/v1/workspaces/{WORKSPACE_A}/process-case"

    forbidden = local_api_request(api, "POST", target, body={"data": DATA_A}, token=None)
    unsupported = local_api_request(api, "PUT", target)

    assert forbidden.status == 403
    assert unsupported.status == 405
    assert bundle.save_process_case.calls == []


def test_product_bridge_forwards_only_exact_process_case_route_end_to_end(tmp_path):
    runtime = build_product_runtime(
        tmp_path / "process-case-bridge.db",
        frontend_build(tmp_path),
        token=TOKEN,
    )
    try:
        runtime.start()
        created_status, created = bridge_request(
            runtime,
            "POST",
            "/app-api/v1/workspaces",
            body={"name": "Pericia do processo"},
        )
        workspace_id = created["workspace_id"]
        target = f"/app-api/v1/workspaces/{workspace_id}/process-case"

        empty_status, empty = bridge_request(runtime, "GET", target)
        saved_status, saved = bridge_request(
            runtime, "POST", target, body={"data": DATA_A}
        )
        restored_status, restored = bridge_request(runtime, "GET", target)
        near_miss_status, near_miss = bridge_request(runtime, "GET", target + "/extra")
    finally:
        runtime.close()

    assert created_status == 201
    assert (empty_status, empty["data"], empty["revision"]) == (200, EMPTY_DATA, None)
    assert (saved_status, saved["data"], saved["revision"]) == (200, DATA_A, 1)
    assert (restored_status, restored) == (200, saved)
    assert near_miss_status == 404
    assert near_miss["error"]["code"] == "NOT_FOUND"


def test_product_bridge_process_case_mutation_requires_exact_same_origin(tmp_path):
    runtime = build_product_runtime(
        tmp_path / "process-case-origin.db",
        frontend_build(tmp_path),
        token=TOKEN,
    )
    try:
        runtime.start()
        _, created = bridge_request(
            runtime,
            "POST",
            "/app-api/v1/workspaces",
            body={"name": "Pericia protegida"},
        )
        target = f"/app-api/v1/workspaces/{created['workspace_id']}/process-case"

        blocked_status, blocked = bridge_raw_request(
            runtime,
            "POST",
            target,
            body={"data": DATA_A},
            headers={
                "Origin": "https://attacker.invalid",
                "Sec-Fetch-Site": "cross-site",
            },
        )
        _, restored = bridge_request(runtime, "GET", target)
    finally:
        runtime.close()

    assert blocked_status == 403
    assert blocked["error"]["code"] == "FORBIDDEN_PRODUCT_REQUEST"
    assert restored["revision"] is None
    assert restored["data"] == EMPTY_DATA


def test_real_vertical_slice_corrects_reopens_and_isolates_workspaces(tmp_path):
    database = tmp_path / "real-process-case.db"
    build = frontend_build(tmp_path)
    first_runtime = build_product_runtime(database, build, token=TOKEN)
    try:
        first_runtime.start()
        _, workspace_a = bridge_request(
            first_runtime,
            "POST",
            "/app-api/v1/workspaces",
            body={"name": "Pericia A"},
        )
        _, workspace_b = bridge_request(
            first_runtime,
            "POST",
            "/app-api/v1/workspaces",
            body={"name": "Pericia B"},
        )
        target_a = f"/app-api/v1/workspaces/{workspace_a['workspace_id']}/process-case"
        target_b = f"/app-api/v1/workspaces/{workspace_b['workspace_id']}/process-case"

        empty_status, empty_a = bridge_request(first_runtime, "GET", target_a)
        first_status, first_a = bridge_request(
            first_runtime, "POST", target_a, body={"data": DATA_A}
        )
        saved_b_status, saved_b = bridge_request(
            first_runtime, "POST", target_b, body={"data": DATA_B}
        )
        corrected_status, corrected_a = bridge_request(
            first_runtime, "POST", target_a, body={"data": CORRECTED_A}
        )
    finally:
        first_runtime.close()

    reopened_runtime = build_product_runtime(database, build, token=TOKEN)
    try:
        reopened_runtime.start()
        restored_a_status, restored_a = bridge_request(reopened_runtime, "GET", target_a)
        restored_b_status, restored_b = bridge_request(reopened_runtime, "GET", target_b)
    finally:
        reopened_runtime.close()

    assert (empty_status, empty_a["revision"], empty_a["data"]) == (200, None, EMPTY_DATA)
    assert (first_status, first_a["revision"], first_a["data"]) == (200, 1, DATA_A)
    assert (saved_b_status, saved_b["revision"], saved_b["data"]) == (200, 1, DATA_B)
    assert (corrected_status, corrected_a["revision"], corrected_a["data"]) == (
        200,
        2,
        CORRECTED_A,
    )
    assert (restored_a_status, restored_a) == (200, corrected_a)
    assert (restored_b_status, restored_b) == (200, saved_b)
