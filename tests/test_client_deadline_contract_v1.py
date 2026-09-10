from __future__ import annotations

import inspect
from threading import Event, Thread

import pytest

try:
    import conftest as suite_conftest
except ModuleNotFoundError:  # subprocess probes run from the repository root
    from tests import conftest as suite_conftest

from scripts.backend_contract.local_api.server import LocalApiServer, LocalServerConfig
from scripts.backend_contract.local_api.transport import LocalApi
from tests.test_local_api_v1 import FailingService, TOKEN, http_request, services


class _ValidSlowListWorkspaces:
    def __init__(self, entered: Event, release: Event) -> None:
        self.entered = entered
        self.release = release

    def execute(self):
        self.entered.set()
        self.release.wait()
        return ()


def _slow_server(entered: Event, release: Event) -> LocalApiServer:
    api = LocalApi(
        services(list_workspaces=_ValidSlowListWorkspaces(entered, release)),
        token=TOKEN,
    )
    return LocalApiServer(api, LocalServerConfig(port=0))


def _require_explicit_deadline_contract() -> None:
    if "timeout" not in inspect.signature(http_request).parameters:
        pytest.fail("http_request must expose an explicit bounded operation deadline")


def test_valid_slow_response_uses_explicit_operation_deadline() -> None:
    """A valid response beyond the short client deadline must remain recoverable."""
    _require_explicit_deadline_contract()
    entered = Event()
    release = Event()
    server = _slow_server(entered, release)
    server.start()
    result: dict[str, object] = {}
    request_seq = str(suite_conftest._REQUEST_SEQUENCE + 1)

    def request() -> None:
        try:
            result["response"] = http_request(
                server,
                "GET",
                "/v1/workspaces",
                timeout=10,
            )
        except BaseException as exc:  # pragma: no cover - RED captures the missing contract
            result["error"] = exc

    worker = Thread(target=request)
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
        suite_conftest._finish_local_api_request(request_seq, retain=False)
        server.close()


def test_hang_still_fails_at_explicit_short_deadline() -> None:
    """A server that never releases must still fail closed at the bound."""
    _require_explicit_deadline_contract()
    entered = Event()
    release = Event()
    server = _slow_server(entered, release)
    server.start()
    result: dict[str, object] = {}
    request_seq = str(suite_conftest._REQUEST_SEQUENCE + 1)

    def request() -> None:
        try:
            http_request(server, "GET", "/v1/workspaces", timeout=0.1)
        except BaseException as exc:
            result["error"] = exc

    worker = Thread(target=request)
    worker.start()
    try:
        assert entered.wait(timeout=2)
        worker.join(timeout=2)
        assert isinstance(result.get("error"), TimeoutError)
    finally:
        release.set()
        worker.join(timeout=2)
        suite_conftest._finish_local_api_request(request_seq, retain=False)
        server.close()


def test_fast_response_remains_successful_with_default_bound() -> None:
    server = LocalApiServer(LocalApi(services(), token=TOKEN), LocalServerConfig(port=0))
    server.start()
    try:
        status, _headers, _body = http_request(server, "GET", "/v1/workspaces")
    finally:
        server.close()

    assert status == 200


def test_server_exception_remains_an_error_response() -> None:
    server = LocalApiServer(
        LocalApi(services(list_workspaces=FailingService(RuntimeError("synthetic failure"))), token=TOKEN),
        LocalServerConfig(port=0),
    )
    server.start()
    try:
        status, _headers, body = http_request(server, "GET", "/v1/workspaces")
    finally:
        server.close()

    assert status == 500
    assert b"INTERNAL_SERVER_ERROR" in body


@pytest.mark.parametrize("timeout", [True, 0, -1, 31, float("nan"), float("inf")])
def test_operation_deadline_is_explicitly_bounded(timeout: object) -> None:
    with pytest.raises(ValueError, match="client operation timeout invalid"):
        http_request(None, "GET", "/v1/workspaces", timeout=timeout)
