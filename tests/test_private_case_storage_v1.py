import ast
import hashlib
import json
import shutil
import stat
import subprocess
import threading
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import (
    PericiaWorkspace,
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    WorkspaceId,
)
from scripts.backend_contract.application.ports import (
    PrivateContentNotFound,
    PrivateContentRepository,
    RepositoryConflict,
    RepositoryError,
    RepositoryIntegrityError,
    WorkspaceNotFound,
)
from scripts.backend_contract.application.services import (
    GetPrivateContent,
    ListPrivateContents,
    StorePrivateContent,
)
from scripts.backend_contract.infrastructure import private_filesystem
from scripts.backend_contract.infrastructure.private_filesystem import (
    LocalPrivateContentStore,
)
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore


WORKSPACE_A = WorkspaceId.parse("11111111-1111-4111-8111-111111111111")
WORKSPACE_B = WorkspaceId.parse("22222222-2222-4222-8222-222222222222")
CONTENT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CONTENT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
IMPORTED_AT = "2026-08-24T12:30:00+00:00"


class FixedClock:
    def now(self):
        return datetime.fromisoformat(IMPORTED_AT)


class SequenceIds:
    def __init__(self, *values):
        self._values = iter(UUID(value) for value in values)

    def new_uuid(self):
        return next(self._values)


def _workspace(workspace_id, name):
    return PericiaWorkspace(workspace_id, name, "2026-08-24T12:00:00+00:00")


def _metadata(
    *,
    workspace_id=WORKSPACE_A,
    content_id=CONTENT_A,
    content=b"synthetic private bytes",
    filename="documento.bin",
    media_type="application/octet-stream",
):
    return PrivateContentMetadata(
        workspace_id=workspace_id,
        content_id=PrivateContentId.parse(content_id),
        original_filename=filename,
        byte_size=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        media_type=media_type,
        imported_at=IMPORTED_AT,
        origin=PrivateContentOrigin.LOCAL_IMPORT,
    )


def _services(sqlite_store, private_store, *ids, max_bytes=1024 * 1024):
    return (
        StorePrivateContent(
            workspaces=sqlite_store.workspaces,
            contents=private_store,
            clock=FixedClock(),
            ids=SequenceIds(*ids),
            max_content_bytes=max_bytes,
        ),
        GetPrivateContent(sqlite_store.workspaces, private_store),
        ListPrivateContents(sqlite_store.workspaces, private_store),
    )


def _create_workspaces(sqlite_store):
    sqlite_store.workspaces.create(_workspace(WORKSPACE_A, "Workspace A"))
    sqlite_store.workspaces.create(_workspace(WORKSPACE_B, "Workspace B"))


def _content_dir(root, workspace_id=WORKSPACE_A, content_id=CONTENT_A):
    return (
        root
        / "workspaces"
        / str(workspace_id)
        / "contents"
        / str(PrivateContentId.parse(content_id))
    )


def test_private_content_records_are_canonical_immutable_and_path_free():
    raw = b"\x00\xffconteudo sintetico"
    metadata = _metadata(
        content=raw,
        filename="Laudo técnico — versão 01.pdf",
        media_type="application/pdf; profile=synthetic",
    )
    record = PrivateContent(metadata=metadata, content=raw)

    assert str(metadata.content_id) == CONTENT_A
    assert metadata.original_filename == "Laudo técnico — versão 01.pdf"
    assert metadata.byte_size == len(raw)
    assert metadata.checksum_sha256 == hashlib.sha256(raw).hexdigest()
    assert metadata.media_type == "application/pdf; profile=synthetic"
    assert metadata.imported_at == IMPORTED_AT
    assert metadata.origin is PrivateContentOrigin.LOCAL_IMPORT
    assert record.content == raw
    assert not ({"path", "storage_path", "private_root"} & set(metadata.__slots__))
    with pytest.raises(FrozenInstanceError):
        metadata.original_filename = "alterado.pdf"


