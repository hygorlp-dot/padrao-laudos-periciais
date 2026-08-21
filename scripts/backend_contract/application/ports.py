"""Ports explícitos para a infraestrutura local da Application Layer."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from .models import ArtifactRevision, PericiaWorkspace, WorkspaceId


class RepositoryError(RuntimeError):
    """Falha explícita no contrato de persistência da Application Layer."""


class RepositoryConflict(RepositoryError):
    """Identidade já existente ou conflito append-only."""


class WorkspaceNotFound(RepositoryError):
    """Workspace exigido pela operação não existe."""


class ArtifactRevisionNotFound(RepositoryError):
    """Revisão de artefato exigida pela operação não existe."""


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
