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


def _text_pdf(lines):
    """PDF de uma pagina com camada de texto, usando apenas `pypdf` (dependencia do produto).

    Os rotulos procurados sao acentuados ("Proprietário", "Área privativa", "m²"), entao
    a fonte declara WinAnsiEncoding e o texto vai em cp1252 com escape octal: a extracao
    devolve exatamente as linhas escritas, e o teste nao passa nem falha por perda de acento.
    """
    import io

    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    def literal(text):
        return "(" + "".join(
            chr(byte) if 32 <= byte < 127 and byte not in b"()\\" else "\\%03o" % byte
            for byte in text.encode("cp1252")
        ) + ")"

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)}),
    })
    body = " ".join(f"{literal(line)} Tj 0 -14 Td" for line in lines)
    stream = StreamObject()
    stream.set_data(f"BT /F1 11 Tf 72 720 Td {body} ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


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
        for owner in ("Pessoa Sintetica A", "Pessoa Sintetica B"):
            source = _text_pdf([f"Proprietário do imóvel: {owner}", "Área privativa: 42,50 m²"])
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
        from tests.test_product_integration_oracle_v1 import _reseal
        from scripts.backend_contract.application.ports import RepositoryIntegrityError
        for tamper in ("page", "excerpt", "method"):
            altered = json.loads(backup)
            property_revision = next(r for r in altered["artifact_revisions"] if r["artifact_kind"] == "PROPERTY_RECORD_V1" and r["revision"] == 2)
            value = next(v for v in property_revision["payload"]["values"] if v["field"] == "owner")
            if tamper == "page":
                value["evidence"]["page"] = 2
            elif tamper == "excerpt":
                value["value"] = value["evidence"]["source_value"] = "Pessoa inventada"
                value["evidence"]["excerpt"] = "Proprietário do imóvel: Pessoa inventada"
            else:
                value["evidence"]["method"] = "LABEL_OCR_V1"
            with pytest.raises(RepositoryIntegrityError, match="property source evidence"):
                VerifyWorkspaceBackup().execute(_reseal(altered))
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
    # AUDITOR_TEST_CHANGED | RESPONSE_SHAPE_ADAPTATION: duble segue o contrato real da
    # porta de leitura (`stale_fields`); nenhuma fonte excluida neste cenario.
    getter = SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=2, checksum_sha256="a" * 64), property_record), stale_fields=lambda _w, _r: ())
    assert _property_reasons(snapshot, getter, report.workspace_id) == ()
    changed = replace(property_record, values=(replace(value, value="Outro endereço"),))
    getter = SimpleNamespace(execute=lambda _w: (SimpleNamespace(revision=3, checksum_sha256="b" * 64), changed), stale_fields=lambda _w, _r: ())
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
    # AUDITOR_TEST_CHANGED | RESPONSE_SHAPE_ADAPTATION: a porta de leitura do imovel
    # passou a projetar a disponibilidade vigente das fontes (`stale_fields`). O duble
    # segue o contrato real; aqui nenhuma fonte foi excluida.
    reader = SimpleNamespace(execute=lambda _w: (record, latest), stale_fields=lambda _w, _r: ())
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
    from scripts.backend_contract.delivery_renderer import canonical_report_audit_lines
    audit = "\n".join(canonical_report_audit_lines(report))
    assert "PROPERTY_RECORD_V1" in audit and "Rua Sintética" in audit
    assert "PROCESS_CASE" in audit and "Número confirmado" in audit


