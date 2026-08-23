"""Roteamento e DTOs HTTP sem dependência de Infrastructure ou Core."""

from __future__ import annotations

import hmac
import json
import string
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from urllib.parse import unquote_to_bytes, urlsplit

from ..application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    WorkspaceId,
    thaw_payload,
)
from ..application.ports import (
    ArtifactRevisionNotFound,
    PersistenceSchemaError,
    RepositoryConflict,
    RepositoryError,
    RepositoryIntegrityError,
    WorkspaceNotFound,
)

_MAX_SAFE_JSON_INTEGER = (1 << 53) - 1


class _JsonSerializationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: MappingProxyType
    body: bytes


@dataclass(frozen=True, slots=True)
class LocalApiServices:
    create_workspace: object
    get_workspace: object
    list_workspaces: object
    append_artifact_revision: object
    get_latest_artifact: object
    get_artifact_revision: object
    list_artifact_revisions: object


def _workspace_dto(record: PericiaWorkspace) -> dict:
    return {
        "workspace_id": str(record.workspace_id),
        "name": record.name,
        "created_at": record.created_at,
    }


def _revision_dto(record: ArtifactRevision) -> dict:
    return {
        "workspace_id": str(record.workspace_id),
        "artifact_kind": record.artifact_kind,
        "artifact_id": record.artifact_id,
        "revision_id": record.revision_id,
        "revision": record.revision,
        "created_at": record.created_at,
        "checksum_sha256": record.checksum_sha256,
        "payload": thaw_payload(record.payload),
    }


def _json_response(status: int, value: object) -> HttpResponse:
    _require_safe_json_integers(value)
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return HttpResponse(
        status=status,
        headers=MappingProxyType(
            {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body)),
                "Cache-Control": "no-store",
            }
        ),
        body=body,
    )


def _error(
    status: int, code: str, message: str = "requisição local inválida"
) -> HttpResponse:
    return _json_response(
        status,
        {"error": {"code": code, "message": message}},
    )


def _decode_segment(value: str) -> str:
    for index, character in enumerate(value):
        if character == "%" and (
            index + 2 >= len(value)
            or value[index + 1] not in string.hexdigits
            or value[index + 2] not in string.hexdigits
        ):
            raise ValueError("percent-encoding inválido")
    decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    if not decoded or "\x00" in decoded:
        raise ValueError("segmento de rota inválido")
    return decoded


