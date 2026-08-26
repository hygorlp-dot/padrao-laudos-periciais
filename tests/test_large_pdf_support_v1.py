from __future__ import annotations

import hashlib
import http.client
import json
import tracemalloc
from contextlib import contextmanager
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

import pytest

from scripts.backend_contract.application.content import (
    DOCUMENT_IO_CHUNK_BYTES,
    MAX_DOCUMENT_BYTES,
    SeekableContent,
)
from scripts.backend_contract.application.models import (
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    WorkspaceId,
)
from scripts.backend_contract.application.ports import PrivateContentTooLarge
from scripts.backend_contract.application.services import ImportCaseDocument, StorePrivateContent
from scripts.backend_contract.infrastructure.private_filesystem import (
    DEFAULT_PRIVATE_CONTENT_LIMIT_BYTES,
    LocalPrivateContentStore,
)
from scripts.backend_contract.local_api.server import LocalServerConfig
from scripts.backend_contract.local_api.transport import LocalApi, LocalApiServices
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig
from scripts.backend_contract.product_bridge.composition import build_product_runtime


MIB = 1024 * 1024
WORKSPACE_ID = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
CONTENT_ID = PrivateContentId(UUID("22222222-2222-4222-8222-222222222222"))


class ExistingWorkspace:
    def get(self, workspace_id):
        return object() if workspace_id == WORKSPACE_ID else None


class FixedClock:
    def now(self):
        return datetime(2026, 8, 26, 12, 30, tzinfo=UTC)


class FixedIds:
    def new_uuid(self):
        return CONTENT_ID.value


class VirtualPdf:
    """Fonte seekable grande sem alocação proporcional ao tamanho."""

    def __init__(self, size: int):
        self.size = size
        self.position = 0
        self.max_requested = 0

    def seek(self, offset: int, whence: int = 0):
        if whence == 0:
            position = offset
        elif whence == 1:
            position = self.position + offset
        elif whence == 2:
            position = self.size + offset
        else:
            raise ValueError("whence")
        if position < 0:
            raise ValueError("negative seek")
        self.position = position
        return position

    def tell(self):
        return self.position

    def read(self, size: int = -1):
        if size is None or size < 0:
            raise AssertionError("unbounded read is forbidden")
        self.max_requested = max(self.max_requested, size)
        remaining = max(0, self.size - self.position)
        count = min(size, remaining)
        start = self.position
        self.position += count
        result = bytearray(b"x" * count)
        prefix = b"%PDF-1.7\n"
        suffix = b"\n%%EOF\n"
        for marker_start, marker in ((0, prefix), (self.size - len(suffix), suffix)):
            overlap_start = max(start, marker_start)
            overlap_end = min(start + count, marker_start + len(marker))
            if overlap_start < overlap_end:
                source_start = overlap_start - marker_start
                target_start = overlap_start - start
                result[target_start : target_start + overlap_end - overlap_start] = marker[
                    source_start : source_start + overlap_end - overlap_start
                ]
        return bytes(result)


class StreamingSink:
    def __init__(self):
        self.metadata = None
        self.digest = None

    def store(self, metadata, content):
        digest = hashlib.sha256()
        content.rewind()
        remaining = content.byte_size
        while remaining:
            block = content.stream.read(min(DOCUMENT_IO_CHUNK_BYTES, remaining))
            assert block
            digest.update(block)
            remaining -= len(block)
        self.metadata = metadata
        self.digest = digest.hexdigest()
        return metadata

    def get(self, _workspace_id, _content_id):
        return None

    def list_all(self, _workspace_id):
        return ()


def services_for_limit(size: int):
    source_stream = VirtualPdf(size)
    source = SeekableContent(source_stream, size)
    sink = StreamingSink()
    service = ImportCaseDocument(
        StorePrivateContent(
            ExistingWorkspace(),
            sink,
            FixedClock(),
            FixedIds(),
            MAX_DOCUMENT_BYTES,
        )
    )
    return service, source, source_stream, sink


