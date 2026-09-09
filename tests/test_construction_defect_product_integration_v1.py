from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import UTC, datetime
import base64
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from types import MappingProxyType
from uuid import UUID

from jsonschema import Draft202012Validator
import pytest

from scripts.backend_contract.construction_defect_analysis import (
    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
    ConstructionDefectAnalysisSnapshot,
    ConstructionDefectSourceSnapshot,
    ObservationContext,
    ObservationOutcome,
    PathologyReview,
    PathologyReviewAction,
    construction_defect_analysis_from_mapping,
    construction_defect_analysis_to_mapping,
    freeze_json_payload,
)
from scripts.backend_contract.application.construction_defect_analysis import (
    GetConstructionDefectAnalysis,
    ReviewPathology,
    SaveConstructionDefectAnalysis,
    StartConstructionDefectAnalysis,
    validated_construction_defect_analysis_from_mapping,
)
from scripts.backend_contract.application.ports import RepositoryConflict
from scripts.backend_contract.application.models import (
    ProcessCaseData,
    WorkspaceId,
    thaw_payload,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.pericial_planning import pericial_planning_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping
from scripts.backend_contract.infrastructure.productization import (
    PRODUCT_RELEASE_VERSION,
    RecoveryStaging,
    RestoreWorkspaceBackup,
    VerifyWorkspaceBackup,
)
from scripts.planejamento_pericial.construction_defect_analysis_adapter import (
    ConstructionDefectAnalysisAdapter,
)


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
FIXTURES = Path("tests/fixtures")


def _json_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _canonical_inputs():
    inspection_payload = _adjusted_inspection_payload()

    return (
        ProcessCaseData(
            numero_processo="0000001-00.2026.4.00.0001",
            ramo_justica="JUSTICA_FEDERAL",
            tribunal="TRF5",
            vara="Vara sintetica",
            municipio_sede="Recife",
            subsecao_judiciaria="Recife",
            comarca_municipio="Recife",
            uf="PE",
            parte_requerente="Parte requerente sintetica",
            parte_requerida="Parte requerida sintetica",
        ),
        case_analysis_from_mapping(_json_fixture("case-analysis-snapshot-v1.json")),
        pericial_planning_from_mapping(
            _json_fixture("pericial-planning-snapshot-v1.json")
        ),
        inspection_session_from_mapping(inspection_payload),
    )


def _adjusted_inspection_payload() -> dict[str, object]:
    inspection_payload = _json_fixture("inspection-session-v1.json")
    inspection_payload["items"][0]["measurement_ids"] = ["MEASUREMENT-001"]
    inspection_payload["items"][0]["photo_ids"] = ["PHOTO-001"]
    inspection_payload["items"][1]["measurement_ids"] = []
    inspection_payload["items"][2]["photo_ids"] = []
    inspection_payload["measurements"][0]["inspection_item_id"] = (
        "INSPECTION-ITEM-001"
    )
    inspection_payload["photos"][0]["inspection_item_id"] = "INSPECTION-ITEM-001"
    inspection_payload["evidence_candidates"][0].update(
        inspection_item_id="INSPECTION-ITEM-001",
        source_record_ids=["OBS-001", "MEASUREMENT-001", "PHOTO-001"],
    )
    return inspection_payload


class _FixedClock:
    def now(self):
        return datetime(2026, 9, 8, 14, 0, tzinfo=UTC)


class _SequenceIds:
    def __init__(self):
        self.value = 100

    def new_uuid(self):
        self.value += 1
        return UUID(int=self.value)


def _record(kind: str, artifact_id: str, revision: int, payload: object):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    return SimpleNamespace(
        artifact_kind=kind,
        artifact_id=artifact_id,
        revision=revision,
        revision_id=str(UUID(int=revision)),
        created_at="2026-09-08T12:00:00+00:00",
        checksum_sha256=hashlib.sha256(encoded).hexdigest(),
        payload=freeze_json_payload(deepcopy(payload)),
    )


class _PairGetter:
    def __init__(self, record, value):
        self.record = record
        self.value = value

    def execute(self, _workspace_id):
        return self.record, self.value


class _ProcessGetter:
    def __init__(self, record, value):
        self.record = record
        self.value = value

    def execute(self, workspace_id):
        return SimpleNamespace(
            workspace_id=workspace_id,
            revision=self.record.revision,
            updated_at=self.record.created_at,
            data=self.value,
        )


class _ConstructionStore:
    def __init__(self, process_record):
        self.process_record = process_record
        self.history = []

    def execute(self, _workspace_id, artifact_kind, artifact_id):
        if artifact_kind == "PROCESS_CASE" and artifact_id == "PROCESS_CASE":
            return self.process_record
        if (
            artifact_kind == "CONSTRUCTION_DEFECT_ANALYSIS_V1"
            and artifact_id == "CONSTRUCTION-DEFECT-ANALYSIS"
            and self.history
        ):
            return self.history[-1]
        raise LookupError((artifact_kind, artifact_id))

    def append_if_latest(self, **kwargs):
        expected = kwargs["expected_revision"]
        actual = self.history[-1].revision if self.history else None
        if expected != actual:
            raise RepositoryConflict("expected construction-defect revision is not latest")
        record = _record(
            kwargs["artifact_kind"],
            kwargs["artifact_id"],
            1 if actual is None else actual + 1,
            kwargs["payload"],
        )
        record.expected_dependencies = kwargs["expected_dependencies"]
        self.history.append(record)
        return record


def _application_services():
    process_case, case_analysis, planning, inspection = _canonical_inputs()
    process_record = _record("PROCESS_CASE", "PROCESS_CASE", 2, process_case.as_dict())
    case_record = _record(
        "CASE_ANALYSIS_SNAPSHOT_V1", "CASE-ANALYSIS", 3, _json_fixture("case-analysis-snapshot-v1.json")
    )
    planning_record = _record(
        "PERICIAL_PLANNING_SNAPSHOT_V1",
        "PERICIAL-PLANNING",
        4,
        _json_fixture("pericial-planning-snapshot-v1.json"),
    )
    inspection_record = _record(
        "INSPECTION_SESSION_V1",
        "INSPECTION-SESSION",
        5,
        _json_fixture("inspection-session-v1.json"),
    )
    store = _ConstructionStore(process_record)
    process_getter = _ProcessGetter(process_record, process_case)
    case_getter = _PairGetter(case_record, case_analysis)
    planning_getter = _PairGetter(planning_record, planning)
    inspection_getter = _PairGetter(inspection_record, inspection)
    get_snapshot = GetConstructionDefectAnalysis(
        store, process_getter, case_getter, planning_getter, inspection_getter
    )
    save_snapshot = SaveConstructionDefectAnalysis(
        store,
        store,
        process_getter,
        case_getter,
        planning_getter,
        inspection_getter,
        nullcontext,
        _FixedClock(),
        _SequenceIds(),
    )
    start = StartConstructionDefectAnalysis(
        store,
        process_getter,
        case_getter,
        planning_getter,
        inspection_getter,
        ConstructionDefectAnalysisAdapter(),
        save_snapshot,
        _SequenceIds(),
    )
    review = ReviewPathology(
        get_snapshot, save_snapshot, inspection_getter, _FixedClock(), _SequenceIds()
    )
    return SimpleNamespace(
        store=store,
        get=get_snapshot,
        save=save_snapshot,
        start=start,
        review=review,
        process=process_getter,
        case=case_getter,
        planning=planning_getter,
        inspection=inspection_getter,
    )
def _snapshot_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "snapshot_id": "CONSTRUCTION-DEFECT-ANALYSIS-001",
        "workspace_id": WORKSPACE_ID,
        "source_snapshot": {
            "workspace_id": WORKSPACE_ID,
            "process_case_revision": 2,
            "process_case_digest": "a" * 64,
            "case_analysis_snapshot_id": "CASE-ANALYSIS-001",
            "case_analysis_revision": 3,
            "case_analysis_digest": "b" * 64,
            "planning_snapshot_id": "PLANNING-001",
            "planning_revision": 4,
            "planning_digest": "c" * 64,
            "inspection_session_id": "INSPECTION-001",
            "inspection_revision": 5,
            "inspection_digest": "d" * 64,
            "source_revision": 2,
        },
        "observation_contexts": [
            {
                "observation_id": "OBSERVATION-CANONICAL-001",
                "manifestation": "Umidade visivel na interface.",
                "system": "IMPERMEABILIZACAO",
                "element": "Parede",
                "outcome": "OBSERVED",
                "methods": ["INSPECAO_VISUAL"],
                "measurement_ids": ["MEASUREMENT-CANONICAL-001"],
                "photo_ids": ["PHOTO-CANONICAL-001"],
                "claim_ids": ["CLAIM-CANONICAL-001"],
                "question_ids": ["QUESTION-CANONICAL-001"],
            }
        ],
        "identity_links": [
            {
                "canonical_kind": "FIELD_OBSERVATION",
                "canonical_id": "OBSERVATION-CANONICAL-001",
                "legacy_kind": "OBSERVATION",
                "legacy_id": "OBS-001",
            },
            {
                "canonical_kind": "MEASUREMENT",
                "canonical_id": "MEASUREMENT-CANONICAL-001",
                "legacy_kind": "MEASUREMENT",
                "legacy_id": "MED-001",
            },
            {
                "canonical_kind": "PHOTO_RECORD",
                "canonical_id": "PHOTO-CANONICAL-001",
                "legacy_kind": "PHOTO",
                "legacy_id": "FOT-001",
            },
            {
                "canonical_kind": "CASE_CLAIM",
                "canonical_id": "CLAIM-CANONICAL-001",
                "legacy_kind": "ALLEGATION",
                "legacy_id": "ALG-001",
            },
            {
                "canonical_kind": "CASE_QUESTION",
                "canonical_id": "QUESTION-CANONICAL-001",
                "legacy_kind": "QUESTION",
                "legacy_id": "QUE-001",
            },
            {
                "canonical_kind": "TECHNICAL_QUESTION",
                "canonical_id": "QUESTION-CANONICAL-001",
                "legacy_kind": "TECHNICAL_QUESTION",
                "legacy_id": "QT-001",
            },
            {
                "canonical_kind": "PATHOLOGY",
                "canonical_id": "PAT-001",
                "legacy_kind": "PATHOLOGY",
                "legacy_id": "PAT-001",
            },
        ],
        "analysis_final": {
            "schema_version": "1.0.0",
            "estado_analise": "PAT_FINAL",
            "patologias": [
                {
                    "id": "PAT-001",
                    "manifestacao": "Umidade visivel na interface.",
                    "constatacoes": ["OBS-001"],
                    "medicoes": ["MED-001"],
                    "evidencias": ["OBS-001", "MED-001", "FOT-001"],
                    "conclusao_tecnica": "Analise sintetica inconclusiva.",
                    "status_validacao": "RASCUNHO",
                }
            ],
        },
        "gate": "APTO_PARA_REDACAO_COM_RESSALVAS",
        "reviews": [
            {
                "review_id": "PAT-REVIEW-001",
                "pat_id": "PAT-001",
                "action": "APPROVE",
                "professional_id": "PROFESSIONAL-001",
                "reason": "Revisao profissional sintetica.",
                "reviewed_at": "2026-09-08T12:00:00+00:00",
                "supersedes_review_id": None,
            }
        ],
        "upstream_stale": False,
        "upstream_stale_reasons": [],
    }


