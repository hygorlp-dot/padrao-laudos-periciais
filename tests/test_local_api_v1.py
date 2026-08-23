import socket
import sqlite3
import subprocess
import sys
import http.client
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from urllib.parse import quote
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    WorkspaceId,
)
from scripts.backend_contract.application.ports import (
    ArtifactRevisionNotFound,
    PersistenceSchemaError,
    RepositoryConflict,
    RepositoryError,
    RepositoryIntegrityError,
    WorkspaceNotFound,
)
from scripts.backend_contract.local_api.transport import LocalApi, LocalApiServices
from scripts.backend_contract.local_api import server as local_server_module
from scripts.backend_contract.local_api.server import LocalApiServer, LocalServerConfig
from scripts.backend_contract.local_api.composition import (
    LocalApiRuntime,
    LocalApiStartupError,
    build_local_api,
)


WORKSPACE_UUID = UUID("11111111-1111-4111-8111-111111111111")
WORKSPACE_ID = WorkspaceId(WORKSPACE_UUID)
REVISION_UUID = "22222222-2222-4222-8222-222222222222"
CREATED_AT = "2026-08-23T12:30:00+00:00"
TOKEN = "local-test-token-with-sufficient-entropy"


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


class FixedClock:
    def now(self):
        return datetime(2026, 8, 23, 12, 30, tzinfo=UTC)


class SequenceIds:
    def __init__(self, values):
        self._values = iter(values)
        self._lock = Lock()

    def new_uuid(self):
        with self._lock:
            return next(self._values)


class BlockingIds:
    def __init__(self, value):
        self._value = value
        self.entered = Event()
        self.release = Event()

    def new_uuid(self):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test synchronization timed out")
        return self._value


def workspace(name="Perícia sintética"):
    return PericiaWorkspace(WORKSPACE_ID, name, CREATED_AT)


def revision(number=1, payload=None):
    return ArtifactRevision(
        workspace_id=WORKSPACE_ID,
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id=REVISION_UUID,
        revision=number,
        created_at=CREATED_AT,
        checksum_sha256="a" * 64,
        payload={"status": "INCONCLUSIVO"} if payload is None else payload,
    )


def services(**overrides):
    defaults = {
        "create_workspace": RecordingService(workspace()),
        "get_workspace": RecordingService(workspace()),
        "list_workspaces": RecordingService((workspace(),)),
        "append_artifact_revision": RecordingService(revision()),
        "get_latest_artifact": RecordingService(revision()),
        "get_artifact_revision": RecordingService(revision()),
        "list_artifact_revisions": RecordingService((revision(),)),
    }
    defaults.update(overrides)
    return LocalApiServices(**defaults)


