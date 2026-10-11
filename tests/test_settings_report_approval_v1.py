"""Synthetic persisted regression of the settings/Report approval boundary (#291)."""

import ast
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts.planejamento_pericial.app_composition import build_pericial_application
from scripts.backend_contract.application.models import _freeze_payload, thaw_payload
from scripts.backend_contract.application.ports import RepositoryConflict, RepositoryIntegrityError
from scripts.backend_contract.application.report_foundation import GetReportSnapshot, SaveReportSnapshot, validated_report_snapshot_from_mapping
from scripts.backend_contract.application.delivery_foundation import StoreDefaultDeliveryTemplate
from scripts.backend_contract.installation_settings import WORKSPACE_SETTINGS_KIND, WORKSPACE_SETTINGS_ID, DEFAULT_PRESENTATION, DEFAULT_BRANDING, TemplateMode
from scripts.backend_contract.report_foundation import ReportState, report_snapshot_to_mapping
from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
from tests.test_document_intake_v1 import provision_private_root
from tests.test_installation_settings_v1 import _profile
import tests.test_product_integration_oracle_v1 as oracle
from tests.test_report_foundation_v1 import bound_report, upstreams
from tests.test_local_persistence_v1 import workspace


@pytest.fixture
def approved_settings_case(tmp_path):
    """Reuse only the existing synthetic input workflow up to Report approval.

    This does not run the oracle's delivery/recovery/RC sequence. The assertions
    below are independent of that input setup and exercise the actual services.
    """
    static = tmp_path / "frontend"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>Synthetic test</title>", encoding="utf-8")
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_application(tmp_path / "cases.sqlite3", static, token=oracle.TOKEN, private_root=private)
    runtime.start()
    try:
        status, result = oracle._bridge_http(runtime, "PUT", "/app-api/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": None, "payload": _profile()})
        assert status == 200, result
        status, workspace = oracle._bridge_http(runtime, "POST", "/app-api/v1/workspaces", {"name": "Synthetic settings approval"})
        assert status == 201, workspace
        workspace_id = workspace["workspace_id"]
        root = f"/app-api/v1/workspaces/{workspace_id}"
        status, profile = oracle._bridge_http(runtime, "GET", root + "/expert-profile")
        assert status == 200, profile
        pdf = tmp_path / "synthetic-process.pdf"
        oracle._pdf_sintetico_com_jdm(pdf)
        source = Path(oracle.__file__).read_text(encoding="utf-8")
        function = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "test_longitudinal_oracle_starts_with_synthetic_pje_through_product_bridge")
        body = next(node for node in function.body if isinstance(node, ast.Try)).body
        steps = []
        for node in body[4:]:
            text = ast.unparse(node)
            if "expert-profile" in text or "profile_response" in text or (isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "profile" for target in node.targets)):
                continue
            steps.append(node)
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "report_digest" for target in node.targets):
                break
        namespace = dict(vars(oracle), runtime=runtime, tmp_path=tmp_path, pdf=pdf, workspace_id=workspace_id, root=root, profile=profile["profile"])
        exec(compile(ast.fix_missing_locations(ast.Module(body=steps, type_ignores=[])), "<synthetic-report-input-setup>", "exec"), namespace)
        report = namespace["report"]
        assert report["snapshot"]["state"] == "APPROVED" and not report["snapshot"]["upstream_stale"]
        yield runtime, root, report, profile
    finally:
        runtime.close()


