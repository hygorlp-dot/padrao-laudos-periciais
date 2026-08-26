from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import (
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    WorkspaceId,
)
from scripts.backend_contract.application.ports import (
    InvalidCaseDocument,
    PrivateContentTooLarge,
    UnsupportedCaseDocument,
)
from scripts.backend_contract.application.services import (
    GetPrivateContent,
    ImportCaseDocument,
    ListCaseDocuments,
    ListPrivateContents,
    ReadCaseDocument,
    StorePrivateContent,
)
from scripts.backend_contract.local_api.transport import LocalApi, LocalApiServices
from scripts.backend_contract.local_api.composition import (
    LocalApiStartupError,
    build_local_api,
)
from scripts.backend_contract.local_api.server import (
    LocalApiServer,
    LocalApiServerStartError,
    LocalServerConfig,
)
from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig
from scripts.backend_contract.infrastructure import private_filesystem
from scripts.backend_contract.infrastructure.private_filesystem import (
    LocalPrivateContentStore,
    provision_private_content_root,
)


WORKSPACE_ID = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
CONTENT_ID = PrivateContentId(UUID("22222222-2222-4222-8222-222222222222"))
PDF = b"%PDF-1.7\nsynthetic case document\n%%EOF\n"
IMPORTED_AT = "2026-08-25T12:30:00+00:00"
TOKEN = "document-intake-test-token-with-entropy"


class ExistingWorkspace:
    def get(self, workspace_id):
        return object() if workspace_id == WORKSPACE_ID else None


class FixedClock:
    def now(self):
        return datetime(2026, 8, 25, 12, 30, tzinfo=UTC)


class FixedIds:
    def new_uuid(self):
        return CONTENT_ID.value


class MemoryContents:
    def __init__(self):
        self.records: dict[tuple[WorkspaceId, PrivateContentId], PrivateContent] = {}

    def store(self, metadata, content):
        self.records[(metadata.workspace_id, metadata.content_id)] = PrivateContent(
            metadata, content
        )
        return metadata

    def get(self, workspace_id, content_id):
        return self.records.get((workspace_id, content_id))

    def list_all(self, workspace_id):
        return tuple(
            record.metadata
            for (owner, _), record in self.records.items()
            if owner == workspace_id
        )


class RecordingService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


def metadata() -> PrivateContentMetadata:
    return PrivateContentMetadata(
        workspace_id=WORKSPACE_ID,
        content_id=CONTENT_ID,
        original_filename="Autos sintéticos.pdf",
        byte_size=len(PDF),
        checksum_sha256=hashlib.sha256(PDF).hexdigest(),
        media_type="application/pdf",
        imported_at=IMPORTED_AT,
        origin=PrivateContentOrigin.USER_IMPORT,
    )


def api_services(**overrides):
    inert = RecordingService(None)
    values = {
        "create_workspace": inert,
        "get_workspace": inert,
        "list_workspaces": inert,
        "append_artifact_revision": inert,
        "get_latest_artifact": inert,
        "get_artifact_revision": inert,
        "list_artifact_revisions": inert,
        "get_process_case": inert,
        "save_process_case": inert,
        "import_case_document": RecordingService(metadata()),
        "list_case_documents": RecordingService((metadata(),)),
        "read_case_document": RecordingService(PrivateContent(metadata(), PDF)),
    }
    values.update(overrides)
    return LocalApiServices(**values)


def document_services(*, max_bytes=1024):
    contents = MemoryContents()
    workspaces = ExistingWorkspace()
    store = StorePrivateContent(
        workspaces=workspaces,
        contents=contents,
        clock=FixedClock(),
        ids=FixedIds(),
        max_content_bytes=max_bytes,
    )
    return (
        ImportCaseDocument(store),
        ListCaseDocuments(ListPrivateContents(workspaces, contents)),
        ReadCaseDocument(GetPrivateContent(workspaces, contents)),
    )


