"""Versioned workspace portability without rewriting active case storage."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any
from uuid import UUID


PRODUCT_RELEASE_VERSION = "0.11.0"
STORAGE_FORMAT_VERSION = 1
SUPPORTED_BACKUP_VERSIONS = frozenset({0, 1})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
        _text(self.name, "workspace name"); _instant(self.created_at, "workspace created_at")


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
    data = _exact(value, {"schema_version", "format_version", "product_release", "storage_schema_version", "workspace", "artifact_revisions", "private_contents", "member_hashes", "manifest_sha256", "created_at"}, "WorkspaceBackup")
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
