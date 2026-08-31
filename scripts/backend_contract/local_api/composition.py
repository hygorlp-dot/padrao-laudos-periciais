"""Composition root explícita da Local API e de sua persistência local."""

from __future__ import annotations

import os
import secrets
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from ..application.ports import Clock, IdGenerator, RepositoryError, RepositoryIntegrityError
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
    ImportInspectionPhoto,
    ListArtifactRevisions,
    ListWorkspaces,
    ListCaseDocuments,
    ListPrivateContents,
    OpenCaseDocument,
    OpenPrivateContentStream,
    SaveProcessCase,
    StorePrivateContent,
)
from ..infrastructure.private_filesystem import LocalPrivateContentStore, _validate_trusted_local_device
from ..infrastructure.pdf_text import LocalPdfTextExtractor
from ..infrastructure.rapid_ocr import RapidOcrLatinEngine
from ..infrastructure.sqlite import SQLiteApplicationStore
from .server import LocalApiServer, LocalApiServerStartError, LocalServerConfig
from .transport import LocalApi, LocalApiServices, _require_local_token
from ..application.case_analysis import GetCaseAnalysis, SaveCaseAnalysis
from ..application.pericial_planning import GetPericialPlanning, ReviewPericialPlanning, SavePericialPlanning
from ..application.vistoria import GetInspectionSession, SaveInspectionSession, StartInspectionSession
from ..application.technical_findings import GetTechnicalSnapshot, SaveTechnicalSnapshot, StartTechnicalSnapshot
from ..application.report_foundation import (
    GetExpertProfile,
    GetReportSnapshot,
    SaveExpertProfile,
    SaveReportSnapshot,
    StartReportSnapshot,
    ReviewReportSnapshot,
    AmendReportDraft,
)
from ..application.delivery_foundation import (
    DeliverDeliverySnapshot,
    AttachDeliveryPackageArtifact,
    FinalizeDeliverySnapshot,
    GetDeliverySnapshot,
    GetDeliveryHistory,
    ReissueDeliverySnapshot,
    RenderDeliveryPackage,
    ReviewDeliverySnapshot,
    SaveDeliverySnapshot,
    StartDeliverySnapshot,
    VerifyDeliveryPackage,
)
from ..application.budget_foundation import (
    AddFeeProposal,
    GetBudgetHistory,
    GetBudgetSnapshot,
    RecordCourtApproval,
    RecordExpense,
    RecordPayment,
    CloseBudgetSnapshot,
    SaveBudgetSnapshot,
    StartBudgetSnapshot,
)


class LocalApiStartupError(RuntimeError):
    """Falha sanitizada antes de a API local ficar disponível."""


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _UuidGenerator:
    def new_uuid(self) -> UUID:
        return uuid4()


def _path_has_recovery_quarantine(path: Path, *, path_is_file: bool) -> bool:
    absolute = path.absolute()
    start = absolute.parent if path_is_file else absolute
    candidates = {start}
    try:
        candidates.add(start.resolve(strict=False))
    except OSError as exc:
        raise RepositoryIntegrityError("local storage ancestry cannot be resolved") from exc
    return any((ancestor / "RECOVERY_NOT_PROMOTABLE").exists() for candidate in candidates for ancestor in (candidate, *candidate.parents))


