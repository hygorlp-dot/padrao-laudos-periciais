"""Autoridade de instalação: configurações globais e ativos, fora de qualquer perícia.

Arquivo SQLite próprio, ao lado do banco das perícias. Não existe
`workspace_id = GLOBAL` e o schema do banco das perícias não muda. O backup de
uma perícia não lê este arquivo, e o arquivo nunca é restaurado junto com uma
perícia: a perícia carrega o snapshot efetivo que recebeu na criação.

Duas tabelas, ambas append-only:

- `installation_setting_revisions`: histórico de cada configuração por
  `(setting_kind, setting_id)`. Restaurar é gravar uma revisão nova.
- `installation_assets`: bytes de imagem ou modelo Word, endereçados pelo
  SHA-256. Um ativo nunca é sobrescrito nem apagado; a revisão de
  configuração diz qual está em uso.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from uuid import UUID

from ..application.models import canonical_payload_json
from ..application.ports import PersistenceSchemaError, RepositoryConflict, RepositoryError, RepositoryIntegrityError


INSTALLATION_SCHEMA_VERSION = 1
INSTALLATION_APPLICATION_ID = 0x50455249  # "PERI"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_KEY = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

_REVISIONS_SQL = """
CREATE TABLE installation_setting_revisions (
    setting_kind TEXT NOT NULL CHECK (typeof(setting_kind) = 'text' AND length(trim(setting_kind)) > 0),
    setting_id TEXT NOT NULL CHECK (typeof(setting_id) = 'text' AND length(trim(setting_id)) > 0),
    revision_id TEXT PRIMARY KEY NOT NULL CHECK (
        typeof(revision_id) = 'text'
        AND length(revision_id) = 36
        AND revision_id = lower(revision_id)
        AND revision_id NOT GLOB '*[^0-9a-f-]*'
    ),
    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision >= 1),
    created_at TEXT NOT NULL CHECK (typeof(created_at) = 'text'),
    checksum_sha256 TEXT NOT NULL CHECK (typeof(checksum_sha256) = 'text'),
    payload_json TEXT NOT NULL CHECK (typeof(payload_json) = 'text'),
    UNIQUE (setting_kind, setting_id, revision)
)
"""

_ASSETS_SQL = """
CREATE TABLE installation_assets (
    sha256 TEXT PRIMARY KEY NOT NULL CHECK (typeof(sha256) = 'text' AND length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    media_type TEXT NOT NULL CHECK (typeof(media_type) = 'text' AND length(trim(media_type)) > 0),
    byte_size INTEGER NOT NULL CHECK (typeof(byte_size) = 'integer' AND byte_size >= 1),
    content BLOB NOT NULL CHECK (typeof(content) = 'blob')
)
"""

_EXPECTED_TABLES = {
    "installation_setting_revisions": " ".join(_REVISIONS_SQL.split()),
    "installation_assets": " ".join(_ASSETS_SQL.split()),
}


@dataclass(frozen=True, slots=True)
class InstallationSettingRevision:
    setting_kind: str
    setting_id: str
    revision_id: str
    revision: int
    created_at: str
    checksum_sha256: str
    payload: object


@dataclass(frozen=True, slots=True)
class InstallationAsset:
    sha256: str
    media_type: str
    byte_size: int
    content: bytes


def _key(value: object, field: str) -> str:
    if type(value) is not str or _KEY.fullmatch(value) is None:
        raise ValueError(f"{field} de configuração inválido")
    return value


def _validate_schema(connection: sqlite3.Connection) -> None:
    unexpected = tuple(connection.execute("SELECT type, name FROM sqlite_master WHERE type IN ('index', 'view', 'trigger') AND sql IS NOT NULL"))
    if unexpected:
        raise PersistenceSchemaError("configurações da instalação com objetos inesperados")
    tables = {row[0]: row[1] for row in connection.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
    if set(tables) != set(_EXPECTED_TABLES):
        raise PersistenceSchemaError("configurações da instalação com tabelas inesperadas ou ausentes")
    for name, sql in _EXPECTED_TABLES.items():
        if " ".join(tables[name].split()) != sql:
            raise PersistenceSchemaError(f"configurações da instalação com schema malformado: {name}")


def _revision_from_row(row) -> InstallationSettingRevision:
    setting_kind, setting_id, revision_id, revision, created_at, checksum, payload_json = row
    try:
        if str(UUID(revision_id)) != revision_id:
            raise ValueError("revision_id não canônico")
        payload = json.loads(payload_json)
        canonical = canonical_payload_json(payload)
        if canonical != payload_json or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != checksum:
            raise ValueError("payload divergente")
        return InstallationSettingRevision(_key(setting_kind, "tipo"), _key(setting_id, "identidade"), revision_id, revision, created_at, checksum, payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RepositoryIntegrityError("revisão de configuração da instalação inválida") from exc


def _validate_records(connection: sqlite3.Connection) -> None:
    sequences: dict[tuple[str, str], list[int]] = {}
    for row in connection.execute("SELECT setting_kind, setting_id, revision_id, revision, created_at, checksum_sha256, payload_json FROM installation_setting_revisions"):
        record = _revision_from_row(tuple(row))
        sequences.setdefault((record.setting_kind, record.setting_id), []).append(record.revision)
    for values in sequences.values():
        if sorted(values) != list(range(1, len(values) + 1)):
            raise RepositoryIntegrityError("histórico de configurações da instalação incompleto")
    for sha, media_type, size, content in connection.execute("SELECT sha256, media_type, byte_size, content FROM installation_assets"):
        if type(content) is not bytes or len(content) != size or hashlib.sha256(content).hexdigest() != sha:
            raise RepositoryIntegrityError("ativo da instalação diverge do seu SHA-256")


def _migrate(connection: sqlite3.Connection) -> None:
    """Cria o schema 1 de forma idempotente; schema desconhecido falha fechado."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        if version == 0:
            existing = tuple(connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
            if existing or application_id not in (0, INSTALLATION_APPLICATION_ID):
                raise PersistenceSchemaError("arquivo de configurações da instalação desconhecido")
            connection.execute(_REVISIONS_SQL)
            connection.execute(_ASSETS_SQL)
            connection.execute(f"PRAGMA user_version = {INSTALLATION_SCHEMA_VERSION}")
            connection.execute(f"PRAGMA application_id = {INSTALLATION_APPLICATION_ID}")
        elif version != INSTALLATION_SCHEMA_VERSION or application_id != INSTALLATION_APPLICATION_ID:
            raise PersistenceSchemaError(f"versão desconhecida das configurações da instalação: {version}")
        _validate_schema(connection)
        _validate_records(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


class SQLiteInstallationStore:
    """Persistência local das configurações e dos ativos da instalação."""

    def __init__(self, database: str | Path, *, timeout: float = 5.0):
        path = Path(database)
        if not str(path).strip() or str(path) == ":memory:":
            raise RepositoryError("arquivo de configurações da instalação inválido")
        self._lock = RLock()
        try:
            self._connection = sqlite3.connect(str(path), timeout=timeout, isolation_level=None, check_same_thread=False)
        except sqlite3.Error as exc:
            raise RepositoryError("falha ao abrir as configurações da instalação") from exc
        try:
            _migrate(self._connection)
        except sqlite3.Error as exc:
            self._connection.close()
            raise RepositoryError("falha ao abrir as configurações da instalação") from exc
        except BaseException:
            # Esquema, checksum ou sequência inválidos: a conexão não fica aberta.
            self._connection.close()
            raise

    @contextmanager
    def _transaction(self, mode: str = "BEGIN"):
        with self._lock:
            try:
                self._connection.execute(mode)
                yield
                self._connection.commit()
            except BaseException:
                try:
                    self._connection.rollback()
                except sqlite3.Error:
                    pass
                raise

    def latest(self, setting_kind: str, setting_id: str) -> InstallationSettingRevision | None:
        kind, identity = _key(setting_kind, "tipo"), _key(setting_id, "identidade")
        try:
            with self._transaction():
                row = self._connection.execute(
                    "SELECT setting_kind, setting_id, revision_id, revision, created_at, checksum_sha256, payload_json FROM installation_setting_revisions WHERE setting_kind = ? AND setting_id = ? ORDER BY revision DESC LIMIT 1",
                    (kind, identity),
                ).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError("falha ao ler configuração da instalação") from exc
        return None if row is None else _revision_from_row(tuple(row))

    def history(self, setting_kind: str, setting_id: str) -> tuple[InstallationSettingRevision, ...]:
        kind, identity = _key(setting_kind, "tipo"), _key(setting_id, "identidade")
        try:
            with self._transaction():
                rows = self._connection.execute(
                    "SELECT setting_kind, setting_id, revision_id, revision, created_at, checksum_sha256, payload_json FROM installation_setting_revisions WHERE setting_kind = ? AND setting_id = ? ORDER BY revision",
                    (kind, identity),
                ).fetchall()
        except sqlite3.Error as exc:
            raise RepositoryError("falha ao ler o histórico da configuração") from exc
        return tuple(_revision_from_row(tuple(row)) for row in rows)

    def append_if_latest(self, *, setting_kind: str, setting_id: str, revision_id: str, created_at: str, payload: object, expected_revision: int | None) -> InstallationSettingRevision:
        kind, identity = _key(setting_kind, "tipo"), _key(setting_id, "identidade")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("revisão esperada inválida")
        canonical = canonical_payload_json(payload)
        checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        revision_id = str(UUID(revision_id))
        try:
            with self._transaction("BEGIN IMMEDIATE"):
                current = self._connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM installation_setting_revisions WHERE setting_kind = ? AND setting_id = ?",
                    (kind, identity),
                ).fetchone()[0]
                if current != (expected_revision or 0):
                    raise RepositoryConflict("a configuração foi alterada em outra tela")
                self._connection.execute(
                    "INSERT INTO installation_setting_revisions (setting_kind, setting_id, revision_id, revision, created_at, checksum_sha256, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (kind, identity, revision_id, current + 1, created_at, checksum, canonical),
                )
        except sqlite3.IntegrityError as exc:
            raise RepositoryConflict("conflito de identidade de revisão da instalação") from exc
        except sqlite3.Error as exc:
            raise RepositoryError("falha ao gravar configuração da instalação") from exc
        return InstallationSettingRevision(kind, identity, revision_id, current + 1, created_at, checksum, json.loads(canonical))

    def put_asset(self, content: bytes, media_type: str) -> InstallationAsset:
        if type(content) is not bytes or not content or type(media_type) is not str or not media_type.strip():
            raise ValueError("ativo da instalação inválido")
        digest = hashlib.sha256(content).hexdigest()
        try:
            with self._transaction("BEGIN IMMEDIATE"):
                existing = self._connection.execute("SELECT media_type, byte_size FROM installation_assets WHERE sha256 = ?", (digest,)).fetchone()
                if existing is None:
                    self._connection.execute(
                        "INSERT INTO installation_assets (sha256, media_type, byte_size, content) VALUES (?, ?, ?, ?)",
                        (digest, media_type, len(content), content),
                    )
                elif tuple(existing) != (media_type, len(content)):
                    raise RepositoryIntegrityError("o mesmo conteúdo já existe com outro tipo")
        except sqlite3.Error as exc:
            raise RepositoryError("falha ao gravar ativo da instalação") from exc
        return InstallationAsset(digest, media_type, len(content), content)

    def get_asset(self, sha256: str) -> InstallationAsset | None:
        if type(sha256) is not str or _SHA256.fullmatch(sha256) is None:
            raise ValueError("identidade de ativo inválida")
        try:
            with self._transaction():
                row = self._connection.execute("SELECT sha256, media_type, byte_size, content FROM installation_assets WHERE sha256 = ?", (sha256,)).fetchone()
        except sqlite3.Error as exc:
            raise RepositoryError("falha ao ler ativo da instalação") from exc
        if row is None:
            return None
        content = row[3]
        if type(content) is not bytes or len(content) != row[2] or hashlib.sha256(content).hexdigest() != row[0]:
            raise RepositoryIntegrityError("ativo da instalação diverge do seu SHA-256")
        return InstallationAsset(row[0], row[1], row[2], content)

    def close(self) -> None:
        with self._lock:
            try:
                self._connection.close()
            except sqlite3.Error as exc:
                raise RepositoryError("falha ao fechar as configurações da instalação") from exc


def installation_database_path(database: str | Path) -> Path:
    """Arquivo da instalação ao lado do banco das perícias, nunca dentro dele."""
    path = Path(database)
    return path.parent / f".{path.name}.installation.sqlite3"
