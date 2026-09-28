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


def test_next_version_drops_table_citations_when_no_effective_findings_remain() -> None:
    from tests.test_report_foundation_v1 import upstreams
    records, _, _, technical, _ = upstreams()
    stored = _superseded()
    stored = replace(stored, findings_table=_rows(stored, technical), claims=(
        replace(stored.claims[0], text=stored.claims[0].text + " [[TABELA:ACHADOS]]"), *stored.claims[1:],
    ))
    rejected = tuple(replace(d, decision_id=d.decision_id + "-REJECTED", action=DecisionAction.REJECT,
        supersedes_decision_id=d.decision_id, timestamp="2026-09-01T12:00:00+00:00") for d in technical.decisions)
    technical = replace(technical, decisions=(*technical.decisions, *rejected), question_links=(), coverage=replace(technical.coverage, effective_findings=0, complete=False))
    getter = SimpleNamespace(execute=lambda _w: (SimpleNamespace(**{**vars(records[2]), "revision": 5}), technical))
    service, appended = version_service(stored)
    service = replace(service, get_technical_snapshot=getter, save_snapshot=replace(service.save_snapshot, get_technical_snapshot=getter))
    _, draft, dropped = service.execute(stored.workspace_id, expected_revision=4)
    assert draft.findings_table is None and dropped["findings_table"]
    assert dropped["claims"] >= 1 and stored.claims[0].claim_id not in {c.claim_id for c in draft.claims}
    assert len(appended) == 1 and not draft.review_decisions


def test_legacy_pathology_and_technical_rows_cannot_be_mislabelled_in_one_table() -> None:
    from tests.test_report_references_findings_v1 import _rows as legacy_rows
    report = _draft()
    with pytest.raises(ValueError, match="cannot mix"):
        replace(report, findings_table=(*legacy_rows(), *_rows(report, _upstream()[1])))


@pytest.mark.parametrize("tamper", [None, "finding", "source_id", "source_revision"])
def test_backup_validates_captured_technical_rows_against_the_bound_authority(tamper) -> None:
    import json
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.infrastructure.productization import _revision_from_mapping, _verify_dependency_closure
    from tests.test_product_integration_oracle_v1 import _longitudinal_backup, _digest

    backup = json.loads(_longitudinal_backup()[0])
    report = next(r for r in backup["artifact_revisions"] if r["artifact_kind"] == "REPORT_SNAPSHOT_V1")
    technical = next(r["payload"] for r in backup["artifact_revisions"] if r["artifact_kind"] == "TECHNICAL_SNAPSHOT_V1")
    finding = technical["findings"][0]
    row = {"manifestation": finding["scope"], "environment": None, "finding": finding["technical_proposition"], "situation": None,
           "provenance": {"provenance_id": "P-SUMMARY", "source_kind": "TECHNICAL_FINDING", "source_id": finding["finding_id"], "source_revision": 1}}
    if tamper == "finding":
        row["finding"] = "Invented conclusion."
    elif tamper:
        row["provenance"][tamper] = "FINDING-OTHER" if tamper == "source_id" else 99
    report["payload"]["findings_table"] = [row]
    report["checksum_sha256"] = _digest(report["payload"])
    for record in backup["artifact_revisions"]:
        if record["artifact_kind"] == "DELIVERY_SNAPSHOT_V1":
            record["payload"]["binding"]["report_digest"] = report["checksum_sha256"]
            record["checksum_sha256"] = _digest(record["payload"])
    records = tuple(_revision_from_mapping(r, backup["workspace"]["workspace_id"]) for r in backup["artifact_revisions"])
    if tamper:
        with pytest.raises(RepositoryIntegrityError, match="finding.*authority"):
            _verify_dependency_closure(records)
    else:
        _verify_dependency_closure(records)