def test_process_change_between_validation_and_commit_conflicts_without_appending_report():
    from scripts.backend_contract.application.models import ProcessCaseData
    from scripts.backend_contract.application.ports import RepositoryConflict
    from scripts.backend_contract.report_foundation import ReportProcess
    from tests.test_report_version_v1 import _service, _superseded
    stored = _superseded()
    captured = ReportProcess(stored.workspace_id, 1, "a" * 64, **ProcessCaseData.empty().as_dict())
    current_revision = 1
    calls = 0
    def captured_then_advance(_workspace):
        nonlocal current_revision, calls
        calls += 1
        if calls == 2:
            current_revision = 2  # Another ProcessCase request commits after validation's read.
        return captured
    service, appended = _service(stored)
    previous_latest = service.get_latest_revision.execute
    latest = SimpleNamespace(execute=lambda workspace, kind, identity: SimpleNamespace(artifact_kind=kind, artifact_id=identity, revision=current_revision, checksum_sha256=("a" if current_revision == 1 else "b") * 64) if kind == "PROCESS_CASE" else previous_latest(workspace, kind, identity))
    previous_append = service.save_snapshot.revisions.append_if_latest
    def commit(**kwargs):
        dependency = next(item for item in kwargs["expected_dependencies"] if item["artifact_kind"] == "PROCESS_CASE")
        if dependency["revision"] != current_revision:
            raise RepositoryConflict("dependency advanced")
        return previous_append(**kwargs)
    reader = SimpleNamespace(execute=captured_then_advance)
    save = replace(service.save_snapshot, get_latest_revision=latest, get_process_record=reader, revisions=SimpleNamespace(append_if_latest=commit))
    service = replace(service, get_latest_revision=latest, get_process_record=reader, save_snapshot=save)
    with pytest.raises(RepositoryConflict, match="dependency advanced"):
        service.execute(stored.workspace_id, expected_revision=4)
    assert appended == []


@pytest.mark.parametrize("missing", ["number", "court"])
def test_partial_captured_process_cannot_be_presented_as_approved(missing):
    from scripts.backend_contract.application.models import ProcessCaseData
    from scripts.backend_contract.report_foundation import ReportProcess
    from tests.test_report_foundation_v1 import bound_report
    report = bound_report()
    data = ProcessCaseData.empty().as_dict()
    data.update(numero_processo="Processo confirmado", vara="Vara confirmada")
    data["numero_processo" if missing == "number" else "vara"] = ""
    captured = ReportProcess(report.workspace_id, 1, "a" * 64, **data)
    with pytest.raises(ValueError, match="captured process identity"):
        replace(report, process_record=captured)


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
        data.update(parte_requerente="Parte sintética", numero_processo="Número sintético", vara="Vara sintética")
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


def test_real_local_ocr_property_evidence_survives_backup_replay():
    import json
    from hashlib import sha256
    from io import BytesIO
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from scripts.backend_contract.infrastructure.pdf_text import LocalPdfTextExtractor
    from scripts.backend_contract.infrastructure.rapid_ocr import RapidOcrLatinEngine
    from tests.test_local_ocr_v1 import scanned_pdf
    from tests.test_product_integration_oracle_v1 import _longitudinal_backup, _private, _revision, _reseal
    backup = json.loads(_longitudinal_backup()[0])
    workspace = backup["workspace"]["workspace_id"]
    source = scanned_pdf("CEP: 40000-000")
    document_id = "81000000-0000-4000-8000-000000000001"
    checksum = sha256(source).hexdigest()
    result = LocalPdfTextExtractor(ocr_engine=RapidOcrLatinEngine()).extract(BytesIO(source), document_sha256=checksum)
    proposals = property_proposals(workspace, document_id, checksum, "imovel-digitalizado.pdf", result.pages)
    proposal = next(p for p in proposals if p.field == "postal_code")
    assert proposal.value == "40000-000" and proposal.evidence.method == "LABEL_OCR_V1"
    profile = next(r["payload"] for r in backup["artifact_revisions"] if r["artifact_kind"] == "EXPERT_MASTER_PROFILE_V1")
    record = PropertyRecord("1.0.0", workspace, (PropertyValue(proposal.field, proposal.value, proposal.evidence, profile["profile_id"], "2026-09-28T12:00:00+00:00"),))
    backup["artifact_revisions"].append(_revision("PROPERTY_RECORD_V1", "PROPERTY-RECORD", property_record_to_mapping(record), 1, 995))
    backup["artifact_revisions"].sort(key=lambda r: (r["artifact_kind"], r["artifact_id"], r["revision"]))
    backup["private_contents"].append(_private(document_id, source, "imovel-digitalizado.pdf", "application/pdf"))
    assert VerifyWorkspaceBackup().execute(_reseal(backup)).workspace.workspace_id == workspace


