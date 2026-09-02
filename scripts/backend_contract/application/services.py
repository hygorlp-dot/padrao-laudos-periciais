"""Casos de uso explícitos e finos da Application Layer local."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from .content import (
    DOCUMENT_IO_CHUNK_BYTES,
    MAX_DOCUMENT_BYTES,
    OpenPrivateContent,
    SeekableContent,
    as_seekable_content,
)
from .ocr_cache import RevisionOcrPageCache
from .pje_party_table import parse_pje_party_table
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
_PJE_INTAKE_ARTIFACT_KIND = "PJE_INTAKE_V1"
_PJE_INTAKE_ARTIFACT_ID = "PJE-INTAKE"




def validate_pje_intake_payload(value: object) -> dict:
    required = {"schema_version", "workspace_id", "storage_content_id", "source_sha256", "instance_label", "documents", "party_rows"}
    if type(value) is not dict or set(value) != required or value.get("schema_version") != "1.0.0":
        raise ValueError("PJe intake payload is invalid")
    WorkspaceId.parse(value["workspace_id"]); PrivateContentId.parse(value["storage_content_id"])
    if type(value["source_sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]) is None:
        raise ValueError("PJe intake source hash is invalid")
    if type(value["instance_label"]) is not str or not value["instance_label"].strip():
        raise ValueError("PJe intake judicial unit is invalid")
    if type(value["documents"]) is not list or not value["documents"] or type(value["party_rows"]) is not list:
        raise ValueError("PJe intake collections are invalid")
    document_fields = {"document_id", "id_pje", "title", "raw_type", "normalized_type", "page_start", "page_end", "available"}
    ids = []
    for row in value["documents"]:
        if type(row) is not dict or set(row) != document_fields or type(row["available"]) is not bool:
            raise ValueError("PJe logical document is invalid")
        if any(type(row[name]) is not str or not row[name].strip() for name in ("document_id", "id_pje", "title", "raw_type", "normalized_type")):
            raise ValueError("PJe logical document identity is invalid")
        if any(type(row[name]) is not int or row[name] < 1 for name in ("page_start", "page_end")) or row["page_end"] < row["page_start"]:
            raise ValueError("PJe logical document page span is invalid")
        ids.append(row["document_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("PJe logical document identities are duplicated")
    party_fields = {"name", "role", "pole", "representative_name", "representative_role", "page", "occurrence", "document_id"}
    for row in value["party_rows"]:
        if type(row) is not dict or set(row) != party_fields or row["pole"] not in {"ACTIVE", "PASSIVE"} or type(row["page"]) is not int or row["page"] < 1:
            raise ValueError("PJe party row is invalid")
        if any(type(row[name]) is not str or not row[name].strip() for name in party_fields - {"page", "pole", "document_id"}):
            raise ValueError("PJe party row text is invalid")
        # None = pagina fora de qualquer documento logico (capa/indice).
        if row["document_id"] is not None and (row["document_id"] not in set(ids)):
            raise ValueError("PJe party row names an unknown logical document")
    canonical_payload_json(value)
    return value


def _metadata_extraction_fingerprint(value: object) -> str:
    encoded = canonical_payload_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _case_document_filename(value: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise InvalidCaseDocument("nome de arquivo PDF inválido")
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\")):
        raise InvalidCaseDocument("nome de arquivo PDF não pode expor path absoluto")
    return value


def _inspection_photo_filename(value: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError("inspection photo filename is invalid")
    if re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith(("/", "\\\\")):
        raise ValueError("inspection photo filename cannot expose an absolute path")
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
class ImportInspectionPhoto:
    contents: StorePrivateContent

    def execute(self, *, workspace_id: WorkspaceId, original_filename: str, content: bytes | SeekableContent, media_type: str) -> PrivateContentMetadata:
        if media_type not in {"image/jpeg", "image/png"}:
            raise ValueError("only JPEG or PNG inspection photos are accepted")
        source = as_seekable_content(content)
        prefix = source.prefix(16)
        if media_type == "image/jpeg" and not prefix.startswith(b"\xff\xd8\xff"):
            raise ValueError("inspection photo bytes do not match JPEG")
        if media_type == "image/png" and not prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("inspection photo bytes do not match PNG")
        expected_format = "JPEG" if media_type == "image/jpeg" else "PNG"
        try:
            source.rewind()
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source.stream) as image:
                    if image.format != expected_format:
                        raise ValueError("inspection photo decoded format diverges")
                    image.verify()
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ValueError("inspection photo is truncated or corrupt") from exc
        finally:
            source.rewind()
        return self.contents.execute(
            workspace_id=workspace_id, original_filename=_inspection_photo_filename(original_filename),
            content=content, media_type=media_type, origin=PrivateContentOrigin.USER_IMPORT,
        )


def _already_imported_in_workspace(existing_documents, workspace_id, source):
    """Return the material already holding these exact bytes in THIS workspace.

    Byte identity is scoped to the workspace on purpose: the same hash appearing
    in another workspace is a different source with its own authority, and must
    never resolve to a shared domain identity.
    """
    if existing_documents is None:
        return None
    digest = source.sha256()
    for item in existing_documents.execute(workspace_id):
        if item.checksum_sha256 == digest:
            return item
    return None


def _carry_forward_availability_decisions(previous_record, inventory: dict) -> dict:
    """Keep the professional's availability decisions across a re-ingest of the source.

    ``available`` is the one field in this artifact that is a professional
    decision rather than a source-derived fact, and a fresh parse always proposes
    ``True``. Letting the re-parse win would make a re-import silently return a
    document the perito deliberately excluded, inverting
    PROFESSIONAL_OVERRIDE > ENGINE_DECISION > SOURCE_VALUE. Source facts (ids,
    spans, types) still refresh; only the decision is preserved, and only for
    logical documents that still exist in the new inventory.
    """
    if previous_record is None:
        return inventory
    try:
        previous = validate_pje_intake_payload(thaw_payload(previous_record.payload))
    except (ValueError, TypeError) as exc:
        raise RepositoryIntegrityError("stored PJe inventory is invalid") from exc
    if previous.get("workspace_id") != inventory.get("workspace_id"):
        raise RepositoryIntegrityError("stored PJe inventory belongs to another workspace")
    decided = {
        row["document_id"]: row["available"]
        for row in previous["documents"]
        if row["available"] is False
    }
    if not decided:
        return inventory
    return {
        **inventory,
        "documents": [
            {**row, "available": decided.get(row["document_id"], row["available"])}
            for row in inventory["documents"]
        ],
    }


def _pje_inventory_payload(record, persisted, text: PdfTextResult, pje_intake) -> dict | None:
    """Build the canonical workspace inventory from an injected PJe intake port.

    The backend must not know the PJe parser: `config/architecture-policy-v1.json`
    gives BACKEND no allowed dependencies, and reading a PJe export belongs to the
    ingestion component. The port is asked only for the logical document list; the
    party rows are still derived here, from text this layer already extracted.

    The port answers with a discriminated status so the failure taxonomy crosses
    the boundary without sharing exception types: ``NOT_PJE`` (this is not, or is
    not readable as, a PJe export -- an ordinary import, never a failure) and
    ``INCONSISTENT`` (it *is* a PJe export and it disagrees with itself, which
    stays fail-closed).
    """
    if pje_intake is None:
        return None
    with tempfile.TemporaryDirectory(prefix="pje-intake-") as temporary:
        pdf = Path(temporary) / "source.pdf"
        persisted.stream.seek(0)
        with pdf.open("wb") as sink:
            while block := persisted.stream.read(DOCUMENT_IO_CHUNK_BYTES):
                sink.write(block)
        persisted.stream.seek(0)
        outcome = pje_intake.logical_inventory(pdf)
    if type(outcome) is not dict or outcome.get("status") not in {"OK", "NOT_PJE", "INCONSISTENT"}:
        raise RepositoryIntegrityError("PJe intake port returned an unknown result")
    if outcome["status"] == "NOT_PJE":
        return None
    if outcome["status"] == "INCONSISTENT":
        raise RepositoryIntegrityError(str(outcome.get("detail", "PJe source is inconsistent")))
    documents = [{**row, "available": True} for row in outcome["documents"]]

    def _containing_document(page_number: int) -> str | None:
        """Documento logico cujo intervalo de paginas contem esta pagina."""
        for document in documents:
            if document["page_start"] <= page_number <= document["page_end"]:
                return document["document_id"]
        return None

    party_rows = []
    for page in text.pages:
        parsed = parse_pje_party_table(page.text)
        for row in parsed.rows:
            party_rows.append({
                "name": row.name, "role": row.role, "pole": row.pole.value,
                "representative_name": row.representative_name,
                "representative_role": row.representative_role,
                "page": page.number, "occurrence": row.source_line,
                # Sem este vinculo a proveniencia da parte nao tem como nomear o
                # documento que de fato a contem, e a exclusao profissional de um
                # documento nao tem como alcancar o que ele afirma. `None` quando
                # a pagina nao pertence a nenhum documento logico (capa/indice).
                "document_id": _containing_document(page.number),
            })
    return {
        "schema_version": "1.0.0", "workspace_id": str(record.workspace_id),
        "storage_content_id": str(record.content_id), "source_sha256": record.checksum_sha256,
        # A unidade judicial vem do proprio inventario: ler o manifesto aqui
        # exigiria conhecer o parser, que e exatamente o que a porta evita.
        "instance_label": outcome.get("instance_label") or "NÃO CLASSIFICADA",
        "documents": documents,
        "party_rows": party_rows,
    }


@dataclass(frozen=True, slots=True)
class ImportCaseDocumentWithMetadata:
    documents: object
    document_streams: object
    extractor: object
    revisions: ArtifactRevisionRepository
    clock: Clock
    ids: IdGenerator
    existing_documents: object | None = None
    pje_intake: object | None = None

    def execute(
        self,
        *,
        workspace_id: WorkspaceId,
        original_filename: str,
        content: bytes | SeekableContent,
        media_type: str,
    ) -> PrivateContentMetadata:
        source = as_seekable_content(content)
        already = _already_imported_in_workspace(self.existing_documents, workspace_id, source)
        if already is not None:
            # Reimportar exatamente os mesmos bytes no mesmo workspace e
            # idempotente: uma segunda autoridade fisica sobre o mesmo conteudo
            # duplicaria a fonte e apagaria as decisoes ja tomadas sobre ela.
            # O escopo e o workspace -- o mesmo hash noutro workspace continua
            # sendo outra fonte, sem identidade compartilhada.
            return already
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
            pje_inventory = _pje_inventory_payload(record, persisted, text, self.pje_intake)
        self.revisions.append(
            workspace_id=record.workspace_id,
            artifact_kind=_PROCESS_METADATA_EXTRACTION_KIND,
            artifact_id=str(record.content_id),
            revision_id=str(_generated_uuid(self.ids)),
            created_at=_generated_timestamp(self.clock),
            payload=document_metadata_payload(extracted),
        )
        if pje_inventory is not None:
            pje_inventory = _carry_forward_availability_decisions(
                self.revisions.latest(
                    record.workspace_id, _PJE_INTAKE_ARTIFACT_KIND, _PJE_INTAKE_ARTIFACT_ID
                ),
                pje_inventory,
            )
            validate_pje_intake_payload(pje_inventory)
            self.revisions.append(
                workspace_id=record.workspace_id, artifact_kind=_PJE_INTAKE_ARTIFACT_KIND,
                artifact_id=_PJE_INTAKE_ARTIFACT_ID, revision_id=str(_generated_uuid(self.ids)),
                created_at=_generated_timestamp(self.clock), payload=pje_inventory,
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
            if record.media_type == "application/pdf" and record.origin is PrivateContentOrigin.USER_IMPORT
        )


@dataclass(frozen=True, slots=True)
class PjeIndexedCaseDocument:
    content_id: PrivateContentId
    checksum_sha256: str
    original_filename: str
    pje_inventory: dict | None


@dataclass(frozen=True, slots=True)
class ListCaseDocumentsWithPjeInventory:
    documents: ListCaseDocuments
    revisions: ArtifactRevisionRepository

    def execute(self, workspace_id: WorkspaceId) -> tuple[PjeIndexedCaseDocument, ...]:
        records = self.documents.execute(workspace_id)
        inventory_record = self.revisions.latest(workspace_id, _PJE_INTAKE_ARTIFACT_KIND, _PJE_INTAKE_ARTIFACT_ID)
        inventory = validate_pje_intake_payload(thaw_payload(inventory_record.payload)) if inventory_record is not None else None
        if inventory is not None:
            # O inventario esta vinculado a UMA autoridade fisica. Exigir que ela
            # seja o unico material do workspace confundia "inventario divergente"
            # com "o workspace tem mais de um documento", tornando um segundo
            # material legitimo um 500 permanente e irreparavel.
            if inventory.get("workspace_id") != str(workspace_id):
                raise RepositoryIntegrityError("PJe inventory belongs to another workspace")
            bound = next(
                (item for item in records if str(item.content_id) == inventory.get("storage_content_id")),
                None,
            )
            if bound is None or inventory.get("source_sha256") != bound.checksum_sha256:
                raise RepositoryIntegrityError("PJe inventory diverges from private source authority")
        return tuple(PjeIndexedCaseDocument(
            item.content_id, item.checksum_sha256, item.original_filename,
            inventory if inventory is not None and str(item.content_id) == inventory["storage_content_id"] else None,
        ) for item in records)


@dataclass(frozen=True, slots=True)
class GetPjeIntake:
    workspaces: WorkspaceRepository
    revisions: ArtifactRevisionRepository

    def execute(self, workspace_id: WorkspaceId):
        workspace_id = _require_workspace(self.workspaces, workspace_id)
        record = self.revisions.latest(workspace_id, _PJE_INTAKE_ARTIFACT_KIND, _PJE_INTAKE_ARTIFACT_ID)
        if record is None:
            raise ArtifactRevisionNotFound("PJe intake not found")
        payload = validate_pje_intake_payload(thaw_payload(record.payload))
        # O inventario declara o workspace a que pertence. Servi-lo sem conferir
        # deixaria um payload cross-linked (por restauracao, por exemplo) ser
        # lido como se fosse deste workspace.
        if payload["workspace_id"] != str(workspace_id):
            raise RepositoryIntegrityError("stored PJe inventory belongs to another workspace")
        return record, payload


@dataclass(frozen=True, slots=True)
class SetPjeDocumentAvailability:
    get_intake: GetPjeIntake
    revisions: ArtifactRevisionRepository
    clock: Clock
    ids: IdGenerator

    def execute(self, workspace_id: WorkspaceId, *, document_id: str, available: bool, expected_revision: int):
        if type(document_id) is not str or not document_id.strip() or type(available) is not bool or type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("PJe availability request is invalid")
        current, payload = self.get_intake.execute(workspace_id)
        if current.revision != expected_revision:
            raise RepositoryConflict("expected PJe intake revision is not latest")
        matched = False
        documents = []
        for row in payload["documents"]:
            updated = dict(row)
            if row["document_id"] == document_id:
                updated["available"] = available; matched = True
            documents.append(updated)
        if not matched:
            raise ValueError("PJe logical document is unknown")
        amended = validate_pje_intake_payload({**payload, "documents": documents})
        record = self.revisions.append_if_latest(
            # O alvo da escrita e o workspace da requisicao autenticada, nunca um
            # identificador lido do proprio dado armazenado: derivar o destino do
            # payload permite que um inventario cross-linked redirecione a
            # gravacao para outro workspace.
            workspace_id=workspace_id, artifact_kind=_PJE_INTAKE_ARTIFACT_KIND,
            artifact_id=_PJE_INTAKE_ARTIFACT_ID, revision_id=str(_generated_uuid(self.ids)),
            created_at=_generated_timestamp(self.clock), payload=amended, expected_revision=expected_revision,
        )
        return record, amended


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
        from .artifact_ownership import USER_DEFINED_ARTIFACT_KINDS

        workspace_id = _workspace_key(workspace_id)
        artifact_kind = _artifact_key(artifact_kind, "artifact_kind")
        artifact_id = _artifact_key(artifact_id, "artifact_id")
        if artifact_kind not in USER_DEFINED_ARTIFACT_KINDS:
            raise ValueError("identidade de artefato reservada: generic artifact mutation is disabled; use the dedicated application service")
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
