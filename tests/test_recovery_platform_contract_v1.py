"""#183 -- platform contract for mutable workspace recovery.

Windows owns the complete mutable Recovery V1 workflow. POSIX deliberately
fails closed before the first state or filesystem mutation; backup export and
package verification remain independent capabilities.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_document_intake_v1 import frontend_build
from tests.test_local_api_v1 import RecordingService, TOKEN, http_request, services
from tests.test_product_bridge_v1 import browser_mutation_headers, request as bridge_request


def _use_posix_recovery_contract(monkeypatch):
    from scripts.backend_contract.application import workspace_recovery as wr

    monkeypatch.setattr(wr, "os", SimpleNamespace(name="posix"))
    return wr


def _assert_platform_unsupported(operation) -> None:
    with pytest.raises(Exception) as caught:
        operation()
    assert type(caught.value).__name__ == "RecoveryPlatformUnsupported"


class _NeverCalled:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("mutable recovery crossed the POSIX platform gate")


def test_posix_stage_fails_before_verification_state_or_filesystem_access(monkeypatch, tmp_path):
    """Removing the stage gate would reach verification and staging creation."""

    wr = _use_posix_recovery_contract(monkeypatch)
    verify = _NeverCalled()
    create_calls = []
    stage = wr.StageWorkspaceRecovery(
        verify,
        lambda root: create_calls.append(root),
        _NeverCalled,
        wr.WorkspaceRecoverySessions(),
        tmp_path / ".target.sqlite3.recovery",
        lambda payload: "a" * 64,
    )

    _assert_platform_unsupported(lambda: stage.execute(b"synthetic-backup"))

    assert verify.calls == []
    assert create_calls == []
    assert not (tmp_path / ".target.sqlite3.recovery").exists()


@pytest.mark.parametrize(
    ("operation", "build"),
    (
        (
            "promote",
            lambda wr, sessions: wr.PromoteWorkspaceRecovery(
                sessions, _NeverCalled(), _NeverCalled(), _NeverCalled()
            ).execute("00000000-0000-4000-8000-000000000183"),
        ),
        (
            "discard",
            lambda wr, sessions: wr.DiscardWorkspaceRecovery(
                sessions, _NeverCalled()
            ).execute("00000000-0000-4000-8000-000000000183"),
        ),
        (
            "abandon",
            lambda wr, sessions: wr.AbandonWorkspaceRecovery(
                wr.DiscardWorkspaceRecovery(sessions, _NeverCalled())
            ).execute("00000000-0000-4000-8000-000000000183"),
        ),
        (
            "retry-discard",
            lambda wr, sessions: wr.DiscardWorkspaceRecovery(
                sessions, _NeverCalled()
            ).execute("00000000-0000-4000-8000-000000000183"),
        ),
        (
            "retry-abandon",
            lambda wr, sessions: wr.DiscardWorkspaceRecovery(
                sessions, _NeverCalled()
            ).execute(
                "00000000-0000-4000-8000-000000000183",
                aceitar_incompleta=True,
            ),
        ),
    ),
)
def test_posix_mutable_commands_fail_before_session_claim(monkeypatch, operation, build):
    """Every command, including retries, rejects before changing session state."""

    wr = _use_posix_recovery_contract(monkeypatch)
    claims = []

    class Sessions:
        def claim(self, *args, **kwargs):
            claims.append((args, kwargs))
            raise AssertionError(f"{operation} reached session claim")

    _assert_platform_unsupported(lambda: build(wr, Sessions()))
    assert claims == []


def test_posix_startup_preserves_existing_recovery_without_traversal_or_gc(monkeypatch, tmp_path):
    """Removing either startup gate would acquire and enumerate the namespace."""

    wr = _use_posix_recovery_contract(monkeypatch)
    base = tmp_path / ".target.sqlite3.recovery"
    root = base / "recovery-00000000-0000-4000-8000-000000000183"
    root.mkdir(parents=True)
    sentinel = root / "preserve.bin"
    sentinel.write_bytes(b"POSIX-RECOVERY-MUST-BE-PRESERVED")
    intent = base / ".recovery-cleanup-intent-00000000-0000-4000-8000-000000000183"
    intent.write_bytes(b"PRESERVE-INTENT")
    acquired = []

    def forbidden_acquire(cls, *args, **kwargs):
        acquired.append((args, kwargs))
        raise AssertionError("POSIX startup traversed the recovery namespace")

    monkeypatch.setattr(
        wr.RecoveryFilesystemCustody,
        "acquire",
        classmethod(forbidden_acquire),
    )
    sessions = wr.WorkspaceRecoverySessions()

    assert wr.recolher_stagings_orfaos(base) == ()
    assert wr.reconstruir_sessoes_recuperacao(base, sessions, _NeverCalled()) == ()
    assert acquired == []
    assert sentinel.read_bytes() == b"POSIX-RECOVERY-MUST-BE-PRESERVED"
    assert intent.read_bytes() == b"PRESERVE-INTENT"
    assert sessions.snapshot() == ()


def test_b16_mkdirat_to_openat_attack_is_unreachable(monkeypatch):
    """B16 regression: the first POSIX create mutation is never reached."""

    wr = _use_posix_recovery_contract(monkeypatch)
    mutations = []
    fake_os = SimpleNamespace(
        name="posix",
        O_RDONLY=os.O_RDONLY,
        O_DIRECTORY=0x10000,
        O_NOFOLLOW=0x20000,
        mkdir=lambda *args, **kwargs: mutations.append(("mkdirat", args, kwargs)),
        open=lambda *args, **kwargs: mutations.append(("openat", args, kwargs)),
        close=lambda _descriptor: None,
    )
    monkeypatch.setattr(wr, "os", fake_os)
    parent = wr.RecoveryFilesystemCustody(
        Path("/trusted/recovery"),
        [41],
        [(7, 10, stat.S_IFDIR)],
    )

    _assert_platform_unsupported(
        lambda: parent.create_child(
            "recovery-00000000-0000-4000-8000-000000000183"
        )
    )

    assert mutations == []
    parent.close()


def test_a16_statat_to_rmdirat_attack_is_unreachable(monkeypatch):
    """A16 regression: neither pre-delete stat nor destructive rmdir is reached."""

    wr = _use_posix_recovery_contract(monkeypatch)
    mutations = []
    fake_os = SimpleNamespace(
        name="posix",
        stat=lambda *args, **kwargs: mutations.append(("statat", args, kwargs)),
        fstat=lambda *args, **kwargs: mutations.append(("fstat", args, kwargs)),
        rmdir=lambda *args, **kwargs: mutations.append(("rmdirat", args, kwargs)),
    )
    monkeypatch.setattr(wr, "os", fake_os)
    node = wr._CleanupNode(
        Path("/trusted/recovery/private"),
        "private",
        (8, 21, stat.S_IFDIR),
        52,
        None,
        [],
        [],
    )

    _assert_platform_unsupported(
        lambda: wr._remover_diretorio_posix_ancorado(
            51,
            node,
            "private",
            (8, 21, stat.S_IFDIR),
        )
    )
    assert mutations == []


def test_posix_cleanup_and_intent_gc_fail_before_custody_acquisition(monkeypatch, tmp_path):
    """Alternate cleanup helpers cannot bypass the application command gates."""

    wr = _use_posix_recovery_contract(monkeypatch)
    acquired = []

    def forbidden_acquire(cls, *args, **kwargs):
        acquired.append((args, kwargs))
        raise AssertionError("cleanup acquired POSIX recovery custody")

    monkeypatch.setattr(
        wr.RecoveryFilesystemCustody,
        "acquire",
        classmethod(forbidden_acquire),
    )
    recovery_id = "00000000-0000-4000-8000-000000000183"
    root = tmp_path / ".target.sqlite3.recovery" / f"recovery-{recovery_id}"

    _assert_platform_unsupported(
        lambda: wr._remover_raiz_quarentenada(root, exigir_remocao=True)
    )
    _assert_platform_unsupported(
        lambda: wr._coletar_cleanup_intent_apos_raiz_ausente(
            root,
            recovery_id,
            expected_filesystem_identity=(1, 2, stat.S_IFDIR),
            expected_identity_removed=True,
        )
    )
    assert acquired == []


def test_posix_infrastructure_stage_and_restore_fail_before_storage(monkeypatch, tmp_path):
    """Infrastructure entry points cannot bypass the application platform gate."""

    wr = _use_posix_recovery_contract(monkeypatch)
    from scripts.backend_contract.infrastructure.productization import (
        RecoveryStaging,
        RestoreWorkspaceBackup,
    )

    acquired = []

    def forbidden_acquire(cls, *args, **kwargs):
        acquired.append((args, kwargs))
        raise AssertionError("infrastructure acquired POSIX recovery custody")

    monkeypatch.setattr(
        wr.RecoveryFilesystemCustody,
        "acquire",
        classmethod(forbidden_acquire),
    )
    root = tmp_path / ".target.sqlite3.recovery" / "recovery-00000000-0000-4000-8000-000000000183"

    _assert_platform_unsupported(lambda: RecoveryStaging.create(root))
    _assert_platform_unsupported(
        lambda: RestoreWorkspaceBackup(object()).execute(b"synthetic-backup")
    )
    assert acquired == []
    assert not root.parent.exists()


def _local_headers(payload: bytes) -> dict[str, str]:
    return {
        "Host": "127.0.0.1",
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(payload)),
        "X-Local-API-Token": TOKEN,
    }


def test_posix_local_api_returns_canonical_error_while_verify_remains_available(monkeypatch):
    """Transport maps one domain state and does not disable safe verification."""

    wr = _use_posix_recovery_contract(monkeypatch)
    from scripts.backend_contract.local_api.transport import LocalApi

    summary = wr.BackupSummary(
        workspace_id="11111111-1111-4111-8111-111111111111",
        workspace_name="Synthetic",
        workspace_created_at="2026-09-08T00:00:00+00:00",
        product_release="0.11.0",
        storage_schema_version=1,
        artifact_revisions=0,
        private_contents=0,
        backup_sha256="a" * 64,
    )
    inspect = RecordingService(summary)
    stage = _NeverCalled()
    api = LocalApi(
        services(
            inspect_workspace_backup=inspect,
            stage_workspace_recovery=stage,
        ),
        token=TOKEN,
    )
    payload = b"synthetic"

    verified = api.handle(
        "POST",
        "/v1/recovery/verify",
        _local_headers(payload),
        payload,
    )
    rejected = api.handle(
        "POST",
        "/v1/recovery/staging",
        _local_headers(payload),
        payload,
    )

    assert verified.status == 200
    assert inspect.calls == [((payload,), {})]
    assert rejected.status == 501
    assert json.loads(rejected.body)["error"]["code"] == "RECOVERY_PLATFORM_UNSUPPORTED"
    assert stage.calls == []


@pytest.mark.parametrize("action", ("promote", "discard", "abandon"))
def test_posix_local_api_rejects_every_mutable_action_before_dto_or_service(
    monkeypatch,
    action,
):
    """Action routes share the platform authority and never parse mutation DTOs."""

    _use_posix_recovery_contract(monkeypatch)
    from scripts.backend_contract.local_api.transport import LocalApi

    promote = _NeverCalled()
    discard = _NeverCalled()
    abandon = _NeverCalled()
    api = LocalApi(
        services(
            promote_workspace_recovery=promote,
            discard_workspace_recovery=discard,
            abandon_workspace_recovery=abandon,
        ),
        token=TOKEN,
    )
    recovery_id = "00000000-0000-4000-8000-000000000183"

    rejected = api.handle(
        "POST",
        f"/v1/recovery/{recovery_id}/{action}",
        {
            "Host": "127.0.0.1",
            "Content-Type": "application/json",
            "Content-Length": "0",
            "X-Local-API-Token": TOKEN,
        },
        b"",
    )

    assert rejected.status == 501
    assert json.loads(rejected.body)["error"]["code"] == "RECOVERY_PLATFORM_UNSUPPORTED"
    assert promote.calls == []
    assert discard.calls == []
    assert abandon.calls == []


def test_posix_backup_export_remains_available(monkeypatch):
    """The platform decision does not disable the independent safe backup path."""

    _use_posix_recovery_contract(monkeypatch)
    from scripts.backend_contract.local_api.transport import LocalApi

    package = b"synthetic-portable-backup"
    export = RecordingService(package)
    api = LocalApi(services(export_workspace_backup=export), token=TOKEN)
    workspace_id = "11111111-1111-4111-8111-111111111111"

    response = api.handle(
        "POST",
        f"/v1/workspaces/{workspace_id}/backup",
        {
            "Host": "127.0.0.1",
            "Content-Length": "0",
            "X-Local-API-Token": TOKEN,
        },
        b"",
    )

    assert response.status == 200
    assert response.body == package
    assert len(export.calls) == 1


def test_posix_local_api_rejects_stage_before_spool_creation(monkeypatch, tmp_path):
    """The Local API acquisition boundary must not create a temporary file."""

    _use_posix_recovery_contract(monkeypatch)
    from scripts.backend_contract.local_api import server as local_server_module
    from scripts.backend_contract.local_api.server import LocalApiServer, LocalServerConfig
    from scripts.backend_contract.local_api.transport import LocalApi

    spool_dir = tmp_path / "local-spool"
    spool_dir.mkdir()
    spool_calls = []

    def forbidden_spool(*args, **kwargs):
        spool_calls.append((args, kwargs))
        raise AssertionError("Local API created a spool before platform rejection")

    monkeypatch.setattr(local_server_module.tempfile, "SpooledTemporaryFile", forbidden_spool)
    stage = _NeverCalled()
    server = LocalApiServer(
        LocalApi(services(stage_workspace_recovery=stage), token=TOKEN),
        LocalServerConfig(spool_dir=str(spool_dir)),
    )
    server.start()
    try:
        status, _headers, body = http_request(
            server,
            "POST",
            "/v1/recovery/staging",
            raw_body=b"synthetic",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Local-API-Token": TOKEN,
            },
        )
    finally:
        server.close()

    assert status == 501
    assert json.loads(body)["error"]["code"] == "RECOVERY_PLATFORM_UNSUPPORTED"
    assert spool_calls == []
    assert list(spool_dir.iterdir()) == []
    assert stage.calls == []


def test_posix_product_bridge_rejects_stage_before_spool_creation(monkeypatch, tmp_path):
    """The browser-facing acquisition boundary must also avoid its own spool."""

    _use_posix_recovery_contract(monkeypatch)
    from scripts.backend_contract.product_bridge import server as bridge_server_module
    from scripts.backend_contract.product_bridge.server import ProductBridgeConfig, ProductBridgeServer

    spool_dir = tmp_path / "bridge-spool"
    spool_dir.mkdir()
    spool_calls = []

    def forbidden_spool(*args, **kwargs):
        spool_calls.append((args, kwargs))
        raise AssertionError("Product Bridge created a spool before platform rejection")

    monkeypatch.setattr(bridge_server_module.tempfile, "SpooledTemporaryFile", forbidden_spool)
    server = ProductBridgeServer(
        frontend_root=frontend_build(tmp_path / "frontend"),
        upstream_address=("127.0.0.1", 9),
        token=TOKEN,
        recovery_mutation_supported=False,
        config=ProductBridgeConfig(spool_dir=str(spool_dir), upstream_timeout_seconds=0.1),
    )
    server.start()
    try:
        status, _headers, body = bridge_request(
            server,
            "POST",
            "/app-api/v1/recovery/staging",
            headers={
                **browser_mutation_headers(server),
                "Content-Type": "application/octet-stream",
            },
            raw_body=b"synthetic",
        )
    finally:
        server.close()

    assert status == 501
    assert json.loads(body)["error"]["code"] == "RECOVERY_PLATFORM_UNSUPPORTED"
    assert spool_calls == []
    assert list(spool_dir.iterdir()) == []