def test_construction_defect_snapshot_round_trip_preserves_pat_and_canonical_identities():
    payload = _json_fixture("construction-defect-analysis-v1.json")

    snapshot = construction_defect_analysis_from_mapping(payload)

    assert type(snapshot) is ConstructionDefectAnalysisSnapshot
    assert isinstance(snapshot.analysis_final, MappingProxyType)
    assert snapshot.analysis_final["estado_analise"] == "PAT_FINAL"
    assert snapshot.effective_pat_ids == ("PAT-001",)
    assert construction_defect_analysis_to_mapping(snapshot) == payload


def test_construction_defect_snapshot_schema_is_strict_and_matches_contract():
    schema = json.loads(
        Path("schemas/construction-defect-analysis-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_snapshot_payload())
    poisoned = {**_snapshot_payload(), "unowned_field": True}
    assert list(Draft202012Validator(schema).iter_errors(poisoned))


def test_openapi_exposes_only_purpose_specific_pat_start_get_and_review():
    contract = json.loads(Path("contracts/openapi-v1.json").read_text(encoding="utf-8"))
    base = "/v1/workspaces/{workspace_id}/construction-defect-analysis"
    assert set(contract["paths"][base]) == {"get", "post"}
    assert set(contract["paths"][f"{base}/pathology-reviews"]) == {"post"}
    assert contract["components"]["schemas"]["ConstructionDefectAnalysis"] == {
        "$ref": "../schemas/construction-defect-analysis-v1.schema.json"
    }
    assert all(
        "subprocess" not in json.dumps(operation).lower()
        for operation in contract["paths"][base].values()
    )


def test_construction_defect_snapshot_rejects_ambiguous_identity_mapping():
    payload = _snapshot_payload()
    duplicate = deepcopy(payload["identity_links"][0])
    duplicate["canonical_id"] = "OBSERVATION-CANONICAL-002"
    payload["identity_links"].append(duplicate)

    with pytest.raises(ValueError, match="identity mapping is ambiguous"):
        construction_defect_analysis_from_mapping(payload)


def test_construction_defect_snapshot_requires_linear_review_history():
    payload = _snapshot_payload()
    payload["reviews"].append(
        {
            "review_id": "PAT-REVIEW-002",
            "pat_id": "PAT-001",
            "action": "REJECT",
            "professional_id": "PROFESSIONAL-001",
            "reason": "Revisao posterior sintetica.",
            "reviewed_at": "2026-09-08T13:00:00+00:00",
            "supersedes_review_id": "UNKNOWN-REVIEW",
        }
    )

    with pytest.raises(ValueError, match="review history is not linear"):
        construction_defect_analysis_from_mapping(payload)


@pytest.mark.parametrize(
    ("gate", "stale", "stale_reasons"),
    [
        ("BLOQUEADO_PARA_REDACAO", False, []),
        ("APTO_PARA_REDACAO_COM_RESSALVAS", True, ["INSPECTION_CHANGED"]),
    ],
)
def test_blocked_or_stale_pat_never_becomes_effective(
    gate: str, stale: bool, stale_reasons: list[str]
):
    payload = _snapshot_payload()
    payload["gate"] = gate
    payload["upstream_stale"] = stale
    payload["upstream_stale_reasons"] = stale_reasons

    snapshot = construction_defect_analysis_from_mapping(payload)

    assert snapshot.effective_pat_ids == ()


def test_adapter_maps_canonical_sources_losslessly_into_existing_pat_engine(monkeypatch):
    import scripts.planejamento_pericial.construction_defect_analysis_adapter as adapter_module

    process_case, case_analysis, planning, inspection = _canonical_inputs()
    captured: dict[str, object] = {}
    real_engine = adapter_module.executar_pipeline_motor

    def capture_engine(processo, delimitacao, plano, vistoria, conhecimento=None, **kwargs):
        captured.update(
            processo=processo,
            delimitacao=delimitacao,
            plano=plano,
            vistoria=vistoria,
            conhecimento=conhecimento,
            kwargs=kwargs,
        )
        return real_engine(
            processo,
            delimitacao,
            plano,
            vistoria,
            conhecimento=conhecimento,
            **kwargs,
        )

    monkeypatch.setattr(adapter_module, "executar_pipeline_motor", capture_engine)
    context = ObservationContext(
        observation_id="OBS-001",
        manifestation="Condicao superficial observada",
        system="VEDACOES",
        element="Parede",
        outcome=ObservationOutcome.CONFORMING,
        methods=("INSPECAO_VISUAL",),
        measurement_ids=("MEASUREMENT-001",),
        photo_ids=("PHOTO-001",),
        claim_ids=("CLAIM-001",),
        question_ids=("QUESTION-001",),
    )

    proposal = ConstructionDefectAnalysisAdapter().execute(
        process_case=process_case,
        case_analysis=case_analysis,
        planning=planning,
        inspection=inspection,
        observation_contexts=(context,),
    )

    links = {
        (item.canonical_kind, item.canonical_id): (item.legacy_kind, item.legacy_id)
        for item in proposal.identity_links
    }
    assert links[("FIELD_OBSERVATION", "OBS-001")] == ("OBSERVATION", "OBS-001")
    assert links[("MEASUREMENT", "MEASUREMENT-001")] == (
        "MEASUREMENT",
        "MED-001",
    )
    assert links[("PHOTO_RECORD", "PHOTO-001")] == ("PHOTO", "FOT-001")
    assert links[("CASE_CLAIM", "CLAIM-001")] == ("ALLEGATION", "ALG-001")
    assert links[("CASE_QUESTION", "QUESTION-001")] == ("QUESTION", "QUE-001")
    assert links[("TECHNICAL_QUESTION", "QUESTION-001")] == (
        "TECHNICAL_QUESTION",
        "QT-001",
    )
    assert ("PATHOLOGY", "PAT-001") in links
    assert proposal.analysis_final["estado_analise"] == "PAT_FINAL"
    assert proposal.gate == "APTO_PARA_REDACAO"
    assert proposal.analysis_final["patologias"][0]["constatacoes"] == ("OBS-001",)
    assert proposal.analysis_final["patologias"][0]["medicoes"] == ("MED-001",)
    assert proposal.analysis_final["patologias"][0]["constatacao"]["fotografias"] == (
        "FOT-001",
    )
    assert captured["vistoria"]["medicoes"][0]["valor"] == "1250"
    assert captured["vistoria"]["medicoes"][0]["unidade"] == "mm"
    assert captured["vistoria"]["fotografias"][0]["sha256_original"] == "e" * 64
    assert captured["conhecimento"] == {}


def test_snapshot_rejects_context_record_without_lossless_identity_link():
    payload = _snapshot_payload()
    payload["observation_contexts"][0]["photo_ids"] = ["PHOTO-UNMAPPED"]

    with pytest.raises(ValueError, match="canonical identity link is incomplete"):
        construction_defect_analysis_from_mapping(payload)


def test_adapter_rejects_context_for_non_direct_observation():
    process_case, case_analysis, planning, inspection = _canonical_inputs()
    context = ObservationContext(
        observation_id="OBS-002",
        manifestation="Contexto invalido",
        system="VEDACOES",
        element="Parede",
        outcome=ObservationOutcome.INCONCLUSIVE,
        methods=("INSPECAO_VISUAL",),
        measurement_ids=(),
        photo_ids=(),
        claim_ids=(),
        question_ids=(),
    )

    with pytest.raises(ValueError, match="direct field observation"):
        ConstructionDefectAnalysisAdapter().execute(
            process_case=process_case,
            case_analysis=case_analysis,
            planning=planning,
            inspection=inspection,
            observation_contexts=(context,),
        )


def test_adapter_rejects_cross_item_measurement_or_photo_links():
    process_case, case_analysis, planning, inspection = _canonical_inputs()
    foreign_payload = _json_fixture("inspection-session-v1.json")
    foreign_inspection = inspection_session_from_mapping(foreign_payload)
    context = ObservationContext(
        observation_id="OBS-001",
        manifestation="Condicao superficial observada",
        system="VEDACOES",
        element="Parede",
        outcome=ObservationOutcome.CONFORMING,
        methods=("INSPECAO_VISUAL",),
        measurement_ids=("MEASUREMENT-001",),
        photo_ids=("PHOTO-001",),
        claim_ids=("CLAIM-001",),
        question_ids=("QUESTION-001",),
    )

    with pytest.raises(ValueError, match="same inspection item"):
        ConstructionDefectAnalysisAdapter().execute(
            process_case=process_case,
            case_analysis=case_analysis,
            planning=planning,
            inspection=foreign_inspection,
            observation_contexts=(context,),
        )


def _application_context() -> ObservationContext:
    return ObservationContext(
        observation_id="OBS-001",
        manifestation="Condicao superficial observada",
        system="VEDACOES",
        element="Parede",
        outcome=ObservationOutcome.CONFORMING,
        methods=("INSPECAO_VISUAL",),
        measurement_ids=("MEASUREMENT-001",),
        photo_ids=("PHOTO-001",),
        claim_ids=("CLAIM-001",),
        question_ids=("QUESTION-001",),
    )


def test_application_binds_pat_to_exact_four_upstreams_and_reviews_append_only():
    services = _application_services()

    first_record, proposal = services.start.execute(
        WORKSPACE_ID, observation_contexts=(_application_context(),)
    )
    reviewed_record, reviewed = services.review.execute(
        WORKSPACE_ID,
        pat_id="PAT-001",
        action="APPROVE",
        professional_id="PROFESSIONAL-001",
        reason="Revisao profissional do PAT sintetico.",
        expected_revision=first_record.revision,
    )

    assert first_record.revision == 1
    assert proposal.effective_pat_ids == ()
    assert reviewed_record.revision == 2
    assert reviewed.effective_pat_ids == ("PAT-001",)
    assert reviewed.reviews[0].reviewed_at == "2026-09-08T14:00:00+00:00"
    assert [item["artifact_kind"] for item in first_record.expected_dependencies] == [
        "PROCESS_CASE",
        "CASE_ANALYSIS_SNAPSHOT_V1",
        "PERICIAL_PLANNING_SNAPSHOT_V1",
        "INSPECTION_SESSION_V1",
    ]
    reopened_record, reopened = services.get.execute(WORKSPACE_ID)
    assert reopened_record.revision == 2
    assert construction_defect_analysis_to_mapping(reopened) == (
        construction_defect_analysis_to_mapping(reviewed)
    )


def test_application_rejects_process_case_change_during_engine_execution():
    services = _application_services()
    consumed_process_numbers = []

    class ProcessChangingRunner:
        def execute(self, **kwargs):
            consumed_process_numbers.append(kwargs["process_case"].numero_processo)
            proposal = ConstructionDefectAnalysisAdapter().execute(**kwargs)
            changed_process = ProcessCaseData.from_mapping(
                {
                    **services.process.value.as_dict(),
                    "numero_processo": "9999999-99.2026.4.00.9999",
                }
            )
            changed_record = _record(
                "PROCESS_CASE",
                "PROCESS_CASE",
                services.process.record.revision + 1,
                changed_process.as_dict(),
            )
            services.process.record = changed_record
            services.process.value = changed_process
            services.store.process_record = changed_record
            return proposal

    start = StartConstructionDefectAnalysis(
        services.store,
        services.process,
        services.case,
        services.planning,
        services.inspection,
        ProcessChangingRunner(),
        services.save,
        _SequenceIds(),
    )

    with pytest.raises(ValueError, match="upstream authority is stale"):
        start.execute(WORKSPACE_ID, observation_contexts=(_application_context(),))

    assert consumed_process_numbers == ["0000001-00.2026.4.00.0001"]
    assert services.process.value.numero_processo == "9999999-99.2026.4.00.9999"
    assert services.store.history == []


def test_application_rejects_wrong_professional_and_stale_upstream_review():
    services = _application_services()
    record, _snapshot = services.start.execute(
        WORKSPACE_ID, observation_contexts=(_application_context(),)
    )

    with pytest.raises(ValueError, match="inspection authority"):
        services.review.execute(
            WORKSPACE_ID,
            pat_id="PAT-001",
            action="APPROVE",
            professional_id="OTHER-PROFESSIONAL",
            reason="Autoridade incorreta.",
            expected_revision=record.revision,
        )

    current = services.inspection.record
    services.inspection.record = _record(
        current.artifact_kind,
        current.artifact_id,
        current.revision + 1,
        _json_fixture("inspection-session-v1.json"),
    )
    _stale_record, stale = services.get.execute(WORKSPACE_ID)
    assert stale.upstream_stale is True
    assert stale.effective_pat_ids == ()
    with pytest.raises(RepositoryConflict, match="upstream is stale"):
        services.review.execute(
            WORKSPACE_ID,
            pat_id="PAT-001",
            action="APPROVE",
            professional_id="PROFESSIONAL-001",
            reason="Revisao tardia.",
            expected_revision=record.revision,
        )


def test_application_rejects_rewriting_pathology_review_history():
    from dataclasses import replace

    services = _application_services()
    first_record, _snapshot = services.start.execute(
        WORKSPACE_ID, observation_contexts=(_application_context(),)
    )
    reviewed_record, reviewed = services.review.execute(
        WORKSPACE_ID,
        pat_id="PAT-001",
        action="APPROVE",
        professional_id="PROFESSIONAL-001",
        reason="Revisao original.",
        expected_revision=first_record.revision,
    )
    rewritten = replace(reviewed, reviews=())

    with pytest.raises(ValueError, match="review history cannot be rewritten"):
        services.save.execute(
            WORKSPACE_ID,
            rewritten,
            reviewed_record.revision,
            mutation_authority="PROFESSIONAL",
        )


@pytest.mark.skipif(os.name != "nt", reason="mutable recovery is Windows-only")
def test_backup_restore_reopens_exact_approved_pat_graph(tmp_path):
    def canonical(value: object) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def revision(kind: str, artifact_id: str, payload: dict, sequence: int) -> dict:
        return {
            "workspace_id": WORKSPACE_ID,
            "artifact_kind": kind,
            "artifact_id": artifact_id,
            "revision_id": str(UUID(int=sequence)),
            "revision": 1,
            "created_at": "2026-09-08T12:00:00+00:00",
            "checksum_sha256": hashlib.sha256(canonical(payload)).hexdigest(),
            "payload": payload,
        }

    process_case, _case, _planning, _inspection = _canonical_inputs()
    process_revision = revision("PROCESS_CASE", "PROCESS_CASE", process_case.as_dict(), 1)

    def replace_text(value: object, replacements: dict[str, str]) -> object:
        if type(value) is dict:
            return {key: replace_text(item, replacements) for key, item in value.items()}
        if type(value) is list:
            return [replace_text(item, replacements) for item in value]
        return replacements.get(value, value) if type(value) is str else value

    case_payload = _json_fixture("case-analysis-snapshot-v1.json")
    source_private_payloads = []
    source_replacements = {}
    for index, document in enumerate(case_payload["documents"], 1):
        content = f"synthetic-case-source-{index}".encode()
        digest = hashlib.sha256(content).hexdigest()
        source_replacements[document["source_sha256"]] = digest
        source_private_payloads.append(
            {
                "workspace_id": WORKSPACE_ID,
                "content_id": document["storage_content_id"],
                "original_filename": f"synthetic-source-{index}.pdf",
                "byte_size": len(content),
                "checksum_sha256": digest,
                "media_type": "application/pdf",
                "imported_at": "2026-09-08T10:30:00+00:00",
                "origin": "USER_IMPORT",
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    case_payload = replace_text(case_payload, source_replacements)
    case_revision = revision("CASE_ANALYSIS_SNAPSHOT_V1", "CASE-ANALYSIS", case_payload, 2)
    planning_payload = replace_text(
        _json_fixture("pericial-planning-snapshot-v1.json"), source_replacements
    )
    planning_payload["plan"]["case_analysis_revision"] = 1
    planning_payload["plan"]["case_analysis_digest"] = case_revision["checksum_sha256"]
    planning_revision = revision(
        "PERICIAL_PLANNING_SNAPSHOT_V1", "PERICIAL-PLANNING", planning_payload, 3
    )
    inspection_payload = replace_text(_adjusted_inspection_payload(), source_replacements)
    inspection_payload["plan_snapshot"]["planning_revision"] = 1
    inspection_payload["plan_snapshot"]["planning_digest"] = planning_revision[
        "checksum_sha256"
    ]
    media_private_payloads = []
    for collection, media_type in (
        ("photos", "image/jpeg"),
        ("videos", "video/mp4"),
        ("sketches", "image/png"),
    ):
        for index, item in enumerate(inspection_payload[collection], 1):
            content = f"synthetic-{collection}-{index}".encode()
            digest = hashlib.sha256(content).hexdigest()
            item["original_sha256"] = digest
            media_private_payloads.append(
                {
                    "workspace_id": WORKSPACE_ID,
                    "content_id": item["private_content_id"],
                    "original_filename": f"synthetic-{collection}-{index}.bin",
                    "byte_size": len(content),
                    "checksum_sha256": digest,
                    "media_type": media_type,
                    "imported_at": "2026-09-08T11:00:00+00:00",
                    "origin": "USER_IMPORT",
                    "content_base64": base64.b64encode(content).decode("ascii"),
                }
            )
    inspection_revision = revision(
        "INSPECTION_SESSION_V1", "INSPECTION-SESSION", inspection_payload, 4
    )
    case = case_analysis_from_mapping(case_payload)
    planning = pericial_planning_from_mapping(planning_payload)
    inspection = inspection_session_from_mapping(inspection_payload)
    proposal = ConstructionDefectAnalysisAdapter().execute(
        process_case=process_case,
        case_analysis=case,
        planning=planning,
        inspection=inspection,
        observation_contexts=(_application_context(),),
    )
    snapshot = ConstructionDefectAnalysisSnapshot(
        schema_version="1.0.0",
        snapshot_id="CONSTRUCTION-DEFECT-ANALYSIS-PORTABLE-001",
        workspace_id=WORKSPACE_ID,
        source_snapshot=ConstructionDefectSourceSnapshot(
            workspace_id=WORKSPACE_ID,
            process_case_revision=1,
            process_case_digest=process_revision["checksum_sha256"],
            case_analysis_snapshot_id=case.snapshot_id,
            case_analysis_revision=1,
            case_analysis_digest=case_revision["checksum_sha256"],
            planning_snapshot_id=planning.snapshot_id,
            planning_revision=1,
            planning_digest=planning_revision["checksum_sha256"],
            inspection_session_id=inspection.session_id,
            inspection_revision=1,
            inspection_digest=inspection_revision["checksum_sha256"],
            source_revision=inspection.source_revision,
        ),
        observation_contexts=proposal.observation_contexts,
        identity_links=proposal.identity_links,
        analysis_final=proposal.analysis_final,
        gate=proposal.gate,
        reviews=(
            PathologyReview(
                "PAT-REVIEW-PORTABLE-001",
                "PAT-001",
                PathologyReviewAction.APPROVE,
                "PROFESSIONAL-001",
                "Revisao profissional sintetica antes do backup.",
                "2026-09-08T14:00:00+00:00",
                None,
            ),
        ),
        upstream_stale=False,
        upstream_stale_reasons=(),
    )
    pathology_revision = revision(
        CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
        CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
        construction_defect_analysis_to_mapping(snapshot),
        5,
    )
    backup = {
        "schema_version": "1.0.0",
        "format_version": 1,
        "product_release": PRODUCT_RELEASE_VERSION,
        "storage_schema_version": 1,
        "workspace": {
            "workspace_id": WORKSPACE_ID,
            "name": "Pericia PAT sintetica",
            "created_at": "2026-09-08T10:00:00+00:00",
        },
        "artifact_revisions": [
            process_revision,
            case_revision,
            planning_revision,
            inspection_revision,
            pathology_revision,
        ],
        "private_contents": [*source_private_payloads, *media_private_payloads],
        "member_hashes": {},
        "manifest_sha256": "0" * 64,
        "created_at": "2026-09-08T15:00:00+00:00",
    }
    backup["artifact_revisions"].sort(
        key=lambda item: (item["artifact_kind"], item["artifact_id"], item["revision"])
    )
    backup["private_contents"].sort(key=lambda item: item["content_id"])
    backup["member_hashes"] = {
        "artifact_revisions": hashlib.sha256(
            canonical(backup["artifact_revisions"])
        ).hexdigest(),
        "private_contents": hashlib.sha256(
            canonical(backup["private_contents"])
        ).hexdigest(),
    }
    backup["manifest_sha256"] = hashlib.sha256(
        canonical({key: value for key, value in backup.items() if key != "manifest_sha256"})
    ).hexdigest()
    package = canonical(backup)

    assert VerifyWorkspaceBackup().execute(package).workspace.workspace_id == WORKSPACE_ID
    staging = RecoveryStaging.create(tmp_path / "pat-restored")
    try:
        RestoreWorkspaceBackup(staging).execute(package)
        restored_record = staging.revisions.latest(
            WorkspaceId.parse(WORKSPACE_ID),
            CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
            CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
        )
        assert restored_record is not None
        restored = validated_construction_defect_analysis_from_mapping(
            thaw_payload(restored_record.payload)
        )
        assert construction_defect_analysis_to_mapping(restored) == (
            construction_defect_analysis_to_mapping(snapshot)
        )
        assert restored.effective_pat_ids == ("PAT-001",)
    finally:
        staging.discard()
