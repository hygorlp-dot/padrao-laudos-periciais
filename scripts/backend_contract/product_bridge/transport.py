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

from ..streaming import (
    DOCUMENT_IO_CHUNK_BYTES,
    MAX_DOCUMENT_BYTES,
    SeekableContent,
    StreamBody,
    as_seekable_content,
)


_CANONICAL_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ASSET_PATH = re.compile(r"/assets/[A-Za-z0-9][A-Za-z0-9._-]*")
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

__all__ = [
    "DOCUMENT_IO_CHUNK_BYTES",
    "MAX_DOCUMENT_BYTES",
    "ProductBridge",
    "SeekableContent",
]


@dataclass(frozen=True, slots=True)
class BridgeResponse:
    status: int
    headers: MappingProxyType
    body: bytes | StreamBody


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
    if type(target) is not str or not target.startswith("/") or any(ord(character) < 32 or character.isspace() for character in target) or "%" in target or "\\" in target:
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
    if path.startswith(prefix):
        remainder = path[len(prefix) :].split("/")
        if len(remainder) == 2 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1] == "materials" and method in {"GET", "POST"}:
            return f"/v1/workspaces/{remainder[0]}/materials"
        if len(remainder) == 2 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1] == "case-analysis" and method in {"GET", "POST"}:
            return f"/v1/workspaces/{remainder[0]}/{remainder[1]}"
        if len(remainder) == 2 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1] == "pericial-planning" and method in {"GET", "PUT"}:
            return f"/v1/workspaces/{remainder[0]}/{remainder[1]}"
        if len(remainder) == 2 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1] == "inspection-session" and method in {"GET", "POST", "PUT"}:
            return f"/v1/workspaces/{remainder[0]}/{remainder[1]}"
        if len(remainder) == 2 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1] == "technical-snapshot" and method in {"GET", "POST", "PUT"}:
            return f"/v1/workspaces/{remainder[0]}/{remainder[1]}"
        if len(remainder) == 2 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1] == "inspection-photos" and method == "POST":
            return f"/v1/workspaces/{remainder[0]}/inspection-photos"
        if len(remainder) == 3 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1:] == ["pericial-planning", "decisions"] and method == "POST":
            return f"/v1/workspaces/{remainder[0]}/pericial-planning/decisions"
        if len(remainder) == 3 and _CANONICAL_UUID.fullmatch(remainder[0]) and remainder[1] == "materials" and _CANONICAL_UUID.fullmatch(remainder[2]) and method == "GET":
            return f"/v1/workspaces/{remainder[0]}/materials/{remainder[2]}"
        if (
            len(remainder) == 3
            and _CANONICAL_UUID.fullmatch(remainder[0])
            and remainder[1:]
            == [
                "process-metadata",
                "source-span-confirmations",
            ]
            and method == "POST"
        ):
            return f"/v1/workspaces/{remainder[0]}/process-metadata/source-span-confirmations"
    process_case_suffix = "/process-case"
    if method in {"GET", "POST"} and path.startswith(prefix) and path.endswith(process_case_suffix):
        workspace_id = path[len(prefix) : -len(process_case_suffix)]
        if _CANONICAL_UUID.fullmatch(workspace_id):
            return f"/v1/workspaces/{workspace_id}/process-case"
    process_metadata_suffix = "/process-metadata"
    if method == "GET" and path.startswith(prefix) and path.endswith(process_metadata_suffix):
        workspace_id = path[len(prefix) : -len(process_metadata_suffix)]
        if _CANONICAL_UUID.fullmatch(workspace_id):
            return f"/v1/workspaces/{workspace_id}/process-metadata"
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
        max_document_body_bytes: int,
        request_timeout_seconds: float,
    ):
        root = Path(frontend_root).resolve()
        if not root.is_dir() or not (root / "index.html").is_file():
            raise ValueError("build frontend inválido")
        if not re.fullmatch(r"http://127\.0\.0\.1:[1-9][0-9]{0,4}", public_origin):
            raise ValueError("origem local inválida")
        if type(upstream_address) is not tuple or len(upstream_address) != 2 or upstream_address[0] != "127.0.0.1" or type(upstream_address[1]) is not int or not 1 <= upstream_address[1] <= 65_535:
            raise ValueError("upstream local inválido")
        if type(token) is not str or len(token) < 32:
            raise ValueError("token local inválido")
        if type(max_body_bytes) is not int or not 1 <= max_body_bytes <= 1_048_576:
            raise ValueError("limite de body inválido")
        if type(max_document_body_bytes) is not int or not 1 <= max_document_body_bytes <= MAX_DOCUMENT_BYTES:
            raise ValueError("limite de documento inválido")
        self._frontend_root = root
        self._public_origin = public_origin
        self._public_host = public_origin.removeprefix("http://")
        self._upstream_address = upstream_address
        self._token = token
        self._max_body_bytes = max_body_bytes
        self._max_document_body_bytes = max_document_body_bytes
        self._request_timeout_seconds = request_timeout_seconds

    def request_body_limit(self, method: str, target: str) -> int:
        """Mantém JSON no teto legado e amplia somente o POST documental exato."""

        try:
            normalized_method = method.upper()
            path = _canonical_path(target)
        except (AttributeError, TypeError, ValueError):
            return self._max_body_bytes
        upstream_target = _proxy_target(path, normalized_method)
        if normalized_method == "POST" and upstream_target is not None and upstream_target.endswith(("/materials", "/inspection-photos")):
            return self._max_document_body_bytes
        return self._max_body_bytes

    def _response_body_limit(self, method: str, upstream_target: str) -> int:
        if method == "GET" and re.fullmatch(
            rf"/v1/workspaces/{_CANONICAL_UUID.pattern}/materials/"
            rf"{_CANONICAL_UUID.pattern}",
            upstream_target,
        ):
            return self._max_document_body_bytes
        return self._max_body_bytes

    def __repr__(self) -> str:
        return f"ProductBridge(public_origin={self._public_origin!r})"

    def _browser_request_allowed(self, method: str, headers: dict[str, str]) -> bool:
        if headers.get("host") != self._public_host:
            return False
        origin = headers.get("origin")
        fetch_site = headers.get("sec-fetch-site")
        if method in {"POST", "PUT"}:
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
        body: bytes | SeekableContent,
    ) -> BridgeResponse:
        request_limit = self._max_document_body_bytes if method == "POST" and upstream_target.endswith(("/materials", "/inspection-photos")) else self._max_body_bytes
        body_size = len(body) if type(body) is bytes else as_seekable_content(body).byte_size
        if body_size > request_limit:
            return _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
        upstream_headers = {
            "Host": f"{self._upstream_address[0]}:{self._upstream_address[1]}",
            "X-Local-API-Token": self._token,
        }
        if method in {"POST", "PUT"}:
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            is_document = upstream_target.endswith("/materials")
            is_photo = upstream_target.endswith("/inspection-photos")
            if content_type not in ({"application/pdf"} if is_document else {"image/jpeg", "image/png"} if is_photo else {"application/json"}):
                return _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
            if is_document or is_photo:
                filename = headers.get("x-document-filename", "")
                if not filename or len(filename) > 1024 or not filename.isascii() or any(ord(character) < 33 or ord(character) > 126 for character in filename):
                    return _error(400, "INVALID_PRODUCT_REQUEST", "requisição local inválida")
                upstream_headers["X-Document-Filename"] = filename
            upstream_headers["Content-Type"] = content_type
            upstream_headers["Content-Length"] = str(body_size)
        connection = http.client.HTTPConnection(
            *self._upstream_address,
            timeout=self._request_timeout_seconds,
        )
        retained_connection = False
        try:
            if type(body) is SeekableContent:
                body.rewind()
                upstream_body = body.stream
            else:
                upstream_body = body or None
            connection.request(method, upstream_target, body=upstream_body, headers=upstream_headers)
            upstream = connection.getresponse()
            response_limit = self._response_body_limit(method, upstream_target)
            is_document_read = response_limit == self._max_document_body_bytes and method == "GET"
            if is_document_read and upstream.status == 200:
                raw_length = upstream.getheader("Content-Length") or ""
                content_type = (upstream.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
                if not raw_length.isascii() or not raw_length.isdecimal() or int(raw_length) > response_limit or content_type != "application/pdf":
                    return _error(502, "INVALID_LOCAL_API_RESPONSE", "resposta local inválida")
                length = int(raw_length)
                retained_connection = True
                body_stream = StreamBody(upstream, length, connection.close)
                headers_out = MappingProxyType(
                    {
                        "Content-Type": "application/pdf",
                        "Content-Length": str(length),
                        "Cache-Control": "no-store",
                        **_SECURITY_HEADERS,
                    }
                )
                return BridgeResponse(upstream.status, headers_out, body_stream)
            response_body = upstream.read(response_limit + 1)
            if len(response_body) > response_limit:
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
            if not retained_connection:
                connection.close()

    def handle(
        self,
        method: str,
        target: str,
        headers: dict[str, str],
        body: bytes | SeekableContent,
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
