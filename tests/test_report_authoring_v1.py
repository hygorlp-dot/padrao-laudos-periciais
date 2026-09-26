"""Professional report authoring (Issue #239, Phase B).

The report is presented as a professional document derived from canonical
authority; answers are composed from the question and the effective finding
without typed internal identities; the canonical audit trail stays available
apart from the document.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.backend_contract import delivery_renderer
from scripts.backend_contract.application.report_foundation import (
    AmendReportDraft,
    ExportReportAuditTrail,
    ListReportSources,
    _draft_coverage,
    report_upstream_digest,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.report_foundation import (
    ReportState,
    report_snapshot_from_mapping,
    report_snapshot_to_mapping,
)
from scripts.backend_contract.technical_findings import technical_snapshot_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _upstream():
    case = case_analysis_from_mapping(_fixture("case-analysis-snapshot-v1.json"))
    technical = technical_snapshot_from_mapping(_fixture("technical-snapshot-v1.json"))
    inspection = inspection_session_from_mapping(_fixture("inspection-session-v1.json"))
    return case, technical, inspection


def _draft_bound_to(case, technical):
    """The fixture report as a draft whose binding names the real upstream digests."""
    report = report_snapshot_from_mapping(_fixture("report-snapshot-v1.json"))
    source = replace(
        report.source_snapshot,
        case_analysis_digest=report_upstream_digest(case),
        technical_snapshot_digest=report_upstream_digest(technical),
    )
    return replace(report, source_snapshot=source, answers=(), review_decisions=(), state=ReportState.DRAFT, coverage=_draft_coverage(report, answers=()))


def _with_answers(report, answers):
    return replace(report, answers=answers, coverage=_draft_coverage(report, answers=answers))


class _Record(SimpleNamespace):
    pass


def _amend(report, case, technical, *, case_revision=None, technical_revision=None):
    saved = []
    service = AmendReportDraft(
        get_snapshot=SimpleNamespace(execute=lambda _workspace: (_Record(revision=7), report)),
        save_snapshot=SimpleNamespace(execute=lambda _workspace, snapshot, expected: saved.append((snapshot, expected)) or _Record(revision=8)),
        ids=SimpleNamespace(new_uuid=lambda: "00000000-0000-4000-8000-000000000123"),
        get_case_analysis=SimpleNamespace(execute=lambda _workspace: (_Record(revision=case_revision or report.source_snapshot.case_analysis_revision), case)),
        get_technical_snapshot=SimpleNamespace(execute=lambda _workspace: (_Record(revision=technical_revision or report.source_snapshot.technical_snapshot_revision), technical)),
    )
    return service, saved


def test_legacy_snapshots_keep_their_exact_mapping() -> None:
    """FUTURE_REGRESSION_GUARD: an answer without question text serializes as before."""
    mapping = _fixture("report-snapshot-v1.json")
    assert report_snapshot_to_mapping(report_snapshot_from_mapping(mapping)) == mapping
    explicit_null = json.loads(json.dumps(mapping))
    explicit_null["answers"][0]["question_text"] = None
    with pytest.raises(ValueError):
        report_snapshot_from_mapping(explicit_null)


def test_an_answer_is_derived_from_the_question_and_the_effective_finding() -> None:
    case, technical, _ = _upstream()
    report = _draft_bound_to(case, technical)
    service, saved = _amend(report, case, technical)

    _, amended = service.execute("11111111-1111-4111-8111-111111111111", expected_revision=7, action="ANSWER_QUESTION",
                                 values={"question_id": "QUESTION-001", "finding_id": "FINDING-001", "text": "  A medição diverge.  "})

    answer = amended.answers[-1]
    finding = next(item for item in technical.findings if item.finding_id == "FINDING-001")
    proposal = next(item for item in technical.finding_proposals if item.proposal_id == finding.proposal_id)
    assert answer.text == "A medição diverge."
    assert answer.decision_id == finding.decision_id
    assert set(answer.evidence_ids) == set(proposal.supporting_evidence_ids) | set(proposal.contrary_evidence_ids)
    assert answer.method_ids == tuple(proposal.method_application_ids)
    assert answer.question_text == next(item.text for item in case.questions if item.item_id == "QUESTION-001")
    assert answer.section_id == next(item.section_id for item in report.sections if item.kind == "ANSWERS_TO_QUESTIONS")
    assert set(answer.claim_ids) == {"CLAIM-007", "CLAIM-008"}
    assert saved and saved[0][1] == 7


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"question_id": "QUESTION-001", "finding_id": "FINDING-002", "text": "x"}, "linked to the question"),
        ({"question_id": "QUESTION-999", "finding_id": "FINDING-001", "text": "x"}, "linked to the question"),
        ({"question_id": "QUESTION-001", "finding_id": "FINDING-001", "text": " "}, "invalid"),
        ({"question_id": "QUESTION-001", "finding_id": "FINDING-001"}, "invalid"),
    ],
)
def test_an_answer_the_upstream_chain_does_not_support_is_refused(values, message) -> None:
    case, technical, _ = _upstream()
    service, saved = _amend(_draft_bound_to(case, technical), case, technical)
    with pytest.raises(ValueError, match=message):
        service.execute("11111111-1111-4111-8111-111111111111", expected_revision=7, action="ANSWER_QUESTION", values=values)
    assert saved == []


def test_an_answer_needs_the_finding_cited_in_the_report_first() -> None:
    case, technical, _ = _upstream()
    report = _draft_bound_to(case, technical)
    claims = tuple(item for item in report.claims if item.claim_id not in {"CLAIM-007", "CLAIM-008"})
    uncited = replace(report, claims=claims, coverage=_draft_coverage(report, claims=claims))
    service, _ = _amend(uncited, case, technical)
    with pytest.raises(ValueError, match="cited in the report"):
        service.execute("11111111-1111-4111-8111-111111111111", expected_revision=7, action="ANSWER_QUESTION",
                        values={"question_id": "QUESTION-001", "finding_id": "FINDING-001", "text": "Resposta."})


def test_a_stale_upstream_cannot_derive_an_answer() -> None:
    case, technical, _ = _upstream()
    report = _draft_bound_to(case, technical)
    service, _ = _amend(report, case, technical, technical_revision=report.source_snapshot.technical_snapshot_revision + 1)
    with pytest.raises(ValueError, match="stale"):
        service.execute("11111111-1111-4111-8111-111111111111", expected_revision=7, action="ANSWER_QUESTION",
                        values={"question_id": "QUESTION-001", "finding_id": "FINDING-001", "text": "Resposta."})


def test_claim_text_edits_keep_authority_and_removal_protects_answers() -> None:
    case, technical, _ = _upstream()
    report = _with_answers(_draft_bound_to(case, technical), report_snapshot_from_mapping(_fixture("report-snapshot-v1.json")).answers)
    service, _ = _amend(report, case, technical)
    _, edited = service.execute("w", expected_revision=7, action="UPDATE_CLAIM_TEXT", values={"claim_id": "CLAIM-001", "text": "Texto revisado."})
    before = next(item for item in report.claims if item.claim_id == "CLAIM-001")
    after = next(item for item in edited.claims if item.claim_id == "CLAIM-001")
    assert after.text == "Texto revisado." and after.authority is before.authority and after.provenance == before.provenance
    with pytest.raises(ValueError, match="supports an answer"):
        service.execute("w", expected_revision=7, action="REMOVE_CLAIM", values={"claim_id": "CLAIM-007"})
    _, removed = service.execute("w", expected_revision=7, action="REMOVE_CLAIM", values={"claim_id": "CLAIM-001"})
    assert "CLAIM-001" not in {item.claim_id for item in removed.claims}


def test_the_source_catalog_labels_every_citable_source_by_content() -> None:
    case, technical, inspection = _upstream()
    catalog = ListReportSources(
        get_case_analysis=SimpleNamespace(execute=lambda _w: (_Record(revision=3), case)),
        get_inspection_session=SimpleNamespace(execute=lambda _w: (_Record(revision=2), inspection)),
        get_technical_snapshot=SimpleNamespace(execute=lambda _w: (_Record(revision=4), technical)),
    ).execute("w")
    kinds = {item["kind"] for item in catalog["sources"]}
    assert {"ALLEGATION", "CASE_DOCUMENT", "FIELD_OBSERVATION", "MEASUREMENT", "TECHNICAL_FINDING"} <= kinds
    assert all(item["label"].strip() for item in catalog["sources"])
    question = next(item for item in catalog["questions"] if item["question_id"] == "QUESTION-001")
    assert question["text"] == next(item.text for item in case.questions if item.item_id == "QUESTION-001")
    assert [item["finding_id"] for item in question["findings"]] == ["FINDING-001"]
    assert set(catalog["context_sources"]) == {"PROCESS_NUMBER", "COURT", "PARTIES", "ADDRESSES", "CLAIM_AND_GROUNDS", "REQUESTS"}


def test_the_professional_presentation_has_no_internal_identity() -> None:
    report = report_snapshot_from_mapping(_fixture("report-snapshot-v1.json"))
    blocks = delivery_renderer.professional_report_blocks(report)
    text = "\n".join(block.visible_text for block in blocks)

    assert blocks[0].kind == "HEADING_1" and blocks[0].text == "1. IDENTIFICAÇÃO"
    headings = [block.text for block in blocks if block.kind == "HEADING_1"]
    assert [heading.split(".")[0] for heading in headings] == [str(index) for index in range(1, len(headings) + 1)]
    for internal in ("CLAIM-", "ANSWER-", "FINDING-", "EVIDENCE-", "DECISION-", "REPORT_SNAPSHOT_SHA256", "PROVENIÊNCIA", "TECHNICALLY_FOUND"):
        assert internal not in text
    assert "Quesito 1:" in text and "Resposta: " + report.answers[0].text in text


def test_empty_sections_are_omitted_and_line_breaks_become_paragraphs() -> None:
    report = report_snapshot_from_mapping(_fixture("report-snapshot-v1.json"))
    first = report.claims[0]
    report = replace(report, claims=(replace(first, text="Primeiro parágrafo.\nSegundo parágrafo."), *report.claims[1:]))
    blocks = delivery_renderer.professional_report_blocks(report)
    paragraphs = [block.text for block in blocks if block.kind == "PARAGRAPH"]
    assert "Primeiro parágrafo." in paragraphs and "Segundo parágrafo." in paragraphs
    presented_titles = {block.text.split(". ", 1)[1] for block in blocks if block.kind == "HEADING_1"}
    with_content = {section.title.upper() for section in report.sections if any(claim.section_id == section.section_id for claim in report.claims) or any(answer.section_id == section.section_id for answer in report.answers)}
    assert presented_titles == with_content


def _styles(style_id: str | None) -> bytes:
    style = (
        f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="heading 1"/></w:style>' if style_id else ""
    )
    return (
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        f"{style}</w:styles>"
    ).encode("utf-8")


@pytest.mark.parametrize("style_id", ["Ttulo1", "Heading1", None])
def test_headings_use_the_template_heading_style_or_direct_formatting(style_id) -> None:
    assert delivery_renderer._heading_style_id(_styles(style_id)) == style_id
    report = report_snapshot_from_mapping(_fixture("report-snapshot-v1.json"))
    markup = delivery_renderer._canonical_content_markup(report, b"w:", style_id).decode("utf-8")
    heading = markup.split("</w:p>", 1)[0]
    assert 'w:outlineLvl w:val="0"' in heading
    if style_id:
        assert f'w:pStyle w:val="{style_id}"' in heading and "<w:b/>" not in heading
    else:
        assert "w:pStyle" not in heading and "<w:b/>" in heading


def test_the_audit_trail_is_exported_apart_from_the_document() -> None:
    report = report_snapshot_from_mapping(_fixture("report-snapshot-v1.json"))
    trail = ExportReportAuditTrail(SimpleNamespace(execute=lambda _w: (_Record(revision=5), report))).execute("w")
    assert trail["report_id"] == report.report_id and trail["revision"] == 5
    assert trail["lines"][0].startswith("LAUDO CANÔNICO | ")
    assert any(line.startswith("REPORT_SNAPSHOT_SHA256 | ") for line in trail["lines"])
    assert any("CLAIM-001" in line for line in trail["lines"])


def test_the_editorial_profile_is_set_on_a_draft_within_validated_ranges() -> None:
    from scripts.backend_contract.report_foundation import editorial_profile_to_mapping

    case, technical, _ = _upstream()
    report = _draft_bound_to(case, technical)
    service, saved = _amend(report, case, technical)
    custom = {**editorial_profile_to_mapping(report.editorial_profile), "profile_id": "CUSTOM", "font_family": "Calibri", "body_font_pt": 12}
    _, amended = service.execute("w", expected_revision=7, action="SET_EDITORIAL_PROFILE", values={"editorial_profile": custom})
    assert (amended.editorial_profile.font_family, amended.editorial_profile.body_font_pt) == ("Calibri", 12)
    with pytest.raises(ValueError):
        service.execute("w", expected_revision=7, action="SET_EDITORIAL_PROFILE", values={"editorial_profile": {**custom, "body_font_pt": 30}})
    with pytest.raises(ValueError):
        service.execute("w", expected_revision=7, action="SET_EDITORIAL_PROFILE", values={"profile": custom})
