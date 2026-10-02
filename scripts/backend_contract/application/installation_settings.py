"""Central de Configurações: autoridade de instalação e snapshot por perícia (#270).

A instalação guarda padrões com histórico append-only. Uma perícia recebe, na
criação, um snapshot efetivo desses padrões (com cópia exata dos ativos), e é
esse snapshot que o laudo usa. Mudar o padrão depois não muda nenhuma perícia;
atualizar uma perícia é um comando explícito, com diferença mostrada antes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
from typing import Any

from ..installation_settings import (
    DEFAULT_SETTING_ID,
    IMAGE_MEDIA_TYPES,
    IMAGE_ROLES,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_TEMPLATE_BYTES,
    TEMPLATE_MEDIA_TYPES,
    WORKSPACE_SETTINGS_ID,
    WORKSPACE_SETTINGS_KIND,
    AssetRole,
    InstallationAssetRecord,
    SettingKind,
    SnapshotAsset,
    TemplateMode,
    WorkspaceSettingsSnapshot,
    asset_record_from_mapping,
    branding_from_mapping,
    default_payload,
    legal_editorial_from_mapping,
    presentation_from_mapping,
    template_selection_from_mapping,
    to_mapping,
    validated_setting_payload,
    workspace_settings_from_mapping,
    workspace_settings_to_mapping,
)
from ..report_foundation import (
    EXPERT_PROFILE_ARTIFACT_ID,
    EXPERT_PROFILE_ARTIFACT_KIND,
    editorial_profile_from_mapping,
    expert_profile_from_mapping,
    expert_profile_to_mapping,
)
from .content_roles import PRIVATE_CONTENT_ROLE_KIND, PrivateContentRole, private_content_role_payload
from .models import PrivateContentOrigin, thaw_payload
from .ports import ArtifactRevisionNotFound, RepositoryConflict, RepositoryIntegrityError

SETTING_KINDS = tuple(kind for kind in SettingKind if kind is not SettingKind.INSTALLATION_ASSET)


class InstallationAssetRejected(ValueError):
    """Arquivo recusado com motivo compreensível (formato, tamanho, dimensão)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _record_dto(record) -> dict[str, Any]:
    return {"revision": record.revision, "revision_id": record.revision_id, "created_at": record.created_at, "checksum_sha256": record.checksum_sha256, "payload": thaw_payload(record.payload) if not isinstance(record.payload, dict) else record.payload}


def inspect_image(content: bytes, media_type: str) -> tuple[int, int]:
    """Prova que os bytes são a imagem declarada, legível e dentro dos limites."""
    from PIL import Image, UnidentifiedImageError

    expected = IMAGE_MEDIA_TYPES.get(media_type)
    if expected is None:
        raise InstallationAssetRejected("FORMAT_NOT_SUPPORTED")
    if len(content) > MAX_IMAGE_BYTES:
        raise InstallationAssetRejected("FILE_TOO_LARGE")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != expected:
                raise InstallationAssetRejected("FORMAT_MISMATCH")
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS or width < 16 or height < 16:
                raise InstallationAssetRejected("DIMENSIONS_OUT_OF_RANGE")
            if getattr(image, "is_animated", False):
                raise InstallationAssetRejected("ANIMATED_IMAGE")
            if image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                raise InstallationAssetRejected("COLOR_MODE_NOT_SUPPORTED")
            image.verify()
        with Image.open(BytesIO(content)) as image:
            image.load()
    except InstallationAssetRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise InstallationAssetRejected("IMAGE_UNREADABLE") from exc
    return width, height


