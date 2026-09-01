from __future__ import annotations

from dataclasses import dataclass

from ..field_mobile import (
    OfflineInspectionPackage,
    OfflineMediaManifest,
    offline_package_to_mapping as _offline_package_to_mapping,
)
from .models import PrivateContentId


def offline_package_to_mapping(package: OfflineInspectionPackage) -> dict[str, object]:
    """Expose serialization through the application boundary for transports."""
    return _offline_package_to_mapping(package)


@dataclass(frozen=True, slots=True)
class SyncAuthority:
    workspace_id: str
    inspection_id: str
    device_id: str
    device_session_id: str
    current_inspection_revision: int
    planning_revision: int
    source_revision: int
    last_device_sequence: int
    deleted_record_ids: tuple[str, ...]
    known_media_hashes: tuple[str, ...]
    media_authority_verified: bool = True


@dataclass(frozen=True, slots=True)
class SyncConflict:
    code: str
    message: str
    record_ids: tuple[str, ...] = ()
    requires_explicit_review: bool = True


@dataclass(frozen=True, slots=True)
class SyncDecision:
    accepted: bool
    conflicts: tuple[SyncConflict, ...]


def _record_ids(package: OfflineInspectionPackage) -> set[str]:
    return _session_record_ids(package.inspection_snapshot)


def _session_record_ids(session) -> set[str]:
    names = (
        (session.items, "item_id"), (session.observations, "observation_id"),
        (session.statements, "statement_id"), (session.measurements, "measurement_id"),
        (session.photos, "photo_id"), (session.videos, "video_id"),
        (session.sketches, "sketch_id"), (session.limitations, "limitation_id"),
        (session.measurement_series, "series_id"), (session.methods, "method_id"),
        (session.instruments, "instrument_id"), (session.instrument_statuses, "status_id"),
        (session.locations, "location_id"), (session.environmental_conditions, "condition_id"),
        (session.access_occurrences, "occurrence_id"), (session.missing_items, "missing_id"),
        (session.evidence_candidates, "candidate_id"), (session.reviews, "review_id"),
    )
    return {getattr(item, field) for collection, field in names for item in collection}


def adjudicate_offline_sync(
    package: OfflineInspectionPackage,
    authority: SyncAuthority,
) -> SyncDecision:
    if type(package) is not OfflineInspectionPackage or type(authority) is not SyncAuthority:
        raise TypeError("canonical offline package and sync authority required")
    conflicts: list[SyncConflict] = []
    if package.workspace_id != authority.workspace_id:
        conflicts.append(SyncConflict("WORKSPACE_MISMATCH", "Pacote pertence a outro workspace."))
    if package.inspection_id != authority.inspection_id:
        conflicts.append(SyncConflict("INSPECTION_MISMATCH", "Pacote pertence a outra vistoria."))
    if package.device_id != authority.device_id:
        conflicts.append(SyncConflict("DEVICE_MISMATCH", "Pacote pertence a outro dispositivo."))
    if package.device_session_id != authority.device_session_id:
        conflicts.append(SyncConflict("DEVICE_SESSION_MISMATCH", "A sessão do dispositivo não corresponde à autoridade de sync."))
    if package.planning_revision != authority.planning_revision:
        conflicts.append(SyncConflict("STALE_PLAN", "O plano de vistoria mudou após a aquisição offline."))
    if package.source_revision != authority.source_revision:
        conflicts.append(SyncConflict("CHANGED_SOURCE", "A fonte autoritativa mudou após a aquisição offline."))
    if package.device_sequence <= authority.last_device_sequence:
        conflicts.append(SyncConflict("DEVICE_REPLAY", "A sequência do dispositivo já foi processada."))
    if package.inspection_revision != authority.current_inspection_revision:
        conflicts.append(SyncConflict("SAME_ITEM_CONCURRENT_EDIT", "A vistoria canônica recebeu edição concorrente."))
    deleted = tuple(sorted(_record_ids(package).intersection(authority.deleted_record_ids)))
    if deleted:
        conflicts.append(SyncConflict("DELETED_ITEM", "O pacote altera registro removido no estado canônico.", deleted))
    duplicate_media = tuple(sorted(
        item.record_id for item in package.media_manifest
        if item.original_sha256 in authority.known_media_hashes
    ))
    if duplicate_media:
        conflicts.append(SyncConflict("DUPLICATE_MEDIA", "Mídia com os mesmos bytes já existe.", duplicate_media))
    if authority.media_authority_verified is not True:
        conflicts.append(SyncConflict("MEDIA_AUTHORITY_UNVERIFIED", "Os bytes originais de mídia não foram verificados."))
    return SyncDecision(not conflicts, tuple(conflicts))


