"""Photo library: register imported originals, curate them, derive local previews."""

from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
import warnings

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from ..photo_library import (
    FIGURE_SECTIONS,
    PHOTO_LIBRARY_ARTIFACT_ID,
    PHOTO_LIBRARY_ARTIFACT_KIND,
    PHOTO_MEDIA_TYPES,
    PhotoEntry,
    PhotoLibrary,
    normalized_tags,
    photo_library_from_mapping,
    photo_library_to_mapping,
)
from .models import PrivateContentId, thaw_payload
from .ports import ArtifactRevisionNotFound, RepositoryConflict, RepositoryIntegrityError

# The transport speaks to the application layer only.
__all__ = ["CuratePhotoLibrary", "DuplicatePhoto", "GetPhotoLibrary", "ReadPhotoThumbnail", "photo_library_to_mapping", "read_photo_facts", "photo_thumbnail"]

THUMBNAIL_EDGE = 320
_EXIF_DATETIME_ORIGINAL = 0x9003
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825


def _opened(content: bytes) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(BytesIO(content))
            image.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("photo is truncated or corrupt") from exc
    return image


def read_photo_facts(content: bytes) -> tuple[int, int, str | None, str | None, bool]:
    """Oriented size, capture time, camera and whether a location is embedded.

    Everything is read from the bytes on this machine.  A capture time the
    camera wrote in an unreadable form is left out rather than guessed.
    """
    image = _opened(content)
    exif = image.getexif()
    oriented = ImageOps.exif_transpose(image)
    width, height = oriented.size
    captured_at = None
    raw = exif.get_ifd(_EXIF_IFD).get(_EXIF_DATETIME_ORIGINAL) or exif.get(ExifTags.Base.DateTime)
    if isinstance(raw, str) and len(raw.strip()) == 19:
        stamp = raw.strip()
        candidate = f"{stamp[0:4]}-{stamp[5:7]}-{stamp[8:10]}T{stamp[11:19]}"
        try:
            from datetime import datetime

            datetime.fromisoformat(candidate)
            captured_at = candidate
        except ValueError:
            captured_at = None
    make = str(exif.get(ExifTags.Base.Make) or "").strip().strip("\x00")
    model = str(exif.get(ExifTags.Base.Model) or "").strip().strip("\x00")
    camera = " ".join(part for part in (make, model) if part)[:120].strip() or None
    has_location = bool(exif.get_ifd(_GPS_IFD))
    return width, height, captured_at, camera, has_location


def photo_thumbnail(content: bytes) -> bytes:
    """A small upright JPEG preview with no metadata, derived on the fly."""
    image = ImageOps.exif_transpose(_opened(content)).convert("RGB")
    image.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)
    output = BytesIO()
    image.save(output, format="JPEG", quality=80)
    return output.getvalue()


@dataclass(frozen=True, slots=True)
class GetPhotoLibrary:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, PHOTO_LIBRARY_ARTIFACT_KIND, PHOTO_LIBRARY_ARTIFACT_ID)
        return record, photo_library_from_mapping(thaw_payload(record.payload))