@dataclass(frozen=True, slots=True)
class InstallationSettings:
    store: object
    clock: object
    ids: object
    validate_template: object

    def _now(self) -> str:
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("installation clock requires timezone")
        return now.isoformat()

    def latest(self, kind: SettingKind, setting_id: str = DEFAULT_SETTING_ID):
        return self.store.latest(kind.value, setting_id)

    def asset_record(self, role: AssetRole) -> tuple[object | None, InstallationAssetRecord | None]:
        record = self.store.latest(SettingKind.INSTALLATION_ASSET.value, role.value)
        if record is None or record.payload.get("removed") is True:
            return record, None
        return record, asset_record_from_mapping(dict(record.payload))

    def overview(self) -> dict[str, Any]:
        settings = {}
        for kind in SETTING_KINDS:
            record = self.latest(kind)
            settings[kind.value] = (
                {"configured": True, **_record_dto(record)} if record is not None
                else {"configured": False, "revision": None, "revision_id": None, "created_at": None, "checksum_sha256": None, "payload": default_payload(kind)}
            )
        assets = {}
        for role in AssetRole:
            record, asset = self.asset_record(role)
            assets[role.value] = {"revision": record.revision if record else None, "asset": to_mapping(asset) if asset else None}
        return {"settings": settings, "assets": assets, "readiness": self.readiness(settings, assets)}

    @staticmethod
    def readiness(settings: dict, assets: dict) -> dict[str, Any]:
        profile = settings[SettingKind.EXPERT_PROFILE_DEFAULT.value]
        selection = settings[SettingKind.DEFAULT_TEMPLATE_SELECTION.value]["payload"]
        branding_configured = settings[SettingKind.BRANDING_PROFILE.value]["configured"] or assets[AssetRole.PRIMARY_LOGO.value]["asset"] is not None
        return {
            "expert_profile": "CONFIGURED" if profile["configured"] else "MISSING",
            "branding": "CONFIGURED" if branding_configured else "PRODUCT_DEFAULT",
            "document": "CONFIGURED" if settings[SettingKind.DOCUMENT_PRESENTATION_PROFILE.value]["configured"] else "PRODUCT_DEFAULT",
            "editorial": "CUSTOM" if settings[SettingKind.EDITORIAL_PROFILE_DEFAULT.value]["payload"]["profile_id"] == "CUSTOM" else "PRESET",
            "legal_editorial": "CNJ_TRF5",
            "template": selection["mode"],
        }

    def save(self, kind: SettingKind, payload: object, expected_revision: int | None):
        if kind is SettingKind.INSTALLATION_ASSET:
            raise ValueError("assets are stored through the asset command")
        canonical = validated_setting_payload(kind, DEFAULT_SETTING_ID, payload)
        if kind is SettingKind.DEFAULT_TEMPLATE_SELECTION:
            selection = template_selection_from_mapping(canonical)
            if selection.mode is TemplateMode.CUSTOM:
                _, template = self.asset_record(AssetRole.DEFAULT_WORD_TEMPLATE)
                if template is None or template.sha256 != selection.template_sha256:
                    raise ValueError("the selected template is not the stored custom template")
        return self.store.append_if_latest(
            setting_kind=kind.value, setting_id=DEFAULT_SETTING_ID, revision_id=str(self.ids.new_uuid()),
            created_at=self._now(), payload=canonical, expected_revision=expected_revision,
        )

    def history(self, kind: SettingKind, setting_id: str = DEFAULT_SETTING_ID):
        return self.store.history(kind.value, setting_id)

    def restore(self, kind: SettingKind, revision: int, expected_revision: int, setting_id: str = DEFAULT_SETTING_ID):
        """Restaurar grava uma revisão nova com o conteúdo antigo; nada é apagado."""
        target = next((item for item in self.history(kind, setting_id) if item.revision == revision), None)
        if target is None:
            raise ValueError("revision to restore does not exist")
        payload = validated_setting_payload(kind, setting_id, dict(target.payload))
        if kind is SettingKind.INSTALLATION_ASSET and payload.get("removed") is not True and self.store.get_asset(payload["sha256"]) is None:
            raise RepositoryIntegrityError("the restored asset bytes are unavailable")
        return self.store.append_if_latest(
            setting_kind=kind.value, setting_id=setting_id, revision_id=str(self.ids.new_uuid()),
            created_at=self._now(), payload=payload, expected_revision=expected_revision,
        )

    def upload_asset(self, role: AssetRole, *, filename: str, media_type: str, content: bytes, expected_revision: int | None):
        if type(content) is not bytes or not content:
            raise InstallationAssetRejected("EMPTY_FILE")
        if role in IMAGE_ROLES:
            width, height = inspect_image(content, media_type)
        else:
            if media_type not in TEMPLATE_MEDIA_TYPES:
                raise InstallationAssetRejected("FORMAT_NOT_SUPPORTED")
            if len(content) > MAX_TEMPLATE_BYTES:
                raise InstallationAssetRejected("FILE_TOO_LARGE")
            try:
                self.validate_template(content, TEMPLATE_MEDIA_TYPES[media_type])
            except ValueError as exc:
                raise InstallationAssetRejected("TEMPLATE_INVALID") from exc
            width = height = None
        stored = self.store.put_asset(content, media_type)
        record = InstallationAssetRecord(
            "ASSET-" + self.ids.new_uuid().hex.upper(), role, filename, media_type, stored.byte_size, stored.sha256, width, height,
        )
        return self.store.append_if_latest(
            setting_kind=SettingKind.INSTALLATION_ASSET.value, setting_id=role.value, revision_id=str(self.ids.new_uuid()),
            created_at=self._now(), payload=to_mapping(record), expected_revision=expected_revision,
        )

    def remove_asset(self, role: AssetRole, expected_revision: int):
        if role is AssetRole.DEFAULT_WORD_TEMPLATE:
            selection = self.latest(SettingKind.DEFAULT_TEMPLATE_SELECTION)
            if selection is not None and selection.payload.get("mode") == TemplateMode.CUSTOM.value:
                raise ValueError("choose the product template before removing the custom template")
        return self.store.append_if_latest(
            setting_kind=SettingKind.INSTALLATION_ASSET.value, setting_id=role.value, revision_id=str(self.ids.new_uuid()),
            created_at=self._now(), payload={"role": role.value, "removed": True}, expected_revision=expected_revision,
        )

    def asset_content(self, role: AssetRole):
        _, record = self.asset_record(role)
        if record is None:
            raise ArtifactRevisionNotFound("installation asset is not configured")
        asset = self.store.get_asset(record.sha256)
        if asset is None or asset.media_type != record.media_type or asset.byte_size != record.byte_size:
            raise RepositoryIntegrityError("installation asset bytes are unavailable")
        return record, asset.content

    def effective(self) -> dict[str, Any]:
        """Os padrões vigentes, cada um com a revisão de origem (ou padrão do produto)."""
        sources, values = {}, {}
        for kind in SETTING_KINDS:
            record = self.latest(kind)
            sources[kind.value] = {"revision": record.revision, "checksum_sha256": record.checksum_sha256} if record else None
            values[kind] = dict(record.payload) if record else default_payload(kind)
        return {"sources": sources, "values": values}


