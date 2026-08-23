"""Composition root explícita da Local API e de sua persistência local."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from ..application.ports import Clock, IdGenerator, RepositoryError
from ..application.services import (
    AppendArtifactRevision,
    CreateWorkspace,
    GetArtifactRevision,
    GetLatestArtifact,
    GetWorkspace,
    ListArtifactRevisions,
    ListWorkspaces,
)
from ..infrastructure.sqlite import SQLiteApplicationStore
from .server import LocalApiServer, LocalApiServerStartError, LocalServerConfig
from .transport import LocalApi, LocalApiServices, _require_local_token


class LocalApiStartupError(RuntimeError):
    """Falha sanitizada antes de a API local ficar disponível."""


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _UuidGenerator:
    def new_uuid(self) -> UUID:
        return uuid4()


@dataclass(slots=True)
class LocalApiRuntime:
    """Dono explícito do servidor e da sessão SQLite."""

    server: LocalApiServer
    token: str = field(repr=False)
    _store: SQLiteApplicationStore = field(repr=False)
    _closed: bool = False
    _lifecycle_lock: object = field(
        default_factory=Lock,
        init=False,
        repr=False,
        compare=False,
    )

    @property
    def address(self) -> tuple[str, int]:
        return self.server.address

    def start(self) -> tuple[str, int]:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("runtime local fechado")
            try:
                return self.server.start()
            except LocalApiServerStartError as exc:
                self._closed = True
                try:
                    self._store.close()
                except RepositoryError:
                    pass
                raise LocalApiStartupError("servidor local indisponível") from exc

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.server.close()
            finally:
                self._store.close()

    def __enter__(self) -> LocalApiRuntime:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is None:
            self.close()
            return
        try:
            self.close()
        except RepositoryError:
            pass


def build_local_api(
    database: str | Path,
    *,
    config: LocalServerConfig | None = None,
    token: str | None = None,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
) -> LocalApiRuntime:
    """Compõe serviços, SQLite e listener sem esconder suas dependências."""

    if config is not None and type(config) is not LocalServerConfig:
        raise TypeError("config local invalida")
    server_config = LocalServerConfig() if config is None else config
    local_token = secrets.token_urlsafe(32) if token is None else token
    _require_local_token(local_token)
    local_clock = _SystemClock() if clock is None else clock
    local_ids = _UuidGenerator() if ids is None else ids
    store = SQLiteApplicationStore(database)
    services = LocalApiServices(
        create_workspace=CreateWorkspace(store.workspaces, local_clock, local_ids),
        get_workspace=GetWorkspace(store.workspaces),
        list_workspaces=ListWorkspaces(store.workspaces),
        append_artifact_revision=AppendArtifactRevision(
            store.revisions, local_clock, local_ids
        ),
        get_latest_artifact=GetLatestArtifact(store.revisions),
        get_artifact_revision=GetArtifactRevision(store.revisions),
        list_artifact_revisions=ListArtifactRevisions(store.revisions),
    )
    api = LocalApi(
        services,
        token=local_token,
        max_body_bytes=server_config.max_body_bytes,
    )
    try:
        server = LocalApiServer(api, server_config)
    except OSError as exc:
        try:
            store.close()
        except RepositoryError:
            pass
        raise LocalApiStartupError("servidor local indisponível") from exc
    return LocalApiRuntime(server=server, token=local_token, _store=store)
