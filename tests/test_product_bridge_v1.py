import http.client
import json
import socket
import subprocess
import sys
from pathlib import Path
from threading import Event, Thread

import pytest

from scripts.backend_contract.product_bridge.transport import _proxy_target

from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.backend_contract.product_bridge.server import (
    ProductBridgeConfig,
    ProductBridgeServer,
    ProductBridgeServerStartError,
)


TOKEN = "product-bridge-test-token-with-sufficient-entropy"


def frontend_build(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><div id="root"></div><script type="module" src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text('document.title="Sistema Pericial";', encoding="utf-8")
    return root


def request(runtime, method, target, *, headers=None, body=None, raw_body=None):
    if body is not None and raw_body is not None:
        raise ValueError("request body is ambiguous")
    encoded = raw_body if raw_body is not None else (None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8"))
    request_headers = dict(headers or {})
    if encoded is not None:
        request_headers.setdefault("Content-Type", "application/octet-stream" if raw_body is not None else "application/json")
        request_headers.setdefault("Content-Length", str(len(encoded)))
    connection = http.client.HTTPConnection(*runtime.address, timeout=5)
    try:
        connection.request(method, target, body=encoded, headers=request_headers)
        response = connection.getresponse()
        payload = response.read()
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


def browser_mutation_headers(runtime):
    return {
        "Origin": runtime.origin,
        "Sec-Fetch-Site": "same-origin",
    }


def raw_request(runtime, payload: bytes) -> bytes:
    client = socket.create_connection(runtime.address, timeout=5)
    try:
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := client.recv(65_536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        client.close()


def test_product_bridge_config_requires_literal_loopback():
    with pytest.raises(ValueError, match="loopback"):
        ProductBridgeConfig(host="0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        ProductBridgeConfig(host="localhost")
    with pytest.raises(ValueError, match="porta"):
        ProductBridgeConfig(port=80)


@pytest.mark.parametrize("value", (0, -1, 31, True, float("inf"), float("nan")))
def test_product_bridge_config_rejects_invalid_upstream_timeouts(value):
    with pytest.raises(ValueError, match="timeout upstream"):
        ProductBridgeConfig(upstream_timeout_seconds=value)


def test_product_bridge_serves_build_and_spa_deep_links_without_secret(tmp_path):
    root = frontend_build(tmp_path)
    runtime = build_product_runtime(tmp_path / "product.db", root, token=TOKEN)
    try:
        runtime.start()
        for target in ("/", "/pericias/11111111-1111-4111-8111-111111111111/vistoria"):
            status, headers, body = request(runtime, "GET", target)
            assert status == 200
            assert body == (root / "index.html").read_bytes()
            assert TOKEN.encode() not in body
            assert headers["Content-Security-Policy"].startswith("default-src 'self'")
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert "Access-Control-Allow-Origin" not in headers
        status, _headers, body = request(runtime, "GET", "/assets/app.js")
        assert status == 200
        assert body == (root / "assets" / "app.js").read_bytes()
        assert TOKEN.encode() not in body
    finally:
        runtime.close()


def test_unknown_browser_route_loads_the_spa_router(tmp_path):
    root = frontend_build(tmp_path)
    runtime = build_product_runtime(tmp_path / "unknown-route.db", root, token=TOKEN)
    try:
        runtime.start()
        status, headers, body = request(runtime, "GET", "/teste-inexistente")
    finally:
        runtime.close()

    assert status == 200
    assert headers["Content-Type"] == "text/html"
    assert body == (root / "index.html").read_bytes()


def test_unknown_browser_route_supports_head_without_a_body(tmp_path):
    root = frontend_build(tmp_path)
    runtime = build_product_runtime(tmp_path / "unknown-head.db", root, token=TOKEN)
    try:
        runtime.start()
        status, headers, body = request(runtime, "HEAD", "/teste-inexistente")
    finally:
        runtime.close()

    assert status == 200
    assert headers["Content-Type"] == "text/html"
    assert headers["Content-Length"] == "0"
    assert body == b""


def test_missing_asset_never_falls_back_to_the_spa(tmp_path):
    root = frontend_build(tmp_path)
    runtime = build_product_runtime(tmp_path / "missing-asset.db", root, token=TOKEN)
    try:
        runtime.start()
        status, headers, body = request(runtime, "GET", "/assets/inexistente.js")
    finally:
        runtime.close()

    assert status == 404
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert body != (root / "index.html").read_bytes()
    assert json.loads(body)["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("target", ("/app-api", "/app-api/rota-inexistente"))
def test_unknown_app_api_route_never_falls_back_to_the_spa(tmp_path, target):
    root = frontend_build(tmp_path)
    runtime = build_product_runtime(tmp_path / "unknown-api.db", root, token=TOKEN)
    try:
        runtime.start()
        status, headers, body = request(runtime, "GET", target)
    finally:
        runtime.close()

    assert status == 404
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert body != (root / "index.html").read_bytes()
    assert json.loads(body)["error"]["code"] == "NOT_FOUND"


def test_non_get_browser_route_never_falls_back_to_the_spa(tmp_path):
    root = frontend_build(tmp_path)
    runtime = build_product_runtime(tmp_path / "unknown-post.db", root, token=TOKEN)
    try:
        runtime.start()
        status, headers, body = request(
            runtime,
            "POST",
            "/teste-inexistente",
            headers=browser_mutation_headers(runtime),
            body={"name": "não é navegação"},
        )
    finally:
        runtime.close()

    assert status == 405
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert body != (root / "index.html").read_bytes()
    assert json.loads(body)["error"]["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
        {"Origin": "null", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://127.0.0.1:1", "Sec-Fetch-Site": "same-origin"},
    ),
)
def test_browser_facing_mutation_fails_closed_without_exact_product_origin(tmp_path, headers):
    runtime = build_product_runtime(tmp_path / "blocked.db", frontend_build(tmp_path), token=TOKEN)
    try:
        runtime.start()
        status, response_headers, body = request(
            runtime,
            "POST",
            "/app-api/v1/workspaces",
            headers=headers,
            body={"name": "Não deve existir"},
        )
        assert status == 403
        assert json.loads(body)["error"]["code"] == "FORBIDDEN_PRODUCT_REQUEST"
        assert TOKEN.encode() not in body
        assert "Access-Control-Allow-Origin" not in response_headers
        listed_status, _listed_headers, listed_body = request(runtime, "GET", "/app-api/v1/workspaces")
        assert listed_status == 200
        assert json.loads(listed_body) == {"items": []}
    finally:
        runtime.close()


def test_same_origin_mutation_is_forwarded_and_token_stays_server_side(tmp_path):
    runtime = build_product_runtime(tmp_path / "allowed.db", frontend_build(tmp_path), token=TOKEN)
    try:
        runtime.start()
        status, headers, body = request(
            runtime,
            "POST",
            "/app-api/v1/workspaces",
            headers=browser_mutation_headers(runtime),
            body={"name": "Perícia Árvore"},
        )
        assert status == 201
        created = json.loads(body)
        assert created["name"] == "Perícia Árvore"
        assert TOKEN.encode() not in body
        assert "Access-Control-Allow-Origin" not in headers
        assert TOKEN not in repr(runtime)
    finally:
        runtime.close()


def test_case_analysis_bridge_saves_and_reopens_canonical_snapshot(tmp_path):
    payload = json.loads((Path(__file__).parent / "fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8"))
    runtime = build_product_runtime(
        tmp_path / "analysis.db",
        frontend_build(tmp_path),
        token=TOKEN,
        private_root=tmp_path / "private",
    )
    try:
        runtime.start()
        workspace_status, _, workspace_body = request(
            runtime,
            "POST",
            "/app-api/v1/workspaces",
            headers=browser_mutation_headers(runtime),
            body={"name": "Análise sintética"},
        )
        workspace_id = json.loads(workspace_body)["workspace_id"]
        payload["workspace_id"] = workspace_id
        payload["judicial_context_workspace_id"] = workspace_id
        imported = []
        for index in range(3):
            content = f"%PDF-1.7\nbridge-synthetic-{index}\n%%EOF\n".encode()
            status, _, body = request(
                runtime,
                "POST",
                f"/app-api/v1/workspaces/{workspace_id}/materials",
                headers={
                    **browser_mutation_headers(runtime),
                    "Content-Type": "application/pdf",
                    "X-Document-Filename": f"synthetic-{index}.pdf",
                },
                raw_body=content,
            )
            assert status == 201, body
            imported.append(json.loads(body))
        source_by_id = {}
        for document, material in zip(payload["documents"], imported, strict=True):
            document["storage_content_id"] = material["content_id"]
            document["source_sha256"] = material["checksum_sha256"]
            source_by_id[document["document_id"]] = material["checksum_sha256"]
        for collection in (
            "claims",
            "counterarguments",
            "decisions",
            "pericial_objects",
            "questions",
            "events",
            "technical_document_references",
            "gaps",
            "conflicts",
        ):
            for item in payload[collection]:
                for provenance in item["provenance"]:
                    provenance["workspace_id"] = workspace_id
                    provenance["source_document_sha256"] = source_by_id[provenance["source_document_id"]]
        context = payload["judicial_context"]
        for owner in [context, *context["entities"], *context["participants"], *context["representation_links"], *context["access_relations"]]:
            for source in owner["provenance"]:
                source["source_sha256"] = source_by_id[source["source_document_id"]]
        saved_status, _, saved_body = request(
            runtime,
            "POST",
            f"/app-api/v1/workspaces/{workspace_id}/case-analysis",
            headers=browser_mutation_headers(runtime),
            body={"expected_revision": None, "snapshot": payload},
        )
        get_status, _, get_body = request(runtime, "GET", f"/app-api/v1/workspaces/{workspace_id}/case-analysis")
    finally:
        runtime.close()

    assert workspace_status == 201
    assert saved_status == 200
    assert get_status == 200
    assert json.loads(saved_body)["snapshot"] == payload
    assert json.loads(get_body)["snapshot"] == payload
    assert TOKEN.encode() not in saved_body + get_body


def test_pericial_planning_bridge_allowlist_is_exact():
    workspace_id = "11111111-1111-4111-8111-111111111111"

    assert _proxy_target(f"/app-api/v1/workspaces/{workspace_id}/pericial-planning", "GET") == f"/v1/workspaces/{workspace_id}/pericial-planning"
    assert _proxy_target(f"/app-api/v1/workspaces/{workspace_id}/pericial-planning", "POST") == f"/v1/workspaces/{workspace_id}/pericial-planning"
    assert _proxy_target(f"/app-api/v1/workspaces/{workspace_id}/pericial-planning/decisions", "POST") is None
    assert _proxy_target(f"/app-api/v1/workspaces/{workspace_id}/pericial-planning", "DELETE") is None


@pytest.mark.parametrize(
    "duplicate_headers",
    (
        "Host: attacker.invalid\r\n",
        "Origin: http://attacker.invalid\r\n",
        "Content-Length: 2\r\n",
    ),
)
def test_duplicate_security_headers_fail_closed(tmp_path, duplicate_headers):
    runtime = build_product_runtime(tmp_path / "duplicates.db", frontend_build(tmp_path), token=TOKEN)
    runtime.start()
    try:
        payload = (
            "POST /app-api/v1/workspaces HTTP/1.1\r\n"
            f"Host: {runtime.address[0]}:{runtime.address[1]}\r\n"
            f"Origin: {runtime.origin}\r\n"
            "Sec-Fetch-Site: same-origin\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 2\r\n"
            f"{duplicate_headers}"
            "\r\n{}"
        ).encode("ascii")
        response = raw_request(runtime, payload)
    finally:
        runtime.close()

    assert response.split(b"\r\n", 1)[0].endswith(b" 400 Bad Request")
    assert TOKEN.encode() not in response


def test_absolute_form_and_truncated_body_fail_closed(tmp_path):
    runtime = build_product_runtime(tmp_path / "framing.db", frontend_build(tmp_path), token=TOKEN)
    runtime.start()
    host = f"{runtime.address[0]}:{runtime.address[1]}"
    try:
        absolute = raw_request(
            runtime,
            (f"GET http://{host}/ HTTP/1.1\r\nHost: {host}\r\n\r\n").encode("ascii"),
        )
        truncated = raw_request(
            runtime,
            (
                f"POST /app-api/v1/workspaces HTTP/1.1\r\nHost: {host}\r\nOrigin: {runtime.origin}\r\nSec-Fetch-Site: same-origin\r\nContent-Type: application/json\r\nContent-Length: 10\r\n\r\n{{}}"
            ).encode("ascii"),
        )
    finally:
        runtime.close()

    assert absolute.split(b"\r\n", 1)[0].endswith(b" 400 Bad Request")
    assert truncated.split(b"\r\n", 1)[0].endswith(b" 400 Bad Request")


def test_upstream_failure_is_sanitized_and_token_never_reaches_public_bytes(tmp_path):
    root = frontend_build(tmp_path)
    assert all(TOKEN.encode() not in path.read_bytes() for path in root.rglob("*.*"))
    bridge = ProductBridgeServer(
        frontend_root=root,
        upstream_address=("127.0.0.1", 9),
        token=TOKEN,
    )
    bridge.start()
    try:
        status, _headers, body = request(bridge, "GET", "/app-api/v1/workspaces")
        missing_status, _missing_headers, missing_body = request(bridge, "GET", "/assets/missing.js")
    finally:
        bridge.close()

    assert status == 503
    assert json.loads(body)["error"]["code"] == "LOCAL_API_UNAVAILABLE"
    assert missing_status == 404
    assert TOKEN.encode() not in body + missing_body


@pytest.mark.parametrize(
    ("method", "target"),
    (
        (
            "GET",
            "/app-api/v1/workspaces/11111111-1111-4111-8111-111111111111/artifacts/LAUDO/X/revisions",
        ),
        ("DELETE", "/app-api/v1/workspaces"),
        ("POST", "/app-api/v1/other"),
        ("GET", "/../scripts/backend_contract/application/models.py"),
        ("GET", "/assets/../index.html"),
        ("GET", "/%2e%2e/scripts/backend_contract/application/models.py"),
        ("GET", "/..\\scripts\\backend_contract\\application\\models.py"),
    ),
)
def test_bridge_exposes_only_the_workspace_slice(tmp_path, method, target):
    runtime = build_product_runtime(tmp_path / "allowlist.db", frontend_build(tmp_path), token=TOKEN)
    try:
        runtime.start()
        status, _headers, body = request(
            runtime,
            method,
            target,
            headers=browser_mutation_headers(runtime),
            body={"name": "x"} if method == "POST" else None,
        )
        assert status in {400, 404, 405}
        assert TOKEN.encode() not in body
    finally:
        runtime.close()


def test_missing_frontend_build_fails_before_runtime_is_exposed(tmp_path):
    with pytest.raises(ValueError, match="frontend"):
        build_product_runtime(tmp_path / "missing.db", tmp_path / "missing", token=TOKEN)


def test_close_is_idempotent_after_start(tmp_path):
    runtime = build_product_runtime(tmp_path / "close.db", frontend_build(tmp_path), token=TOKEN)
    runtime.start()
    runtime.close()
    runtime.close()


@pytest.mark.parametrize("slow_part", ("body", "header"))
def test_slow_drip_cannot_hold_product_runtime_shutdown(tmp_path, slow_part):
    runtime = build_product_runtime(
        tmp_path / "slow-drip.db",
        frontend_build(tmp_path),
        token=TOKEN,
        config=ProductBridgeConfig(request_timeout_seconds=0.1),
    )
    runtime.start()
    client = socket.create_connection(runtime.address, timeout=5)
    if slow_part == "body":
        request_prefix = (
            b"POST /app-api/v1/workspaces HTTP/1.1\r\n"
            + f"Host: {runtime.address[0]}:{runtime.address[1]}\r\n".encode("ascii")
            + f"Origin: {runtime.origin}\r\n".encode("ascii")
            + b"Sec-Fetch-Site: same-origin\r\n"
            + b"Content-Type: application/json\r\n"
            + b"Content-Length: 100\r\n\r\n{"
        )
    else:
        request_prefix = b"GET / HTTP/1.1\r\n" + f"Host: {runtime.address[0]}:{runtime.address[1]}\r\n".encode("ascii") + b"X-Slow-Header:"
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
        request_threads = getattr(runtime._bridge._server, "_threads", ())
        if any(thread.is_alive() for thread in request_threads):
            break
        Event().wait(0.01)
    else:
        pytest.fail("product request worker did not start")

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


def test_thread_start_failure_closes_product_bridge_listener(tmp_path):
    root = frontend_build(tmp_path)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import socket\n"
            "from scripts.backend_contract.product_bridge import server as module\n"
            "from scripts.backend_contract.product_bridge.server import "
            "ProductBridgeServer, ProductBridgeServerStartError\n"
            f"server = ProductBridgeServer(frontend_root={str(root)!r}, "
            f"upstream_address=('127.0.0.1', 9), token={TOKEN!r})\n"
            "address = server.address\n"
            "def fail_start(_self):\n"
            "    raise RuntimeError('private thread failure')\n"
            "module.Thread.start = fail_start\n"
            "try:\n"
            "    server.start()\n"
            "except ProductBridgeServerStartError as exc:\n"
            "    assert 'private' not in str(exc)\n"
            "else:\n"
            "    raise AssertionError('startup should fail')\n"
            "server.close()\n"
            "probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "probe.bind(address)\n"
            "probe.close()\n",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    assert probe.returncode == 0, probe.stderr


def test_serve_loop_failure_before_ready_fails_closed(tmp_path):
    bridge = ProductBridgeServer(
        frontend_root=frontend_build(tmp_path),
        upstream_address=("127.0.0.1", 9),
        token=TOKEN,
    )

    def stop_before_ready():
        bridge._serve_stopped.set()

    bridge._serve = stop_before_ready
    with pytest.raises(ProductBridgeServerStartError):
        bridge.start()
    bridge.close()


def test_partial_product_runtime_startup_closes_owned_local_api(tmp_path):
    runtime = build_product_runtime(tmp_path / "partial.db", frontend_build(tmp_path), token=TOKEN)

    def fail_bridge_start():
        raise ProductBridgeServerStartError("bridge indisponível")

    runtime._bridge.start = fail_bridge_start
    with pytest.raises(ProductBridgeServerStartError):
        runtime.start()
    assert runtime._local_api._closed is True
    assert runtime._bridge._closed is True


def test_unsupported_method_uses_sanitized_bridge_response(tmp_path):
    runtime = build_product_runtime(tmp_path / "unsupported.db", frontend_build(tmp_path), token=TOKEN)
    runtime.start()
    try:
        status, headers, body = request(runtime, "CONNECT", "/")
    finally:
        runtime.close()

    assert status == 405
    assert "Server" not in headers
    assert "Date" not in headers
    assert headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert json.loads(body)["error"]["code"] == "METHOD_NOT_ALLOWED"