@pytest.mark.parametrize("tamper", [None, "missing_binding", "source_id", "source_revision"])
def test_backup_preserves_valid_legacy_rows_but_rejects_invented_pathology_provenance(tamper) -> None:
    import json
    from pathlib import Path
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.construction_defect_analysis import construction_defect_analysis_from_mapping, construction_defect_analysis_to_mapping
    from scripts.backend_contract.infrastructure.productization import _revision_from_mapping, _verify_dependency_closure
    from scripts.planejamento_pericial.construction_defect_analysis_adapter import ConstructionDefectAnalysisAdapter
    from tests.test_construction_defect_product_integration_v1 import _canonical_inputs, _application_context
    from tests.test_product_integration_oracle_v1 import _longitudinal_backup, _digest, _revision

    backup = json.loads(_longitudinal_backup()[0])
    revisions = backup["artifact_revisions"]
    report = next(r for r in revisions if r["artifact_kind"] == "REPORT_SNAPSHOT_V1")
    pathology = json.loads((Path(__file__).parent / "fixtures/construction-defect-analysis-v1.json").read_text(encoding="utf-8"))
    process_case, case, planning, inspection = _canonical_inputs()
    proposal = ConstructionDefectAnalysisAdapter().execute(
        process_case=process_case, case_analysis=case, planning=planning, inspection=inspection,
        observation_contexts=(_application_context(),),
    )
    pathology = construction_defect_analysis_to_mapping(replace(construction_defect_analysis_from_mapping(pathology),
        observation_contexts=proposal.observation_contexts, identity_links=proposal.identity_links,
        analysis_final=proposal.analysis_final, gate=proposal.gate,
    ))
    process = process_case.as_dict()
    revisions.append(_revision("PROCESS_CASE", "PROCESS_CASE", process, 1, 90))
    binding = pathology["source_snapshot"]
    binding.update(process_case_revision=1, process_case_digest=_digest(process))
    for kind, prefix, identity in (
        ("CASE_ANALYSIS_SNAPSHOT_V1", "case_analysis", "snapshot_id"),
        ("PERICIAL_PLANNING_SNAPSHOT_V1", "planning", "snapshot_id"),
        ("INSPECTION_SESSION_V1", "inspection", "session_id"),
    ):
        source = max((r for r in revisions if r["artifact_kind"] == kind), key=lambda r: r["revision"])
        identity_key = "inspection_session_id" if prefix == "inspection" else prefix + "_snapshot_id"
        binding.update({identity_key: source["payload"][identity], prefix + "_revision": source["revision"], prefix + "_digest": source["checksum_sha256"]})
    pat_id = construction_defect_analysis_from_mapping(pathology).effective_pat_ids[0]
    revisions.append(_revision("CONSTRUCTION_DEFECT_ANALYSIS_V1", "CONSTRUCTION-DEFECT-ANALYSIS", pathology, 1, 91))
    if tamper != "missing_binding":
        report["payload"]["source_snapshot"].update(
            construction_defect_analysis_snapshot_id=pathology["snapshot_id"],
            construction_defect_analysis_revision=1, construction_defect_analysis_digest=_digest(pathology),
        )
    report["payload"]["findings_table"] = [{
        "manifestation": "Manifestation from a synthetic legacy report.", "environment": None,
        "finding": "Captured legacy wording.", "situation": None,
        "provenance": {"provenance_id": "P-LEGACY", "source_kind": "PATHOLOGY",
            "source_id": "PAT-INVENTED" if tamper == "source_id" else pat_id,
            "source_revision": 99 if tamper == "source_revision" else 1},
    }]
    report["checksum_sha256"] = _digest(report["payload"])
    for record in revisions:
        if record["artifact_kind"] == "DELIVERY_SNAPSHOT_V1":
            record["payload"]["binding"]["report_digest"] = report["checksum_sha256"]
            record["checksum_sha256"] = _digest(record["payload"])
    records = tuple(_revision_from_mapping(r, backup["workspace"]["workspace_id"]) for r in revisions)
    if tamper:
        with pytest.raises(RepositoryIntegrityError, match="pathology authority"):
            _verify_dependency_closure(records)
    else:
        _verify_dependency_closure(records)


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