def test_refresh_without_profile_invalidates_approval_and_preserves_captured_history(approved_settings_case, tmp_path):
    runtime, root, before, profile_before = approved_settings_case
    status, template = oracle._bridge_http(runtime, "POST", root + "/delivery-templates/default", {})
    assert status == 201, template
    packages = []
    def backup():
        status, _, content = oracle.http_request(runtime._local_api.server, "POST", root.removeprefix("/app-api") + "/backup", value={}, headers={"X-Local-API-Token": oracle.TOKEN})
        assert status == 200
        packages.append(content)
        return VerifyWorkspaceBackup().execute(content)
    original = backup()
    status, overview = oracle._bridge_http(runtime, "GET", "/app-api/v1/installation/settings")
    assert status == 200
    presentation = overview["settings"]["DOCUMENT_PRESENTATION_PROFILE_V1"]["payload"]
    presentation["cover"]["title"] = "Synthetic cover changed after approval"
    status, saved = oracle._bridge_http(runtime, "PUT", "/app-api/v1/installation/settings/DOCUMENT_PRESENTATION_PROFILE_V1", {"expected_revision": overview["settings"]["DOCUMENT_PRESENTATION_PROFILE_V1"]["revision"], "payload": presentation})
    assert status == 200, saved
    status, unchanged = oracle._bridge_http(runtime, "GET", root + "/report-snapshot")
    assert status == 200 and unchanged == before, "global edits alone never change a case"
    status, refreshed = oracle._bridge_http(runtime, "POST", root + "/settings-snapshot/refresh", {"include_profile": False, "expected_snapshot_revision": 1, "expected_profile_revision": None})
    assert status == 200 and refreshed["revision"] == 2
    status, after = oracle._bridge_http(runtime, "GET", root + "/report-snapshot")
    assert status == 200, after
    assert after["snapshot"]["upstream_stale"] is True
    assert after["snapshot"]["state"] == "DRAFT"
    assert after["snapshot"]["review_decisions"] == []
    assert after["revision"] == before["revision"], "invalidation is observed without rewriting approval history"
    assert after["review_history"]["captured_state"] == "APPROVED"
    assert after["review_history"]["last_review"] == before["snapshot"]["review_decisions"][-1]
    assert oracle._bridge_http(runtime, "GET", root + "/expert-profile")[1] == profile_before
    status, rejected = oracle._bridge_http(runtime, "POST", root + "/delivery-templates/default", {})
    assert status == 400 and rejected["error"]["code"] == "INVALID_REQUEST", rejected
    # Read-only observation remains stale after another read; no approval is
    # resurrected merely because every technical/profile source is unchanged.
    assert oracle._bridge_http(runtime, "GET", root + "/report-snapshot")[1] == after
    assert before["snapshot"]["source_snapshot"]["workspace_settings_revision"] == 1
    # Restoring the old global bytes and explicitly capturing them again does
    # not promote the old approval. A new version must start its review again.
    status, restored = oracle._bridge_http(runtime, "POST", "/app-api/v1/installation/settings/DOCUMENT_PRESENTATION_PROFILE_V1/restore", {"revision": 1, "expected_revision": saved["settings"]["DOCUMENT_PRESENTATION_PROFILE_V1"]["revision"]})
    assert status == 200, restored
    status, refreshed = oracle._bridge_http(runtime, "POST", root + "/settings-snapshot/refresh", {"include_profile": False, "expected_snapshot_revision": 2, "expected_profile_revision": None})
    assert status == 200 and refreshed["revision"] == 3
    assert oracle._bridge_http(runtime, "GET", root + "/report-snapshot")[1] == after
    status, new = oracle._bridge_http(runtime, "POST", root + "/report-snapshot/versions", {"expected_revision": before["revision"]})
    assert status == 201, new
    assert new["snapshot"]["state"] == "DRAFT" and not new["snapshot"]["upstream_stale"]
    assert new["snapshot"]["source_snapshot"]["workspace_settings_revision"] == 3
    assert new["snapshot"]["review_decisions"] == []
    for action in ("MARK_REVIEWED", "APPROVE"):
        status, new = oracle._bridge_http(runtime, "POST", root + "/report-snapshot/reviews", {"expected_revision": new["revision"], "action": action, "professional_id": new["snapshot"]["expert_profile"]["profile_id"], "reason": "Synthetic explicit review after case settings refresh"})
        assert status == 200, new
    assert new["snapshot"]["state"] == "APPROVED"
    status, current_template = oracle._bridge_http(runtime, "POST", root + "/delivery-templates/default", {})
    assert status == 201, current_template
    # The backup verifier reopens the full append-only history: old approval,
    # settings binding and Word bytes remain exactly as originally stored.
    final = backup()
    by_revision = {item["revision_id"]: item for item in final.artifact_revisions}
    for item in original.artifact_revisions:
        assert by_revision[item["revision_id"]] == item
    old_word = template["template"]["content_id"]
    assert next(item for item in final.private_contents if item["content_id"] == old_word) == next(item for item in original.private_contents if item["content_id"] == old_word)
    if os.name == "nt":
        from tests.test_backup_recovery_reachability_v1 import _runtime, _json
        from tests.test_recovery_transaction_v1 import _stage, _promote
        target = _runtime(tmp_path, "settings-recovery-target")
        try:
            _, globals_before = _json(target, "GET", "/v1/installation/settings")
            status, staged = _stage(target, packages[-1])
            assert status == 201, staged
            status, promoted = _promote(target, staged["recovery_id"])
            assert status == 200, promoted
            status, recovered = _json(target, "GET", root.removeprefix("/app-api") + "/report-snapshot")
            assert status == 200, recovered
            assert recovered["snapshot"] == new["snapshot"] and recovered["snapshot"]["state"] == "APPROVED"
            assert _json(target, "GET", "/v1/installation/settings")[1] == globals_before
            assert _json(target, "GET", root.removeprefix("/app-api") + "/expert-profile")[1] == profile_before
        finally:
            target.close()