def request(api, method, target, *, body=None, headers=None):
    request_headers = {"Host": "127.0.0.1", **(headers or {})}
    if method == "POST":
        request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
        request_headers.setdefault("X-Local-API-Token", TOKEN)
    encoded = b"" if body is None else json.dumps(
        body, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    request_headers.setdefault("Content-Length", str(len(encoded)))
    return api.handle(method, target, request_headers, encoded)


def decoded(response):
    assert response.headers["Content-Type"] == "application/json; charset=utf-8"
    assert response.headers["Content-Length"] == str(len(response.body))
    return json.loads(response.body.decode("utf-8"))


def test_post_workspace_delegates_name_and_serializes_created_model():
    bundle = services()
    response = request(
        LocalApi(bundle, token=TOKEN),
        "POST",
        "/v1/workspaces",
        body={"name": "Perícia sintética"},
    )

    assert response.status == 201
    assert decoded(response) == {
        "created_at": CREATED_AT,
        "name": "Perícia sintética",
        "workspace_id": str(WORKSPACE_UUID),
    }
    assert bundle.create_workspace.calls == [(('Perícia sintética',), {})]


def test_get_workspace_delegates_typed_uuid_and_serializes_model():
    bundle = services()
    response = request(
        LocalApi(bundle, token=TOKEN),
        "GET",
        f"/v1/workspaces/{WORKSPACE_UUID}",
    )

    assert response.status == 200
    assert decoded(response)["workspace_id"] == str(WORKSPACE_UUID)
    assert bundle.get_workspace.calls == [((WORKSPACE_ID,), {})]


def test_list_workspaces_preserves_service_order_and_empty_list():
    first = workspace("Árvore")
    second = PericiaWorkspace(
        WorkspaceId(UUID("33333333-3333-4333-8333-333333333333")),
        "Última",
        "2026-08-23T12:31:00+00:00",
    )
    listed = RecordingService((first, second))
    bundle = services(list_workspaces=listed)

    response = request(LocalApi(bundle, token=TOKEN), "GET", "/v1/workspaces")
    assert response.status == 200
    assert decoded(response) == {
        "items": [
            {
                "created_at": CREATED_AT,
                "name": "Árvore",
                "workspace_id": str(WORKSPACE_UUID),
            },
            {
                "created_at": "2026-08-23T12:31:00+00:00",
                "name": "Última",
                "workspace_id": "33333333-3333-4333-8333-333333333333",
            },
        ]
    }
    assert listed.calls == [((), {})]

    empty = services(list_workspaces=RecordingService(()))
    assert decoded(request(LocalApi(empty, token=TOKEN), "GET", "/v1/workspaces")) == {
        "items": []
    }


def test_post_revision_delegates_exact_identity_and_nested_payload():
    payload = {
        "descrição": "Não constatado ≠ inexistente",
        "ordem": [3, 1, {"unknown": True, "nullable": None}],
    }
    record = revision(payload=payload)
    appended = RecordingService(record)
    bundle = services(append_artifact_revision=appended)
    kind = quote("LAUDO TÉCNICO", safe="")
    artifact = quote("LAU/001", safe="")

    response = request(
        LocalApi(bundle, token=TOKEN),
        "POST",
        f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/{kind}/{artifact}/revisions",
        body={"payload": payload},
    )

    assert response.status == 201
    assert appended.calls == [
        (
            (),
            {
                "workspace_id": WORKSPACE_ID,
                "artifact_kind": "LAUDO TÉCNICO",
                "artifact_id": "LAU/001",
                "payload": payload,
            },
        )
    ]
    assert decoded(response) == {
        "artifact_id": "LAU-001",
        "artifact_kind": "LAUDO",
        "checksum_sha256": "a" * 64,
        "created_at": CREATED_AT,
        "payload": payload,
        "revision": 1,
        "revision_id": REVISION_UUID,
        "workspace_id": str(WORKSPACE_UUID),
    }


def test_get_latest_revision_uses_latest_service():
    latest = RecordingService(revision())
    bundle = services(get_latest_artifact=latest)
    target = (
        f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions/latest"
    )
    response = request(LocalApi(bundle, token=TOKEN), "GET", target)

    assert response.status == 200
    assert latest.calls == [((WORKSPACE_ID, "LAUDO", "LAU-001"), {})]


def test_get_exact_revision_uses_positive_integer_revision():
    exact = RecordingService(revision(7))
    bundle = services(get_artifact_revision=exact)
    target = f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions/7"
    response = request(LocalApi(bundle, token=TOKEN), "GET", target)

    assert response.status == 200
    assert exact.calls == [((WORKSPACE_ID, "LAUDO", "LAU-001", 7), {})]


def test_list_revisions_preserves_order_and_payload_fidelity():
    first = revision(1, {"order": [2, 1], "unknown": {"enabled": False}})
    second = ArtifactRevision(
        workspace_id=WORKSPACE_ID,
        artifact_kind="LAUDO",
        artifact_id="LAU-001",
        revision_id="33333333-3333-4333-8333-333333333333",
        revision=2,
        created_at="2026-08-23T12:31:00+00:00",
        checksum_sha256="b" * 64,
        payload={"order": [], "value": 2},
    )
    listed = RecordingService((first, second))
    bundle = services(list_artifact_revisions=listed)
    target = f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions"
    response = request(LocalApi(bundle, token=TOKEN), "GET", target)

    assert response.status == 200
    result = decoded(response)
    assert [item["revision"] for item in result["items"]] == [1, 2]
    assert result["items"][0]["payload"] == {
        "order": [2, 1],
        "unknown": {"enabled": False},
    }
    assert result["items"][1]["payload"] == {"order": [], "value": 2}
    assert listed.calls == [((WORKSPACE_ID, "LAUDO", "LAU-001"), {})]


@pytest.mark.parametrize(
    ("method", "target", "expected_status", "expected_code"),
    (
        ("GET", "/v1/unknown", 404, "NOT_FOUND"),
        ("DELETE", "/v1/workspaces", 405, "METHOD_NOT_ALLOWED"),
        ("POST", f"/v1/workspaces/{WORKSPACE_UUID}", 405, "METHOD_NOT_ALLOWED"),
        ("GET", "/v1/workspaces/not-a-uuid", 400, "INVALID_REQUEST"),
        (
            "GET",
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions/0",
            400,
            "INVALID_REQUEST",
        ),
        (
            "GET",
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions/not-int",
            400,
            "INVALID_REQUEST",
        ),
        ("GET", "/v1/workspaces?offset=1", 400, "INVALID_REQUEST"),
    ),
)
def test_invalid_routes_methods_and_path_values_fail_explicitly(
    method, target, expected_status, expected_code
):
    response = request(LocalApi(services(), token=TOKEN), method, target)
    assert response.status == expected_status
    assert decoded(response) == {
        "error": {"code": expected_code, "message": "requisição local inválida"}
    }


@pytest.mark.parametrize("malformed", ("%", "%Z0", "%0Z"))
def test_malformed_percent_encoding_is_not_aliased_to_a_literal_path(malformed):
    response = request(LocalApi(services(), token=TOKEN), "GET", f"/v1/{malformed}")
    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "body",
    (
        None,
        {},
        {"name": "válido", "unknown": True},
        {"name": 12},
    ),
)
def test_workspace_dto_requires_exact_text_name(body):
    response = request(
        LocalApi(services(), token=TOKEN), "POST", "/v1/workspaces", body=body
    )
    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("body", (None, {}, {"payload": {}, "unknown": 1}))
def test_revision_dto_requires_exact_payload_field(body):
    target = f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions"
    response = request(LocalApi(services(), token=TOKEN), "POST", target, body=body)
    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"


