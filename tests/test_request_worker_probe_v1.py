from __future__ import annotations

import socket
from http.server import BaseHTTPRequestHandler
from threading import Event, Thread

import pytest

from scripts.backend_contract.local_api.server import _ThreadingLocalServer
from scripts.backend_contract.product_bridge.server import _ProductHttpServer

from request_worker_probe import live_request_workers

SERVER_CLASSES = (_ThreadingLocalServer, _ProductHttpServer)


@pytest.mark.parametrize("server_class", SERVER_CLASSES)
def test_no_worker_before_first_request_is_empty_not_type_error(server_class):
    # ThreadingMixIn keeps a non-iterable class-level placeholder in
    # `_threads` until the first request is processed (#300).
    server = server_class(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        assert "_threads" not in vars(server)
        assert live_request_workers(server) == ()
    finally:
        server.server_close()


@pytest.mark.parametrize("server_class", SERVER_CLASSES)
def test_in_flight_worker_is_seen_and_disappears_after_it_ends(server_class):
    entered = Event()
    release = Event()

    class BlockingHandler(BaseHTTPRequestHandler):
        def handle(self):
            entered.set()
            release.wait(timeout=5)

    server = server_class(("127.0.0.1", 0), BlockingHandler)
    serving = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    serving.start()
    client = socket.create_connection(server.server_address, timeout=5)
    try:
        assert entered.wait(timeout=5)
        workers = live_request_workers(server)
        assert len(workers) == 1 and workers[0].is_alive()
    finally:
        release.set()
        client.close()
        server.shutdown()
        serving.join(timeout=5)
        server.server_close()
    assert live_request_workers(server) == ()


def test_unexpected_non_iterable_instance_value_fails_closed():
    server = _ThreadingLocalServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        server._threads = object()
        with pytest.raises(TypeError):
            live_request_workers(server)
    finally:
        del server._threads
        server.server_close()