def _has_ascii_control(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _normalized_headers(headers) -> dict[str, str]:
    if not hasattr(headers, "items"):
        raise TypeError("headers inválidos")
    result = {}
    for key, value in headers.items():
        if type(key) is not str or type(value) is not str:
            raise TypeError("header inválido")
        result[key.lower()] = value
    return result


def _local_host_allowed(value: str | None) -> bool:
    if not value or type(value) is not str or _has_ascii_control(value):
        return False
    try:
        parsed = urlsplit(f"//{value}")
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.hostname in {"127.0.0.1", "localhost"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
    )


def _require_local_token(token: str) -> str:
    if (
        type(token) is not str
        or len(token) < 32
        or not token.isascii()
        or not token.isprintable()
        or any(character.isspace() for character in token)
    ):
        raise ValueError("token local inválido")
    return token


def _json_object_without_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("chave JSON duplicada")
        value[key] = item
    return value


def _reject_nonstandard_json_constant(_value: str):
    raise ValueError("constante JSON invalida")


def _json_float_without_value_loss(source: str) -> float:
    value = float(source)
    canonical = json.dumps(value, allow_nan=False)
    if Decimal(source) != Decimal(canonical):
        raise ValueError("numero JSON perde precisao")
    return value


def _json_int_without_value_loss(source: str) -> int:
    value = int(source)
    if source == "-0" or abs(value) > _MAX_SAFE_JSON_INTEGER:
        raise ValueError("inteiro JSON perde fidelidade entre runtimes")
    return value


def _require_safe_json_integers(value: object) -> None:
    if type(value) is int:
        if abs(value) > _MAX_SAFE_JSON_INTEGER:
            raise _JsonSerializationError("inteiro JSON inseguro na resposta")
        return
    if type(value) is dict:
        for item in value.values():
            _require_safe_json_integers(item)
        return
    if type(value) in {list, tuple}:
        for item in value:
            _require_safe_json_integers(item)


def _parse_content_length(value: str) -> int:
    if (
        type(value) is not str
        or not value
        or not value.isascii()
        or not value.isdecimal()
    ):
        raise ValueError("Content-Length invalido")
    return int(value)


def _target_segments(target: str) -> tuple[str, ...]:
    if type(target) is not str:
        raise TypeError("target inválido")
    if _has_ascii_control(target):
        raise ValueError("target contains ASCII control")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("target deve conter somente path")
    if not parsed.path.startswith("/"):
        raise ValueError("path absoluto obrigatório")
    return tuple(_decode_segment(item) for item in parsed.path.split("/")[1:])


class LocalApi:
    def __init__(
        self,
        services: LocalApiServices,
        *,
        token: str,
        max_body_bytes: int = 1_048_576,
    ):
        if type(services) is not LocalApiServices:
            raise TypeError("services inválidos")
        _require_local_token(token)
        if type(max_body_bytes) is not int or max_body_bytes < 1:
            raise ValueError("limite de body inválido")
        self._services = services
        self._token = token
        self._max_body_bytes = max_body_bytes

    def _request_dto(self, headers: dict[str, str], body: bytes) -> dict:
        if type(body) is not bytes or len(body) > self._max_body_bytes:
            raise ValueError("body inválido")
        content_type = headers.get("content-type", "").split(";", 1)[0]
        if content_type.strip().lower() != "application/json":
            raise ValueError("Content-Type inválido")
        try:
            length = _parse_content_length(headers.get("content-length", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError("Content-Length inválido") from exc
        if length != len(body) or length < 1:
            raise ValueError("Content-Length diverge")
        value = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_without_duplicate_keys,
            parse_constant=_reject_nonstandard_json_constant,
            parse_float=_json_float_without_value_loss,
            parse_int=_json_int_without_value_loss,
        )
        if type(value) is not dict:
            raise TypeError("DTO deve ser objeto JSON")
        return value

    @staticmethod
    def _workspace_id(value: str) -> WorkspaceId:
        return WorkspaceId.parse(value)

    def handle(self, method: str, target: str, headers, body: bytes) -> HttpResponse:
        try:
            if type(method) is not str:
                raise TypeError("request inválida")
            request_headers = _normalized_headers(headers)
            if not _local_host_allowed(request_headers.get("host")):
                return _error(
                    403,
                    "FORBIDDEN_LOCAL_REQUEST",
                    "requisição local não autorizada",
                )
            if "origin" in request_headers or request_headers.get(
                "sec-fetch-site", "none"
            ).lower() not in {"none", "same-origin"}:
                return _error(
                    403,
                    "FORBIDDEN_LOCAL_REQUEST",
                    "requisição local não autorizada",
                )
            segments = _target_segments(target)
            normalized_method = method.upper()
            if normalized_method == "POST" and not hmac.compare_digest(
                request_headers.get("x-local-api-token", ""), self._token
            ):
                return _error(
                    403,
                    "FORBIDDEN_LOCAL_REQUEST",
                    "requisição local não autorizada",
                )
            if "transfer-encoding" in request_headers:
                raise ValueError("Transfer-Encoding não suportado")

            if segments == ("v1", "workspaces"):
                if normalized_method == "GET":
                    records = self._services.list_workspaces.execute()
                    return _json_response(
                        200, {"items": [_workspace_dto(item) for item in records]}
                    )
                if normalized_method == "POST":
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"name"} or type(dto["name"]) is not str or not dto[
                        "name"
                    ].strip():
                        raise ValueError("name inválido")
                    record = self._services.create_workspace.execute(dto["name"])
                    return _json_response(201, _workspace_dto(record))
                return _error(405, "METHOD_NOT_ALLOWED")

            if len(segments) == 3 and segments[:2] == ("v1", "workspaces"):
                if normalized_method != "GET":
                    return _error(405, "METHOD_NOT_ALLOWED")
                record = self._services.get_workspace.execute(
                    self._workspace_id(segments[2])
                )
                return _json_response(200, _workspace_dto(record))

            artifact_route = (
                len(segments) in {7, 8}
                and segments[:2] == ("v1", "workspaces")
                and segments[3] == "artifacts"
                and segments[6] == "revisions"
            )
            if artifact_route:
                if len(segments) == 7 and normalized_method == "POST":
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"payload"}:
                        raise ValueError("payload ausente")
                    record = self._services.append_artifact_revision.execute(
                        workspace_id=self._workspace_id(segments[2]),
                        artifact_kind=segments[4],
                        artifact_id=segments[5],
                        payload=dto["payload"],
                    )
                    return _json_response(201, _revision_dto(record))
                if len(segments) == 7 and normalized_method == "GET":
                    records = self._services.list_artifact_revisions.execute(
                        self._workspace_id(segments[2]), segments[4], segments[5]
                    )
                    return _json_response(
                        200, {"items": [_revision_dto(item) for item in records]}
                    )
                if len(segments) == 8 and normalized_method == "GET":
                    workspace_id = self._workspace_id(segments[2])
                    if segments[7] == "latest":
                        record = self._services.get_latest_artifact.execute(
                            workspace_id, segments[4], segments[5]
                        )
                    else:
                        if not segments[7].isdigit():
                            raise ValueError("revision inválida")
                        revision = int(segments[7])
                        if revision < 1 or revision > _MAX_SAFE_JSON_INTEGER:
                            raise ValueError("revision inválida")
                        record = self._services.get_artifact_revision.execute(
                            workspace_id, segments[4], segments[5], revision
                        )
                    return _json_response(200, _revision_dto(record))
                return _error(405, "METHOD_NOT_ALLOWED")

            return _error(404, "NOT_FOUND")
        except _JsonSerializationError:
            return _error(
                500,
                "LOCAL_API_SERIALIZATION_FAILURE",
                "resposta local invÃ¡lida",
            )
        except WorkspaceNotFound:
            return _error(404, "WORKSPACE_NOT_FOUND", "workspace não encontrado")
        except ArtifactRevisionNotFound:
            return _error(
                404,
                "ARTIFACT_REVISION_NOT_FOUND",
                "revisão de artefato não encontrada",
            )
        except RepositoryConflict:
            return _error(409, "REPOSITORY_CONFLICT", "conflito de persistência local")
        except RepositoryIntegrityError:
            return _error(
                500,
                "REPOSITORY_INTEGRITY_FAILURE",
                "integridade da persistência local inválida",
            )
        except PersistenceSchemaError:
            return _error(
                500,
                "PERSISTENCE_SCHEMA_FAILURE",
                "schema da persistência local inválido",
            )
        except RepositoryError:
            return _error(
                503, "REPOSITORY_UNAVAILABLE", "persistência local indisponível"
            )
        except (
            json.JSONDecodeError,
            RecursionError,
            UnicodeError,
            TypeError,
            ValueError,
        ):
            return _error(400, "INVALID_REQUEST")