def test_malformed_utf8_json_and_non_object_json_fail_explicitly():
    api = LocalApi(services(), token=TOKEN)
    headers = {
        "Host": "127.0.0.1",
        "Content-Type": "application/json",
        "Content-Length": "2",
        "X-Local-API-Token": TOKEN,
    }
    malformed = api.handle("POST", "/v1/workspaces", headers, b"\xff\xfe")
    non_object = api.handle("POST", "/v1/workspaces", headers, b"[]")
    for response in (malformed, non_object):
        assert response.status == 400
        assert decoded(response)["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("target", "raw_body", "service_name"),
    (
        (
            "/v1/workspaces",
            b'{"name":"FIRST","name":"SECOND"}',
            "create_workspace",
        ),
        (
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions",
            b'{"payload":{"status":"FIRST","status":"SECOND"}}',
            "append_artifact_revision",
        ),
    ),
)
def test_duplicate_json_object_keys_are_rejected_at_any_depth(
    target, raw_body, service_name
):
    bundle = services()
    response = LocalApi(bundle, token=TOKEN).handle(
        "POST",
        target,
        {
            "Host": "127.0.0.1",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw_body)),
            "X-Local-API-Token": TOKEN,
        },
        raw_body,
    )

    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"
    assert getattr(bundle, service_name).calls == []


@pytest.mark.parametrize("constant", (b"NaN", b"Infinity", b"-Infinity"))
def test_nonstandard_json_numeric_constants_are_rejected(constant):
    bundle = services()
    raw_body = b'{"payload":{"measurement":' + constant + b"}}"
    response = LocalApi(bundle, token=TOKEN).handle(
        "POST",
        f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions",
        {
            "Host": "127.0.0.1",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw_body)),
            "X-Local-API-Token": TOKEN,
        },
        raw_body,
    )

    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"
    assert bundle.append_artifact_revision.calls == []


@pytest.mark.parametrize(
    "number",
    (
        b"0.100000000000000005",
        b"1.0000000000000000001",
        b"9007199254740993.0",
        b"1e400",
        b"-1e400",
        b"1e-400",
    ),
)
def test_json_number_that_cannot_round_trip_without_value_loss_is_rejected(number):
    bundle = services()
    raw_body = b'{"payload":{"measurement":' + number + b"}}"
    response = LocalApi(bundle, token=TOKEN).handle(
        "POST",
        f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions",
        {
            "Host": "127.0.0.1",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw_body)),
            "X-Local-API-Token": TOKEN,
        },
        raw_body,
    )

    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"
    assert bundle.append_artifact_revision.calls == []


@pytest.mark.parametrize(
    "number",
    (b"0.1", b"1.0", b"1e0", b"1.25", b"1e20", b"-0.0"),
)
def test_json_number_with_value_preserving_float_representation_is_accepted(number):
    append = RecordingService(revision())
    bundle = services(append_artifact_revision=append)
    raw_body = b'{"payload":{"measurement":' + number + b"}}"
    response = LocalApi(bundle, token=TOKEN).handle(
        "POST",
        f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions",
        {
            "Host": "127.0.0.1",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw_body)),
            "X-Local-API-Token": TOKEN,
        },
        raw_body,
    )

    assert response.status == 201
    assert append.calls[0][1]["payload"]["measurement"] == float(number)


def test_body_larger_than_configured_limit_is_rejected_before_service_call():
    create = RecordingService(workspace())
    bundle = services(create_workspace=create)
    api = LocalApi(bundle, token=TOKEN, max_body_bytes=8)
    response = request(api, "POST", "/v1/workspaces", body={"name": "long"})
    assert response.status == 400
    assert create.calls == []


def test_transport_does_not_mutate_payload_passed_to_service():
    original = {"nested": {"items": [2, 1]}, "unknown": None}

    class NonMutatingContractService(RecordingService):
        def execute(self, *args, **kwargs):
            snapshot = json.loads(json.dumps(kwargs["payload"], ensure_ascii=False))
            result = super().execute(*args, **kwargs)
            assert kwargs["payload"] == snapshot
            return result

    append = NonMutatingContractService(revision(payload=original))
    bundle = services(append_artifact_revision=append)
    target = f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions"
    response = request(
        LocalApi(bundle, token=TOKEN), "POST", target, body={"payload": original}
    )
    assert response.status == 201
    assert original == {"nested": {"items": [2, 1]}, "unknown": None}


@pytest.mark.parametrize(
    ("override", "method", "target", "body", "error", "status", "code", "message"),
    (
        (
            "get_workspace",
            "GET",
            f"/v1/workspaces/{WORKSPACE_UUID}",
            None,
            WorkspaceNotFound("private path C:/secret.db"),
            404,
            "WORKSPACE_NOT_FOUND",
            "workspace não encontrado",
        ),
        (
            "get_latest_artifact",
            "GET",
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions/latest",
            None,
            ArtifactRevisionNotFound("secret artifact"),
            404,
            "ARTIFACT_REVISION_NOT_FOUND",
            "revisão de artefato não encontrada",
        ),
        (
            "create_workspace",
            "POST",
            "/v1/workspaces",
            {"name": "Duplicado"},
            RepositoryConflict("UNIQUE workspaces.workspace_id"),
            409,
            "REPOSITORY_CONFLICT",
            "conflito de persistência local",
        ),
        (
            "list_workspaces",
            "GET",
            "/v1/workspaces",
            None,
            RepositoryIntegrityError("payload_json secret"),
            500,
            "REPOSITORY_INTEGRITY_FAILURE",
            "integridade da persistência local inválida",
        ),
        (
            "list_workspaces",
            "GET",
            "/v1/workspaces",
            None,
            PersistenceSchemaError("table private_table"),
            500,
            "PERSISTENCE_SCHEMA_FAILURE",
            "schema da persistência local inválido",
        ),
        (
            "list_workspaces",
            "GET",
            "/v1/workspaces",
            None,
            RepositoryError("C:/private/application.db is locked"),
            503,
            "REPOSITORY_UNAVAILABLE",
            "persistência local indisponível",
        ),
    ),
)
def test_application_error_taxonomy_maps_without_internal_detail_leak(
    override, method, target, body, error, status, code, message
):
    bundle = services(**{override: FailingService(error)})
    response = request(LocalApi(bundle, token=TOKEN), method, target, body=body)

    assert response.status == status
    assert decoded(response) == {"error": {"code": code, "message": message}}
    rendered = response.body.decode("utf-8")
    assert str(error) not in rendered
    assert "secret" not in rendered
    assert "private" not in rendered