def test_one_canonical_inclusive_128_mib_contract_is_shared_by_every_layer():
    assert MAX_DOCUMENT_BYTES == 128 * MIB
    assert DEFAULT_PRIVATE_CONTENT_LIMIT_BYTES == MAX_DOCUMENT_BYTES
    assert LocalServerConfig().max_document_body_bytes == MAX_DOCUMENT_BYTES
    assert ProductBridgeConfig().max_document_body_bytes == MAX_DOCUMENT_BYTES


@pytest.mark.parametrize("size", (15 * MIB, 64 * MIB, 100 * MIB, 128 * MIB))
def test_representative_large_pdf_sizes_are_accepted_without_unbounded_reads(size):
    importer, source, source_stream, sink = services_for_limit(size)

    metadata = importer.execute(
        workspace_id=WORKSPACE_ID,
        original_filename="autos-sinteticos.pdf",
        content=source,
        media_type="application/pdf",
    )

    assert metadata.byte_size == size
    assert metadata.checksum_sha256 == sink.digest
    assert source_stream.max_requested <= DOCUMENT_IO_CHUNK_BYTES


def test_one_byte_above_128_mib_is_rejected_before_hash_or_storage():
    importer, source, source_stream, sink = services_for_limit(MAX_DOCUMENT_BYTES + 1)

    with pytest.raises(PrivateContentTooLarge, match="limite"):
        importer.execute(
            workspace_id=WORKSPACE_ID,
            original_filename="autos-grandes.pdf",
            content=source,
            media_type="application/pdf",
        )

    assert source_stream.max_requested == 0
    assert sink.metadata is None


def test_private_store_copies_hashes_opens_and_reopens_streamed_content(tmp_path):
    payload = b"%PDF-1.7\nsynthetic bounded document\n%%EOF\n"
    metadata = PrivateContentMetadata(
        workspace_id=WORKSPACE_ID,
        content_id=CONTENT_ID,
        original_filename="autos.pdf",
        byte_size=len(payload),
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/pdf",
        imported_at="2026-08-26T12:30:00+00:00",
        origin=PrivateContentOrigin.USER_IMPORT,
    )
    root = tmp_path / "private"

    with LocalPrivateContentStore.open_or_provision(root) as store:
        store.store(metadata, SeekableContent(BytesIO(payload), len(payload)))
        with store.open_content(WORKSPACE_ID, CONTENT_ID) as opened:
            assert opened.metadata == metadata
            assert opened.stream.read(5) == b"%PDF-"

    with LocalPrivateContentStore(root) as reopened:
        with reopened.open_content(WORKSPACE_ID, CONTENT_ID) as opened:
            digest = hashlib.sha256()
            while block := opened.stream.read(DOCUMENT_IO_CHUNK_BYTES):
                digest.update(block)
            assert digest.hexdigest() == metadata.checksum_sha256


