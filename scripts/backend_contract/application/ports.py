"""Ports explícitos para a infraestrutura local da Application Layer."""

from __future__ import annotations

from typing import Protocol

from .models import ArtifactRevision, PericiaWorkspace, WorkspaceId


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
