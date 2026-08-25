import ast
import hashlib
import json
import os
import re
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
def _provision_default_private_root(tmp_path, monkeypatch):
    # Unit tests assert every durability barrier through call/order spies; an
    # actual fsync cannot prove power-loss durability and makes the synthetic
    # matrix contend with verify_core's parallel suites on Windows runners.
    # Child-process recovery tests still execute the unpatched implementation.
    monkeypatch.setattr(private_filesystem.os, "fsync", lambda _descriptor: None)
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


def test_private_filesystem_has_no_destructive_namespace_operation():
    source_path = REPOSITORY_ROOT / (
        "scripts/backend_contract/infrastructure/private_filesystem.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    destructive_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"remove", "rename", "replace", "rmdir", "unlink"}
    }

    assert destructive_calls == set()


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
            with pytest.raises(
                RepositoryIntegrityError, match="identidade|journal|invent.rio"
            ):
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
    assert (root / ".commit-log").read_bytes() == (
        f"{WORKSPACE_A}.{CONTENT_A}\n".encode("ascii")
    )
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


@pytest.mark.parametrize("missing_member", (*private_filesystem._MEMBERS, "commit"))
def test_pending_commit_missing_any_staging_identity_fails_before_anchor_mutation(
    tmp_path, missing_member
):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    next(root.glob(f".staging.*.{missing_member}")).unlink()
    (root / ".commit-anchor").write_bytes(b"")

    with pytest.raises(RepositoryIntegrityError, match="staging|identidade"):
        LocalPrivateContentStore(root)
    assert (root / ".commit-anchor").read_bytes() == b""


@pytest.mark.parametrize("namespace", ("final", "staging"))
@pytest.mark.parametrize("missing_member", (*private_filesystem._MEMBERS, "commit"))
def test_confirmed_record_missing_any_identity_alias_fails_closed(
    tmp_path, namespace, missing_member
):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    if namespace == "staging":
        next(root.glob(f".staging.*.{missing_member}")).unlink()
    else:
        final_key = {
            "content": "content.bin",
            "metadata": "metadata.json",
            "metadata-sha256": "metadata.sha256",
            "commit": "commit",
        }[missing_member]
        _record_paths(root)[final_key].unlink()
    journal_before = (root / ".commit-log").read_bytes()
    anchor_before = (root / ".commit-anchor").read_bytes()

    with pytest.raises(RepositoryIntegrityError):
        LocalPrivateContentStore(root)
    assert (root / ".commit-log").read_bytes() == journal_before
    assert (root / ".commit-anchor").read_bytes() == anchor_before


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


def test_process_death_with_short_torn_wal_ignores_prior_committed_groups(tmp_path):
    root = tmp_path / "private"
    first = _metadata(content=b"first")
    second = _metadata(content_id=CONTENT_B, content=b"second")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(first, b"first")

    second_prefix = f"{WORKSPACE_A}.{second.content_id}"
    nonce = "1" * 32
    intent = root / f".intent.{second_prefix}.{nonce}"
    intent.write_bytes(b"")
    with (root / ".commit-log").open("ab") as journal:
        journal.write(second_prefix.encode("ascii")[:12])
        journal.flush()
        os.fsync(journal.fileno())

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == (first,)
    assert (root / f".aborted.{nonce}").exists()


def test_short_torn_wal_ignores_prior_aborted_intent_without_wal(tmp_path):
    root = tmp_path / "private"
    with LocalPrivateContentStore(root):
        pass
    aborted_prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    aborted_nonce = "1" * 32
    aborted_intent = root / f".intent.{aborted_prefix}.{aborted_nonce}"
    aborted_intent.write_bytes(b"")
    os.link(aborted_intent, root / f".aborted.{aborted_nonce}")
    assert (root / ".commit-log").read_bytes() == b""

    pending_prefix = f"{WORKSPACE_A}.{CONTENT_B}"
    pending_nonce = "2" * 32
    (root / f".intent.{pending_prefix}.{pending_nonce}").write_bytes(b"")
    with (root / ".commit-log").open("ab") as journal:
        journal.write(pending_prefix.encode("ascii")[:12])
        journal.flush()
        os.fsync(journal.fileno())

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert (root / f".aborted.{pending_nonce}").exists()


