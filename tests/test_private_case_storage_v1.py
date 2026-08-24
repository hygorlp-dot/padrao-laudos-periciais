import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
import time
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
from scripts.quality.capability_analyzer import analyze_source


WORKSPACE_A = WorkspaceId.parse("11111111-1111-4111-8111-111111111111")
WORKSPACE_B = WorkspaceId.parse("22222222-2222-4222-8222-222222222222")
CONTENT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CONTENT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
IMPORTED_AT = "2026-08-24T12:30:00+00:00"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _provision_default_private_root(tmp_path):
    root = tmp_path / "private"
    root.mkdir()
    (root / ".store-lock").write_bytes(b"0")
    (root / ".commit-log").write_bytes(b"")
    (root / ".commit-anchor").write_bytes(b"")


class FixedClock:
    def now(self):
        return datetime.fromisoformat(IMPORTED_AT)


class SequenceIds:
    def __init__(self, *values):
        self._values = iter(UUID(value) for value in values)

    def new_uuid(self):
        return next(self._values)


def test_private_filesystem_does_not_escape_the_sensitive_os_namespace():
    source_path = REPOSITORY_ROOT / (
        "scripts/backend_contract/infrastructure/private_filesystem.py"
    )

    findings = analyze_source(
        source_path.relative_to(REPOSITORY_ROOT).as_posix(),
        source_path.read_text(encoding="utf-8"),
        policy_path=REPOSITORY_ROOT / "config/capability-policy-v1.json",
    )

    assert findings == []


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


def _record_paths(root, workspace_id=WORKSPACE_A, content_id=CONTENT_A):
    prefix = f"{workspace_id}.{PrivateContentId.parse(content_id)}"
    return {
        "content.bin": root / f"{prefix}.content",
        "metadata.json": root / f"{prefix}.metadata",
        "metadata.sha256": root / f"{prefix}.metadata-sha256",
        "commit": root / f"{prefix}.commit",
    }


def _record_commits(root):
    return tuple(sorted(root.glob("*.commit")))


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
            physical = _record_paths(private_root)
            assert all(path.is_file() for path in physical.values())
            assert all(filename not in path.name for path in physical.values())
            assert all(
                path.resolve().is_relative_to(private_root.resolve())
                for path in physical.values()
            )


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

            source = _record_paths(private_root, WORKSPACE_A, CONTENT_A)
            substituted = _record_paths(private_root, WORKSPACE_B, CONTENT_A)
            for member in source:
                shutil.copy2(source[member], substituted[member])
            substituted_prefix = f"{WORKSPACE_B}.{CONTENT_A}"
            with (private_root / ".commit-log").open("ab") as journal:
                journal.write(substituted_prefix.encode("ascii") + b"\n")
                journal.flush()
                os.fsync(journal.fileno())
            private_store._committed.add(substituted_prefix)
            with pytest.raises(RepositoryIntegrityError, match="identidade|journal"):
                get.execute(WORKSPACE_B, metadata.content_id)


