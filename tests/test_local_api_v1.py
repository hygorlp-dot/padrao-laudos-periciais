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
from scripts.backend_contract.local_api.server import LocalApiServer, LocalServerConfig
from scripts.backend_contract.local_api.composition import (
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


@pytest.mark.parametrize("token", ("", "short", "x" * 31, "á" * 32))
def test_local_mutation_token_requires_high_entropy_header_safe_shape(token):
    with pytest.raises(ValueError, match="token"):
        LocalApi(services(), token=token)


def test_composition_rejects_invalid_token_before_opening_sqlite(tmp_path):
    database = tmp_path / "must-not-open.db"
    with pytest.raises(ValueError, match="token"):
        build_local_api(database, token="short")
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
            {"ordem": [2, 1], "unknown": {"flag": True}, "value": None},
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
