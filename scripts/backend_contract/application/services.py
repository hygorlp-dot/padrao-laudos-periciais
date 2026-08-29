"""Casos de uso explícitos e finos da Application Layer local."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from .content import (
    MAX_DOCUMENT_BYTES,
    OpenPrivateContent,
    SeekableContent,
    as_seekable_content,
)
from .ocr_cache import RevisionOcrPageCache
from .process_metadata import (
    PROCESS_METADATA_FIELDS,
    DocumentExtractionSummary,
    ExtractedField,
    FieldExtractionState,
    PageProcessingStatus,
    PdfTextExtractionState,
    PdfTextResult,
    ProcessMetadataReview,
    aggregate_process_metadata,
    document_metadata_from_payload,
    document_metadata_payload,
    extract_process_metadata,
)
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
    PrivateContentStreamRepository,
    PrivateContentTooLarge,
    RepositoryConflict,
    RepositoryIntegrityError,
    WorkspaceNotFound,
    WorkspaceRepository,
    UnsupportedCaseDocument,
)


_PROCESS_CASE_ARTIFACT_KIND = "PROCESS_CASE"
_PROCESS_CASE_ARTIFACT_ID = "PROCESS_CASE"
_PROCESS_METADATA_EXTRACTION_KIND = "PROCESS_METADATA_EXTRACTION"
_PROCESS_METADATA_CONFIRMATION_KIND = "PROCESS_METADATA_CONFIRMATION"
_PROCESS_METADATA_CONFIRMATION_ID = "PROCESS_METADATA_CONFIRMATION"
_PROCESS_METADATA_SOURCE_CONFIRMATION_KIND = "PROCESS_METADATA_SOURCE_CONFIRMATION"


def _metadata_extraction_fingerprint(value: object) -> str:
    encoded = canonical_payload_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _case_document_filename(value: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise InvalidCaseDocument("nome de arquivo PDF inválido")
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\")):
        raise InvalidCaseDocument("nome de arquivo PDF não pode expor path absoluto")
    return value
_CASE_DOCUMENT_MAX_BYTES = MAX_DOCUMENT_BYTES


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
        content: bytes | SeekableContent,
        media_type: str | None,
        origin: PrivateContentOrigin,
    ) -> PrivateContentMetadata:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        source = as_seekable_content(content)
        if source.byte_size > self.max_content_bytes:
            raise PrivateContentTooLarge("conteúdo privado excede limite configurado")
        metadata = PrivateContentMetadata(
            workspace_id=workspace_id,
            content_id=PrivateContentId(_generated_uuid(self.ids)),
            original_filename=original_filename,
            byte_size=source.byte_size,
            checksum_sha256=source.sha256(),
            media_type=media_type,
            imported_at=_generated_timestamp(self.clock),
            origin=origin,
        )
        stored = self.contents.store(metadata, content if type(content) is bytes else source)
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
class OpenPrivateContentStream:
    workspaces: WorkspaceRepository
    contents: PrivateContentStreamRepository

    def execute(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> OpenPrivateContent:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        if type(content_id) is not PrivateContentId:
            raise TypeError("content_id inválido")
        record = self.contents.open_content(workspace_id, content_id)
        if record is None:
            raise PrivateContentNotFound(
                f"conteúdo privado não encontrado: {workspace_id}/{content_id}"
            )
        if (
            type(record) is not OpenPrivateContent
            or record.metadata.workspace_id != workspace_id
            or record.metadata.content_id != content_id
        ):
            if type(record) is OpenPrivateContent:
                record.close()
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
        content: bytes | SeekableContent,
        media_type: str,
    ) -> PrivateContentMetadata:
        if media_type != "application/pdf":
            raise UnsupportedCaseDocument("somente documentos PDF são aceitos")
        original_filename = _case_document_filename(original_filename)
        source = as_seekable_content(content)
        if source.byte_size > _CASE_DOCUMENT_MAX_BYTES:
            raise PrivateContentTooLarge("documento PDF excede limite de 128 MiB")
        if not source.prefix(5).startswith(b"%PDF-") or not source.suffix(64).rstrip().endswith(b"%%EOF"):
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
class ImportCaseDocumentWithMetadata:
    documents: object
    document_streams: object
    extractor: object
    revisions: ArtifactRevisionRepository
    clock: Clock
    ids: IdGenerator

    def execute(
        self,
        *,
        workspace_id: WorkspaceId,
        original_filename: str,
        content: bytes | SeekableContent,
        media_type: str,
    ) -> PrivateContentMetadata:
        source = as_seekable_content(content)
        record = self.documents.execute(
            workspace_id=workspace_id,
            original_filename=original_filename,
            content=source,
            media_type=media_type,
        )
        page_cache = RevisionOcrPageCache(
            self.revisions,
            record.workspace_id,
            self.clock,
            self.ids,
        )
        extracted_at = _generated_timestamp(self.clock)
        with self.document_streams.execute(
            record.workspace_id, record.content_id
        ) as persisted:
            if persisted.metadata != record:
                raise RepositoryIntegrityError(
                    "conteúdo persistido diverge do documento importado"
                )

            def extract_with(method):
                persisted.stream.seek(0)
                text = method(
                    persisted.stream,
                    document_sha256=record.checksum_sha256,
                    page_cache=page_cache,
                )
                if (
                    type(text) is not PdfTextResult
                    or text.document_sha256 != record.checksum_sha256
                ):
                    raise RepositoryIntegrityError(
                        "checksum da extração diverge do material persistido"
                    )
                return text

            text = extract_with(self.extractor.extract)
            extracted = extract_process_metadata(
                workspace_id=record.workspace_id,
                document_id=record.content_id,
                original_filename=record.original_filename,
                text=text,
                extracted_at=extracted_at,
            )
            if (
                any(
                    page.processing_status is PageProcessingStatus.NOT_PROCESSED
                    for page in text.pages
                )
                and any(
                    field.state is not FieldExtractionState.CONFIDENT
                    for field in extracted.fields.values()
                )
            ):
                expand = getattr(self.extractor, "expand", None)
                if not callable(expand):
                    raise RepositoryIntegrityError(
                        "leitor parcial não oferece expansão OCR limitada"
                    )
                text = extract_with(expand)
                extracted = extract_process_metadata(
                    workspace_id=record.workspace_id,
                    document_id=record.content_id,
                    original_filename=record.original_filename,
                    text=text,
                    extracted_at=extracted_at,
                )
        self.revisions.append(
            workspace_id=record.workspace_id,
            artifact_kind=_PROCESS_METADATA_EXTRACTION_KIND,
            artifact_id=str(record.content_id),
            revision_id=str(_generated_uuid(self.ids)),
            created_at=_generated_timestamp(self.clock),
            payload=document_metadata_payload(extracted),
        )
        return record


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


@dataclass(frozen=True, slots=True)
class OpenCaseDocument:
    contents: OpenPrivateContentStream

    def execute(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> OpenPrivateContent:
        record = self.contents.execute(workspace_id, content_id)
        try:
            _case_document_metadata(record.metadata)
        except Exception:
            record.close()
            raise
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

    def execute_with_source_confirmation(
        self,
        workspace_id: WorkspaceId,
        data: ProcessCaseData,
        expected_revision: int | None,
        *,
        confirmation: dict[str, object],
        source_expectations: tuple[dict[str, object], ...],
    ) -> ProcessCaseSnapshot:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        if type(data) is not ProcessCaseData:
            raise TypeError("dados processuais inválidos")
        if (
            type(confirmation) is not dict
            or set(confirmation) != {"artifact_id", "payload"}
            or type(source_expectations) is not tuple
            or not source_expectations
        ):
            raise ValueError("confirmação de fonte inválida")
        created_at = _generated_timestamp(self.clock)
        process_record, _ = self.revisions.append_pair_if_latest(
            workspace_id=workspace_id,
            first={
                "artifact_kind": _PROCESS_CASE_ARTIFACT_KIND,
                "artifact_id": _PROCESS_CASE_ARTIFACT_ID,
                "revision_id": str(_generated_uuid(self.ids)),
                "created_at": created_at,
                "payload": data.as_dict(),
            },
            second={
                "artifact_kind": _PROCESS_METADATA_SOURCE_CONFIRMATION_KIND,
                "artifact_id": confirmation["artifact_id"],
                "revision_id": str(_generated_uuid(self.ids)),
                "created_at": created_at,
                "payload": confirmation["payload"],
            },
            expected_first_revision=expected_revision,
            expected_latest=source_expectations,
        )
        return _process_case_snapshot(process_record, workspace_id)


@dataclass(frozen=True, slots=True)
class GetProcessMetadataReview:
    workspaces: WorkspaceRepository
    documents: object
    revisions: ArtifactRevisionRepository
    process_case: object | None = None

    @staticmethod
    def empty(workspace_id: WorkspaceId) -> ProcessMetadataReview:
        snapshot: list[object] = []
        return ProcessMetadataReview(
            workspace_id=workspace_id,
            state="WAITING_FOR_DOCUMENTS",
            confirmed_revision=None,
            fields=MappingProxyType(
                {
                    field: ExtractedField(FieldExtractionState.NOT_FOUND, "", ())
                    for field in PROCESS_METADATA_FIELDS
                }
            ),
            documents=(),
            extraction_fingerprint=_metadata_extraction_fingerprint(snapshot),
            document_payloads=(),
            source_expectations=(),
        )

    def execute(self, workspace_id: WorkspaceId) -> ProcessMetadataReview:
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        document_records = self.documents.execute(workspace_id)
        if not document_records:
            return self.empty(workspace_id)
        extractions = []
        payloads = []
        summaries = []
        snapshot = []
        source_expectations = []
        missing_extraction = False
        for document in document_records:
            revision = self.revisions.latest(
                workspace_id,
                _PROCESS_METADATA_EXTRACTION_KIND,
                str(document.content_id),
            )
            if revision is None:
                missing_extraction = True
                summaries.append(
                    DocumentExtractionSummary(
                        document.content_id,
                        document.original_filename,
                        PdfTextExtractionState.ERROR,
                    )
                )
                snapshot.append(
                    {
                        "document_id": str(document.content_id),
                        "extraction_revision": None,
                    }
                )
                source_expectations.append(
                    {
                        "artifact_kind": _PROCESS_METADATA_EXTRACTION_KIND,
                        "artifact_id": str(document.content_id),
                        "revision": None,
                        "checksum_sha256": None,
                    }
                )
                continue
            extraction = document_metadata_from_payload(
                revision.payload,
                legacy_document_sha256=document.checksum_sha256,
            )
            if (
                extraction.workspace_id != workspace_id
                or extraction.document_id != document.content_id
                or extraction.source_filename != document.original_filename
                or extraction.document_sha256 != document.checksum_sha256
            ):
                raise RepositoryIntegrityError("extração documental diverge do material")
            extractions.append(extraction)
            payloads.append(revision.payload)
            summaries.append(
                DocumentExtractionSummary(
                    extraction.document_id,
                    extraction.source_filename,
                    extraction.text_state,
                )
            )
            snapshot.append(
                {
                    "document_id": str(document.content_id),
                    "document_checksum": document.checksum_sha256,
                    "extraction_revision": revision.revision,
                    "extraction_checksum": revision.checksum_sha256,
                    "payload": thaw_payload(revision.payload),
                }
            )
            source_expectations.append(
                {
                    "artifact_kind": _PROCESS_METADATA_EXTRACTION_KIND,
                    "artifact_id": str(document.content_id),
                    "revision": revision.revision,
                    "checksum_sha256": revision.checksum_sha256,
                }
            )
        aggregate = aggregate_process_metadata(tuple(extractions))
        extraction_fingerprint = _metadata_extraction_fingerprint(snapshot)
        confirmation = self.revisions.latest(
            workspace_id,
            _PROCESS_METADATA_CONFIRMATION_KIND,
            _PROCESS_METADATA_CONFIRMATION_ID,
        )
        confirmed_revision = None
        if confirmation is not None:
            confirmation_payload = thaw_payload(confirmation.payload)
            if type(confirmation_payload) is not dict or set(confirmation_payload) != {
                "schema_version",
                "confirmed_revision",
                "extraction_fingerprint",
            } or confirmation_payload["schema_version"] != 1:
                raise RepositoryIntegrityError("confirmação processual persistida inválida")
            confirmed_revision = confirmation_payload["confirmed_revision"]
            if type(confirmed_revision) is not int or confirmed_revision < 1:
                raise RepositoryIntegrityError("revisão confirmada inválida")
            confirmed_fingerprint = confirmation_payload["extraction_fingerprint"]
            if (
                type(confirmed_fingerprint) is not str
                or len(confirmed_fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in confirmed_fingerprint)
            ):
                raise RepositoryIntegrityError("fingerprint de confirmação inválido")
            if confirmed_fingerprint != extraction_fingerprint:
                confirmed_revision = None
            elif self.process_case is None:
                raise RepositoryIntegrityError(
                    "confirmação processual não possui vínculo à revisão atual"
                )
            else:
                current_case = self.process_case.execute(workspace_id)
                if current_case.revision != confirmed_revision:
                    confirmed_revision = None
        state = "CONFIRMED" if confirmed_revision is not None else aggregate.state
        if missing_extraction and confirmed_revision is None:
            state = "ERROR"
        return ProcessMetadataReview(
            workspace_id,
            state,
            confirmed_revision,
            aggregate.fields,
            tuple(summaries),
            extraction_fingerprint,
            tuple(payloads),
            tuple(source_expectations),
        )


@dataclass(frozen=True, slots=True)
class ConfirmProcessMetadata:
    process_case: object
    metadata_review: GetProcessMetadataReview
    revisions: ArtifactRevisionRepository
    clock: Clock
    ids: IdGenerator

    def execute(
        self,
        workspace_id: WorkspaceId,
        data: ProcessCaseData,
        expected_revision: int | None,
    ) -> ProcessCaseSnapshot:
        review = self.metadata_review.execute(workspace_id)
        snapshot = self.process_case.execute(workspace_id, data, expected_revision)
        self.revisions.append(
            workspace_id=workspace_id,
            artifact_kind=_PROCESS_METADATA_CONFIRMATION_KIND,
            artifact_id=_PROCESS_METADATA_CONFIRMATION_ID,
            revision_id=str(_generated_uuid(self.ids)),
            created_at=_generated_timestamp(self.clock),
            payload={
                "schema_version": 1,
                "confirmed_revision": snapshot.revision,
                "extraction_fingerprint": review.extraction_fingerprint,
            },
        )
        return snapshot


@dataclass(frozen=True, slots=True)
class ConfirmProcessMetadataSourceSpan:
    process_case: object
    save_process_case: object
    metadata_review: GetProcessMetadataReview

    def execute(
        self,
        *,
        workspace_id: WorkspaceId,
        field_name: str,
        evidence_id: str,
        source_start: int,
        source_end: int,
        expected_source_revision: str,
        expected_revision: int | None,
    ) -> ProcessCaseSnapshot:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace inválido")
        if field_name not in {"parte_requerente", "parte_requerida"}:
            raise ValueError("campo não admite confirmação por fonte")
        if (
            type(evidence_id) is not str
            or len(evidence_id) != 64
            or any(character not in "0123456789abcdef" for character in evidence_id)
            or type(expected_source_revision) is not str
            or len(expected_source_revision) != 64
            or any(
                character not in "0123456789abcdef"
                for character in expected_source_revision
            )
        ):
            raise ValueError("identidade de evidência inválida")
        if (
            type(source_start) is not int
            or type(source_end) is not int
            or source_start < 0
            or source_end <= source_start
        ):
            raise ValueError("span de fonte inválido")
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise ValueError("expected_revision inválida")

        review = self.metadata_review.execute(workspace_id)
        if review.workspace_id != workspace_id:
            raise ValueError("evidência pertence a outro workspace")
        if review.extraction_fingerprint != expected_source_revision:
            raise RepositoryConflict("fonte de metadados foi atualizada")
        matches = tuple(
            evidence
            for evidence in review.fields[field_name].evidence
            if evidence.evidence_id == evidence_id
        )
        if len(matches) != 1:
            raise ValueError("evidência não encontrada")
        evidence = matches[0]
        if (
            evidence.workspace_id != workspace_id
            or evidence.field_name != field_name
            or not evidence.requires_source_selection
            or source_end > len(evidence.source_text)
        ):
            raise ValueError("evidência não admite o span solicitado")
        selected_value = evidence.source_text[source_start:source_end]
        if not selected_value.strip():
            raise ValueError("seleção de fonte vazia")

        document_payloads = tuple(
            dict(payload) if type(payload) is dict else thaw_payload(payload)
            for payload in review.document_payloads
        )
        matching_documents = tuple(
            payload
            for payload in document_payloads
            if type(payload) is dict
            and payload.get("document_id") == str(evidence.document_id)
        )
        if len(matching_documents) != 1:
            raise RepositoryIntegrityError("documento da evidência não é único")
        document_sha256 = matching_documents[0].get("document_sha256")
        if (
            type(document_sha256) is not str
            or len(document_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in document_sha256
            )
        ):
            raise RepositoryIntegrityError("identidade documental inválida")

        current = self.process_case.execute(workspace_id)
        if (
            type(current) is not ProcessCaseSnapshot
            or current.workspace_id != workspace_id
        ):
            raise RepositoryIntegrityError("identidade processual divergente")
        if current.revision != expected_revision:
            raise RepositoryConflict("dados processuais foram atualizados")
        updated_data = ProcessCaseData.from_mapping(
            {
                **current.data.as_dict(),
                field_name: selected_value,
            }
        )
        confirmation_payload = {
            "schema_version": 1,
            "decision": "HUMAN_CONFIRMED",
            "field_name": field_name,
            "process_case_revision": (
                1 if expected_revision is None else expected_revision + 1
            ),
            "extraction_fingerprint": review.extraction_fingerprint,
            "evidence_id": evidence.evidence_id,
            "document_id": str(evidence.document_id),
            "document_sha256": document_sha256,
            "source_page": evidence.source_page,
            "evidence_source_start": evidence.source_start,
            "selection_start": source_start,
            "selection_end": source_end,
            "source_start": evidence.source_start + source_start,
            "source_end": evidence.source_start + source_end,
            "selected_value": selected_value,
        }
        snapshot = self.save_process_case.execute_with_source_confirmation(
            workspace_id,
            updated_data,
            expected_revision,
            confirmation={
                "artifact_id": field_name,
                "payload": confirmation_payload,
            },
            source_expectations=review.source_expectations,
        )
        if (
            type(snapshot) is not ProcessCaseSnapshot
            or snapshot.workspace_id != workspace_id
            or snapshot.data.as_dict() != updated_data.as_dict()
            or snapshot.revision is None
        ):
            raise RepositoryIntegrityError("confirmação processual divergente")
        if confirmation_payload["process_case_revision"] != snapshot.revision:
            raise RepositoryIntegrityError("revisão da proveniência divergente")
        return snapshot


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
        if artifact_kind in {
            _PROCESS_CASE_ARTIFACT_KIND,
            _PROCESS_METADATA_EXTRACTION_KIND,
            _PROCESS_METADATA_CONFIRMATION_KIND,
            _PROCESS_METADATA_SOURCE_CONFIRMATION_KIND,
            "OCR_PAGE_CACHE_V1",
        }:
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