@dataclass(frozen=True, slots=True)
class PrepareOfflineInspection:
    get_inspection: object
    get_private_content: object
    vault_for: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, device_id: str, device_session_id: str) -> OfflineInspectionPackage:
        record, snapshot = self.get_inspection.execute(workspace_id)
        if snapshot.upstream_stale:
            raise ValueError("stale inspection cannot be prepared for offline capture")
        media = []
        originals: dict[str, bytes] = {}
        for kind, records, identity in (
            ("PHOTO", snapshot.photos, "photo_id"),
            ("VIDEO", snapshot.videos, "video_id"),
            ("SKETCH", snapshot.sketches, "sketch_id"),
        ):
            for item in records:
                private = self.get_private_content.execute(workspace_id, PrivateContentId.parse(item.private_content_id))
                metadata = private.metadata
                if str(metadata.workspace_id) != str(workspace_id) or metadata.checksum_sha256 != item.original_sha256:
                    raise ValueError("canonical private media diverges from inspection authority")
                media.append(OfflineMediaManifest(
                    kind, getattr(item, identity), item.private_content_id, item.original_sha256,
                    metadata.byte_size, metadata.media_type or "application/octet-stream",
                ))
                originals[getattr(item, identity)] = private.content
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("offline package clock requires timezone")
        package = OfflineInspectionPackage(
            schema_version="1.0.0", package_id=f"OFFLINE-PACKAGE-{self.ids.new_uuid().hex.upper()}",
            package_revision=1, workspace_id=str(workspace_id), inspection_id=snapshot.session_id,
            inspection_revision=record.revision, planning_revision=snapshot.plan_snapshot.planning_revision,
            planning_digest=snapshot.plan_snapshot.planning_digest, source_revision=snapshot.source_revision,
            device_id=device_id, device_session_id=device_session_id, device_sequence=1,
            created_at=now.isoformat(), inspection_snapshot=snapshot, media_manifest=tuple(media),
        )
        vault = self.vault_for(workspace_id, device_id)
        vault.save(package)
        for record_id, original in originals.items():
            vault.save_media(package.package_id, record_id, original)
        return package


@dataclass(frozen=True, slots=True)
class SyncOfflineInspection:
    get_inspection: object
    save_inspection: object
    vault_for: object

    def execute(self, workspace_id, *, device_id: str, package_id: str):
        vault = self.vault_for(workspace_id, device_id)
        package = vault.load(package_id)
        replacement = vault.superseding_package_id(package_id)
        if replacement is not None:
            return SyncDecision(False, (SyncConflict(
                "SUPERSEDED_PACKAGE",
                "Uma revisão offline posterior substituiu este pacote.",
            ),)), None
        media_verified = vault.verify_media_authority(package_id)
        record, current = self.get_inspection.execute(workspace_id)
        if vault.has_accepted_sync(package):
            if current == package.inspection_snapshot:
                return SyncDecision(True, ()), record
            return SyncDecision(False, (SyncConflict(
                "DEVICE_REPLAY",
                "O pacote já foi sincronizado e o estado canônico avançou.",
            ),)), None
        sync_intent_revision = vault.sync_intent_expected_revision(package)
        if sync_intent_revision is not None and record.revision == sync_intent_revision + 1:
            if current != package.inspection_snapshot:
                return SyncDecision(False, (SyncConflict(
                    "INTERRUPTED_SYNC_DIVERGED",
                    "A vistoria canônica divergiu do pacote durante a recuperação do sync.",
                ),)), None
            vault.record_accepted_sync(package)
            return SyncDecision(True, ()), record
        current_media = {
            getattr(item, identity): item.original_sha256
            for records, identity in ((current.photos, "photo_id"), (current.videos, "video_id"), (current.sketches, "sketch_id"))
            for item in records
        }
        known_hashes = tuple(
            checksum for record_id, checksum in current_media.items()
            if not any(item.record_id == record_id and item.original_sha256 == checksum for item in package.media_manifest)
        )
        current_ids = _session_record_ids(current)
        deleted = tuple(sorted(_record_ids(package) - current_ids)) if record.revision != package.inspection_revision else ()
        authority = SyncAuthority(
            workspace_id=str(workspace_id), inspection_id=current.session_id,
            device_id=device_id, device_session_id=package.device_session_id,
            current_inspection_revision=record.revision,
            planning_revision=current.plan_snapshot.planning_revision, source_revision=current.source_revision,
            last_device_sequence=vault.last_accepted_sequence(package.device_session_id),
            deleted_record_ids=deleted, known_media_hashes=known_hashes,
            media_authority_verified=media_verified,
        )
        decision = adjudicate_offline_sync(package, authority)
        if not decision.accepted:
            return decision, None
        vault.begin_sync(package, record.revision)
        saved = self.save_inspection.execute(workspace_id, package.inspection_snapshot, record.revision)
        vault.record_accepted_sync(package)
        return decision, saved


