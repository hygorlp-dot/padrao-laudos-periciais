from __future__ import annotations

from dataclasses import dataclass

from ..field_mobile import OfflineInspectionPackage


@dataclass(frozen=True, slots=True)
class SyncAuthority:
    workspace_id: str
    inspection_id: str
    current_inspection_revision: int
    planning_revision: int
    source_revision: int
    last_device_sequence: int
    deleted_record_ids: tuple[str, ...]
    known_media_hashes: tuple[str, ...]


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
    session = package.inspection_snapshot
    names = (
        (session.items, "item_id"), (session.observations, "observation_id"),
        (session.statements, "statement_id"), (session.measurements, "measurement_id"),
        (session.photos, "photo_id"), (session.videos, "video_id"),
        (session.sketches, "sketch_id"), (session.limitations, "limitation_id"),
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
    return SyncDecision(not conflicts, tuple(conflicts))
