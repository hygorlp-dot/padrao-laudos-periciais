"""Application operations for workspace-owned Pericial Planning snapshots."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from ..pericial_planning import (
    PERICIAL_PLANNING_ARTIFACT_ID,
    PERICIAL_PLANNING_ARTIFACT_KIND,
    PlanningSnapshot,
    PlanningDecision,
    InspectionRequirement,
    PericialPlan,
    PlanningCoverage,
    PlanningDerivation,
    PlanningIssue,
    ProfessionalReviewStatus,
    ProposalStatus,
    QuestionPlanningLink,
    ReadinessStatus,
    ReviewAction,
    append_professional_decision,
    case_analysis_digest,
    pericial_planning_from_mapping,
    pericial_planning_to_mapping,
    validate_against_case_analysis,
)
from .models import thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "pericial-planning-snapshot-v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


def validated_pericial_planning_from_mapping(value: object) -> PlanningSnapshot:
    try:
        _VALIDATOR.validate(value)
        return pericial_planning_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Pericial Planning payload") from exc


def _refuse_new_references_to_unavailable_documents(analysis, snapshot, previous=None) -> None:
    """Unica guarda: recusa o que o snapshot PASSA a referenciar sobre peca indisponivel.

    O Start monta o plano a partir dos itens efetivos e o grava pela criacao do Save, entao
    esta guarda cobre os dois caminhos; uma guarda separada no Start era redundante.

    Recusar tudo que estivesse derivado (como no Start) travava planos legados: um plano
    criado na main sobre uma lacuna que citava a propria peca ausente ficava com toda
    decisao recusada -- inclusive sobre itens sem relacao nenhuma com a peca. Criar um
    plano (sem predecessor) continua exigindo que nenhuma referencia seja derivada;
    numa atualizacao, so as referencias NOVAS sao julgadas.
    """
    # O predecessor so serve de baseline se o plano continua autorizado pela MESMA analise.
    # Revincular o plano (trocar digest/revisao da Analise do Caso) e uma nova autorizacao:
    # tudo volta a ser julgado, como numa criacao.
    if previous is not None and (
        previous.plan.case_analysis_digest != snapshot.plan.case_analysis_digest
        or previous.plan.case_analysis_revision != snapshot.plan.case_analysis_revision
    ):
        previous = None

    def referenced(planning):
        # Pares (item do plano, item da analise): um item NOVO que cita um derivado ja
        # citado por outro item tambem e uma referencia nova.
        return {
            (item.item_id, item_id)
            for item in planning.material_items for item_id in item.derivation.case_analysis_item_ids
        }

    derived = {item.item_id for item in analysis.material_items if analysis.derived_from_unavailable(item)}
    introduced = referenced(snapshot) - (referenced(previous) if previous is not None else set())
    offending = sorted({item_id for _plan_item, item_id in introduced if item_id in derived})
    if offending:
        raise ValueError(
            "Pericial Planning cannot build on items derived from a document excluded by the professional: "
            + ", ".join(offending)
        )


@dataclass(frozen=True, slots=True)
class SavePericialPlanning:
    revisions: object
    get_latest_revision: object
    get_case_analysis: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, snapshot: PlanningSnapshot, expected_revision: int | None, *, allow_review_transition: bool = False, allow_succession: bool = False):
        if type(snapshot) is not PlanningSnapshot or str(workspace_id) != snapshot.workspace_id:
            raise ValueError("Pericial Planning workspace identity mismatch")
        if snapshot.upstream_stale:
            raise ValueError("stale Pericial Planning snapshots cannot be persisted")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        if allow_succession and (expected_revision is None or allow_review_transition):
            raise ValueError("Pericial Planning succession requires the stale predecessor revision")
        if (expected_revision is None or allow_succession) and (
            snapshot.decisions or any(item.professional_review_status.value != "PENDING" for item in snapshot.material_items)
        ):
            raise ValueError("initial Pericial Planning must be proposal-only")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Pericial Planning authority guard is unavailable")
        with self.authority_guard():
            return self._execute_guarded(workspace_id, snapshot, expected_revision, allow_review_transition, allow_succession)

    def _execute_guarded(self, workspace_id, snapshot: PlanningSnapshot, expected_revision: int | None, allow_review_transition: bool, allow_succession: bool):
        analysis_record, analysis = self.get_case_analysis.execute(workspace_id)
        if analysis.stale_document_ids or analysis.source_inventory_stale:
            raise ValueError("stale Case Analysis cannot authorize Pericial Planning")
        if expected_revision is None or allow_succession:
            _refuse_new_references_to_unavailable_documents(analysis, snapshot)
        validate_against_case_analysis(snapshot, analysis, artifact_revision=analysis_record.revision)
        if expected_revision is not None:
            previous_record = self.get_latest_revision.execute(
                workspace_id,
                PERICIAL_PLANNING_ARTIFACT_KIND,
                PERICIAL_PLANNING_ARTIFACT_ID,
            )
            if previous_record.revision != expected_revision:
                raise ValueError("expected Pericial Planning revision is not latest")
            previous = validated_pericial_planning_from_mapping(thaw_payload(previous_record.payload))
            if allow_succession:
                _validate_succession(previous, snapshot, analysis_record, analysis)
            else:
                _refuse_new_references_to_unavailable_documents(analysis, snapshot, previous)
                _validate_append_only_history(previous, snapshot)
                if not allow_review_transition and snapshot.decisions != previous.decisions:
                    raise ValueError("Pericial Planning decisions require the professional review command")
        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Pericial Planning clock requires timezone")
        return self.revisions.append_if_latest(
            workspace_id=workspace_id,
            artifact_kind=PERICIAL_PLANNING_ARTIFACT_KIND,
            artifact_id=PERICIAL_PLANNING_ARTIFACT_ID,
            revision_id=str(self.ids.new_uuid()),
            created_at=created_at.isoformat(),
            payload=pericial_planning_to_mapping(snapshot),
            expected_revision=expected_revision,
            expected_dependencies=({
                "artifact_kind": analysis_record.artifact_kind,
                "artifact_id": analysis_record.artifact_id,
                "revision": analysis_record.revision,
                "checksum_sha256": analysis_record.checksum_sha256,
            },),
        )


@dataclass(frozen=True, slots=True)
class GetPericialPlanning:
    get_latest_revision: object
    get_case_analysis: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id,
            PERICIAL_PLANNING_ARTIFACT_KIND,
            PERICIAL_PLANNING_ARTIFACT_ID,
        )
        snapshot = validated_pericial_planning_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Pericial Planning workspace mismatch")
        analysis_record, analysis = self.get_case_analysis.execute(workspace_id)
        reconciled = snapshot.reconcile_upstream(
            snapshot_id=analysis.snapshot_id,
            revision=analysis_record.revision,
            source_revision=analysis.source_revision,
            digest=case_analysis_digest(analysis),
        )
        return record, reconciled


@dataclass(frozen=True, slots=True)
class ReviewPericialPlanning:
    get_planning: object
    save_planning: object
    clock: object
    ids: object

    def execute(
        self,
        workspace_id,
        *,
        target_item_id: str,
        action: str,
        reviewer: str,
        reason: str,
        decided_value: str | None,
        expected_revision: int,
    ):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected revision is invalid")
        record, snapshot = self.get_planning.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Pericial Planning revision is not latest")
        if snapshot.upstream_stale:
            raise ValueError("stale Pericial Planning cannot receive professional decisions")
        target = next((item for item in snapshot.material_items if item.item_id == target_item_id), None)
        if target is None:
            raise ValueError("professional decision target is invalid")
        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("professional decision clock requires timezone")
        decision_uuid = self.ids.new_uuid()
        history = [item for item in snapshot.decisions if item.target_item_id == target_item_id]
        decision = PlanningDecision(
            decision_id=f"PLANNING-DECISION-{decision_uuid.hex.upper()}",
            target_item_id=target_item_id,
            action=ReviewAction(action),
            proposal_value=target.description,
            decided_value=decided_value,
            reviewer=reviewer,
            reason=reason,
            revision=len(history) + 1,
            timestamp=created_at.isoformat(),
        )
        reviewed = append_professional_decision(snapshot, decision)
        saved = self.save_planning.execute(workspace_id, reviewed, expected_revision, allow_review_transition=True)
        return saved, reviewed


@dataclass(frozen=True, slots=True)
class StartPericialPlanning:
    get_case_analysis: object
    save_planning: object
    ids: object

    def execute(self, workspace_id, *, title: str):
        snapshot = self.propose(workspace_id, title=title)
        saved = self.save_planning.execute(workspace_id, snapshot, None)
        return saved, snapshot

    def propose(self, workspace_id, *, title: str) -> PlanningSnapshot:
        """Monta um plano so de propostas sobre a Analise do Caso vigente."""
        record, analysis = self.get_case_analysis.execute(workspace_id)
        if analysis.stale_document_ids or analysis.source_inventory_stale or type(title) is not str or not title.strip():
            raise ValueError("current reviewed Case Analysis is required to start planning")
        effective = [(item, analysis.effective_reviewed_value(item.item_id)) for item in analysis.material_items]
        effective = [(item, value) for item, value in effective if value is not None]

        def derivation(item):
            specialized = dict(question_ids=(), pericial_object_ids=(), court_decision_ids=(), technical_document_reference_ids=(), gap_or_conflict_ids=())
            if item in analysis.questions: specialized["question_ids"] = (item.item_id,)
            if item in analysis.pericial_objects: specialized["pericial_object_ids"] = (item.item_id,)
            if item in analysis.decisions: specialized["court_decision_ids"] = (item.item_id,)
            if item in analysis.technical_document_references: specialized["technical_document_reference_ids"] = (item.item_id,)
            if item in (*analysis.gaps, *analysis.conflicts): specialized["gap_or_conflict_ids"] = (item.item_id,)
            return PlanningDerivation(
                rationale="Proposta derivada do valor efetivo revisado da análise.",
                case_analysis_item_ids=(item.item_id,), source_provenance=item.provenance, **specialized,
            )

        pending = dict(priority="MEDIUM", proposal_status=ProposalStatus.PROPOSED, professional_review_status=ProfessionalReviewStatus.PENDING)
        issues = tuple(
            PlanningIssue(item_id=f"PLAN-ISSUE-{self.ids.new_uuid().hex.upper()}", title="Tema para planejamento", description=value, derivation=derivation(item), **pending)
            for item, value in effective if item not in analysis.questions
        )
        inspection_by_question = tuple(
            (item, InspectionRequirement(
                item_id=f"PLAN-INSPECTION-{self.ids.new_uuid().hex.upper()}", title="Verificar quesito em diligência",
                description=value, derivation=derivation(item), inspection_target=value,
                field_observations_needed=("Registrar constatação pertinente ao quesito.",), **pending,
            )) for item, value in effective if item in analysis.questions
        )
        links = tuple(
            QuestionPlanningLink(
                item_id=f"PLAN-QUESTION-{self.ids.new_uuid().hex.upper()}", title="Vínculo do quesito",
                description=value, derivation=derivation(item), question_id=item.item_id,
                linked_item_ids=(inspection.item_id,), dependency_item_ids=(), **pending,
            ) for (item, inspection), (_, value) in zip(inspection_by_question, ((i, v) for i, v in effective if i in analysis.questions), strict=True)
        )
        inspections = tuple(value for _, value in inspection_by_question)
        total = len(issues) + len(inspections) + len(links)
        snapshot = PlanningSnapshot(
            schema_version="1.0.0", snapshot_id=f"PLANNING-SNAPSHOT-{self.ids.new_uuid().hex.upper()}", workspace_id=str(workspace_id),
            plan=PericialPlan(f"PERICIAL-PLAN-{self.ids.new_uuid().hex.upper()}", title.strip(), str(workspace_id), analysis.snapshot_id, record.revision, analysis.source_revision, case_analysis_digest(analysis)),
            objectives=(), issues=issues, question_links=links, required_documents=(), required_information=(),
            inspection_requirements=inspections, measurement_requirements=(), photo_requirements=(), equipment_requirements=(),
            access_requirements=(), method_candidates=(), procedure_candidates=(), sampling_candidates=(), safety_requirements=(),
            external_support_requirements=(), risks=(), gaps=(), decisions=(),
            coverage=PlanningCoverage(total, 0, total, 0, 0, 0, 0, ReadinessStatus.PARTIAL, ("Itens materiais aguardam revisão profissional.",)),
        )
        return snapshot


@dataclass(frozen=True, slots=True)
class StartSuccessorPericialPlanning:
    """Novo plano sobre a Analise do Caso vigente, quando o atual ficou para tras (#252).

    O plano anterior nao e apagado nem "des-stalead": continua como revisao
    imutavel do mesmo artefato, com todas as suas decisoes, no historico e no
    backup. O sucessor nasce so de propostas -- nenhuma decisao antiga e
    transportada ou promovida -- e passa a ser o plano corrente. So um plano
    stale pode ser sucedido; um plano vigente continua recebendo decisoes.
    """

    get_planning: object
    start_planning: StartPericialPlanning
    save_planning: object

    def execute(self, workspace_id, *, title: str, expected_revision: int):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected revision is invalid")
        # So a revisao lida aqui; se o plano continua vigente, o Save recusa sob a
        # guarda de autoridade, contra a Analise lida na mesma transacao.
        record, _current = self.get_planning.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Pericial Planning revision is not latest")
        snapshot = self.start_planning.propose(workspace_id, title=title)
        saved = self.save_planning.execute(workspace_id, snapshot, expected_revision, allow_succession=True)
        return saved, snapshot


def _validate_succession(previous: PlanningSnapshot, successor: PlanningSnapshot, analysis_record, analysis) -> None:
    # Revalidado sob a guarda de autoridade, contra a Analise lida na mesma transacao:
    # a sucessao so existe porque o predecessor deixou de refletir a analise vigente.
    reconciled = previous.reconcile_upstream(
        snapshot_id=analysis.snapshot_id,
        revision=analysis_record.revision,
        source_revision=analysis.source_revision,
        digest=case_analysis_digest(analysis),
    )
    if not reconciled.upstream_stale:
        raise ValueError("only a stale Pericial Planning can be succeeded")
    if successor.plan.plan_id == previous.plan.plan_id or successor.snapshot_id == previous.snapshot_id:
        raise ValueError("Pericial Planning successor requires a new plan identity")


def _validate_append_only_history(previous: PlanningSnapshot, current: PlanningSnapshot) -> None:
    if previous.plan.plan_id != current.plan.plan_id:
        raise ValueError("immutable pericial plan identity cannot be replaced")
    previous_items = {item.item_id: _proposal_signature(item) for item in previous.material_items}
    current_items = {item.item_id: _proposal_signature(item) for item in current.material_items}
    if not previous_items.keys() <= current_items.keys() or any(
        current_items[item_id] != signature for item_id, signature in previous_items.items()
    ):
        raise ValueError("immutable proposal history cannot be replaced")
    previous_decisions = pericial_planning_to_mapping(previous)["decisions"]
    current_decisions = pericial_planning_to_mapping(current)["decisions"]
    if current_decisions[: len(previous_decisions)] != previous_decisions:
        raise ValueError("immutable proposal decision history cannot be replaced")


def _proposal_signature(item) -> dict:
    value = asdict(item)
    value.pop("professional_review_status", None)
    return value
