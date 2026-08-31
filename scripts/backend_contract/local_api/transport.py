"""Roteamento e DTOs HTTP sem dependência de Infrastructure ou Core."""

from __future__ import annotations

import hmac
import json
import string
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from urllib.parse import unquote_to_bytes, urlsplit

from ..application.content import (
    DOCUMENT_IO_CHUNK_BYTES,
    MAX_DOCUMENT_BYTES,
    OpenPrivateContent,
    SeekableContent,
)
from ..application.process_metadata import ProcessMetadataReview, review_dto
from ..application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    ProcessCaseData,
    ProcessCaseSnapshot,
    WorkspaceId,
    thaw_payload,
)
from ..application.ports import (
    ArtifactRevisionNotFound,
    InvalidCaseDocument,
    PersistenceSchemaError,
    PrivateContentNotFound,
    PrivateContentTooLarge,
    RepositoryConflict,
    RepositoryError,
    RepositoryIntegrityError,
    WorkspaceNotFound,
    UnsupportedCaseDocument,
)
from ..application.case_analysis import (
    CASE_ANALYSIS_ARTIFACT_KIND,
    CaseAnalysisSnapshot,
    case_analysis_to_mapping,
    validated_case_analysis_from_mapping,
)
from ..application.pericial_planning import (
    PERICIAL_PLANNING_ARTIFACT_KIND,
    PlanningSnapshot,
    pericial_planning_to_mapping,
    validated_pericial_planning_from_mapping,
)
from ..application.vistoria import (
    inspection_session_to_validated_mapping,
    validated_inspection_session_from_mapping,
)

_MAX_SAFE_JSON_INTEGER = (1 << 53) - 1

__all__ = [
    "DOCUMENT_IO_CHUNK_BYTES",
    "MAX_DOCUMENT_BYTES",
    "LocalApi",
    "SeekableContent",
]


class _JsonSerializationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: MappingProxyType
    body: bytes | OpenPrivateContent


@dataclass(frozen=True, slots=True)
class LocalApiServices:
    create_workspace: object
    get_workspace: object
    list_workspaces: object
    append_artifact_revision: object
    get_latest_artifact: object
    get_artifact_revision: object
    list_artifact_revisions: object
    get_process_case: object
    save_process_case: object
    save_case_analysis: object | None = None
    get_case_analysis: object | None = None
    save_pericial_planning: object | None = None
    get_pericial_planning: object | None = None
    review_pericial_planning: object | None = None
    save_inspection_session: object | None = None
    get_inspection_session: object | None = None
    start_inspection_session: object | None = None
    get_process_metadata_review: object | None = None
    confirm_process_metadata_source_span: object | None = None
    import_case_document: object | None = None
    list_case_documents: object | None = None
    read_case_document: object | None = None
    import_inspection_photo: object | None = None


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


def _process_case_dto(record: ProcessCaseSnapshot, expected_workspace_id: WorkspaceId) -> dict:
    if type(record) is not ProcessCaseSnapshot or record.workspace_id != expected_workspace_id:
        raise RepositoryIntegrityError("identidade processual divergente")
    return {
        "workspace_id": str(record.workspace_id),
        "revision": record.revision,
        "updated_at": record.updated_at,
        "data": record.data.as_dict(),
    }


def _private_content_dto(record: PrivateContentMetadata, expected_workspace_id: WorkspaceId) -> dict:
    if type(record) is not PrivateContentMetadata or record.workspace_id != expected_workspace_id:
        raise RepositoryIntegrityError("identidade documental divergente")
    return {
        "workspace_id": str(record.workspace_id),
        "content_id": str(record.content_id),
        "original_filename": record.original_filename,
        "byte_size": record.byte_size,
        "checksum_sha256": record.checksum_sha256,
        "media_type": record.media_type,
        "imported_at": record.imported_at,
        "origin": record.origin.value,
    }