@dataclass(frozen=True, slots=True)
class WorkspaceSettings:
    """Snapshot por perícia: o laudo usa este, nunca o padrão global vigente."""
    settings: InstallationSettings
    revisions: object
    get_latest_revision: object
    store_private_content: object
    authority_guard: object
    clock: object
    ids: object

    def current(self, workspace_id):
        try:
            record = self.get_latest_revision.execute(workspace_id, WORKSPACE_SETTINGS_KIND, WORKSPACE_SETTINGS_ID)
        except ArtifactRevisionNotFound:
            return None, None
        snapshot = workspace_settings_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise RepositoryIntegrityError("workspace settings belong to another workspace")
        return record, snapshot

    def _copied_assets(self, workspace_id, effective) -> tuple[SnapshotAsset, ...]:
        """Cópia exata dos ativos para dentro da perícia, marcada como ativo de marca.

        O papel `BRANDING_ASSET` mantém a cópia fora de Materiais, da Análise e das
        fontes do caso (F8): é identidade visual, nunca peça dos autos.
        """
        copies = []
        selection = template_selection_from_mapping(effective["values"][SettingKind.DEFAULT_TEMPLATE_SELECTION])
        for role in AssetRole:
            _, asset = self.settings.asset_record(role)
            if asset is None:
                continue
            if role is AssetRole.DEFAULT_WORD_TEMPLATE and selection.mode is not TemplateMode.CUSTOM:
                continue
            _, content = self.settings.asset_content(role)
            stored = self.store_private_content.execute(
                workspace_id=workspace_id, original_filename=asset.filename, content=content,
                media_type=asset.media_type, origin=PrivateContentOrigin.LOCAL_IMPORT,
            )
            if stored.checksum_sha256 != asset.sha256:
                raise RepositoryIntegrityError("workspace asset copy diverges from the installation asset")
            self.revisions.append(
                workspace_id=workspace_id, artifact_kind=PRIVATE_CONTENT_ROLE_KIND, artifact_id=str(stored.content_id),
                revision_id=str(self.ids.new_uuid()), created_at=self.clock.now().isoformat(),
                payload=private_content_role_payload(stored, PrivateContentRole.BRANDING_ASSET),
            )
            copies.append(SnapshotAsset(role, asset.asset_id, asset.filename, asset.media_type, asset.byte_size, asset.sha256, asset.width, asset.height, str(stored.content_id)))
        return tuple(copies)

    def _snapshot(self, workspace_id, reason: str) -> WorkspaceSettingsSnapshot:
        effective = self.settings.effective()
        values = effective["values"]
        return WorkspaceSettingsSnapshot(
            1, str(workspace_id), reason, dict(effective["sources"]),
            editorial_profile_from_mapping(values[SettingKind.EDITORIAL_PROFILE_DEFAULT]),
            branding_from_mapping(values[SettingKind.BRANDING_PROFILE]),
            presentation_from_mapping(values[SettingKind.DOCUMENT_PRESENTATION_PROFILE]),
            legal_editorial_from_mapping(values[SettingKind.LEGAL_EDITORIAL_PROFILE]),
            template_selection_from_mapping(values[SettingKind.DEFAULT_TEMPLATE_SELECTION]),
            self._copied_assets(workspace_id, effective),
        )

    def seed(self, workspace_id):
        """Na criação da perícia: snapshot dos padrões e perfil do perito, se houver."""
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("workspace settings authority guard is unavailable")
        with self.authority_guard():
            existing, _ = self.current(workspace_id)
            if existing is not None:
                raise RepositoryConflict("workspace settings were already captured")
            snapshot = self._snapshot(workspace_id, "WORKSPACE_CREATED")
            record = self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=WORKSPACE_SETTINGS_KIND, artifact_id=WORKSPACE_SETTINGS_ID,
                revision_id=str(self.ids.new_uuid()), created_at=self.clock.now().isoformat(),
                payload=workspace_settings_to_mapping(snapshot), expected_revision=None,
            )
            profile = self.settings.latest(SettingKind.EXPERT_PROFILE_DEFAULT)
            if profile is not None:
                self.revisions.append_if_latest(
                    workspace_id=workspace_id, artifact_kind=EXPERT_PROFILE_ARTIFACT_KIND, artifact_id=EXPERT_PROFILE_ARTIFACT_ID,
                    revision_id=str(self.ids.new_uuid()), created_at=self.clock.now().isoformat(),
                    payload=expert_profile_to_mapping(expert_profile_from_mapping(dict(profile.payload))), expected_revision=None,
                )
            return record, snapshot

    def _profile_record(self, workspace_id):
        try:
            record = self.get_latest_revision.execute(workspace_id, EXPERT_PROFILE_ARTIFACT_KIND, EXPERT_PROFILE_ARTIFACT_ID)
        except ArtifactRevisionNotFound:
            return None, None
        return record, expert_profile_from_mapping(thaw_payload(record.payload))

    def differences(self, workspace_id) -> dict[str, Any]:
        """O que mudaria se a perícia adotasse os padrões vigentes; nada é gravado."""
        record, snapshot = self.current(workspace_id)
        effective = self.settings.effective()
        changes = []
        if snapshot is None:
            changes.append("SETTINGS_NOT_CAPTURED")
        else:
            current = workspace_settings_to_mapping(snapshot)
            for kind, field in ((SettingKind.EDITORIAL_PROFILE_DEFAULT, "editorial_profile"), (SettingKind.BRANDING_PROFILE, "branding"), (SettingKind.DOCUMENT_PRESENTATION_PROFILE, "presentation"), (SettingKind.LEGAL_EDITORIAL_PROFILE, "legal_editorial"), (SettingKind.DEFAULT_TEMPLATE_SELECTION, "template_selection")):
                if current[field] != effective["values"][kind]:
                    changes.append(kind.value)
            installed = {role.value: (self.settings.asset_record(role)[1].sha256 if self.settings.asset_record(role)[1] else None) for role in AssetRole}
            captured = {item.role.value: item.sha256 for item in snapshot.assets}
            for role in AssetRole:
                if role is AssetRole.DEFAULT_WORD_TEMPLATE:
                    continue
                if installed[role.value] != captured.get(role.value):
                    changes.append(f"ASSET:{role.value}")
        profile_record, profile = self._profile_record(workspace_id)
        default_profile = self.settings.latest(SettingKind.EXPERT_PROFILE_DEFAULT)
        profile_changes = []
        if default_profile is not None:
            target = expert_profile_from_mapping(dict(default_profile.payload))
            if profile is None:
                profile_changes = ["PROFILE_NOT_CAPTURED"]
            else:
                current_mapping = expert_profile_to_mapping(replace(profile, revision=1))
                target_mapping = expert_profile_to_mapping(target)
                profile_changes = sorted(name for name in set(current_mapping) | set(target_mapping) if current_mapping.get(name) != target_mapping.get(name))
        return {
            "snapshot_revision": record.revision if record else None,
            "profile_revision": profile_record.revision if profile_record else None,
            "settings_changes": changes,
            "profile_changes": profile_changes,
        }

    def update_from_defaults(self, workspace_id, *, include_profile: bool, expected_snapshot_revision: int | None, expected_profile_revision: int | None):
        """Atualização explícita: nova revisão do snapshot e, se pedido, do perfil.

        A revisão anterior continua no histórico. Um laudo que fixou a revisão
        anterior do perfil passa a stale e precisa de nova aprovação.
        """
        if type(include_profile) is not bool:
            raise ValueError("profile update choice is invalid")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("workspace settings authority guard is unavailable")
        with self.authority_guard():
            record, _ = self.current(workspace_id)
            if (record.revision if record else None) != expected_snapshot_revision:
                raise RepositoryConflict("workspace settings changed")
            snapshot = self._snapshot(workspace_id, "UPDATED_FROM_INSTALLATION_DEFAULTS")
            saved = self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=WORKSPACE_SETTINGS_KIND, artifact_id=WORKSPACE_SETTINGS_ID,
                revision_id=str(self.ids.new_uuid()), created_at=self.clock.now().isoformat(),
                payload=workspace_settings_to_mapping(snapshot), expected_revision=expected_snapshot_revision,
            )
            profile_saved = None
            if include_profile:
                default_profile = self.settings.latest(SettingKind.EXPERT_PROFILE_DEFAULT)
                if default_profile is None:
                    raise ValueError("the installation has no professional profile to apply")
                profile_record, _ = self._profile_record(workspace_id)
                if (profile_record.revision if profile_record else None) != expected_profile_revision:
                    raise RepositoryConflict("the professional profile of this case changed")
                target = expert_profile_from_mapping(dict(default_profile.payload))
                target = replace(target, revision=(profile_record.revision + 1) if profile_record else 1)
                profile_saved = self.revisions.append_if_latest(
                    workspace_id=workspace_id, artifact_kind=EXPERT_PROFILE_ARTIFACT_KIND, artifact_id=EXPERT_PROFILE_ARTIFACT_ID,
                    revision_id=str(self.ids.new_uuid()), created_at=self.clock.now().isoformat(),
                    payload=expert_profile_to_mapping(target), expected_revision=expected_profile_revision,
                )
            return saved, snapshot, profile_saved


class WorkspaceSettingsCaptureFailed(RepositoryIntegrityError):
    """A perícia foi criada, mas o snapshot dos padrões não foi gravado."""

    def __init__(self, workspace):
        super().__init__("workspace created without its settings snapshot")
        self.workspace = workspace


@dataclass(frozen=True, slots=True)
class CreateWorkspaceWithSettings:
    """Cria a perícia e captura os padrões vigentes; falha nunca vira sucesso."""
    create: object
    settings: WorkspaceSettings | None

    def execute(self, name: str):
        workspace = self.create.execute(name)
        if self.settings is None:
            return workspace
        try:
            self.settings.seed(workspace.workspace_id)
        except Exception as exc:
            raise WorkspaceSettingsCaptureFailed(workspace) from exc
        return workspace
