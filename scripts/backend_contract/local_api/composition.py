"""Composition root explícita da Local API e de sua persistência local."""

from __future__ import annotations

import secrets
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from ..application.ports import Clock, IdGenerator, RepositoryError
from ..application.services import (
    AppendArtifactRevision,
    CreateWorkspace,
    ConfirmProcessMetadata,
    ConfirmProcessMetadataSourceSpan,
    GetArtifactRevision,
    GetLatestArtifact,
    GetPrivateContent,
    GetProcessCase,
    GetProcessMetadataReview,
    GetWorkspace,
    ImportCaseDocument,
    ImportCaseDocumentWithMetadata,
    ListArtifactRevisions,
    ListWorkspaces,
    ListCaseDocuments,
    ListPrivateContents,
    OpenCaseDocument,
    OpenPrivateContentStream,
    SaveProcessCase,
    StorePrivateContent,
)
from ..infrastructure.private_filesystem import LocalPrivateContentStore
from ..infrastructure.pdf_text import LocalPdfTextExtractor
from ..infrastructure.rapid_ocr import RapidOcrLatinEngine
from ..infrastructure.sqlite import SQLiteApplicationStore
from .server import LocalApiServer, LocalApiServerStartError, LocalServerConfig
from .transport import LocalApi, LocalApiServices, _require_local_token
from ..application.case_analysis import GetCaseAnalysis, SaveCaseAnalysis
from ..application.pericial_planning import GetPericialPlanning, ReviewPericialPlanning, SavePericialPlanning
from ..application.vistoria import GetInspectionSession, SaveInspectionSession


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
    _private_store: LocalPrivateContentStore | None = field(default=None, repr=False)
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
                    if self._private_store is not None:
                        self._private_store.close()
                finally:
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
                try:
                    if self._private_store is not None:
                        self._private_store.close()
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
    private_root: str | Path | None = None,
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
    private_store = None
    if private_root is not None:
        try:
            private_store = LocalPrivateContentStore.open_or_provision(private_root)
        except Exception:
            store.close()
            raise
    import_case_document = None
    list_case_documents = None
    read_case_document = None
    get_process_metadata_review = None
    get_process_case = GetProcessCase(store.workspaces, store.revisions)
    if private_store is not None:
        open_case_document = OpenCaseDocument(OpenPrivateContentStream(store.workspaces, private_store))
        generic_store = StorePrivateContent(
            store.workspaces,
            private_store,
            local_clock,
            local_ids,
            server_config.max_document_body_bytes,
        )
        import_case_document = ImportCaseDocumentWithMetadata(
            ImportCaseDocument(generic_store),
            open_case_document,
            LocalPdfTextExtractor(ocr_engine=RapidOcrLatinEngine()),
            store.revisions,
            local_clock,
            local_ids,
        )
        list_case_documents = ListCaseDocuments(ListPrivateContents(store.workspaces, private_store))
        read_case_document = open_case_document
        get_process_metadata_review = GetProcessMetadataReview(
            store.workspaces,
            list_case_documents,
            store.revisions,
            get_process_case,
        )
    save_process_case = SaveProcessCase(store.workspaces, store.revisions, local_clock, local_ids)
    confirm_process_metadata_source_span = (
        ConfirmProcessMetadataSourceSpan(
            get_process_case,
            save_process_case,
            get_process_metadata_review,
        )
        if get_process_metadata_review is not None
        else None
    )
    append_artifact_revision = AppendArtifactRevision(store.revisions, local_clock, local_ids)
    get_latest_artifact = GetLatestArtifact(store.revisions)
    get_case_analysis = GetCaseAnalysis(get_latest_artifact, list_case_documents)
    save_pericial_planning = SavePericialPlanning(
        store.revisions,
        get_latest_artifact,
        get_case_analysis,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    get_pericial_planning = GetPericialPlanning(get_latest_artifact, get_case_analysis)
    get_inspection_session = GetInspectionSession(get_latest_artifact, get_pericial_planning)
    save_inspection_session = (
        SaveInspectionSession(
            store.revisions,
            get_pericial_planning,
            GetPrivateContent(store.workspaces, private_store),
            private_store.authority_guard,
            local_clock,
            local_ids,
        )
        if private_store is not None
        else None
    )
    services = LocalApiServices(
        create_workspace=CreateWorkspace(store.workspaces, local_clock, local_ids),
        get_workspace=GetWorkspace(store.workspaces),
        list_workspaces=ListWorkspaces(store.workspaces),
        append_artifact_revision=append_artifact_revision,
        get_latest_artifact=get_latest_artifact,
        get_artifact_revision=GetArtifactRevision(store.revisions),
        list_artifact_revisions=ListArtifactRevisions(store.revisions),
        get_process_case=get_process_case,
        save_process_case=(
            ConfirmProcessMetadata(
                save_process_case,
                get_process_metadata_review,
                store.revisions,
                local_clock,
                local_ids,
            )
            if get_process_metadata_review is not None
            else save_process_case
        ),
        save_case_analysis=SaveCaseAnalysis(
            store.revisions,
            local_clock,
            local_ids,
            list_case_documents,
            private_store.authority_guard if private_store is not None else nullcontext,
        ),
        get_case_analysis=get_case_analysis,
        save_pericial_planning=save_pericial_planning,
        get_pericial_planning=get_pericial_planning,
        review_pericial_planning=ReviewPericialPlanning(
            get_pericial_planning,
            save_pericial_planning,
            local_clock,
            local_ids,
        ),
        save_inspection_session=save_inspection_session,
        get_inspection_session=get_inspection_session,
        get_process_metadata_review=get_process_metadata_review,
        confirm_process_metadata_source_span=confirm_process_metadata_source_span,
        import_case_document=import_case_document,
        list_case_documents=list_case_documents,
        read_case_document=read_case_document,
    )
    api = LocalApi(
        services,
        token=local_token,
        max_body_bytes=server_config.max_body_bytes,
        max_document_body_bytes=server_config.max_document_body_bytes,
    )
    try:
        server = LocalApiServer(api, server_config)
    except OSError as exc:
        try:
            if private_store is not None:
                private_store.close()
        finally:
            store.close()
        raise LocalApiStartupError("servidor local indisponível") from exc
    return LocalApiRuntime(
        server=server,
        token=local_token,
        _store=store,
        _private_store=private_store,
    )
