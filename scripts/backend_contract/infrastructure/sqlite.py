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
    RepositoryError,
    RepositoryIntegrityError,
    WorkspaceNotFound,
)


CURRENT_SCHEMA_VERSION = 1

_WORKSPACES_SQL = """
CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY NOT NULL CHECK (
        typeof(workspace_id) = 'text'
        AND length(workspace_id) = 36
        AND workspace_id = lower(workspace_id)
        AND substr(workspace_id, 9, 1) = '-'
        AND substr(workspace_id, 14, 1) = '-'
        AND substr(workspace_id, 19, 1) = '-'
        AND substr(workspace_id, 24, 1) = '-'
        AND length(replace(workspace_id, '-', '')) = 32
        AND workspace_id NOT GLOB '*[^0-9a-f-]*'
    ),
    name TEXT NOT NULL CHECK (typeof(name) = 'text' AND length(trim(name)) > 0),
    created_at TEXT NOT NULL CHECK (typeof(created_at) = 'text')
)
"""

_REVISIONS_SQL = """
CREATE TABLE artifact_revisions (
    workspace_id TEXT NOT NULL CHECK (typeof(workspace_id) = 'text'),
    artifact_kind TEXT NOT NULL CHECK (
        typeof(artifact_kind) = 'text' AND length(trim(artifact_kind)) > 0
    ),
    artifact_id TEXT NOT NULL CHECK (
        typeof(artifact_id) = 'text' AND length(trim(artifact_id)) > 0
    ),
    revision_id TEXT PRIMARY KEY NOT NULL CHECK (
        typeof(revision_id) = 'text'
        AND length(revision_id) = 36
        AND revision_id = lower(revision_id)
        AND substr(revision_id, 9, 1) = '-'
        AND substr(revision_id, 14, 1) = '-'
        AND substr(revision_id, 19, 1) = '-'
        AND substr(revision_id, 24, 1) = '-'
        AND length(replace(revision_id, '-', '')) = 32
        AND revision_id NOT GLOB '*[^0-9a-f-]*'
    ),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL CHECK (typeof(created_at) = 'text'),
    checksum_sha256 TEXT NOT NULL CHECK (typeof(checksum_sha256) = 'text'),
    payload_json TEXT NOT NULL CHECK (typeof(payload_json) = 'text'),
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


def _canonical_uuid(raw_value, field: str) -> str:
    try:
        canonical = str(UUID(raw_value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RepositoryIntegrityError(f"identidade UUID persistida inválida: {field}") from exc
    if canonical != raw_value:
        raise RepositoryIntegrityError(f"identidade UUID persistida não canônica: {field}")
    return canonical


def _workspace_from_values(workspace_id, name, created_at) -> PericiaWorkspace:
    try:
        canonical_id = _canonical_uuid(workspace_id, "workspace_id")
        return PericiaWorkspace(WorkspaceId.parse(canonical_id), name, created_at)
    except RepositoryIntegrityError:
        raise
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("workspace persistido inválido") from exc


def _revision_from_values(
    workspace_id,
    artifact_kind,
    artifact_id,
    revision_id,
    revision,
    created_at,
    checksum_sha256,
    payload_json,
) -> ArtifactRevision:
    try:
        canonical_workspace_id = _canonical_uuid(workspace_id, "workspace_id")
        canonical_revision_id = _canonical_uuid(revision_id, "revision_id")
        if type(payload_json) is not str:
            raise TypeError("payload_json persistido não é texto")
        payload = json.loads(payload_json)
        canonical_json = canonical_payload_json(payload)
        if canonical_json != payload_json:
            raise RepositoryIntegrityError("payload persistido não é JSON canônico")
        checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        if checksum != checksum_sha256:
            raise RepositoryIntegrityError("checksum do payload persistido diverge")
        return ArtifactRevision(
            workspace_id=WorkspaceId.parse(canonical_workspace_id),
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            revision_id=canonical_revision_id,
            revision=revision,
            created_at=created_at,
            checksum_sha256=checksum_sha256,
            payload=payload,
        )
    except RepositoryIntegrityError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("revisão persistida inválida") from exc


def _validate_persisted_records(connection: sqlite3.Connection) -> None:
    workspace_ids = set()
    revision_sequences: dict[tuple[str, str, str], list[int]] = {}
    for values in connection.execute(
        "SELECT workspace_id, name, created_at FROM workspaces"
    ):
        record = _workspace_from_values(*values)
        workspace_ids.add(str(record.workspace_id))
    for values in connection.execute(
        "SELECT workspace_id, artifact_kind, artifact_id, revision_id, revision, "
        "created_at, checksum_sha256, payload_json FROM artifact_revisions"
    ):
        record = _revision_from_values(*values)
        if str(record.workspace_id) not in workspace_ids:
            raise RepositoryIntegrityError("revisão persistida referencia workspace ausente")
        key = (str(record.workspace_id), record.artifact_kind, record.artifact_id)
        revision_sequences.setdefault(key, []).append(record.revision)
    for revisions in revision_sequences.values():
        if sorted(revisions) != list(range(1, len(revisions) + 1)):
            raise RepositoryIntegrityError("histórico persistido possui sequência incompleta")


def _validate_database_state(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if type(version) is not int or version != CURRENT_SCHEMA_VERSION:
        raise PersistenceSchemaError(f"versão inesperada do schema SQLite: {version}")
    _validate_schema(connection)
    _validate_persisted_records(connection)


def _database_state_token(connection: sqlite3.Connection) -> tuple[int, int, int, int]:
    return (
        connection.execute("PRAGMA data_version").fetchone()[0],
        connection.execute("PRAGMA schema_version").fetchone()[0],
        connection.execute("PRAGMA user_version").fetchone()[0],
        connection.total_changes,
    )


class _DatabaseStateGuard:
    def __init__(
        self,
        connection: sqlite3.Connection,
        trusted_token: tuple[int, int, int, int],
    ):
        self._connection = connection
        self._trusted_token = trusted_token

    def validate(self) -> None:
        current = _database_state_token(self._connection)
        if current != self._trusted_token:
            _validate_database_state(self._connection)
            validated = _database_state_token(self._connection)
            if validated != current:
                raise RepositoryIntegrityError(
                    "estado SQLite mudou durante a validação"
                )
            self._trusted_token = validated

    def accept_current(self) -> None:
        self._trusted_token = _database_state_token(self._connection)


def migrate(connection: sqlite3.Connection) -> tuple[int, int, int, int]:
    """Aplica migrações conhecidas numa única transação e valida o schema exato."""
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if type(version) is not int or version < 0 or version > CURRENT_SCHEMA_VERSION:
            raise PersistenceSchemaError(
                f"versão futura ou inválida do schema SQLite: {version}"
            )
        for target in range(version + 1, CURRENT_SCHEMA_VERSION + 1):
            statements = MIGRATIONS.get(target)
            if not statements:
                raise PersistenceSchemaError(f"migração SQLite ausente: {target}")
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {target}")
        _validate_database_state(connection)
        trusted_token = _database_state_token(connection)
        connection.commit()
        return trusted_token
    except Exception as exc:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        if isinstance(exc, PersistenceSchemaError):
            raise
        if isinstance(exc, sqlite3.Error):
            error_code = getattr(exc, "sqlite_errorcode", 0) or 0
            if (error_code & 0xFF) in {
                sqlite3.SQLITE_ABORT,
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_CANTOPEN,
                sqlite3.SQLITE_FULL,
                sqlite3.SQLITE_INTERRUPT,
                sqlite3.SQLITE_IOERR,
                sqlite3.SQLITE_LOCKED,
                sqlite3.SQLITE_NOMEM,
                sqlite3.SQLITE_READONLY,
            }:
                raise RepositoryError("falha operacional durante migração SQLite") from exc
            raise PersistenceSchemaError("migração SQLite falhou") from exc
        raise


class _SQLiteRepository:
    def __init__(
        self,
        connection: sqlite3.Connection,
        lock: RLock,
        state_guard: _DatabaseStateGuard,
    ):
        self._connection = connection
        self._lock = lock
        self._state_guard = state_guard

    @contextmanager
    def _write(self):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._state_guard.validate()
                yield
                self._state_guard.accept_current()
                self._connection.commit()
            except Exception:
                try:
                    self._connection.rollback()
                except sqlite3.Error:
                    pass
                raise

    @contextmanager
    def _read(self):
        with self._lock:
            try:
                self._connection.execute("BEGIN")
                self._state_guard.validate()
                yield
                self._connection.commit()
            except Exception:
                try:
                    self._connection.rollback()
                except sqlite3.Error:
                    pass
                raise

    def _fetchone(self, query: str, parameters: tuple = ()) -> sqlite3.Row | None:
        try:
            with self._read():
                return self._connection.execute(query, parameters).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError("falha SQLite de leitura") from exc

    def _fetchall(self, query: str, parameters: tuple = ()) -> tuple[sqlite3.Row, ...]:
        try:
            with self._read():
                return tuple(self._connection.execute(query, parameters).fetchall())
        except sqlite3.Error as exc:
            raise RepositoryError("falha SQLite de leitura") from exc


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
        except sqlite3.Error as exc:
            raise RepositoryError("falha SQLite ao criar workspace") from exc
        return workspace

    def _from_row(self, row: sqlite3.Row) -> PericiaWorkspace:
        return _workspace_from_values(
            row["workspace_id"], row["name"], row["created_at"]
        )

    def get(self, workspace_id: WorkspaceId) -> PericiaWorkspace | None:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        row = self._fetchone(
            "SELECT workspace_id, name, created_at FROM workspaces WHERE workspace_id = ?",
            (str(workspace_id),),
        )
        return None if row is None else self._from_row(row)

    def list_all(self) -> tuple[PericiaWorkspace, ...]:
        rows = self._fetchall(
            "SELECT workspace_id, name, created_at FROM workspaces "
            "ORDER BY created_at, workspace_id"
        )
        return tuple(self._from_row(row) for row in rows)


_NO_REVISION_PRECONDITION = object()


class SQLiteArtifactRevisionRepository(_SQLiteRepository):
    _PENDING_KEYS = {
        "artifact_kind",
        "artifact_id",
        "revision_id",
        "created_at",
        "payload",
    }
    _EXPECTATION_KEYS = {
        "artifact_kind",
        "artifact_id",
        "revision",
        "checksum_sha256",
    }
    @staticmethod
    def _text_key(value, field: str) -> str:
        if type(value) is not str or not value.strip():
            raise ValueError(f"{field} inválido")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError(f"{field} contém Unicode inválido") from exc
        return value

    @staticmethod
    def _key(
        workspace_id: WorkspaceId, artifact_kind: str, artifact_id: str
    ) -> tuple[str, str, str]:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        return (
            str(workspace_id),
            SQLiteArtifactRevisionRepository._text_key(
                artifact_kind, "artifact_kind"
            ),
            SQLiteArtifactRevisionRepository._text_key(artifact_id, "artifact_id"),
        )

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
        return self._append(
            workspace_id=workspace_id,
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            revision_id=revision_id,
            created_at=created_at,
            payload=payload,
            expected_revision=_NO_REVISION_PRECONDITION,
            expected_dependencies=(),
        )

    def append_if_latest(
        self,
        *,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision_id: str,
        created_at: str,
        payload: object,
        expected_revision: int | None,
        expected_dependencies: tuple[dict[str, object], ...] = (),
    ) -> ArtifactRevision:
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("expected_revision inválida")
        return self._append(
            workspace_id=workspace_id,
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            revision_id=revision_id,
            created_at=created_at,
            payload=payload,
            expected_revision=expected_revision,
            expected_dependencies=expected_dependencies,
        )

    def append_pair_if_latest(
        self,
        *,
        workspace_id: WorkspaceId,
        first: dict[str, object],
        second: dict[str, object],
        expected_first_revision: int | None,
        expected_latest: tuple[dict[str, object], ...],
    ) -> tuple[ArtifactRevision, ArtifactRevision]:
        if expected_first_revision is not None and (
            type(expected_first_revision) is not int or expected_first_revision < 1
        ):
            raise ValueError("expected_revision inválida")
        if (
            type(first) is not dict
            or set(first) != self._PENDING_KEYS
            or type(second) is not dict
            or set(second) != self._PENDING_KEYS
            or type(expected_latest) is not tuple
        ):
            raise ValueError("par de revisões inválido")

        workspace_key = str(workspace_id) if type(workspace_id) is WorkspaceId else None
        if workspace_key is None:
            raise TypeError("workspace_id inválido")

        def prepared(values: dict[str, object], revision: int):
            _, artifact_kind, artifact_id = self._key(
                workspace_id,
                values["artifact_kind"],
                values["artifact_id"],
            )
            canonical_json = canonical_payload_json(values["payload"])
            payload_snapshot = json.loads(canonical_json)
            checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
            try:
                revision_id = str(UUID(values["revision_id"]))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("revision_id inválido") from exc
            created_at = values["created_at"]
            if type(created_at) is not str or not created_at.strip():
                raise ValueError("created_at inválido")
            record = ArtifactRevision(
                workspace_id=workspace_id,
                artifact_kind=artifact_kind,
                artifact_id=artifact_id,
                revision_id=revision_id,
                revision=revision,
                created_at=created_at,
                checksum_sha256=checksum,
                payload=payload_snapshot,
            )
            return record, canonical_json

        normalized_expectations = []
        expected_identities_by_kind = {}
        for expectation in expected_latest:
            if type(expectation) is not dict or set(expectation) != self._EXPECTATION_KEYS:
                raise ValueError("precondição de fonte inválida")
            _, kind, artifact_id = self._key(
                workspace_id,
                expectation["artifact_kind"],
                expectation["artifact_id"],
            )
            revision = expectation["revision"]
            checksum = expectation["checksum_sha256"]
            if revision is None:
                if checksum is not None:
                    raise ValueError("precondição ausente possui checksum")
            elif (
                type(revision) is not int
                or revision < 1
                or type(checksum) is not str
                or len(checksum) != 64
                or any(character not in "0123456789abcdef" for character in checksum)
            ):
                raise ValueError("precondição de fonte inválida")
            normalized_expectations.append((kind, artifact_id, revision, checksum))
            identities = expected_identities_by_kind.setdefault(kind, {})
            if artifact_id in identities:
                raise ValueError("precondição de fonte duplicada")
            identities[artifact_id] = (
                None if revision is None else (revision, checksum)
            )

        try:
            with self._write():
                exists = self._connection.execute(
                    "SELECT 1 FROM workspaces WHERE workspace_id = ?",
                    (workspace_key,),
                ).fetchone()
                if exists is None:
                    raise WorkspaceNotFound(f"workspace não encontrado: {workspace_id}")
                for kind, artifact_id, revision, checksum in normalized_expectations:
                    current = self._connection.execute(
                        "SELECT revision, checksum_sha256 FROM artifact_revisions "
                        "WHERE workspace_id = ? AND artifact_kind = ? AND artifact_id = ? "
                        "ORDER BY revision DESC LIMIT 1",
                        (workspace_key, kind, artifact_id),
                    ).fetchone()
                    actual = None if current is None else (current[0], current[1])
                    expected = None if revision is None else (revision, checksum)
                    if actual != expected:
                        raise RepositoryConflict("fonte de metadados foi atualizada")
                for kind, expected_identities in expected_identities_by_kind.items():
                    current_rows = self._connection.execute(
                        "SELECT current.artifact_id, current.revision, "
                        "current.checksum_sha256 FROM artifact_revisions AS current "
                        "WHERE current.workspace_id = ? AND current.artifact_kind = ? "
                        "AND current.revision = ("
                        "SELECT MAX(candidate.revision) FROM artifact_revisions AS candidate "
                        "WHERE candidate.workspace_id = current.workspace_id "
                        "AND candidate.artifact_kind = current.artifact_kind "
                        "AND candidate.artifact_id = current.artifact_id)",
                        (workspace_key, kind),
                    ).fetchall()
                    current_identities = {
                        row[0]: (row[1], row[2]) for row in current_rows
                    }
                    expected_present = {
                        artifact_id: identity
                        for artifact_id, identity in expected_identities.items()
                        if identity is not None
                    }
                    if current_identities != expected_present:
                        raise RepositoryConflict("conjunto de fontes foi atualizado")

                first_key = self._key(
                    workspace_id, first["artifact_kind"], first["artifact_id"]
                )
                second_key = self._key(
                    workspace_id, second["artifact_kind"], second["artifact_id"]
                )
                if first_key == second_key:
                    raise ValueError("par de revisões exige artefatos distintos")
                first_current = self._connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM artifact_revisions "
                    "WHERE workspace_id = ? AND artifact_kind = ? AND artifact_id = ?",
                    first_key,
                ).fetchone()[0]
                expected_current = (
                    0 if expected_first_revision is None else expected_first_revision
                )
                if first_current != expected_current:
                    raise RepositoryConflict("revisão processual desatualizada")
                second_current = self._connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM artifact_revisions "
                    "WHERE workspace_id = ? AND artifact_kind = ? AND artifact_id = ?",
                    second_key,
                ).fetchone()[0]
                records = (
                    prepared(first, first_current + 1),
                    prepared(second, second_current + 1),
                )
                for record, canonical_json in records:
                    self._connection.execute(
                        "INSERT INTO artifact_revisions "
                        "(workspace_id, artifact_kind, artifact_id, revision_id, revision, "
                        "created_at, checksum_sha256, payload_json) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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
        except sqlite3.Error as exc:
            raise RepositoryError("falha SQLite ao anexar revisões atômicas") from exc
        return records[0][0], records[1][0]

    def _append(
        self,
        *,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision_id: str,
        created_at: str,
        payload: object,
        expected_revision: object,
        expected_dependencies: tuple[dict[str, object], ...],
    ) -> ArtifactRevision:
        workspace_key, artifact_kind, artifact_id = self._key(
            workspace_id, artifact_kind, artifact_id
        )
        canonical_json = canonical_payload_json(payload)
        payload_snapshot = json.loads(canonical_json)
        checksum = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        normalized_dependencies = []
        if type(expected_dependencies) is not tuple:
            raise ValueError("invalid dependent preconditions")
        for expectation in expected_dependencies:
            if type(expectation) is not dict or set(expectation) != self._EXPECTATION_KEYS:
                raise ValueError("invalid dependent precondition")
            _, dependency_kind, dependency_id = self._key(
                workspace_id, expectation["artifact_kind"], expectation["artifact_id"]
            )
            dependency_revision = expectation["revision"]
            dependency_checksum = expectation["checksum_sha256"]
            if (
                type(dependency_revision) is not int
                or dependency_revision < 1
                or type(dependency_checksum) is not str
                or len(dependency_checksum) != 64
                or any(character not in "0123456789abcdef" for character in dependency_checksum)
            ):
                raise ValueError("invalid dependent precondition")
            normalized_dependencies.append(
                (dependency_kind, dependency_id, dependency_revision, dependency_checksum)
            )
        try:
            canonical_revision_id = str(UUID(revision_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("revision_id inválido") from exc
        try:
            with self._write():
                exists = self._connection.execute(
                    "SELECT 1 FROM workspaces WHERE workspace_id = ?",
                    (workspace_key,),
                ).fetchone()
                if exists is None:
                    raise WorkspaceNotFound(f"workspace não encontrado: {workspace_id}")
                for dependency_kind, dependency_id, dependency_revision, dependency_checksum in normalized_dependencies:
                    current_dependency = self._connection.execute(
                        "SELECT revision, checksum_sha256 FROM artifact_revisions "
                        "WHERE workspace_id = ? AND artifact_kind = ? AND artifact_id = ? "
                        "ORDER BY revision DESC LIMIT 1",
                        (workspace_key, dependency_kind, dependency_id),
                    ).fetchone()
                    if current_dependency is None or tuple(current_dependency) != (
                        dependency_revision,
                        dependency_checksum,
                    ):
                        raise RepositoryConflict("dependent artifact was updated")
                current_revision = self._connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM artifact_revisions "
                    "WHERE workspace_id = ? AND artifact_kind = ? AND artifact_id = ?",
                    (workspace_key, artifact_kind, artifact_id),
                ).fetchone()[0]
                if expected_revision is not _NO_REVISION_PRECONDITION:
                    expected_current = 0 if expected_revision is None else expected_revision
                    if current_revision != expected_current:
                        raise RepositoryConflict("revisão processual desatualizada")
                revision = current_revision + 1
                record = ArtifactRevision(
                    workspace_id=workspace_id,
                    artifact_kind=artifact_kind,
                    artifact_id=artifact_id,
                    revision_id=canonical_revision_id,
                    revision=revision,
                    created_at=created_at,
                    checksum_sha256=checksum,
                    payload=payload_snapshot,
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
        except sqlite3.Error as exc:
            raise RepositoryError("falha SQLite ao anexar revisão") from exc
        return record

    def _from_row(self, row: sqlite3.Row) -> ArtifactRevision:
        return _revision_from_values(
            row["workspace_id"],
            row["artifact_kind"],
            row["artifact_id"],
            row["revision_id"],
            row["revision"],
            row["created_at"],
            row["checksum_sha256"],
            row["payload_json"],
        )

    def _select_one(self, query: str, parameters: tuple) -> ArtifactRevision | None:
        row = self._fetchone(query, parameters)
        return None if row is None else self._from_row(row)

    def latest(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> ArtifactRevision | None:
        key = self._key(workspace_id, artifact_kind, artifact_id)
        return self._select_one(
            "SELECT * FROM artifact_revisions WHERE workspace_id = ? "
            "AND artifact_kind = ? AND artifact_id = ? ORDER BY revision DESC LIMIT 1",
            key,
        )

    def get_revision(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision: int,
    ) -> ArtifactRevision | None:
        key = self._key(workspace_id, artifact_kind, artifact_id)
        if type(revision) is not int or revision < 1:
            raise ValueError("revision inválida")
        return self._select_one(
            "SELECT * FROM artifact_revisions WHERE workspace_id = ? "
            "AND artifact_kind = ? AND artifact_id = ? AND revision = ?",
            (*key, revision),
        )

    def list_all(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> tuple[ArtifactRevision, ...]:
        key = self._key(workspace_id, artifact_kind, artifact_id)
        rows = self._fetchall(
            "SELECT * FROM artifact_revisions WHERE workspace_id = ? "
            "AND artifact_kind = ? AND artifact_id = ? ORDER BY revision",
            key,
        )
        return tuple(self._from_row(row) for row in rows)


class SQLiteApplicationStore:
    """Sessão local que expõe separadamente os dois ports de persistência."""

    def __init__(self, database: str | Path, *, timeout: float = 5.0):
        if not isinstance(database, (str, Path)):
            raise RepositoryError("target SQLite inválido")
        target = str(database)
        reserved = {
            "CON",
            "CONIN$",
            "CONOUT$",
            "PRN",
            "AUX",
            "NUL",
            "CLOCK$",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        windows_target = target.replace("/", "\\")
        has_drive_prefix = len(windows_target) >= 2 and windows_target[1] == ":"
        has_absolute_drive = (
            has_drive_prefix
            and windows_target[0].isalpha()
            and len(windows_target) >= 3
            and windows_target[2] == "\\"
        )
        without_drive = windows_target[2:] if has_drive_prefix else windows_target
        target_parts = tuple(part for part in windows_target.split("\\") if part)
        try:
            target.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise RepositoryError("target SQLite contém Unicode inválido") from exc
        ambiguous_part = any(part != part.rstrip(" .") for part in target_parts)
        superscript_digits = str.maketrans({"¹": "1", "²": "2", "³": "3"})
        reserved_part = any(
            part.split(":", 1)[0]
            .split(".", 1)[0]
            .rstrip(" .")
            .translate(superscript_digits)
            .upper()
            in reserved
            for part in target_parts
        )
        if (
            not target.strip()
            or target == ":memory:"
            or target.lower().startswith("file:")
            or "\x00" in target
            or windows_target.startswith("\\\\")
            or (has_drive_prefix and not has_absolute_drive)
            or ":" in without_drive
            or ambiguous_part
            or reserved_part
        ):
            raise RepositoryError("target SQLite efêmero ou ambíguo")
        try:
            self._connection = sqlite3.connect(
                target,
                timeout=timeout,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            trusted_token = migrate(self._connection)
            lock = RLock()
            state_guard = _DatabaseStateGuard(self._connection, trusted_token)
            self.workspaces = SQLiteWorkspaceRepository(
                self._connection, lock, state_guard
            )
            self.revisions = SQLiteArtifactRevisionRepository(
                self._connection, lock, state_guard
            )
        except RepositoryError:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
            raise
        except sqlite3.Error as exc:
            if hasattr(self, "_connection"):
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
            raise RepositoryError("falha ao abrir armazenamento SQLite") from exc

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error as exc:
            raise RepositoryError("falha ao fechar armazenamento SQLite") from exc

    def __enter__(self) -> SQLiteApplicationStore:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.close()
            return
        try:
            self.close()
        except RepositoryError:
            pass
