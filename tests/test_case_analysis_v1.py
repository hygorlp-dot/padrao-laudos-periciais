import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import jsonschema
import pytest

from scripts.backend_contract.case_analysis import (
    AnalysisStatus,
    CaseAnalysisCoverage,
    CoverageStatus,
    case_analysis_from_mapping,
    case_analysis_to_mapping,
    query_analysis,
)
from scripts.backend_contract.application.case_analysis import (
    GetCaseAnalysis,
    SaveCaseAnalysis,
    validated_case_analysis_from_mapping,
)
from scripts.backend_contract.application.models import ArtifactRevision, WorkspaceId
from scripts.backend_contract.application.ports import RepositoryIntegrityError


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "tests/fixtures/case-analysis-snapshot-v1.json").read_text(encoding="utf-8"))


def test_synthetic_snapshot_is_structurally_and_semantically_canonical():
    raw = fixture()
    schema = json.loads((ROOT / "schemas/case-analysis-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validated_case_analysis_from_mapping(raw)

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


def test_stale_state_and_occurrence_identity_survive_canonical_roundtrip():
    snapshot = case_analysis_from_mapping(fixture())
    changed = snapshot.reconcile_sources(
        {
            **{document.document_id: document.source_sha256 for document in snapshot.documents},
            "DOC-002": "f" * 64,
        }
    )

    reopened = case_analysis_from_mapping(case_analysis_to_mapping(changed))

    assert reopened.stale_document_ids == ("DOC-002",)
    assert reopened.claims[0].stale is False
    assert reopened.counterarguments[0].stale is True
    assert reopened.claims[0].provenance[0].occurrence_id == "OCC-CLAIM-001"


def test_participant_references_are_owned_by_canonical_jdm_context():
    raw = fixture()
    raw["participant_refs"].append("PART-SMUGGLED")

    with pytest.raises(ValueError, match="canonical JDM"):
        case_analysis_from_mapping(raw)


def test_provenance_cannot_false_bind_a_document_sha_or_occurrence():
    wrong_sha = fixture()
    wrong_sha["claims"][0]["provenance"][0]["source_document_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="indexed source identity"):
        case_analysis_from_mapping(wrong_sha)

    conflicting_occurrence = fixture()
    conflicting_occurrence["claims"][1]["provenance"][0]["occurrence_id"] = "OCC-CLAIM-001"
    with pytest.raises(ValueError, match="conflicting source locators"):
        case_analysis_from_mapping(conflicting_occurrence)


def test_reconciliation_clears_persisted_stale_state_when_source_is_restored():
    snapshot = case_analysis_from_mapping(fixture())
    source_hashes = {document.document_id: document.source_sha256 for document in snapshot.documents}
    changed = snapshot.reconcile_sources({**source_hashes, "DOC-002": "f" * 64})
    reopened = case_analysis_from_mapping(case_analysis_to_mapping(changed))

    restored = reopened.reconcile_sources(source_hashes)

    assert restored.stale_document_ids == ()
    assert all(not item.stale for item in restored.material_items)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (lambda raw: raw["counterarguments"][0]["target_claim_ids"].append("CLAIM-MISSING"), "counterargument targets"),
        (lambda raw: raw["decisions"][0]["addressed_claim_ids"].append("CLAIM-MISSING"), "decision targets"),
        (lambda raw: raw["conflicts"][0].update(statement_a_id="ITEM-MISSING"), "conflict statements"),
        (lambda raw: raw["human_reviews"][0].update(target_item_id="ITEM-MISSING"), "human review target"),
        (lambda raw: raw["coverage"].update(source_revision=99), "coverage"),
        (lambda raw: raw["coverage"].update(documents_total=4, documents_unavailable=2), "coverage"),
        (lambda raw: raw["coverage"].update(status="COMPLETE", documents_analyzed=3, documents_unavailable=0), "availability"),
        (lambda raw: raw["claims"][0].update(text=""), "material item"),
    ),
)
def test_semantic_graph_rejects_dangling_or_dishonest_state(mutate, message):
    raw = fixture()
    mutate(raw)
    with pytest.raises(ValueError, match=message):
        case_analysis_from_mapping(raw)


def test_runtime_schema_rejects_nonhex_sha_and_workspace_promoted_jdm():
    raw = fixture()
    raw["documents"][0]["source_sha256"] = "z" * 64
    for collection in ("claims", "conflicts"):
        for item in raw[collection]:
            for source in item["provenance"]:
                if source["source_document_id"] == "DOC-001":
                    source["source_document_sha256"] = "z" * 64
    with pytest.raises(ValueError, match="invalid Case Analysis payload"):
        validated_case_analysis_from_mapping(raw)

    promoted = fixture()
    promoted["workspace_id"] = "22222222-2222-4222-8222-222222222222"
    for collection in ("claims", "counterarguments", "decisions", "pericial_objects", "questions", "events", "technical_document_references", "gaps", "conflicts"):
        for item in promoted[collection]:
            for source in item["provenance"]:
                source["workspace_id"] = promoted["workspace_id"]
    with pytest.raises(ValueError, match="JDM context workspace"):
        case_analysis_from_mapping(promoted)


def test_duplicate_material_identity_is_rejected():
    raw = fixture()
    raw["claims"][1]["item_id"] = raw["claims"][0]["item_id"]
    with pytest.raises(ValueError, match="identities must be unique"):
        case_analysis_from_mapping(raw)


def _authoritative_documents(snapshot, *, changed_document_id=None):
    return tuple(
        SimpleNamespace(
            content_id=document.storage_content_id,
            checksum_sha256=("f" * 64 if document.document_id == changed_document_id else document.source_sha256),
        )
        for document in snapshot.documents
    )


def test_save_uses_atomic_repository_cas_and_authoritative_inventory():
    snapshot = case_analysis_from_mapping(fixture())
    calls = []
    revisions = SimpleNamespace(append_if_latest=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(revision=1))
    clock = SimpleNamespace(now=lambda: datetime(2026, 8, 30, tzinfo=UTC))
    ids = SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999"))
    documents = SimpleNamespace(execute=lambda _workspace: _authoritative_documents(snapshot))

    result = SaveCaseAnalysis(revisions, clock, ids, documents).execute(
        WorkspaceId.parse(snapshot.workspace_id), snapshot, None
    )

    assert result.revision == 1
    assert calls[0]["expected_revision"] is None
    assert calls[0]["payload"] == case_analysis_to_mapping(snapshot)

    mismatched = SimpleNamespace(
        execute=lambda _workspace: _authoritative_documents(snapshot, changed_document_id="DOC-002")
    )
    with pytest.raises(RepositoryIntegrityError, match="source inventory mismatch"):
        SaveCaseAnalysis(revisions, clock, ids, mismatched).execute(
            WorkspaceId.parse(snapshot.workspace_id), snapshot, None
        )

    extra = SimpleNamespace(
        execute=lambda _workspace: (
            *_authoritative_documents(snapshot),
            SimpleNamespace(content_id="10000000-0000-4000-8000-000000000004", checksum_sha256="e" * 64),
        )
    )
    with pytest.raises(RepositoryIntegrityError, match="source inventory mismatch"):
        SaveCaseAnalysis(revisions, clock, ids, extra).execute(
            WorkspaceId.parse(snapshot.workspace_id), snapshot, None
        )


def test_get_reconciles_current_snapshot_against_live_inventory():
    snapshot = case_analysis_from_mapping(fixture())
    record = ArtifactRevision(
        workspace_id=WorkspaceId.parse(snapshot.workspace_id),
        artifact_kind="CASE_ANALYSIS_SNAPSHOT_V1",
        artifact_id="CASE-ANALYSIS",
        revision_id="99999999-9999-4999-8999-999999999999",
        revision=1,
        created_at="2026-08-30T12:00:00+00:00",
        checksum_sha256="0" * 64,
        payload=case_analysis_to_mapping(snapshot),
    )
    latest = SimpleNamespace(execute=lambda *_args: record)
    documents = SimpleNamespace(execute=lambda _workspace: _authoritative_documents(snapshot, changed_document_id="DOC-002"))

    _, reopened = GetCaseAnalysis(latest, documents).execute(WorkspaceId.parse(snapshot.workspace_id))

    assert reopened.stale_document_ids == ("DOC-002",)
    assert reopened.claims[0].stale is False
    assert reopened.counterarguments[0].stale is True


def test_get_marks_live_inventory_additions_as_unindexed_and_stale():
    snapshot = case_analysis_from_mapping(fixture())
    record = ArtifactRevision(
        workspace_id=WorkspaceId.parse(snapshot.workspace_id), artifact_kind="CASE_ANALYSIS_SNAPSHOT_V1",
        artifact_id="CASE-ANALYSIS", revision_id="99999999-9999-4999-8999-999999999999",
        revision=1, created_at="2026-08-30T12:00:00+00:00", checksum_sha256="0" * 64,
        payload=case_analysis_to_mapping(snapshot),
    )
    latest = SimpleNamespace(execute=lambda *_args: record)
    documents = SimpleNamespace(
        execute=lambda _workspace: (
            *_authoritative_documents(snapshot),
            SimpleNamespace(content_id="10000000-0000-4000-8000-000000000004", checksum_sha256="e" * 64),
        )
    )

    _, reopened = GetCaseAnalysis(latest, documents).execute(WorkspaceId.parse(snapshot.workspace_id))

    assert reopened.source_inventory_stale is True
    assert reopened.unindexed_source_count == 1


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
    assert path["post"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SaveCaseAnalysisRequest"
    }
    assert path["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CaseAnalysisEnvelope"
    }