def _assert_plain_single_link_database(path: Path) -> tuple[int, int] | None:
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        is_junction = getattr(component, "is_junction", lambda: False)
        if component.is_symlink() or is_junction():
            raise RepositoryIntegrityError("local database cannot use a link or reparse ancestry")
    if not absolute.exists():
        parent_identity = os.lstat(absolute.parent.resolve(strict=True))
        _validate_trusted_local_device(parent_identity)
        return None
    try:
        identity = os.stat(absolute, follow_symlinks=False)
    except OSError as exc:
        raise RepositoryIntegrityError("local database identity cannot be verified") from exc
    if identity.st_nlink != 1:
        raise RepositoryIntegrityError("local database must have exactly one filesystem link")
    _validate_trusted_local_device(identity)
    return identity.st_dev, identity.st_ino


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
    raw_database = str(database)
    if raw_database.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
        raise RepositoryIntegrityError("local database cannot use network or device paths")
    database_path = Path(database)
    if _path_has_recovery_quarantine(database_path, path_is_file=True) or (private_root is not None and _path_has_recovery_quarantine(Path(private_root), path_is_file=False)):
        raise RepositoryIntegrityError("recovery staging is quarantined and cannot become active")
    before_identity = _assert_plain_single_link_database(database_path)
    store = SQLiteApplicationStore(database)
    try:
        after_identity = _assert_plain_single_link_database(database_path)
        if before_identity is not None and after_identity != before_identity:
            raise RepositoryIntegrityError("local database identity changed during opening")
        if store.is_recovery_quarantined():
            raise RepositoryIntegrityError("recovery SQLite is quarantined and cannot become active")
    except BaseException:
        store.close()
        raise
    private_store = None
    if private_root is not None:
        try:
            private_store = LocalPrivateContentStore.open_or_provision(private_root)
            if private_store.is_recovery_quarantined():
                raise RepositoryIntegrityError("recovery private storage is quarantined and cannot become active")
        except Exception:
            if private_store is not None:
                private_store.close()
            store.close()
            raise
    import_case_document = None
    import_inspection_photo = None
    generic_store = None
    get_private_content = None
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
        get_private_content = GetPrivateContent(store.workspaces, private_store)
        import_case_document = ImportCaseDocumentWithMetadata(
            ImportCaseDocument(generic_store),
            open_case_document,
            LocalPdfTextExtractor(ocr_engine=RapidOcrLatinEngine()),
            store.revisions,
            local_clock,
            local_ids,
        )
        import_inspection_photo = ImportInspectionPhoto(generic_store)
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
    list_artifact_revisions = ListArtifactRevisions(store.revisions)
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
    get_technical_snapshot = GetTechnicalSnapshot(get_latest_artifact, get_case_analysis, get_inspection_session)
    save_technical_snapshot = SaveTechnicalSnapshot(
        store.revisions,
        get_case_analysis,
        get_inspection_session,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    get_expert_profile = GetExpertProfile(get_latest_artifact)
    save_expert_profile = SaveExpertProfile(
        store.revisions,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    get_report_snapshot = GetReportSnapshot(get_latest_artifact, get_case_analysis, get_inspection_session, get_technical_snapshot, get_expert_profile)
    save_report_snapshot = SaveReportSnapshot(
        store.revisions,
        get_case_analysis,
        get_inspection_session,
        get_technical_snapshot,
        get_expert_profile,
        get_latest_artifact,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    get_delivery_snapshot = None
    get_delivery_history = None
    save_delivery_snapshot = None
    start_delivery_snapshot = None
    review_delivery_snapshot = None
    render_delivery_package = None
    attach_delivery_artifact = None
    verify_delivery_package = None
    finalize_delivery_snapshot = None
    deliver_delivery_snapshot = None
    reissue_delivery_snapshot = None
    if private_store is not None and generic_store is not None and get_private_content is not None:
        authorities = (get_case_analysis, get_pericial_planning, get_inspection_session, get_technical_snapshot, get_report_snapshot)
        get_delivery_snapshot = GetDeliverySnapshot(get_latest_artifact, *authorities)
        get_delivery_history = GetDeliveryHistory(list_artifact_revisions)
        save_delivery_snapshot = SaveDeliverySnapshot(
            store.revisions,
            get_latest_artifact,
            *authorities,
            private_store.authority_guard,
            local_clock,
            local_ids,
        )
        start_delivery_snapshot = StartDeliverySnapshot(*authorities, get_private_content, save_delivery_snapshot, local_ids)
        review_delivery_snapshot = ReviewDeliverySnapshot(get_delivery_snapshot, save_delivery_snapshot, local_clock, local_ids)
        render_delivery_package = RenderDeliveryPackage(
            get_delivery_snapshot,
            get_report_snapshot,
            get_private_content,
            generic_store,
            save_delivery_snapshot,
            local_ids,
        )
        attach_delivery_artifact = AttachDeliveryPackageArtifact(get_delivery_snapshot, get_private_content, save_delivery_snapshot, local_ids)
        verify_delivery_package = VerifyDeliveryPackage(get_delivery_snapshot, get_private_content)
        finalize_delivery_snapshot = FinalizeDeliverySnapshot(verify_delivery_package, review_delivery_snapshot)
        deliver_delivery_snapshot = DeliverDeliverySnapshot(verify_delivery_package, review_delivery_snapshot)
        reissue_delivery_snapshot = ReissueDeliverySnapshot(
            get_delivery_snapshot,
            save_delivery_snapshot,
            *authorities,
            get_private_content,
            local_ids,
        )
    get_budget_snapshot = GetBudgetSnapshot(get_latest_artifact)
    save_budget_snapshot = SaveBudgetSnapshot(store.revisions, get_latest_artifact, local_clock, local_ids)
    services = LocalApiServices(
        create_workspace=CreateWorkspace(store.workspaces, local_clock, local_ids),
        get_workspace=GetWorkspace(store.workspaces),
        list_workspaces=ListWorkspaces(store.workspaces),
        append_artifact_revision=append_artifact_revision,
        get_latest_artifact=get_latest_artifact,
        get_artifact_revision=GetArtifactRevision(store.revisions),
        list_artifact_revisions=list_artifact_revisions,
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
        start_inspection_session=(StartInspectionSession(get_pericial_planning, save_inspection_session, local_clock, local_ids) if save_inspection_session is not None else None),
        save_technical_snapshot=save_technical_snapshot,
        get_technical_snapshot=get_technical_snapshot,
        start_technical_snapshot=StartTechnicalSnapshot(get_case_analysis, get_inspection_session, save_technical_snapshot, local_ids),
        save_expert_profile=save_expert_profile,
        get_expert_profile=get_expert_profile,
        save_report_snapshot=save_report_snapshot,
        get_report_snapshot=get_report_snapshot,
        start_report_snapshot=StartReportSnapshot(
            get_case_analysis,
            get_inspection_session,
            get_technical_snapshot,
            get_expert_profile,
            save_report_snapshot,
            local_ids,
        ),
        review_report_snapshot=ReviewReportSnapshot(get_report_snapshot, save_report_snapshot, local_clock, local_ids),
        amend_report_draft=AmendReportDraft(get_report_snapshot, save_report_snapshot, local_ids),
        store_delivery_template=generic_store,
        get_delivery_artifact=get_private_content,
        get_delivery_snapshot=get_delivery_snapshot,
        get_delivery_history=get_delivery_history,
        start_delivery_snapshot=start_delivery_snapshot,
        review_delivery_snapshot=review_delivery_snapshot,
        render_delivery_package=render_delivery_package,
        attach_delivery_artifact=attach_delivery_artifact,
        store_delivery_supporting_file=generic_store,
        verify_delivery_package=verify_delivery_package,
        finalize_delivery_snapshot=finalize_delivery_snapshot,
        deliver_delivery_snapshot=deliver_delivery_snapshot,
        reissue_delivery_snapshot=reissue_delivery_snapshot,
        save_budget_snapshot=save_budget_snapshot,
        get_budget_snapshot=get_budget_snapshot,
        get_budget_history=GetBudgetHistory(list_artifact_revisions),
        start_budget_snapshot=StartBudgetSnapshot(save_budget_snapshot, local_ids),
        add_fee_proposal=AddFeeProposal(get_budget_snapshot, save_budget_snapshot, local_clock, local_ids),
        record_court_approval=RecordCourtApproval(get_budget_snapshot, save_budget_snapshot, local_ids),
        record_budget_expense=RecordExpense(get_budget_snapshot, save_budget_snapshot, local_ids),
        record_received_payment=RecordPayment(get_budget_snapshot, save_budget_snapshot, local_ids),
        close_budget_snapshot=CloseBudgetSnapshot(get_budget_snapshot, save_budget_snapshot),
        get_process_metadata_review=get_process_metadata_review,
        confirm_process_metadata_source_span=confirm_process_metadata_source_span,
        import_case_document=import_case_document,
        list_case_documents=list_case_documents,
        read_case_document=read_case_document,
        import_inspection_photo=import_inspection_photo,
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
