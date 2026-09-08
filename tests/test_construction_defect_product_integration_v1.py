from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import MappingProxyType

from jsonschema import Draft202012Validator
import pytest

from scripts.backend_contract.construction_defect_analysis import (
    ConstructionDefectAnalysisSnapshot,
    ObservationContext,
    ObservationOutcome,
    construction_defect_analysis_from_mapping,
    construction_defect_analysis_to_mapping,
)
from scripts.backend_contract.application.models import ProcessCaseData
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.pericial_planning import pericial_planning_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping
from scripts.planejamento_pericial.construction_defect_analysis_adapter import (
    ConstructionDefectAnalysisAdapter,
)


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
FIXTURES = Path("tests/fixtures")


def _json_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _canonical_inputs():
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