@dataclass(frozen=True, slots=True)
class UpdateOfflineInspection:
    get_private_content: object
    vault_for: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, device_id: str, package_id: str, expected_package_revision: int, snapshot):
        vault = self.vault_for(workspace_id, device_id)
        previous = vault.load(package_id)
        if previous.package_revision != expected_package_revision:
            raise ValueError("offline package revision conflict")
        if snapshot.workspace_id != str(workspace_id) or snapshot.session_id != previous.inspection_id:
            raise ValueError("offline update workspace/inspection mismatch")
        manifests = []
        originals = {}
        for kind, records, identity in (("PHOTO", snapshot.photos, "photo_id"), ("VIDEO", snapshot.videos, "video_id"), ("SKETCH", snapshot.sketches, "sketch_id")):
            for item in records:
                private = self.get_private_content.execute(workspace_id, PrivateContentId.parse(item.private_content_id))
                if str(private.metadata.workspace_id) != str(workspace_id):
                    raise ValueError("offline update media belongs to another workspace")
                if private.metadata.checksum_sha256 != item.original_sha256:
                    raise ValueError("offline update media diverges from private authority")
                record_id = getattr(item, identity)
                manifests.append(OfflineMediaManifest(kind, record_id, item.private_content_id, item.original_sha256, private.metadata.byte_size, private.metadata.media_type or "application/octet-stream"))
                originals[record_id] = private.content
        now = self.clock.now()
        updated = OfflineInspectionPackage(
            previous.schema_version, f"OFFLINE-PACKAGE-{self.ids.new_uuid().hex.upper()}",
            previous.package_revision + 1, previous.workspace_id, previous.inspection_id,
            previous.inspection_revision, previous.planning_revision, previous.planning_digest,
            previous.source_revision, previous.device_id, previous.device_session_id,
            previous.device_sequence + 1, now.isoformat(), snapshot, tuple(manifests),
        )
        vault.save(updated)
        for record_id, original in originals.items():
            vault.save_media(updated.package_id, record_id, original)
        vault.mark_superseded(previous.package_id, updated.package_id)
        return updated


@dataclass(frozen=True, slots=True)
class GetOfflineInspection:
    vault_for: object

    def execute(self, workspace_id, *, device_id: str, package_id: str):
        return self.vault_for(workspace_id, device_id).load(package_id)


@dataclass(frozen=True, slots=True)
class ListPendingOfflineInspections:
    vault_for: object

    def execute(self, workspace_id, *, device_id: str):
        return self.vault_for(workspace_id, device_id).inventory_pending_packages()


@dataclass(frozen=True, slots=True)
class RevokeOfflineDevice:
    revoke_device: object

    def execute(self, workspace_id):
        del workspace_id
        self.revoke_device()


@dataclass(frozen=True, slots=True)
class ReplaceRevokedOfflineDevice:
    replace_device: object

    def execute(self, workspace_id, *, expected_device_id: str) -> str:
        del workspace_id
        return self.replace_device(expected_device_id)