@pytest.mark.parametrize("target", ("content.bin", "metadata.json", "metadata.sha256"))
def test_missing_private_storage_member_fails_closed(tmp_path, target):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
        _record_paths(root)[target].unlink()
        with pytest.raises(RepositoryIntegrityError, match="inventário|ausente|inacessível"):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_truncated_or_corrupted_content_fails_closed_without_repair(tmp_path):
    root = tmp_path / "private"
    payload = b"synthetic private bytes"
    metadata = _metadata(content=payload)
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, payload)
        content_path = _record_paths(root)["content.bin"]
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
        metadata_path = _record_paths(root)["metadata.json"]
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        data["originalFilename"] = "tampered.bin"
        metadata_path.write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        with pytest.raises(RepositoryIntegrityError, match="metadados"):
            private_store.get(WORKSPACE_A, metadata.content_id)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schemaVersion", True),
        ("workspaceId", "{11111111-1111-4111-8111-111111111111}"),
    ),
)
def test_noncanonical_manifest_identity_or_schema_type_fails_closed(
    tmp_path, field, value
):
    root = tmp_path / "private"
    payload = b"synthetic private bytes"
    metadata = _metadata(content=payload)
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, payload)
        record = _record_paths(root)
        metadata_path = record["metadata.json"]
        sidecar_path = record["metadata.sha256"]
        manifest = json.loads(metadata_path.read_text(encoding="utf-8"))
        manifest[field] = value
        encoded = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        metadata_path.write_bytes(encoded)
        sidecar_path.write_text(hashlib.sha256(encoded).hexdigest(), encoding="ascii")

        with pytest.raises(RepositoryIntegrityError, match="metadados"):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_corrupt_oversized_content_is_rejected_before_unbounded_read(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    metadata = _metadata(content=b"x")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"x")
        _record_paths(root)["content.bin"].write_bytes(b"x" * (2 * 1024 * 1024))
        original_read = private_filesystem.os.read

        def bounded_read(descriptor, size):
            assert 0 <= size <= 64 * 1024
            return original_read(descriptor, size)

        monkeypatch.setattr(private_filesystem.os, "read", bounded_read)
        with pytest.raises(RepositoryIntegrityError):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_forged_manifest_cannot_raise_the_adapter_read_limit(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata(content=b"x")
    with LocalPrivateContentStore(root, max_content_bytes=1024) as private_store:
        private_store.store(metadata, b"x")
        paths = _record_paths(root)
        forged_content = b"x" * 2048
        paths["content.bin"].write_bytes(forged_content)
        manifest = json.loads(paths["metadata.json"].read_text(encoding="utf-8"))
        manifest["byteSize"] = len(forged_content)
        manifest["checksumSha256"] = hashlib.sha256(forged_content).hexdigest()
        encoded = json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifest_checksum = hashlib.sha256(encoded).hexdigest()
        paths["metadata.json"].write_bytes(encoded)
        paths["metadata.sha256"].write_text(manifest_checksum, encoding="ascii")
        paths["commit"].write_text(manifest_checksum, encoding="ascii")
        monkeypatch.setattr(
            private_filesystem,
            "_hash_regular",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("content read must not start")
            ),
        )

        with pytest.raises(RepositoryIntegrityError, match="limite"):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_unknown_object_in_private_record_fails_closed(tmp_path):
    root = tmp_path / "private"
    payload = b"synthetic private bytes"
    metadata = _metadata(content=payload)
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, payload)
        (root / "unexpected.tmp").write_text("x", encoding="utf-8")
        with pytest.raises(RepositoryIntegrityError, match="inesperado"):
            private_store.list_all(WORKSPACE_A)


def test_valid_shaped_uncommitted_object_is_rejected_during_runtime(tmp_path):
    root = tmp_path / "private"
    with LocalPrivateContentStore(root) as private_store:
        injected = root / f"{WORKSPACE_B}.{CONTENT_B}.content"
        injected.write_bytes(b"uncommitted synthetic bytes")

        with pytest.raises(RepositoryIntegrityError, match="inventário"):
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


def test_singleton_blocks_a_second_store_and_releases_after_close(tmp_path):
    root = tmp_path / "private"
    first = LocalPrivateContentStore(root)
    try:
        with pytest.raises(RepositoryConflict, match="já está aberto"):
            LocalPrivateContentStore(root)
    finally:
        first.close()
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()


def test_open_anchor_prevents_namespace_swap_or_keeps_posix_dirfd_stable(tmp_path):
    root = tmp_path / "private"
    moved = tmp_path / "moved-private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
        if os.name == "nt":
            with pytest.raises(OSError):
                root.rename(moved)
        else:
            root.rename(moved)
        assert private_store.get(WORKSPACE_A, metadata.content_id) == PrivateContent(
            metadata, b"synthetic private bytes"
        )