@dataclass(frozen=True, slots=True)
class CuratePhotoLibrary:
    """Every library change: register an import, edit, select, remove."""
    revisions: object
    get_latest_revision: object
    get_private_content: object
    authority_guard: object
    clock: object
    ids: object

    def _current(self, workspace_id, expected_revision):
        try:
            record = self.get_latest_revision.execute(workspace_id, PHOTO_LIBRARY_ARTIFACT_KIND, PHOTO_LIBRARY_ARTIFACT_ID)
        except ArtifactRevisionNotFound:
            if expected_revision is not None:
                raise RepositoryConflict("photo library does not exist yet") from None
            return None, PhotoLibrary("1.0.0", str(workspace_id), ())
        if expected_revision != record.revision:
            raise RepositoryConflict("expected photo library revision is not latest")
        return record, photo_library_from_mapping(thaw_payload(record.payload))

    def _save(self, workspace_id, library: PhotoLibrary, expected_revision):
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("photo library authority guard is unavailable")
        with self.authority_guard():
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("photo library clock requires timezone")
            record = self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=PHOTO_LIBRARY_ARTIFACT_KIND, artifact_id=PHOTO_LIBRARY_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()), created_at=created_at.isoformat(), payload=photo_library_to_mapping(library),
                expected_revision=expected_revision,
            )
        return record, library

    def register(self, workspace_id, *, content_id: str, expected_revision: int | None):
        """Add an imported original; the same bytes twice are refused as a duplicate."""
        _, library = self._current(workspace_id, expected_revision)
        stored = self.get_private_content.execute(workspace_id, PrivateContentId.parse(content_id))
        metadata = stored.metadata
        if metadata.media_type not in PHOTO_MEDIA_TYPES:
            raise ValueError("only JPEG or PNG photos enter the library")
        duplicate = next((item for item in library.photos if item.original_sha256 == metadata.checksum_sha256), None)
        if duplicate is not None:
            raise DuplicatePhoto(duplicate.photo_id)
        width, height, captured_at, camera, has_location = read_photo_facts(stored.content)
        entry = PhotoEntry(
            f"PHOTO-{str(self.ids.new_uuid()).upper()}", str(metadata.content_id), metadata.checksum_sha256,
            metadata.original_filename, metadata.media_type, width, height, captured_at, camera, has_location,
            self.clock.now().isoformat(), None, (), None, None,
        )
        return self._save(workspace_id, replace(library, photos=(*library.photos, entry)), expected_revision)

    def describe(self, workspace_id, *, photo_id: str, caption: object, tags: object, expected_revision: int):
        _, library = self._current(workspace_id, expected_revision)
        if caption is not None and type(caption) is not str:
            raise ValueError("photo caption is invalid")
        text = " ".join(caption.split()) if isinstance(caption, str) else ""
        photos = tuple(
            replace(item, caption=text or None, tags=normalized_tags(tags)) if item.photo_id == photo_id else item
            for item in library.photos
        )
        if photos == library.photos and not any(item.photo_id == photo_id for item in library.photos):
            raise ValueError("photo is unknown")
        return self._save(workspace_id, replace(library, photos=photos), expected_revision)

    def select(self, workspace_id, *, selection: object, expected_revision: int):
        """The report's figures, in order, each placed in a report section."""
        _, library = self._current(workspace_id, expected_revision)
        if type(selection) is not list or any(type(item) is not dict or set(item) != {"photo_id", "section"} for item in selection):
            raise ValueError("photo selection is invalid")
        chosen = {item["photo_id"]: (order, item["section"]) for order, item in enumerate(selection, 1)}
        if len(chosen) != len(selection) or not set(chosen) <= {item.photo_id for item in library.photos} or any(section not in FIGURE_SECTIONS for _order, section in chosen.values()):
            raise ValueError("photo selection is invalid")
        photos = tuple(
            replace(item, report_section=chosen[item.photo_id][1], report_order=chosen[item.photo_id][0]) if item.photo_id in chosen
            else replace(item, report_section=None, report_order=None)
            for item in library.photos
        )
        return self._save(workspace_id, replace(library, photos=photos), expected_revision)

    def remove(self, workspace_id, *, photo_id: str, expected_revision: int):
        """Take a photo out of the library; the original stays in private storage."""
        _, library = self._current(workspace_id, expected_revision)
        target = next((item for item in library.photos if item.photo_id == photo_id), None)
        if target is None or target.report_order is not None:
            raise ValueError("only an unselected photo can leave the library")
        return self._save(workspace_id, replace(library, photos=tuple(item for item in library.photos if item.photo_id != photo_id)), expected_revision)


class DuplicatePhoto(ValueError):
    def __init__(self, photo_id: str):
        super().__init__("photo already in the library")
        self.photo_id = photo_id


@dataclass(frozen=True, slots=True)
class ReadPhotoThumbnail:
    get_library: GetPhotoLibrary
    get_private_content: object

    def execute(self, workspace_id, photo_id: str) -> bytes:
        _, library = self.get_library.execute(workspace_id)
        entry = next((item for item in library.photos if item.photo_id == photo_id), None)
        if entry is None:
            raise ValueError("photo is unknown")
        stored = self.get_private_content.execute(workspace_id, PrivateContentId.parse(entry.content_id))
        if stored.metadata.checksum_sha256 != entry.original_sha256:
            raise RepositoryIntegrityError("photo original diverges from the library")
        return photo_thumbnail(stored.content)