def test_transport_rejects_configuration_above_canonical_document_limit():
    with pytest.raises(ValueError, match="limite"):
        LocalServerConfig(max_document_body_bytes=MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(ValueError, match="limite"):
        ProductBridgeConfig(max_document_body_bytes=MAX_DOCUMENT_BYTES + 1)


def test_local_api_accepts_canonical_document_limit_without_expanding_json_limit():
    inert = object()
    api = LocalApi(
        LocalApiServices(
            create_workspace=inert,
            get_workspace=inert,
            list_workspaces=inert,
            append_artifact_revision=inert,
            get_latest_artifact=inert,
            get_artifact_revision=inert,
            list_artifact_revisions=inert,
            get_process_case=inert,
            save_process_case=inert,
        ),
        token="bounded-document-test-token-with-entropy",
        max_document_body_bytes=MAX_DOCUMENT_BYTES,
    )

    assert api.body_limits == (1_048_576, MAX_DOCUMENT_BYTES)


def test_product_upload_and_read_stream_without_whole_document_memory_copies(tmp_path):
    build = tmp_path / "dist"
    build.mkdir()
    (build / "index.html").write_text("<!doctype html><title>test</title>", encoding="utf-8")
    runtime = build_product_runtime(
        tmp_path / "case.db",
        build,
        private_root=tmp_path / "private",
        token="streaming-product-flow-token-with-entropy",
        config=ProductBridgeConfig(request_timeout_seconds=30),
    )
    runtime.start()
    document_size = 100 * MIB
    source = tmp_path / "large.pdf"
    with source.open("wb") as stream:
        stream.write(b"%PDF-1.7\n")
        stream.seek(document_size - len(b"\n%%EOF\n"))
        stream.write(b"\n%%EOF\n")

    try:
        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        create_body = json.dumps({"name": "Perícia grande"}).encode()
        connection.request(
            "POST",
            "/app-api/v1/workspaces",
            body=create_body,
            headers={
                "Origin": runtime.origin,
                "Sec-Fetch-Site": "same-origin",
                "Content-Type": "application/json",
                "Content-Length": str(len(create_body)),
            },
        )
        created = connection.getresponse()
        workspace_id = json.loads(created.read())["workspace_id"]
        connection.close()

        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        connection.request(
            "POST",
            "/app-api/v1/workspaces",
            body=create_body,
            headers={
                "Origin": runtime.origin,
                "Sec-Fetch-Site": "same-origin",
                "Content-Type": "application/json",
                "Content-Length": str(len(create_body)),
            },
        )
        isolated_workspace_id = json.loads(connection.getresponse().read())["workspace_id"]
        connection.close()

        tracemalloc.start()
        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        connection.putrequest(
            "POST", f"/app-api/v1/workspaces/{workspace_id}/materials"
        )
        connection.putheader("Origin", runtime.origin)
        connection.putheader("Sec-Fetch-Site", "same-origin")
        connection.putheader("Content-Type", "application/pdf")
        connection.putheader("X-Document-Filename", "autos-grandes.pdf")
        connection.putheader("Content-Length", str(document_size))
        connection.endheaders()
        with source.open("rb") as stream:
            while block := stream.read(DOCUMENT_IO_CHUNK_BYTES):
                connection.send(block)
        imported_response = connection.getresponse()
        imported_body = imported_response.read()
        connection.close()
        imported = json.loads(imported_body)
        _current, upload_peak = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()

        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        connection.request(
            "GET", f"/app-api/v1/workspaces/{workspace_id}/materials"
        )
        catalog = connection.getresponse()
        catalog_payload = json.loads(catalog.read())
        connection.close()

        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        connection.request(
            "GET", f"/app-api/v1/workspaces/{isolated_workspace_id}/materials"
        )
        isolated_catalog = connection.getresponse()
        isolated_payload = json.loads(isolated_catalog.read())
        connection.close()

        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        connection.request(
            "GET",
            f"/app-api/v1/workspaces/{isolated_workspace_id}/materials/{imported['content_id']}",
        )
        isolated_open = connection.getresponse()
        isolated_open.read()
        connection.close()

        runtime.close()
        runtime = build_product_runtime(
            tmp_path / "case.db",
            build,
            private_root=tmp_path / "private",
            token="streaming-product-reopen-token-with-entropy",
            config=ProductBridgeConfig(request_timeout_seconds=30),
        )
        runtime.start()

        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        connection.request(
            "GET", f"/app-api/v1/workspaces/{workspace_id}/materials"
        )
        reopened_catalog = connection.getresponse()
        reopened_catalog_payload = json.loads(reopened_catalog.read())
        connection.close()

        connection = http.client.HTTPConnection(*runtime.address, timeout=30)
        connection.request(
            "GET",
            f"/app-api/v1/workspaces/{workspace_id}/materials/{imported['content_id']}",
        )
        opened = connection.getresponse()
        digest = hashlib.sha256()
        received = 0
        while block := opened.read(DOCUMENT_IO_CHUNK_BYTES):
            digest.update(block)
            received += len(block)
        connection.close()
        _current, download_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        runtime.close()

    assert imported_response.status == 201
    assert catalog.status == 200
    assert catalog_payload["items"][0]["content_id"] == imported["content_id"]
    assert isolated_catalog.status == 200
    assert isolated_payload["items"] == []
    assert isolated_open.status == 404
    assert reopened_catalog.status == 200
    assert reopened_catalog_payload == catalog_payload
    assert opened.status == 200
    assert received == document_size
    assert digest.hexdigest() == imported["checksum_sha256"]
    assert upload_peak < 20 * MIB
    assert download_peak < 20 * MIB
