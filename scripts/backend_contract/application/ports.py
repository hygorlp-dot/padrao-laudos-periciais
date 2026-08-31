"""Ports explícitos para a infraestrutura local da Application Layer."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from .models import (
    ArtifactRevision,
    PericiaWorkspace,
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    WorkspaceId,
)
from .content import OpenPrivateContent, SeekableContent


class RepositoryError(RuntimeError):
    """Falha explícita no contrato de persistência da Application Layer."""


class RepositoryConflict(RepositoryError):
    """Identidade já existente ou conflito append-only."""


class WorkspaceNotFound(RepositoryError):
    """Workspace exigido pela operação não existe."""


class ArtifactRevisionNotFound(RepositoryError):
    """Revisão de artefato exigida pela operação não existe."""


class PrivateContentNotFound(RepositoryError):
    """Conteúdo privado exigido pela operação não existe no workspace."""


class PrivateContentTooLarge(ValueError):
    """Conteúdo privado excede o limite explícito do caso de uso."""


class UnsupportedCaseDocument(ValueError):
    """Formato de documento ainda não aceito pelo intake do produto."""


class InvalidCaseDocument(ValueError):
    """Bytes ou metadados não satisfazem o contrato documental V1."""


class RepositoryIntegrityError(RepositoryError):
    """Dados persistidos não satisfazem o contrato de integridade."""


class PersistenceSchemaError(RepositoryError):
    """Schema ausente, malformado ou de versão não suportada."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_uuid(self) -> UUID: ...


class WorkspaceRepository(Protocol):
    def create(self, workspace: PericiaWorkspace) -> PericiaWorkspace: ...

    def get(self, workspace_id: WorkspaceId) -> PericiaWorkspace | None: ...

    def list_all(self) -> tuple[PericiaWorkspace, ...]: ...


class ArtifactRevisionRepository(Protocol):
    def append(
        self,
        *,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision_id: str,
        created_at: str,
        payload: object,
    ) -> ArtifactRevision: ...

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
    ) -> ArtifactRevision: ...

    def append_pair_if_latest(
        self,
        *,
        workspace_id: WorkspaceId,
        first: dict[str, object],
        second: dict[str, object],
        expected_first_revision: int | None,
        expected_latest: tuple[dict[str, object], ...],
    ) -> tuple[ArtifactRevision, ArtifactRevision]: ...

    def latest(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> ArtifactRevision | None: ...

    def get_revision(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision: int,
    ) -> ArtifactRevision | None: ...

    def list_all(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> tuple[ArtifactRevision, ...]: ...


class PrivateContentRepository(Protocol):
    def store(
        self, metadata: PrivateContentMetadata, content: bytes | SeekableContent
    ) -> PrivateContentMetadata: ...

    def get(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> PrivateContent | None: ...

    def list_all(
        self, workspace_id: WorkspaceId
    ) -> tuple[PrivateContentMetadata, ...]: ...


class PrivateContentStreamRepository(PrivateContentRepository, Protocol):
    def open_content(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> OpenPrivateContent | None: ...
