"""Servidor HTTP loopback do produto local."""

from __future__ import annotations

import math
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread

from .transport import ProductBridge, _error


@dataclass(frozen=True, slots=True)
class ProductBridgeConfig:
    host: str = "127.0.0.1"
    port: int = 0
    max_body_bytes: int = 1_048_576
    request_timeout_seconds: float = 5.0

    def __post_init__(self):
        if self.host != "127.0.0.1":
            raise ValueError("product bridge exige loopback literal")
        if type(self.port) is not int or not 0 <= self.port <= 65_535:
            raise ValueError("porta local inválida")
        if type(self.max_body_bytes) is not int or self.max_body_bytes < 1:
            raise ValueError("limite de body inválido")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or not math.isfinite(self.request_timeout_seconds)
            or not 0 < self.request_timeout_seconds <= 30
        ):
            raise ValueError("timeout local inválido")


class _ProductHttpServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self.bridge: ProductBridge | None = None
        self.serve_ready = Event()
        super().__init__(*args, **kwargs)

    def service_actions(self):
        super().service_actions()
        self.serve_ready.set()

    def handle_error(self, _request, _client_address):
        return


class _ProductRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.request_timeout_seconds)

    def _write_response(self, response):
        self.send_response_only(response.status)
        for name, value in response.headers.items():
            if self.command == "HEAD" and name.lower() == "content-length":
                value = "0"
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(response.body)
            except ConnectionError:
                pass
        self.close_connection = True

    def _dispatch(self):
        try:
            duplicate = any(
                len(self.headers.get_all(name, [])) != 1 for name in ("Host",)
            ) or any(
                len(self.headers.get_all(name, [])) > 1
                for name in (
                    "Content-Length",
                    "Content-Type",
                    "Origin",
                    "Sec-Fetch-Site",
                    "Transfer-Encoding",
                )
            )
            if duplicate or "Transfer-Encoding" in self.headers:
                response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
            else:
                raw_length = self.headers.get("Content-Length", "0")
                if not raw_length.isascii() or not raw_length.isdecimal():
                    response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                else:
                    length = int(raw_length)
                    if length > self.server.max_body_bytes:
                        response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                    else:
                        body = self.rfile.read(length) if length else b""
                        if len(body) != length:
                            response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                        else:
                            bridge = self.server.bridge
                            if bridge is None:
                                response = _error(503, "PRODUCT_BRIDGE_UNAVAILABLE", "serviço local indisponível")
                            else:
                                response = bridge.handle(
                                    self.command,
                                    self.path,
                                    dict(self.headers.items()),
                                    body,
                                )
        except Exception:
            response = _error(500, "PRODUCT_BRIDGE_FAILURE", "falha local")
        self._write_response(response)

    do_GET = _dispatch
    do_POST = _dispatch
    do_HEAD = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_DELETE = _dispatch
    do_OPTIONS = _dispatch

    def log_message(self, _format, *_args):
        return


class ProductBridgeServer:
    def __init__(
        self,
        *,
        frontend_root,
        upstream_address: tuple[str, int],
        token: str,
        config: ProductBridgeConfig | None = None,
    ):
        self._config = ProductBridgeConfig() if config is None else config
        if type(self._config) is not ProductBridgeConfig:
            raise TypeError("configuração do bridge inválida")
        self._server = _ProductHttpServer(
            (self._config.host, self._config.port),
            _ProductRequestHandler,
        )
        self._server.max_body_bytes = self._config.max_body_bytes
        self._server.request_timeout_seconds = self._config.request_timeout_seconds
        host, port = self.address
        self._server.bridge = ProductBridge(
            frontend_root=frontend_root,
            public_origin=f"http://{host}:{port}",
            upstream_address=upstream_address,
            token=token,
            max_body_bytes=self._config.max_body_bytes,
            request_timeout_seconds=self._config.request_timeout_seconds,
        )
        self._thread: Thread | None = None
        self._closed = False
        self._lock = Lock()

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    @property
    def origin(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    def start(self) -> tuple[str, int]:
        with self._lock:
            if self._closed:
                raise RuntimeError("product bridge fechado")
            if self._thread is not None:
                raise RuntimeError("product bridge já iniciado")
            self._thread = Thread(
                target=self._server.serve_forever,
                kwargs={"poll_interval": 0.01},
                name="product-bridge-loopback",
                daemon=True,
            )
            self._thread.start()
            for _ in range(500):
                if self._server.serve_ready.wait(0.01):
                    break
                if not self._thread.is_alive():
                    break
            if not self._server.serve_ready.is_set() or not self._thread.is_alive():
                self._closed = True
                self._server.server_close()
                self._thread.join(timeout=5)
                self._thread = None
                raise RuntimeError("product bridge indisponível")
            return self.address

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._thread is not None:
                self._server.shutdown()
                self._thread.join(timeout=5)
            self._server.server_close()
