"""3C: a preparação deve continuar exata antes da primeira mutação viva."""
import os
import sqlite3
import ctypes
from ctypes import wintypes

import pytest

from tests.test_backup_recovery_reachability_v1 import _json, _runtime, _workspace_with_material

pytestmark = pytest.mark.skipif(os.name != "nt", reason="mutable recovery is Windows-only")


@pytest.mark.parametrize("damage", ("workspace_name", "private_byte"))
def test_tampered_staging_is_refused_before_any_live_workspace(tmp_path, damage):
    source = _runtime(tmp_path, "source")
    target = _runtime(tmp_path, "target")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path, "Perícia sintética")
        from tests.test_recovery_transaction_v1 import _pacote, _stage, _promote
        package = _pacote(source, workspace_id)
        status, staged = _stage(target, package)
        assert status == 201, staged
        root = next(tmp_path.rglob("recovery-" + staged["recovery_id"]))
        if damage == "workspace_name":
            with sqlite3.connect(root / "workspace.sqlite3") as connection:
                connection.execute("UPDATE workspaces SET name=? WHERE workspace_id=?", ("Nome adulterado", workspace_id))
        else:
            content = next(root.rglob("*.content"))
            with content.open("r+b") as stream:
                stream.seek(0)
                stream.write(b"!")
        status, result = _promote(target, staged["recovery_id"])
        assert status in (400, 409, 500), result
        status, workspaces = _json(target, "GET", "/v1/workspaces")
        assert status == 200
        assert not workspaces["items"], "tampered staging must never publish even a partial workspace"
    finally:
        source.close()
        target.close()


@pytest.mark.parametrize("restart", (False, True))
def test_temporarily_locked_descriptor_preserves_same_resumable_promotion(tmp_path, restart):
    import json
    from tests.test_recovery_transaction_v1 import (
        _interromper_promocao, _journal_da_unica_raiz, _promote,
    )
    workspace_id, package, target, recovery_id = _interromper_promocao(tmp_path, "descriptor-lock")
    journal = _journal_da_unica_raiz(tmp_path, "descriptor-lock")
    before = journal.read_bytes()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(journal.parent / "RECOVERY_SESSION_V1"), 0x80000000, 0,
                                None, 3, 0x80, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    try:
        try:
            status, result = _promote(target, recovery_id)
            assert status == 409 and result["error"]["code"] == "RECOVERY_PROMOTION_INCOMPLETE", result
            assert journal.read_bytes() == before, "transient unavailability must not rewrite durable authority"
        finally:
            assert kernel.CloseHandle(handle)
        if restart:
            target.close()
            target = _runtime(tmp_path, "descriptor-lock")
        status, promoted = _promote(target, recovery_id)
        assert status == 200, promoted
        status, materials = _json(target, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert status == 200
        expected = json.loads(package)["private_contents"]
        assert {(m["content_id"], m["checksum_sha256"]) for m in materials["items"]} == {
            (m["content_id"], m["checksum_sha256"]) for m in expected
        }
        assert len(materials["items"]) == len(expected), "resume must not duplicate original private contents"
    finally:
        target.close()
