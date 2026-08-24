"""Política browser-facing e forwarding opaco do produto local."""

from __future__ import annotations

import http.client
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit


_CANONICAL_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
_ASSET_PATH = re.compile(r"/assets/[A-Za-z0-9][A-Za-z0-9._-]*")
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


@dataclass(frozen=True, slots=True)
class BridgeResponse:
    status: int
    headers: MappingProxyType
    body: bytes


def _response(status: int, body: bytes, content_type: str, *, cache: str) -> BridgeResponse:
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Cache-Control": cache,
        **_SECURITY_HEADERS,
    }
    return BridgeResponse(status, MappingProxyType(headers), body)


def _error(status: int, code: str, message: str) -> BridgeResponse:
    body = json.dumps(
        {"error": {"code": code, "message": message}},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _response(
        status,
        body,
        "application/json; charset=utf-8",
        cache="no-store",
    )


def _canonical_path(target: str) -> str:
    if (
        type(target) is not str
        or not target.startswith("/")
        or any(ord(character) < 32 or character.isspace() for character in target)
        or "%" in target
        or "\\" in target
    ):
        raise ValueError("target inválido")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("target inválido")
    return parsed.path


def _is_spa_path(path: str) -> bool:
    if path == "/":
        return True
    segments = path.removeprefix("/").split("/")
    return all(segment not in {"", ".", ".."} for segment in segments)


def _proxy_target(path: str, method: str) -> str | None:
    if path == "/app-api/v1/workspaces" and method in {"GET", "POST"}:
        return "/v1/workspaces"
    prefix = "/app-api/v1/workspaces/"
    process_case_suffix = "/process-case"
    if method in {"GET", "POST"} and path.startswith(prefix) and path.endswith(
        process_case_suffix
    ):
        workspace_id = path[len(prefix) : -len(process_case_suffix)]
        if _CANONICAL_UUID.fullmatch(workspace_id):
            return f"/v1/workspaces/{workspace_id}/process-case"
    if method == "GET" and path.startswith(prefix):
        workspace_id = path[len(prefix) :]
        if _CANONICAL_UUID.fullmatch(workspace_id):
            return f"/v1/workspaces/{workspace_id}"
    return None


class ProductBridge:
    """Executa somente política HTTP e forwarding; não interpreta domínio."""

    def __init__(
        self,
        *,
        frontend_root: str | Path,
        public_origin: str,
        upstream_address: tuple[str, int],
        token: str,
        max_body_bytes: int,
        request_timeout_seconds: float,
    ):
        root = Path(frontend_root).resolve()
        if not root.is_dir() or not (root / "index.html").is_file():
            raise ValueError("build frontend inválido")
        if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", public_origin):
            raise ValueError("origem local inválida")
        if (
            type(upstream_address) is not tuple
            or len(upstream_address) != 2
            or upstream_address[0] != "127.0.0.1"
            or type(upstream_address[1]) is not int
            or not 1 <= upstream_address[1] <= 65_535
        ):
            raise ValueError("upstream local inválido")
        if type(token) is not str or len(token) < 32:
            raise ValueError("token local inválido")
        self._frontend_root = root
        self._public_origin = public_origin
        self._public_host = public_origin.removeprefix("http://")
        self._upstream_address = upstream_address
        self._token = token
        self._max_body_bytes = max_body_bytes
        self._request_timeout_seconds = request_timeout_seconds

    def __repr__(self) -> str:
        return f"ProductBridge(public_origin={self._public_origin!r})"

    def _browser_request_allowed(
        self, method: str, headers: dict[str, str]
    ) -> bool:
        if headers.get("host") != self._public_host:
            return False
        origin = headers.get("origin")
        fetch_site = headers.get("sec-fetch-site")
        if method == "POST":
            return origin == self._public_origin and fetch_site == "same-origin"
        if origin is not None and origin != self._public_origin:
            return False
        return fetch_site is None or fetch_site in {"none", "same-origin"}

    def _static(self, path: str, method: str) -> BridgeResponse:
        if method not in {"GET", "HEAD"}:
            return _error(405, "METHOD_NOT_ALLOWED", "método não permitido")
        if path == "/assets" or path.startswith("/assets/"):
            if _ASSET_PATH.fullmatch(path) is None:
                return _error(404, "NOT_FOUND", "recurso local não encontrado")
            candidate = self._frontend_root / path.removeprefix("/")
            cache = "public, max-age=31536000, immutable"
        elif _is_spa_path(path):
            candidate = self._frontend_root / "index.html"
            cache = "no-store"
        else:
            return _error(404, "NOT_FOUND", "recurso local não encontrado")
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._frontend_root) or not resolved.is_file():
            return _error(404, "NOT_FOUND", "recurso local não encontrado")
        body = resolved.read_bytes()
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if resolved.suffix == ".js":
            content_type = "text/javascript"
        response = _response(status=200, body=body, content_type=content_type, cache=cache)
        if method == "HEAD":
            return BridgeResponse(response.status, response.headers, b"")
        return response

    def _forward(
        self,
        method: str,
        upstream_target: str,
        headers: dict[str, str],
        body: bytes,
    ) -> BridgeResponse:
        if len(body) > self._max_body_bytes:
            return _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
        upstream_headers = {
            "Host": f"{self._upstream_address[0]}:{self._upstream_address[1]}",
            "X-Local-API-Token": self._token,
        }
        if method == "POST":
            if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                return _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
            upstream_headers["Content-Type"] = "application/json"
            upstream_headers["Content-Length"] = str(len(body))
        connection = http.client.HTTPConnection(
            *self._upstream_address,
            timeout=self._request_timeout_seconds,
        )
        try:
            connection.request(method, upstream_target, body=body or None, headers=upstream_headers)
            upstream = connection.getresponse()
            response_body = upstream.read(self._max_body_bytes + 1)
            if len(response_body) > self._max_body_bytes:
                return _error(502, "INVALID_LOCAL_API_RESPONSE", "resposta local inválida")
            content_type = upstream.getheader("Content-Type") or "application/json; charset=utf-8"
            return _response(
                upstream.status,
                response_body,
                content_type,
                cache="no-store",
            )
        except (OSError, TimeoutError, http.client.HTTPException):
            return _error(503, "LOCAL_API_UNAVAILABLE", "serviço local indisponível")
        finally:
            connection.close()

    def handle(
        self,
        method: str,
        target: str,
        headers: dict[str, str],
        body: bytes,
    ) -> BridgeResponse:
        try:
            normalized_method = method.upper()
            path = _canonical_path(target)
            normalized_headers = {key.lower(): value for key, value in headers.items()}
            if not self._browser_request_allowed(normalized_method, normalized_headers):
                return _error(
                    403,
                    "FORBIDDEN_PRODUCT_REQUEST",
                    "requisição local não autorizada",
                )
            upstream_target = _proxy_target(path, normalized_method)
            if path == "/app-api" or path.startswith("/app-api/"):
                if upstream_target is None:
                    status = 405 if path == "/app-api/v1/workspaces" else 404
                    return _error(status, "NOT_FOUND", "rota local não disponível")
                return self._forward(
                    normalized_method,
                    upstream_target,
                    normalized_headers,
                    body,
                )
            return self._static(path, normalized_method)
        except (OSError, TypeError, ValueError):
            return _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