@pytest.mark.parametrize(
    "value",
    (
        "",
        "not-a-uuid",
        "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        "{aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa}",
        "../aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "C:\\aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "\\\\server\\share\\aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    ),
)
def test_private_content_id_rejects_malformed_or_noncanonical_identity(value):
    with pytest.raises((TypeError, ValueError)):
        PrivateContentId.parse(value)


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"original_filename": ""}, ValueError),
        ({"byte_size": -1}, ValueError),
        ({"byte_size": True}, ValueError),
        ({"checksum_sha256": "A" * 64}, ValueError),
        ({"media_type": ""}, ValueError),
        ({"imported_at": "2026-08-24T12:30:00"}, ValueError),
        ({"origin": "LOCAL_IMPORT"}, TypeError),
    ),
)
def test_private_content_metadata_rejects_invalid_contract(changes, error):
    values = {
        "workspace_id": WORKSPACE_A,
        "content_id": PrivateContentId.parse(CONTENT_A),
        "original_filename": "documento.bin",
        "byte_size": 1,
        "checksum_sha256": hashlib.sha256(b"x").hexdigest(),
        "media_type": None,
        "imported_at": IMPORTED_AT,
        "origin": PrivateContentOrigin.LOCAL_IMPORT,
    }
    values.update(changes)
    with pytest.raises(error):
        PrivateContentMetadata(**values)


def test_private_content_record_rejects_size_hash_and_mutable_payload_mismatch():
    metadata = _metadata(content=b"expected")
    with pytest.raises(ValueError, match="conteúdo privado"):
        PrivateContent(metadata, b"different")
    with pytest.raises(TypeError, match="bytes"):
        PrivateContent(metadata, bytearray(b"expected"))


def test_private_content_repository_has_only_create_read_list_operations():
    methods = {
        name for name in PrivateContentRepository.__dict__ if not name.startswith("_")
    }
    assert methods == {"store", "get", "list_all"}
    hints = get_type_hints(PrivateContentRepository.get)
    assert hints["return"] == PrivateContent | None


def test_nonexistent_workspace_is_rejected_before_any_private_write(tmp_path):
    with SQLiteApplicationStore(tmp_path / "application.db") as sqlite_store:
        with LocalPrivateContentStore(tmp_path / "private") as private_store:
            store, _, _ = _services(sqlite_store, private_store, CONTENT_A)
            with pytest.raises(WorkspaceNotFound, match="workspace não encontrado"):
                store.execute(
                    workspace_id=WORKSPACE_A,
                    original_filename="ausente.bin",
                    content=b"must not be written",
                    media_type=None,
                    origin=PrivateContentOrigin.LOCAL_IMPORT,
                )
            assert private_store.list_all(WORKSPACE_A) == ()


def test_application_round_trip_reopens_exact_bytes_metadata_and_workspace(tmp_path):
    database = tmp_path / "application.db"
    private_root = tmp_path / "private"
    payload = b"\x00\x01\xffsynthetic\x00payload"

    with SQLiteApplicationStore(database) as sqlite_store:
        _create_workspaces(sqlite_store)
        with LocalPrivateContentStore(private_root) as private_store:
            store, get, _ = _services(sqlite_store, private_store, CONTENT_A)
            created = store.execute(
                workspace_id=WORKSPACE_A,
                original_filename="Inspeção — ção.bin",
                content=payload,
                media_type="application/octet-stream",
                origin=PrivateContentOrigin.LOCAL_IMPORT,
            )
            immediate = get.execute(WORKSPACE_A, created.content_id)
            assert immediate == PrivateContent(created, payload)

    with SQLiteApplicationStore(database) as reopened_sqlite:
        with LocalPrivateContentStore(private_root) as reopened_private:
            _, get, list_contents = _services(
                reopened_sqlite, reopened_private, CONTENT_B
            )
            reopened = get.execute(WORKSPACE_A, PrivateContentId.parse(CONTENT_A))
            assert reopened.content == payload
            assert reopened.metadata == created
            assert list_contents.execute(WORKSPACE_A) == (created,)


