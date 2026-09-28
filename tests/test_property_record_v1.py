"""Synthetic property identity: enter once, confirm provenance, reuse safely."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from contextlib import nullcontext

import pytest

from scripts.backend_contract.property_record import (
    PropertyRecord, PropertyValue, PropertyEvidence, property_record_from_mapping,
    property_record_to_mapping, property_proposals,
)


def test_property_is_not_a_duplicate_coordinate_or_claimant_authority():
    value = PropertyValue("street", "Rua Sintética", None, "EXPERT-1", "2026-09-28T12:00:00+00:00")
    record = PropertyRecord("1.0.0", "workspace-one", (value,))
    assert property_record_from_mapping(property_record_to_mapping(record)) == record
    assert record.get("owner") is None
    for field in ("latitude", "longitude", "parte_requerente", "unknown"):
        with pytest.raises(ValueError):
            replace(value, field=field)
    for text in ("NaN", "-1", "1,2,3", "infinity"):
        with pytest.raises(ValueError):
            replace(value, field="private_area_m2", value=text)
    assert replace(value, field="private_area_m2", value="0").value == "0"
    assert replace(value, field="contractual_value", value="120.000,50").value == "120.000,50"


def test_label_extraction_preserves_exact_source_and_never_infers_owner_from_claimant():
    pages = [SimpleNamespace(number=2, text="Autor: Pessoa Sintética\nProprietário: Proprietária Sintética\nLogradouro do imóvel: Rua Sintética\nÁrea privativa: 42,50 m²\n", extraction_mode=SimpleNamespace(value="NATIVE_TEXT"), confidence=None)]
    proposals = property_proposals("workspace-one", "document-one", "a" * 64, "documento.pdf", pages)
    by_field = {p.field: p for p in proposals}
    assert by_field["owner"].value == "Proprietária Sintética"
    assert by_field["street"].evidence.page == 2
    assert by_field["street"].evidence.excerpt == "Logradouro do imóvel: Rua Sintética"
    assert by_field["private_area_m2"].value == "42,50"
    assert not property_proposals("workspace-one", "d", "b" * 64, "autos.pdf", [SimpleNamespace(number=1, text="Autor: Pessoa Sintética", extraction_mode=SimpleNamespace(value="NATIVE_TEXT"), confidence=None)])
    foreign = property_proposals("workspace-two", "document-one", "a" * 64, "documento.pdf", pages)
    assert {p.proposal_id for p in proposals}.isdisjoint(p.proposal_id for p in foreign)


def test_property_value_rejects_false_source_and_duplicate_fields():
    evidence = PropertyEvidence("document-one", "a" * 64, "documento.pdf", 2, "Área privativa: 42,50 m²", "LABEL_NATIVE_TEXT_V1", None, "42,50")
    value = PropertyValue("private_area_m2", "42,50", evidence, "EXPERT-1", "2026-09-28T12:00:00+00:00")
    with pytest.raises(ValueError):
        replace(value, value="99")
    with pytest.raises(ValueError):
        PropertyRecord("1.0.0", "w", (value, value))
    with pytest.raises(ValueError):
        replace(value, confirmed_at="2026-09-28")


def test_confirming_proposal_preserves_other_fields_and_rejects_cross_case_or_stale_id():
    from scripts.backend_contract.application.property_record import GetPropertyRecord, SavePropertyRecord
    from scripts.backend_contract.application.ports import ArtifactRevisionNotFound, RepositoryConflict
    from scripts.backend_contract.application.models import _freeze_payload
    records = []
    def latest(*_args):
        if not records:
            raise ArtifactRevisionNotFound("absent")
        return records[-1]
    def append(**kwargs):
        if kwargs["expected_revision"] != (len(records) or None):
            raise RepositoryConflict("stale")
        record = SimpleNamespace(revision=len(records)+1, payload=_freeze_payload(kwargs["payload"]), created_at=kwargs["created_at"])
        records.append(record)
        return record
    get = GetPropertyRecord(SimpleNamespace(execute=latest))
    profile = SimpleNamespace(profile_id="EXPERT-1")
    proposals = property_proposals("w", "d", "a" * 64, "d.pdf", [SimpleNamespace(number=1, text="Proprietário: Pessoa Sintética", extraction_mode=SimpleNamespace(value="NATIVE_TEXT"), confidence=None)])
    save = SavePropertyRecord(
        get, SimpleNamespace(append_if_latest=append), SimpleNamespace(execute=lambda _w: (None, profile)),
        SimpleNamespace(execute=lambda _w: proposals), nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 9, 28, 12, tzinfo=UTC)),
        SimpleNamespace(new_uuid=lambda: "00000000-0000-4000-8000-000000000001"),
    )
    save.execute("w", changes=[{"field": "street", "value": "Rua Sintética", "proposal_id": None}], expected_revision=None)
    _, saved = save.execute("w", changes=[{"field": "owner", "value": "Pessoa Sintética", "proposal_id": proposals[0].proposal_id}], expected_revision=1)
    assert saved.get("street").value == "Rua Sintética" and saved.get("owner").evidence.document_id == "d"
    for workspace, proposal_id in (("w", "invented"), ("foreign", proposals[0].proposal_id)):
        with pytest.raises(ValueError):
            save.execute(workspace, changes=[{"field": "owner", "value": "Pessoa Sintética", "proposal_id": proposal_id}], expected_revision=2)
    with pytest.raises(RepositoryConflict):
        save.execute("w", changes=[{"field": "street", "value": "Outro local", "proposal_id": None}], expected_revision=1)
    assert len(records) == 2


def test_local_product_saves_property_and_backup_requires_its_professional(tmp_path):
    import json
    from pathlib import Path
    from scripts.backend_contract.local_api.composition import build_local_api
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import _http, TOKEN
    runtime = build_local_api(tmp_path / "property.db", token=TOKEN, private_root=tmp_path / "private")
    runtime.start()
    try:
        status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Imóvel sintético"})
        assert status == 201
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        profile = json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
        assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
        status, empty = _http(runtime, "GET", root + "/property-record")
        assert status == 200 and empty["record"]["values"] == []
        changes = [{"field": "street", "value": "Rua Sintética", "proposal_id": None}]
        status, saved = _http(runtime, "PUT", root + "/property-record", {"expected_revision": None, "changes": changes})
        assert status == 200 and saved["record"]["values"][0]["confirmed_by"] == profile["profile_id"]
        assert _http(runtime, "PUT", root + "/property-record", {"expected_revision": None, "changes": changes})[0] == 409
        assert _http(runtime, "GET", root + "/property-record")[1] == saved
        import pymupdf as fitz
        for owner in ("Pessoa Sintetica A", "Pessoa Sintetica B"):
            with fitz.open() as pdf:
                pdf.new_page().insert_text((72, 72), f"Proprietário do imóvel: {owner}\nÁrea privativa: 42,50 m²")
                source = pdf.tobytes()
            status, _ = _http(runtime, "POST", root + "/materials", raw_body=source, headers={"Content-Type": "application/pdf", "X-Document-Filename": "imovel-sintetico.pdf"})
            assert status == 201
        status, proposed = _http(runtime, "GET", root + "/property-record/proposals")
        assert status == 200
        owners = [p for p in proposed["proposals"] if p["field"] == "owner"]
        assert len(owners) == 2 and all(p["state"] == "CONFLICTING" for p in owners)
        assert _http(runtime, "GET", root + "/property-record")[1] == saved
        chosen = owners[0]
        status, confirmed = _http(runtime, "PUT", root + "/property-record", {"expected_revision": 1, "changes": [{"field": "owner", "value": chosen["value"], "proposal_id": chosen["proposal_id"]}]})
        assert status == 200
        owner = next(v for v in confirmed["record"]["values"] if v["field"] == "owner")
        assert owner["evidence"]["excerpt"] == chosen["evidence"]["excerpt"]
        assert owner["evidence"]["page"] == 1
        assert _http(runtime, "GET", root + "/property-record", headers={"X-Local-API-Token": "invalid"})[0] == 403
        from tests.test_product_integration_oracle_v1 import http_request
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": TOKEN})
        assert status == 200
        restored = VerifyWorkspaceBackup().execute(backup)
        assert any(r["artifact_kind"] == "PROPERTY_RECORD_V1" for r in restored.artifact_revisions)
    finally:
        runtime.close()


def test_report_captures_property_revision_without_mutating_old_reports():
    from scripts.backend_contract.report_foundation import ReportProperty, report_snapshot_from_mapping, report_snapshot_to_mapping
    from scripts.backend_contract.application.report_foundation import _property_reasons
    from tests.test_report_references_findings_v1 import _draft
    value = PropertyValue("street", "Rua Sintética", None, "EXPERT-1", "2026-09-28T12:00:00+00:00")
    report = _draft()
    property_record = PropertyRecord("1.0.0", report.workspace_id, (value,))
    capture = ReportProperty(property_record, 2, "a" * 64)
    snapshot = replace(report, property_record=capture)
    assert report_snapshot_from_mapping(report_snapshot_to_mapping(snapshot)) == snapshot
    getter = SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=2, checksum_sha256="a" * 64), property_record))
    assert _property_reasons(snapshot, getter, report.workspace_id) == ()
    changed = replace(property_record, values=(replace(value, value="Outro endereço"),))
    getter = SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=3, checksum_sha256="b" * 64), changed))
    assert _property_reasons(snapshot, getter, report.workspace_id)
    assert snapshot.property_record.record.get("street").value == "Rua Sintética"
    with pytest.raises(ValueError):
        replace(snapshot, property_record=replace(capture, record=replace(property_record, workspace_id="foreign")))
    assert "property_record" not in report_snapshot_to_mapping(report)


def test_report_process_capture_reuses_the_canonical_ten_fields_and_rejects_other_workspace():
    from scripts.backend_contract.report_foundation import ReportProcess, report_snapshot_to_mapping, report_snapshot_from_mapping
    from scripts.backend_contract.application.report_foundation import _process_reasons
    from scripts.backend_contract.application.models import ProcessCaseData
    from tests.test_report_foundation_v1 import bound_report
    report = bound_report()
    data = ProcessCaseData.empty().as_dict()
    data.update(numero_processo="0000000-00.2026.0.00.0000", vara="Vara sintética", parte_requerente="Parte sintética")
    captured = ReportProcess(workspace_id=report.workspace_id, source_revision=1, source_checksum="c" * 64, **data)
    current = replace(report, process_record=captured)
    assert report_snapshot_from_mapping(report_snapshot_to_mapping(current)) == current
    reader = SimpleNamespace(execute=lambda _w: captured)
    assert _process_reasons(current, reader, report.workspace_id) == ()
    reader.execute = lambda _w: replace(captured, source_revision=2)
    assert _process_reasons(current, reader, report.workspace_id) == ("process record changed",)
    with pytest.raises(ValueError):
        replace(report, process_record=replace(captured, workspace_id="other"))
    assert "process_record" not in report_snapshot_to_mapping(report)


def test_new_version_recaptures_property_and_uses_canonical_save_dependencies():
    from scripts.backend_contract.report_foundation import ReportProperty
    from tests.test_report_version_v1 import _service, _superseded
    stored = _superseded()
    value = PropertyValue("street", "Rua anterior", None, stored.expert_profile.profile_id, "2026-09-28T12:00:00+00:00")
    old = PropertyRecord("1.0.0", stored.workspace_id, (value,))
    stored = replace(stored, property_record=ReportProperty(old, 1, "a" * 64))
    latest = replace(old, values=(replace(value, value="Rua atual"),))
    record = SimpleNamespace(revision=2, checksum_sha256="b" * 64, artifact_kind="PROPERTY_RECORD_V1", artifact_id="PROPERTY-RECORD")
    reader = SimpleNamespace(execute=lambda _w: (record, latest))
    service, appended = _service(stored)
    service = replace(service, get_property_record=reader, save_snapshot=replace(service.save_snapshot, get_property_record=reader))
    _, draft, _ = service.execute(stored.workspace_id, expected_revision=4)
    assert draft.property_record.record.get("street").value == "Rua atual"
    assert stored.property_record.record.get("street").value == "Rua anterior"
    assert not draft.review_decisions and not draft.coverage.complete
    assert any(item["artifact_kind"] == "PROPERTY_RECORD_V1" and item["revision"] == 2 for item in appended[0]["expected_dependencies"])
    forged = replace(draft, property_record=replace(draft.property_record, source_checksum="e" * 64))
    with pytest.raises(ValueError, match="stale"):
        service.save_snapshot.execute(stored.workspace_id, forged, 4)


def test_report_presentation_reuses_confirmed_property_and_process_not_context_typing():
    from scripts.backend_contract.report_foundation import ReportProperty, ReportProcess
    from scripts.backend_contract.delivery_renderer import professional_report_blocks
    from scripts.backend_contract.report_template import _FIELD_VALUES
    from scripts.backend_contract.application.models import ProcessCaseData
    from tests.test_report_foundation_v1 import bound_report
    report = bound_report()
    value = PropertyValue("street", "Rua Sintética", None, report.expert_profile.profile_id, "2026-09-28T12:00:00+00:00")
    record = PropertyRecord("1.0.0", report.workspace_id, (value,))
    process = ProcessCaseData.empty().as_dict()
    process.update(numero_processo="Número confirmado", vara="Vara confirmada", tribunal="Tribunal confirmado")
    report = replace(report, property_record=ReportProperty(record, 1, "a" * 64), process_record=ReportProcess(report.workspace_id, 1, "b" * 64, **process))
    assert "Logradouro: Rua Sintética" in [block.text for block in professional_report_blocks(report)]
    assert _FIELD_VALUES["PROCESS_NUMBER"](report) == "Número confirmado"
    assert _FIELD_VALUES["COURT"](report) == "Vara confirmada · Tribunal confirmado"


@pytest.mark.parametrize("capture_kind", ["property_record", "process_record"])
@pytest.mark.parametrize("tamper", [None, "value", "revision", "checksum"])
def test_backup_captures_are_checked_against_exact_source(capture_kind, tamper):
    import json
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.infrastructure.productization import _revision_from_mapping, _verify_dependency_closure
    from tests.test_product_integration_oracle_v1 import _longitudinal_backup, _digest, _revision
    backup = json.loads(_longitudinal_backup()[0])
    revisions = backup["artifact_revisions"]
    report = next(r for r in revisions if r["artifact_kind"] == "REPORT_SNAPSHOT_V1")
    workspace = backup["workspace"]["workspace_id"]
    if capture_kind == "property_record":
        data = property_record_to_mapping(PropertyRecord("1.0.0", workspace, (PropertyValue("street", "Rua Sintética", None, report["payload"]["expert_profile"]["profile_id"], "2026-09-28T12:00:00+00:00"),)))
        source = _revision("PROPERTY_RECORD_V1", "PROPERTY-RECORD", data, 1, 991)
        revisions.append(source)
        captured = {"record": data, "source_revision": 1, "source_checksum": source["checksum_sha256"]}
        captured = json.loads(json.dumps(captured))
        if tamper == "value":
            captured["record"]["values"][0]["value"] = "Outro imóvel"
    else:
        from scripts.backend_contract.application.models import ProcessCaseData
        data = ProcessCaseData.empty().as_dict()
        data["parte_requerente"] = "Parte sintética"
        source = _revision("PROCESS_CASE", "PROCESS_CASE", data, 1, 992)
        revisions.append(source)
        captured = {**ProcessCaseData.from_mapping(source["payload"]).as_dict(), "workspace_id": workspace, "source_revision": source["revision"], "source_checksum": source["checksum_sha256"]}
        if tamper == "value":
            captured["parte_requerente"] = "Outra pessoa"
    if tamper == "revision":
        captured["source_revision"] = 999
    if tamper == "checksum":
        captured["source_checksum"] = "f" * 64
    report["payload"][capture_kind] = captured
    report["checksum_sha256"] = _digest(report["payload"])
    for revision in revisions:
        if revision["artifact_kind"] == "DELIVERY_SNAPSHOT_V1":
            revision["payload"]["binding"]["report_digest"] = report["checksum_sha256"]
            revision["checksum_sha256"] = _digest(revision["payload"])
    records = tuple(_revision_from_mapping(r, workspace) for r in revisions)
    if tamper:
        with pytest.raises(RepositoryIntegrityError):
            _verify_dependency_closure(records)
    else:
        _verify_dependency_closure(records)
