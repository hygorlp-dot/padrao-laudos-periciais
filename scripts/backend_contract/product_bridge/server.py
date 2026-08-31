"""Servidor HTTP loopback do produto local."""

from __future__ import annotations

import math
import socket
import tempfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread, Timer

from .transport import (
    DOCUMENT_IO_CHUNK_BYTES,
    MAX_DOCUMENT_BYTES,
    ProductBridge,
    SeekableContent,
    _error,
)


@dataclass(frozen=True, slots=True)
class ProductBridgeConfig:
    host: str = "127.0.0.1"
    port: int = 0
    max_body_bytes: int = 1_048_576
    max_document_body_bytes: int = MAX_DOCUMENT_BYTES
    request_timeout_seconds: float = 5.0
    upstream_timeout_seconds: float = 30.0

    def __post_init__(self):
        if self.host != "127.0.0.1":
            raise ValueError("product bridge exige loopback literal")
        if type(self.port) is not int or not 0 <= self.port <= 65_535:
            raise ValueError("porta local inválida")
        if self.port == 80:
            raise ValueError("porta 80 não preserva a origem local canônica")
        if (
            type(self.max_body_bytes) is not int
            or not 1 <= self.max_body_bytes <= 1_048_576
        ):
            raise ValueError("limite de body inválido")
        if (
            type(self.max_document_body_bytes) is not int
            or not 1 <= self.max_document_body_bytes <= MAX_DOCUMENT_BYTES
        ):
            raise ValueError("limite de documento inválido")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or not math.isfinite(self.request_timeout_seconds)
            or not 0 < self.request_timeout_seconds <= 30
        ):
            raise ValueError("timeout local inválido")
        if (
            isinstance(self.upstream_timeout_seconds, bool)
            or not isinstance(self.upstream_timeout_seconds, (int, float))
            or not math.isfinite(self.upstream_timeout_seconds)
            or not 0 < self.upstream_timeout_seconds <= 30
        ):
            raise ValueError("timeout upstream local inválido")


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


class ProductBridgeServerStartError(RuntimeError):
    """Falha sanitizada ao iniciar o listener do produto local."""


class _ProductRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(self.server.request_timeout_seconds)

    def handle_one_request(self):
        self._deadline_lock = Lock()
        self._deadline_active = True
        self._deadline_expired = False
        self._deadline_timer = Timer(
            self.server.request_timeout_seconds,
            self._expire_request_acquisition,
        )
        self._deadline_timer.daemon = True
        self._deadline_timer.start()
        try:
            return super().handle_one_request()
        finally:
            self._finish_request_acquisition()

    def _expire_request_acquisition(self):
        with self._deadline_lock:
            if not self._deadline_active:
                return
            self._deadline_expired = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _finish_request_acquisition(self) -> bool:
        deadline = getattr(self, "_deadline_timer", None)
        if deadline is None:
            return not getattr(self, "_deadline_expired", False)
        with self._deadline_lock:
            self._deadline_active = False
            expired = self._deadline_expired
        deadline.cancel()
        deadline.join()
        self._deadline_timer = None
        return not expired

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
                if type(response.body) is bytes:
                    self.wfile.write(response.body)
                else:
                    try:
                        while block := response.body.stream.read(DOCUMENT_IO_CHUNK_BYTES):
                            self.wfile.write(block)
                    finally:
                        response.body.close()
            except ConnectionError:
                pass
        self.close_connection = True

    def _handle_request(self):
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
                "X-Document-Filename",
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
                bridge = self.server.bridge
                if bridge is None:
                    response = _error(503, "PRODUCT_BRIDGE_UNAVAILABLE", "serviço local indisponível")
                elif length > bridge.request_body_limit(self.command, self.path):
                    response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                else:
                    spool = None
                    try:
                        document_upload = (
                            self.command == "POST"
                            and self.path.startswith("/app-api/v1/workspaces/")
                            and self.path.endswith(("/materials", "/inspection-photos", "/delivery-templates", "/delivery-supporting-files"))
                        )
                        if length and document_upload:
                            spool = tempfile.SpooledTemporaryFile(max_size=1_048_576, mode="w+b")
                            remaining = length
                            while remaining:
                                block = self.rfile.read(min(DOCUMENT_IO_CHUNK_BYTES, remaining))
                                if not block:
                                    return _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                                spool.write(block)
                                remaining -= len(block)
                            spool.seek(0)
                            body = SeekableContent(spool, length)
                        else:
                            body = self.rfile.read(length) if length else b""
                            if len(body) != length:
                                response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                                return response
                        if not self._finish_request_acquisition():
                            response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                        else:
                            response = bridge.handle(
                                self.command,
                                self.path,
                                dict(self.headers.items()),
                                body,
                            )
                    except (TimeoutError, OSError):
                        return _error(
                            400,
                            "INVALID_PRODUCT_REQUEST",
                            "requisição local inválida",
                        )
                    finally:
                        if spool is not None:
                            spool.close()
        return response

    def _dispatch(self):
        try:
            response = self._handle_request()
        except Exception:
            response = _error(500, "PRODUCT_BRIDGE_FAILURE", "falha local")
        if not self._finish_request_acquisition():
            response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
        try:
            self._write_response(response)
        except OSError:
            self.close_connection = True

    def send_error(self, code, _message=None, _explain=None):
        self._finish_request_acquisition()
        if code == 501:
            response = _error(405, "METHOD_NOT_ALLOWED", "método não permitido")
        else:
            response = _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
        try:
            self._write_response(response)
        except OSError:
            self.close_connection = True

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
        self._server.request_timeout_seconds = self._config.request_timeout_seconds
        host, port = self.address
        self._server.bridge = ProductBridge(
            frontend_root=frontend_root,
            public_origin=f"http://{host}:{port}",
            upstream_address=upstream_address,
            token=token,
            max_body_bytes=self._config.max_body_bytes,
            max_document_body_bytes=self._config.max_document_body_bytes,
            request_timeout_seconds=self._config.upstream_timeout_seconds,
        )
        self._thread: Thread | None = None
        self._serve_stopped = Event()
        self._serve_error: Exception | None = None
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
                target=self._serve,
                name="product-bridge-loopback",
                daemon=True,
            )
            try:
                self._thread.start()
            except RuntimeError as exc:
                self._thread = None
                self._closed = True
                self._server.server_close()
                raise ProductBridgeServerStartError(
                    "product bridge não pôde iniciar"
                ) from exc
            for _ in range(500):
                if self._server.serve_ready.wait(0.01):
                    break
                if self._serve_stopped.is_set():
                    break
            if not self._server.serve_ready.is_set():
                self._closed = True
                self._server.server_close()
                self._thread.join(timeout=5)
                self._thread = None
                raise ProductBridgeServerStartError("product bridge indisponível")
            if self._serve_stopped.is_set() or not self._thread.is_alive():
                cause = self._serve_error
                self._closed = True
                self._server.server_close()
                self._thread.join(timeout=5)
                self._thread = None
                raise ProductBridgeServerStartError("product bridge indisponível") from cause
            return self.address

    def _serve(self) -> None:
        try:
            self._server.serve_forever(poll_interval=0.01)
        except Exception as exc:
            self._serve_error = exc
        finally:
            self._serve_stopped.set()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._thread is not None:
                self._server.shutdown()
                self._thread.join(timeout=5)
            self._server.server_close()
