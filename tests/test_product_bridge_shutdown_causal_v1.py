from __future__ import annotations

import socket
from threading import Event, Thread

import pytest

from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig

from test_product_bridge_v1 import TOKEN, frontend_build


@pytest.mark.parametrize("slow_part", ("body", "header"))
def test_controlled_shutdown_delay_exposes_fixed_wall_clock_assertion(
    tmp_path, monkeypatch, slow_part
):
    runtime = build_product_runtime(
        tmp_path / "slow-drip.db",
        frontend_build(tmp_path),
        token=TOKEN,
        config=ProductBridgeConfig(request_timeout_seconds=0.1),
    )
    runtime.start()
    client = socket.create_connection(runtime.address, timeout=5)
    if slow_part == "body":
        prefix = (
            b"POST /app-api/v1/workspaces HTTP/1.1\r\n"
            + f"Host: {runtime.address[0]}:{runtime.address[1]}\r\n".encode("ascii")
            + f"Origin: {runtime.origin}\r\n".encode("ascii")
            + b"Sec-Fetch-Site: same-origin\r\n"
            + b"Content-Type: application/json\r\n"
            + b"Content-Length: 100\r\n\r\n{"
        )
    else:
        prefix = (
            b"GET / HTTP/1.1\r\n"
            + f"Host: {runtime.address[0]}:{runtime.address[1]}\r\n".encode("ascii")
            + b"X-Slow-Header:"
        )
    client.sendall(prefix)
    stop_drip = Event()
    shutdown_entered = Event()
    release_shutdown = Event()

    def drip_body():
        while not stop_drip.wait(0.04):
            try:
                client.sendall(b" ")
            except OSError:
                return

    dripper = Thread(target=drip_body, daemon=True)
    dripper.start()
    try:
        request_threads = runtime._bridge._server._threads
        for _ in range(50):
            if any(thread.is_alive() for thread in request_threads):
                break
            Event().wait(0.01)
        else:
            pytest.fail("product request worker did not start")

        original_shutdown = runtime._bridge._server.shutdown

        def delayed_shutdown():
            shutdown_entered.set()
            if not release_shutdown.wait(timeout=2):
                raise AssertionError("controlled shutdown seam was not released")
            return original_shutdown()

        monkeypatch.setattr(runtime._bridge._server, "shutdown", delayed_shutdown)
        closing = Thread(target=runtime.close, daemon=True)
        closing.start()
        assert shutdown_entered.wait(timeout=2)

        closing.join(timeout=0.5)
        assert closing.is_alive()

        release_shutdown.set()
        closing.join(timeout=2)
        assert not closing.is_alive()
        assert runtime._closed
        assert runtime._bridge._thread is not None
        assert not runtime._bridge._thread.is_alive()
        assert runtime._bridge._server.socket.fileno() == -1
        assert all(not thread.is_alive() for thread in runtime._bridge._server._threads)
    finally:
        release_shutdown.set()
        stop_drip.set()
        client.close()
        dripper.join(timeout=2)
        if "closing" in locals():
            closing.join(timeout=2)
        runtime.close()


def test_watchdog_detects_stalled_shutdown_without_false_success(tmp_path, monkeypatch):
    runtime = build_product_runtime(
        tmp_path / "stalled.db",
        frontend_build(tmp_path),
        token=TOKEN,
        config=ProductBridgeConfig(request_timeout_seconds=0.1),
    )
    runtime.start()
    entered = Event()
    release = Event()

    def stalled_shutdown():
        entered.set()
        release.wait(timeout=2)

    monkeypatch.setattr(runtime._bridge._server, "shutdown", stalled_shutdown)
    closing = Thread(target=runtime.close, daemon=True)
    closing.start()
    try:
        assert entered.wait(timeout=2)
        closing.join(timeout=0.5)
        true_hang_detected = closing.is_alive()
        assert true_hang_detected
    finally:
        release.set()
        closing.join(timeout=2)
        runtime.close()