def _json_response(status: int, value: object) -> HttpResponse:
    try:
        _require_safe_json_integers(value)
        body = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except _JsonSerializationError:
        raise
    except (RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise _JsonSerializationError("resposta JSON invalida") from exc
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


def _binary_response(status: int, body: bytes | OpenPrivateContent, content_type: str) -> HttpResponse:
    if type(body) not in {bytes, OpenPrivateContent} or content_type != "application/pdf":
        raise RepositoryIntegrityError("resposta documental inválida")
    length = len(body) if type(body) is bytes else body.metadata.byte_size
    return HttpResponse(
        status=status,
        headers=MappingProxyType(
            {
                "Content-Type": content_type,
                "Content-Length": str(length),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            }
        ),
        body=body,
    )


def _error(status: int, code: str, message: str = "requisição local inválida") -> HttpResponse:
    return _json_response(
        status,
        {"error": {"code": code, "message": message}},
    )


def _decode_segment(value: str) -> str:
    for index, character in enumerate(value):
        if character == "%" and (index + 2 >= len(value) or value[index + 1] not in string.hexdigits or value[index + 2] not in string.hexdigits):
            raise ValueError("percent-encoding inválido")
    decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    if not decoded or _has_ascii_control(decoded):
        raise ValueError("segmento de rota inválido")
    return decoded


def _document_filename(value: str | None) -> str:
    if type(value) is not str or not value or len(value) > 1024 or not value.isascii():
        raise ValueError("filename de documento inválido")
    decoded = _decode_segment(value)
    if len(decoded) > 255:
        raise ValueError("filename de documento inválido")
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
    return parsed.hostname in {"127.0.0.1", "localhost"} and parsed.username is None and parsed.password is None and not parsed.path and not parsed.query and not parsed.fragment


def _require_local_token(token: str) -> str:
    if type(token) is not str or len(token) < 32 or not token.isascii() or not token.isprintable() or any(character.isspace() for character in token):
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
    if type(value) is not str or not value or not value.isascii() or not value.isdecimal():
        raise ValueError("Content-Length invalido")
    return int(value)


def _target_segments(target: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if type(target) is not str:
        raise TypeError("target inválido")
    if _has_ascii_control(target) or any(character.isspace() for character in target) or "?" in target or "#" in target:
        raise ValueError("target contains noncanonical syntax")
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("target deve conter somente path")
    if not parsed.path.startswith("/"):
        raise ValueError("path absoluto obrigatório")
    raw_segments = tuple(parsed.path.split("/")[1:])
    return raw_segments, tuple(_decode_segment(item) for item in raw_segments)


class LocalApi:
    def __init__(
        self,
        services: LocalApiServices,
        *,
        token: str,
        max_body_bytes: int = 1_048_576,
        max_document_body_bytes: int = MAX_DOCUMENT_BYTES,
    ):
        if type(services) is not LocalApiServices:
            raise TypeError("services inválidos")
        _require_local_token(token)
        if type(max_body_bytes) is not int or not 1 <= max_body_bytes <= 1_048_576:
            raise ValueError("limite de body inválido")
        if type(max_document_body_bytes) is not int or not 1 <= max_document_body_bytes <= MAX_DOCUMENT_BYTES:
            raise ValueError("limite de documento inválido")
        self._services = services
        self._token = token
        self._max_body_bytes = max_body_bytes
        self._max_document_body_bytes = max_document_body_bytes

    @property
    def body_limits(self) -> tuple[int, int]:
        return self._max_body_bytes, self._max_document_body_bytes

    def is_document_upload(self, method: str, target: str) -> bool:
        """Reconhece somente o POST documental com workspace canônico."""

        try:
            raw_segments, _segments = _target_segments(target)
        except (TypeError, ValueError):
            return False
        if not (type(method) is str and method.upper() == "POST" and len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] in {"materials", "inspection-photos"}):
            return False
        try:
            self._workspace_id(raw_segments[2])
        except (TypeError, ValueError):
            return False
        return True

    def request_body_limit(self, method: str, target: str) -> int:
        """Retorna o teto de aquisição sem ampliar rotas JSON legadas."""

        if self.is_document_upload(method, target):
            return self._max_document_body_bytes
        return self._max_body_bytes

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
        workspace_id = WorkspaceId.parse(value)
        if str(workspace_id) != value:
            raise ValueError("workspace_id nao canonico")
        return workspace_id

    def handle(
        self,
        method: str,
        target: str,
        headers,
        body: bytes | SeekableContent,
    ) -> HttpResponse:
        try:
            if type(method) is not str:
                raise TypeError("request inválida")
            if type(body) is bytes:
                body_size = len(body)
            elif type(body) is SeekableContent:
                body_size = body.byte_size
            else:
                raise TypeError("body inválido")
            if body_size > self.request_body_limit(method, target):
                raise ValueError("body inválido")
            request_headers = _normalized_headers(headers)
            if not _local_host_allowed(request_headers.get("host")):
                return _error(
                    403,
                    "FORBIDDEN_LOCAL_REQUEST",
                    "requisição local não autorizada",
                )
            if "origin" in request_headers or request_headers.get("sec-fetch-site", "none").lower() not in {"none", "same-origin"}:
                return _error(
                    403,
                    "FORBIDDEN_LOCAL_REQUEST",
                    "requisição local não autorizada",
                )
            raw_segments, segments = _target_segments(target)
            normalized_method = method.upper()
            private_route = len(raw_segments) >= 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] in {"materials", "case-analysis", "pericial-planning", "inspection-session", "inspection-photos"}
            if (normalized_method == "POST" or private_route) and not hmac.compare_digest(request_headers.get("x-local-api-token", ""), self._token):
                return _error(
                    403,
                    "FORBIDDEN_LOCAL_REQUEST",
                    "requisição local não autorizada",
                )
            if "transfer-encoding" in request_headers:
                raise ValueError("Transfer-Encoding não suportado")

            if raw_segments == ("v1", "workspaces"):
                if normalized_method == "GET":
                    records = self._services.list_workspaces.execute()
                    return _json_response(200, {"items": [_workspace_dto(item) for item in records]})
                if normalized_method == "POST":
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"name"} or type(dto["name"]) is not str or not dto["name"].strip():
                        raise ValueError("name inválido")
                    record = self._services.create_workspace.execute(dto["name"])
                    return _json_response(201, _workspace_dto(record))
                return _error(405, "METHOD_NOT_ALLOWED")

            if len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "case-analysis":
                workspace_id = self._workspace_id(raw_segments[2])
                if normalized_method == "GET":
                    record, snapshot = self._services.get_case_analysis.execute(workspace_id)
                    if type(snapshot) is not CaseAnalysisSnapshot:
                        raise RepositoryIntegrityError("Case Analysis persisted state is invalid")
                    return _json_response(
                        200,
                        {
                            "revision": record.revision,
                            "updated_at": record.created_at,
                            "snapshot": case_analysis_to_mapping(snapshot),
                        },
                    )
                if normalized_method == "POST":
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"expected_revision", "snapshot"}:
                        raise ValueError("Case Analysis request is invalid")
                    expected = dto["expected_revision"]
                    if expected is not None and (type(expected) is not int or expected < 1):
                        raise ValueError("Case Analysis expected revision is invalid")
                    snapshot = validated_case_analysis_from_mapping(dto["snapshot"])
                    if snapshot.workspace_id != str(workspace_id):
                        raise ValueError("Case Analysis workspace mismatch")
                    record = self._services.save_case_analysis.execute(workspace_id, snapshot, expected)
                    return _json_response(
                        200,
                        {
                            "revision": record.revision,
                            "updated_at": record.created_at,
                            "snapshot": case_analysis_to_mapping(snapshot),
                        },
                    )
                return _error(405, "METHOD_NOT_ALLOWED")

            if len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "pericial-planning":
                workspace_id = self._workspace_id(raw_segments[2])
                if normalized_method == "GET":
                    record, snapshot = self._services.get_pericial_planning.execute(workspace_id)
                    if type(snapshot) is not PlanningSnapshot:
                        raise RepositoryIntegrityError("Pericial Planning persisted state is invalid")
                    return _json_response(
                        200,
                        {
                            "revision": record.revision,
                            "updated_at": record.created_at,
                            "snapshot": pericial_planning_to_mapping(snapshot),
                        },
                    )
                if normalized_method == "PUT":
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"expected_revision", "snapshot"}:
                        raise ValueError("Pericial Planning request is invalid")
                    expected = dto["expected_revision"]
                    if expected is not None and (type(expected) is not int or expected < 1):
                        raise ValueError("Pericial Planning expected revision is invalid")
                    snapshot = validated_pericial_planning_from_mapping(dto["snapshot"])
                    if snapshot.workspace_id != str(workspace_id):
                        raise ValueError("Pericial Planning workspace mismatch")
                    record = self._services.save_pericial_planning.execute(workspace_id, snapshot, expected)
                    return _json_response(
                        200,
                        {
                            "revision": record.revision,
                            "updated_at": record.created_at,
                            "snapshot": pericial_planning_to_mapping(snapshot),
                        },
                    )
                return _error(405, "METHOD_NOT_ALLOWED")

            if len(raw_segments) == 5 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3:] == ("pericial-planning", "decisions"):
                if normalized_method != "POST":
                    return _error(405, "METHOD_NOT_ALLOWED")
                workspace_id = self._workspace_id(raw_segments[2])
                dto = self._request_dto(request_headers, body)
                if set(dto) != {"expected_revision", "target_item_id", "action", "reviewer", "reason", "decided_value"}:
                    raise ValueError("professional planning decision request is invalid")
                record, snapshot = self._services.review_pericial_planning.execute(
                    workspace_id,
                    target_item_id=dto["target_item_id"],
                    action=dto["action"],
                    reviewer=dto["reviewer"],
                    reason=dto["reason"],
                    decided_value=dto["decided_value"],
                    expected_revision=dto["expected_revision"],
                )
                if type(snapshot) is not PlanningSnapshot:
                    raise RepositoryIntegrityError("Pericial Planning reviewed state is invalid")
                return _json_response(
                    200,
                    {"revision": record.revision, "updated_at": record.created_at, "snapshot": pericial_planning_to_mapping(snapshot)},
                )

            if len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "inspection-session":
                workspace_id = self._workspace_id(raw_segments[2])
                if normalized_method == "GET":
                    if self._services.get_inspection_session is None:
                        return _error(503, "INSPECTION_SESSION_UNAVAILABLE")
                    record, snapshot = self._services.get_inspection_session.execute(workspace_id)
                    return _json_response(200, {"revision": record.revision, "updated_at": record.created_at, "snapshot": inspection_session_to_validated_mapping(snapshot)})
                if normalized_method == "PUT":
                    if self._services.save_inspection_session is None:
                        return _error(503, "PRIVATE_STORAGE_UNAVAILABLE", "armazenamento privado indisponível")
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"expected_revision", "snapshot"}:
                        raise ValueError("Inspection Session request is invalid")
                    expected = dto["expected_revision"]
                    if expected is not None and (type(expected) is not int or expected < 1):
                        raise ValueError("Inspection Session expected revision is invalid")
                    snapshot = validated_inspection_session_from_mapping(dto["snapshot"])
                    if snapshot.workspace_id != str(workspace_id):
                        raise ValueError("Inspection Session workspace mismatch")
                    record = self._services.save_inspection_session.execute(workspace_id, snapshot, expected)
                    return _json_response(200, {"revision": record.revision, "updated_at": record.created_at, "snapshot": inspection_session_to_validated_mapping(snapshot)})
                if normalized_method == "POST":
                    if self._services.start_inspection_session is None:
                        return _error(503, "PRIVATE_STORAGE_UNAVAILABLE", "armazenamento privado indisponível")
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"responsible_professional", "location_context", "participant_references"} or type(dto["participant_references"]) is not list:
                        raise ValueError("Inspection Session start request is invalid")
                    record, snapshot = self._services.start_inspection_session.execute(
                        workspace_id,
                        responsible_professional=dto["responsible_professional"],
                        location_context=dto["location_context"],
                        participant_references=tuple(dto["participant_references"]),
                    )
                    return _json_response(201, {"revision": record.revision, "updated_at": record.created_at, "snapshot": inspection_session_to_validated_mapping(snapshot)})
                return _error(405, "METHOD_NOT_ALLOWED")

            if len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "materials":
                workspace_id = self._workspace_id(raw_segments[2])
                if normalized_method == "GET":
                    service = self._services.list_case_documents
                    if service is None:
                        return _error(503, "PRIVATE_STORAGE_UNAVAILABLE", "armazenamento privado indisponível")
                    records = service.execute(workspace_id)
                    return _json_response(
                        200,
                        {"items": [_private_content_dto(item, workspace_id) for item in records]},
                    )
                if normalized_method == "POST":
                    service = self._services.import_case_document
                    if service is None:
                        return _error(503, "PRIVATE_STORAGE_UNAVAILABLE", "armazenamento privado indisponível")
                    content_type = request_headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type != "application/pdf":
                        raise ValueError("Content-Type de documento inválido")
                    if _parse_content_length(request_headers.get("content-length", "")) != body_size:
                        raise ValueError("Content-Length diverge")
                    record = service.execute(
                        workspace_id=workspace_id,
                        original_filename=_document_filename(request_headers.get("x-document-filename")),
                        content=body,
                        media_type="application/pdf",
                    )
                    return _json_response(201, _private_content_dto(record, workspace_id))
                return _error(405, "METHOD_NOT_ALLOWED")

            if len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "inspection-photos":
                if normalized_method != "POST":
                    return _error(405, "METHOD_NOT_ALLOWED")
                service = self._services.import_inspection_photo
                if service is None:
                    return _error(503, "PRIVATE_STORAGE_UNAVAILABLE", "armazenamento privado indisponível")
                workspace_id = self._workspace_id(raw_segments[2])
                media_type = request_headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if _parse_content_length(request_headers.get("content-length", "")) != body_size:
                    raise ValueError("Content-Length diverge")
                filename = _document_filename(request_headers.get("x-document-filename"))
                record = service.execute(workspace_id=workspace_id, original_filename=filename, content=body, media_type=media_type)
                return _json_response(201, _private_content_dto(record, workspace_id))

            if len(raw_segments) == 5 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "materials":
                if normalized_method != "GET":
                    return _error(405, "METHOD_NOT_ALLOWED")
                service = self._services.read_case_document
                if service is None:
                    return _error(503, "PRIVATE_STORAGE_UNAVAILABLE", "armazenamento privado indisponível")
                workspace_id = self._workspace_id(raw_segments[2])
                content_id = PrivateContentId.parse(raw_segments[4])
                record = service.execute(workspace_id, content_id)
                if type(record) is PrivateContent:
                    metadata = record.metadata
                    response_body = record.content
                elif type(record) is OpenPrivateContent:
                    metadata = record.metadata
                    response_body = record
                else:
                    raise RepositoryIntegrityError("identidade documental divergente")
                if metadata.workspace_id != workspace_id or metadata.content_id != content_id or metadata.media_type != "application/pdf":
                    if type(record) is OpenPrivateContent:
                        record.close()
                    raise RepositoryIntegrityError("identidade documental divergente")
                return _binary_response(200, response_body, "application/pdf")

            if len(raw_segments) == 3 and raw_segments[:2] == (
                "v1",
                "workspaces",
            ):
                if normalized_method != "GET":
                    return _error(405, "METHOD_NOT_ALLOWED")
                record = self._services.get_workspace.execute(self._workspace_id(raw_segments[2]))
                return _json_response(200, _workspace_dto(record))

            if len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "process-case":
                workspace_id = self._workspace_id(raw_segments[2])
                if normalized_method == "GET":
                    record = self._services.get_process_case.execute(workspace_id)
                    return _json_response(200, _process_case_dto(record, workspace_id))
                if normalized_method == "POST":
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"expected_revision", "data"}:
                        raise ValueError("data invalida")
                    expected_revision = dto["expected_revision"]
                    if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1 or expected_revision > _MAX_SAFE_JSON_INTEGER):
                        raise ValueError("expected_revision invalida")
                    data = ProcessCaseData.from_mapping(dto["data"])
                    record = self._services.save_process_case.execute(workspace_id, data, expected_revision)
                    return _json_response(200, _process_case_dto(record, workspace_id))
                return _error(405, "METHOD_NOT_ALLOWED")

            if (
                len(raw_segments) == 5
                and raw_segments[:2] == ("v1", "workspaces")
                and raw_segments[3:]
                == (
                    "process-metadata",
                    "source-span-confirmations",
                )
            ):
                if normalized_method != "POST":
                    return _error(405, "METHOD_NOT_ALLOWED")
                service = self._services.confirm_process_metadata_source_span
                if service is None:
                    return _error(
                        503,
                        "PROCESS_METADATA_UNAVAILABLE",
                        "extração local indisponível",
                    )
                workspace_id = self._workspace_id(raw_segments[2])
                dto = self._request_dto(request_headers, body)
                if set(dto) != {
                    "field_name",
                    "evidence_id",
                    "source_start",
                    "source_end",
                    "expected_source_revision",
                    "expected_revision",
                }:
                    raise ValueError("confirmação de fonte inválida")
                record = service.execute(
                    workspace_id=workspace_id,
                    field_name=dto["field_name"],
                    evidence_id=dto["evidence_id"],
                    source_start=dto["source_start"],
                    source_end=dto["source_end"],
                    expected_source_revision=dto["expected_source_revision"],
                    expected_revision=dto["expected_revision"],
                )
                return _json_response(
                    200,
                    _process_case_dto(record, workspace_id),
                )

            if len(raw_segments) == 4 and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "process-metadata":
                if normalized_method != "GET":
                    return _error(405, "METHOD_NOT_ALLOWED")
                service = self._services.get_process_metadata_review
                if service is None:
                    return _error(503, "PROCESS_METADATA_UNAVAILABLE", "extração local indisponível")
                workspace_id = self._workspace_id(raw_segments[2])
                review = service.execute(workspace_id)
                if type(review) is not ProcessMetadataReview or review.workspace_id != workspace_id:
                    raise RepositoryIntegrityError("revisão de metadados processuais divergente")
                return _json_response(200, review_dto(review))

            artifact_route = len(raw_segments) in {7, 8} and raw_segments[:2] == ("v1", "workspaces") and raw_segments[3] == "artifacts" and raw_segments[6] == "revisions"
            if artifact_route:
                if segments[4] in {CASE_ANALYSIS_ARTIFACT_KIND, PERICIAL_PLANNING_ARTIFACT_KIND}:
                    return _error(404, "NOT_FOUND")
                if len(segments) == 7 and normalized_method == "POST":
                    dto = self._request_dto(request_headers, body)
                    if set(dto) != {"payload"}:
                        raise ValueError("payload ausente")
                    record = self._services.append_artifact_revision.execute(
                        workspace_id=self._workspace_id(raw_segments[2]),
                        artifact_kind=segments[4],
                        artifact_id=segments[5],
                        payload=dto["payload"],
                    )
                    return _json_response(201, _revision_dto(record))
                if len(segments) == 7 and normalized_method == "GET":
                    records = self._services.list_artifact_revisions.execute(
                        self._workspace_id(raw_segments[2]),
                        segments[4],
                        segments[5],
                    )
                    return _json_response(200, {"items": [_revision_dto(item) for item in records]})
                if len(segments) == 8 and normalized_method == "GET":
                    workspace_id = self._workspace_id(raw_segments[2])
                    if raw_segments[7] == "latest":
                        record = self._services.get_latest_artifact.execute(workspace_id, segments[4], segments[5])
                    else:
                        revision_text = raw_segments[7]
                        if not revision_text.isascii() or not revision_text.isdecimal():
                            raise ValueError("revision inválida")
                        revision = int(revision_text)
                        if revision < 1 or revision > _MAX_SAFE_JSON_INTEGER or str(revision) != revision_text:
                            raise ValueError("revision inválida")
                        record = self._services.get_artifact_revision.execute(workspace_id, segments[4], segments[5], revision)
                    return _json_response(200, _revision_dto(record))
                return _error(405, "METHOD_NOT_ALLOWED")

            return _error(404, "NOT_FOUND")
        except _JsonSerializationError:
            return _error(
                500,
                "LOCAL_API_SERIALIZATION_FAILURE",
                "resposta local invalida",
            )
        except WorkspaceNotFound:
            return _error(404, "WORKSPACE_NOT_FOUND", "workspace não encontrado")
        except ArtifactRevisionNotFound:
            return _error(
                404,
                "ARTIFACT_REVISION_NOT_FOUND",
                "revisão de artefato não encontrada",
            )
        except PrivateContentNotFound:
            return _error(404, "MATERIAL_NOT_FOUND", "material não encontrado")
        except PrivateContentTooLarge:
            return _error(413, "DOCUMENT_TOO_LARGE", "documento excede o limite permitido")
        except UnsupportedCaseDocument:
            return _error(415, "UNSUPPORTED_DOCUMENT", "somente documentos PDF são aceitos")
        except InvalidCaseDocument:
            return _error(400, "INVALID_DOCUMENT", "documento PDF inválido")
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
            return _error(503, "REPOSITORY_UNAVAILABLE", "persistência local indisponível")
        except (
            json.JSONDecodeError,
            RecursionError,
            UnicodeError,
            TypeError,
            ValueError,
        ):
            return _error(400, "INVALID_REQUEST")
