"""Composition root explícita da Local API e de sua persistência local."""

from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import nullcontext
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from ..application.ai_assistant import AIAssistantStatus
from ..application.document_ingestion import CaseDocumentIngestion, DocumentDerivationQueue
from ..application.photo_library import CuratePhotoLibrary, GetPhotoLibrary, ReadPhotoThumbnail
from ..application.site_location import ConfirmSiteLocation, GetSiteLocation, ProposeSiteLocation
from ..application.property_record import GetPropertyRecord, GetPropertyProposals, SavePropertyRecord
from ..application.case_document_texts import CaseDocumentTexts
from ..application.legal_editorial_preflight import GetReportPreflight
from ..application.installation_settings import CreateWorkspaceWithSettings, GenerateTestDocument, InstallationSettings, WorkspaceSettings, validate_installation_template
from ..infrastructure.installation_store import SQLiteInstallationStore, installation_database_path
from ..application.process_participants import DecideProcessParticipants, GetProcessParticipants, ParticipantProposals
from ..application.process_number_classification import GetProcessNumberClassification
from ..application.ports import Clock, IdGenerator, RepositoryError, RepositoryIntegrityError
from ..application.workspace_recovery import (
    AbandonWorkspaceRecovery,
    recolher_stagings_orfaos,
    reconstruir_sessoes_recuperacao,
    DiscardWorkspaceRecovery,
    ExportWorkspaceBackup,
    InspectWorkspaceBackup,
    ListWorkspaceRecoveries,
    PromoteWorkspaceRecovery,
    StageWorkspaceRecovery,
    WorkspaceRecoverySessions,
)
from ..infrastructure.productization import (
    abrir_staging_quarentenado,
    CreateWorkspaceBackup,
    RecoveryStaging,
    RestoreWorkspaceBackup,
    VerifyWorkspaceBackup,
)
from ..application.content_roles import PrivateContentRoles
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
    GetPjeIntake,
    GetWorkspace,
    ImportCaseDocument,
    ImportCaseDocumentWithMetadata,
    ImportInspectionPhoto,
    ListArtifactRevisions,
    ListWorkspaces,
    ListCaseDocuments,
    ListCaseDocumentsWithPjeInventory,
    ListPrivateContents,
    OpenCaseDocument,
    OpenPrivateContentStream,
    SaveProcessCase,
    SetPjeDocumentAvailability,
    StoreDeliverySupportingFile,
    StorePrivateContent,
)
from ..infrastructure.private_filesystem import (
    LocalPrivateContentStore,
    _validate_trusted_local_device,
    provision_local_storage_directory,
)
from ..infrastructure.pdf_text import LocalPdfTextExtractor
from ..infrastructure.office_pdf import LocalOfficePdfConverter
from ..infrastructure.rapid_ocr import RapidOcrLatinEngine
from ..infrastructure.sqlite import SQLiteApplicationStore
from ..infrastructure.field_mobile import DeviceOfflineVaultRegistry
from .server import LocalApiServer, LocalApiServerStartError, LocalServerConfig
from .transport import LocalApi, LocalApiServices, _require_local_token
from ..application.case_analysis import AddCaseAnalysisItem, GetCaseAnalysis, ReviewCaseAnalysisItem, SaveCaseAnalysis, StartCaseAnalysis
from ..application.pericial_planning import GetPericialPlanning, ReviewPericialPlanning, SavePericialPlanning, StartPericialPlanning, StartSuccessorPericialPlanning
from ..application.vistoria import GetInspectionSession, SaveInspectionSession, StartInspectionSession, ConfirmInspectionVisit, InspectionReuseCandidates, ReuseInspectionRecords, StartSuccessorInspectionSession
from ..application.case_intake import GetCaseIntake, AcceptCaseQuestions, ConfirmDocumentInventory
from ..application.field_mobile import GetOfflineInspection, ListPendingOfflineInspections, PrepareOfflineInspection, ReplaceRevokedOfflineDevice, RevokeOfflineDevice, SyncOfflineInspection, UpdateOfflineInspection
from ..application.technical_findings import (
    AddEvidenceProposal,
    GetTechnicalSnapshot,
    ProposeTechnicalFinding,
    ReviewTechnicalEvidence,
    ReviewTechnicalFinding,
    ResolveTechnicalProfessional,
    SaveTechnicalSnapshot,
    SelectTechnicalMethod,
    StartTechnicalSnapshot,
    StartSuccessorTechnicalSnapshot,
)
from ..application.construction_defect_analysis import (
    GetConstructionDefectAnalysis,
    ReviewPathology,
    SaveConstructionDefectAnalysis,
    StartConstructionDefectAnalysis,
    StartSuccessorConstructionDefectAnalysis,
)
from ..application.report_foundation import (
    StartReportVersion,
    GetReportProcess,
    GetExpertProfile,
    GetReportSnapshot,
    SaveExpertProfile,
    SaveReportSnapshot,
    StartReportSnapshot,
    ReviewReportSnapshot,
    AmendReportDraft,
    ExportReportAuditTrail,
    ListReportSources,
)
from ..application.delivery_foundation import (
    StoreDefaultDeliveryTemplate,
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
    AddBudgetItem,
    AddFeeProposal,
    AddProfessionalEffortEstimate,
    AddThirdPartyEstimate,
    AddTravelEstimate,
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


#: Falhas controladas de compor o armazenamento local e o listener: mensagens
#: sem caminho nem conteúdo, que a entrada do produto pode mostrar ao usuário
#: em vez de um traceback (#283).
STARTUP_FAILURES = (RepositoryError, LocalApiStartupError)


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _UuidGenerator:
    def new_uuid(self) -> UUID:
        return uuid4()


def _sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _provision_recovery_staging(base: Path):
    """Fábrica de raízes de staging sob uma base IRMÃ da base viva.

    `RecoveryStaging.create` exige que a raiz não exista e que o pai resolva sem
    redirecionamento; a base é criada sob demanda, com permissão restrita, e o
    marcador de quarentena fica sempre DENTRO da raiz filha — nunca num ancestral
    do armazenamento ativo.
    """

    def create(root: Path):
        return RecoveryStaging.create(root)

    return create


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


#: Quanto `POST /materials` espera a derivacao antes de responder "aceito,
#: processando" (#266). Precisa ficar abaixo do timeout de transporte do bridge
#: (30 s), que nao pode mais decidir o destino de uma fonte ja aceita.
DEFAULT_INGESTION_GRACE_SECONDS = 10.0

@dataclass(slots=True)
class LocalApiRuntime:
    """Dono explícito do servidor e da sessão SQLite."""

    server: LocalApiServer
    token: str = field(repr=False)
    _store: SQLiteApplicationStore = field(repr=False)
    _private_store: LocalPrivateContentStore | None = field(default=None, repr=False)
    _recovery_sessions: object | None = field(default=None, repr=False)
    # #266: o executor das derivacoes pertence ao runtime, nao a conexao.
    _derivations: object | None = field(default=None, repr=False)
    # #270: configurações da instalação, em arquivo próprio fora das perícias.
    _installation_store: object | None = field(default=None, repr=False)
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

    @property
    def recovery_mutation_supported(self) -> bool:
        return self.server.recovery_mutation_supported

    def start(self) -> tuple[str, int]:
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("runtime local fechado")
            try:
                if self._derivations is not None:
                    self._derivations.start()
                return self.server.start()
            except LocalApiServerStartError as exc:
                self._closed = True
                if self._derivations is not None:
                    self._derivations.close()
                try:
                    if self._private_store is not None:
                        self._private_store.close()
                    if self._installation_store is not None:
                        self._installation_store.close()
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
                    # Antes dos stores: nenhuma derivação começa depois daqui e
                    # nenhuma grava depois do fechamento (#266).
                    if self._derivations is not None:
                        self._derivations.close()
                    # Sessões de recuperação não sobrevivem ao processo: descartar
                    # aqui garante que nenhum staging fique com handle aberto.
                    if self._recovery_sessions is not None:
                        self._recovery_sessions.close_all()
                finally:
                    try:
                        if self._private_store is not None:
                            self._private_store.close()
                    finally:
                        try:
                            if self._installation_store is not None:
                                self._installation_store.close()
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
    pje_intake: object | None = None,
    construction_defect_analysis: object | None = None,
    ingestion_grace_seconds: float = DEFAULT_INGESTION_GRACE_SECONDS,
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
    # O primeiro uso parte de uma raiz local sem o diretório de dados (#283):
    # ele é provisionado aqui, depois das recusas de rede, dispositivo e
    # quarentena, e com as mesmas garantias de ancestralidade e dispositivo
    # que a abertura do banco exige logo abaixo.
    provision_local_storage_directory(database_path.parent)
    before_identity = _assert_plain_single_link_database(database_path)
    store = SQLiteApplicationStore(database)
    try:
        after_identity = _assert_plain_single_link_database(database_path)
        if before_identity is not None and after_identity != before_identity:
            raise RepositoryIntegrityError("local database identity changed during opening")
        store.assert_active_application_identity()
    except BaseException:
        store.close()
        raise
    try:
        installation_store = SQLiteInstallationStore(installation_database_path(database_path))
    except RepositoryError:
        # Arquivo da instalação ilegível: a Central fica indisponível (503) e a
        # criação de perícia é recusada, mas as perícias existentes abrem com o
        # snapshot que cada uma capturou. Os dados do caso não dependem dele.
        installation_store = None
    except BaseException:
        store.close()
        raise
    private_store = None
    offline_registry = None
    if private_root is not None:
        try:
            private_store = LocalPrivateContentStore.open_or_provision(private_root)
            offline_registry = DeviceOfflineVaultRegistry(
                database_path.parent / f".{database_path.name}.field-mobile"
            )
            if private_store.is_recovery_quarantined():
                raise RepositoryIntegrityError("recovery private storage is quarantined and cannot become active")
        except Exception:
            if private_store is not None:
                private_store.close()
            installation_store.close()
            store.close()
            raise
    import_case_document = None
    derivation_queue = None
    case_document_ingestion = None
    import_inspection_photo = None
    generic_store = None
    store_delivery_supporting_file = None
    get_private_content = None
    list_case_documents = None
    case_analysis_documents = None
    get_pje_intake = None
    set_pje_document_availability = None
    read_case_document = None
    get_process_metadata_review = None
    get_process_case = GetProcessCase(store.workspaces, store.revisions)
    # Sem a porta injetada nao existe deteccao PJe nesta composicao. Construir os
    # servicos assim mesmo faria a rota responder 404 ("este processo nao tem PJe"),
    # que e indistinguivel de "esta instalacao nao le PJe". Deixando-os ausentes, o
    # transporte responde 503 PJE_INTAKE_UNAVAILABLE e a degradacao fica visivel.
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
        list_case_documents = ListCaseDocuments(
            ListPrivateContents(store.workspaces, private_store), PrivateContentRoles(store.revisions)
        )
        store_delivery_supporting_file = StoreDeliverySupportingFile(generic_store, store.revisions, local_clock, local_ids)
        import_case_document = ImportCaseDocumentWithMetadata(
            ImportCaseDocument(generic_store),
            open_case_document,
            LocalPdfTextExtractor(ocr_engine=RapidOcrLatinEngine()),
            store.revisions,
            local_clock,
            local_ids,
            list_case_documents,
            pje_intake,
            private_store.authority_guard,
        )
        derivation_queue = DocumentDerivationQueue(import_case_document.derive)
        case_document_ingestion = CaseDocumentIngestion(
            import_case_document, derivation_queue, list_case_documents,
            grace_seconds=ingestion_grace_seconds,
        )
        import_inspection_photo = ImportInspectionPhoto(generic_store)
        case_analysis_documents = ListCaseDocumentsWithPjeInventory(list_case_documents, store.revisions)
        # Depende de `list_case_documents`, que so existe com armazenamento
        # privado: o inventario e endereçado por fonte, entao e preciso saber
        # quais fontes o workspace tem.
        get_pje_intake = (
            GetPjeIntake(store.workspaces, store.revisions, list_case_documents)
            if pje_intake is not None else None
        )
        set_pje_document_availability = (
            SetPjeDocumentAvailability(get_pje_intake, store.revisions, local_clock, local_ids)
            if get_pje_intake is not None else None
        )
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
    installation_settings = InstallationSettings(installation_store, local_clock, local_ids, validate_installation_template) if installation_store is not None else None
    workspace_settings = (
        WorkspaceSettings(
            installation_settings, store.revisions, get_latest_artifact, generic_store,
            private_store.authority_guard if private_store is not None else nullcontext, local_clock, local_ids,
        )
        if generic_store is not None else None
    )
    list_artifact_revisions = ListArtifactRevisions(store.revisions)
    get_case_analysis = GetCaseAnalysis(get_latest_artifact, case_analysis_documents)
    save_pericial_planning = SavePericialPlanning(
        store.revisions,
        get_latest_artifact,
        get_case_analysis,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    get_pericial_planning = GetPericialPlanning(get_latest_artifact, get_case_analysis)
    start_pericial_planning = StartPericialPlanning(get_case_analysis, save_pericial_planning, local_ids)
    get_inspection_session = GetInspectionSession(get_latest_artifact, get_pericial_planning)
    save_inspection_session = (
        SaveInspectionSession(
            store.revisions,
            get_latest_artifact,
            get_pericial_planning,
            GetPrivateContent(store.workspaces, private_store),
            private_store.authority_guard,
            local_clock,
            local_ids,
        )
        if private_store is not None
        else None
    )
    start_inspection_session = (StartInspectionSession(get_pericial_planning, save_inspection_session, local_clock, local_ids) if save_inspection_session is not None else None)
    inspection_reuse_candidates = (InspectionReuseCandidates(get_inspection_session, store.revisions, get_pericial_planning) if save_inspection_session is not None else None)
    prepare_offline_inspection = (
        PrepareOfflineInspection(get_inspection_session, get_private_content, offline_registry.vault_for, local_clock, local_ids)
        if offline_registry is not None and get_private_content is not None else None
    )
    sync_offline_inspection = (
        SyncOfflineInspection(get_inspection_session, save_inspection_session, offline_registry.vault_for)
        if offline_registry is not None and save_inspection_session is not None else None
    )
    update_offline_inspection = (
        UpdateOfflineInspection(get_private_content, offline_registry.vault_for, local_clock, local_ids)
        if offline_registry is not None and get_private_content is not None else None
    )
    get_technical_snapshot = GetTechnicalSnapshot(get_latest_artifact, get_case_analysis, get_inspection_session)
    save_technical_snapshot = SaveTechnicalSnapshot(
        store.revisions,
        get_latest_artifact,
        get_case_analysis,
        get_inspection_session,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    resolve_technical_professional = ResolveTechnicalProfessional(get_inspection_session)
    get_construction_defect_analysis = GetConstructionDefectAnalysis(
        get_latest_artifact,
        get_process_case,
        get_case_analysis,
        get_pericial_planning,
        get_inspection_session,
    )
    save_construction_defect_analysis = SaveConstructionDefectAnalysis(
        store.revisions,
        get_latest_artifact,
        get_process_case,
        get_case_analysis,
        get_pericial_planning,
        get_inspection_session,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    start_construction_defect_analysis = (
        StartConstructionDefectAnalysis(
            get_latest_artifact,
            get_process_case,
            get_case_analysis,
            get_pericial_planning,
            get_inspection_session,
            construction_defect_analysis,
            save_construction_defect_analysis,
            local_ids,
        )
        if construction_defect_analysis is not None
        else None
    )
    start_successor_construction_defect_analysis = (
        StartSuccessorConstructionDefectAnalysis(
            get_construction_defect_analysis, start_construction_defect_analysis, save_construction_defect_analysis,
        )
        if start_construction_defect_analysis is not None
        else None
    )
    review_pathology = ReviewPathology(
        get_construction_defect_analysis,
        save_construction_defect_analysis,
        get_inspection_session,
        local_clock,
        local_ids,
    )
    get_expert_profile = GetExpertProfile(get_latest_artifact)
    save_case_intake = SaveCaseAnalysis(store.revisions, get_latest_artifact, local_clock, local_ids, case_analysis_documents, private_store.authority_guard if private_store is not None else nullcontext)
    get_case_intake = GetCaseIntake(get_case_analysis, read_case_document, LocalPdfTextExtractor(ocr_engine=RapidOcrLatinEngine())) if read_case_document is not None else None
    save_expert_profile = SaveExpertProfile(
        store.revisions,
        get_latest_artifact,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    get_site_location = GetSiteLocation(get_latest_artifact)
    get_property_record = GetPropertyRecord(
        get_latest_artifact,
        ListCaseDocumentsWithPjeInventory(list_case_documents, store.revisions) if list_case_documents is not None else None,
    )
    case_document_texts = (
        CaseDocumentTexts(
            ListCaseDocumentsWithPjeInventory(list_case_documents, store.revisions), read_case_document,
            LocalPdfTextExtractor(ocr_engine=RapidOcrLatinEngine()), store.revisions, local_clock, local_ids,
        )
        if list_case_documents is not None and read_case_document is not None else None
    )
    get_property_proposals = GetPropertyProposals(case_document_texts) if case_document_texts is not None else None
    get_process_number_classification = (
        GetProcessNumberClassification(case_document_texts) if case_document_texts is not None else None
    )
    get_process_participants = GetProcessParticipants(
        get_latest_artifact, get_process_case, case_document_texts,
        ParticipantProposals(case_document_texts) if case_document_texts is not None else None,
    )
    decide_process_participants = DecideProcessParticipants(
        get_process_participants, store.revisions,
        private_store.authority_guard if private_store is not None else nullcontext, local_clock, local_ids,
    )
    save_property_record = SavePropertyRecord(
        get_property_record, store.revisions, get_expert_profile, get_property_proposals,
        private_store.authority_guard if private_store is not None else nullcontext, local_clock, local_ids,
    )
    get_photo_library = GetPhotoLibrary(get_latest_artifact)
    propose_site_location = ProposeSiteLocation(
        store.revisions,
        get_latest_artifact,
        private_store.authority_guard if private_store is not None else nullcontext,
        local_clock,
        local_ids,
    )
    get_report_process = GetReportProcess(get_latest_artifact)
    get_report_snapshot = GetReportSnapshot(
        get_latest_artifact,
        get_case_analysis,
        get_inspection_session,
        get_technical_snapshot,
        get_expert_profile,
        get_construction_defect_analysis,
        get_site_location=get_site_location,
        get_property_record=get_property_record, get_process_record=get_report_process,
    )
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
        get_construction_defect_analysis,
        get_site_location=get_site_location,
        get_property_record=get_property_record, get_process_record=get_report_process,
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
            # The Phase C purpose-specific renderer, with its own validated local
            # render root; nothing about the process it may create is configurable.
            LocalOfficePdfConverter(),
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
    # Backup e recuperação alcançáveis pelo produto (#183). A raiz de staging é
    # IRMÃ da base viva, nunca ancestral: o marcador RECOVERY_NOT_PROMOTABLE de
    # um staging jamais pode quarentenar o armazenamento ativo.
    recovery_sessions = WorkspaceRecoverySessions()
    # Corpo grande é derramado AQUI, não no temporário do sistema: o pacote de
    # recuperação carrega todo o conteúdo privado em claro, e %TEMP% é varrido,
    # indexado e sincronizado por ferramentas de terceiros.
    # Corpo grande é derramado AQUI, não no temporário do sistema. O pacote de
    # recuperação carrega todo o conteúdo privado em claro, e %TEMP% fica FORA
    # da área que o usuário escolheu para os dados do caso — é varrido,
    # indexado e limpo por ferramentas de terceiros. Esta pasta não é um
    # esconderijo melhor: é a MESMA pasta onde o banco e o armazenamento
    # privado já vivem, então não acrescenta classe de exposição nenhuma.
    spool_root = database_path.parent / f".{database_path.name}.spool"
    spool_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Queda dura (BSOD, falta de energia) pode deixar derramamento para trás:
    # no Windows o `O_TEMPORARY` só some com o processo. Recolhe na reabertura,
    # antes de servir — nada aqui é autoridade de coisa alguma.
    for residuo in spool_root.iterdir():
        try:
            if residuo.is_file():
                residuo.unlink()
        except OSError:
            pass
    if server_config.spool_dir is None:
        server_config = replace(server_config, spool_dir=str(spool_root))

    recovery_staging_root = database_path.parent / f".{database_path.name}.recovery"
    # Reabertura do produto: recolhe stagings órfãos ANTES de servir. Preserva
    # tudo que ainda for retomável — ver `recolher_stagings_orfaos`.
    recolher_stagings_orfaos(recovery_staging_root)
    reconstruir_sessoes_recuperacao(
        recovery_staging_root,
        recovery_sessions,
        abrir_staging_quarentenado,
    )
    # `assert_backup_ready` é a autoridade canônica de prontidão: recusa o backup
    # enquanto houver vistoria offline pendente de sincronização. Ligar um no-op
    # aqui faria o produto entregar, em silêncio, um pacote sem o trabalho de
    # campo — exatamente o que essa autoridade existe para impedir. Sem registry
    # offline não há como PROVAR prontidão, então falha fechada.
    if offline_registry is None:
        def _assert_backup_ready(_workspace_id):
            raise RepositoryIntegrityError(
                "backup readiness authority is unavailable"
            )
    else:
        def _assert_backup_ready(workspace_id, _registry=offline_registry):
            try:
                _registry.assert_workspace_backup_ready(workspace_id)
            except PermissionError:
                # Dispositivo de campo revogado: o cofre local é inacessível, logo
                # NÃO há trabalho pendente sincronizável para proteger. A autoridade
                # existe para impedir backup que omita trabalho recuperável — não
                # para negar backup justamente quando o perito perdeu o dispositivo
                # e mais precisa de um. Trabalho pendente REAL continua bloqueando.
                return
    export_workspace_backup = ExportWorkspaceBackup(
        CreateWorkspaceBackup(
            store.workspaces,
            store.revisions,
            private_store,
            local_clock,
            _assert_backup_ready,
        ),
        store.workspaces,
        server_config.max_document_body_bytes,
    )
    inspect_workspace_backup = InspectWorkspaceBackup(VerifyWorkspaceBackup(), _sha256_hex)
    stage_workspace_recovery = StageWorkspaceRecovery(
        VerifyWorkspaceBackup(),
        _provision_recovery_staging(recovery_staging_root),
        RestoreWorkspaceBackup,
        recovery_sessions,
        recovery_staging_root,
        _sha256_hex,
        abrir_staging_quarentenado,
        store.workspaces,
    )
    promote_workspace_recovery = PromoteWorkspaceRecovery(
        recovery_sessions, store.workspaces, store.revisions, private_store
    )
    discard_workspace_recovery = DiscardWorkspaceRecovery(recovery_sessions, store.workspaces)
    abandon_workspace_recovery = AbandonWorkspaceRecovery(discard_workspace_recovery)
    services = LocalApiServices(
        create_workspace=CreateWorkspaceWithSettings(CreateWorkspace(store.workspaces, local_clock, local_ids), workspace_settings),
        installation_settings=installation_settings,
        workspace_settings=workspace_settings,
        generate_test_document=GenerateTestDocument(installation_settings) if installation_settings is not None else None,
        get_report_preflight=GetReportPreflight(get_report_snapshot, workspace_settings),
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
            get_latest_artifact,
            local_clock,
            local_ids,
            case_analysis_documents,
            private_store.authority_guard if private_store is not None else nullcontext,
        ),
        get_case_analysis=get_case_analysis,
        get_case_intake=get_case_intake,
        accept_case_questions=AcceptCaseQuestions(get_case_intake, save_case_intake, local_ids) if get_case_intake is not None else None,
        confirm_document_inventory=ConfirmDocumentInventory(get_case_analysis, save_case_intake, get_expert_profile, local_clock),
        start_case_analysis=StartCaseAnalysis(
            case_analysis_documents,
            SaveCaseAnalysis(
                store.revisions, get_latest_artifact, local_clock, local_ids, case_analysis_documents,
                private_store.authority_guard if private_store is not None else nullcontext,
            ),
            local_ids,
        ),
        add_case_analysis_item=AddCaseAnalysisItem(
            get_case_analysis,
            SaveCaseAnalysis(
                store.revisions, get_latest_artifact, local_clock, local_ids, case_analysis_documents,
                private_store.authority_guard if private_store is not None else nullcontext,
            ),
            local_ids,
        ),
        review_case_analysis_item=ReviewCaseAnalysisItem(
            get_case_analysis,
            SaveCaseAnalysis(
                store.revisions, get_latest_artifact, local_clock, local_ids, case_analysis_documents,
                private_store.authority_guard if private_store is not None else nullcontext,
            ),
            local_clock,
            local_ids,
        ),
        save_pericial_planning=save_pericial_planning,
        get_pericial_planning=get_pericial_planning,
        start_pericial_planning=start_pericial_planning,
        start_successor_pericial_planning=StartSuccessorPericialPlanning(get_pericial_planning, start_pericial_planning, save_pericial_planning),
        review_pericial_planning=ReviewPericialPlanning(
            get_pericial_planning,
            save_pericial_planning,
            local_clock,
            local_ids,
        ),
        save_inspection_session=save_inspection_session,
        get_inspection_session=get_inspection_session,
        start_inspection_session=start_inspection_session,
        start_successor_inspection_session=(StartSuccessorInspectionSession(get_inspection_session, start_inspection_session, save_inspection_session) if save_inspection_session is not None else None),
        inspection_reuse_candidates=inspection_reuse_candidates,
        reuse_inspection_records=(ReuseInspectionRecords(inspection_reuse_candidates, save_inspection_session, get_expert_profile, local_clock, local_ids) if save_inspection_session is not None else None),
        confirm_inspection_visit=(ConfirmInspectionVisit(get_inspection_session, save_inspection_session, get_expert_profile, local_clock) if save_inspection_session is not None else None),
        prepare_offline_inspection=prepare_offline_inspection,
        sync_offline_inspection=sync_offline_inspection,
        update_offline_inspection=update_offline_inspection,
        get_offline_inspection=(GetOfflineInspection(offline_registry.vault_for) if offline_registry is not None else None),
        list_offline_inspections=(ListPendingOfflineInspections(offline_registry.vault_for) if offline_registry is not None else None),
        revoke_offline_device=(RevokeOfflineDevice(offline_registry.revoke_device) if offline_registry is not None else None),
        replace_offline_device=(ReplaceRevokedOfflineDevice(offline_registry.replace_revoked_device) if offline_registry is not None else None),
        offline_device_id=(offline_registry.device_id if offline_registry is not None else None),
        offline_device_authority=offline_registry,
        save_technical_snapshot=save_technical_snapshot,
        get_technical_snapshot=get_technical_snapshot,
        start_technical_snapshot=StartTechnicalSnapshot(get_case_analysis, get_inspection_session, save_technical_snapshot, local_ids),
        start_successor_technical_snapshot=StartSuccessorTechnicalSnapshot(get_technical_snapshot, StartTechnicalSnapshot(get_case_analysis, get_inspection_session, save_technical_snapshot, local_ids), save_technical_snapshot),
        add_technical_evidence_proposal=AddEvidenceProposal(get_technical_snapshot, save_technical_snapshot, local_ids),
        review_technical_evidence=ReviewTechnicalEvidence(get_technical_snapshot, save_technical_snapshot, local_clock, local_ids, resolve_technical_professional),
        select_technical_method=SelectTechnicalMethod(get_technical_snapshot, save_technical_snapshot, local_ids, resolve_technical_professional),
        propose_technical_finding=ProposeTechnicalFinding(get_technical_snapshot, save_technical_snapshot, local_ids),
        review_technical_finding=ReviewTechnicalFinding(get_technical_snapshot, save_technical_snapshot, local_clock, local_ids, resolve_technical_professional),
        get_construction_defect_analysis=get_construction_defect_analysis,
        start_construction_defect_analysis=start_construction_defect_analysis,
        start_successor_construction_defect_analysis=start_successor_construction_defect_analysis,
        review_pathology=review_pathology,
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
            get_construction_defect_analysis,
            get_property_record=get_property_record, get_process_record=get_report_process,
            get_workspace_settings=workspace_settings,
        ),
        review_report_snapshot=ReviewReportSnapshot(get_report_snapshot, save_report_snapshot, local_clock, local_ids),
        start_report_version=StartReportVersion(
            get_latest_artifact, get_case_analysis, get_inspection_session, get_technical_snapshot, get_expert_profile,
            save_report_snapshot, local_ids, get_construction_defect_analysis, get_site_location,
            get_property_record=get_property_record, get_process_record=get_report_process,
        ),
        amend_report_draft=AmendReportDraft(get_report_snapshot, save_report_snapshot, local_ids, get_case_analysis, get_technical_snapshot, get_construction_defect_analysis, get_site_location, get_photo_library, get_property_record=get_property_record, get_process_record=get_report_process),
        list_report_sources=ListReportSources(get_case_analysis, get_inspection_session, get_technical_snapshot, get_construction_defect_analysis),
        export_report_audit_trail=ExportReportAuditTrail(get_report_snapshot),
        store_delivery_template=generic_store,
        store_default_delivery_template=StoreDefaultDeliveryTemplate(get_report_snapshot, generic_store, workspace_settings, get_private_content),
        get_site_location=get_site_location,
        get_photo_library=get_photo_library,
        ai_assistant_status=AIAssistantStatus(),
        get_property_record=get_property_record,
        save_property_record=save_property_record,
        get_property_proposals=get_property_proposals,
        get_process_participants=get_process_participants,
        get_process_number_classification=get_process_number_classification,
        decide_process_participants=decide_process_participants,
        curate_photo_library=CuratePhotoLibrary(
            store.revisions, get_latest_artifact, get_private_content,
            private_store.authority_guard if private_store is not None else nullcontext, local_clock, local_ids,
        ) if get_private_content is not None else None,
        read_photo_thumbnail=ReadPhotoThumbnail(get_photo_library, get_private_content) if get_private_content is not None else None,
        propose_site_location=propose_site_location,
        confirm_site_location=ConfirmSiteLocation(get_site_location, get_latest_artifact, propose_site_location),
        get_delivery_artifact=get_private_content,
        get_delivery_snapshot=get_delivery_snapshot,
        get_delivery_history=get_delivery_history,
        start_delivery_snapshot=start_delivery_snapshot,
        review_delivery_snapshot=review_delivery_snapshot,
        render_delivery_package=render_delivery_package,
        attach_delivery_artifact=attach_delivery_artifact,
        store_delivery_supporting_file=store_delivery_supporting_file,
        verify_delivery_package=verify_delivery_package,
        finalize_delivery_snapshot=finalize_delivery_snapshot,
        deliver_delivery_snapshot=deliver_delivery_snapshot,
        reissue_delivery_snapshot=reissue_delivery_snapshot,
        save_budget_snapshot=save_budget_snapshot,
        get_budget_snapshot=get_budget_snapshot,
        get_budget_history=GetBudgetHistory(list_artifact_revisions),
        start_budget_snapshot=StartBudgetSnapshot(save_budget_snapshot, local_ids),
        add_budget_item=AddBudgetItem(get_budget_snapshot, save_budget_snapshot, local_ids),
        add_professional_effort_estimate=AddProfessionalEffortEstimate(get_budget_snapshot, save_budget_snapshot, local_ids),
        add_travel_estimate=AddTravelEstimate(get_budget_snapshot, save_budget_snapshot, local_ids),
        add_third_party_estimate=AddThirdPartyEstimate(get_budget_snapshot, save_budget_snapshot, local_ids),
        add_fee_proposal=AddFeeProposal(get_budget_snapshot, save_budget_snapshot, local_clock, local_ids),
        record_court_approval=RecordCourtApproval(get_budget_snapshot, save_budget_snapshot, local_ids),
        record_budget_expense=RecordExpense(get_budget_snapshot, save_budget_snapshot, local_ids),
        record_received_payment=RecordPayment(get_budget_snapshot, save_budget_snapshot, local_ids),
        close_budget_snapshot=CloseBudgetSnapshot(get_budget_snapshot, save_budget_snapshot),
        get_process_metadata_review=get_process_metadata_review,
        confirm_process_metadata_source_span=confirm_process_metadata_source_span,
        import_case_document=import_case_document,
        case_document_ingestion=case_document_ingestion,
        list_case_documents=list_case_documents,
        get_pje_intake=get_pje_intake,
        set_pje_document_availability=set_pje_document_availability,
        export_workspace_backup=export_workspace_backup,
        inspect_workspace_backup=inspect_workspace_backup,
        stage_workspace_recovery=stage_workspace_recovery,
        list_workspace_recoveries=ListWorkspaceRecoveries(recovery_sessions),
        promote_workspace_recovery=promote_workspace_recovery,
        discard_workspace_recovery=discard_workspace_recovery,
        abandon_workspace_recovery=abandon_workspace_recovery,
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
        _recovery_sessions=recovery_sessions,
        _derivations=derivation_queue,
        _installation_store=installation_store,
    )
