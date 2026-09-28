"""#246: presentation repeats current findings, without creating PAT authority."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts.backend_contract import delivery_renderer as dr
from scripts.backend_contract.application.report_foundation import report_upstream_digest
from scripts.backend_contract.report_foundation import ReportFindingRow, ReportProvenance
from scripts.backend_contract.technical_findings import DecisionAction
from tests.test_report_references_findings_v1 import _draft, _service
from tests.test_report_authoring_v1 import _upstream
from tests.test_report_version_v1 import _service as version_service, _superseded


def _command(technical=None, *, report=None, revision=None):
    report = report or _draft()
    technical = technical or _upstream()[1]
    service, saved = _service(report)
    return replace(service, get_technical_snapshot=SimpleNamespace(execute=lambda _w: (
        SimpleNamespace(revision=revision if revision is not None else report.source_snapshot.technical_snapshot_revision), technical,
    ))), saved


def _capture(service, workspace=None):
    return service.execute(workspace or _draft().workspace_id, expected_revision=7, action="SET_FINDINGS_TABLE", values={})[1]


def _bind(technical):
    report = _draft()
    return replace(report, source_snapshot=replace(report.source_snapshot, technical_snapshot_digest=report_upstream_digest(technical)))


def _rows(report, technical):
    return tuple(ReportFindingRow(
        finding.scope, None, finding.technical_proposition, None,
        ReportProvenance(f"P-{index}", "TECHNICAL_FINDING", finding.finding_id, report.source_snapshot.technical_snapshot_revision),
    ) for index, finding in enumerate(technical.findings))


def test_summary_captures_effective_findings_without_any_pathology() -> None:
    service, saved = _command()
    report = _capture(service)
    technical = _upstream()[1]
    assert report.source_snapshot.construction_defect_analysis_snapshot_id is None
    assert [(r.manifestation, r.finding, r.environment, r.situation) for r in report.findings_table] == [
        (f.scope, f.technical_proposition, None, None) for f in technical.findings
    ]
    assert [(r.provenance.source_kind, r.provenance.source_id, r.provenance.source_revision) for r in report.findings_table] == [
        ("TECHNICAL_FINDING", f.finding_id, report.source_snapshot.technical_snapshot_revision) for f in technical.findings
    ]
    assert saved == [report]
    blocks = dr.professional_report_blocks(report)
    table = next(b for b in blocks if b.kind == "TABLE")
    assert table.rows[0] == ("Item", "Escopo", "Achado técnico")
    assert table.rows[1] == ("1", technical.findings[0].scope, technical.findings[0].technical_proposition)


def test_proposals_without_decisions_do_not_become_summary_rows() -> None:
    technical = _upstream()[1]
    technical = replace(technical, findings=(), decisions=(), dependencies=(), question_links=(), coverage=replace(technical.coverage, effective_findings=0, complete=False))
    service, saved = _command(technical, report=_bind(technical))
    with pytest.raises(ValueError, match="effective technical findings"):
        _capture(service)
    assert saved == []


@pytest.mark.parametrize("action", [DecisionAction.MODIFY, DecisionAction.REJECT])
def test_latest_professional_decision_controls_summary_not_historical_findings(action) -> None:
    technical = _upstream()[1]
    previous = technical.decisions[0]
    decision = replace(previous, decision_id="DECISION-CURRENT", action=action, timestamp="2026-09-01T12:00:00+00:00", supersedes_decision_id=previous.decision_id,
                       modified_proposition="Constatação sintética corrigida pelo profissional." if action is DecisionAction.MODIFY else None)
    current = replace(technical.findings[0], finding_id="FINDING-CURRENT", decision_id=decision.decision_id, technical_proposition=decision.modified_proposition) if action is DecisionAction.MODIFY else None
    technical = replace(technical, decisions=(*technical.decisions, decision), findings=(*technical.findings, current) if current else technical.findings,
                        question_links=(), coverage=replace(technical.coverage, effective_findings=2 if current else 1, complete=current is not None))
    report = _capture(_command(technical, report=_bind(technical))[0])
    ids = [r.provenance.source_id for r in report.findings_table]
    assert "FINDING-001" not in ids
    assert set(ids) == ({"FINDING-002", "FINDING-CURRENT"} if current else {"FINDING-002"})
    if current:
        assert next(r.finding for r in report.findings_table if r.provenance.source_id == current.finding_id) == decision.modified_proposition


@pytest.mark.parametrize("change", ["workspace", "request_workspace", "identity", "revision", "digest", "stale"])
def test_summary_refuses_mismatched_or_stale_authority_without_saving(change) -> None:
    technical = _upstream()[1]
    workspace = None
    if change == "workspace":
        technical = replace(technical, workspace_id="22222222-2222-4222-8222-222222222222", source_snapshot=replace(technical.source_snapshot, workspace_id="22222222-2222-4222-8222-222222222222"))
    elif change == "request_workspace":
        workspace = "22222222-2222-4222-8222-222222222222"
    elif change == "identity":
        technical = replace(technical, snapshot_id="TECHNICAL-OTHER")
    elif change == "digest":
        technical = replace(technical, coverage=replace(technical.coverage, reasons=("New limitation.",)))
    elif change == "stale":
        technical = replace(technical, upstream_stale=True, upstream_stale_reasons=("inspection changed",), coverage=replace(technical.coverage, complete=False))
    service, saved = _command(technical, revision=99 if change == "revision" else None)
    with pytest.raises(ValueError, match="authority|workspace|stale"):
        _capture(service, workspace)
    assert saved == []


@pytest.mark.parametrize("field,value", [("finding", "Invented conclusion."), ("manifestation", "Invented scope."), ("environment", "Invented room."), ("situation", "ANOMALIA")])
def test_canonical_save_rejects_tampered_technical_summary_content(field, value) -> None:
    stored = _superseded()
    service, appended = version_service(stored)
    technical = _upstream()[1]
    rows = _rows(stored, technical)
    tampered = replace(stored, findings_table=(replace(rows[0], **{field: value}), *rows[1:]))
    with pytest.raises(ValueError, match="finding.*authority"):
        service.save_snapshot.execute(stored.workspace_id, tampered, 4)
    assert appended == []


def test_next_version_recaptures_summary_after_technical_revision_changes() -> None:
    from tests.test_report_foundation_v1 import upstreams
    stored = _superseded()
    records, _, _, technical, _ = upstreams()
    stored = replace(stored, findings_table=_rows(stored, technical))
    moved = (*records[:2], SimpleNamespace(**{**vars(records[2]), "revision": 5}), records[3])
    service, appended = version_service(stored, records=moved)
    service = replace(service, ids=SimpleNamespace(new_uuid=iter(f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 10)).__next__))
    _, draft, dropped = service.execute(stored.workspace_id, expected_revision=4)
    assert not draft.upstream_stale and not dropped["findings_table"]
    assert all(r.provenance.source_revision == 5 for r in draft.findings_table)
    assert len(appended) == 1
    assert all(r.provenance.source_revision == 4 for r in stored.findings_table)


def test_a_changed_upstream_makes_the_captured_report_stale_and_refuses_save() -> None:
    from scripts.backend_contract.application.report_foundation import _reconcile
    stored = _superseded()
    technical = _upstream()[1]
    stored = replace(stored, findings_table=_rows(stored, technical))
    changed = replace(stored.source_snapshot, technical_snapshot_revision=99)
    stale = _reconcile(stored, changed)
    assert stale.upstream_stale and not stale.review_decisions
    assert stale.findings_table == stored.findings_table
    service, appended = version_service(stored)
    with pytest.raises(ValueError, match="stale"):
        service.save_snapshot.execute(stored.workspace_id, stale, 4)
    assert appended == []


def test_legacy_pathology_and_technical_rows_cannot_be_mislabelled_in_one_table() -> None:
    from tests.test_report_references_findings_v1 import _rows as legacy_rows
    report = _draft()
    with pytest.raises(ValueError, match="cannot mix"):
        replace(report, findings_table=(*legacy_rows(), *_rows(report, _upstream()[1])))


@pytest.mark.skipif("not __import__('tests.test_report_references_findings_v1', fromlist=['_native'])._native()", reason="Microsoft Word 16 unavailable")
def test_word_16_renders_effective_findings_table_with_faithful_derived_pdf() -> None:
    from scripts.backend_contract.infrastructure.office_pdf import LocalOfficePdfConverter
    from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest

    from tests.test_report_foundation_v1 import bound_report

    report = replace(bound_report(), findings_table=_capture(_command()[0]).findings_table)
    template = default_report_template(report.editorial_profile)
    word = dr.render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest()).output_bytes
    pdf = dr.render_final_pdf_candidate(word_content=word, word_format="DOCX", converter=LocalOfficePdfConverter())
    dr.validate_final_artifact(pdf, "PDF")
    # Same source identities with changed printed text still fail fidelity.
    row, *rest = report.findings_table
    changed = replace(report, findings_table=(replace(row, finding="Texto sintético adulterado."), *rest))
    other = dr.render_word_candidate(template_bytes=template, report=changed, manifest=default_template_manifest()).output_bytes
    copy, _ = dr.safe_pdf_conversion_copy(other, "DOCX")
    with pytest.raises(ValueError, match="faithfully"):
        dr._validate_pdf_fidelity(copy, pdf)
