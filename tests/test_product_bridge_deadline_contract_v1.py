from __future__ import annotations

import inspect
from threading import Event, Thread

import pytest

from scripts.backend_contract.local_api.server import LocalApiServer, LocalServerConfig
from scripts.backend_contract.local_api.transport import LocalApi
from scripts.backend_contract.product_bridge.server import ProductBridgeServer, ProductBridgeConfig
from tests.test_local_api_v1 import services
from tests.test_product_bridge_v1 import TOKEN, request


class _ValidSlowListWorkspaces:
    def __init__(self, entered: Event, release: Event) -> None:
        self.entered = entered
        self.release = release

    def execute(self):
        self.entered.set()
        self.release.wait()
        return ()


def _slow_bridge(
    entered: Event,
    release: Event,
    frontend_root,
) -> tuple[LocalApiServer, ProductBridgeServer]:
    frontend_root.mkdir(exist_ok=True)
    (frontend_root / "index.html").write_text("<!doctype html>", encoding="utf-8")
    upstream = LocalApiServer(
        LocalApi(services(list_workspaces=_ValidSlowListWorkspaces(entered, release)), token=TOKEN),
        LocalServerConfig(port=0),
    )
    upstream.start()
    bridge = ProductBridgeServer(
        frontend_root=frontend_root,
        upstream_address=upstream.address,
        token=TOKEN,
        recovery_mutation_supported=True,
        config=ProductBridgeConfig(port=0),
    )
    bridge.start()
    return upstream, bridge


def _require_explicit_deadline_contract() -> None:
    if "timeout" not in inspect.signature(request).parameters:
        pytest.fail("request must expose an explicit bounded operation deadline")


def test_valid_slow_bridge_response_uses_explicit_operation_deadline(tmp_path) -> None:
    _require_explicit_deadline_contract()
    entered = Event()
    release = Event()
    upstream, bridge = _slow_bridge(entered, release, tmp_path)
    result: dict[str, object] = {}

    def call() -> None:
        try:
            result["response"] = request(bridge, "GET", "/app-api/v1/workspaces", timeout=10)
        except BaseException as exc:  # pragma: no cover - RED captures missing contract
            result["error"] = exc

    worker = Thread(target=call)
    worker.start()
    try:
        assert entered.wait(timeout=2)
        assert not worker.join(timeout=5.2)
        release.set()
        worker.join(timeout=2)
        assert "error" not in result
        assert result["response"][0] == 200
    finally:
        release.set()
        worker.join(timeout=2)
        bridge.close()
        upstream.close()


def test_bridge_hang_still_fails_at_explicit_short_deadline(tmp_path) -> None:
    _require_explicit_deadline_contract()
    entered = Event()
    release = Event()
    upstream, bridge = _slow_bridge(entered, release, tmp_path)
    result: dict[str, object] = {}

    def call() -> None:
        try:
            request(bridge, "GET", "/app-api/v1/workspaces", timeout=0.1)
        except BaseException as exc:
            result["error"] = exc

    worker = Thread(target=call)
    worker.start()
    try:
        assert entered.wait(timeout=2)
        worker.join(timeout=2)
        assert isinstance(result.get("error"), TimeoutError)
    finally:
        release.set()
        worker.join(timeout=2)
        bridge.close()
        upstream.close()


@pytest.mark.parametrize("timeout", [True, 0, -1, 31, float("nan"), float("inf")])
def test_bridge_operation_deadline_is_explicitly_bounded(timeout: object) -> None:
    with pytest.raises(ValueError, match="client operation timeout invalid"):
        request(None, "GET", "/app-api/v1/workspaces", timeout=timeout)
