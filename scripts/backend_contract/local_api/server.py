"""Servidor HTTP estritamente loopback para a Local API."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from .transport import LocalApi, _error


@dataclass(frozen=True, slots=True)
class LocalServerConfig:
    host: str = "127.0.0.1"
    port: int = 0
    max_body_bytes: int = 1_048_576

    def __post_init__(self):
        if self.host != "127.0.0.1":
            raise ValueError("servidor exige bind loopback literal")
        if type(self.port) is not int:
            raise TypeError("porta local inválida")
        if self.port < 0 or self.port > 65_535:
            raise ValueError("porta local inválida")
        if type(self.max_body_bytes) is not int or self.max_body_bytes < 1:
            raise ValueError("limite de body inválido")


class _ThreadingLocalServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False


class LocalApiServerStartError(RuntimeError):
    """Falha sanitizada ao iniciar a thread do listener já criado."""


def _handler_for(api: LocalApi, max_body_bytes: int):
    class LocalRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _write_response(self, response):
            is_head = self.command == "HEAD"
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
                except (BrokenPipeError, ConnectionResetError):
                    pass
            self.close_connection = True

        def _dispatch(self):
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
                    "X-Local-API-Token",
                )
            )
            if duplicate_sensitive_header:
                response = _error(400, "INVALID_REQUEST")
            else:
                raw_length = self.headers.get("Content-Length", "0")
                try:
                    length = int(raw_length)
                except (TypeError, ValueError):
                    length = -1
                if length < 0 or length > max_body_bytes:
                    self.close_connection = True
                    response = _error(400, "INVALID_REQUEST")
                else:
                    body = self.rfile.read(length) if length else b""
                    response = api.handle(
                        self.command, self.path, dict(self.headers.items()), body
                    )
            self._write_response(response)

        def send_error(self, code, _message=None, _explain=None):
            if code == 501:
                response = _error(405, "METHOD_NOT_ALLOWED")
            else:
                response = _error(400, "INVALID_REQUEST")
            self._write_response(response)

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
        self._config = config or LocalServerConfig()
        if type(self._config) is not LocalServerConfig:
            raise TypeError("configuração local inválida")
        self._server = _ThreadingLocalServer(
            (self._config.host, self._config.port),
            _handler_for(api, self._config.max_body_bytes),
        )
        self._thread: Thread | None = None
        self._closed = False

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> tuple[str, int]:
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
            raise LocalApiServerStartError("servidor local não pôde iniciar") from exc
        return self.address

    def _serve(self) -> None:
        self._server.serve_forever(poll_interval=0.01)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
        self._server.server_close()
