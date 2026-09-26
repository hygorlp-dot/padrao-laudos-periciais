"""The case photo library: originals kept intact, curated for the report.

Each entry points at an original private content by its SHA-256; the original
is never rewritten.  What the library adds is the expert's curation -- caption,
tags and the selection that becomes the report's figures -- and what the
camera recorded, read locally (capture time, camera, whether it embedded a
location).  Embedded coordinates themselves are not copied anywhere.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
import json
import re

PHOTO_LIBRARY_ARTIFACT_KIND = "PHOTO_LIBRARY_V1"
PHOTO_LIBRARY_ARTIFACT_ID = "PHOTO-LIBRARY"
FIGURE_SECTIONS = ("INSPECTION", "TECHNICAL_ANALYSIS", "TECHNICAL_FINDINGS", "ATTACHMENTS")
PHOTO_MEDIA_TYPES = ("image/jpeg", "image/png")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PHOTO_ID = re.compile(r"^PHOTO-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")
_CAPTURED = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
MAX_TAGS = 12
MAX_TAG = 40
MAX_CAPTION = 300
MAX_PHOTOS = 500


def _text(value: object, limit: int) -> bool:
    return type(value) is str and bool(value.strip()) and value == value.strip() and len(value) <= limit and "\x00" not in value


@dataclass(frozen=True, slots=True)
class PhotoEntry:
    photo_id: str
    content_id: str
    original_sha256: str
    original_filename: str
    media_type: str
    width: int
    height: int
    captured_at: str | None
    camera: str | None
    has_embedded_location: bool
    imported_at: str
    caption: str | None
    tags: tuple[str, ...]
    report_section: str | None
    report_order: int | None

    def __post_init__(self):
        if _PHOTO_ID.fullmatch(self.photo_id or "") is None or _UUID.fullmatch(self.content_id or "") is None or _SHA256.fullmatch(self.original_sha256 or "") is None:
            raise ValueError("photo identity is invalid")
        if not _text(self.original_filename, 255) or self.media_type not in PHOTO_MEDIA_TYPES:
            raise ValueError("photo file is invalid")
        if any(type(value) is not int or not 1 <= value <= 100_000 for value in (self.width, self.height)):
            raise ValueError("photo dimensions are invalid")
        if self.captured_at is not None:
            if type(self.captured_at) is not str or _CAPTURED.fullmatch(self.captured_at) is None:
                raise ValueError("photo capture time is invalid")
            datetime.fromisoformat(self.captured_at)
        if self.camera is not None and not _text(self.camera, 120):
            raise ValueError("photo camera is invalid")
        if type(self.has_embedded_location) is not bool:
            raise ValueError("photo location flag is invalid")
        parsed = datetime.fromisoformat(self.imported_at) if type(self.imported_at) is str else None
        if parsed is None or parsed.tzinfo is None:
            raise ValueError("photo import time is invalid")
        if self.caption is not None and not _text(self.caption, MAX_CAPTION):
            raise ValueError("photo caption is invalid")
        if type(self.tags) is not tuple or len(self.tags) > MAX_TAGS or any(not _text(tag, MAX_TAG) for tag in self.tags) or len({tag.casefold() for tag in self.tags}) != len(self.tags):
            raise ValueError("photo tags are invalid")
        selected = self.report_section is not None
        if selected != (self.report_order is not None):
            raise ValueError("photo report selection is dishonest")
        if selected:
            if self.report_section not in FIGURE_SECTIONS or type(self.report_order) is not int or self.report_order < 1:
                raise ValueError("photo report selection is invalid")
            if self.caption is None:
                raise ValueError("a figure requires a caption")


@dataclass(frozen=True, slots=True)
class PhotoLibrary:
    schema_version: str
    workspace_id: str
    photos: tuple[PhotoEntry, ...]

    def __post_init__(self):
        if self.schema_version != "1.0.0" or type(self.workspace_id) is not str or _UUID.fullmatch(self.workspace_id) is None:
            raise ValueError("photo library identity is invalid")
        if type(self.photos) is not tuple or len(self.photos) > MAX_PHOTOS or any(type(item) is not PhotoEntry for item in self.photos):
            raise ValueError("photo library entries are invalid")
        for name in ("photo_id", "content_id", "original_sha256"):
            if len({getattr(item, name) for item in self.photos}) != len(self.photos):
                # The same bytes twice would be one photo with two identities.
                raise ValueError(f"photo library {name} must be unique")
        orders = sorted(item.report_order for item in self.photos if item.report_order is not None)
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("photo library report order is not a sequence")

    @property
    def selected(self) -> tuple[PhotoEntry, ...]:
        """The report's figures, in the expert's order."""
        return tuple(sorted((item for item in self.photos if item.report_order is not None), key=lambda item: item.report_order))


def photo_library_to_mapping(value: PhotoLibrary) -> dict:
    if type(value) is not PhotoLibrary:
        raise TypeError("expected PhotoLibrary")
    return json.loads(json.dumps(asdict(value), ensure_ascii=False))


def photo_library_from_mapping(value: object) -> PhotoLibrary:
    if type(value) is not dict or set(value) != {item.name for item in fields(PhotoLibrary)} or type(value["photos"]) is not list:
        raise ValueError("PhotoLibrary mapping is invalid")
    entry_fields = {item.name for item in fields(PhotoEntry)}
    photos = []
    for item in value["photos"]:
        if type(item) is not dict or set(item) != entry_fields or type(item["tags"]) is not list:
            raise ValueError("PhotoEntry mapping is invalid")
        photos.append(PhotoEntry(**{**item, "tags": tuple(item["tags"])}))
    return PhotoLibrary(value["schema_version"], value["workspace_id"], tuple(photos))


def normalized_tags(values: object) -> tuple[str, ...]:
    """Tags as the expert typed them, trimmed, first spelling kept per word."""
    if type(values) is not list or any(type(value) is not str for value in values):
        raise ValueError("photo tags are invalid")
    tags: list[str] = []
    for value in values:
        tag = " ".join(value.split())
        if tag and tag.casefold() not in {item.casefold() for item in tags}:
            tags.append(tag)
    return tuple(tags)