@pytest.mark.parametrize(
    "host",
    (
        "0.0.0.0",
        "::",
        "192.168.1.50",
        "localhost",
        "api.local",
        "",
    ),
)
def test_server_configuration_rejects_every_nonliteral_ipv4_loopback_bind(host):
    with pytest.raises(ValueError, match="loopback"):
        LocalServerConfig(host=host)


@pytest.mark.parametrize("port", (-1, 65536, 1.5, "8080"))
def test_server_configuration_rejects_invalid_ports(port):
    with pytest.raises((TypeError, ValueError)):
        LocalServerConfig(port=port)


@pytest.mark.parametrize(
    "timeout", (0, -1, True, "5", float("nan"), float("inf"), 31)
)
def test_server_configuration_rejects_invalid_request_timeout(timeout):
    with pytest.raises(ValueError, match="timeout"):
        LocalServerConfig(request_timeout_seconds=timeout)


@pytest.mark.parametrize(
    "token",
    (
        "",
        "short",
        "x" * 31,
        "á" * 32,
        " " * 32,
        " " + "x" * 32,
        "x" * 32 + " ",
        "x" * 16 + " " + "x" * 16,
    ),
)
def test_local_mutation_token_requires_high_entropy_header_safe_shape(token):
    with pytest.raises(ValueError, match="token"):
        LocalApi(services(), token=token)


@pytest.mark.parametrize(
    "token",
    (
        "",
        "short",
        " " * 32,
        " " + "x" * 32,
        "x" * 32 + " ",
        "x" * 16 + " " + "x" * 16,
    ),
)
def test_composition_rejects_invalid_token_before_opening_sqlite(tmp_path, token):
    database = tmp_path / "must-not-open.db"
    with pytest.raises(ValueError, match="token"):
        build_local_api(database, token=token)
    assert not database.exists()


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"Host": "attacker.example"},
        {"Host": "attacker.example:8080"},
        {"Host": "user@127.0.0.1"},
    ),
)
def test_missing_or_nonlocal_host_fails_closed(headers):
    response = LocalApi(services(), token=TOKEN).handle(
        "GET", "/v1/workspaces", headers, b""
    )
    assert response.status == 403
    assert decoded(response)["error"] == {
        "code": "FORBIDDEN_LOCAL_REQUEST",
        "message": "requisição local não autorizada",
    }


@pytest.mark.parametrize(
    "headers",
    (
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Origin": "http://127.0.0.1:3000"},
        {"Sec-Fetch-Site": "cross-site"},
    ),
)
def test_every_browser_origin_or_cross_site_request_is_rejected(headers):
    response = request(
        LocalApi(services(), token=TOKEN),
        "GET",
        "/v1/workspaces",
        headers=headers,
    )
    assert response.status == 403
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize("provided", (None, "", "wrong-token", TOKEN + "x"))
def test_mutations_require_exact_local_token(provided):
    headers = {"X-Local-API-Token": provided} if provided is not None else {}
    api = LocalApi(services(), token=TOKEN)
    encoded = b'{"name":"Pericia"}'
    request_headers = {
        "Host": "127.0.0.1",
        "Content-Type": "application/json",
        "Content-Length": str(len(encoded)),
        **headers,
    }
    response = api.handle("POST", "/v1/workspaces", request_headers, encoded)
    assert response.status == 403
    assert decoded(response)["error"]["code"] == "FORBIDDEN_LOCAL_REQUEST"


def test_transfer_encoding_is_rejected_instead_of_interpreted():
    response = request(
        LocalApi(services(), token=TOKEN),
        "POST",
        "/v1/workspaces",
        body={"name": "Perícia"},
        headers={"Transfer-Encoding": "chunked"},
    )
    assert response.status == 400
    assert decoded(response)["error"]["code"] == "INVALID_REQUEST"


