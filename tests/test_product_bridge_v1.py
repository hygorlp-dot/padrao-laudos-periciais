import http.client
import json
from pathlib import Path

import pytest

from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig


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


def request(runtime, method, target, *, headers=None, body=None):
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request_headers = dict(headers or {})
    if encoded is not None:
        request_headers.setdefault("Content-Type", "application/json")
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


def test_product_bridge_config_requires_literal_loopback():
    with pytest.raises(ValueError, match="loopback"):
        ProductBridgeConfig(host="0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        ProductBridgeConfig(host="localhost")


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


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
        {"Origin": "null", "Sec-Fetch-Site": "same-origin"},
        {"Origin": "http://127.0.0.1:1", "Sec-Fetch-Site": "same-origin"},
    ),
)
def test_browser_facing_mutation_fails_closed_without_exact_product_origin(
    tmp_path, headers
):
    runtime = build_product_runtime(
        tmp_path / "blocked.db", frontend_build(tmp_path), token=TOKEN
    )
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
        listed_status, _listed_headers, listed_body = request(
            runtime, "GET", "/app-api/v1/workspaces"
        )
        assert listed_status == 200
        assert json.loads(listed_body) == {"items": []}
    finally:
        runtime.close()


def test_same_origin_mutation_is_forwarded_and_token_stays_server_side(tmp_path):
    runtime = build_product_runtime(
        tmp_path / "allowed.db", frontend_build(tmp_path), token=TOKEN
    )
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
        ("GET", "/%2e%2e/scripts/backend_contract/application/models.py"),
    ),
)
def test_bridge_exposes_only_the_workspace_slice(tmp_path, method, target):
    runtime = build_product_runtime(
        tmp_path / "allowlist.db", frontend_build(tmp_path), token=TOKEN
    )
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
    runtime = build_product_runtime(
        tmp_path / "close.db", frontend_build(tmp_path), token=TOKEN
    )
    runtime.start()
    runtime.close()
    runtime.close()

