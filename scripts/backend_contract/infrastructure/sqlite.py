"""Persistência SQLite local, transacional e append-only da Application Layer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import UUID

from ..application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    WorkspaceId,
    canonical_payload_json,
)
from ..application.ports import (
    PersistenceSchemaError,
    RepositoryConflict,
    RepositoryIntegrityError,
    WorkspaceNotFound,
)


CURRENT_SCHEMA_VERSION = 1

_WORKSPACES_SQL = """
CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_REVISIONS_SQL = """
CREATE TABLE artifact_revisions (
    workspace_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    revision_id TEXT PRIMARY KEY NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (workspace_id, artifact_kind, artifact_id, revision),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE RESTRICT
)
"""

MIGRATIONS = {1: (_WORKSPACES_SQL, _REVISIONS_SQL)}

_EXPECTED_COLUMNS = {
    "workspaces": (
        ("workspace_id", "TEXT", 1, None, 1),
        ("name", "TEXT", 1, None, 0),
        ("created_at", "TEXT", 1, None, 0),
    ),
    "artifact_revisions": (
        ("workspace_id", "TEXT", 1, None, 0),
        ("artifact_kind", "TEXT", 1, None, 0),
        ("artifact_id", "TEXT", 1, None, 0),
        ("revision_id", "TEXT", 1, None, 1),
        ("revision", "INTEGER", 1, None, 0),
        ("created_at", "TEXT", 1, None, 0),
        ("checksum_sha256", "TEXT", 1, None, 0),
        ("payload_json", "TEXT", 1, None, 0),
    ),
}


def _normalized_sql(value: str) -> str:
    return " ".join(value.split())