def http_request(server, method, target, *, value=None, headers=None):
    host, port = server.address
    body = None
    request_headers = dict(headers or {})
    if value is not None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(method, target, body=body, headers=request_headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_real_http_server_accepts_local_get_and_exactly_authorized_post():
    bundle = services()
    server = LocalApiServer(
        LocalApi(bundle, token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    try:
        get_status, get_headers, get_body = http_request(
            server, "GET", "/v1/workspaces"
        )
        post_status, post_headers, post_body = http_request(
            server,
            "POST",
            "/v1/workspaces",
            value={"name": "Perícia local"},
            headers={"X-Local-API-Token": TOKEN},
        )
    finally:
        server.close()

    assert get_status == 200
    assert json.loads(get_body.decode("utf-8"))["items"]
    assert post_status == 201
    assert json.loads(post_body.decode("utf-8"))["name"] == "Perícia sintética"
    for headers, body in ((get_headers, get_body), (post_headers, post_body)):
        assert "Access-Control-Allow-Origin" not in headers
        assert TOKEN.encode("utf-8") not in body


def test_real_http_server_blocks_cross_origin_mutation_even_with_valid_token():
    create = RecordingService(workspace())
    bundle = services(create_workspace=create)
    server = LocalApiServer(
        LocalApi(bundle, token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    try:
        status, headers, body = http_request(
            server,
            "POST",
            "/v1/workspaces",
            value={"name": "Blocked"},
            headers={
                "Origin": "https://attacker.example",
                "X-Local-API-Token": TOKEN,
            },
        )
    finally:
        server.close()

    assert status == 403
    assert "Access-Control-Allow-Origin" not in headers
    assert json.loads(body.decode("utf-8"))["error"]["code"] == (
        "FORBIDDEN_LOCAL_REQUEST"
    )
    assert create.calls == []


@pytest.mark.parametrize("method", ("TRACE", "CONNECT", "FROB"))
def test_real_http_server_sanitizes_every_unsupported_method(method):
    server = LocalApiServer(
        LocalApi(services(), token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    try:
        status, headers, body = http_request(server, method, "/v1/workspaces")
    finally:
        server.close()

    assert status == 405
    assert "Server" not in headers
    assert "Date" not in headers
    assert json.loads(body.decode("utf-8"))["error"]["code"] == (
        "METHOD_NOT_ALLOWED"
    )


def test_real_http_head_is_sanitized_without_default_server_fingerprint():
    server = LocalApiServer(
        LocalApi(services(), token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    try:
        status, headers, body = http_request(server, "HEAD", "/v1/workspaces")
    finally:
        server.close()

    assert status == 405
    assert "Server" not in headers
    assert "Date" not in headers
    assert headers["Content-Length"] == "0"
    assert body == b""


def test_deeply_nested_json_returns_sanitized_error_instead_of_dropping_connection():
    server = LocalApiServer(
        LocalApi(services(), token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    host, port = server.address
    body = (
        '{"payload":' + "[" * 20_000 + "0" + "]" * 20_000 + "}"
    ).encode("ascii")
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/workspaces",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Local-API-Token": TOKEN,
            },
        )
        response = connection.getresponse()
        response_body = response.read()
    finally:
        connection.close()
        server.close()

    assert response.status == 400
    assert json.loads(response_body.decode("utf-8"))["error"]["code"] == (
        "INVALID_REQUEST"
    )


def test_oversized_request_line_is_sanitized_before_method_parsing():
    server = LocalApiServer(
        LocalApi(services(), token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    client = socket.create_connection(server.address, timeout=5)
    try:
        client.sendall(
            b"GET /" + b"a" * 70_000 + b" HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        )
        chunks = []
        while chunk := client.recv(65_536):
            chunks.append(chunk)
    finally:
        client.close()
        server.close()

    response = b"".join(chunks)
    assert response.startswith(b"HTTP/1.1 400")
    assert b"BaseHTTP" not in response
    assert b"INVALID_REQUEST" in response


def test_oversized_header_is_sanitized_by_the_parser_error_path():
    server = LocalApiServer(
        LocalApi(services(), token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    client = socket.create_connection(server.address, timeout=5)
    try:
        client.sendall(
            b"GET /v1/workspaces HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Large: "
            + b"a" * 70_000
            + b"\r\n\r\n"
        )
        chunks = []
        while chunk := client.recv(65_536):
            chunks.append(chunk)
    finally:
        client.close()
        server.close()

    response = b"".join(chunks)
    assert response.startswith(b"HTTP/1.1 400")
    assert b"BaseHTTP" not in response
    assert b"INVALID_REQUEST" in response


def test_http09_request_still_receives_explicit_status_line():
    server = LocalApiServer(
        LocalApi(services(), token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    client = socket.create_connection(server.address, timeout=5)
    try:
        client.sendall(b"GET /v1/workspaces\r\n")
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := client.recv(65_536):
            chunks.append(chunk)
    finally:
        client.close()
        server.close()

    response = b"".join(chunks)
    assert response.startswith(b"HTTP/1.1 400")
    assert b"INVALID_REQUEST" in response


@pytest.mark.parametrize(
    "request_bytes",
    (
        b"BOGUS\r\n\r\n",
        b"GET /v1/workspaces NOTHTTP\r\nHost: 127.0.0.1\r\n\r\n",
        b"GET /v1/workspaces HTTP/1.1 EXTRA\r\nHost: 127.0.0.1\r\n\r\n",
        b"GET /v1/workspaces HTTP/2.0\r\nHost: 127.0.0.1\r\n\r\n",
    ),
)
def test_malformed_request_lines_receive_http_status_and_sanitized_json(request_bytes):
    server = LocalApiServer(
        LocalApi(services(), token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    client = socket.create_connection(server.address, timeout=5)
    try:
        client.sendall(request_bytes)
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := client.recv(65_536):
            chunks.append(chunk)
    finally:
        client.close()
        server.close()

    response = b"".join(chunks)
    assert response.startswith(b"HTTP/1.1 400")
    assert b"INVALID_REQUEST" in response
    assert b"BaseHTTP" not in response


@pytest.mark.parametrize(
    ("override", "method", "target", "value"),
    (
        ("create_workspace", "POST", "/v1/workspaces", {"name": "Falha"}),
        ("get_workspace", "GET", f"/v1/workspaces/{WORKSPACE_UUID}", None),
        ("list_workspaces", "GET", "/v1/workspaces", None),
        (
            "append_artifact_revision",
            "POST",
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions",
            {"payload": {}},
        ),
        (
            "get_latest_artifact",
            "GET",
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions/latest",
            None,
        ),
        (
            "get_artifact_revision",
            "GET",
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions/1",
            None,
        ),
        (
            "list_artifact_revisions",
            "GET",
            f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions",
            None,
        ),
    ),
)
def test_unexpected_service_exception_is_sanitized_without_stderr_leak(
    capsys, override, method, target, value
):
    secret = "PRIVATE_TOKEN_payload_xyz"
    bundle = services(**{override: FailingService(RuntimeError(secret))})
    server = LocalApiServer(
        LocalApi(bundle, token=TOKEN), LocalServerConfig(port=0)
    )
    server.start()
    try:
        status, _headers, body = http_request(
            server,
            method,
            target,
            value=value,
            headers={"X-Local-API-Token": TOKEN} if method == "POST" else None,
        )
    finally:
        server.close()

    assert status == 500
    assert json.loads(body.decode("utf-8"))["error"]["code"] == (
        "INTERNAL_SERVER_ERROR"
    )
    assert secret not in body.decode("utf-8")
    assert secret not in capsys.readouterr().err


def test_partial_body_times_out_without_unbounded_shutdown_or_traceback(
    capsys, tmp_path
):
    runtime = build_local_api(
        tmp_path / "partial.db",
        token=TOKEN,
        config=LocalServerConfig(request_timeout_seconds=0.1),
    )
    runtime.start()
    client = socket.create_connection(runtime.address, timeout=5)
    client.sendall(
        b"POST /v1/workspaces HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Type: application/json\r\n"
        b"X-Local-API-Token: "
        + TOKEN.encode("ascii")
        + b"\r\nContent-Length: 100\r\n\r\n{"
    )
    Event().wait(0.05)
    closing = Thread(target=runtime.close)
    closing.start()
    closing.join(timeout=1)
    try:
        assert not closing.is_alive()
        assert "Traceback" not in capsys.readouterr().err
    finally:
        client.close()
        closing.join(timeout=5)


def test_short_body_at_eof_is_rejected_before_any_service_call():
    listed = RecordingService((workspace(),))
    server = LocalApiServer(
        LocalApi(services(list_workspaces=listed), token=TOKEN),
        LocalServerConfig(request_timeout_seconds=1),
    )
    server.start()
    client = socket.create_connection(server.address, timeout=5)
    try:
        client.sendall(
            b"GET /v1/workspaces HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Length: 10\r\n\r\nabc"
        )
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        client.close()
        server.close()

    response = b"".join(chunks)
    assert response.startswith(b"HTTP/1.1 400")
    assert b"INVALID_REQUEST" in response
    assert listed.calls == []


@pytest.mark.parametrize("invalid_style", ("sign", "underscore"))
def test_non_http_decimal_content_length_is_rejected_before_service(invalid_style):
    create = RecordingService(workspace())
    server = LocalApiServer(
        LocalApi(services(create_workspace=create), token=TOKEN),
        LocalServerConfig(request_timeout_seconds=1),
    )
    server.start()
    body = b'{"name":"Valid"}'
    digits = str(len(body))
    raw_length = (
        f"+{digits}"
        if invalid_style == "sign"
        else f"{digits[:-1]}_{digits[-1]}"
    )
    client = socket.create_connection(server.address, timeout=5)
    try:
        client.sendall(
            b"POST /v1/workspaces HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"X-Local-API-Token: "
            + TOKEN.encode("ascii")
            + f"\r\nContent-Length: {raw_length}\r\n\r\n".encode("ascii")
            + body
        )
        chunks = []
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        client.close()
        server.close()

    assert b"".join(chunks).startswith(b"HTTP/1.1 400")
    assert create.calls == []


@pytest.mark.parametrize(
    "request_prefix",
    (
        (
            b"POST /v1/workspaces HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"X-Local-API-Token: "
            + TOKEN.encode("ascii")
            + b"\r\nContent-Length: 100\r\n\r\n{"
        ),
        b"POST /v1/workspaces HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Slow-Header:",
    ),
)
def test_slow_drip_cannot_extend_total_request_deadline(tmp_path, request_prefix):
    runtime = build_local_api(
        tmp_path / "slow-drip.db",
        token=TOKEN,
        config=LocalServerConfig(request_timeout_seconds=0.1),
    )
    runtime.start()
    client = socket.create_connection(runtime.address, timeout=5)
    client.sendall(request_prefix)
    stop_drip = Event()

    def drip_body():
        while not stop_drip.wait(0.04):
            try:
                client.sendall(b" ")
            except OSError:
                return

    dripper = Thread(target=drip_body)
    dripper.start()
    for _ in range(50):
        request_threads = getattr(runtime.server._server, "_threads", ())
        if any(thread.is_alive() for thread in request_threads):
            break
        Event().wait(0.01)
    else:
        pytest.fail("request worker did not start")

    closing = Thread(target=runtime.close)
    closing.start()
    try:
        closing.join(timeout=0.5)
        assert not closing.is_alive()
    finally:
        stop_drip.set()
        client.close()
        dripper.join(timeout=5)
        closing.join(timeout=5)


def test_request_deadline_ends_before_valid_service_execution():
    entered = Event()
    release = Event()

    class SlowCreateService(RecordingService):
        def execute(self, *args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test synchronization timed out")
            return super().execute(*args, **kwargs)

    create = SlowCreateService(workspace())
    server = LocalApiServer(
        LocalApi(services(create_workspace=create), token=TOKEN),
        LocalServerConfig(request_timeout_seconds=0.1),
    )
    server.start()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                http_request,
                server,
                "POST",
                "/v1/workspaces",
                value={"name": "PerÃ­cia sintÃ©tica"},
                headers={"X-Local-API-Token": TOKEN},
            )
            assert entered.wait(timeout=2)
            Event().wait(0.2)
            release.set()
            status, _headers, body = future.result(timeout=2)
    finally:
        release.set()
        server.close()

    assert status == 201
    assert json.loads(body.decode("utf-8"))["workspace_id"] == str(WORKSPACE_UUID)
    assert len(create.calls) == 1


def test_server_start_and_close_are_linearized_without_thread_leak(monkeypatch, capsys):
    constructor_entered = Event()
    release_constructor = Event()
    real_thread = local_server_module.Thread

    def delayed_thread(*args, **kwargs):
        constructor_entered.set()
        assert release_constructor.wait(timeout=5)
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(local_server_module, "Thread", delayed_thread)
    server = LocalApiServer(LocalApi(services(), token=TOKEN))
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(server.start)
        assert constructor_entered.wait(timeout=2)
        closed = pool.submit(server.close)
        Event().wait(0.05)
        try:
            assert not closed.done()
        finally:
            release_constructor.set()
        assert started.result(timeout=2)[0] == "127.0.0.1"
        closed.result(timeout=2)

    assert "Traceback" not in capsys.readouterr().err


def test_server_start_waits_until_serve_forever_is_ready_before_close():
    serve_target_entered = Event()
    release_serve_target = Event()
    server = LocalApiServer(LocalApi(services(), token=TOKEN))
    real_serve = server._serve

    def delayed_serve():
        serve_target_entered.set()
        assert release_serve_target.wait(timeout=5)
        real_serve()

    server._serve = delayed_serve
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(server.start)
        assert serve_target_entered.wait(timeout=2)
        closed = pool.submit(server.close)
        Event().wait(0.05)
        try:
            assert not started.done()
            assert not closed.done()
        finally:
            release_serve_target.set()
        assert started.result(timeout=2)[0] == "127.0.0.1"
        closed.result(timeout=2)


def test_server_start_fails_closed_if_serve_loop_exits_before_ready():
    server = LocalApiServer(LocalApi(services(), token=TOKEN))
    server._serve = lambda: None

    with pytest.raises(local_server_module.LocalApiServerStartError):
        server.start()

    server.close()


def test_runtime_start_and_close_are_linearized_before_store_close():
    start_entered = Event()
    release_start = Event()

    class ControlledServer:
        address = ("127.0.0.1", 12345)

        def start(self):
            start_entered.set()
            assert release_start.wait(timeout=5)
            return self.address

        def close(self):
            return None

    class RecordingStore:
        def __init__(self):
            self.close_calls = 0

        def close(self):
            self.close_calls += 1

    store = RecordingStore()
    runtime = LocalApiRuntime(
        server=ControlledServer(),
        token=TOKEN,
        _store=store,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(runtime.start)
        assert start_entered.wait(timeout=2)
        closed = pool.submit(runtime.close)
        Event().wait(0.05)
        try:
            assert not closed.done()
            assert store.close_calls == 0
        finally:
            release_start.set()
        assert started.result(timeout=2) == ("127.0.0.1", 12345)
        closed.result(timeout=2)

    assert store.close_calls == 1


def test_composition_starts_on_dynamic_loopback_port_and_closes_idempotently(tmp_path):
    runtime = build_local_api(
        tmp_path / "local-api.db",
        token=TOKEN,
        clock=FixedClock(),
        ids=SequenceIds([WORKSPACE_UUID]),
    )
    address = runtime.start()
    try:
        assert address[0] == "127.0.0.1"
        assert 1 <= address[1] <= 65_535
        status, _headers, body = http_request(
            runtime.server, "GET", "/v1/workspaces"
        )
        assert status == 200
        assert json.loads(body.decode("utf-8")) == {"items": []}
    finally:
        runtime.close()
        runtime.close()


def test_runtime_repr_never_exposes_mutation_token(tmp_path):
    runtime = build_local_api(tmp_path / "repr.db", token=TOKEN)
    try:
        rendered = repr(runtime)
    finally:
        runtime.close()
    assert TOKEN not in rendered


def test_runtime_close_drains_accepted_request_before_closing_sqlite(tmp_path):
    ids = BlockingIds(WORKSPACE_UUID)
    runtime = build_local_api(
        tmp_path / "drain.db", token=TOKEN, clock=FixedClock(), ids=ids
    )
    runtime.start()
    result = []
    client = Thread(
        target=lambda: result.append(
            http_request(
                runtime.server,
                "POST",
                "/v1/workspaces",
                value={"name": "Em voo"},
                headers={"X-Local-API-Token": TOKEN},
            )
        )
    )
    client.start()
    assert ids.entered.wait(timeout=5)
    closing = Thread(target=runtime.close)
    closing.start()
    closing.join(timeout=0.15)
    close_waited_for_request = closing.is_alive()
    ids.release.set()
    client.join(timeout=5)
    closing.join(timeout=5)

    assert close_waited_for_request
    assert not client.is_alive()
    assert not closing.is_alive()
    assert result[0][0] == 201


def test_occupied_port_closes_store_and_raises_sanitized_startup_error(tmp_path):
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    database = tmp_path / "occupied.db"
    try:
        with pytest.raises(LocalApiStartupError) as raised:
            build_local_api(
                database,
                config=LocalServerConfig(port=port),
                token=TOKEN,
                clock=FixedClock(),
                ids=SequenceIds([WORKSPACE_UUID]),
            )
    finally:
        blocker.close()
    assert "127.0.0.1" not in str(raised.value)
    assert str(port) not in str(raised.value)
    database.unlink()


def test_thread_start_failure_closes_listener_and_store_in_subprocess(tmp_path):
    database = tmp_path / "thread-start.db"
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path\n"
            "import socket\n"
            "from scripts.backend_contract.local_api import server as server_module\n"
            "from scripts.backend_contract.local_api.composition import "
            "LocalApiStartupError, build_local_api\n"
            f"database = Path({str(database)!r})\n"
            f"runtime = build_local_api(database, token={TOKEN!r})\n"
            "address = runtime.address\n"
            "def fail_start(_self):\n"
            "    raise RuntimeError('private thread failure')\n"
            "server_module.Thread.start = fail_start\n"
            "try:\n"
            "    runtime.start()\n"
            "except LocalApiStartupError as exc:\n"
            "    assert 'private' not in str(exc)\n"
            "else:\n"
            "    raise AssertionError('startup should fail')\n"
            "probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "probe.bind(address)\n"
            "probe.close()\n"
            "database.unlink()\n",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr


def test_future_sqlite_schema_blocks_composition_before_listener(tmp_path):
    database = tmp_path / "future.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 2")
    with pytest.raises(PersistenceSchemaError):
        build_local_api(
            database,
            token=TOKEN,
            clock=FixedClock(),
            ids=SequenceIds([WORKSPACE_UUID]),
        )


def test_real_http_sqlite_round_trip_append_only_and_reopen(tmp_path):
    database = tmp_path / "round-trip.db"
    revision_two = UUID("33333333-3333-4333-8333-333333333333")
    runtime = build_local_api(
        database,
        token=TOKEN,
        clock=FixedClock(),
        ids=SequenceIds([WORKSPACE_UUID, UUID(REVISION_UUID), revision_two]),
    )
    runtime.start()
    try:
        workspace_status, _headers, workspace_body = http_request(
            runtime.server,
            "POST",
            "/v1/workspaces",
            value={"name": "Perícia Árvore"},
            headers={"X-Local-API-Token": TOKEN},
        )
        target = f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions"
        payloads = (
            {
                "measurements": [0.1, 1.25, 1e20, -0.0],
                "ordem": [2, 1],
                "unknown": {"flag": True},
                "value": None,
            },
            {"ordem": [], "status": "NÃO CONSTATADO"},
        )
        appended = [
            http_request(
                runtime.server,
                "POST",
                target,
                value={"payload": payload},
                headers={"X-Local-API-Token": TOKEN},
            )
            for payload in payloads
        ]
    finally:
        runtime.close()

    assert workspace_status == 201
    assert json.loads(workspace_body.decode("utf-8"))["name"] == "Perícia Árvore"
    assert [json.loads(item[2].decode("utf-8"))["revision"] for item in appended] == [
        1,
        2,
    ]

    reopened = build_local_api(
        database,
        token=TOKEN,
        clock=FixedClock(),
        ids=SequenceIds([]),
    )
    reopened.start()
    try:
        status, _headers, body = http_request(reopened.server, "GET", target)
        latest_status, _headers, latest_body = http_request(
            reopened.server, "GET", f"{target}/latest"
        )
    finally:
        reopened.close()

    assert status == 200
    records = json.loads(body.decode("utf-8"))["items"]
    assert [item["revision"] for item in records] == [1, 2]
    assert [item["payload"] for item in records] == list(payloads)
    assert latest_status == 200
    assert json.loads(latest_body.decode("utf-8"))["payload"] == payloads[1]


def test_two_concurrent_http_appends_are_monotonic_and_workspace_isolated(tmp_path):
    database = tmp_path / "concurrent-api.db"
    workspace_two = UUID("44444444-4444-4444-8444-444444444444")
    revision_two = UUID("33333333-3333-4333-8333-333333333333")
    runtime = build_local_api(
        database,
        token=TOKEN,
        clock=FixedClock(),
        ids=SequenceIds(
            [WORKSPACE_UUID, workspace_two, UUID(REVISION_UUID), revision_two]
        ),
    )
    runtime.start()
    try:
        for name in ("Primeiro", "Segundo"):
            status, _headers, _body = http_request(
                runtime.server,
                "POST",
                "/v1/workspaces",
                value={"name": name},
                headers={"X-Local-API-Token": TOKEN},
            )
            assert status == 201
        target = f"/v1/workspaces/{WORKSPACE_UUID}/artifacts/LAUDO/LAU-001/revisions"

        def append(worker):
            return http_request(
                runtime.server,
                "POST",
                target,
                value={"payload": {"worker": worker}},
                headers={"X-Local-API-Token": TOKEN},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(append, (1, 2)))
        list_status, _headers, list_body = http_request(
            runtime.server, "GET", target
        )
        other_target = (
            f"/v1/workspaces/{workspace_two}/artifacts/LAUDO/LAU-001/revisions"
        )
        other_status, _headers, other_body = http_request(
            runtime.server, "GET", other_target
        )
    finally:
        runtime.close()

    assert {item[0] for item in results} == {201}
    assert {
        json.loads(item[2].decode("utf-8"))["revision"] for item in results
    } == {1, 2}
    assert list_status == 200
    assert [
        item["revision"] for item in json.loads(list_body.decode("utf-8"))["items"]
    ] == [1, 2]
    assert other_status == 200
    assert json.loads(other_body.decode("utf-8")) == {"items": []}