def test_import_pdf_preserves_exact_bytes_integrity_and_user_import_provenance():
    importer, listed, reader = document_services()

    metadata = importer.execute(
        workspace_id=WORKSPACE_ID,
        original_filename="Autos sintéticos.pdf",
        content=PDF,
        media_type="application/pdf",
    )

    assert metadata == PrivateContentMetadata(
        workspace_id=WORKSPACE_ID,
        content_id=CONTENT_ID,
        original_filename="Autos sintéticos.pdf",
        byte_size=len(PDF),
        checksum_sha256=hashlib.sha256(PDF).hexdigest(),
        media_type="application/pdf",
        imported_at=IMPORTED_AT,
        origin=PrivateContentOrigin.USER_IMPORT,
    )
    assert listed.execute(WORKSPACE_ID) == (metadata,)
    assert reader.execute(WORKSPACE_ID, CONTENT_ID) == PrivateContent(metadata, PDF)


def test_case_document_limit_remains_16_mib_when_transport_limit_is_higher():
    content = b"%PDF-1.7\n" + (b"x" * 16_777_201) + b"\n%%EOF\n"
    importer, listed, _reader = document_services(max_bytes=len(content))

    with pytest.raises(PrivateContentTooLarge, match="limite"):
        importer.execute(
            workspace_id=WORKSPACE_ID,
            original_filename="oversized.pdf",
            content=content,
            media_type="application/pdf",
        )

    assert listed.execute(WORKSPACE_ID) == ()


@pytest.mark.parametrize("media_type", ("text/plain", "application/octet-stream", ""))
def test_import_rejects_unsupported_media_type_before_storage(media_type):
    importer, listed, _reader = document_services()

    with pytest.raises(UnsupportedCaseDocument, match="PDF"):
        importer.execute(
            workspace_id=WORKSPACE_ID,
            original_filename="autos.pdf",
            content=PDF,
            media_type=media_type,
        )

    assert listed.execute(WORKSPACE_ID) == ()


@pytest.mark.parametrize("content", (b"", b"not a pdf", b"%PDF-1.7\nmissing eof"))
def test_import_rejects_invalid_pdf_bytes_before_storage(content):
    importer, listed, _reader = document_services()

    with pytest.raises(InvalidCaseDocument, match="PDF"):
        importer.execute(
            workspace_id=WORKSPACE_ID,
            original_filename="autos.pdf",
            content=content,
            media_type="application/pdf",
        )

    assert listed.execute(WORKSPACE_ID) == ()


def test_import_reports_the_existing_bounded_size_contract():
    importer, listed, _reader = document_services(max_bytes=len(PDF) - 1)

    with pytest.raises(PrivateContentTooLarge, match="limite"):
        importer.execute(
            workspace_id=WORKSPACE_ID,
            original_filename="autos.pdf",
            content=PDF,
            media_type="application/pdf",
        )

    assert listed.execute(WORKSPACE_ID) == ()


def test_case_document_views_fail_closed_for_non_pdf_private_records():
    _importer, listed, reader = document_services()
    metadata = PrivateContentMetadata(
        workspace_id=WORKSPACE_ID,
        content_id=CONTENT_ID,
        original_filename="notes.txt",
        byte_size=3,
        checksum_sha256=hashlib.sha256(b"abc").hexdigest(),
        media_type="text/plain",
        imported_at=IMPORTED_AT,
        origin=PrivateContentOrigin.LOCAL_IMPORT,
    )
    listed.contents.contents.store(metadata, b"abc")

    with pytest.raises(InvalidCaseDocument, match="contrato"):
        listed.execute(WORKSPACE_ID)
    with pytest.raises(InvalidCaseDocument, match="contrato"):
        reader.execute(WORKSPACE_ID, CONTENT_ID)


def test_local_api_imports_raw_pdf_with_decoded_filename_metadata():
    services = api_services()
    response = LocalApi(services, token=TOKEN).handle(
        "POST",
        f"/v1/workspaces/{WORKSPACE_ID}/materials",
        {
            "Host": "127.0.0.1",
            "X-Local-API-Token": TOKEN,
            "Content-Type": "application/pdf",
            "Content-Length": str(len(PDF)),
            "X-Document-Filename": "Autos%20sint%C3%A9ticos.pdf",
        },
        PDF,
    )

    assert response.status == 201
    assert json.loads(response.body)["content_id"] == str(CONTENT_ID)
    assert services.import_case_document.calls == [
        (
            (),
            {
                "workspace_id": WORKSPACE_ID,
                "original_filename": "Autos sintéticos.pdf",
                "content": PDF,
                "media_type": "application/pdf",
            },
        )
    ]


