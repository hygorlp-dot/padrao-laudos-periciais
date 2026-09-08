"""Purpose-specific adapter from canonical product snapshots to ``motor_vicios``."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from uuid import NAMESPACE_URL, uuid5

from jsonschema import FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

from scripts.backend_contract.application.models import ProcessCaseData
from scripts.backend_contract.case_analysis import CaseAnalysisSnapshot
from scripts.backend_contract.construction_defect_analysis import (
    CanonicalIdentityLink,
    ObservationContext,
    ObservationOutcome,
    freeze_json_payload,
)
from scripts.backend_contract.pericial_planning import PlanningSnapshot
from scripts.backend_contract.vistoria import (
    InspectionSession,
    ObservationType,
)
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.planejamento_pericial.requisitos_materiais import evidencia_requerida


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _ROOT / "schemas" / "analise-motor-vicios.schema.json"
_OUTCOME = {
    ObservationOutcome.OBSERVED: "OBSERVADO",
    ObservationOutcome.NOT_OBSERVED: "NAO_CONSTATADO_NA_VISTORIA",
    ObservationOutcome.CONFORMING: "CONFORME",
    ObservationOutcome.INCONCLUSIVE: "INCONCLUSIVO",
}


def _engine_validator():
    registry = Registry()
    selected = None
    for path in (_ROOT / "schemas").glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
        if path == _SCHEMA_PATH:
            selected = schema
    if selected is None:  # pragma: no cover - repository corruption guard
        raise RuntimeError("construction-defect engine schema is unavailable")
    validator = validator_for(selected)
    validator.check_schema(selected)
    return validator(selected, registry=registry, format_checker=FormatChecker())


_ENGINE_VALIDATOR = _engine_validator()


@dataclass(frozen=True, slots=True)
class ConstructionDefectAnalysisProposal:
    observation_contexts: tuple[ObservationContext, ...]
    identity_links: tuple[CanonicalIdentityLink, ...]
    analysis_final: MappingProxyType
    gate: str

    def __post_init__(self) -> None:
        if not self.observation_contexts or not self.identity_links:
            raise ValueError("construction-defect proposal provenance is incomplete")
        if not isinstance(self.analysis_final, MappingProxyType):
            raise TypeError("construction-defect proposal must be immutable")
        if self.analysis_final.get("estado_analise") != "PAT_FINAL":
            raise ValueError("construction-defect proposal is not PAT_FINAL")
        if self.gate not in {
            "APTO_PARA_REDACAO",
            "APTO_PARA_REDACAO_COM_RESSALVAS",
            "BLOQUEADO_PARA_REDACAO",
        }:
            raise ValueError("construction-defect proposal gate is invalid")


def _aliases(values: set[str], prefix: str) -> dict[str, str]:
    return {
        value: f"{prefix}-{index:03d}"
        for index, value in enumerate(sorted(values), start=1)
    }


def _links(
    aliases: dict[str, str], canonical_kind: str, legacy_kind: str
) -> list[CanonicalIdentityLink]:
    return [
        CanonicalIdentityLink(canonical_kind, canonical_id, legacy_kind, legacy_id)
        for canonical_id, legacy_id in aliases.items()
    ]


class ConstructionDefectAnalysisAdapter:
    """Run the existing local engine after lossless, fail-closed adaptation."""

    def execute(
        self,
        *,
        process_case: ProcessCaseData,
        case_analysis: CaseAnalysisSnapshot,
        planning: PlanningSnapshot,
        inspection: InspectionSession,
        observation_contexts: tuple[ObservationContext, ...],
    ) -> ConstructionDefectAnalysisProposal:
        self._validate_sources(
            process_case, case_analysis, planning, inspection, observation_contexts
        )
        adapted = self._adapt(case_analysis, planning, inspection, observation_contexts)
        execution_id = str(
            uuid5(
                NAMESPACE_URL,
                "|".join(
                    (
                        inspection.workspace_id,
                        inspection.session_id,
                        *sorted(item.observation_id for item in observation_contexts),
                    )
                ),
            )
        )
        result = executar_pipeline_motor(
            {"numero_processo": process_case.numero_processo, "alegacoes": adapted["alegacoes"]},
            adapted["delimitacao"],
            adapted["plano"],
            adapted["vistoria"],
            conhecimento={},
            execucao_id=execution_id,
        )
        if type(result) is not dict or type(result.get("analise_final")) is not dict:
            raise ValueError("construction-defect engine returned an invalid result")
        analysis_final = result["analise_final"]
        if analysis_final.get("estado_analise") != "PAT_FINAL":
            raise ValueError("construction-defect engine did not produce PAT_FINAL")
        try:
            _ENGINE_VALIDATOR.validate(analysis_final)
        except ValidationError as exc:
            raise ValueError(
                f"construction-defect engine schema validation failed: {exc.message}"
            ) from exc
        gate = result.get("gate")
        if gate != analysis_final.get("gate_redacao"):
            raise ValueError("construction-defect engine gate is inconsistent")
        links = [*adapted["identity_links"]]
        for pathology in analysis_final["patologias"]:
            pat_id = pathology["id"]
            links.append(
                CanonicalIdentityLink("PATHOLOGY", pat_id, "PATHOLOGY", pat_id)
            )
        return ConstructionDefectAnalysisProposal(
            observation_contexts=observation_contexts,
            identity_links=tuple(links),
            analysis_final=freeze_json_payload(analysis_final),
            gate=gate,
        )

    @staticmethod
    def _validate_sources(
        process_case: ProcessCaseData,
        case_analysis: CaseAnalysisSnapshot,
        planning: PlanningSnapshot,
        inspection: InspectionSession,
        observation_contexts: tuple[ObservationContext, ...],
    ) -> None:
        if type(process_case) is not ProcessCaseData:
            raise TypeError("process case is invalid")
        if type(case_analysis) is not CaseAnalysisSnapshot:
            raise TypeError("case analysis is invalid")
        if type(planning) is not PlanningSnapshot:
            raise TypeError("pericial planning is invalid")
        if type(inspection) is not InspectionSession:
            raise TypeError("inspection session is invalid")
        if type(observation_contexts) is not tuple or not observation_contexts:
            raise ValueError("construction-defect analysis requires explicit contexts")
        if any(type(item) is not ObservationContext for item in observation_contexts):
            raise TypeError("construction-defect observation context is invalid")
        if len({item.observation_id for item in observation_contexts}) != len(
            observation_contexts
        ):
            raise ValueError("construction-defect observation context is duplicated")
        workspaces = {
            case_analysis.workspace_id,
            planning.workspace_id,
            inspection.workspace_id,
        }
        if len(workspaces) != 1:
            raise ValueError("construction-defect source workspace mismatch")
        if planning.upstream_stale or inspection.upstream_stale:
            raise ValueError("construction-defect source snapshot is stale")
        if planning.plan.case_analysis_snapshot_id != case_analysis.snapshot_id:
            raise ValueError("planning is not bound to the Case Analysis snapshot")
        if planning.plan.case_analysis_source_revision != case_analysis.source_revision:
            raise ValueError("planning source revision is not current")
        if (
            inspection.plan_snapshot.plan_id != planning.plan.plan_id
            or inspection.plan_snapshot.planning_snapshot_id != planning.snapshot_id
        ):
            raise ValueError("inspection is not bound to the planning snapshot")

        observations = {item.observation_id: item for item in inspection.observations}
        measurements = {item.measurement_id: item for item in inspection.measurements}
        photos = {item.photo_id: item for item in inspection.photos}
        claims = {item.item_id for item in case_analysis.claims}
        questions = {item.item_id for item in case_analysis.questions}
        used_measurements: set[str] = set()
        used_photos: set[str] = set()
        for context in observation_contexts:
            observation = observations.get(context.observation_id)
            if (
                observation is None
                or observation.observation_type is not ObservationType.DIRECT_OBSERVATION
            ):
                raise ValueError("context must target a direct field observation")
            if not set(context.claim_ids) <= claims:
                raise ValueError("observation context contains an unknown Case Analysis claim")
            if not set(context.question_ids) <= questions:
                raise ValueError("observation context contains an unknown Case Analysis question")
            selected_measurements = set(context.measurement_ids)
            selected_photos = set(context.photo_ids)
            if (
                not selected_measurements <= set(measurements)
                or not selected_photos <= set(photos)
            ):
                raise ValueError("observation context contains an unknown field record")
            if any(
                measurements[item].inspection_item_id != observation.inspection_item_id
                for item in selected_measurements
            ) or any(
                photos[item].inspection_item_id != observation.inspection_item_id
                for item in selected_photos
            ):
                raise ValueError(
                    "measurement and photo must belong to the same inspection item"
                )
            if used_measurements.intersection(selected_measurements) or used_photos.intersection(
                selected_photos
            ):
                raise ValueError("field record cannot ground multiple observation contexts")
            used_measurements.update(selected_measurements)
            used_photos.update(selected_photos)

    @staticmethod
    def _adapt(
        case_analysis: CaseAnalysisSnapshot,
        planning: PlanningSnapshot,
        inspection: InspectionSession,
        observation_contexts: tuple[ObservationContext, ...],
    ) -> dict[str, object]:
        observations = {item.observation_id: item for item in inspection.observations}
        measurements = {item.measurement_id: item for item in inspection.measurements}
        photos = {item.photo_id: item for item in inspection.photos}
        locations = {item.location_id: item.description for item in inspection.locations}
        methods = {item.method_id: item.name for item in inspection.methods}
        claims = {item.item_id: item for item in case_analysis.claims}
        questions = {item.item_id: item for item in case_analysis.questions}
        inspection_items = {item.item_id: item for item in inspection.items}

        context_by_observation = {
            item.observation_id: item for item in observation_contexts
        }
        observation_aliases = _aliases(set(context_by_observation), "OBS")
        measurement_aliases = _aliases(
            {item for context in observation_contexts for item in context.measurement_ids},
            "MED",
        )
        planned_measurement_aliases = {
            item: f"MED-PLANO-{index:03d}"
            for index, item in enumerate(sorted(measurement_aliases), start=1)
        }
        photo_aliases = _aliases(
            {item for context in observation_contexts for item in context.photo_ids}, "FOT"
        )
        claim_aliases = _aliases(
            {item for context in observation_contexts for item in context.claim_ids}, "ALG"
        )
        question_aliases = _aliases(
            {item for context in observation_contexts for item in context.question_ids},
            "QUE",
        )
        technical_question_aliases = {
            item: f"QT-{index:03d}"
            for index, item in enumerate(sorted(question_aliases), start=1)
        }
        planning_ids = {
            inspection_items[observations[context.observation_id].inspection_item_id].planning_item_id
            for context in observation_contexts
        }
        activity_aliases = _aliases(planning_ids, "ATV-PLANO")
        activity_execution_aliases = {
            item: f"ATV-EXEC-{index:03d}"
            for index, item in enumerate(sorted(planning_ids), start=1)
        }

        identity_links = [
            *_links(observation_aliases, "FIELD_OBSERVATION", "OBSERVATION"),
            *_links(measurement_aliases, "MEASUREMENT", "MEASUREMENT"),
            *_links(
                planned_measurement_aliases,
                "PLANNED_MEASUREMENT_SOURCE",
                "PLANNED_MEASUREMENT",
            ),
            *_links(photo_aliases, "PHOTO_RECORD", "PHOTO"),
            *_links(claim_aliases, "CASE_CLAIM", "ALLEGATION"),
            *_links(question_aliases, "CASE_QUESTION", "QUESTION"),
            *_links(
                technical_question_aliases,
                "TECHNICAL_QUESTION",
                "TECHNICAL_QUESTION",
            ),
            *_links(activity_aliases, "PLANNING_ITEM", "PLANNED_ACTIVITY"),
        ]

        owner_context: dict[str, ObservationContext] = {}
        owner_observation_alias: dict[str, str] = {}
        legacy_observations = []
        for context in sorted(observation_contexts, key=lambda item: item.observation_id):
            observation = observations[context.observation_id]
            inspection_item = inspection_items[observation.inspection_item_id]
            legacy_observation_id = observation_aliases[context.observation_id]
            qts = [technical_question_aliases[item] for item in context.question_ids]
            ques = [question_aliases[item] for item in context.question_ids]
            algs = [claim_aliases[item] for item in context.claim_ids]
            for item in (*context.measurement_ids, *context.photo_ids):
                owner_context[item] = context
                owner_observation_alias[item] = legacy_observation_id
            legacy_observations.append(
                {
                    "id": legacy_observation_id,
                    "descricao_objetiva": observation.raw_observation,
                    "manifestacao": context.manifestation,
                    "ambiente": locations[observation.location_id],
                    "sistema": context.system,
                    "elemento": context.element,
                    "resultado": _OUTCOME[context.outcome],
                    "metodo": list(context.methods),
                    "questoes": qts,
                    "quesitos": ques,
                    "alegacoes": algs,
                    "fotografias": [photo_aliases[item] for item in context.photo_ids],
                    "medicoes": [
                        measurement_aliases[item] for item in context.measurement_ids
                    ],
                    "atividade_planejada": activity_aliases[
                        inspection_item.planning_item_id
                    ],
                    "data_hora": observation.timestamp,
                    "proveniencia": [
                        f"INSPECTION_SESSION:{inspection.session_id}",
                        f"FIELD_OBSERVATION:{observation.observation_id}",
                        observation.provenance,
                    ],
                }
            )

        legacy_measurements = []
        for canonical_id, legacy_id in measurement_aliases.items():
            measurement = measurements[canonical_id]
            context = owner_context[canonical_id]
            observation = observations[context.observation_id]
            inspection_item = inspection_items[observation.inspection_item_id]
            legacy_measurements.append(
                {
                    "id": legacy_id,
                    "medicao_planejada": planned_measurement_aliases[canonical_id],
                    "grandeza": measurement.quantity,
                    "valor": measurement.raw_value,
                    "unidade": measurement.raw_unit,
                    "local": locations[measurement.location_id],
                    "sistema": context.system,
                    "elemento": context.element,
                    "manifestacao": context.manifestation,
                    "questoes": [
                        technical_question_aliases[item] for item in context.question_ids
                    ],
                    "quesitos": [question_aliases[item] for item in context.question_ids],
                    "alegacoes": [claim_aliases[item] for item in context.claim_ids],
                    "observacoes": [owner_observation_alias[canonical_id]],
                    "atividade_planejada": activity_aliases[
                        inspection_item.planning_item_id
                    ],
                    "metodo": methods[measurement.method_id],
                    "anotacao": measurement.raw_observation,
                    "data_hora": measurement.timestamp,
                    "proveniencia": [
                        f"INSPECTION_SESSION:{inspection.session_id}",
                        f"MEASUREMENT:{measurement.measurement_id}",
                        measurement.provenance,
                    ],
                }
            )

        legacy_photos = []
        for canonical_id, legacy_id in photo_aliases.items():
            photo = photos[canonical_id]
            context = owner_context[canonical_id]
            observation = observations[context.observation_id]
            inspection_item = inspection_items[observation.inspection_item_id]
            legacy_photos.append(
                {
                    "id": legacy_id,
                    "fotografia_planejada": None,
                    "finalidade_planejada": photo.caption,
                    "descricao_visual_observada": None,
                    "sha256_original": photo.original_sha256,
                    "local": locations[photo.location_id],
                    "sistema": context.system,
                    "elemento": context.element,
                    "manifestacao": context.manifestation,
                    "questoes": [
                        technical_question_aliases[item] for item in context.question_ids
                    ],
                    "quesitos": [question_aliases[item] for item in context.question_ids],
                    "alegacoes": [claim_aliases[item] for item in context.claim_ids],
                    "observacoes": [owner_observation_alias[canonical_id]],
                    "atividade_planejada": activity_aliases[
                        inspection_item.planning_item_id
                    ],
                    "data_hora": photo.reliable_capture_timestamp,
                    "proveniencia": [
                        f"INSPECTION_SESSION:{inspection.session_id}",
                        f"PHOTO_RECORD:{photo.photo_id}",
                        f"SHA256:{photo.original_sha256}",
                        photo.provenance,
                    ],
                }
            )

        activity_contexts: dict[str, list[ObservationContext]] = {
            item: [] for item in planning_ids
        }
        for context in observation_contexts:
            observation = observations[context.observation_id]
            planning_id = inspection_items[
                observation.inspection_item_id
            ].planning_item_id
            activity_contexts[planning_id].append(context)

        planned_activities = []
        planned_measurements = []
        executed_activities = []
        execution_coverage = []
        coverage_requirements = []
        for planning_id in sorted(activity_contexts):
            contexts = activity_contexts[planning_id]
            qts = sorted(
                {
                    technical_question_aliases[item]
                    for context in contexts
                    for item in context.question_ids
                }
            )
            ques = sorted(
                {
                    question_aliases[item]
                    for context in contexts
                    for item in context.question_ids
                }
            )
            algs = sorted(
                {
                    claim_aliases[item]
                    for context in contexts
                    for item in context.claim_ids
                }
            )
            planned_id = activity_aliases[planning_id]
            executed_id = activity_execution_aliases[planning_id]
            planned_activities.append(
                {
                    "id": planned_id,
                    "verificar": "; ".join(
                        sorted({context.manifestation for context in contexts})
                    ),
                    "metodo": "; ".join(
                        sorted({method for context in contexts for method in context.methods})
                    ),
                    "evidencia_esperada": "observacao direta registrada",
                    "questoes_tecnicas": qts,
                    "quesitos": ques,
                    "alegacoes": algs,
                }
            )
            executed_activities.append(
                {
                    "id": executed_id,
                    "atividade_planejada": planned_id,
                    "questoes": qts,
                    "quesitos": ques,
                    "alegacoes": algs,
                    "resultado": "EXECUTADO",
                }
            )
            execution_coverage.append(
                {
                    "tipo": "ATIVIDADE",
                    "planejado": planned_id,
                    "status": "EXECUTADO",
                    "executado": [executed_id],
                    "evidencia_equivalente": [],
                }
            )

        for canonical_id, planned_id in planned_measurement_aliases.items():
            measurement = measurements[canonical_id]
            context = owner_context[canonical_id]
            qts = [technical_question_aliases[item] for item in context.question_ids]
            ques = [question_aliases[item] for item in context.question_ids]
            planned_measurements.append(
                {
                    "id": planned_id,
                    "grandeza": measurement.quantity,
                    "local": locations[measurement.location_id],
                    "criterio": f"Registrar valor bruto em {measurement.raw_unit}",
                    "precisao_necessaria": f"Unidade {measurement.raw_unit}",
                    "questoes_tecnicas": qts,
                    "quesitos": ques,
                    "alegacoes": [claim_aliases[item] for item in context.claim_ids],
                }
            )
            execution_coverage.append(
                {
                    "tipo": "MEDICAO",
                    "planejado": planned_id,
                    "status": "EXECUTADO",
                    "executado": [measurement_aliases[canonical_id]],
                    "evidencia_equivalente": [],
                }
            )

        semantic_requirements = []
        planned_coverage = []
        for canonical_id, que_id in question_aliases.items():
            qt_id = technical_question_aliases[canonical_id]
            activities = sorted(
                {
                    activity_aliases[
                        inspection_items[
                            observations[context.observation_id].inspection_item_id
                        ].planning_item_id
                    ]
                    for context in observation_contexts
                    if canonical_id in context.question_ids
                }
            )
            measurement_items = sorted(
                {
                    planned_measurement_aliases[measurement_id]
                    for context in observation_contexts
                    if canonical_id in context.question_ids
                    for measurement_id in context.measurement_ids
                }
            )
            required_evidence = evidencia_requerida(questions[canonical_id].text)
            if required_evidence == "OBSERVACIONAL":
                required_items = [("ATIVIDADE", item) for item in activities]
            elif required_evidence in {"METROLOGICA", "DESCONHECIDA"}:
                required_items = [("MEDICAO", item) for item in measurement_items]
            else:
                required_items = []
            semantic_requirements.append(
                {
                    "requirement_id": f"REQ-{qt_id}",
                    "quesito": que_id,
                    "requisito": questions[canonical_id].text,
                    "itens_planejados": [item for _, item in required_items],
                }
            )
            coverage_requirements.extend(
                {
                    "questao_tecnica": qt_id,
                    "tipo": item_type,
                    "obrigatoriedade": "OBRIGATORIA",
                    "item_planejado": item,
                }
                for item_type, item in required_items
            )
            planned_coverage.append(
                {
                    "quesito": que_id,
                    "questoes_tecnicas": [qt_id],
                    "atividades": activities,
                    "fotografias": [],
                    "medicoes": measurement_items,
                    "ensaios": [],
                    "documentos": [],
                }
            )

        legacy_questions = []
        technical_questions = []
        for canonical_id, que_id in question_aliases.items():
            qt_id = technical_question_aliases[canonical_id]
            related_claims = sorted(
                {
                    claim_aliases[item]
                    for context in observation_contexts
                    if canonical_id in context.question_ids
                    for item in context.claim_ids
                }
            )
            legacy_questions.append(
                {
                    "id": que_id,
                    "texto": questions[canonical_id].text,
                    "pertinencia": "PERTINENTE",
                    "materia_juridica_associada": False,
                    "materia_tecnica": True,
                    "questoes_tecnicas_relacionadas": [qt_id],
                }
            )
            technical_questions.append(
                {
                    "id": qt_id,
                    "descricao": questions[canonical_id].text,
                    "alegacoes_relacionadas": related_claims,
                    "quesitos_relacionados": [que_id],
                }
            )

        relations = []
        for context in observation_contexts:
            obs_id = observation_aliases[context.observation_id]
            for item in context.measurement_ids:
                relations.append(
                    {
                        "observacao": obs_id,
                        "evidencia": measurement_aliases[item],
                        "motivo": "VINCULO_CANONICO_EXPLICITO",
                        "origem": "INSPECTION_ITEM_COMUM",
                    }
                )
            for item in context.photo_ids:
                relations.append(
                    {
                        "observacao": obs_id,
                        "evidencia": photo_aliases[item],
                        "motivo": "VINCULO_CANONICO_EXPLICITO",
                        "origem": "INSPECTION_ITEM_COMUM",
                    }
                )

        return {
            "alegacoes": [
                {"id": legacy_id, "descricao": claims[canonical_id].text}
                for canonical_id, legacy_id in claim_aliases.items()
            ],
            "delimitacao": {
                "tipo_pericia": {"tipo": "VICIOS_CONSTRUTIVOS"},
                "questoes_tecnicas": technical_questions,
                "quesitos": legacy_questions,
                "ressalvas": [],
            },
            "plano": {
                "atividades": planned_activities,
                "fotografias": [],
                "medicoes": planned_measurements,
                "ensaios": [],
                "documentos_a_solicitar": [],
                "requisitos_cobertura": coverage_requirements,
                "requisitos_semanticos": semantic_requirements,
                "cobertura": planned_coverage,
            },
            "vistoria": {
                "observacoes": legacy_observations,
                "medicoes": legacy_measurements,
                "fotografias": legacy_photos,
                "atividades_executadas": executed_activities,
                "ensaios": [],
                "documentos_obtidos": [],
                "declaracoes": [],
                "cobertura": execution_coverage,
                "relacoes_evidencia": relations,
            },
            "identity_links": identity_links,
        }
