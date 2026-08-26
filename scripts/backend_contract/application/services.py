"""Casos de uso explícitos e finos da Application Layer local."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .models import (
    ArtifactRevision,
    PericiaWorkspace,
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
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
    InvalidCaseDocument,
    PrivateContentNotFound,
    PrivateContentRepository,
    PrivateContentTooLarge,
    RepositoryIntegrityError,
    WorkspaceNotFound,
    WorkspaceRepository,
    UnsupportedCaseDocument,
)


_PROCESS_CASE_ARTIFACT_KIND = "PROCESS_CASE"
_PROCESS_CASE_ARTIFACT_ID = "PROCESS_CASE"
_CASE_DOCUMENT_MAX_BYTES = 16 * 1024 * 1024


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


@dataclass(frozen=True, slots=True)
class StorePrivateContent:
    workspaces: WorkspaceRepository
    contents: PrivateContentRepository
    clock: Clock
    ids: IdGenerator
    max_content_bytes: int

    def __post_init__(self):
        if type(self.max_content_bytes) is not int or self.max_content_bytes < 0:
            raise ValueError("max_content_bytes inválido")

    def execute(
        self,
        *,
        workspace_id: WorkspaceId,
        original_filename: str,
        content: bytes,
        media_type: str | None,
        origin: PrivateContentOrigin,
    ) -> PrivateContentMetadata:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        if type(content) is not bytes:
            raise TypeError("conteúdo privado exige bytes")
        if len(content) > self.max_content_bytes:
            raise PrivateContentTooLarge("conteúdo privado excede limite configurado")
        metadata = PrivateContentMetadata(
            workspace_id=workspace_id,
            content_id=PrivateContentId(_generated_uuid(self.ids)),
            original_filename=original_filename,
            byte_size=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
            media_type=media_type,
            imported_at=_generated_timestamp(self.clock),
            origin=origin,
        )
        stored = self.contents.store(metadata, content)
        if type(stored) is not PrivateContentMetadata or stored != metadata:
            raise RepositoryIntegrityError(
                "metadados retornados pelo armazenamento privado divergem"
            )
        return stored


@dataclass(frozen=True, slots=True)
class GetPrivateContent:
    workspaces: WorkspaceRepository
    contents: PrivateContentRepository

    def execute(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> PrivateContent:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        if type(content_id) is not PrivateContentId:
            raise TypeError("content_id inválido")
        record = self.contents.get(workspace_id, content_id)
        if record is None:
            raise PrivateContentNotFound(
                f"conteúdo privado não encontrado: {workspace_id}/{content_id}"
            )
        if (
            type(record) is not PrivateContent
            or record.metadata.workspace_id != workspace_id
            or record.metadata.content_id != content_id
        ):
            raise RepositoryIntegrityError(
                "identidade retornada pelo armazenamento privado diverge"
            )
        return record


@dataclass(frozen=True, slots=True)
class ListPrivateContents:
    workspaces: WorkspaceRepository
    contents: PrivateContentRepository

    def execute(
        self, workspace_id: WorkspaceId
    ) -> tuple[PrivateContentMetadata, ...]:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        records = self.contents.list_all(workspace_id)
        if type(records) is not tuple or any(
            type(record) is not PrivateContentMetadata
            or record.workspace_id != workspace_id
            for record in records
        ):
            raise RepositoryIntegrityError(
                "listagem retornada pelo armazenamento privado diverge"
            )
        return records


def _case_document_metadata(record: PrivateContentMetadata) -> PrivateContentMetadata:
    if (
        type(record) is not PrivateContentMetadata
        or record.media_type != "application/pdf"
        or record.origin is not PrivateContentOrigin.USER_IMPORT
    ):
        raise InvalidCaseDocument("documento privado diverge do contrato PDF")
    return record


@dataclass(frozen=True, slots=True)
class ImportCaseDocument:
    contents: StorePrivateContent

    def __post_init__(self):
        if type(self.contents) is not StorePrivateContent:
            raise TypeError("serviço de conteúdo privado inválido")

    def execute(
        self,
        *,
        workspace_id: WorkspaceId,
        original_filename: str,
        content: bytes,
        media_type: str,
    ) -> PrivateContentMetadata:
        if media_type != "application/pdf":
            raise UnsupportedCaseDocument("somente documentos PDF são aceitos")
        if type(content) is not bytes:
            raise TypeError("documento PDF exige bytes")
        if len(content) > _CASE_DOCUMENT_MAX_BYTES:
            raise PrivateContentTooLarge("documento PDF excede limite de 16 MiB")
        if not content.startswith(b"%PDF-") or not content.rstrip().endswith(b"%%EOF"):
            raise InvalidCaseDocument("bytes não representam um documento PDF válido")
        return _case_document_metadata(
            self.contents.execute(
                workspace_id=workspace_id,
                original_filename=original_filename,
                content=content,
                media_type="application/pdf",
                origin=PrivateContentOrigin.USER_IMPORT,
            )
        )


@dataclass(frozen=True, slots=True)
class ListCaseDocuments:
    contents: ListPrivateContents

    def __post_init__(self):
        if type(self.contents) is not ListPrivateContents:
            raise TypeError("serviço de listagem privada inválido")

    def execute(self, workspace_id: WorkspaceId) -> tuple[PrivateContentMetadata, ...]:
        return tuple(
            _case_document_metadata(record)
            for record in self.contents.execute(workspace_id)
        )


@dataclass(frozen=True, slots=True)
class ReadCaseDocument:
    contents: GetPrivateContent

    def __post_init__(self):
        if type(self.contents) is not GetPrivateContent:
            raise TypeError("serviço de leitura privada inválido")

    def execute(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> PrivateContent:
        record = self.contents.execute(workspace_id, content_id)
        _case_document_metadata(record.metadata)
        return record


def _require_workspace(
    repository: WorkspaceRepository, workspace_id: WorkspaceId
) -> WorkspaceId:
    workspace_id = _workspace_key(workspace_id)
    if repository.get(workspace_id) is None:
        raise WorkspaceNotFound(f"workspace não encontrado: {workspace_id}")
    return workspace_id


def _process_case_snapshot(
    record: ArtifactRevision, expected_workspace_id: WorkspaceId
) -> ProcessCaseSnapshot:
    try:
        if (
            record.workspace_id != expected_workspace_id
            or record.artifact_kind != _PROCESS_CASE_ARTIFACT_KIND
            or record.artifact_id != _PROCESS_CASE_ARTIFACT_ID
        ):
            raise ValueError("identidade processual divergente")
        data = ProcessCaseData.from_mapping(thaw_payload(record.payload))
        return ProcessCaseSnapshot(
            workspace_id=record.workspace_id,
            revision=record.revision,
            updated_at=record.created_at,
            data=data,
        )
    except (AttributeError, TypeError, ValueError) as exc:
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
        return _process_case_snapshot(record, workspace_id)


@dataclass(frozen=True, slots=True)
class SaveProcessCase:
    workspaces: WorkspaceRepository
    revisions: ArtifactRevisionRepository
    clock: Clock
    ids: IdGenerator

    def execute(
        self,
        workspace_id: WorkspaceId,
        data: ProcessCaseData,
        expected_revision: int | None,
    ) -> ProcessCaseSnapshot:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        if type(data) is not ProcessCaseData:
            raise TypeError("dados processuais inválidos")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("expected_revision inválida")
        record = self.revisions.append_if_latest(
            workspace_id=workspace_id,
            artifact_kind=_PROCESS_CASE_ARTIFACT_KIND,
            artifact_id=_PROCESS_CASE_ARTIFACT_ID,
            revision_id=str(_generated_uuid(self.ids)),
            created_at=_generated_timestamp(self.clock),
            payload=data.as_dict(),
            expected_revision=expected_revision,
        )
        return _process_case_snapshot(record, workspace_id)


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
        if (
            artifact_kind == _PROCESS_CASE_ARTIFACT_KIND
            and artifact_id == _PROCESS_CASE_ARTIFACT_ID
        ):
            raise ValueError("identidade de artefato reservada")
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