def test_rollback_completes_owned_wal_before_marking_intent_aborted(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    metadata = _metadata(content=b"aborted")
    prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    private_store = LocalPrivateContentStore(root)

    def fail_before_wal(_prefix):
        raise OSError("synthetic pre-WAL failure")

    original_mark = private_filesystem._mark_intent_aborted

    def assert_wal_then_mark(*args, **kwargs):
        assert (root / ".commit-log").read_bytes() == (
            prefix.encode("ascii") + b"\n"
        )
        return original_mark(*args, **kwargs)

    monkeypatch.setattr(private_store, "_append_intent", fail_before_wal)
    monkeypatch.setattr(private_filesystem, "_mark_intent_aborted", assert_wal_then_mark)
    with pytest.raises(RepositoryError):
        private_store.store(metadata, b"aborted")
    private_store.close()

    assert tuple(root.glob(".aborted.*"))
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()


def test_complete_group_without_wal_never_mutates_confirmation_anchor(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    (root / ".commit-log").write_bytes(b"")
    (root / ".commit-anchor").write_bytes(b"")

    with pytest.raises(RepositoryIntegrityError, match="journal|proveni"):
        LocalPrivateContentStore(root)

    assert (root / ".commit-log").read_bytes() == b""
    assert (root / ".commit-anchor").read_bytes() == b""


def test_runtime_journal_tampering_is_detected_before_read(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
        (root / ".commit-log").write_bytes(b"")

        with pytest.raises(RepositoryIntegrityError, match="journal"):
            private_store.get(WORKSPACE_A, metadata.content_id)


def test_recovery_never_erases_a_ledger_entry_injected_after_abort_marker(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    nonce = "2" * 32
    (root / f".intent.{prefix}.{nonce}").write_bytes(b"")
    (root / ".commit-log").write_bytes(prefix.encode("ascii")[:12])
    foreign = f"{WORKSPACE_B}.{CONTENT_B}\n".encode("ascii")
    original_mark = private_filesystem._mark_intent_aborted

    def mark_then_inject(*args, **kwargs):
        result = original_mark(*args, **kwargs)
        with (root / ".commit-log").open("ab") as journal:
            journal.write(foreign)
            journal.flush()
            os.fsync(journal.fileno())
        return result

    monkeypatch.setattr(private_filesystem, "_mark_intent_aborted", mark_then_inject)
    with pytest.raises(RepositoryIntegrityError, match="journal|ledger|intent"):
        LocalPrivateContentStore(root)
    assert foreign in (root / ".commit-log").read_bytes()


def test_recovery_never_uses_destructive_ledger_truncation(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    _record_paths(root)["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")

    def forbidden_truncation(*_args, **_kwargs):
        raise AssertionError("rollback must preserve the append-only journal")

    monkeypatch.setattr(private_filesystem.os, "ftruncate", forbidden_truncation)
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert (root / ".commit-log").read_bytes() == (
        f"{WORKSPACE_A}.{CONTENT_A}\n".encode("ascii")
    )


def test_concurrent_ledger_append_is_never_overwritten(tmp_path, monkeypatch):
    root = tmp_path / "private"
    foreign = f"{WORKSPACE_B}.{CONTENT_B}\n".encode("ascii")
    original_write_all = private_filesystem._write_all
    injected = False

    with LocalPrivateContentStore(root) as private_store:
        journal_fd = private_store._journal_fd

        def inject_before_owned_append(descriptor, payload):
            nonlocal injected
            if descriptor == journal_fd and not injected:
                injected = True
                with (root / ".commit-log").open("ab") as journal:
                    journal.write(foreign)
                    journal.flush()
                    os.fsync(journal.fileno())
            return original_write_all(descriptor, payload)

        monkeypatch.setattr(
            private_filesystem, "_write_all", inject_before_owned_append
        )
        private_store.store(_metadata(), b"synthetic private bytes")

    assert foreign in (root / ".commit-log").read_bytes()
    with pytest.raises(RepositoryIntegrityError, match="journal|ledger|intent"):
        LocalPrivateContentStore(root)


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


def test_store_rejects_ledger_capacity_before_any_persistent_mutation(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    monkeypatch.setattr(private_filesystem, "_MAX_JOURNAL_ENTRIES", 1)
    first = _metadata(content=b"first")
    second = _metadata(content_id=CONTENT_B, content=b"second")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(first, b"first")
        before = {
            path.name: path.read_bytes()
            for path in root.iterdir()
            if path.name != ".store-lock"
        }
        with pytest.raises(RepositoryError, match="limite"):
            private_store.store(second, b"second")
        assert {
            path.name: path.read_bytes()
            for path in root.iterdir()
            if path.name != ".store-lock"
        } == before

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == (first,)


def test_root_inventory_count_is_bounded_before_sorting(tmp_path, monkeypatch):
    root = tmp_path / "private"
    monkeypatch.setattr(private_filesystem, "_MAX_ROOT_ENTRIES", 4)
    for index in range(3):
        (root / f".synthetic-{index}").write_bytes(b"x")

    with pytest.raises(RepositoryIntegrityError, match="inventário.*limite"):
        LocalPrivateContentStore(root)


def test_store_reserves_worst_case_abort_footprint_before_first_mutation(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    monkeypatch.setattr(private_filesystem, "_MAX_ROOT_ENTRIES", 20)

    with LocalPrivateContentStore(root) as private_store:
        with pytest.raises(RepositoryError, match="limite"):
            private_store.store(_metadata(), b"synthetic private bytes")

    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


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
    assert tuple(root.glob(".retired.*"))


@pytest.mark.parametrize("published_members", range(4))
def test_recovery_reconciles_every_precommit_publication_boundary(
    tmp_path, published_members
):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    paths["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    ordered = (
        ("content", "content.bin"),
        ("metadata", "metadata.json"),
        ("metadata-sha256", "metadata.sha256"),
    )
    for index, (member, path_key) in enumerate(ordered):
        if index >= published_members:
            paths[path_key].unlink()
            next(root.glob(f".staging.*.{member}")).unlink()

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert tuple(root.glob(".retired.*"))


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


def test_recovery_retirement_revalidates_inode_before_link(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    paths["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    target = paths["content.bin"]
    original_cleanup = LocalPrivateContentStore._retire_internal
    replaced = False

    def replace_before_retirement(store, path, *, expected):
        nonlocal replaced
        if Path(path) == target and not replaced:
            replaced = True
            target.unlink()
            target.write_bytes(b"independent recovery replacement")
        return original_cleanup(store, path, expected=expected)

    monkeypatch.setattr(
        LocalPrivateContentStore, "_retire_internal", replace_before_retirement
    )
    with pytest.raises(RepositoryIntegrityError, match="identidade|mudou"):
        LocalPrivateContentStore(root)
    assert (root / ".commit-log").read_bytes() == (
        f"{WORKSPACE_A}.{CONTENT_A}\n".encode("ascii")
    )
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert target.read_bytes() == b"independent recovery replacement"


def test_recovery_retirement_failure_keeps_wal_and_is_retryable(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    _record_paths(root)["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    original_retire = LocalPrivateContentStore._retire_internal
    failed = False

    def fail_first_retirement(store, path, *, expected):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic retirement interruption")
        return original_retire(store, path, expected=expected)

    monkeypatch.setattr(
        LocalPrivateContentStore, "_retire_internal", fail_first_retirement
    )
    with pytest.raises(RepositoryError, match="abrir"):
        LocalPrivateContentStore(root)
    expected_wal = f"{WORKSPACE_A}.{CONTENT_A}\n".encode("ascii")
    assert (root / ".commit-log").read_bytes() == expected_wal

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert (root / ".commit-log").read_bytes() == expected_wal


def test_torn_wal_is_completed_and_preserved_as_aborted_evidence(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    _record_paths(root)["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    (root / ".commit-log").write_bytes(prefix.encode("ascii")[:12])
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert (root / ".commit-log").read_bytes() == prefix.encode("ascii") + b"\n"


def test_interrupted_torn_wal_completion_is_restartable(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    _record_paths(root)["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    fragment = prefix.encode("ascii")[:12]
    (root / ".commit-log").write_bytes(fragment)
    original_complete = LocalPrivateContentStore._complete_torn_intent

    def interrupt_completion(store, exact_prefix, exact_fragment):
        suffix = exact_prefix.encode("ascii")[len(exact_fragment) :] + b"\n"
        os.lseek(store._journal_fd, 0, os.SEEK_END)
        os.write(store._journal_fd, suffix[:7])
        os.fsync(store._journal_fd)
        raise OSError("synthetic torn-WAL completion interruption")

    monkeypatch.setattr(
        LocalPrivateContentStore, "_complete_torn_intent", interrupt_completion
    )
    with pytest.raises(RepositoryError, match="abrir"):
        LocalPrivateContentStore(root)
    assert (root / ".commit-log").read_bytes() == fragment + (
        prefix.encode("ascii")[len(fragment) :] + b"\n"
    )[:7]

    monkeypatch.setattr(
        LocalPrivateContentStore, "_complete_torn_intent", original_complete
    )
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()


def test_abrupt_first_torn_wal_uses_durable_intent_provenance(tmp_path):
    root = tmp_path / "private"
    nonce = "3" * 32
    prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    intent = root / f".intent.{prefix}.{nonce}"
    intent.write_bytes(b"")
    (root / ".commit-log").write_bytes(prefix.encode("ascii")[:12])

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert (root / ".commit-log").read_bytes() == prefix.encode("ascii") + b"\n"


def test_crash_after_physical_intent_before_wal_is_recovered_as_abort(tmp_path):
    root = tmp_path / "private"
    nonce = "4" * 32
    prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    (root / f".intent.{prefix}.{nonce}").write_bytes(b"")

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert (root / f".aborted.{nonce}").exists()


def test_recovery_revalidates_every_path_after_retirement_before_sealing_abort(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    paths["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    target = paths["content.bin"]
    original_retire = LocalPrivateContentStore._retire_internal
    swapped = False

    def swap_after_retirement(store, path, *, expected):
        nonlocal swapped
        result = original_retire(store, path, expected=expected)
        if Path(path) == target and not swapped:
            swapped = True
            target.unlink()
            target.write_bytes(b"independent post-retirement replacement")
        return result

    monkeypatch.setattr(
        LocalPrivateContentStore, "_retire_internal", swap_after_retirement
    )
    with pytest.raises(RepositoryIntegrityError, match="aposent|proveni|identidade"):
        LocalPrivateContentStore(root)
    expected_wal = f"{WORKSPACE_A}.{CONTENT_A}\n".encode("ascii")
    assert (root / ".commit-log").read_bytes() == expected_wal
    assert target.read_bytes() == b"independent post-retirement replacement"

    monkeypatch.setattr(LocalPrivateContentStore, "_retire_internal", original_retire)
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert target.read_bytes() == b"independent post-retirement replacement"


def test_recovery_rechecks_after_wal_preservation_without_losing_provenance(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    paths["commit"].unlink()
    (root / ".commit-anchor").write_bytes(b"")
    target = paths["commit"]
    original_abort = LocalPrivateContentStore._abort_intent
    injected = False

    def inject_after_abort(store, prefix, intents):
        nonlocal injected
        result = original_abort(store, prefix, intents)
        if not injected:
            injected = True
            target.write_bytes(b"independent late replacement")
        return result

    monkeypatch.setattr(
        LocalPrivateContentStore,
        "_abort_intent",
        inject_after_abort,
    )
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert target.read_bytes() == b"independent late replacement"

    monkeypatch.setattr(
        LocalPrivateContentStore,
        "_abort_intent",
        original_abort,
    )
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()


def test_retirement_marks_owned_inode_without_any_unlink(tmp_path, monkeypatch):
    target = tmp_path / "owned"
    target.write_bytes(b"owned bytes")
    expected = target.stat()

    def forbidden_unlink(*_args, **_kwargs):
        raise AssertionError("retirement must not unlink")

    monkeypatch.setattr(private_filesystem.os, "unlink", forbidden_unlink)
    private_filesystem._retire_if_owned(target, expected, root_fd=None)
    assert target.read_bytes() == b"owned bytes"
    marker = next(tmp_path.glob(".retired.*"))
    assert private_filesystem._same_identity(target.stat(), marker.stat())


def test_standalone_retirement_marker_fails_closed(tmp_path):
    root = tmp_path / "private"
    (root / f".retired.{'0' * 32}").write_bytes(b"unbound marker")

    with pytest.raises(RepositoryIntegrityError, match="aposentado|v.nculo"):
        LocalPrivateContentStore(root)


def test_hardlinked_retirement_markers_without_transaction_fail_closed(tmp_path):
    root = tmp_path / "private"
    first = root / f".retired.{'0' * 32}"
    second = root / f".retired.{'1' * 32}"
    first.write_bytes(b"unbound markers")
    os.link(first, second)

    with pytest.raises(RepositoryIntegrityError, match="aposent|proveni|invent.rio"):
        LocalPrivateContentStore(root)


def test_forged_final_and_retirement_marker_without_intent_fail_closed(tmp_path):
    root = tmp_path / "private"
    final = _record_paths(root)["content.bin"]
    marker = root / f".retired.{'2' * 32}"
    final.write_bytes(b"unbound private-shaped bytes")
    os.link(final, marker)

    with pytest.raises(RepositoryIntegrityError, match="intent|proveni|invent.rio"):
        LocalPrivateContentStore(root)


def test_retired_private_inode_with_external_hardlink_fails_closed(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    metadata = _metadata()
    original_write = private_filesystem._write_fsynced
    writes = 0

    def fail_second_write(path, payload, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("synthetic aborted transaction")
        return original_write(path, payload, **kwargs)

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(
            private_filesystem, "_write_fsynced", fail_second_write
        )
        with pytest.raises(RepositoryError, match="armazenar"):
            private_store.store(metadata, b"synthetic private bytes")
    marker = next(root.glob(".retired.*"))
    owned_alias = next(
        path
        for path in root.glob(".staging.*")
        if private_filesystem._same_identity(path.stat(), marker.stat())
    )
    os.link(owned_alias, tmp_path / "external-private-hardlink")

    with pytest.raises(RepositoryIntegrityError, match="hard link|extern|invent.rio"):
        LocalPrivateContentStore(root)


def test_committed_intent_with_external_hardlink_fails_closed(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    intent = next(root.glob(".intent.*"))
    os.link(intent, tmp_path / "external-intent-hardlink")

    with pytest.raises(RepositoryIntegrityError, match="hard link"):
        LocalPrivateContentStore(root)


def test_staging_nonce_must_match_its_physical_intent(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    stage = next(root.glob(".staging.*.content"))
    segments = stage.name.split(".")
    segments[-2] = "5" * 32
    stage.rename(stage.with_name(".".join(segments)))

    with pytest.raises(RepositoryIntegrityError, match="staging.*intent"):
        LocalPrivateContentStore(root)


def test_recovery_reconciles_exact_staging_to_final_hard_link_after_crash(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    final_commit = _record_paths(root)["commit"]
    stage_commit = next(root.glob(".staging.*.commit"))

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.get(WORKSPACE_A, metadata.content_id) == PrivateContent(
            metadata, b"synthetic private bytes"
        )
    assert stage_commit.exists()
    assert final_commit.stat().st_nlink == 2


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
    assert tuple(root.glob(".retired.*"))
    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()


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
        assert tuple(root.glob(".retired.*"))


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
        with pytest.raises(
            RepositoryIntegrityError, match="identidade física|hard link"
        ):
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


def test_windows_publication_flushes_link_identity_after_hardlink(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"owned stage")
    events = []
    original_link = private_filesystem.os.link
    original_fsync = private_filesystem.os.fsync

    def observed_link(*args, **kwargs):
        result = original_link(*args, **kwargs)
        events.append("link")
        return result

    def observed_fsync(descriptor):
        events.append("fsync")
        return original_fsync(descriptor)

    monkeypatch.setattr(private_filesystem.os, "link", observed_link)
    monkeypatch.setattr(private_filesystem.os, "fsync", observed_fsync)
    private_filesystem._publish_durable(
        source,
        destination,
        expected_source=source.stat(),
        root_fd=None,
    )

    assert events == ["link", "fsync"]


@pytest.mark.parametrize("operation", ("read", "hash"))
def test_private_read_revalidates_link_count_after_bytes_are_consumed(
    tmp_path, monkeypatch, operation
):
    source = tmp_path / "private" / "source"
    alias = tmp_path / "private" / "alias"
    outside = tmp_path / "outside-hardlink"
    source.write_bytes(b"race-private-bytes")
    os.link(source, alias)
    original_read = private_filesystem.os.read
    injected = False

    def inject_external_link_after_read(descriptor, size):
        nonlocal injected
        block = original_read(descriptor, size)
        if block and not injected:
            injected = True
            os.link(source, outside)
        return block

    monkeypatch.setattr(private_filesystem.os, "read", inject_external_link_after_read)
    with pytest.raises(RepositoryIntegrityError, match="hard link|mudou"):
        if operation == "read":
            private_filesystem._read_regular(
                source,
                root_fd=None,
                maximum_bytes=1024,
                expected_links=2,
            )
        else:
            private_filesystem._hash_regular(
                source,
                root_fd=None,
                maximum_bytes=1024,
                expected_size=len(b"race-private-bytes"),
                load_content=True,
                expected_links=2,
            )


@pytest.mark.parametrize("operation", ("retire", "abort"))
def test_windows_rollback_markers_flush_link_identity(
    tmp_path, monkeypatch, operation
):
    root = tmp_path / "private"
    source = root / "owned"
    source.write_bytes(b"" if operation == "abort" else b"owned")
    expected = source.stat()
    events = []
    original_link = private_filesystem.os.link
    original_fsync = private_filesystem.os.fsync

    def observed_link(*args, **kwargs):
        result = original_link(*args, **kwargs)
        events.append("link")
        return result

    def observed_fsync(descriptor):
        events.append("fsync")
        return original_fsync(descriptor)

    monkeypatch.setattr(private_filesystem.os, "link", observed_link)
    monkeypatch.setattr(private_filesystem.os, "fsync", observed_fsync)
    if operation == "retire":
        private_filesystem._retire_if_owned(source, expected, root_fd=None)
    else:
        private_filesystem._mark_intent_aborted(
            source, expected, "3" * 32, root_fd=None
        )
    assert events == ["link", "fsync"]


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
        private_filesystem._publish_durable(
            source, destination, expected_source=source.stat()
        )
    assert destination.read_bytes() == b"independent winner"


def test_publish_rollback_preserves_destination_swapped_after_link(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"owned stage")
    expected_source = source.stat()
    original_lstat = private_filesystem.os.lstat
    swapped = False

    def replace_destination_before_observation(path, *args, **kwargs):
        nonlocal swapped
        if Path(path) == destination and destination.exists() and not swapped:
            swapped = True
            destination.unlink()
            destination.write_bytes(b"independent replacement")
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(private_filesystem.os, "lstat", replace_destination_before_observation)
    with pytest.raises(RepositoryIntegrityError, match="identidade|mudou"):
        private_filesystem._publish_durable(
            source,
            destination,
            expected_source=expected_source,
        )
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
    assert (root / ".commit-log").read_bytes() == (
        f"{WORKSPACE_A}.{CONTENT_A}\n".encode("ascii")
    )

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
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

    with LocalPrivateContentStore(root) as reopened:
        assert reopened.list_all(WORKSPACE_A) == ()
    assert first_stage.read_bytes() == b"independent staging replacement"


def test_recovery_preserves_valid_shaped_object_without_durable_provenance(tmp_path):
    root = tmp_path / "private"
    foreign = _record_paths(root)["content.bin"]
    foreign.write_bytes(b"independent valid-shaped object")

    with pytest.raises(RepositoryIntegrityError, match="proveni|journal|invent.rio"):
        LocalPrivateContentStore(root)
    assert foreign.read_bytes() == b"independent valid-shaped object"


def test_publish_rejects_replaced_commit_staging_identity(tmp_path, monkeypatch):
    root = tmp_path / "private"
    metadata = _metadata()
    original_publish = private_filesystem._publish_durable
    replaced = False

    def replace_commit_stage(source, destination, **kwargs):
        nonlocal replaced
        if Path(destination).name.endswith(".commit") and not replaced:
            replaced = True
            Path(source).unlink()
            Path(source).write_bytes(b"independent commit-stage replacement")
        return original_publish(source, destination, **kwargs)

    with LocalPrivateContentStore(root) as private_store:
        monkeypatch.setattr(
            private_filesystem, "_publish_durable", replace_commit_stage
        )
        with pytest.raises(
            RepositoryIntegrityError, match="identidade|mudou|proveni"
        ):
            private_store.store(metadata, b"synthetic private bytes")
    assert replaced


def test_cleanup_never_unlinks_replacement_swapped_after_identity_check(
    tmp_path, monkeypatch
):
    target = tmp_path / "owned"
    target.write_bytes(b"owned")
    expected = target.stat()
    original_link = os.link
    swapped = False

    def swap_before_retirement_link(source, destination, *args, **kwargs):
        nonlocal swapped
        if Path(destination).name.startswith(".retired.") and not swapped:
            swapped = True
            target.unlink()
            target.write_bytes(b"independent replacement")
        return original_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(private_filesystem.os, "link", swap_before_retirement_link)
    with pytest.raises(RepositoryIntegrityError, match="identidade|mudou|ownership"):
        private_filesystem._retire_if_owned(target, expected, root_fd=None)
    assert target.read_bytes() == b"independent replacement"


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
    prefix = f"{WORKSPACE_A}.{CONTENT_A}"
    (root / f".intent.{prefix}.{'1' * 32}").write_bytes(b"")
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


def test_windows_unc_private_root_is_rejected_before_any_filesystem_probe(monkeypatch):
    probed = []

    def forbidden_probe(path):
        probed.append(str(path))
        raise AssertionError("UNC root reached the filesystem")

    monkeypatch.setattr(private_filesystem.os.path, "lexists", forbidden_probe)
    with pytest.raises(RepositoryError, match="local|private root"):
        LocalPrivateContentStore(r"\\server.invalid\private-share")
    assert probed == []


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


def test_reparse_in_any_configured_root_ancestor_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "private"
    marked_ancestor = root.parent
    original_check = private_filesystem._path_is_link_or_reparse

    def ancestor_is_reparse(path):
        if Path(path) == marked_ancestor:
            return True
        return original_check(path)

    monkeypatch.setattr(
        private_filesystem, "_path_is_link_or_reparse", ancestor_is_reparse
    )
    with pytest.raises(RepositoryIntegrityError, match="ancestral|reparse"):
        LocalPrivateContentStore(root)


def test_closed_private_store_rejects_further_operations(tmp_path):
    store = LocalPrivateContentStore(tmp_path / "private")
    store.close()
    with pytest.raises(RepositoryError, match="fechado"):
        store.list_all(WORKSPACE_A)


def test_context_manager_preserves_body_exception_when_close_also_fails(
    tmp_path, monkeypatch
):
    store = LocalPrivateContentStore(tmp_path / "private")
    original_close = store.close

    def fail_close():
        raise RepositoryError("controlled close failure")

    monkeypatch.setattr(store, "close", fail_close)
    try:
        with pytest.raises(ValueError, match="body failure") as captured:
            with store:
                raise ValueError("body failure")
        assert any(
            "controlled close failure" in note
            for note in getattr(captured.value, "__notes__", ())
        )
    finally:
        monkeypatch.setattr(store, "close", original_close)
        original_close()


def test_ambiguous_close_failure_never_retries_a_reused_descriptor(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    store = LocalPrivateContentStore(root)
    journal_fd = store._journal_fd
    original_close = private_filesystem.os.close
    failed = False
    probes = []

    def fail_journal_once(descriptor):
        nonlocal failed
        if descriptor == journal_fd and not failed:
            failed = True
            original_close(descriptor)
            raise OSError("synthetic ambiguous journal close failure")
        return original_close(descriptor)

    monkeypatch.setattr(private_filesystem.os, "close", fail_journal_once)
    with pytest.raises(RepositoryError, match="fechar"):
        store.close()
    try:
        while journal_fd not in probes:
            probes.append(os.open(root / ".commit-log", os.O_RDONLY))
        store.close()
        os.fstat(journal_fd)
    finally:
        for descriptor in probes:
            try:
                original_close(descriptor)
            except OSError:
                pass
    with LocalPrivateContentStore(root):
        pass


@pytest.mark.parametrize("failed_control", (".commit-log", ".commit-anchor"))
def test_control_descriptor_is_closed_when_initial_sync_fails(
    tmp_path, monkeypatch, failed_control
):
    root = tmp_path / "private"
    captured = {}
    original_open_control = private_filesystem._open_control_regular
    original_fsync = private_filesystem.os.fsync
    original_fstat = private_filesystem.os.fstat

    def capture_control(path, *, root_fd):
        descriptor, identity = original_open_control(path, root_fd=root_fd)
        captured[Path(path).name] = descriptor
        return descriptor, identity

    def fail_selected_sync(descriptor):
        if descriptor == captured.get(failed_control):
            raise OSError(f"synthetic {failed_control} sync failure")
        return original_fsync(descriptor)

    monkeypatch.setattr(private_filesystem, "_open_control_regular", capture_control)
    monkeypatch.setattr(private_filesystem.os, "fsync", fail_selected_sync)
    with pytest.raises(RepositoryError, match="armazenamento privado"):
        LocalPrivateContentStore(root)

    with pytest.raises(OSError):
        original_fstat(captured[failed_control])


def test_staging_descriptor_is_closed_when_initial_identity_probe_fails(
    tmp_path, monkeypatch
):
    target = tmp_path / "staging"
    captured = {}
    original_open = private_filesystem.os.open
    original_fstat = private_filesystem.os.fstat

    def capture_created(path, flags, *args, **kwargs):
        descriptor = original_open(path, flags, *args, **kwargs)
        captured["staging"] = descriptor
        return descriptor

    def fail_staging_probe(descriptor):
        if descriptor == captured.get("staging"):
            raise OSError("synthetic staging identity failure")
        return original_fstat(descriptor)

    monkeypatch.setattr(private_filesystem.os, "open", capture_created)
    monkeypatch.setattr(private_filesystem.os, "fstat", fail_staging_probe)
    with pytest.raises(OSError, match="synthetic staging identity failure"):
        private_filesystem._write_fsynced(target, b"synthetic")

    with pytest.raises(OSError):
        original_fstat(captured["staging"])
    assert target.exists()


def test_lock_descriptor_is_closed_when_stream_adoption_fails(tmp_path, monkeypatch):
    root = tmp_path / "private"
    captured = {}
    original_fdopen = private_filesystem.os.fdopen
    original_fstat = private_filesystem.os.fstat

    def fail_stream_adoption(descriptor, *args, **kwargs):
        captured["lock"] = descriptor
        raise OSError("synthetic fdopen failure")

    monkeypatch.setattr(private_filesystem.os, "fdopen", fail_stream_adoption)
    with pytest.raises(RepositoryError, match="armazenamento privado"):
        LocalPrivateContentStore(root)
    monkeypatch.setattr(private_filesystem.os, "fdopen", original_fdopen)

    with pytest.raises(OSError):
        original_fstat(captured["lock"])


@pytest.mark.skipif(os.name != "nt", reason="locking Windows")
def test_close_closes_lock_handle_even_when_explicit_unlock_fails(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    store = LocalPrivateContentStore(root)
    original_locking = private_filesystem.msvcrt.locking

    def fail_unlock(descriptor, mode, count):
        if mode == private_filesystem.msvcrt.LK_UNLCK:
            raise OSError("synthetic unlock failure")
        return original_locking(descriptor, mode, count)

    monkeypatch.setattr(private_filesystem.msvcrt, "locking", fail_unlock)
    with pytest.raises(RepositoryError, match="fechar") as captured:
        store.close()
    monkeypatch.setattr(private_filesystem.msvcrt, "locking", original_locking)

    with LocalPrivateContentStore(root):
        pass
    assert captured.value is not None


def test_store_inherited_by_another_process_identity_is_unusable_and_closes_safely(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    store = LocalPrivateContentStore(root)
    owner_pid = store._owner_pid
    monkeypatch.setattr(private_filesystem.os, "getpid", lambda: owner_pid + 1)

    with pytest.raises(RepositoryError, match="processo|herdado"):
        store.list_all(WORKSPACE_A)
    store.close()
    assert store._closed

    monkeypatch.undo()
    with LocalPrivateContentStore(root):
        pass


def test_trusted_local_device_policy_rejects_remote_mount_identity(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    original_stat = private_filesystem.os.stat
    trusted_anchor = Path(sys.executable).anchor

    def remote_volume_for_runtime(path, *args, **kwargs):
        observed = original_stat(path, *args, **kwargs)
        if Path(path) == Path(trusted_anchor):
            return SimpleNamespace(st_dev=observed.st_dev + 1)
        return observed

    monkeypatch.setattr(private_filesystem.os, "stat", remote_volume_for_runtime)
    with pytest.raises(RepositoryError, match="local"):
        private_filesystem._validate_trusted_local_device(os.lstat(root))


def test_private_root_on_untrusted_device_is_rejected_on_every_platform(
    tmp_path, monkeypatch
):
    root = tmp_path / "private"
    original_stat = private_filesystem.os.stat
    trusted_anchor = Path(sys.executable).anchor

    def remote_volume_for_runtime(path, *args, **kwargs):
        observed = original_stat(path, *args, **kwargs)
        if Path(path) == Path(trusted_anchor):
            return SimpleNamespace(st_dev=observed.st_dev + 1)
        return observed

    monkeypatch.setattr(private_filesystem.os, "stat", remote_volume_for_runtime)
    before = {path.name: path.read_bytes() for path in root.iterdir()}
    with pytest.raises(RepositoryError, match="local"):
        LocalPrivateContentStore(root)
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


def test_huge_json_integer_is_a_controlled_integrity_failure(tmp_path):
    root = tmp_path / "private"
    metadata = _metadata()
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(metadata, b"synthetic private bytes")
    paths = _record_paths(root)
    manifest = paths["metadata.json"].read_text(encoding="utf-8")
    oversized_integer = "9" * 5_000
    poisoned = re.sub(r'"byteSize":\d+', f'"byteSize":{oversized_integer}', manifest)
    poisoned_bytes = poisoned.encode("utf-8")
    digest = hashlib.sha256(poisoned_bytes).hexdigest().encode("ascii")
    paths["metadata.json"].write_bytes(poisoned_bytes)
    paths["metadata.sha256"].write_bytes(digest)
    paths["commit"].write_bytes(digest)

    with pytest.raises(RepositoryIntegrityError, match="metadados|manifesto"):
        LocalPrivateContentStore(root)


@pytest.mark.parametrize("operation", ("store", "get", "list"))
def test_public_operations_translate_raw_filesystem_errors_without_path_leakage(
    tmp_path, monkeypatch, operation
):
    root = tmp_path / "private"
    first = _metadata(content=b"first")
    second = _metadata(content_id=CONTENT_B, content=b"second")
    with LocalPrivateContentStore(root) as private_store:
        private_store.store(first, b"first")

        def fail_inventory():
            raise OSError("synthetic secret path C:/private/case")

        monkeypatch.setattr(private_store, "_root_names", fail_inventory)
        with pytest.raises(RepositoryError) as captured:
            if operation == "store":
                private_store.store(second, b"second")
            elif operation == "get":
                private_store.get(WORKSPACE_A, first.content_id)
            else:
                private_store.list_all(WORKSPACE_A)

    assert "C:/private/case" not in str(captured.value)
    assert isinstance(captured.value.__cause__, OSError)


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