def test_local_api_lists_safe_metadata_and_never_serializes_a_private_path():
    services = api_services()
    response = LocalApi(services, token=TOKEN).handle(
        "GET",
        f"/v1/workspaces/{WORKSPACE_ID}/materials",
        {"Host": "127.0.0.1", "X-Local-API-Token": TOKEN},
        b"",
    )

    assert response.status == 200
    payload = json.loads(response.body)
    assert payload == {
        "items": [
            {
                "workspace_id": str(WORKSPACE_ID),
                "content_id": str(CONTENT_ID),
                "original_filename": "Autos sintéticos.pdf",
                "byte_size": len(PDF),
                "checksum_sha256": hashlib.sha256(PDF).hexdigest(),
                "media_type": "application/pdf",
                "imported_at": IMPORTED_AT,
                "origin": "USER_IMPORT",
            }
        ]
    }
    assert "path" not in response.body.decode("utf-8").lower()


def test_local_api_reads_exact_pdf_bytes_only_with_private_token():
    services = api_services()
    target = f"/v1/workspaces/{WORKSPACE_ID}/materials/{CONTENT_ID}"
    api = LocalApi(services, token=TOKEN)

    denied = api.handle("GET", target, {"Host": "127.0.0.1"}, b"")
    response = api.handle(
        "GET", target, {"Host": "127.0.0.1", "X-Local-API-Token": TOKEN}, b""
    )

    assert denied.status == 403
    assert response.status == 200
    assert response.body == PDF
    assert response.headers["Content-Type"] == "application/pdf"
    assert response.headers["Cache-Control"] == "no-store"
    assert services.read_case_document.calls == [((WORKSPACE_ID, CONTENT_ID), {})]


@pytest.mark.parametrize(
    "headers",
    (
        {"Content-Type": "application/pdf", "Content-Length": str(len(PDF))},
        {
            "Content-Type": "application/pdf",
            "Content-Length": str(len(PDF)),
            "X-Document-Filename": "%ZZ",
        },
        {
            "Content-Type": "text/plain",
            "Content-Length": str(len(PDF)),
            "X-Document-Filename": "autos.pdf",
        },
    ),
)
def test_local_api_rejects_malformed_document_transport_without_calling_application(headers):
    services = api_services()
    response = LocalApi(services, token=TOKEN).handle(
        "POST",
        f"/v1/workspaces/{WORKSPACE_ID}/materials",
        {"Host": "127.0.0.1", "X-Local-API-Token": TOKEN, **headers},
        PDF,
    )

    assert response.status == 400
    assert services.import_case_document.calls == []


def provision_private_root(root: Path) -> None:
    provision_private_content_root(root)


def test_explicit_private_root_provisioning_creates_only_exact_controls_and_is_idempotent(tmp_path):
    root = tmp_path / "private"

    provision_private_content_root(root)
    provision_private_content_root(root)

    assert {path.name: path.read_bytes() for path in root.iterdir()} == {
        ".store-lock": b"0",
        ".commit-log": b"",
        ".commit-anchor": b"",
    }
    with LocalPrivateContentStore(root):
        pass


def test_partial_private_root_provisioning_fails_closed_without_filling_gaps(tmp_path):
    root = tmp_path / "partial"
    root.mkdir()
    (root / ".store-lock").write_bytes(b"wrong")

    with pytest.raises(Exception, match="provision|controle|private root"):
        provision_private_content_root(root)

    assert [path.name for path in root.iterdir()] == [".store-lock"]


def test_private_root_provisioning_rejects_a_control_symlink(tmp_path):
    root = tmp_path / "linked"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"0")
    try:
        (root / ".store-lock").symlink_to(outside)
    except OSError:
        pytest.skip("symlink indisponível neste host")
    (root / ".commit-log").write_bytes(b"")
    (root / ".commit-anchor").write_bytes(b"")

    with pytest.raises(Exception, match="regular|reparse|simbólico|controle"):
        provision_private_content_root(root)


