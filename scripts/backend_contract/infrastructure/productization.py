"""Versioned workspace portability without rewriting active case storage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID
from weakref import WeakKeyDictionary

from ..application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    ProcessCaseData,
    WorkspaceId,
    canonical_payload_json,
    thaw_payload,
)
from ..application.ports import RepositoryConflict, RepositoryIntegrityError
from ..application.artifact_ownership import (
    INTERNAL_ARTIFACT_KINDS,
    PORTABLE_PRODUCT_ARTIFACT_KINDS,
    USER_DEFINED_ARTIFACT_KINDS,
)
from ..application.ocr_cache import _page_from_payload
from ..application.process_metadata import document_metadata_from_payload
from ..budget_foundation import budget_snapshot_from_mapping
from ..case_analysis import case_analysis_from_mapping
from ..delivery_foundation import delivery_snapshot_from_mapping
from ..pericial_planning import pericial_planning_from_mapping
from ..report_foundation import expert_profile_from_mapping, report_snapshot_from_mapping
from ..technical_findings import technical_snapshot_from_mapping
from ..vistoria import inspection_session_from_mapping
from .private_filesystem import LocalPrivateContentStore
from .sqlite import SQLiteApplicationStore

import base64


BACKUP_PORTABILITY_RELEASE = "0.11.0"
# Serialized backup compatibility is a portability contract generation, not
# the independently versioned application release.
PRODUCT_RELEASE_VERSION = BACKUP_PORTABILITY_RELEASE
STORAGE_FORMAT_VERSION = 1
SUPPORTED_BACKUP_VERSIONS = frozenset({0, 1})
SUPPORTED_BACKUP_PORTABILITY_RELEASES = frozenset({"0.10.0", "0.11.0"})
SUPPORTED_PRODUCT_RELEASES = SUPPORTED_BACKUP_PORTABILITY_RELEASES
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPEN_BINARY = 0x8000 if os.name == "nt" else 0


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ValueError("backup payload is not canonical JSON") from exc


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: object, expected: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} fields are invalid")
    return dict(value)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value


def _instant(value: object, name: str) -> str:
    result = _text(value, name)
    parsed = datetime.fromisoformat(result)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} requires timezone")
    return result


@dataclass(frozen=True, slots=True)
class BackupWorkspace:
    workspace_id: str
    name: str
    created_at: str

    def __post_init__(self) -> None:
        if str(UUID(self.workspace_id)) != self.workspace_id:
            raise ValueError("workspace_id is invalid")
        _text(self.name, "workspace name")
        _instant(self.created_at, "workspace created_at")


@dataclass(frozen=True, slots=True)
class WorkspaceBackup:
    schema_version: str
    format_version: int
    product_release: str
    storage_schema_version: int
    workspace: BackupWorkspace
    artifact_revisions: tuple[dict[str, Any], ...]
    private_contents: tuple[dict[str, Any], ...]
    member_hashes: dict[str, str]
    manifest_sha256: str
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("backup schema version is unsupported")
        if self.format_version != STORAGE_FORMAT_VERSION:
            raise ValueError("backup format version is unsupported")
        _text(self.product_release, "product release")
        if type(self.storage_schema_version) is not int or self.storage_schema_version < 1:
            raise ValueError("storage schema version is invalid")
        if type(self.workspace) is not BackupWorkspace or type(self.artifact_revisions) is not tuple or type(self.private_contents) is not tuple:
            raise ValueError("backup collections are invalid")
        if type(self.member_hashes) is not dict or any(type(key) is not str or _SHA256.fullmatch(value) is None for key, value in self.member_hashes.items()):
            raise ValueError("backup member hashes are invalid")
        if _SHA256.fullmatch(self.manifest_sha256) is None:
            raise ValueError("backup manifest hash is invalid")
        _instant(self.created_at, "backup created_at")


def migrate_backup_mapping(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("backup version is invalid")
    result = deepcopy(value)
    version = result.get("format_version")
    if type(version) is not int or version not in SUPPORTED_BACKUP_VERSIONS:
        raise ValueError("backup version is unsupported")
    if version == 0:
        result["schema_version"] = "1.0.0"
        result["format_version"] = 1
        result["member_hashes"] = {
            "artifact_revisions": _hash(result.get("artifact_revisions")),
            "private_contents": _hash(result.get("private_contents")),
        }
        result["manifest_sha256"] = _hash({key: item for key, item in result.items() if key != "manifest_sha256"})
    return result


def workspace_backup_from_mapping(value: object) -> WorkspaceBackup:
    data = _exact(
        value,
        {"schema_version", "format_version", "product_release", "storage_schema_version", "workspace", "artifact_revisions", "private_contents", "member_hashes", "manifest_sha256", "created_at"},
        "WorkspaceBackup",
    )
    workspace = _exact(data["workspace"], {"workspace_id", "name", "created_at"}, "BackupWorkspace")
    if type(data["artifact_revisions"]) is not list or type(data["private_contents"]) is not list:
        raise ValueError("backup collections are invalid")
    data["workspace"] = BackupWorkspace(**workspace)
    data["artifact_revisions"] = tuple(deepcopy(data["artifact_revisions"]))
    data["private_contents"] = tuple(deepcopy(data["private_contents"]))
    return WorkspaceBackup(**data)


def workspace_backup_to_mapping(value: WorkspaceBackup) -> dict[str, Any]:
    if type(value) is not WorkspaceBackup:
        raise TypeError("WorkspaceBackup is required")
    result = asdict(value)
    result["artifact_revisions"] = list(result["artifact_revisions"])
    result["private_contents"] = list(result["private_contents"])
    return result


_ARTIFACT_VALIDATORS = {
    "BUDGET_SNAPSHOT_V1": budget_snapshot_from_mapping,
    "CASE_ANALYSIS_SNAPSHOT_V1": case_analysis_from_mapping,
    "DELIVERY_SNAPSHOT_V1": delivery_snapshot_from_mapping,
    "EXPERT_MASTER_PROFILE_V1": expert_profile_from_mapping,
    "INSPECTION_SESSION_V1": inspection_session_from_mapping,
    "PERICIAL_PLANNING_SNAPSHOT_V1": pericial_planning_from_mapping,
    "PROCESS_CASE": ProcessCaseData.from_mapping,
    "REPORT_SNAPSHOT_V1": report_snapshot_from_mapping,
    "TECHNICAL_SNAPSHOT_V1": technical_snapshot_from_mapping,
}
ARTIFACT_COMPATIBILITY = {kind: {"current_version": "1.0.0", "supported_versions": ("1.0.0",), "migration": None, "future_version_policy": "FAIL_CLOSED"} for kind in _ARTIFACT_VALIDATORS}


def _validate_ocr_cache(value: object) -> None:
    if type(value) is not dict:
        raise RepositoryIntegrityError("cache OCR persistido inválido")
    key = tuple(value.get(name) for name in ("document_sha256", "page_number", "engine", "engine_version", "model_version", "config_version"))
    _page_from_payload(value, key)


def _validate_confirmation(value: object) -> None:
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "confirmed_revision", "extraction_fingerprint"}
        or value["schema_version"] != 1
        or type(value["confirmed_revision"]) is not int
        or value["confirmed_revision"] < 1
        or type(value["extraction_fingerprint"]) is not str
        or _SHA256.fullmatch(value["extraction_fingerprint"]) is None
    ):
        raise RepositoryIntegrityError("process metadata confirmation is invalid")


def _validate_source_confirmation(value: object) -> None:
    expected = {
        "schema_version",
        "decision",
        "field_name",
        "process_case_revision",
        "extraction_fingerprint",
        "evidence_id",
        "document_id",
        "document_sha256",
        "source_page",
        "evidence_source_start",
        "selection_start",
        "selection_end",
        "source_start",
        "source_end",
        "selected_value",
    }
    if (
        type(value) is not dict
        or set(value) != expected
        or value["schema_version"] != 1
        or value["decision"] != "HUMAN_CONFIRMED"
        or value["field_name"] not in {"parte_requerente", "parte_requerida"}
    ):
        raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    if any(
        type(value[name]) is not int or value[name] < 0 for name in ("process_case_revision", "source_page", "evidence_source_start", "selection_start", "selection_end", "source_start", "source_end")
    ):
        raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    if value["process_case_revision"] < 1 or value["source_page"] < 1 or value["selection_end"] <= value["selection_start"] or value["source_end"] <= value["source_start"]:
        raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    for name in ("extraction_fingerprint", "evidence_id", "document_sha256"):
        if type(value[name]) is not str or _SHA256.fullmatch(value[name]) is None:
            raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    PrivateContentId.parse(value["document_id"])
    _text(value["selected_value"], "selected_value")


_INTERNAL_ARTIFACT_VALIDATORS = {
    "PROCESS_METADATA_EXTRACTION": document_metadata_from_payload,
    "PROCESS_METADATA_CONFIRMATION": _validate_confirmation,
    "PROCESS_METADATA_SOURCE_CONFIRMATION": _validate_source_confirmation,
    "OCR_PAGE_CACHE_V1": _validate_ocr_cache,
}


def _validate_user_artifact(value: object) -> None:
    canonical_payload_json(value)


_USER_ARTIFACT_VALIDATORS = {kind: _validate_user_artifact for kind in USER_DEFINED_ARTIFACT_KINDS}

if frozenset(_ARTIFACT_VALIDATORS) != PORTABLE_PRODUCT_ARTIFACT_KINDS:
    raise RuntimeError("portable artifact validators diverge from application ownership")
if frozenset(_INTERNAL_ARTIFACT_VALIDATORS) != INTERNAL_ARTIFACT_KINDS:
    raise RuntimeError("internal artifact validators diverge from application ownership")


def _revision_mapping(record: ArtifactRevision) -> dict[str, Any]:
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


def _revision_from_mapping(value: object, workspace_id: str) -> ArtifactRevision:
    data = _exact(value, {"workspace_id", "artifact_kind", "artifact_id", "revision_id", "revision", "created_at", "checksum_sha256", "payload"}, "ArtifactRevision")
    if data["workspace_id"] != workspace_id:
        raise RepositoryIntegrityError("backup revision belongs to another workspace")
    record = ArtifactRevision(
        workspace_id=WorkspaceId.parse(data["workspace_id"]),
        artifact_kind=data["artifact_kind"],
        artifact_id=data["artifact_id"],
        revision_id=data["revision_id"],
        revision=data["revision"],
        created_at=data["created_at"],
        checksum_sha256=data["checksum_sha256"],
        payload=data["payload"],
    )
    canonical = canonical_payload_json(thaw_payload(record.payload))
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != record.checksum_sha256:
        raise RepositoryIntegrityError("backup revision checksum diverges")
    validator = (
        _ARTIFACT_VALIDATORS.get(record.artifact_kind)
        or _INTERNAL_ARTIFACT_VALIDATORS.get(record.artifact_kind)
        or _USER_ARTIFACT_VALIDATORS.get(record.artifact_kind)
    )
    if validator is not None:
        validator(thaw_payload(record.payload))
    else:
        raise RepositoryIntegrityError("backup artifact kind is not portable")
    return record


def _private_mapping(metadata: PrivateContentMetadata, content: bytes) -> dict[str, Any]:
    return {
        "workspace_id": str(metadata.workspace_id),
        "content_id": str(metadata.content_id),
        "original_filename": metadata.original_filename,
        "byte_size": metadata.byte_size,
        "checksum_sha256": metadata.checksum_sha256,
        "media_type": metadata.media_type,
        "imported_at": metadata.imported_at,
        "origin": metadata.origin.value,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _private_from_mapping(value: object, workspace_id: str) -> PrivateContent:
    data = _exact(value, {"workspace_id", "content_id", "original_filename", "byte_size", "checksum_sha256", "media_type", "imported_at", "origin", "content_base64"}, "PrivateContent")
    if data["workspace_id"] != workspace_id:
        raise RepositoryIntegrityError("backup private content belongs to another workspace")
    try:
        content = base64.b64decode(data.pop("content_base64"), validate=True)
        data["workspace_id"] = WorkspaceId.parse(data["workspace_id"])
        data["content_id"] = PrivateContentId.parse(data["content_id"])
        data["origin"] = PrivateContentOrigin(data["origin"])
        return PrivateContent(PrivateContentMetadata(**data), content)
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("backup private content is invalid") from exc


def _manifest_hash(mapping: dict[str, Any]) -> str:
    return _hash({key: value for key, value in mapping.items() if key != "manifest_sha256"})


@dataclass(frozen=True, slots=True)
class VerifyWorkspaceBackup:
    def execute(self, payload: bytes) -> WorkspaceBackup:
        if type(payload) is not bytes:
            raise TypeError("backup requires bytes")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise RepositoryIntegrityError("backup package is invalid") from exc
        migrated = migrate_backup_mapping(raw)
        value = workspace_backup_from_mapping(migrated)
        mapping = workspace_backup_to_mapping(value)
        if mapping["product_release"] not in SUPPORTED_PRODUCT_RELEASES or mapping["storage_schema_version"] != 1:
            raise RepositoryIntegrityError("backup compatibility window is unsupported")
        expected_members = {"artifact_revisions": _hash(mapping["artifact_revisions"]), "private_contents": _hash(mapping["private_contents"])}
        if mapping["member_hashes"] != expected_members or mapping["manifest_sha256"] != _manifest_hash(mapping):
            raise RepositoryIntegrityError("backup package checksum diverges")
        workspace_id = value.workspace.workspace_id
        revisions = tuple(_revision_from_mapping(item, workspace_id) for item in value.artifact_revisions)
        identities: set[str] = set()
        sequences: dict[tuple[str, str], list[int]] = {}
        for record in revisions:
            if record.revision_id in identities:
                raise RepositoryIntegrityError("backup revision identity is duplicated")
            identities.add(record.revision_id)
            sequences.setdefault((record.artifact_kind, record.artifact_id), []).append(record.revision)
        if any(items != list(range(1, len(items) + 1)) for items in sequences.values()):
            raise RepositoryIntegrityError("backup revision sequence is incomplete")
        private_contents = tuple(_private_from_mapping(item, workspace_id) for item in value.private_contents)
        private_ids = [item["content_id"] for item in value.private_contents]
        if len(private_ids) != len(set(private_ids)):
            raise RepositoryIntegrityError("backup private identity is duplicated")
        private_authority = {
            str(item.metadata.content_id): item.metadata.checksum_sha256
            for item in private_contents
        }
        for record in revisions:
            if record.artifact_kind != "INSPECTION_SESSION_V1":
                continue
            inspection = inspection_session_from_mapping(thaw_payload(record.payload))
            media = (*inspection.photos, *inspection.videos, *inspection.sketches)
            if any(
                private_authority.get(item.private_content_id) != item.original_sha256
                for item in media
            ):
                raise RepositoryIntegrityError("backup inspection media authority is incomplete")
        return value


@dataclass(frozen=True, slots=True)
class CreateWorkspaceBackup:
    workspaces: object
    revisions: object
    private_contents: object | None
    clock: object
    assert_backup_ready: object | None = None

    def execute(self, workspace_id: WorkspaceId) -> bytes:
        if self.assert_backup_ready is not None:
            self.assert_backup_ready(workspace_id)
        workspace = self.workspaces.get(workspace_id)
        if workspace is None:
            raise ValueError("workspace is unavailable")
        revision_items = [_revision_mapping(item) for item in self.revisions.list_workspace(workspace_id)]
        private_items = []
        if self.private_contents is not None:
            for metadata in self.private_contents.list_all(workspace_id):
                with self.private_contents.open_content(workspace_id, metadata.content_id) as opened:
                    content = opened.stream.read()
                private_items.append(_private_mapping(metadata, content))
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("backup clock requires timezone")
        mapping = {
            "schema_version": "1.0.0",
            "format_version": 1,
            "product_release": PRODUCT_RELEASE_VERSION,
            "storage_schema_version": 1,
            "workspace": {"workspace_id": str(workspace.workspace_id), "name": workspace.name, "created_at": workspace.created_at},
            "artifact_revisions": revision_items,
            "private_contents": private_items,
            "member_hashes": {"artifact_revisions": _hash(revision_items), "private_contents": _hash(private_items)},
            "manifest_sha256": "0" * 64,
            "created_at": now.isoformat(),
        }
        mapping["manifest_sha256"] = _manifest_hash(mapping)
        payload = _canonical(mapping)
        VerifyWorkspaceBackup().execute(payload)
        return payload


@dataclass(frozen=True, slots=True)
class RestoreReceipt:
    workspace_id: str
    backup_sha256: str
    artifact_revisions: int
    private_contents: int
    product_release: str
    storage_schema_version: int


_AUTHORIZED_RECOVERY_STAGING: WeakKeyDictionary["RecoveryStaging", tuple[Path, SQLiteApplicationStore, LocalPrivateContentStore, os.stat_result]] = WeakKeyDictionary()


class RecoveryStaging:
    """Owns a new disposable storage root until external promotion."""

    __slots__ = ("_root", "_database", "_private_contents", "_identity", "_closed", "_discarded", "__weakref__")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("recovery staging must be created by RecoveryStaging.create")

    @classmethod
    def create(cls, root: str | Path) -> "RecoveryStaging":
        if not isinstance(root, (str, Path)):
            raise TypeError("recovery staging root is invalid")
        raw = str(root)
        if not raw.strip() or "\x00" in raw or raw.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
            raise RepositoryIntegrityError("recovery staging root must be local")
        target = Path(root)
        if not target.is_absolute():
            raise RepositoryIntegrityError("recovery staging root must be absolute")
        parent = target.parent.resolve(strict=True)
        if parent != target.parent.absolute():
            raise RepositoryIntegrityError("recovery staging parent must not redirect")
        if target.exists() or target.is_symlink():
            raise RepositoryConflict("recovery staging root must not exist")
        os.mkdir(target, 0o700)
        marker_fd = os.open(target / "RECOVERY_NOT_PROMOTABLE", os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_BINARY, 0o600)
        try:
            remaining = memoryview(b"RECOVERY_STAGING_V1\n")
            while remaining:
                written = os.write(marker_fd, remaining)
                if written <= 0:
                    raise RepositoryIntegrityError("recovery quarantine marker write failed")
                remaining = remaining[written:]
            os.fsync(marker_fd)
        finally:
            os.close(marker_fd)
        marker = target / "RECOVERY_NOT_PROMOTABLE"
        if marker.read_bytes() != b"RECOVERY_STAGING_V1\n":
            raise RepositoryIntegrityError("recovery quarantine marker is incomplete")
        if os.name == "posix":
            directory_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        identity = os.lstat(target)
        database = None
        private = None
        try:
            database = SQLiteApplicationStore(target / "workspace.sqlite3")
            database.mark_recovery_quarantine()
            private = LocalPrivateContentStore.open_or_provision(target / "private")
            private.mark_recovery_quarantine()
            staging = object.__new__(cls)
            staging._root = target.resolve(strict=True)
            staging._database = database
            staging._private_contents = private
            staging._identity = identity
            staging._closed = False
            staging._discarded = False
            _AUTHORIZED_RECOVERY_STAGING[staging] = (staging._root, database, private, identity)
            return staging
        except BaseException:
            if private is not None:
                private.close()
            if database is not None:
                database.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        authority = _AUTHORIZED_RECOVERY_STAGING.pop(self, None)
        database = authority[1] if authority is not None else self._database
        private_contents = authority[2] if authority is not None else self._private_contents
        try:
            private_contents.close()
        finally:
            database.close()

    def discard(self) -> None:
        if self._discarded:
            return
        self._discarded = True
        self.close()

    @property
    def discarded(self) -> bool:
        return self._discarded

    @property
    def root(self) -> Path:
        return self._root

    @property
    def database(self) -> SQLiteApplicationStore:
        return self._database

    @property
    def workspaces(self):
        return self._database.workspaces

    @property
    def revisions(self):
        return self._database.revisions

    @property
    def private_contents(self) -> LocalPrivateContentStore:
        return self._private_contents


@dataclass(frozen=True, slots=True)
class RestoreWorkspaceBackup:
    staging: RecoveryStaging

    def execute(self, payload: bytes) -> RestoreReceipt:
        authority = _AUTHORIZED_RECOVERY_STAGING.get(self.staging) if type(self.staging) is RecoveryStaging else None
        if authority is None or self.staging._closed:
            raise TypeError("restore requires first-party recovery staging")
        _root, database, private_contents, _identity = authority
        workspaces = database.workspaces
        revisions = database.revisions
        try:
            backup = VerifyWorkspaceBackup().execute(payload)
            workspace_id = WorkspaceId.parse(backup.workspace.workspace_id)
            if workspaces.list_all() != ():
                raise RepositoryConflict("restore staging workspace is not empty")
            revision_records = tuple(_revision_from_mapping(item, backup.workspace.workspace_id) for item in backup.artifact_revisions)
            private_records = tuple(_private_from_mapping(item, backup.workspace.workspace_id) for item in backup.private_contents)
            workspaces.create(PericiaWorkspace(workspace_id, backup.workspace.name, backup.workspace.created_at))
            for record in revision_records:
                revisions.append(
                    workspace_id=workspace_id,
                    artifact_kind=record.artifact_kind,
                    artifact_id=record.artifact_id,
                    revision_id=record.revision_id,
                    created_at=record.created_at,
                    payload=thaw_payload(record.payload),
                )
            for item in private_records:
                private_contents.store(item.metadata, item.content)
            reopened = revisions.list_workspace(workspace_id)
            if tuple(_revision_mapping(item) for item in reopened) != backup.artifact_revisions:
                raise RepositoryIntegrityError("restored workspace failed canonical reopen")
            for item in private_records:
                with private_contents.open_content(workspace_id, item.metadata.content_id) as opened:
                    if opened.stream.read() != item.content:
                        raise RepositoryIntegrityError("restored private content diverges")
            return RestoreReceipt(str(workspace_id), hashlib.sha256(payload).hexdigest(), len(revision_records), len(private_records), backup.product_release, backup.storage_schema_version)
        except BaseException:
            self.staging.discard()
            raise


@dataclass(frozen=True, slots=True)
class SupportDiagnostic:
    product_release: str
    storage_schema_version: int
    supported_backup_versions: tuple[int, ...]
    integrity_status: str
    artifact_revision_count: int
    private_content_count: int
    error_code: str | None
    private_egress: bool = False


def collect_support_diagnostics(payload: bytes) -> SupportDiagnostic:
    try:
        value = VerifyWorkspaceBackup().execute(payload)
        return SupportDiagnostic(
            PRODUCT_RELEASE_VERSION, value.storage_schema_version, tuple(sorted(SUPPORTED_BACKUP_VERSIONS)), "PASS", len(value.artifact_revisions), len(value.private_contents), None
        )
    except (RepositoryIntegrityError, TypeError, ValueError):
        return SupportDiagnostic(PRODUCT_RELEASE_VERSION, 1, tuple(sorted(SUPPORTED_BACKUP_VERSIONS)), "FAIL", 0, 0, "BACKUP_INTEGRITY_INVALID")
