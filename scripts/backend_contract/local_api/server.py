"""Servidor HTTP estritamente loopback para a Local API."""

from __future__ import annotations

import math
import socket
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread, Timer

from .transport import LocalApi, _error, _parse_content_length


@dataclass(frozen=True, slots=True)
class LocalServerConfig:
    host: str = "127.0.0.1"
    port: int = 0
    max_body_bytes: int = 1_048_576
    max_document_body_bytes: int = 16_777_216
    request_timeout_seconds: float = 5.0

    def __post_init__(self):
        if self.host != "127.0.0.1":
            raise ValueError("servidor exige bind loopback literal")
        if type(self.port) is not int:
            raise TypeError("porta local inválida")
        if self.port < 0 or self.port > 65_535:
            raise ValueError("porta local inválida")
        if (
            type(self.max_body_bytes) is not int
            or not 1 <= self.max_body_bytes <= 1_048_576
        ):
            raise ValueError("limite de body inválido")
        if (
            type(self.max_document_body_bytes) is not int
            or not 1 <= self.max_document_body_bytes <= 16_777_216
        ):
            raise ValueError("limite de documento inválido")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, (int, float))
            or not math.isfinite(self.request_timeout_seconds)
            or self.request_timeout_seconds <= 0
            or self.request_timeout_seconds > 30
        ):
            raise ValueError("timeout local inválido")


class _ThreadingLocalServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False

    def __init__(self, *args, **kwargs):
        self.serve_ready = Event()
        super().__init__(*args, **kwargs)

    def service_actions(self):
        super().service_actions()
        self.serve_ready.set()

    def handle_error(self, _request, _client_address):
        return


class LocalApiServerStartError(RuntimeError):
    """Falha sanitizada ao iniciar a thread do listener já criado."""


def _handler_for(
    api: LocalApi,
    request_timeout_seconds: float,
):
    class LocalRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(request_timeout_seconds)

        def parse_request(self):
            if not super().parse_request():
                return False
            try:
                canonical_request_line = (
                    self.command.encode("ascii")
                    + b" "
                    + self.path.encode("iso-8859-1")
                    + b" "
                    + self.protocol_version.encode("ascii")
                    + b"\r\n"
                )
            except UnicodeEncodeError:
                canonical_request_line = b""
            if self.raw_requestline != canonical_request_line:
                self.send_error(400)
                return False
            return True

        def handle_one_request(self):
            self._deadline_lock = Lock()
            self._deadline_active = True
            self._deadline_expired = False
            self._deadline_timer = Timer(
                request_timeout_seconds,
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
            is_head = getattr(self, "command", None) == "HEAD"
            self.request_version = self.protocol_version
            self.send_response_only(response.status)
            for name, value in response.headers.items():
                if is_head and name.lower() == "content-length":
                    value = "0"
                self.send_header(name, value)
            self.send_header("Connection", "close")
            self.end_headers()
            if not is_head:
                try:
                    self.wfile.write(response.body)
                except ConnectionError:
                    pass
            self.close_connection = True

        def _handle_request(self):
            if self.request_version != self.protocol_version:
                return _error(400, "INVALID_REQUEST")
            duplicate_sensitive_header = any(
                len(self.headers.get_all(name, [])) != 1
                for name in ("Host",)
            ) or any(
                len(self.headers.get_all(name, [])) > 1
                for name in (
                    "Content-Length",
                    "Content-Type",
                    "Origin",
                    "Transfer-Encoding",
                    "X-Document-Filename",
                    "X-Local-API-Token",
                )
            )
            if duplicate_sensitive_header:
                response = _error(400, "INVALID_REQUEST")
            else:
                raw_length = self.headers.get("Content-Length", "0")
                try:
                    length = _parse_content_length(raw_length)
                except (TypeError, ValueError):
                    length = -1
                body_limit = api.request_body_limit(self.command, self.path)
                if length < 0 or length > body_limit:
                    self.close_connection = True
                    response = _error(400, "INVALID_REQUEST")
                else:
                    try:
                        body = self.rfile.read(length) if length else b""
                    except (TimeoutError, OSError):
                        return _error(400, "INVALID_REQUEST")
                    if len(body) != length:
                        return _error(400, "INVALID_REQUEST")
                    if not self._finish_request_acquisition():
                        return _error(400, "INVALID_REQUEST")
                    response = api.handle(
                        self.command, self.path, dict(self.headers.items()), body
                    )
            return response

        def _dispatch(self):
            try:
                response = self._handle_request()
            except Exception:
                response = _error(
                    500,
                    "INTERNAL_SERVER_ERROR",
                    "falha interna da API local",
                )
            acquisition_complete = self._finish_request_acquisition()
            if not acquisition_complete:
                response = _error(400, "INVALID_REQUEST")
            try:
                self._write_response(response)
            except ConnectionError:
                self.close_connection = True

        def send_error(self, code, _message=None, _explain=None):
            self._finish_request_acquisition()
            if code == 501:
                response = _error(405, "METHOD_NOT_ALLOWED")
            else:
                response = _error(400, "INVALID_REQUEST")
            try:
                self._write_response(response)
            except ConnectionError:
                self.close_connection = True

        do_GET = _dispatch
        do_POST = _dispatch
        do_PUT = _dispatch
        do_PATCH = _dispatch
        do_DELETE = _dispatch
        do_OPTIONS = _dispatch

        def log_message(self, _format, *_args):
            return

    return LocalRequestHandler


class LocalApiServer:
    def __init__(
        self,
        api: LocalApi,
        config: LocalServerConfig | None = None,
    ):
        if type(api) is not LocalApi:
            raise TypeError("LocalApi inválida")
        self._config = LocalServerConfig() if config is None else config
        if type(self._config) is not LocalServerConfig:
            raise TypeError("configuração local inválida")
        self._server = _ThreadingLocalServer(
            (self._config.host, self._config.port),
            _handler_for(
                api,
                self._config.request_timeout_seconds,
            ),
        )
        self._thread: Thread | None = None
        self._serve_stopped = Event()
        self._serve_error: Exception | None = None
        self._closed = False
        self._lifecycle_lock = Lock()

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> tuple[str, int]:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("servidor local fechado")
            if self._thread is not None:
                raise RuntimeError("servidor local já iniciado")
            self._thread = Thread(
                target=self._serve,
                name="local-api-loopback",
                daemon=True,
            )
            try:
                self._thread.start()
            except RuntimeError as exc:
                self._thread = None
                self._closed = True
                self._server.server_close()
                raise LocalApiServerStartError(
                    "servidor local não pôde iniciar"
                ) from exc
            for _ in range(500):
                if self._server.serve_ready.wait(timeout=0.01):
                    break
                if self._serve_stopped.is_set():
                    break
            if not self._server.serve_ready.is_set():
                self._closed = True
                self._server.server_close()
                self._thread.join(timeout=5)
                self._thread = None
                raise LocalApiServerStartError("servidor local indisponivel")
            if self._serve_stopped.is_set() or not self._thread.is_alive():
                cause = self._serve_error
                self._closed = True
                self._server.server_close()
                self._thread.join(timeout=5)
                self._thread = None
                raise LocalApiServerStartError(
                    "servidor local indisponivel"
                ) from cause
            return self.address

    def _serve(self) -> None:
        try:
            self._server.serve_forever(poll_interval=0.01)
        except Exception as exc:
            self._serve_error = exc
        finally:
            self._serve_stopped.set()

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            if self._thread is not None:
                self._server.shutdown()
                self._thread.join(timeout=5)
            self._server.server_close()