@pytest.mark.skipif(os.name != "nt", reason="Windows pathname provisioning race")
def test_private_root_provisioning_rejects_regular_root_swap_before_first_control(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    original_root = tmp_path / "original-private"
    replacement = tmp_path / "replacement-private"
    replacement.mkdir()
    original_open = private_filesystem.os.open
    swapped = False

    def swap_before_first_control(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if Path(path) == root / ".store-lock" and not swapped:
            swapped = True
            root.rename(original_root)
            replacement.rename(root)
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(private_filesystem.os, "open", swap_before_first_control)

    with pytest.raises(Exception, match="identidade|private root|provision"):
        provision_private_content_root(root)

    assert {path.name: path.read_bytes() for path in root.iterdir()} == {
        ".store-lock": b""
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows pathname provisioning race")
def test_private_root_provisioning_holds_anchor_while_creating_later_controls(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    moved = tmp_path / "moved-private"
    original_open = private_filesystem.os.open
    rename_blocked = False

    def attempt_swap_before_second_control(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal rename_blocked
        if Path(path) == root / ".commit-log" and not rename_blocked:
            with pytest.raises(OSError):
                root.rename(moved)
            rename_blocked = True
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(
        private_filesystem.os, "open", attempt_swap_before_second_control
    )

    provision_private_content_root(root)

    assert rename_blocked is True
    assert {path.name: path.read_bytes() for path in root.iterdir()} == {
        ".store-lock": b"0",
        ".commit-log": b"",
        ".commit-anchor": b"",
    }


@pytest.mark.skipif(os.name != "posix", reason="POSIX dirfd provisioning race")
def test_posix_new_root_swap_is_rejected_before_first_control(tmp_path, monkeypatch):
    root = tmp_path / "private"
    original_root = tmp_path / "original-private"
    replacement = tmp_path / "replacement-private"
    replacement.mkdir()
    original_open = private_filesystem.os.open
    swapped = False

    def swap_before_root_fd(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if Path(path) == root and dir_fd is None and not swapped:
            root.rename(original_root)
            replacement.rename(root)
            swapped = True
        if dir_fd is None:
            return original_open(path, flags, mode)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(private_filesystem.os, "open", swap_before_root_fd)

    with pytest.raises(Exception, match="identidade|private root|provision"):
        provision_private_content_root(root)

    assert swapped is True
    assert list(root.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows parent custody")
def test_windows_parent_swap_is_blocked_before_private_root_creation(
    tmp_path, monkeypatch
):
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "private"
    moved_parent = tmp_path / "moved-parent"
    replacement_parent = tmp_path / "replacement-parent"
    replacement_parent.mkdir()
    original_mkdir = private_filesystem.os.mkdir
    swap_blocked = False

    def swap_parent_before_mkdir(path, mode=0o777, *, dir_fd=None):
        nonlocal swap_blocked
        if Path(path) == root and dir_fd is None:
            try:
                parent.rename(moved_parent)
                replacement_parent.rename(parent)
            except PermissionError:
                swap_blocked = True
                raise
        if dir_fd is None:
            return original_mkdir(path, mode)
        return original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(private_filesystem.os, "mkdir", swap_parent_before_mkdir)

    with pytest.raises(Exception):
        provision_private_content_root(root)

    assert swap_blocked is True
    assert parent.exists()
    assert list(parent.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX parent dirfd custody")
def test_posix_parent_swap_never_redirects_private_root_creation(
    tmp_path, monkeypatch
):
    parent = tmp_path / "parent"
    parent.mkdir()
    root = parent / "private"
    moved_parent = tmp_path / "moved-parent"
    replacement_parent = tmp_path / "replacement-parent"
    replacement_parent.mkdir()
    original_mkdir = private_filesystem.os.mkdir
    swapped = False

    def swap_parent_before_mkdir(path, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == root.name and dir_fd is not None and not swapped:
            parent.rename(moved_parent)
            replacement_parent.rename(parent)
            swapped = True
        if dir_fd is None:
            return original_mkdir(path, mode)
        return original_mkdir(path, mode, dir_fd=dir_fd)

    monkeypatch.setattr(private_filesystem.os, "mkdir", swap_parent_before_mkdir)

    with pytest.raises(Exception, match="identidade|private root|provision"):
        provision_private_content_root(root)

    assert swapped is True
    assert list(parent.iterdir()) == []
    assert (moved_parent / "private").is_dir()
    assert list((moved_parent / "private").iterdir()) == []


def test_local_api_start_failure_releases_the_private_store(monkeypatch, tmp_path):
    root = tmp_path / "private"
    provision_private_content_root(root)
    runtime = build_local_api(tmp_path / "case.db", private_root=root, token=TOKEN)
    monkeypatch.setattr(
        runtime.server,
        "start",
        lambda: (_ for _ in ()).throw(LocalApiServerStartError("synthetic")),
    )

    with pytest.raises(LocalApiStartupError, match="indisponível"):
        runtime.start()

    with LocalPrivateContentStore(root):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows provisioning handoff race")
@pytest.mark.parametrize("root_preexists", (False, True))
def test_local_api_composition_keeps_root_anchored_through_store_open(
    tmp_path, monkeypatch, root_preexists
):
    root = tmp_path / "private"
    original_root = tmp_path / "original-private"
    replacement = tmp_path / "replacement-private"
    provision_private_content_root(replacement)
    if root_preexists:
        provision_private_content_root(root)
    original_init = LocalPrivateContentStore.__init__
    swap_blocked = False

    def attempt_handoff_swap(self, private_root, *args, **kwargs):
        nonlocal swap_blocked
        if Path(private_root) == root and not swap_blocked:
            try:
                root.rename(original_root)
            except OSError:
                swap_blocked = True
            else:
                replacement.rename(root)
        original_init(self, private_root, *args, **kwargs)

    monkeypatch.setattr(LocalPrivateContentStore, "__init__", attempt_handoff_swap)
    runtime = build_local_api(tmp_path / "case.db", private_root=root, token=TOKEN)
    try:
        assert swap_blocked is True
    finally:
        runtime.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX dirfd handoff")
@pytest.mark.parametrize("root_preexists", (False, True))
def test_posix_composition_fails_closed_on_root_swap_during_store_open(
    tmp_path, monkeypatch, root_preexists
):
    root = tmp_path / "private"
    original_root = tmp_path / "original-private"
    replacement = tmp_path / "replacement-private"
    provision_private_content_root(replacement)
    if root_preexists:
        provision_private_content_root(root)
    original_init = LocalPrivateContentStore.__init__
    swapped = False

    def swap_during_handoff(self, private_root, *args, **kwargs):
        nonlocal swapped
        if Path(private_root) == root and not swapped:
            root.rename(original_root)
            replacement.rename(root)
            swapped = True
        original_init(self, private_root, *args, **kwargs)

    monkeypatch.setattr(LocalPrivateContentStore, "__init__", swap_during_handoff)

    with pytest.raises(Exception, match="identidade|private root|handoff"):
        build_local_api(tmp_path / "case.db", private_root=root, token=TOKEN)

    assert swapped is True
    assert sorted(path.name for path in root.iterdir()) == [
        ".commit-anchor",
        ".commit-log",
        ".store-lock",
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows provisioning handoff")
def test_ambiguous_handoff_anchor_close_is_never_retried(tmp_path, monkeypatch):
    captured = {"descriptor": None, "close_calls": 0}
    original_take = private_filesystem._ProvisionedRootHandoff.take
    original_close = private_filesystem.os.close

    def capture_handoff(handoff):
        identity, root_fd, windows_anchor_fd = original_take(handoff)
        captured["descriptor"] = windows_anchor_fd
        return identity, root_fd, windows_anchor_fd

    def ambiguous_close(descriptor):
        if descriptor == captured["descriptor"]:
            captured["close_calls"] += 1
            if captured["close_calls"] == 1:
                original_close(descriptor)
                raise OSError("synthetic ambiguous handoff close failure")
        return original_close(descriptor)

    monkeypatch.setattr(
        private_filesystem._ProvisionedRootHandoff, "take", capture_handoff
    )
    monkeypatch.setattr(private_filesystem.os, "close", ambiguous_close)

    with pytest.raises(Exception):
        build_local_api(tmp_path / "case.db", private_root=tmp_path / "private", token=TOKEN)

    assert captured["close_calls"] == 1


def test_local_api_reopens_valid_store_content_above_the_intake_limit(tmp_path):
    root = tmp_path / "private"
    provision_private_content_root(root)
    content = b"x" * (16_777_216 + 1)
    stored = PrivateContentMetadata(
        workspace_id=WORKSPACE_ID,
        content_id=CONTENT_ID,
        original_filename="legacy-large.bin",
        byte_size=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        media_type="application/octet-stream",
        imported_at=IMPORTED_AT,
        origin=PrivateContentOrigin.LOCAL_IMPORT,
    )
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(stored, content)

    runtime = build_local_api(tmp_path / "case.db", private_root=root, token=TOKEN)
    runtime.close()


def frontend_build(root: Path) -> Path:
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><div id='root'></div>", encoding="utf-8")
    return root


def product_request(runtime, method, target, *, body=b"", headers=None):
    request_headers = dict(headers or {})
    request_headers.setdefault("Content-Length", str(len(body)))
    connection = http.client.HTTPConnection(*runtime.address, timeout=5)
    try:
        connection.request(method, target, body=body or None, headers=request_headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def raw_product_request(runtime, payload: bytes) -> bytes:
    client = socket.create_connection(runtime.address, timeout=5)
    try:
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while chunk := client.recv(65_536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        client.close()


def create_workspace(runtime, name: str) -> str:
    body = json.dumps({"name": name}).encode("utf-8")
    status, _headers, response = product_request(
        runtime,
        "POST",
        "/app-api/v1/workspaces",
        body=body,
        headers={
            "Origin": runtime.origin,
            "Sec-Fetch-Site": "same-origin",
            "Content-Type": "application/json",
        },
    )
    assert status == 201
    return json.loads(response)["workspace_id"]


def import_pdf(runtime, workspace_id: str, filename: str, content=PDF):
    return product_request(
        runtime,
        "POST",
        f"/app-api/v1/workspaces/{workspace_id}/materials",
        body=content,
        headers={
            "Origin": runtime.origin,
            "Sec-Fetch-Site": "same-origin",
            "Content-Type": "application/pdf",
            "X-Document-Filename": quote(filename, safe="-._~"),
        },
    )


def test_document_transport_limit_does_not_expand_legacy_json_limit(tmp_path):
    assert LocalServerConfig().max_body_bytes == 1_048_576
    assert LocalServerConfig().max_document_body_bytes == 16_777_216
    assert ProductBridgeConfig().max_body_bytes == 1_048_576
    assert ProductBridgeConfig().max_document_body_bytes == 16_777_216

    runtime = build_product_runtime(
        tmp_path / "case.db",
        frontend_build(tmp_path / "dist"),
        private_root=tmp_path / "private",
        token=TOKEN,
    )
    runtime.start()
    try:
        oversized_json = json.dumps({"name": "x" * 1_048_576}).encode("utf-8")
        json_status, _headers, _body = product_request(
            runtime,
            "POST",
            "/app-api/v1/workspaces",
            body=oversized_json,
            headers={
                "Origin": runtime.origin,
                "Sec-Fetch-Site": "same-origin",
                "Content-Type": "application/json",
            },
        )
        workspace_id = create_workspace(runtime, "Perícia documental")
        document = b"%PDF-1.7\n" + (b"x" * 1_048_576) + b"\n%%EOF\n"
        document_status, _headers, document_body = import_pdf(
            runtime, workspace_id, "autos.pdf", document
        )
        content_id = json.loads(document_body)["content_id"]
        read_status, _headers, read_body = product_request(
            runtime,
            "GET",
            f"/app-api/v1/workspaces/{workspace_id}/materials/{content_id}",
        )
    finally:
        runtime.close()

    assert json_status == 400
    assert document_status == 201
    assert read_status == 200
    assert read_body == document


@pytest.mark.parametrize(
    ("config_type", "overrides"),
    (
        (LocalServerConfig, {"max_body_bytes": 1_048_577}),
        (LocalServerConfig, {"max_document_body_bytes": 16_777_217}),
        (ProductBridgeConfig, {"max_body_bytes": 1_048_577}),
        (ProductBridgeConfig, {"max_document_body_bytes": 16_777_217}),
    ),
)
def test_transport_configuration_cannot_raise_contractual_body_limits(
    config_type, overrides
):
    with pytest.raises(ValueError, match="limite"):
        config_type(**overrides)


def test_local_server_rejects_transport_cap_divergence_and_malformed_expansion():
    services = api_services()
    api = LocalApi(
        services,
        token=TOKEN,
        max_body_bytes=8,
        max_document_body_bytes=4,
    )

    with pytest.raises(ValueError, match="limite"):
        LocalApiServer(
            api,
            LocalServerConfig(max_body_bytes=8, max_document_body_bytes=1),
        )

    with pytest.raises(ValueError, match="limite"):
        LocalApi(
            services,
            token=TOKEN,
            max_document_body_bytes=16_777_217,
        )

    assert (
        api.request_body_limit(
            "POST", "/v1/workspaces/not-a-canonical-uuid/materials"
        )
        == 8
    )


def test_product_flow_imports_reads_isolates_and_reopens_pdf_without_path_or_token(tmp_path):
    database = tmp_path / "case.db"
    private_root = tmp_path / "private"
    build = frontend_build(tmp_path / "dist")

    first = build_product_runtime(
        database, build, private_root=private_root, token=TOKEN
    )
    first.start()
    try:
        workspace_a = create_workspace(first, "Perícia A")
        workspace_b = create_workspace(first, "Perícia B")
        status, _headers, imported_body = import_pdf(
            first, workspace_a, "../../Autos sintéticos.pdf"
        )
        assert status == 201
        imported = json.loads(imported_body)
        content_id = imported["content_id"]
        assert imported["original_filename"] == "../../Autos sintéticos.pdf"
        assert imported["checksum_sha256"] == hashlib.sha256(PDF).hexdigest()

        duplicate_status, _headers, duplicate_body = import_pdf(
            first, workspace_a, "../../Autos sintéticos.pdf"
        )
        assert duplicate_status == 201
        assert json.loads(duplicate_body)["content_id"] != content_id

        denied_status, _headers, _body = product_request(
            first,
            "GET",
            f"/app-api/v1/workspaces/{workspace_b}/materials/{content_id}",
        )
        assert denied_status == 404
    finally:
        first.close()

    provision_private_content_root(private_root)
    reopened = build_product_runtime(
        database, build, private_root=private_root, token=TOKEN
    )
    reopened.start()
    try:
        list_status, _headers, list_body = product_request(
            reopened, "GET", f"/app-api/v1/workspaces/{workspace_a}/materials"
        )
        read_status, read_headers, read_body = product_request(
            reopened,
            "GET",
            f"/app-api/v1/workspaces/{workspace_a}/materials/{content_id}",
        )
    finally:
        reopened.close()

    assert list_status == 200
    assert len(json.loads(list_body)["items"]) == 2
    assert read_status == 200
    assert read_headers["Content-Type"] == "application/pdf"
    assert read_body == PDF
    browser_facing = imported_body + list_body + read_body
    assert str(private_root).encode() not in browser_facing
    assert TOKEN.encode() not in browser_facing


def test_product_bridge_rejects_duplicate_document_filename_before_import(tmp_path):
    private_root = tmp_path / "private"
    provision_private_content_root(private_root)
    runtime = build_product_runtime(
        tmp_path / "case.db",
        frontend_build(tmp_path / "dist"),
        private_root=private_root,
        token=TOKEN,
    )
    runtime.start()
    try:
        workspace_id = create_workspace(runtime, "Perícia A")
        response = raw_product_request(
            runtime,
            (
                f"POST /app-api/v1/workspaces/{workspace_id}/materials HTTP/1.1\r\n"
                f"Host: {runtime.address[0]}:{runtime.address[1]}\r\n"
                f"Origin: {runtime.origin}\r\n"
                "Sec-Fetch-Site: same-origin\r\n"
                "Content-Type: application/pdf\r\n"
                "X-Document-Filename: first.pdf\r\n"
                "X-Document-Filename: second.pdf\r\n"
                f"Content-Length: {len(PDF)}\r\n\r\n"
            ).encode("ascii") + PDF,
        )
        status, _headers, listed = product_request(
            runtime, "GET", f"/app-api/v1/workspaces/{workspace_id}/materials"
        )
    finally:
        runtime.close()

    assert response.startswith(b"HTTP/1.1 400")
    assert status == 200
    assert json.loads(listed) == {"items": []}
