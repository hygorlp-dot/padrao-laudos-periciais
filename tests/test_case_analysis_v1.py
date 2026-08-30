import copy
import json
from pathlib import Path

import jsonschema
import pytest

from scripts.backend_contract.case_analysis import (
    AnalysisStatus,
    CaseAnalysisCoverage,
    CoverageStatus,
    case_analysis_from_mapping,
    query_analysis,
)


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8"))


def test_synthetic_snapshot_is_structurally_and_semantically_canonical():
    raw = fixture()
    schema = json.loads((ROOT / "schemas/case-analysis-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(raw)

    snapshot = case_analysis_from_mapping(raw)

    assert snapshot.workspace_id == "11111111-1111-4111-8111-111111111111"
    assert snapshot.coverage == CaseAnalysisCoverage(
        status=CoverageStatus.PARTIAL,
        documents_total=3,
        documents_analyzed=2,
        documents_unavailable=1,
        documents_failed=0,
        source_revision=4,
    )
    assert snapshot.pericial_objects[0].text == "Delimitar a manifestação descrita nos autos sintéticos."
    assert snapshot.conflicts[0].analysis_status is AnalysisStatus.PROPOSED_CONFLICT


def test_every_material_item_has_exact_source_grounding():
    raw = fixture()
    for collection in (
        "claims",
        "counterarguments",
        "decisions",
        "pericial_objects",
        "questions",
        "events",
        "technical_document_references",
        "gaps",
        "conflicts",
    ):
        assert raw[collection]
        assert all(item["provenance"] for item in raw[collection])

    broken = copy.deepcopy(raw)
    broken["claims"][0]["provenance"] = []
    with pytest.raises(ValueError, match="provenance"):
        case_analysis_from_mapping(broken)


def test_argument_and_decision_relations_are_explicit_and_many_to_many():
    snapshot = case_analysis_from_mapping(fixture())

    assert snapshot.counterarguments[0].target_claim_ids == ("CLAIM-001", "CLAIM-002")
    assert snapshot.decisions[0].addressed_claim_ids == ("CLAIM-001",)
    assert snapshot.decisions[0].addressed_counterargument_ids == ("COUNTER-001",)


def test_access_or_foreign_reference_never_creates_participant_or_case_fact():
    snapshot = case_analysis_from_mapping(fixture())

    assert snapshot.participant_refs == ("PART-CLAIMANT", "PART-DEFENDANT")
    assert snapshot.technical_document_references[0].external_reference is True
    assert "PART-FOREIGN" not in snapshot.participant_refs


def test_query_uses_deterministic_small_index_bucket_without_full_rescan():
    snapshot = case_analysis_from_mapping(fixture())

    result = query_analysis(
        snapshot,
        participant_ref="PART-DEFENDANT",
        technical_subject="levantamento topográfico",
    )

    assert result.document_ids == ("DOC-002",)
    assert result.documents_considered == 1
    assert result.documents_total == 3
    assert result.full_case_rescan is False


def test_unchanged_hash_reuses_analysis_and_changed_hash_stales_only_dependents():
    snapshot = case_analysis_from_mapping(fixture())
    same = snapshot.reconcile_sources({document.document_id: document.source_sha256 for document in snapshot.documents})
    assert same is snapshot

    changed = snapshot.reconcile_sources({**{document.document_id: document.source_sha256 for document in snapshot.documents}, "DOC-002": "f" * 64})
    assert changed.stale_document_ids == ("DOC-002",)
    assert changed.claims[0].stale is False
    assert changed.counterarguments[0].stale is True


def test_human_review_preserves_original_extraction_and_never_answers_question():
    snapshot = case_analysis_from_mapping(fixture())
    review = snapshot.human_reviews[0]

    assert review.original_extraction == "fundação inadequada"
    assert review.corrected_value == "alegação sobre fundação"
    assert review.reason == "Correção sintética de natureza da afirmação."
    assert snapshot.questions[0].answer is None


def test_coverage_counts_and_source_revision_fail_closed():
    with pytest.raises(ValueError):
        CaseAnalysisCoverage(CoverageStatus.COMPLETE, 3, 2, 1, 0, 4)
    with pytest.raises(ValueError):
        CaseAnalysisCoverage(CoverageStatus.PARTIAL, 3, 3, 1, 0, 4)


def test_unknown_fields_cannot_smuggle_pericial_conclusion():
    raw = fixture()
    raw["pericial_conclusion"] = "não permitido"
    with pytest.raises(ValueError, match="exact fields"):
        case_analysis_from_mapping(raw)


def test_openapi_exposes_only_minimum_case_analysis_operations_and_canonical_schema():
    contract = json.loads((ROOT / "contracts/openapi-v1.json").read_text(encoding="utf-8"))
    path = contract["paths"]["/v1/workspaces/{workspace_id}/case-analysis"]

    assert set(path) == {"get", "post"}
    assert contract["components"]["schemas"]["CaseAnalysisSnapshot"] == {
        "$ref": "../schemas/case-analysis-snapshot-v1.schema.json"
    }
    assert contract["info"]["x-case-analysis-semantic-boundary"] == (
        "scripts.backend_contract.case_analysis.case_analysis_from_mapping"
    )