def test_empty_file_and_nullable_media_type_round_trip(tmp_path):
    with SQLiteApplicationStore(tmp_path / "application.db") as sqlite_store:
        _create_workspaces(sqlite_store)
        with LocalPrivateContentStore(tmp_path / "private") as private_store:
            store, get, _ = _services(sqlite_store, private_store, CONTENT_A)
            metadata = store.execute(
                workspace_id=WORKSPACE_A,
                original_filename="vazio.txt",
                content=b"",
                media_type=None,
                origin=PrivateContentOrigin.LOCAL_IMPORT,
            )
            assert metadata.byte_size == 0
            assert metadata.checksum_sha256 == hashlib.sha256(b"").hexdigest()
            assert get.execute(WORKSPACE_A, metadata.content_id).content == b""


@pytest.mark.parametrize(
    "filename",
    (
        "../outside.pdf",
        "/tmp/outside.pdf",
        "C:\\private\\outside.pdf",
        "\\\\server\\share\\outside.pdf",
        "mixed/..\\outside.pdf",
    ),
)
def test_caller_filename_is_literal_metadata_never_physical_identity(tmp_path, filename):
    private_root = tmp_path / "private"
    with SQLiteApplicationStore(tmp_path / "application.db") as sqlite_store:
        _create_workspaces(sqlite_store)
        with LocalPrivateContentStore(private_root) as private_store:
            store, get, _ = _services(sqlite_store, private_store, CONTENT_A)
            metadata = store.execute(
                workspace_id=WORKSPACE_A,
                original_filename=filename,
                content=b"synthetic",
                media_type=None,
                origin=PrivateContentOrigin.LOCAL_IMPORT,
            )
            assert get.execute(WORKSPACE_A, metadata.content_id).metadata.original_filename == filename
            physical = _content_dir(private_root)
            assert physical.is_dir()
            assert filename not in physical.as_posix()
            assert physical.resolve().is_relative_to(private_root.resolve())


def test_duplicate_filename_and_identical_bytes_create_distinct_local_records(tmp_path):
    with SQLiteApplicationStore(tmp_path / "application.db") as sqlite_store:
        _create_workspaces(sqlite_store)
        with LocalPrivateContentStore(tmp_path / "private") as private_store:
            store, _, list_contents = _services(
                sqlite_store, private_store, CONTENT_A, CONTENT_B
            )
            first = store.execute(
                workspace_id=WORKSPACE_A,
                original_filename="mesmo.pdf",
                content=b"same",
                media_type="application/pdf",
                origin=PrivateContentOrigin.LOCAL_IMPORT,
            )
            second = store.execute(
                workspace_id=WORKSPACE_A,
                original_filename="mesmo.pdf",
                content=b"same",
                media_type="application/pdf",
                origin=PrivateContentOrigin.LOCAL_IMPORT,
            )
            assert first.content_id != second.content_id
            assert first.checksum_sha256 == second.checksum_sha256
            assert list_contents.execute(WORKSPACE_A) == (first, second)


def test_application_rejects_non_bytes_and_configured_oversize_input(tmp_path):
    with SQLiteApplicationStore(tmp_path / "application.db") as sqlite_store:
        _create_workspaces(sqlite_store)
        with LocalPrivateContentStore(tmp_path / "private") as private_store:
            store, _, _ = _services(
                sqlite_store, private_store, CONTENT_A, max_bytes=3
            )
            common = {
                "workspace_id": WORKSPACE_A,
                "original_filename": "bounded.bin",
                "media_type": None,
                "origin": PrivateContentOrigin.LOCAL_IMPORT,
            }
            with pytest.raises(TypeError, match="bytes"):
                store.execute(content=bytearray(b"abc"), **common)
            with pytest.raises(ValueError, match="limite"):
                store.execute(content=b"abcd", **common)
            assert private_store.list_all(WORKSPACE_A) == ()


def test_workspace_isolation_blocks_read_list_and_identity_substitution(tmp_path):
    private_root = tmp_path / "private"
    with SQLiteApplicationStore(tmp_path / "application.db") as sqlite_store:
        _create_workspaces(sqlite_store)
        with LocalPrivateContentStore(private_root) as private_store:
            store, get, list_contents = _services(
                sqlite_store, private_store, CONTENT_A
            )
            metadata = store.execute(
                workspace_id=WORKSPACE_A,
                original_filename="a.bin",
                content=b"A only",
                media_type=None,
                origin=PrivateContentOrigin.LOCAL_IMPORT,
            )
            with pytest.raises(PrivateContentNotFound):
                get.execute(WORKSPACE_B, metadata.content_id)
            assert list_contents.execute(WORKSPACE_B) == ()

            source = _content_dir(private_root, WORKSPACE_A, CONTENT_A)
            substituted = _content_dir(private_root, WORKSPACE_B, CONTENT_A)
            substituted.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, substituted)
            with pytest.raises(RepositoryIntegrityError, match="workspace"):
                get.execute(WORKSPACE_B, metadata.content_id)


