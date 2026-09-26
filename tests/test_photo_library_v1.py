"""The case photo library (#239, Phase E).

Originals stay intact in private storage and are identified by SHA-256; the
library records the expert's curation and what the camera wrote, read
locally.  The same bytes cannot enter twice, a figure needs a caption, and
previews are derived upright and without metadata.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
import hashlib
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

from PIL import Image
import pytest

from scripts.backend_contract.application.models import PrivateContentId, _freeze_payload
from scripts.backend_contract.application.photo_library import (
    CuratePhotoLibrary,
    DuplicatePhoto,
    GetPhotoLibrary,
    ReadPhotoThumbnail,
    read_photo_facts,
)
from scripts.backend_contract.application.ports import ArtifactRevisionNotFound, RepositoryConflict
from scripts.backend_contract.photo_library import (
    PhotoEntry,
    PhotoLibrary,
    photo_library_from_mapping,
    photo_library_to_mapping,
)

WORKSPACE = "11111111-1111-4111-8111-111111111111"


def jpeg(color=(200, 80, 40), size=(640, 480), *, taken="2026:09:20 14:05:33", make="SyntheticCam", orientation=1, gps=False) -> bytes:
    image = Image.new("RGB", size, color)
    exif = Image.Exif()
    exif[0x010F] = make
    exif[0x0110] = "Model S"
    exif[0x0112] = orientation
    exif.get_ifd(0x8769)[0x9003] = taken
    if gps:
        exif.get_ifd(0x8825)[1] = "S"
        exif.get_ifd(0x8825)[2] = (23.0, 33.0, 1.9)
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif.tobytes(), quality=90)
    return output.getvalue()


class _Private:
    def __init__(self):
        self.items = {}

    def add(self, content: bytes, filename="foto.jpg", media_type="image/jpeg") -> str:
        content_id = f"{len(self.items) + 1:08d}-0000-4000-8000-000000000000"
        self.items[content_id] = SimpleNamespace(
            content=content,
            metadata=SimpleNamespace(content_id=PrivateContentId.parse(content_id), checksum_sha256=hashlib.sha256(content).hexdigest(), original_filename=filename, media_type=media_type),
        )
        return content_id

    def execute(self, _workspace, content_id):
        return self.items[str(content_id)]


class _Revisions:
    def __init__(self):
        self.records = []

    def append_if_latest(self, *, expected_revision, payload, created_at, **_kwargs):
        if expected_revision != (len(self.records) or None):
            raise RepositoryConflict("stale")
        record = SimpleNamespace(revision=len(self.records) + 1, payload=_freeze_payload(payload), created_at=created_at)
        self.records.append(record)
        return record

    def execute(self, *_args):
        if not self.records:
            raise ArtifactRevisionNotFound("absent")
        return self.records[-1]


def _curator():
    revisions, private = _Revisions(), _Private()
    counter = iter(range(1, 1000))
    curator = CuratePhotoLibrary(
        revisions, revisions, private, nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 9, 26, 13, 0, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: UUID(f"00000000-0000-4000-8000-{next(counter):012d}")),
    )
    return curator, revisions, private


def test_the_camera_record_is_read_locally_without_copying_its_location() -> None:
    width, height, captured, camera, located = read_photo_facts(jpeg(orientation=6, gps=True))
    assert (width, height) == (480, 640), "EXIF orientation 6 is a portrait photo"
    assert (captured, camera, located) == ("2026-09-20T14:05:33", "SyntheticCam Model S", True)
    assert read_photo_facts(jpeg(taken="garbage"))[2] is None


def test_originals_register_once_and_curation_is_honest() -> None:
    curator, revisions, private = _curator()
    first = private.add(jpeg())
    record, library = curator.register(WORKSPACE, content_id=first, expected_revision=None)
    entry = library.photos[0]
    assert (record.revision, entry.original_sha256, entry.caption, entry.report_order) == (1, private.items[first].metadata.checksum_sha256, None, None)
    with pytest.raises(DuplicatePhoto) as duplicate:
        curator.register(WORKSPACE, content_id=private.add(jpeg()), expected_revision=1)
    assert duplicate.value.photo_id == entry.photo_id
    second = private.add(jpeg(color=(10, 90, 200)))
    _, library = curator.register(WORKSPACE, content_id=second, expected_revision=1)
    photo_a, photo_b = (item.photo_id for item in library.photos)
    with pytest.raises(ValueError, match="caption"):
        curator.select(WORKSPACE, selection=[{"photo_id": photo_a, "section": "INSPECTION"}], expected_revision=2)
    _, library = curator.describe(WORKSPACE, photo_id=photo_a, caption="  Fissura   na parede leste ", tags=["fachada", " Fachada ", "umidade"], expected_revision=2)
    assert (library.photos[0].caption, library.photos[0].tags) == ("Fissura na parede leste", ("fachada", "umidade"))
    _, library = curator.describe(WORKSPACE, photo_id=photo_b, caption="Mancha no teto", tags=[], expected_revision=3)
    _, library = curator.select(WORKSPACE, selection=[{"photo_id": photo_b, "section": "TECHNICAL_FINDINGS"}, {"photo_id": photo_a, "section": "INSPECTION"}], expected_revision=4)
    assert [(item.photo_id, item.report_section) for item in library.selected] == [(photo_b, "TECHNICAL_FINDINGS"), (photo_a, "INSPECTION")]
    with pytest.raises(ValueError, match="unselected"):
        curator.remove(WORKSPACE, photo_id=photo_a, expected_revision=5)
    for bad in ([{"photo_id": photo_a, "section": "CONCLUSIONS"}], [{"photo_id": photo_a, "section": "INSPECTION"}] * 2, [{"photo_id": "PHOTO-X", "section": "INSPECTION"}]):
        with pytest.raises(ValueError):
            curator.select(WORKSPACE, selection=bad, expected_revision=5)
    _, library = curator.select(WORKSPACE, selection=[], expected_revision=5)
    _, library = curator.remove(WORKSPACE, photo_id=photo_a, expected_revision=6)
    assert [item.photo_id for item in library.photos] == [photo_b]
    assert photo_library_from_mapping(photo_library_to_mapping(library)) == library
    assert GetPhotoLibrary(revisions).execute(WORKSPACE)[1] == library


def test_a_library_refuses_two_identities_for_the_same_bytes_and_a_broken_order() -> None:
    curator, _, private = _curator()
    _, library = curator.register(WORKSPACE, content_id=private.add(jpeg()), expected_revision=None)
    entry = library.photos[0]
    twin = PhotoEntry(**{**photo_library_to_mapping(library)["photos"][0], "photo_id": "PHOTO-00000000-0000-4000-8000-0000000000AA", "content_id": "99999999-0000-4000-8000-000000000000", "tags": ()})
    with pytest.raises(ValueError, match="original_sha256"):
        PhotoLibrary("1.0.0", WORKSPACE, (entry, twin))
    gap = PhotoEntry(**{**photo_library_to_mapping(library)["photos"][0], "caption": "Legenda", "report_section": "INSPECTION", "report_order": 2, "tags": ()})
    with pytest.raises(ValueError, match="order"):
        PhotoLibrary("1.0.0", WORKSPACE, (gap,))


def test_a_thumbnail_is_upright_small_and_carries_no_metadata() -> None:
    curator, revisions, private = _curator()
    _, library = curator.register(WORKSPACE, content_id=private.add(jpeg(size=(1600, 1200), orientation=6, gps=True)), expected_revision=None)
    preview = ReadPhotoThumbnail(GetPhotoLibrary(revisions), private).execute(WORKSPACE, library.photos[0].photo_id)
    with Image.open(BytesIO(preview)) as image:
        assert image.format == "JPEG" and max(image.size) <= 320 and image.size[1] > image.size[0]
        assert not image.getexif()


def test_the_photo_library_routes_register_curate_and_preview_through_the_local_api(tmp_path) -> None:
    import json

    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_document_intake_v1 import provision_private_root
    from tests.test_local_api_v1 import TOKEN, http_request

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_local_api(tmp_path / "case.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        def call(method, path, value=None, raw=None, headers=None):
            status, response_headers, body = http_request(runtime.server, method, path, value=value, raw_body=raw, headers={"X-Local-API-Token": TOKEN, **(headers or {})})
            return status, response_headers, body

        def upload(content):
            status, _h, body = call("POST", f"/v1/workspaces/{workspace}/inspection-photos", raw=content, headers={"Content-Type": "image/jpeg", "X-Document-Filename": "foto.jpg"})
            assert status == 201, body
            return json.loads(body)["content_id"]

        status, _h, body = call("POST", "/v1/workspaces", {"name": "Caso"})
        workspace = json.loads(body)["workspace_id"]
        base = f"/v1/workspaces/{workspace}/photo-library"
        assert call("GET", base)[0] == 404
        status, _h, body = call("POST", f"{base}/photos", {"expected_revision": None, "content_id": upload(jpeg())})
        assert status == 201
        photo_id = json.loads(body)["library"]["photos"][0]["photo_id"]
        status, _h, body = call("POST", f"{base}/photos", {"expected_revision": 1, "content_id": upload(jpeg())})
        assert status == 409 and json.loads(body)["error"] == {"code": "PHOTO_DUPLICATE", "message": "foto já está na biblioteca", "photo_id": photo_id}
        assert call("POST", f"{base}/descriptions", {"expected_revision": 1, "photo_id": photo_id, "caption": "Fissura", "tags": ["fachada"]})[0] == 200
        status, _h, body = call("POST", f"{base}/selection", {"expected_revision": 2, "selection": [{"photo_id": photo_id, "section": "INSPECTION"}]})
        assert status == 200 and json.loads(body)["library"]["photos"][0]["report_order"] == 1
        status, headers, preview = call("GET", f"{base}/photos/{photo_id}/thumbnail")
        assert status == 200 and headers["Content-Type"] == "image/jpeg" and preview.startswith(b"\xff\xd8\xff")
    finally:
        runtime.close()
