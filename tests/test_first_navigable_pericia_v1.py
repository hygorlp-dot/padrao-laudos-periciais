import http.client
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

from scripts.backend_contract.product_bridge.composition import build_product_runtime


TOKEN = "vertical-slice-test-token-with-sufficient-entropy"


def frontend_build(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    return root


def request(runtime, method, target, *, body=None):
    encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {}
    if encoded is not None:
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(encoded)),
            "Origin": runtime.origin,
            "Sec-Fetch-Site": "same-origin",
        }
    connection = http.client.HTTPConnection(*runtime.address, timeout=5)
    try:
        connection.request(method, target, body=encoded, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_real_vertical_slice_survives_runtime_reopen(tmp_path):
    database = tmp_path / "pericias.db"
    root = frontend_build(tmp_path)

    first_runtime = build_product_runtime(database, root, token=TOKEN)
    try:
        first_runtime.start()
        assert request(first_runtime, "GET", "/app-api/v1/workspaces") == (
            200,
            {"items": []},
        )
        created_status, created = request(
            first_runtime,
            "POST",
            "/app-api/v1/workspaces",
            body={"name": "Perícia de teste"},
        )
        assert created_status == 201
        assert created["name"] == "Perícia de teste"
        assert str(UUID(created["workspace_id"])) == created["workspace_id"]
        assert created["created_at"].endswith("+00:00")
        listed_status, listed = request(
            first_runtime, "GET", "/app-api/v1/workspaces"
        )
        assert listed_status == 200
        assert listed == {"items": [created]}
        opened_status, opened = request(
            first_runtime,
            "GET",
            f"/app-api/v1/workspaces/{created['workspace_id']}",
        )
        assert opened_status == 200
        assert opened == created
    finally:
        first_runtime.close()

    reopened_runtime = build_product_runtime(database, root, token=TOKEN)
    try:
        reopened_runtime.start()
        reopened_status, reopened = request(
            reopened_runtime,
            "GET",
            f"/app-api/v1/workspaces/{created['workspace_id']}",
        )
        assert reopened_status == 200
        assert reopened == created
        assert request(reopened_runtime, "GET", "/app-api/v1/workspaces") == (
            200,
            {"items": [created]},
        )
    finally:
        reopened_runtime.close()


def test_two_legitimate_creates_remain_distinct_and_persisted(tmp_path):
    runtime = build_product_runtime(
        tmp_path / "concurrent.db", frontend_build(tmp_path), token=TOKEN
    )
    try:
        runtime.start()

        def create(name):
            return request(
                runtime,
                "POST",
                "/app-api/v1/workspaces",
                body={"name": name},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(create, ("Perícia A", "Perícia B")))

        assert [status for status, _record in results] == [201, 201]
        identities = {record["workspace_id"] for _status, record in results}
        assert len(identities) == 2
        status, listed = request(runtime, "GET", "/app-api/v1/workspaces")
        assert status == 200
        assert {item["workspace_id"] for item in listed["items"]} == identities
    finally:
        runtime.close()
