"""The selected template and current asset must commit as one authority (#291)."""

from datetime import UTC, datetime
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.backend_contract.application.installation_settings import InstallationSettings, validate_installation_template
from scripts.backend_contract.application.ports import RepositoryConflict
from scripts.backend_contract.infrastructure.installation_store import SQLiteInstallationStore
from scripts.backend_contract.installation_settings import AssetRole, SettingKind, TemplateMode
from tests.test_installation_settings_v1 import _custom_template


@pytest.mark.parametrize("separate_connection", [False, True])
@pytest.mark.parametrize("operation,preexisting_selection", [("restore_asset", False), ("upload_asset", False), ("remove_asset", False), ("save_selection", False), ("restore_selection", False), ("restore_asset", True), ("upload_asset", True), ("remove_asset", True)])
def test_template_dependency_change_between_guard_and_append_conflicts(tmp_path, separate_connection, operation, preexisting_selection):
    database = tmp_path / "synthetic-installation.sqlite3"
    store = SQLiteInstallationStore(database)
    other_store = SQLiteInstallationStore(database) if separate_connection else store
    clock = SimpleNamespace(now=lambda: datetime.now(UTC))
    ids = SimpleNamespace(new_uuid=uuid4)
    first = InstallationSettings(store, clock, ids, validate_installation_template)
    other = InstallationSettings(other_store, clock, ids, validate_installation_template)
    role = AssetRole.DEFAULT_WORD_TEMPLATE
    selection_kind = SettingKind.DEFAULT_TEMPLATE_SELECTION
    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    content_a = _custom_template(b"SYNTHETIC-TEMPLATE-A")
    content_b = _custom_template(b"SYNTHETIC-TEMPLATE-B")
    checked, resume = threading.Event(), threading.Event()
    thread = None
    try:
        first.upload_asset(role, filename="a.docx", media_type=media_type, content=content_a, expected_revision=None)
        b = first.upload_asset(role, filename="b.docx", media_type=media_type, content=content_b, expected_revision=1)
        custom_b = {"mode": "CUSTOM", "template_sha256": b.payload["sha256"]}
        selection_revision = None
        if preexisting_selection:
            first.save(selection_kind, {"mode": "PRODUCT_DEFAULT", "template_sha256": None}, None)
            selection_revision = 1
        if operation == "restore_selection":
            first.save(selection_kind, custom_b, None)
            first.save(selection_kind, {"mode": "PRODUCT_DEFAULT", "template_sha256": None}, 1)
            selection_revision = 2
        kind = SettingKind.INSTALLATION_ASSET if operation.endswith("asset") else selection_kind
        append = store.append_if_latest
        def paused_append(**kw):
            if threading.current_thread() is thread and kw["setting_kind"] == kind.value:
                checked.set()
                assert resume.wait(10), "competing operation must release the append"
            return append(**kw)
        store.append_if_latest = paused_append
        outcome = []
        def mutate():
            try:
                if operation == "restore_asset":
                    first.restore(SettingKind.INSTALLATION_ASSET, 1, 2, setting_id=role.value)
                elif operation == "upload_asset":
                    first.upload_asset(role, filename="a-again.docx", media_type=media_type, content=content_a, expected_revision=2)
                elif operation == "remove_asset":
                    first.remove_asset(role, 2)
                elif operation == "save_selection":
                    first.save(selection_kind, custom_b, selection_revision)
                else:
                    first.restore(selection_kind, 1, selection_revision)
                outcome.append("committed")
            except Exception as exc:
                outcome.append(exc)
        thread = threading.Thread(target=mutate)
        thread.start()
        assert checked.wait(10), "the first operation must reach its validated append"
        if kind is SettingKind.INSTALLATION_ASSET:
            other.save(selection_kind, custom_b, selection_revision)
        else:
            other.restore(SettingKind.INSTALLATION_ASSET, 1, 2, setting_id=role.value)
        resume.set()
        thread.join(10)
        assert not thread.is_alive()
        assert len(outcome) == 1 and isinstance(outcome[0], RepositoryConflict), outcome
        selection = first.latest(selection_kind)
        asset_record, asset = first.asset_record(role)
        if kind is SettingKind.INSTALLATION_ASSET:
            assert asset_record.revision == 2 and asset.filename == "b.docx"
            assert selection.payload["template_sha256"] == asset.sha256
        else:
            assert asset_record.revision == 3 and asset.filename == "a.docx"
            assert selection is None or selection.payload["mode"] == TemplateMode.PRODUCT_DEFAULT.value
        # Both Word files and every prior revision remain append-only.
        assert len(first.history(SettingKind.INSTALLATION_ASSET, role.value)) == asset_record.revision
        assert store.get_asset(b.payload["sha256"]).content == content_b
    finally:
        resume.set()
        if thread is not None:
            thread.join(10)
        if separate_connection:
            other_store.close()
        store.close()