def _settings_reader(workspace_id, revision=1, digest="f" * 64):
    record = SimpleNamespace(workspace_id=workspace_id, artifact_kind=WORKSPACE_SETTINGS_KIND, artifact_id=WORKSPACE_SETTINGS_ID, revision=revision, checksum_sha256=digest)
    return SimpleNamespace(current=lambda _w: (record, SimpleNamespace(workspace_id=workspace_id)))


def _report_reader(snapshot, settings):
    records, case, inspection, technical, profile = upstreams()
    stored = SimpleNamespace(revision=4, payload=_freeze_payload(report_snapshot_to_mapping(snapshot)))
    readers = tuple(SimpleNamespace(execute=lambda _w, pair=pair: pair) for pair in zip(records, (case, inspection, technical, profile)))
    return GetReportSnapshot(SimpleNamespace(execute=lambda *_a: stored), *readers, get_workspace_settings=settings), stored


@pytest.mark.parametrize("revision,digest", [(None, "f" * 64), (1, None), (True, "f" * 64), (0, "f" * 64), (1, "F" * 64), (1, "short")])
def test_settings_binding_rejects_partial_or_invalid_pairs(revision, digest):
    mapping = report_snapshot_to_mapping(bound_report())
    mapping["source_snapshot"].update(workspace_settings_revision=revision, workspace_settings_digest=digest)
    with pytest.raises(ValueError):
        validated_report_snapshot_from_mapping(mapping)


def test_legacy_report_bytes_are_unchanged_but_a_later_case_refresh_requires_review():
    report = bound_report()
    mapping = report_snapshot_to_mapping(report)
    assert "workspace_settings_revision" not in mapping["source_snapshot"]
    assert report_snapshot_to_mapping(validated_report_snapshot_from_mapping(mapping)) == mapping
    initial, stored = _report_reader(report, _settings_reader(report.workspace_id))
    assert initial.execute(report.workspace_id)[1] == report
    changed, _ = _report_reader(report, _settings_reader(report.workspace_id, revision=2))
    observed = changed.execute(report.workspace_id)[1]
    assert observed.upstream_stale and observed.state is ReportState.DRAFT
    assert thaw_payload(stored.payload) == mapping


@pytest.mark.parametrize("revision,digest", [(2, "f" * 64), (1, "a" * 64), (None, None)])
def test_settings_revision_digest_or_missing_capture_cannot_resurrect_approval(revision, digest):
    report = bound_report()
    report = replace(report, source_snapshot=replace(report.source_snapshot, workspace_settings_revision=1, workspace_settings_digest="f" * 64))
    settings = _settings_reader(report.workspace_id, revision, digest) if revision is not None else SimpleNamespace(current=lambda _w: (None, None))
    reader, stored = _report_reader(report, settings)
    observed = reader.execute(report.workspace_id)[1]
    assert observed.upstream_stale and observed.review_decisions == ()
    assert thaw_payload(stored.payload)["review_decisions"] == report_snapshot_to_mapping(report)["review_decisions"]


def test_case_settings_identity_is_not_taken_from_another_workspace():
    report = bound_report()
    reader, _ = _report_reader(report, _settings_reader("22222222-2222-4222-8222-222222222222"))
    with pytest.raises(ValueError, match="settings authority mismatch"):
        reader.execute(report.workspace_id)


def test_bound_report_reopens_with_its_case_capture_without_accessing_global_defaults():
    report = bound_report()
    report = replace(report, source_snapshot=replace(report.source_snapshot, workspace_settings_revision=1, workspace_settings_digest="f" * 64))
    mapping = report_snapshot_to_mapping(report)
    assert validated_report_snapshot_from_mapping(mapping) == report
    reader, _ = _report_reader(report, _settings_reader(report.workspace_id))
    assert reader.execute(report.workspace_id)[1] == report


@pytest.mark.parametrize("revision,digest,legacy", [(2, "a" * 64, False), (1, "a" * 64, False), (None, None, False), (2, "a" * 64, True)])
def test_template_cannot_consume_settings_that_advanced_after_the_approved_report_read(revision, digest, legacy):
    report = bound_report()
    if not legacy:
        report = replace(report, source_snapshot=replace(report.source_snapshot, workspace_settings_revision=1, workspace_settings_digest="f" * 64))
    settings = SimpleNamespace(assets=(), presentation=DEFAULT_PRESENTATION, branding=DEFAULT_BRANDING, template_selection=SimpleNamespace(mode=TemplateMode.PRODUCT_DEFAULT))
    record = SimpleNamespace(revision=revision, checksum_sha256=digest) if revision is not None else None
    if record is None:
        settings = None
    written = []
    service = StoreDefaultDeliveryTemplate(SimpleNamespace(execute=lambda _w: (None, report)), SimpleNamespace(execute=lambda **kw: written.append(kw) or SimpleNamespace()), SimpleNamespace(current=lambda _w: (record, settings)), SimpleNamespace())
    with pytest.raises(ValueError, match="settings.*approved report"):
        service.execute(report.workspace_id)
    assert written == []