def _pje_export_with_owner(path, owner_line):
    """Export PJe sintetico cuja linha de proprietario fica na p. 4, dentro do DOC-PJE-002.

    Mesma estrutura de `tests.test_final_closure_r7.pdf_sintetico` (indice na p. 1,
    DOC-PJE-001 na p. 2, pagina complementar na p. 3, DOC-PJE-002 na p. 4), com a
    linha do proprietario acrescentada a peca 2.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    writer = PdfWriter()

    def page(commands):
        added = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        added[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = StreamObject()
        stream.set_data(commands.encode("ascii"))
        added[NameObject("/Contents")] = writer._add_object(stream)

    grid = " ".join(f"{x} 650 m {x} 740 l S" for x in (40, 140, 260, 480, 570)) + " 40 650 m 570 650 l S 40 680 m 570 680 l S 40 710 m 570 710 l S 40 740 m 570 740 l S"
    index = "BT /F1 10 Tf 45 720 Td (ID) Tj 100 0 Td (Data) Tj 120 0 Td (Titulo) Tj 220 0 Td (Tipo) Tj ET BT /F1 10 Tf 45 690 Td (900001) Tj 100 0 Td (01/01/2026) Tj 120 0 Td (Manifestacao da parte autora) Tj 220 0 Td (PETICAO) Tj ET BT /F1 10 Tf 45 660 Td (900002) Tj 100 0 Td (02/01/2026) Tj 120 0 Td (Decisao sintetica) Tj 220 0 Td (DECISAO) Tj ET"
    page(grid + index + " BT /F1 10 Tf 40 760 Td (Processo 0000001-00.2026.4.00.0001) Tj ET")
    page("BT /F1 10 Tf 40 730 Td (A autora alega infiltracao e fissura no imovel por vicio construtivo.) Tj 0 -20 Td (O objeto da pericia e o imovel e o objetivo da pericia e determinar a causa.) Tj 0 -20 Td (QUESITOS:) Tj 0 -20 Td (1. Existe umidade na parede?) Tj 0 -630 Td (Num. 900001 - Pag. 1) Tj ET")
    page("BT /F1 10 Tf 40 730 Td (Pagina complementar sem rodape e sem link) Tj ET")
    page(f"BT /F1 10 Tf 40 730 Td (DECISAO: defiro pericia para verificar infiltracao, fissura e determinar a causa.) Tj 0 -20 Td (O objeto da pericia e o imovel e o objetivo da pericia e sanear a controversia.) Tj 0 -20 Td ({owner_line}) Tj 0 -630 Td (Num. 900002 - Pag. 1) Tj ET")
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def test_a_pje_document_excluded_by_the_professional_does_not_feed_property_proposals(tmp_path):
    """A exclusao profissional de uma peca PJe precisa alcancar o cadastro do imovel.

    As propostas leem o arquivo FISICO inteiro, mas a exclusao recai sobre o
    documento LOGICO. Antes do reparo, a linha do proprietario de uma peca excluida
    seguia como PROPOSED, podia ser confirmada e ia ao laudo citando a pagina que o
    perito tirou da analise.

    Os controles impedem o teste de ficar verde pelo motivo errado: a proposta
    existe antes da exclusao (e vem da p. 4), excluir OUTRA peca nao a afeta, e
    reabilitar a traz de volta.
    """
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api
    from tests.test_document_intake_v1 import provision_private_root
    from tests.test_product_integration_oracle_v1 import _http, _fixture, TOKEN

    provision_private_root(tmp_path / "private")
    pdf = _pje_export_with_owner(tmp_path / "autos.pdf", "Proprietario do imovel: Pessoa Sintetica Excluida")
    runtime = build_pericial_local_api(tmp_path / "property.db", private_root=tmp_path / "private", token=TOKEN)
    runtime.start()
    try:
        workspace_id = _http(runtime, "POST", "/v1/workspaces", {"name": "Imovel PJe"})[1]["workspace_id"]
        root = f"/v1/workspaces/{workspace_id}"
        profile = _fixture("report-snapshot-v1.json")["expert_profile"]
        assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
        status, material = _http(runtime, "POST", root + "/materials", raw_body=pdf.read_bytes(), headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        assert status == 201, material
        content_id = material["content_id"]

        def owners():
            status, body = _http(runtime, "GET", root + "/property-record/proposals")
            assert status == 200, body
            return [p for p in body["proposals"] if p["field"] == "owner"]

        def set_available(document_id, available):
            intake = next(i for i in _http(runtime, "GET", root + "/pje-intake")[1]["intakes"] if i["inventory"]["storage_content_id"] == content_id)
            assert intake["inventory"]["status"] == "OK", intake
            status, body = _http(runtime, "POST", root + "/pje-intake/availability", {
                "storage_content_id": content_id, "document_id": document_id,
                "available": available, "expected_revision": intake["revision"],
            })
            assert status == 200, body

        # Controle: sem exclusao, o proprietario e proposto a partir da p. 4 (DOC-PJE-002).
        before = owners()
        assert len(before) == 1 and before[0]["evidence"]["page"] == 4, before
        stale_proposal = before[0]

        # Excluir OUTRA peca nao pode apagar a proposta: o filtro e por pagina da peca.
        set_available("DOC-PJE-001", False)
        assert owners() == before

        set_available("DOC-PJE-002", False)
        assert owners() == [], "peca excluida pelo perito ainda propoe o proprietario"
        status, _ = _http(runtime, "PUT", root + "/property-record", {"expected_revision": None, "changes": [
            {"field": "owner", "value": stale_proposal["value"], "proposal_id": stale_proposal["proposal_id"]},
        ]})
        assert status == 400, "uma proposta de peca excluida foi confirmada"

        # A exclusao e reversivel: reabilitar devolve a proposta, identica.
        set_available("DOC-PJE-002", True)
        assert owners() == before
    finally:
        runtime.close()


def test_a_source_excluded_after_confirmation_is_flagged_not_erased_and_blocks_report_capture(tmp_path):
    """Confirmar e DEPOIS excluir a peca: a exclusao precisa alcancar o valor confirmado.

    O valor e uma decisao anterior do perito, entao nao e apagado nem reescrito. O
    que muda e a leitura: o campo aparece em `stale_fields`, um laudo que o capturou
    fica desatualizado com motivo proprio, e uma captura nova e recusada ate o perito
    resolver o campo. Reabilitar a peca desfaz tudo.
    """
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api
    from tests.test_document_intake_v1 import provision_private_root
    from tests.test_product_integration_oracle_v1 import _http, _fixture, TOKEN

    provision_private_root(tmp_path / "private")
    pdf = _pje_export_with_owner(tmp_path / "autos.pdf", "Proprietario do imovel: Pessoa Sintetica Excluida")
    runtime = build_pericial_local_api(tmp_path / "property.db", private_root=tmp_path / "private", token=TOKEN)
    runtime.start()
    try:
        workspace_id = _http(runtime, "POST", "/v1/workspaces", {"name": "Imovel PJe"})[1]["workspace_id"]
        root = f"/v1/workspaces/{workspace_id}"
        assert _http(runtime, "PUT", root + "/expert-profile", {"expected_revision": None, "profile": _fixture("report-snapshot-v1.json")["expert_profile"]})[0] == 200
        content_id = _http(runtime, "POST", root + "/materials", raw_body=pdf.read_bytes(), headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})[1]["content_id"]
        owner = next(p for p in _http(runtime, "GET", root + "/property-record/proposals")[1]["proposals"] if p["field"] == "owner")
        status, confirmed = _http(runtime, "PUT", root + "/property-record", {"expected_revision": None, "changes": [
            {"field": "owner", "value": owner["value"], "proposal_id": owner["proposal_id"]},
            {"field": "street", "value": "Rua Sintetica", "proposal_id": None},
        ]})
        assert status == 200 and confirmed["stale_fields"] == [], confirmed

        def set_available(available):
            intake = next(i for i in _http(runtime, "GET", root + "/pje-intake")[1]["intakes"] if i["inventory"]["storage_content_id"] == content_id)
            assert _http(runtime, "POST", root + "/pje-intake/availability", {
                "storage_content_id": content_id, "document_id": "DOC-PJE-002",
                "available": available, "expected_revision": intake["revision"],
            })[0] == 200

        set_available(False)
        status, after = _http(runtime, "GET", root + "/property-record")
        assert status == 200
        # Sinalizado, e so o campo afetado: o manual continua limpo.
        assert after["stale_fields"] == ["owner"], after
        # Nao apagado nem reescrito: o registro e a mesma revisao, byte a byte.
        assert after["record"] == confirmed["record"] and after["revision"] == confirmed["revision"]

        # Salvar outro campo nao pode "lavar" a evidencia excluida.
        status, resaved = _http(runtime, "PUT", root + "/property-record", {"expected_revision": after["revision"], "changes": [
            {"field": "street", "value": "Rua Sintetica Nova", "proposal_id": None},
        ]})
        assert status == 200 and resaved["stale_fields"] == ["owner"], resaved

        set_available(True)
        status, restored = _http(runtime, "GET", root + "/property-record")
        assert restored["stale_fields"] == [], "reabilitar a peca nao desfez a sinalizacao"
    finally:
        runtime.close()


def test_report_refuses_to_capture_and_goes_stale_on_a_property_value_whose_source_was_excluded():
    """No laudo: captura nova recusada; laudo que ja capturou fica stale com motivo proprio.

    Usa o `GetPropertyRecord` real; so o leitor de inventario e sintetico.
    """
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.application.property_record import GetPropertyRecord
    from scripts.backend_contract.application.report_foundation import _capture_property, _property_reasons
    from scripts.backend_contract.report_foundation import ReportProperty
    from tests.test_report_references_findings_v1 import _draft

    report = _draft()
    evidence = PropertyEvidence("DOC-FISICO-1", "a" * 64, "autos.pdf", 4, "Proprietario do imovel: Pessoa", "LABEL_NATIVE_TEXT_V1", None, "Pessoa")
    value = PropertyValue("owner", "Pessoa", evidence, "EXPERT-1", "2026-09-28T12:00:00+00:00")
    property_record = PropertyRecord("1.0.0", report.workspace_id, (value,))
    from scripts.backend_contract.application.models import ArtifactRevision, WorkspaceId

    revision = ArtifactRevision(
        WorkspaceId.parse(report.workspace_id), "PROPERTY_RECORD_V1", "PROPERTY-RECORD",
        "55555555-5555-4555-8555-555555555555", 2, "2026-09-28T12:00:00+00:00", "a" * 64,
        property_record_to_mapping(property_record),
    )
    stored = SimpleNamespace(execute=lambda *_a: revision)

    def inventory(available):
        return SimpleNamespace(execute=lambda _w: (SimpleNamespace(content_id="DOC-FISICO-1", pje_inventory={"documents": [
            {"document_id": "DOC-PJE-001", "page_start": 2, "page_end": 3, "available": True},
            {"document_id": "DOC-PJE-002", "page_start": 4, "page_end": 4, "available": available},
        ]}),))

    kept = GetPropertyRecord(stored, inventory(True))
    excluded = GetPropertyRecord(stored, inventory(False))
    captured = _capture_property(kept, report.workspace_id)
    assert captured == ReportProperty(property_record, 2, "a" * 64)
    snapshot = replace(report, property_record=captured)
    assert _property_reasons(snapshot, kept, report.workspace_id) == ()

    with pytest.raises(ValueError, match="excluded by the professional: owner"):
        _capture_property(excluded, report.workspace_id)
    assert _property_reasons(snapshot, excluded, report.workspace_id) == ("property evidence excluded by the professional",)

    # Sem inventario nao ha como provar que a pagina citada segue admitida: fecha.
    with pytest.raises(RepositoryIntegrityError, match="availability is unavailable"):
        GetPropertyRecord(stored).stale_fields(report.workspace_id, property_record)
