"""Casos de uso explícitos e finos da Application Layer local."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .models import (
    ArtifactRevision,
    PericiaWorkspace,
    ProcessCaseData,
    ProcessCaseSnapshot,
    WorkspaceId,
    canonical_payload_json,
    thaw_payload,
)
from .ports import (
    ArtifactRevisionNotFound,
    ArtifactRevisionRepository,
    Clock,
    IdGenerator,
    RepositoryIntegrityError,
    WorkspaceNotFound,
    WorkspaceRepository,
)


_PROCESS_CASE_ARTIFACT_KIND = "PROCESS_CASE"
_PROCESS_CASE_ARTIFACT_ID = "PROCESS_CASE"


def _generated_uuid(ids: IdGenerator) -> UUID:
    value = ids.new_uuid()
    if type(value) is not UUID:
        raise TypeError("IdGenerator deve retornar UUID")
    return value


def _generated_timestamp(clock: Clock) -> str:
    value = clock.now()
    if type(value) is not datetime:
        raise TypeError("Clock deve retornar datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Clock deve retornar datetime com timezone")
    return value.isoformat()


def _workspace_key(value: WorkspaceId) -> WorkspaceId:
    if type(value) is not WorkspaceId:
        raise TypeError("workspace_id inválido")
    return value


def _artifact_key(value: str, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} inválido")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contém Unicode inválido") from exc
    return value


def _revision_number(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError("revision inválida")
    return value


def _not_found(
    workspace_id: WorkspaceId,
    artifact_kind: str,
    artifact_id: str,
    revision: int | None = None,
) -> ArtifactRevisionNotFound:
    identity = f"{workspace_id}/{artifact_kind}/{artifact_id}"
    if revision is not None:
        identity = f"{identity}@{revision}"
    return ArtifactRevisionNotFound(f"revisão de artefato não encontrada: {identity}")


@dataclass(frozen=True, slots=True)
class CreateWorkspace:
    repository: WorkspaceRepository
    clock: Clock
    ids: IdGenerator

    def execute(self, name: str) -> PericiaWorkspace:
        workspace_id = WorkspaceId(_generated_uuid(self.ids))
        created_at = _generated_timestamp(self.clock)
        return self.repository.create(PericiaWorkspace(workspace_id, name, created_at))


@dataclass(frozen=True, slots=True)
class GetWorkspace:
    repository: WorkspaceRepository

    def execute(self, workspace_id: WorkspaceId) -> PericiaWorkspace:
        workspace_id = _workspace_key(workspace_id)
        result = self.repository.get(workspace_id)
        if result is None:
            raise WorkspaceNotFound(f"workspace não encontrado: {workspace_id}")
        return result


@dataclass(frozen=True, slots=True)
class ListWorkspaces:
    repository: WorkspaceRepository

    def execute(self) -> tuple[PericiaWorkspace, ...]:
        return self.repository.list_all()


def _require_workspace(
    repository: WorkspaceRepository, workspace_id: WorkspaceId
) -> WorkspaceId:
    workspace_id = _workspace_key(workspace_id)
    if repository.get(workspace_id) is None:
        raise WorkspaceNotFound(f"workspace não encontrado: {workspace_id}")
    return workspace_id


def _process_case_snapshot(record: ArtifactRevision) -> ProcessCaseSnapshot:
    try:
        data = ProcessCaseData.from_mapping(thaw_payload(record.payload))
        return ProcessCaseSnapshot(
            workspace_id=record.workspace_id,
            revision=record.revision,
            updated_at=record.created_at,
            data=data,
        )
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError(
            "dados processuais persistidos são inválidos"
        ) from exc


@dataclass(frozen=True, slots=True)
class GetProcessCase:
    workspaces: WorkspaceRepository
    revisions: ArtifactRevisionRepository

    def execute(self, workspace_id: WorkspaceId) -> ProcessCaseSnapshot:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        record = self.revisions.latest(
            workspace_id,
            _PROCESS_CASE_ARTIFACT_KIND,
            _PROCESS_CASE_ARTIFACT_ID,
        )
        if record is None:
            return ProcessCaseSnapshot(
                workspace_id=workspace_id,
                revision=None,
                updated_at=None,
                data=ProcessCaseData.empty(),
            )
        return _process_case_snapshot(record)


@dataclass(frozen=True, slots=True)
class SaveProcessCase:
    workspaces: WorkspaceRepository
    revisions: ArtifactRevisionRepository
    clock: Clock
    ids: IdGenerator

    def execute(
        self, workspace_id: WorkspaceId, data: ProcessCaseData
    ) -> ProcessCaseSnapshot:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        if type(data) is not ProcessCaseData:
            raise TypeError("dados processuais inválidos")
        record = self.revisions.append(
            workspace_id=workspace_id,
            artifact_kind=_PROCESS_CASE_ARTIFACT_KIND,
            artifact_id=_PROCESS_CASE_ARTIFACT_ID,
            revision_id=str(_generated_uuid(self.ids)),
            created_at=_generated_timestamp(self.clock),
            payload=data.as_dict(),
        )
        return _process_case_snapshot(record)


@dataclass(frozen=True, slots=True)
class AppendArtifactRevision:
    repository: ArtifactRevisionRepository
    clock: Clock
    ids: IdGenerator

    def execute(
        self,
        *,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        payload: object,
    ) -> ArtifactRevision:
        workspace_id = _workspace_key(workspace_id)
        artifact_kind = _artifact_key(artifact_kind, "artifact_kind")
        artifact_id = _artifact_key(artifact_id, "artifact_id")
        payload_snapshot = json.loads(canonical_payload_json(payload))
        revision_id = str(_generated_uuid(self.ids))
        created_at = _generated_timestamp(self.clock)
        return self.repository.append(
            workspace_id=workspace_id,
            artifact_kind=artifact_kind,
            artifact_id=artifact_id,
            revision_id=revision_id,
            created_at=created_at,
            payload=payload_snapshot,
        )


@dataclass(frozen=True, slots=True)
class GetLatestArtifact:
    repository: ArtifactRevisionRepository

    def execute(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> ArtifactRevision:
        workspace_id = _workspace_key(workspace_id)
        artifact_kind = _artifact_key(artifact_kind, "artifact_kind")
        artifact_id = _artifact_key(artifact_id, "artifact_id")
        result = self.repository.latest(workspace_id, artifact_kind, artifact_id)
        if result is None:
            raise _not_found(workspace_id, artifact_kind, artifact_id)
        return result


@dataclass(frozen=True, slots=True)
class GetArtifactRevision:
    repository: ArtifactRevisionRepository

    def execute(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
        revision: int,
    ) -> ArtifactRevision:
        workspace_id = _workspace_key(workspace_id)
        artifact_kind = _artifact_key(artifact_kind, "artifact_kind")
        artifact_id = _artifact_key(artifact_id, "artifact_id")
        revision = _revision_number(revision)
        result = self.repository.get_revision(
            workspace_id, artifact_kind, artifact_id, revision
        )
        if result is None:
            raise _not_found(workspace_id, artifact_kind, artifact_id, revision)
        return result


@dataclass(frozen=True, slots=True)
class ListArtifactRevisions:
    repository: ArtifactRevisionRepository

    def execute(
        self,
        workspace_id: WorkspaceId,
        artifact_kind: str,
        artifact_id: str,
    ) -> tuple[ArtifactRevision, ...]:
        workspace_id = _workspace_key(workspace_id)
        artifact_kind = _artifact_key(artifact_kind, "artifact_kind")
        artifact_id = _artifact_key(artifact_id, "artifact_id")
        return self.repository.list_all(workspace_id, artifact_kind, artifact_id)