def test_backup_cannot_accept_a_report_binding_to_absent_case_settings():
    package, _ = oracle._longitudinal_backup()
    mapping = json.loads(package)
    report = next(item for item in mapping["artifact_revisions"] if item["artifact_kind"] == "REPORT_SNAPSHOT_V1")
    report["payload"]["source_snapshot"].update(workspace_settings_revision=1, workspace_settings_digest="f" * 64)
    for item in mapping["artifact_revisions"]:
        if item["artifact_kind"] == "DELIVERY_SNAPSHOT_V1":
            item["payload"]["binding"]["report_digest"] = oracle._digest(report["payload"])
    with pytest.raises(RepositoryIntegrityError, match="dependency closure"):
        VerifyWorkspaceBackup().execute(oracle._reseal(mapping))


def test_save_fences_the_exact_captured_case_settings_without_a_second_read(tmp_path):
    report = bound_report()
    report = replace(report, source_snapshot=replace(report.source_snapshot, workspace_settings_revision=1, workspace_settings_digest="f" * 64))
    records, case, inspection, technical, profile = upstreams()
    readers = tuple(SimpleNamespace(execute=lambda _w, pair=pair: pair) for pair in zip(records, (case, inspection, technical, profile)))
    stored = SimpleNamespace(payload=_freeze_payload(report_snapshot_to_mapping(report)))
    settings = _settings_reader(report.workspace_id)
    calls = []
    read = settings.current
    settings.current = lambda w: calls.append(w) or read(w)
    captured = {}
    save = SaveReportSnapshot(SimpleNamespace(append_if_latest=lambda **kw: captured.update(kw) or SimpleNamespace(revision=5)), *readers, SimpleNamespace(execute=lambda *_a: stored), nullcontext, SimpleNamespace(now=lambda: datetime.now(UTC)), SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999")), get_workspace_settings=settings)
    save.execute(report.workspace_id, report, 4)
    assert calls == [report.workspace_id]
    assert {"artifact_kind": WORKSPACE_SETTINGS_KIND, "artifact_id": WORKSPACE_SETTINGS_ID, "revision": 1, "checksum_sha256": "f" * 64} in captured["expected_dependencies"]
    assert json.loads(json.dumps(captured["payload"]))["source_snapshot"]["workspace_settings_revision"] == 1
    repository = SQLiteApplicationStore(tmp_path / "settings-race.sqlite3")
    try:
        repository.workspaces.create(workspace())
        current = repository.revisions.append(workspace_id=workspace().workspace_id, artifact_kind=WORKSPACE_SETTINGS_KIND, artifact_id=WORKSPACE_SETTINGS_ID, revision_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", created_at="2026-10-11T12:00:00+00:00", payload={"synthetic": "initial"})
        report = replace(report, source_snapshot=replace(report.source_snapshot, workspace_settings_digest=current.checksum_sha256))
        stored.payload = _freeze_payload(report_snapshot_to_mapping(report))
        record = SimpleNamespace(**{**vars(read(report.workspace_id)[0]), "checksum_sha256": current.checksum_sha256})
        settings.current = lambda _w: (record, SimpleNamespace(workspace_id=report.workspace_id))
        def concurrent_append(**kw):
            repository.revisions.append(workspace_id=workspace().workspace_id, artifact_kind=WORKSPACE_SETTINGS_KIND, artifact_id=WORKSPACE_SETTINGS_ID, revision_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", created_at="2026-10-11T12:00:01+00:00", payload={"synthetic": "changed during commit"})
            dependency = next(item for item in kw["expected_dependencies"] if item["artifact_kind"] == WORKSPACE_SETTINGS_KIND)
            # Exercise the real CAS repository with the exact dependency emitted
            # by SaveReportSnapshot; no report append may escape that fence.
            return repository.revisions.append_if_latest(**{**kw, "workspace_id": workspace().workspace_id, "expected_revision": None, "expected_dependencies": (dependency,)})
        raced = replace(save, revisions=SimpleNamespace(append_if_latest=concurrent_append))
        with pytest.raises(RepositoryConflict):
            raced.execute(report.workspace_id, report, 4)
        assert not repository.revisions.list_all(workspace().workspace_id, "REPORT_SNAPSHOT_V1", "REPORT-SNAPSHOT")
    finally:
        repository.close()
