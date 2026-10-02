"""Configurações da instalação e snapshot por perícia (#270, #271, #272).

O padrão global nunca reescreve uma perícia existente:

    PADRÃO DA INSTALAÇÃO -> NOVA PERÍCIA -> SNAPSHOT DA PERÍCIA -> LAUDO -> WORD

Os tipos aqui são apresentação e política editorial. Nenhum carrega fato
pericial, e nenhum invariante do produto vira opção: proveniência, Word
autoritativo, PDF derivado e a separação entre proposta e decisão não são
configuráveis.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from enum import StrEnum
import json
import re
from typing import Any

from .report_foundation import (
    DEFAULT_EDITORIAL_LAYOUT,
    DEFAULT_EDITORIAL_TYPOGRAPHY,
    EDITORIAL_PRESET_ID,
    EditorialProfile,
    editorial_profile_from_mapping,
    editorial_profile_to_mapping,
    expert_profile_from_mapping,
    expert_profile_to_mapping,
)


class SettingKind(StrEnum):
    EXPERT_PROFILE_DEFAULT = "EXPERT_PROFILE_DEFAULT_V1"
    EDITORIAL_PROFILE_DEFAULT = "EDITORIAL_PROFILE_DEFAULT_V1"
    BRANDING_PROFILE = "BRANDING_PROFILE_V1"
    DOCUMENT_PRESENTATION_PROFILE = "DOCUMENT_PRESENTATION_PROFILE_V1"
    LEGAL_EDITORIAL_PROFILE = "LEGAL_EDITORIAL_PROFILE_V1"
    DEFAULT_TEMPLATE_SELECTION = "DEFAULT_TEMPLATE_SELECTION_V1"
    INSTALLATION_ASSET = "INSTALLATION_ASSET_V1"


class AssetRole(StrEnum):
    PRIMARY_LOGO = "PRIMARY_LOGO"
    SYMBOL = "SYMBOL"
    WATERMARK = "WATERMARK"
    SIGNATURE_IMAGE = "SIGNATURE_IMAGE"
    PROFESSIONAL_SEAL = "PROFESSIONAL_SEAL"
    BACKGROUND = "BACKGROUND"
    DEFAULT_WORD_TEMPLATE = "DEFAULT_WORD_TEMPLATE"


IMAGE_ROLES = frozenset(role for role in AssetRole if role is not AssetRole.DEFAULT_WORD_TEMPLATE)
IMAGE_MEDIA_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG"}
TEMPLATE_MEDIA_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/vnd.ms-word.document.macroEnabled.12": "DOCM",
}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TEMPLATE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
DEFAULT_SETTING_ID = "DEFAULT"
WORKSPACE_SETTINGS_KIND = "WORKSPACE_SETTINGS_SNAPSHOT_V1"
WORKSPACE_SETTINGS_ID = "WORKSPACE-SETTINGS"
LEGAL_EDITORIAL_PROFILE_ID = "SISTEMA_PERICIAL_CNJ_TRF5_V1"
_HEX_COLOR = re.compile(r"#[0-9A-F]{6}")
_ASSET_ID = re.compile(r"ASSET-[0-9A-F]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# Acima disto a marca d'agua compete com o texto; a UI avisa e o produto nao
# aceita como padrao.
WATERMARK_MAX_OPACITY = 0.30
WATERMARK_LEGIBLE_OPACITY = 0.15


def _text(value: object, limit: int = 200) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip() and len(value) <= limit and "\x00" not in value


def _optional(value: object, limit: int = 200) -> bool:
    return value is None or _text(value, limit)


def _number(value: object, low: float, high: float) -> bool:
    return type(value) in (int, float) and value == value and low <= value <= high and round(value * 100) == value * 100


def relative_luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_on_white(color: str) -> float:
    return 1.05 / (relative_luminance(color) + 0.05)


def _color(value: object) -> bool:
    return type(value) is str and _HEX_COLOR.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class BrandingProfile:
    """Somente apresentação: cores da identidade. Imagens são ativos à parte."""
    primary_color: str
    secondary_color: str
    rule_color: str
    heading_color: str

    def __post_init__(self):
        if not all(_color(getattr(self, item.name)) for item in fields(self)):
            raise ValueError("branding colors must be #RRGGBB")
        # Titulo colorido continua texto: contraste minimo AA sobre papel branco.
        if contrast_on_white(self.heading_color) < 4.5:
            raise ValueError("heading color is not legible on white paper")


DEFAULT_BRANDING = BrandingProfile("#1F3A4D", "#5B7083", "#9AAAB8", "#1F3A4D")


class Alignment(StrEnum):
    LEFT = "LEFT"
    CENTER = "CENTER"
    RIGHT = "RIGHT"


class WatermarkKind(StrEnum):
    IMAGE = "IMAGE"
    SYMBOL = "SYMBOL"
    TEXT = "TEXT"


class BackgroundKind(StrEnum):
    WHITE = "WHITE"
    SOLID = "SOLID"
    IMAGE = "IMAGE"


class PageNumbering(StrEnum):
    PAGE_X_OF_Y = "PAGE_X_OF_Y"
    PAGE_X = "PAGE_X"


@dataclass(frozen=True, slots=True)
class CoverPresentation:
    enabled: bool
    show_logo: bool
    title: str
    subtitle: str | None
    show_court: bool
    show_participants: bool
    show_expert: bool
    show_city_year: bool
    city: str | None

    def __post_init__(self):
        if any(type(getattr(self, name)) is not bool for name in ("enabled", "show_logo", "show_court", "show_participants", "show_expert", "show_city_year")):
            raise ValueError("cover flags are invalid")
        if not _text(self.title, 120) or not _optional(self.subtitle, 200) or not _optional(self.city, 80):
            raise ValueError("cover text is invalid")


@dataclass(frozen=True, slots=True)
class HeaderPresentation:
    enabled: bool
    show_logo: bool
    show_name: bool
    show_title: bool
    show_council: bool
    show_court_registration: bool
    show_phone: bool
    show_email: bool
    logo_width_cm: float
    alignment: Alignment
    separator_enabled: bool
    separator_thickness_pt: float

    def __post_init__(self):
        flags = ("enabled", "show_logo", "show_name", "show_title", "show_council", "show_court_registration", "show_phone", "show_email", "separator_enabled")
        if any(type(getattr(self, name)) is not bool for name in flags):
            raise ValueError("header flags are invalid")
        if not _number(self.logo_width_cm, 0.8, 6) or not _number(self.separator_thickness_pt, 0.25, 3) or type(self.alignment) is not Alignment:
            raise ValueError("header geometry is invalid")


@dataclass(frozen=True, slots=True)
class FooterPresentation:
    page_numbering: PageNumbering
    institutional_text: str | None
    show_registration: bool
    show_contact: bool

    def __post_init__(self):
        if type(self.page_numbering) is not PageNumbering or not _optional(self.institutional_text, 160):
            raise ValueError("footer is invalid")
        if type(self.show_registration) is not bool or type(self.show_contact) is not bool:
            raise ValueError("footer flags are invalid")


@dataclass(frozen=True, slots=True)
class WatermarkPresentation:
    enabled: bool
    kind: WatermarkKind
    text: str | None
    opacity: float
    scale: float
    rotation_degrees: int
    apply_cover: bool
    apply_body: bool
    apply_attachments: bool

    def __post_init__(self):
        if any(type(getattr(self, name)) is not bool for name in ("enabled", "apply_cover", "apply_body", "apply_attachments")):
            raise ValueError("watermark flags are invalid")
        if type(self.kind) is not WatermarkKind or not _optional(self.text, 60):
            raise ValueError("watermark kind is invalid")
        if self.kind is WatermarkKind.TEXT and self.text is None:
            raise ValueError("a text watermark needs its text")
        if not _number(self.opacity, 0.02, WATERMARK_MAX_OPACITY) or not _number(self.scale, 0.2, 1.0):
            raise ValueError("watermark opacity or scale is outside the legible range")
        if type(self.rotation_degrees) is not int or not -60 <= self.rotation_degrees <= 60:
            raise ValueError("watermark rotation is invalid")

    @property
    def legibility_warning(self) -> bool:
        return self.enabled and self.opacity > WATERMARK_LEGIBLE_OPACITY


@dataclass(frozen=True, slots=True)
class BackgroundPresentation:
    kind: BackgroundKind
    color: str | None
    apply_cover: bool
    apply_body: bool

    def __post_init__(self):
        if type(self.kind) is not BackgroundKind or type(self.apply_cover) is not bool or type(self.apply_body) is not bool:
            raise ValueError("background is invalid")
        if self.kind is BackgroundKind.SOLID:
            # Fundo claro: texto preto continua com contraste AA.
            if not _color(self.color) or relative_luminance(self.color) < 0.80:
                raise ValueError("a solid background must be a light color")
        elif self.color is not None:
            raise ValueError("only a solid background carries a color")


@dataclass(frozen=True, slots=True)
class DocumentPresentationProfile:
    cover: CoverPresentation
    header: HeaderPresentation
    footer: FooterPresentation
    watermark: WatermarkPresentation
    background: BackgroundPresentation

    def __post_init__(self):
        expected = (CoverPresentation, HeaderPresentation, FooterPresentation, WatermarkPresentation, BackgroundPresentation)
        if any(type(getattr(self, item.name)) is not kind for item, kind in zip(fields(self), expected, strict=True)):
            raise ValueError("document presentation is invalid")


DEFAULT_PRESENTATION = DocumentPresentationProfile(
    CoverPresentation(True, True, "LAUDO PERICIAL", None, True, True, True, True, None),
    HeaderPresentation(True, True, True, True, True, False, False, False, 2.5, Alignment.LEFT, True, 0.75),
    FooterPresentation(PageNumbering.PAGE_X_OF_Y, None, False, False),
    WatermarkPresentation(False, WatermarkKind.SYMBOL, None, 0.08, 0.5, 0, False, True, False),
    BackgroundPresentation(BackgroundKind.WHITE, None, False, False),
)


@dataclass(frozen=True, slots=True)
class LegalEditorialProfile:
    """Política editorial complementar; avisos, nunca reescrita automática.

    Marcadores pendentes sempre bloqueiam a emissão e não aparecem aqui como
    opção: são invariante do produto, não preferência.
    """
    profile_id: str
    check_acronyms: bool
    check_latinisms: bool
    check_foreign_terms: bool
    check_jargon: bool
    check_long_sentences: bool
    check_long_paragraphs: bool
    long_sentence_words: int
    long_paragraph_words: int

    def __post_init__(self):
        if self.profile_id != LEGAL_EDITORIAL_PROFILE_ID:
            raise ValueError("legal editorial profile is unknown")
        if any(type(getattr(self, item.name)) is not bool for item in fields(self) if item.name.startswith("check_")):
            raise ValueError("legal editorial checks are invalid")
        if type(self.long_sentence_words) is not int or not 25 <= self.long_sentence_words <= 90:
            raise ValueError("long sentence threshold is invalid")
        if type(self.long_paragraph_words) is not int or not 80 <= self.long_paragraph_words <= 400:
            raise ValueError("long paragraph threshold is invalid")


DEFAULT_LEGAL_EDITORIAL = LegalEditorialProfile(LEGAL_EDITORIAL_PROFILE_ID, True, True, True, True, True, True, 45, 180)


class TemplateMode(StrEnum):
    PRODUCT_DEFAULT = "PRODUCT_DEFAULT"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class DefaultTemplateSelection:
    mode: TemplateMode
    template_sha256: str | None

    def __post_init__(self):
        if type(self.mode) is not TemplateMode:
            raise ValueError("template selection is invalid")
        if self.mode is TemplateMode.CUSTOM:
            if type(self.template_sha256) is not str or _SHA256.fullmatch(self.template_sha256) is None:
                raise ValueError("a custom template selection names its template")
        elif self.template_sha256 is not None:
            raise ValueError("the product default template has no custom bytes")


DEFAULT_TEMPLATE_SELECTION = DefaultTemplateSelection(TemplateMode.PRODUCT_DEFAULT, None)


@dataclass(frozen=True, slots=True)
class InstallationAssetRecord:
    asset_id: str
    role: AssetRole
    filename: str
    media_type: str
    byte_size: int
    sha256: str
    width: int | None
    height: int | None

    def __post_init__(self):
        if _ASSET_ID.fullmatch(self.asset_id or "") is None or type(self.role) is not AssetRole:
            raise ValueError("installation asset identity is invalid")
        if not _text(self.filename, 255) or "/" in self.filename or "\\" in self.filename:
            raise ValueError("installation asset filename is invalid")
        allowed = IMAGE_MEDIA_TYPES if self.role in IMAGE_ROLES else TEMPLATE_MEDIA_TYPES
        if self.media_type not in allowed:
            raise ValueError("installation asset format is not supported for this role")
        limit = MAX_IMAGE_BYTES if self.role in IMAGE_ROLES else MAX_TEMPLATE_BYTES
        if type(self.byte_size) is not int or not 1 <= self.byte_size <= limit or type(self.sha256) is not str or _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("installation asset bytes are invalid")
        if self.role in IMAGE_ROLES:
            if any(type(value) is not int or value < 1 for value in (self.width, self.height)) or self.width * self.height > MAX_IMAGE_PIXELS:
                raise ValueError("installation image dimensions are invalid")
        elif self.width is not None or self.height is not None:
            raise ValueError("a Word template has no pixel dimensions")


def _enum_fields(cls, value: dict) -> dict:
    converted = dict(value)
    for item in fields(cls):
        kind = {"alignment": Alignment, "kind": None, "page_numbering": PageNumbering, "mode": TemplateMode, "role": AssetRole}.get(item.name)
        if item.name == "kind":
            kind = WatermarkKind if cls is WatermarkPresentation else BackgroundKind if cls is BackgroundPresentation else None
        if kind is not None and type(converted.get(item.name)) is str:
            converted[item.name] = kind(converted[item.name])
    return converted


def _exact(cls, value: object):
    if type(value) is not dict or set(value) != {item.name for item in fields(cls)}:
        raise ValueError(f"{cls.__name__} fields are invalid")
    try:
        return cls(**_enum_fields(cls, value))
    except (TypeError, KeyError) as exc:
        raise ValueError(f"{cls.__name__} is invalid") from exc


def branding_from_mapping(value: object) -> BrandingProfile:
    return _exact(BrandingProfile, value)


def presentation_from_mapping(value: object) -> DocumentPresentationProfile:
    if type(value) is not dict or set(value) != {"cover", "header", "footer", "watermark", "background"}:
        raise ValueError("DocumentPresentationProfile fields are invalid")
    return DocumentPresentationProfile(
        _exact(CoverPresentation, value["cover"]), _exact(HeaderPresentation, value["header"]),
        _exact(FooterPresentation, value["footer"]), _exact(WatermarkPresentation, value["watermark"]),
        _exact(BackgroundPresentation, value["background"]),
    )


def legal_editorial_from_mapping(value: object) -> LegalEditorialProfile:
    return _exact(LegalEditorialProfile, value)


def template_selection_from_mapping(value: object) -> DefaultTemplateSelection:
    return _exact(DefaultTemplateSelection, value)


def asset_record_from_mapping(value: object) -> InstallationAssetRecord:
    return _exact(InstallationAssetRecord, value)


def to_mapping(value: object) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(value), ensure_ascii=False))


DEFAULT_EDITORIAL_PROFILE = EditorialProfile(
    EDITORIAL_PRESET_ID, "Arial", 11, 10, 9, "JUSTIFIED", 1.15, 1.25, "A4", 2, 2, 3, 2, False, (),
    DEFAULT_EDITORIAL_TYPOGRAPHY, DEFAULT_EDITORIAL_LAYOUT,
)
# A geometria observada no laudo legado aprovado (padrao-visual-word.md), como
# perfil personalizado pronto para aplicar. Nao substitui o preset da #131.
LEGACY_VISUAL_EDITORIAL_PROFILE = EditorialProfile(
    "CUSTOM", "Arial", 11, 10, 9, "JUSTIFIED", 1.15, 1.25, "A4", 2.54, 2.54, 3, 2.54, False, ("Geometria do laudo legado aprovado",),
    DEFAULT_EDITORIAL_TYPOGRAPHY, DEFAULT_EDITORIAL_LAYOUT,
)


def validated_setting_payload(kind: SettingKind, setting_id: str, payload: object) -> dict[str, Any]:
    """Payload canônico de uma revisão; qualquer coisa fora do contrato falha fechado."""
    if type(kind) is not SettingKind:
        raise ValueError("setting kind is invalid")
    if kind is SettingKind.INSTALLATION_ASSET:
        role = AssetRole(setting_id)
        if type(payload) is dict and set(payload) == {"role", "removed"}:
            if payload["role"] != role.value or payload["removed"] is not True:
                raise ValueError("asset removal is invalid")
            return {"role": role.value, "removed": True}
        record = asset_record_from_mapping(payload)
        if record.role is not role:
            raise ValueError("asset role diverges from its setting identity")
        return to_mapping(record)
    if setting_id != DEFAULT_SETTING_ID:
        raise ValueError("setting identity is invalid")
    if kind is SettingKind.EXPERT_PROFILE_DEFAULT:
        profile = expert_profile_from_mapping(payload)
        if profile.revision != 1:
            raise ValueError("the installation profile is not a workspace revision")
        return expert_profile_to_mapping(profile)
    if kind is SettingKind.EDITORIAL_PROFILE_DEFAULT:
        return editorial_profile_to_mapping(editorial_profile_from_mapping(payload))
    readers = {
        SettingKind.BRANDING_PROFILE: branding_from_mapping,
        SettingKind.DOCUMENT_PRESENTATION_PROFILE: presentation_from_mapping,
        SettingKind.LEGAL_EDITORIAL_PROFILE: legal_editorial_from_mapping,
        SettingKind.DEFAULT_TEMPLATE_SELECTION: template_selection_from_mapping,
    }
    return to_mapping(readers[kind](payload))


PRODUCT_DEFAULTS: dict[SettingKind, object] = {
    SettingKind.EDITORIAL_PROFILE_DEFAULT: DEFAULT_EDITORIAL_PROFILE,
    SettingKind.BRANDING_PROFILE: DEFAULT_BRANDING,
    SettingKind.DOCUMENT_PRESENTATION_PROFILE: DEFAULT_PRESENTATION,
    SettingKind.LEGAL_EDITORIAL_PROFILE: DEFAULT_LEGAL_EDITORIAL,
    SettingKind.DEFAULT_TEMPLATE_SELECTION: DEFAULT_TEMPLATE_SELECTION,
}


def default_payload(kind: SettingKind) -> dict[str, Any] | None:
    value = PRODUCT_DEFAULTS.get(kind)
    if value is None:
        return None
    if type(value) is EditorialProfile:
        return editorial_profile_to_mapping(value)
    return to_mapping(value)


@dataclass(frozen=True, slots=True)
class SnapshotAsset:
    """Cópia exata de um ativo dentro da perícia, para reabrir sem a instalação."""
    role: AssetRole
    asset_id: str
    filename: str
    media_type: str
    byte_size: int
    sha256: str
    width: int | None
    height: int | None
    content_id: str

    def __post_init__(self):
        InstallationAssetRecord(self.asset_id, self.role, self.filename, self.media_type, self.byte_size, self.sha256, self.width, self.height)
        if not _text(self.content_id, 64):
            raise ValueError("snapshot asset content is invalid")


SNAPSHOT_REASONS = ("WORKSPACE_CREATED", "UPDATED_FROM_INSTALLATION_DEFAULTS")


@dataclass(frozen=True, slots=True)
class WorkspaceSettingsSnapshot:
    schema_version: int
    workspace_id: str
    reason: str
    # Revisão da instalação de que cada parte veio; None = padrão do produto.
    sources: dict[str, dict | None]
    editorial_profile: EditorialProfile
    branding: BrandingProfile
    presentation: DocumentPresentationProfile
    legal_editorial: LegalEditorialProfile
    template_selection: DefaultTemplateSelection
    assets: tuple[SnapshotAsset, ...]

    def __post_init__(self):
        if self.schema_version != 1 or not _text(self.workspace_id, 64) or self.reason not in SNAPSHOT_REASONS:
            raise ValueError("workspace settings snapshot identity is invalid")
        if type(self.sources) is not dict or set(self.sources) != {kind.value for kind in SettingKind if kind is not SettingKind.INSTALLATION_ASSET}:
            raise ValueError("workspace settings sources are invalid")
        for source in self.sources.values():
            if source is not None and (type(source) is not dict or set(source) != {"revision", "checksum_sha256"} or type(source["revision"]) is not int or source["revision"] < 1 or type(source["checksum_sha256"]) is not str or _SHA256.fullmatch(source["checksum_sha256"]) is None):
                raise ValueError("workspace settings source is invalid")
        if type(self.assets) is not tuple or any(type(item) is not SnapshotAsset for item in self.assets) or len({item.role for item in self.assets}) != len(self.assets):
            raise ValueError("workspace settings assets are invalid")
        if self.template_selection.mode is TemplateMode.CUSTOM and not any(item.role is AssetRole.DEFAULT_WORD_TEMPLATE and item.sha256 == self.template_selection.template_sha256 for item in self.assets):
            raise ValueError("the selected custom template is not in the workspace snapshot")

    def asset(self, role: AssetRole) -> SnapshotAsset | None:
        return next((item for item in self.assets if item.role is role), None)


def workspace_settings_to_mapping(value: WorkspaceSettingsSnapshot) -> dict[str, Any]:
    return {
        "schema_version": value.schema_version,
        "workspace_id": value.workspace_id,
        "reason": value.reason,
        "sources": json.loads(json.dumps(value.sources)),
        "editorial_profile": editorial_profile_to_mapping(value.editorial_profile),
        "branding": to_mapping(value.branding),
        "presentation": to_mapping(value.presentation),
        "legal_editorial": to_mapping(value.legal_editorial),
        "template_selection": to_mapping(value.template_selection),
        "assets": [to_mapping(item) for item in value.assets],
    }


def workspace_settings_from_mapping(value: object) -> WorkspaceSettingsSnapshot:
    names = {"schema_version", "workspace_id", "reason", "sources", "editorial_profile", "branding", "presentation", "legal_editorial", "template_selection", "assets"}
    if type(value) is not dict or set(value) != names or type(value["assets"]) is not list:
        raise ValueError("workspace settings snapshot mapping is invalid")
    return WorkspaceSettingsSnapshot(
        value["schema_version"], value["workspace_id"], value["reason"], dict(value["sources"]) if type(value["sources"]) is dict else value["sources"],
        editorial_profile_from_mapping(value["editorial_profile"]), branding_from_mapping(value["branding"]),
        presentation_from_mapping(value["presentation"]), legal_editorial_from_mapping(value["legal_editorial"]),
        template_selection_from_mapping(value["template_selection"]),
        tuple(_exact(SnapshotAsset, item) for item in value["assets"]),
    )
