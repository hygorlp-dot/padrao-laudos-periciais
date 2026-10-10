"""3C: a preparação deve continuar exata antes da primeira mutação viva."""
import os
import sqlite3

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