@pytest.mark.parametrize("target", ("content.bin", "metadata.json", "metadata.sha256"))
def test_missing_private_storage_member_fails_closed(tmp_path, target):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
        (_content_dir(root) / target).unlink()
        with pytest.raises(RepositoryIntegrityError, match="incompleto"):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_truncated_or_corrupted_content_fails_closed_without_repair(tmp_path):
    root = tmp_path / "private"
    payload = b"synthetic private bytes"
    metadata = _metadata(content=payload)
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, payload)
        content_path = _content_dir(root) / "content.bin"
        content_path.write_bytes(payload[:-1])
        with pytest.raises(RepositoryIntegrityError, match="conteúdo"):
            private_store.get(WORKSPACE_A, metadata.content_id)
        assert content_path.read_bytes() == payload[:-1]


def test_metadata_and_sidecar_tampering_fail_closed(tmp_path):
    root = tmp_path / "private"
    payload = b"synthetic private bytes"
    metadata = _metadata(content=payload)
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, payload)
        metadata_path = _content_dir(root) / "metadata.json"
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        data["originalFilename"] = "tampered.bin"
        metadata_path.write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        with pytest.raises(RepositoryIntegrityError, match="metadados"):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_unknown_object_in_private_record_fails_closed(tmp_path):
    root = tmp_path / "private"
    payload = b"synthetic private bytes"
    metadata = _metadata(content=payload)
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, payload)
        (_content_dir(root) / "unexpected.tmp").write_text("x", encoding="utf-8")
        with pytest.raises(RepositoryIntegrityError, match="incompleto"):
            private_store.list_all(WORKSPACE_A)


def test_collision_never_overwrites_existing_content(tmp_path):
    root = tmp_path / "private"
    first = _metadata(content=b"first")
    second = _metadata(content=b"second")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(first, b"first")
        with pytest.raises(RepositoryConflict):
            private_store.store(second, b"second")
        assert private_store.get(WORKSPACE_A, first.content_id) == PrivateContent(
            first, b"first"
        )


def test_finalize_failure_exposes_no_partial_object_and_cleans_owned_temp(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(
            private_filesystem.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("synthetic finalize failure")),
        )
        with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
            private_store.store(metadata, b"synthetic private bytes")
        assert private_store.get(WORKSPACE_A, metadata.content_id) is None
        contents = _content_dir(root).parent
        assert tuple(contents.iterdir()) == ()