def _validate_schema(connection: sqlite3.Connection) -> None:
    unexpected_objects = tuple(
        connection.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('index', 'view', 'trigger') AND sql IS NOT NULL"
        )
    )
    if unexpected_objects:
        raise PersistenceSchemaError("schema SQLite contém objetos inesperados")
    tables = {
        row[0]: row[1]
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    expected_sql = {
        "workspaces": _normalized_sql(_WORKSPACES_SQL),
        "artifact_revisions": _normalized_sql(_REVISIONS_SQL),
    }
    if set(tables) != set(expected_sql):
        raise PersistenceSchemaError("schema SQLite contém tabelas inesperadas ou ausentes")
    for table, sql in expected_sql.items():
        if _normalized_sql(tables[table]) != sql:
            raise PersistenceSchemaError(f"schema SQLite malformado: {table}")
        columns = tuple(
            (row[1], row[2], row[3], row[4], row[5])
            for row in connection.execute(f"PRAGMA table_info({table})")
        )
        if columns != _EXPECTED_COLUMNS[table]:
            raise PersistenceSchemaError(f"colunas SQLite malformadas: {table}")
    foreign_keys = tuple(connection.execute("PRAGMA foreign_key_list(artifact_revisions)"))
    if len(foreign_keys) != 1 or foreign_keys[0][2:] != (
        "workspaces",
        "workspace_id",
        "workspace_id",
        "NO ACTION",
        "RESTRICT",
        "NONE",
    ):
        raise PersistenceSchemaError("foreign key SQLite malformada")


def migrate(connection: sqlite3.Connection) -> None:
    """Aplica migrações conhecidas numa única transação e valida o schema exato."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if type(version) is not int or version < 0 or version > CURRENT_SCHEMA_VERSION:
        raise PersistenceSchemaError(
            f"versão futura ou inválida do schema SQLite: {version}"
        )
    try:
        connection.execute("BEGIN IMMEDIATE")
        for target in range(version + 1, CURRENT_SCHEMA_VERSION + 1):
            statements = MIGRATIONS.get(target)
            if not statements:
                raise PersistenceSchemaError(f"migração SQLite ausente: {target}")
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {target}")
        _validate_schema(connection)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, PersistenceSchemaError):
            raise
        if isinstance(exc, sqlite3.Error):
            raise PersistenceSchemaError("migração SQLite falhou") from exc
        raise


class _SQLiteRepository:
    def __init__(self, connection: sqlite3.Connection, lock: RLock):
        self._connection = connection
        self._lock = lock

    @contextmanager
    def _write(self):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise


class SQLiteWorkspaceRepository(_SQLiteRepository):
    def create(self, workspace: PericiaWorkspace) -> PericiaWorkspace:
        if type(workspace) is not PericiaWorkspace:
            raise TypeError("workspace inválido")
        try:
            with self._write():
                self._connection.execute(
                    "INSERT INTO workspaces (workspace_id, name, created_at) VALUES (?, ?, ?)",
                    (str(workspace.workspace_id), workspace.name, workspace.created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise RepositoryConflict("workspace já existe") from exc
        return workspace

    def _from_row(self, row: sqlite3.Row) -> PericiaWorkspace:
        try:
            return PericiaWorkspace(
                WorkspaceId.parse(row["workspace_id"]), row["name"], row["created_at"]
            )
        except (TypeError, ValueError) as exc:
            raise RepositoryIntegrityError("workspace persistido inválido") from exc

    def get(self, workspace_id: WorkspaceId) -> PericiaWorkspace | None:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        with self._lock:
            row = self._connection.execute(
                "SELECT workspace_id, name, created_at FROM workspaces WHERE workspace_id = ?",
                (str(workspace_id),),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def list_all(self) -> tuple[PericiaWorkspace, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT workspace_id, name, created_at FROM workspaces "
                "ORDER BY created_at, workspace_id"
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)


class SQLiteArtifactRevisionRepository(_SQLiteRepository):
    def append(
        self,
        *,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision_id: str,
        created_at: str,
        payload: object,
    ) -> ArtifactRevision:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        canonical_json = canonical_payload_json(payload)
        checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        try:
            canonical_revision_id = str(UUID(revision_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("revision_id inválido") from exc
        try:
            with self._write():
                exists = self._connection.execute(
                    "SELECT 1 FROM workspaces WHERE workspace_id = ?",
                    (str(workspace_id),),
                ).fetchone()
                if exists is None:
                    raise WorkspaceNotFound(f"workspace não encontrado: {workspace_id}")
                revision = self._connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) + 1 FROM artifact_revisions "
                    "WHERE workspace_id = ? AND artifact_kind = ? AND artifact_id = ?",
                    (str(workspace_id), artifact_kind, artifact_id),
                ).fetchone()[0]
                record = ArtifactRevision(
                    workspace_id=workspace_id,
                    artifact_kind=artifact_kind,
                    artifact_id=artifact_id,
                    revision_id=canonical_revision_id,
                    revision=revision,
                    created_at=created_at,
                    checksum_sha256=checksum,
                    payload=payload,
                )
                self._connection.execute(
                    "INSERT INTO artifact_revisions "
                    "(workspace_id, artifact_kind, artifact_id, revision_id, revision, "
                    "created_at, checksum_sha256, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(record.workspace_id),
                        record.artifact_kind,
                        record.artifact_id,
                        record.revision_id,
                        record.revision,
                        record.created_at,
                        record.checksum_sha256,
                        canonical_json,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise RepositoryConflict("conflito de identidade de revisão") from exc
        return record

    def _from_row(self, row: sqlite3.Row) -> ArtifactRevision:
        try:
            payload = json.loads(row["payload_json"])
            canonical_json = canonical_payload_json(payload)
            if canonical_json != row["payload_json"]:
                raise RepositoryIntegrityError("payload persistido não é JSON canônico")
            checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            if checksum != row["checksum_sha256"]:
                raise RepositoryIntegrityError("checksum do payload persistido diverge")
            return ArtifactRevision(
                workspace_id=WorkspaceId.parse(row["workspace_id"]),
                artifact_kind=row["artifact_kind"],
                artifact_id=row["artifact_id"],
                revision_id=row["revision_id"],
                revision=row["revision"],
                created_at=row["created_at"],
                checksum_sha256=row["checksum_sha256"],
                payload=payload,
            )
        except RepositoryIntegrityError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RepositoryIntegrityError("revisão persistida inválida") from exc

    def _select_one(self, query: str, parameters: tuple) -> ArtifactRevision | None:
        with self._lock:
            row = self._connection.execute(query, parameters).fetchone()
        return None if row is None else self._from_row(row)

    def latest(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> ArtifactRevision | None:
        return self._select_one(
            "SELECT * FROM artifact_revisions WHERE workspace_id = ? "
            "AND artifact_kind = ? AND artifact_id = ? ORDER BY revision DESC LIMIT 1",
            (str(workspace_id), artifact_kind, artifact_id),
        )

    def get_revision(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision: int,
    ) -> ArtifactRevision | None:
        return self._select_one(
            "SELECT * FROM artifact_revisions WHERE workspace_id = ? "
            "AND artifact_kind = ? AND artifact_id = ? AND revision = ?",
            (str(workspace_id), artifact_kind, artifact_id, revision),
        )

    def list_all(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> tuple[ArtifactRevision, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM artifact_revisions WHERE workspace_id = ? "
                "AND artifact_kind = ? AND artifact_id = ? ORDER BY revision",
                (str(workspace_id), artifact_kind, artifact_id),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)


class SQLiteApplicationStore:
    """Sessão local que expõe separadamente os dois ports de persistência."""

    def __init__(self, database: str | Path, *, timeout: float = 5.0):
        self._connection = sqlite3.connect(
            str(database),
            timeout=timeout,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        try:
            migrate(self._connection)
        except Exception:
            self._connection.close()
            raise
        lock = RLock()
        self.workspaces = SQLiteWorkspaceRepository(self._connection, lock)
        self.revisions = SQLiteArtifactRevisionRepository(self._connection, lock)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteApplicationStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