def test_root_identity_swap_before_anchor_fails_without_writing_to_replacement(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    original_root = tmp_path / "original-private"
    replacement = tmp_path / "replacement-private"
    replacement.mkdir()
    (replacement / ".store-lock").write_bytes(b"0")
    original_resolve = Path.resolve
    swapped = False

    def swap_before_resolve(path, *args, **kwargs):
        nonlocal swapped
        if path == root and not swapped:
            swapped = True
            root.rename(original_root)
            replacement.rename(root)
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", swap_before_resolve)
    with pytest.raises(RepositoryIntegrityError, match="private root"):
        LocalPrivateContentStore(root)
    assert set(path.name for path in root.iterdir()) == {".store-lock"}


def test_external_hard_link_is_rejected_before_private_read(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
        outside_link = tmp_path / "outside-hard-link.bin"
        os.link(_record_paths(root)["content.bin"], outside_link)
        with pytest.raises(RepositoryIntegrityError, match="hard link"):
            private_store.get(WORKSPACE_A, metadata.content_id)


@pytest.mark.parametrize(
    "control_name", (".store-lock", ".commit-log", ".commit-anchor")
)
def test_control_file_identity_change_is_rejected_during_runtime(
    tmp_path, control_name
):
    root = tmp_path / "private"
    with LocalPrivateContentStore(root) as private_store:
        external_link = tmp_path / f"external-{control_name[1:]}"
        os.link(root / control_name, external_link)

        with pytest.raises(RepositoryIntegrityError, match="hard link|controle"):
            private_store.list_all(WORKSPACE_A)


def test_fsynced_journal_detects_confirmed_record_loss_on_reopen(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    paths["commit"].unlink()
    preserved = {name: path.read_bytes() for name, path in paths.items() if path.exists()}
    with pytest.raises(RepositoryIntegrityError, match="journal|confirmado"):
        LocalPrivateContentStore(root)
    assert {
        name: path.read_bytes() for name, path in paths.items() if path.exists()
    } == preserved


def test_truncated_journal_line_is_rejected_before_unbounded_accumulation(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    (root / ".commit-log").write_bytes(b"x" * (2 * 1024 * 1024))
    original_read = private_filesystem.os.read
    bytes_read = 0

    def bounded_observed_read(descriptor, size):
        nonlocal bytes_read
        block = original_read(descriptor, size)
        bytes_read += len(block)
        return block

    monkeypatch.setattr(private_filesystem.os, "read", bounded_observed_read)
    with pytest.raises(RepositoryIntegrityError, match="journal"):
        LocalPrivateContentStore(root)
    assert bytes_read <= 64 * 1024


def test_unrelated_plausible_journal_tail_fails_closed_without_truncation(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    with (root / ".commit-log").open("ab") as journal:
        journal.write(b"bbbbbbbb-bbbb")
        journal.flush()
        os.fsync(journal.fileno())

    before = (root / ".commit-log").read_bytes()
    with pytest.raises(RepositoryIntegrityError, match="proveniência"):
        LocalPrivateContentStore(root)
    assert (root / ".commit-log").read_bytes() == before


@pytest.mark.parametrize("cutoff", (12, 73))
def test_interrupted_first_journal_intent_exposes_no_committed_record(
    tmp_path, monkeypatch, cutoff
):
    root = tmp_path / "private"
    metadata = _metadata()
    private_store = LocalPrivateContentStore(root)

    def torn_append(prefix):
        os.lseek(private_store._journal_fd, 0, os.SEEK_END)
        os.write(private_store._journal_fd, prefix.encode("ascii")[:cutoff])
        os.fsync(private_store._journal_fd)
        raise OSError("synthetic journal interruption")

    monkeypatch.setattr(private_store, "_append_intent", torn_append)
    with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
        private_store.store(metadata, b"synthetic private bytes")
    private_store.close()

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.get(WORKSPACE_A, metadata.content_id) is None
    assert (root / ".commit-log").read_bytes() == b""
    assert (root / ".commit-anchor").read_bytes() == b""


@pytest.mark.parametrize("cutoff", (0, 12, 73))
def test_commit_before_anchor_confirmation_recovers_exactly_one_record(
    tmp_path, monkeypatch, cutoff
):
    root = tmp_path / "private"
    metadata = _metadata()
    private_store = LocalPrivateContentStore(root)

    def torn_confirmation(prefix):
        if cutoff:
            os.lseek(private_store._anchor_fd, 0, os.SEEK_END)
            os.write(private_store._anchor_fd, prefix.encode("ascii")[:cutoff])
            os.fsync(private_store._anchor_fd)
        raise OSError("synthetic anchor interruption")

    monkeypatch.setattr(private_store, "_confirm_intent", torn_confirmation)
    with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
        private_store.store(metadata, b"synthetic private bytes")
    private_store.close()

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.get(WORKSPACE_A, metadata.content_id) == PrivateContent(
            metadata, b"synthetic private bytes"
        )
    expected = f"{WORKSPACE_A}.{CONTENT_A}\n".encode("ascii")
    assert (root / ".commit-log").read_bytes() == expected
    assert (root / ".commit-anchor").read_bytes() == expected


def test_short_torn_tail_binds_to_only_unjournaled_commit_in_same_workspace(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    first = _metadata(content=b"first")
    second = _metadata(content_id=CONTENT_B, content=b"second")
    private_store = LocalPrivateContentStore(root)
    private_store.store(first, b"first")

    def torn_append(prefix):
        os.lseek(private_store._journal_fd, 0, os.SEEK_END)
        os.write(private_store._journal_fd, prefix.encode("ascii")[:12])
        os.fsync(private_store._journal_fd)
        raise OSError("synthetic journal interruption")

    monkeypatch.setattr(private_store, "_append_intent", torn_append)
    with pytest.raises(RepositoryError):
        private_store.store(second, b"second")
    private_store.close()

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == (first,)


def test_runtime_journal_tampering_is_detected_before_read(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
        (root / ".commit-log").write_bytes(b"")

        with pytest.raises(RepositoryIntegrityError, match="journal"):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_clean_journal_truncation_is_not_reclassified_as_crash_recovery(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    (root / ".commit-log").write_bytes(b"")

    with pytest.raises(RepositoryIntegrityError, match="journal|anchor|proveniência"):
        LocalPrivateContentStore(root)
    assert _record_paths(root)["content.bin"].read_bytes() == b"synthetic private bytes"


def test_joint_record_and_journal_loss_is_detected_by_independent_anchor(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    for path in _record_paths(root).values():
        path.unlink()
    (root / ".commit-log").write_bytes(b"")

    with pytest.raises(RepositoryIntegrityError, match="journal|anchor|proveniência"):
        LocalPrivateContentStore(root)


def test_journal_entry_count_is_bounded_before_inventory_reconciliation(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    monkeypatch.setattr(private_filesystem, "_MAX_JOURNAL_ENTRIES", 4, raising=False)
    entries = [
        f"{WORKSPACE_A}.{index:08x}-0000-4000-8000-000000000000"
        for index in range(5)
    ]
    (root / ".commit-log").write_bytes(
        ("\n".join(entries) + "\n").encode("ascii")
    )

    with pytest.raises(RepositoryIntegrityError, match="journal.*limite|limite.*journal"):
        LocalPrivateContentStore(root)


def test_root_inventory_count_is_bounded_before_sorting(tmp_path, monkeypatch):
    root = tmp_path / "private"
    monkeypatch.setattr(private_filesystem, "_MAX_ROOT_ENTRIES", 4)
    for index in range(3):
        (root / f".synthetic-{index}").write_bytes(b"x")

    with pytest.raises(RepositoryIntegrityError, match="inventário.*limite"):
        LocalPrivateContentStore(root)


def test_missing_preprovisioned_journal_fails_closed_even_if_records_are_removed(
    tmp_path,
):
    root = tmp_path / "private"
    first = _metadata(content=b"first")
    second = _metadata(content_id=CONTENT_B, content=b"second")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(first, b"first")
        private_store.store(second, b"second")
    for path in _record_paths(root, content_id=CONTENT_B).values():
        path.unlink()
    (root / ".commit-log").unlink()

    with pytest.raises(RepositoryIntegrityError, match="controle"):
        LocalPrivateContentStore(root)
    assert _record_paths(root)["content.bin"].read_bytes() == b"first"


def test_recovery_rejects_complete_commit_missing_from_journal(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    (root / ".commit-log").write_bytes(b"")

    with pytest.raises(RepositoryIntegrityError, match="journal|anchor|proveniência"):
        LocalPrivateContentStore(root)


def test_recovery_discards_uncommitted_published_components_idempotently(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    paths["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")

    for _ in range(2):
        with LocalPrivateContentStore(root) as reopened:
            assert reopened.list_all(WORKSPACE_A) == ()
    assert not any(path.exists() for path in paths.values())


def test_recovery_validates_every_group_before_any_destructive_cleanup(tmp_path):
    root = tmp_path / "private"
    uncommitted = _metadata(content=b"uncommitted")
    confirmed = _metadata(content_id=CONTENT_B, content=b"confirmed")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(uncommitted, b"uncommitted")
        private_store.store(confirmed, b"confirmed")
    uncommitted_paths = _record_paths(root)
    uncommitted_paths["commit"].unlink()
    _record_paths(root, content_id=CONTENT_B)["content.bin"].write_bytes(b"corrupt")
    preserved = {
        name: path.read_bytes()
        for name, path in uncommitted_paths.items()
        if path.exists()
    }

    with pytest.raises(RepositoryIntegrityError):
        LocalPrivateContentStore(root)
    assert {
        name: path.read_bytes()
        for name, path in uncommitted_paths.items()
        if path.exists()
    } == preserved


def test_recovery_cleanup_revalidates_inode_before_unlink(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    paths["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    target = paths["content.bin"]
    original_cleanup = LocalPrivateContentStore._safe_unlink_internal
    replaced = False

    def replace_before_unlink(store, path, *, expected):
        nonlocal replaced
        if Path(path) == target and not replaced:
            replaced = True
            target.unlink()
            target.write_bytes(b"independent recovery replacement")
        return original_cleanup(store, path, expected=expected)

    monkeypatch.setattr(
        LocalPrivateContentStore, "_safe_unlink_internal", replace_before_unlink
    )
    with pytest.raises(RepositoryIntegrityError, match="identidade|mudou|ownership"):
        LocalPrivateContentStore(root)
    assert target.read_bytes() == b"independent recovery replacement"


def test_recovery_reconciles_exact_staging_to_final_hard_link_after_crash(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    final_commit = _record_paths(root)["commit"]
    stage_commit = root / f".staging.{'1' * 32}.commit"
    os.link(final_commit, stage_commit)

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.get(WORKSPACE_A, metadata.content_id) == PrivateContent(
            metadata, b"synthetic private bytes"
        )
    assert not stage_commit.exists()
    assert final_commit.stat().st_nlink == 1


def test_deep_manifest_is_reported_as_controlled_integrity_failure(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    nested = (b"[" * 20_000) + b"0" + (b"]" * 20_000)
    manifest_checksum = hashlib.sha256(nested).hexdigest().encode("ascii")
    paths["metadata.json"].write_bytes(nested)
    paths["metadata.sha256"].write_bytes(manifest_checksum)
    paths["commit"].write_bytes(manifest_checksum)

    with pytest.raises(RepositoryIntegrityError, match="metadados|manifesto"):
        LocalPrivateContentStore(root)


def test_finalize_failure_exposes_no_partial_object_and_cleans_owned_temp(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(
            private_filesystem,
            "_publish_durable",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("synthetic finalize failure")
            ),
        )
        with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
            private_store.store(metadata, b"synthetic private bytes")
        assert private_store.get(WORKSPACE_A, metadata.content_id) is None
        assert _record_commits(root) == ()


def test_partial_commit_marker_write_never_reaches_the_visible_final_name(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    metadata = _metadata()
    original_write_all = private_filesystem._write_all
    calls = 0

    def fail_during_commit_write(descriptor, payload):
        nonlocal calls
        calls += 1
        if calls == 4:
            original_write_all(descriptor, b"partial")
            raise OSError("synthetic commit write interruption")
        return original_write_all(descriptor, payload)

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(
            private_filesystem, "_write_all", fail_during_commit_write
        )
        with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
            private_store.store(metadata, b"synthetic private bytes")

    assert tuple(root.glob("*.commit")) == ()
    assert tuple(root.glob(".staging.*")) == ()
    assert all(not path.exists() for path in _record_paths(root).values())


def test_abrupt_process_death_is_reconciled_on_next_exclusive_open(tmp_path):
    root = tmp_path / "private"
    sentinel = tmp_path / "writer-paused"
    child = textwrap.dedent(
        """
        import hashlib
        import time
        from pathlib import Path

        from scripts.backend_contract.application.models import (
            PrivateContentId,
            PrivateContentMetadata,
            PrivateContentOrigin,
            WorkspaceId,
        )
        from scripts.backend_contract.infrastructure import private_filesystem
        from scripts.backend_contract.infrastructure.private_filesystem import LocalPrivateContentStore

        root = Path(__import__('sys').argv[1])
        sentinel = Path(__import__('sys').argv[2])
        payload = b'synthetic crash bytes'
        metadata = PrivateContentMetadata(
            workspace_id=WorkspaceId.parse('11111111-1111-4111-8111-111111111111'),
            content_id=PrivateContentId.parse('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
            original_filename='crash.bin',
            byte_size=len(payload),
            checksum_sha256=hashlib.sha256(payload).hexdigest(),
            media_type=None,
            imported_at='2026-08-24T12:30:00+00:00',
            origin=PrivateContentOrigin.LOCAL_IMPORT,
        )
        original = private_filesystem._write_fsynced

        def pause_after_private_bytes(path, content, **kwargs):
            original(path, content, **kwargs)
            if path.name.endswith('.content'):
                sentinel.write_text('paused', encoding='ascii')
                time.sleep(30)

        private_filesystem._write_fsynced = pause_after_private_bytes
        with LocalPrivateContentStore(root) as store:
            store.store(metadata, payload)
        """
    )
    process = subprocess.Popen(
        [sys.executable, "-c", child, str(root), str(sentinel)],
        cwd=REPOSITORY_ROOT,
    )
    try:
        deadline = time.monotonic() + 10
        while not sentinel.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                pytest.fail("child did not reach the controlled crash window")
            time.sleep(0.02)
        assert process.poll() is None
        process.terminate()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
        assert tuple(root.glob(".staging.*")) == ()


def test_private_reads_do_not_use_unanchored_name_based_open(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata(content=b"same bytes")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"same bytes")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"same bytes")
        original_open = private_filesystem.os.open
        original_read = private_filesystem.os.read
        redirected = []
        external_reads = []

        def redirect_unanchored(path, flags, *args, **kwargs):
            if Path(path).name.endswith(".content") and kwargs.get("dir_fd") is None:
                redirected.append(Path(path))
                return original_open(outside, flags, *args, **kwargs)
            return original_open(path, flags, *args, **kwargs)

        def observed_read(descriptor, size):
            if redirected:
                external_reads.append((descriptor, size))
            return original_read(descriptor, size)

        monkeypatch.setattr(private_filesystem.os, "open", redirect_unanchored)
        monkeypatch.setattr(private_filesystem.os, "read", observed_read)
        with pytest.raises(RepositoryIntegrityError, match="identidade física"):
            private_store.get(WORKSPACE_A, metadata.content_id)
        assert len(redirected) == 1
        assert external_reads == []


def test_successful_publication_uses_a_durable_directory_commit(tmp_path, monkeypatch):
    durable_publish = getattr(private_filesystem, "_publish_durable", None)
    assert callable(durable_publish)
    calls = []

    def observed_publish(source, destination, **kwargs):
        result = durable_publish(source, destination, **kwargs)
        calls.append((Path(source), Path(destination)))
        return result

    monkeypatch.setattr(private_filesystem, "_publish_durable", observed_publish)
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    assert len(calls) == 4
    assert {destination for _, destination in calls} == {
        _record_paths(root)[member]
        for member in ("content.bin", "metadata.json", "metadata.sha256", "commit")
    }
    assert calls[-1][1] == _record_paths(root)["commit"]


def test_publish_failure_does_not_delete_destination_not_created_by_attempt(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"owned stage")

    def fail_without_link(_source, target, **_kwargs):
        Path(target).write_bytes(b"independent winner")
        raise OSError("synthetic link failure")

    monkeypatch.setattr(private_filesystem.os, "link", fail_without_link)
    with pytest.raises(OSError, match="synthetic link failure"):
        private_filesystem._publish_durable(source, destination)
    assert destination.read_bytes() == b"independent winner"


def test_publish_rollback_revalidates_owned_inode_before_unlink(tmp_path, monkeypatch):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"owned stage")
    original_unlink = Path.unlink

    def replace_destination_then_fail(path, *args, **kwargs):
        if path == source:
            original_unlink(destination)
            destination.write_bytes(b"independent replacement")
            raise OSError("synthetic source unlink failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", replace_destination_then_fail)
    with pytest.raises(OSError, match="synthetic source unlink failure"):
        private_filesystem._publish_durable(source, destination)
    assert destination.read_bytes() == b"independent replacement"


def test_store_rollback_preserves_replacement_of_published_inode(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    original_publish = private_filesystem._publish_durable
    first_destination = None
    calls = 0

    def replace_first_then_fail(source, destination, **kwargs):
        nonlocal calls, first_destination
        calls += 1
        if calls == 1:
            result = original_publish(source, destination, **kwargs)
            first_destination = Path(destination)
            return result
        assert first_destination is not None
        first_destination.unlink()
        first_destination.write_bytes(b"independent replacement")
        raise OSError("synthetic later publication failure")

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(
            private_filesystem, "_publish_durable", replace_first_then_fail
        )
        with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
            private_store.store(metadata, b"synthetic private bytes")
    assert first_destination.read_bytes() == b"independent replacement"


def test_store_cleanup_preserves_replaced_staging_inode(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    original_write = private_filesystem._write_fsynced
    first_stage = None
    calls = 0

    def replace_first_stage_then_fail(path, payload, **kwargs):
        nonlocal calls, first_stage
        calls += 1
        if calls == 1:
            first_stage = Path(path)
            return original_write(path, payload, **kwargs)
        assert first_stage is not None
        first_stage.unlink()
        first_stage.write_bytes(b"independent staging replacement")
        raise OSError("synthetic later staging failure")

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(
            private_filesystem, "_write_fsynced", replace_first_stage_then_fail
        )
        with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
            private_store.store(metadata, b"synthetic private bytes")
    assert first_stage.read_bytes() == b"independent staging replacement"


def test_partial_write_failure_exposes_no_record_and_cleans_owned_temp(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    original = private_filesystem._write_fsynced
    calls = 0

    def fail_second(path, payload, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic disk failure")
        return original(path, payload, **kwargs)

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(private_filesystem, "_write_fsynced", fail_second)
        with pytest.raises(RepositoryError, match="armazenar conteúdo privado"):
            private_store.store(metadata, b"synthetic private bytes")
        assert private_store.get(WORKSPACE_A, metadata.content_id) is None
        assert _record_commits(root) == ()


def test_in_progress_write_is_not_visible_to_concurrent_listing(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    entered = threading.Event()
    release = threading.Event()
    original_publish = private_filesystem._publish_durable
    outcome = []
    listing = []

    def blocked_publish(source, destination, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original_publish(source, destination, **kwargs)

    def writer(private_store):
        try:
            outcome.append(private_store.store(metadata, b"synthetic private bytes"))
        except Exception as exc:  # captured for assertion in the coordinating thread
            outcome.append(exc)

    def reader(private_store):
        listing.append(private_store.list_all(WORKSPACE_A))

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(private_filesystem, "_publish_durable", blocked_publish)
        thread = threading.Thread(target=writer, args=(private_store,))
        thread.start()
        assert entered.wait(timeout=5)
        reader_thread = threading.Thread(target=reader, args=(private_store,))
        reader_thread.start()
        try:
            reader_thread.join(timeout=0.1)
            assert listing == []
        finally:
            release.set()
            thread.join(timeout=5)
            reader_thread.join(timeout=5)
        assert outcome == [metadata]
        assert listing == [(metadata,)]


def test_close_waits_for_active_writer_before_releasing_singleton(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    outcome = []
    original_publish = private_filesystem._publish_durable

    def blocked_publish(source, destination, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original_publish(source, destination, **kwargs)

    store = LocalPrivateContentStore(root)
    monkeypatch.setattr(private_filesystem, "_publish_durable", blocked_publish)
    writer = threading.Thread(
        target=lambda: outcome.append(
            store.store(metadata, b"synthetic private bytes")
        )
    )
    closer = threading.Thread(target=lambda: (store.close(), closed.set()))
    writer.start()
    assert entered.wait(timeout=5)
    closer.start()
    try:
        assert not closed.wait(timeout=0.1)
        with pytest.raises(RepositoryConflict):
            LocalPrivateContentStore(root)
    finally:
        release.set()
        writer.join(timeout=5)
        closer.join(timeout=5)
    assert outcome == [metadata]
    assert closed.is_set()


def test_adapter_rejects_oversize_before_constructing_or_hashing_record(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    content = b"oversize"
    metadata = _metadata(content=content)
    with LocalPrivateContentStore(root, max_content_bytes=1) as store:
        monkeypatch.setattr(
            private_filesystem,
            "PrivateContent",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("record construction must not start")
            ),
        )
        with pytest.raises(RepositoryError, match="limite"):
            store.store(metadata, content)


def test_concurrent_same_identity_has_exactly_one_winner_without_overwrite(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    first = _metadata(content=b"first")
    second = _metadata(content=b"second")
    first_entered = threading.Event()
    finish_first = threading.Event()
    second_entered = threading.Event()
    original_publish = private_filesystem._publish_durable
    results = []

    publish_calls = 0

    def blocked_first_publish(source, destination, **kwargs):
        nonlocal publish_calls
        publish_calls += 1
        if publish_calls == 1:
            first_entered.set()
            assert finish_first.wait(timeout=5)
        return original_publish(source, destination, **kwargs)

    def attempt(store, metadata, content, *, signal=False):
        try:
            if signal:
                second_entered.set()
            results.append(store.store(metadata, content))
        except Exception as exc:  # captured for exact winner/loser assertions
            results.append(exc)

    with LocalPrivateContentStore(root) as store:
        monkeypatch.setattr(
            private_filesystem, "_publish_durable", blocked_first_publish
        )
        thread_one = threading.Thread(target=attempt, args=(store, first, b"first"))
        thread_one.start()
        assert first_entered.wait(timeout=5)
        thread_two = threading.Thread(
            target=attempt,
            args=(store, second, b"second"),
            kwargs={"signal": True},
        )
        thread_two.start()
        assert second_entered.wait(timeout=5)
        finish_first.set()
        thread_one.join(timeout=5)
        thread_two.join(timeout=5)

        winners = [item for item in results if type(item) is PrivateContentMetadata]
        conflicts = [item for item in results if isinstance(item, RepositoryConflict)]
        assert len(winners) == 1
        assert len(conflicts) == 1
        stored = store.get(WORKSPACE_A, PrivateContentId.parse(CONTENT_A))
        assert stored is not None
        assert stored.metadata == winners[0]


def test_symlink_record_is_rejected_when_platform_supports_it(tmp_path):
    root = tmp_path / "private"
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    record_path = _record_paths(root)["content.bin"]
    try:
        record_path.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink indisponível nesta plataforma: {exc}")
    with pytest.raises(
        RepositoryIntegrityError,
        match="objeto inesperado|reparse|arquivo regular",
    ):
        LocalPrivateContentStore(root)


def test_unprovisioned_private_root_is_rejected_without_creating_it(tmp_path):
    root = tmp_path / "not-provisioned"
    with pytest.raises(RepositoryError, match="provisionado"):
        LocalPrivateContentStore(root)
    assert not root.exists()


def test_provisioned_root_without_lock_is_rejected_before_journal_creation(tmp_path):
    root = tmp_path / "missing-lock"
    root.mkdir()
    with pytest.raises(RepositoryIntegrityError, match="controle"):
        LocalPrivateContentStore(root)
    assert tuple(root.iterdir()) == ()


@pytest.mark.parametrize("lock_bytes", (b"", b"1", b"00"))
def test_malformed_preprovisioned_lock_is_rejected_without_mutation(
    tmp_path, lock_bytes
):
    root = tmp_path / f"invalid-lock-{len(lock_bytes)}-{lock_bytes.hex()}"
    root.mkdir()
    lock = root / ".store-lock"
    lock.write_bytes(lock_bytes)
    with pytest.raises(RepositoryIntegrityError, match="trust anchor"):
        LocalPrivateContentStore(root)
    assert lock.read_bytes() == lock_bytes
    assert set(path.name for path in root.iterdir()) == {".store-lock"}


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