def test_partial_write_failure_exposes_no_record_and_cleans_owned_temp(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    original = private_filesystem._write_fsynced
    calls = 0

    def fail_second(path, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic disk failure")
        return original(path, payload)

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(private_filesystem, "_write_fsynced", fail_second)
        with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
            private_store.store(metadata, b"synthetic private bytes")
        assert private_store.get(WORKSPACE_A, metadata.content_id) is None
        assert tuple(_content_dir(root).parent.iterdir()) == ()


def test_in_progress_write_is_not_visible_to_concurrent_listing(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    entered = threading.Event()
    release = threading.Event()
    original_replace = private_filesystem.os.replace
    outcome = []

    def blocked_replace(source, destination):
        entered.set()
        assert release.wait(timeout=5)
        return original_replace(source, destination)

    def writer(private_store):
        try:
            outcome.append(private_store.store(metadata, b"synthetic private bytes"))
        except Exception as exc:  # captured for assertion in the coordinating thread
            outcome.append(exc)

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(private_filesystem.os, "replace", blocked_replace)
        thread = threading.Thread(target=writer, args=(private_store,))
        thread.start()
        assert entered.wait(timeout=5)
        try:
            assert private_store.list_all(WORKSPACE_A) == ()
        finally:
            release.set()
            thread.join(timeout=5)
        assert outcome == [metadata]


def test_concurrent_same_identity_has_exactly_one_winner_without_overwrite(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    first = _metadata(content=b"first")
    second = _metadata(content=b"second")
    first_entered = threading.Event()
    finish_first = threading.Event()
    call_lock = threading.Lock()
    replace_calls = 0
    original_replace = private_filesystem.os.replace
    results = []

    def permissive_interleaved_replace(source, destination):
        nonlocal replace_calls
        with call_lock:
            replace_calls += 1
            call_number = replace_calls
        destination = Path(destination)
        if call_number == 1:
            first_entered.set()
            assert finish_first.wait(timeout=5)
        if destination.exists():
            for child in destination.iterdir():
                child.unlink()
            destination.rmdir()
        return original_replace(source, destination)

    def attempt(store, metadata, content, *, signal=False):
        try:
            results.append(store.store(metadata, content))
        except Exception as exc:  # captured for exact winner/loser assertions
            results.append(exc)
        finally:
            if signal:
                finish_first.set()

    with LocalPrivateContentStore(root) as first_store:
        with LocalPrivateContentStore(root) as second_store:
            monkeypatch.setattr(
                private_filesystem.os, "replace", permissive_interleaved_replace
            )
            thread_one = threading.Thread(
                target=attempt, args=(first_store, first, b"first")
            )
            thread_one.start()
            assert first_entered.wait(timeout=5)
            thread_two = threading.Thread(
                target=attempt,
                args=(second_store, second, b"second"),
                kwargs={"signal": True},
            )
            thread_two.start()
            thread_one.join(timeout=5)
            thread_two.join(timeout=5)

            winners = [item for item in results if type(item) is PrivateContentMetadata]
            conflicts = [item for item in results if isinstance(item, RepositoryConflict)]
            assert len(winners) == 1
            assert len(conflicts) == 1
            stored = first_store.get(WORKSPACE_A, PrivateContentId.parse(CONTENT_A))
            assert stored is not None
            assert stored.metadata == winners[0]


def test_symlink_record_is_rejected_when_platform_supports_it(tmp_path):
    root = tmp_path / "private"
    outside = tmp_path / "outside"
    outside.mkdir()
    record_path = _content_dir(root)
    record_path.parent.mkdir(parents=True)
    try:
        record_path.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink indisponível nesta plataforma: {exc}")
    with LocalPrivateContentStore(root) as private_store:
        with pytest.raises(RepositoryIntegrityError, match="reparse|simbólico"):
            private_store.get(WORKSPACE_A, PrivateContentId.parse(CONTENT_A))


def test_windows_reparse_attribute_is_mechanically_recognized(monkeypatch, tmp_path):
    fake = SimpleNamespace(
        st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400),
        st_mode=stat.S_IFDIR,
    )
    monkeypatch.setattr(private_filesystem.os, "lstat", lambda _path: fake)
    assert private_filesystem._path_is_link_or_reparse(tmp_path / "junction")


def test_closed_private_store_rejects_further_operations(tmp_path):
    store = LocalPrivateContentStore(tmp_path / "private")
    store.close()
    with pytest.raises(RepositoryError, match="fechado"):
        store.list_all(WORKSPACE_A)


def test_private_storage_introduces_no_network_import_or_log_egress(tmp_path, caplog):
    source_path = Path("scripts/backend_contract/infrastructure/private_filesystem.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert imported.isdisjoint(
        {"aiohttp", "http.client", "requests", "socket", "urllib", "urllib.request", "urllib3"}
    )

    secret = b"PRIVATE_SYNTHETIC_BYTES_NEVER_LOGGED"
    metadata = _metadata(content=secret)
    with LocalPrivateContentStore(tmp_path / "private") as private_store:
        private_store.store(metadata, secret)
        private_store.get(WORKSPACE_A, metadata.content_id)
    assert secret.decode("ascii") not in caplog.text


def test_no_private_fixture_or_product_storage_is_git_tracked(tmp_path):
    tracked = subprocess.run(
        ["git", "ls-files", "referencias/privadas/*"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert tracked.stdout == ""
    assert not tmp_path.resolve().is_relative_to(Path.cwd().resolve())
