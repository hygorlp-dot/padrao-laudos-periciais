"""Situacao do fluxo pericial: projecao SOMENTE DE LEITURA (#291).

Agrega as autoridades de leitura que ja existem (`Get*`) para responder, de uma
vez: qual e a situacao de cada etapa, o que espera decisao profissional e o que
ficou desatualizado. A matriz de estados e seus fundamentos estao em
`docs/arquitetura/decisoes/ADR-workflow-status-projection-v1.md`.

Limites (decisao de produto (a)):
- nada aqui grava, aprova, decide, agenda ou dispara OCR/renderizacao/derivacao;
- nenhum estado e persistido: cada chamada le a autoridade da propria etapa;
- existir registro nao e "etapa concluida": READY/APPROVED so quando o proprio
  dominio ja diz isso;
- falha de consulta de uma etapa e UNAVAILABLE naquela etapa, nunca estado vazio;
- texto livre de motivos internos nao sai daqui: so codigos e contagens.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from ..case_analysis import CASE_ANALYSIS_ARTIFACT_ID, CASE_ANALYSIS_ARTIFACT_KIND, CoverageStatus
from ..construction_defect_analysis import (
    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
    CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND,
)
from ..delivery_foundation import (
    DELIVERY_SNAPSHOT_ARTIFACT_ID,
    DELIVERY_SNAPSHOT_ARTIFACT_KIND,
    DeliveryRole,
    DeliveryState,
)
from ..pericial_planning import PERICIAL_PLANNING_ARTIFACT_ID, PERICIAL_PLANNING_ARTIFACT_KIND, ReadinessStatus
from ..report_foundation import REPORT_SNAPSHOT_ARTIFACT_ID, REPORT_SNAPSHOT_ARTIFACT_KIND, ReportState
from ..technical_findings import (
    TECHNICAL_SNAPSHOT_ARTIFACT_ID,
    TECHNICAL_SNAPSHOT_ARTIFACT_KIND,
    ConflictStatus,
    EvidenceReviewState,
)
from ..vistoria import INSPECTION_SESSION_ARTIFACT_ID, INSPECTION_SESSION_ARTIFACT_KIND
from .budget_foundation import BUDGET_SNAPSHOT_ARTIFACT_ID, BUDGET_SNAPSHOT_ARTIFACT_KIND
from .document_ingestion import FAILED, INTERRUPTED, PROCESSING, READY
from .models import thaw_payload
from .ports import WorkspaceNotFound
from .report_foundation import validated_report_snapshot_from_mapping

# Chaves = segmentos de rota do catalogo do frontend; a ordem e a do fluxo.
STAGES = (
    "processo", "materiais", "analise", "planejamento", "vistoria", "evidencias",
    "constatacoes", "analise-tecnica", "laudo", "revisao", "exportar", "orcamento",
    "recuperacao",
)
STATES = (
    "NOT_STARTED", "IN_PROGRESS", "PROCESSING", "AWAITING_REVIEW", "REVIEW_REQUIRED",
    "ATTENTION", "READY", "APPROVED", "RECORDED", "NOT_TRACKED", "UNAVAILABLE",
)
AVAILABILITY = ("AVAILABLE", "UNAVAILABLE")
CURRENCY = ("CURRENT", "STALE", "NOT_EVALUATED")
DECISIONS = ("NOT_TRACKED", "NONE", "PARTIAL", "COMPLETE", "REVIEWED", "APPROVED")

# Mesma constante de `services.py`: a confirmacao processual e um artefato
# proprio, e so a existencia dela e lida aqui.
_PROCESS_METADATA_CONFIRMATION_KIND = "PROCESS_METADATA_CONFIRMATION"
_PROCESS_METADATA_CONFIRMATION_ID = "PROCESS_METADATA_CONFIRMATION"


@dataclass(frozen=True, slots=True)
class StageReason:
    code: str
    count: int | None = None

    def __post_init__(self):
        if type(self.code) is not str or not self.code or not self.code.replace("_", "").isalnum() or not self.code.isupper():
            raise ValueError("codigo de motivo invalido")
        if self.count is not None and (type(self.count) is not int or self.count < 0):
            raise ValueError("contagem de motivo invalida")


@dataclass(frozen=True, slots=True)
class StageStatus:
    stage: str
    state: str
    availability: str
    currency: str
    decision: str
    reasons: tuple[StageReason, ...]
    revision: int | None = None
    updated_at: str | None = None

    def __post_init__(self):
        if self.stage not in STAGES or self.state not in STATES:
            raise ValueError("etapa ou estado fora do conjunto fechado")
        if self.availability not in AVAILABILITY or self.currency not in CURRENCY or self.decision not in DECISIONS:
            raise ValueError("dimensao fora do conjunto fechado")
        if (self.state == "UNAVAILABLE") != (self.availability == "UNAVAILABLE"):
            raise ValueError("indisponibilidade tem de ser coerente entre estado e consulta")
        if self.state == "REVIEW_REQUIRED" and self.currency != "STALE":
            raise ValueError("revisao necessaria exige base desatualizada")
        if self.currency == "STALE" and self.state not in {"REVIEW_REQUIRED", "UNAVAILABLE", "ATTENTION"}:
            # Base desatualizada nunca pode aparecer como pronta/aprovada/registrada.
            raise ValueError("base desatualizada nao pode parecer vigente")
        if self.state in {"READY", "APPROVED", "RECORDED"} and self.revision is None and self.stage not in {"materiais"}:
            raise ValueError("estado afirmativo exige revisao que o sustente")
        if type(self.reasons) is not tuple or any(type(item) is not StageReason for item in self.reasons):
            raise ValueError("motivos invalidos")
        if self.revision is not None and (type(self.revision) is not int or self.revision < 1):
            raise ValueError("revisao invalida")


@dataclass(frozen=True, slots=True)
class WorkflowStatus:
    workspace_id: str
    stages: tuple[StageStatus, ...]

    def __post_init__(self):
        if tuple(item.stage for item in self.stages) != STAGES:
            raise ValueError("a projecao tem de cobrir todas as etapas, na ordem do fluxo")


def workflow_status_to_mapping(status: WorkflowStatus) -> dict:
    return {
        "workspace_id": status.workspace_id,
        "stages": [
            {
                "stage": item.stage,
                "state": item.state,
                "availability": item.availability,
                "currency": item.currency,
                "decision": item.decision,
                "reasons": [
                    {"code": reason.code, **({} if reason.count is None else {"count": reason.count})}
                    for reason in item.reasons
                ],
                "revision": item.revision,
                "updated_at": item.updated_at,
            }
            for item in status.stages
        ],
    }


def _reason(code: str, count: int | None = None) -> StageReason:
    return StageReason(code, count)


def _counted(code: str, count: int) -> tuple[StageReason, ...]:
    return (StageReason(code, count),) if count else ()


def _unavailable(stage: str, code: str = "QUERY_FAILED") -> StageStatus:
    return StageStatus(stage, "UNAVAILABLE", "UNAVAILABLE", "NOT_EVALUATED", "NOT_TRACKED", (_reason(code),))


def _not_started(stage: str, decision: str = "NONE", *reasons: StageReason) -> StageStatus:
    return StageStatus(stage, "NOT_STARTED", "AVAILABLE", "NOT_EVALUATED", decision, tuple(reasons))


def _stale(stage: str, decision: str, record, reasons_count: int, *extra: StageReason) -> StageStatus:
    return StageStatus(
        stage, "REVIEW_REQUIRED", "AVAILABLE", "STALE", decision,
        (_reason("UPSTREAM_CHANGED", reasons_count), *extra), record.revision, record.created_at,
    )


def _item_decision(pending: int, decided: int) -> str:
    if not pending and not decided:
        return "NONE"
    if pending and decided:
        return "PARTIAL"
    return "NONE" if pending else "COMPLETE"


@dataclass(frozen=True, slots=True)
class GetWorkflowStatus:
    """Le cada autoridade de etapa sob uma unica janela sem gravacoes."""

    get_workspace: object
    revisions: object
    consistent_reads: Callable[[], AbstractContextManager]
    get_process_case: object
    get_case_analysis: object
    get_pericial_planning: object
    get_inspection_session: object
    get_technical_snapshot: object
    get_construction_defect_analysis: object
    get_report_snapshot: object
    get_budget_snapshot: object
    get_process_metadata_review: object | None = None
    ingestion: object | None = None
    get_delivery_snapshot: object | None = None

    def execute(self, workspace_id) -> WorkflowStatus:
        with self.consistent_reads():
            workspace = self.get_workspace.execute(workspace_id)
            workspace_id = workspace.workspace_id
            materials = self._guard(lambda: self._material_states(workspace_id))
            technical = self._guard(lambda: self._artifact(
                workspace_id, TECHNICAL_SNAPSHOT_ARTIFACT_KIND, TECHNICAL_SNAPSHOT_ARTIFACT_ID, self.get_technical_snapshot,
            ))
            report = self._guard(lambda: self._report(workspace_id))
            stages = (
                self._stage("processo", lambda: self._process(workspace_id, materials)),
                self._stage("materiais", lambda: self._materials(materials)),
                self._stage("analise", lambda: self._analysis(workspace_id)),
                self._stage("planejamento", lambda: self._planning(workspace_id)),
                self._stage("vistoria", lambda: self._inspection(workspace_id)),
                self._stage("evidencias", lambda: self._evidence(technical)),
                self._stage("constatacoes", lambda: self._findings(technical)),
                self._stage("analise-tecnica", lambda: self._defects(workspace_id)),
                self._stage("laudo", lambda: self._report_drafting(report)),
                self._stage("revisao", lambda: self._report_review(report)),
                self._stage("exportar", lambda: self._delivery(workspace_id)),
                self._stage("orcamento", lambda: self._budget(workspace_id)),
                StageStatus("recuperacao", "NOT_TRACKED", "AVAILABLE", "NOT_EVALUATED", "NOT_TRACKED", (_reason("MANAGEMENT_TOOL"),)),
            )
        return WorkflowStatus(str(workspace_id), stages)

    # -- infraestrutura de leitura -------------------------------------------------

    @staticmethod
    def _guard(read):
        """Leitura compartilhada por mais de uma etapa; a falha vira valor, nao some."""
        try:
            return ("ok", read())
        except WorkspaceNotFound:
            raise
        except Exception as exc:  # noqa: BLE001 -- qualquer falha e "nao verificado", nunca vazio
            return ("failed", exc)

    @staticmethod
    def _stage(stage: str, build) -> StageStatus:
        try:
            return build()
        except WorkspaceNotFound:
            raise
        except _ServiceMissing:
            return _unavailable(stage, "SERVICE_UNAVAILABLE")
        except Exception:  # noqa: BLE001 -- a etapa fica UNAVAILABLE; as demais seguem
            return _unavailable(stage)

    def _artifact(self, workspace_id, kind: str, artifact_id: str, getter):
        """(registro, snapshot reconciliado) ou None quando a etapa nunca comecou.

        A existencia e conferida antes: um "nao encontrado" vindo de uma autoridade
        de montante, dentro do `Get*`, e inconsistencia (UNAVAILABLE), nao inicio.
        """
        if self.revisions.latest(workspace_id, kind, artifact_id) is None:
            return None
        return getter.execute(workspace_id)

    @staticmethod
    def _unwrap(shared):
        outcome, value = shared
        if outcome == "failed":
            raise value
        return value

    def _material_states(self, workspace_id):
        if self.ingestion is None:
            raise _ServiceMissing()
        return Counter(state for _record, state in self.ingestion.states(workspace_id))

    def _report(self, workspace_id):
        found = self._artifact(workspace_id, REPORT_SNAPSHOT_ARTIFACT_KIND, REPORT_SNAPSHOT_ARTIFACT_ID, self.get_report_snapshot)
        if found is None:
            return None
        record, snapshot = found
        # A reconciliacao devolve DRAFT e descarta as decisoes quando a base muda;
        # a decisao HISTORICA vem do proprio registro persistido.
        persisted = validated_report_snapshot_from_mapping(thaw_payload(record.payload))
        return record, snapshot, persisted.state

    # -- etapas -----------------------------------------------------------------------

    def _process(self, workspace_id, materials) -> StageStatus:
        case = self.get_process_case.execute(workspace_id)
        revision, updated_at = case.revision, case.updated_at
        counts = self._unwrap(materials) if self.ingestion is not None else Counter()
        if self.get_process_metadata_review is None:
            if revision is None:
                return _not_started("processo", "NOT_TRACKED", _reason("METADATA_REVIEW_UNAVAILABLE"))
            return StageStatus("processo", "RECORDED", "AVAILABLE", "NOT_EVALUATED", "NOT_TRACKED",
                               (_reason("PROCESS_DATA_RECORDED"), _reason("METADATA_REVIEW_UNAVAILABLE")), revision, updated_at)
        review = self.get_process_metadata_review.execute(workspace_id)
        confirmation = self.revisions.latest(workspace_id, _PROCESS_METADATA_CONFIRMATION_KIND, _PROCESS_METADATA_CONFIRMATION_ID)
        state = review.state
        if state == "CONFIRMED":
            return StageStatus("processo", "RECORDED", "AVAILABLE", "CURRENT", "COMPLETE",
                               (_reason("METADATA_CONFIRMED"),), revision, updated_at)
        if counts[PROCESSING]:
            # Extracao ausente enquanto a derivacao roda nao e erro: ainda nao terminou.
            return StageStatus("processo", "PROCESSING", "AVAILABLE", "NOT_EVALUATED", "NONE",
                               _counted("MATERIALS_PROCESSING", counts[PROCESSING]), revision, updated_at)
        if confirmation is not None and state != "WAITING_FOR_DOCUMENTS":
            # Ja houve confirmacao, mas ela nao se vincula mais a extracao/revisao atual.
            return StageStatus("processo", "REVIEW_REQUIRED", "AVAILABLE", "STALE", "COMPLETE",
                               (_reason("METADATA_CONFIRMATION_OUTDATED"),), revision, updated_at)
        if state == "CONFLICT":
            return StageStatus("processo", "ATTENTION", "AVAILABLE", "NOT_EVALUATED", "NONE",
                               (_reason("METADATA_CONFLICT"),), revision, updated_at)
        if state == "ERROR":
            return StageStatus("processo", "ATTENTION", "AVAILABLE", "NOT_EVALUATED", "NONE",
                               (_reason("METADATA_EXTRACTION_FAILED"),), revision, updated_at)
        if state in {"EXTRACTED", "PARTIAL"}:
            return StageStatus("processo", "AWAITING_REVIEW", "AVAILABLE", "NOT_EVALUATED", "NONE",
                               (_reason("METADATA_AWAITING_CONFIRMATION" if state == "EXTRACTED" else "METADATA_PARTIAL_AWAITING_CONFIRMATION"),),
                               revision, updated_at)
        if state == "WAITING_FOR_DOCUMENTS":
            if revision is None:
                return _not_started("processo", "NONE", _reason("NO_PROCESS_DATA"))
            return StageStatus("processo", "RECORDED", "AVAILABLE", "NOT_EVALUATED", "NONE",
                               (_reason("PROCESS_DATA_RECORDED"),), revision, updated_at)
        raise ValueError("estado de metadados processuais desconhecido")

    def _materials(self, materials) -> StageStatus:
        counts = self._unwrap(materials)
        facts = (
            *_counted("MATERIALS_READY", counts[READY]),
            *_counted("MATERIALS_PROCESSING", counts[PROCESSING]),
            *_counted("MATERIALS_FAILED", counts[FAILED]),
            *_counted("MATERIALS_INTERRUPTED", counts[INTERRUPTED]),
        )
        if not sum(counts.values()):
            return _not_started("materiais", "NOT_TRACKED", _reason("NO_MATERIALS"))
        if counts[FAILED] or counts[INTERRUPTED]:
            state = "ATTENTION"
        elif counts[PROCESSING]:
            state = "PROCESSING"
        else:
            state = "RECORDED"
        return StageStatus("materiais", state, "AVAILABLE", "NOT_EVALUATED", "NOT_TRACKED", facts)

    def _analysis(self, workspace_id) -> StageStatus:
        found = self._artifact(workspace_id, CASE_ANALYSIS_ARTIFACT_KIND, CASE_ANALYSIS_ARTIFACT_ID, self.get_case_analysis)
        if found is None:
            return _not_started("analise")
        record, snapshot = found
        pending = sum(1 for item in snapshot.conflicts if item.human_review_status == "PENDING")
        reviewed = len(snapshot.conflicts) - pending
        decision = _item_decision(pending, reviewed) if snapshot.conflicts else ("COMPLETE" if snapshot.human_reviews else "NONE")
        coverage = () if snapshot.coverage.status is CoverageStatus.COMPLETE else (_reason(f"COVERAGE_{snapshot.coverage.status.value}"),)
        changed = len(snapshot.stale_document_ids)
        if changed or snapshot.source_inventory_stale:
            return StageStatus(
                "analise", "REVIEW_REQUIRED", "AVAILABLE", "STALE", decision,
                (*_counted("SOURCES_CHANGED", changed), *_counted("SOURCES_NOT_INDEXED", snapshot.unindexed_source_count), *coverage),
                record.revision, record.created_at,
            )
        if pending:
            return StageStatus("analise", "AWAITING_REVIEW", "AVAILABLE", "CURRENT", decision,
                               (_reason("CONFLICTS_AWAITING_REVIEW", pending), *coverage), record.revision, record.created_at)
        return StageStatus("analise", "RECORDED", "AVAILABLE", "CURRENT", decision,
                           (*_counted("QUESTIONS_RECORDED", len(snapshot.questions)), *coverage), record.revision, record.created_at)

    def _planning(self, workspace_id) -> StageStatus:
        found = self._artifact(workspace_id, PERICIAL_PLANNING_ARTIFACT_KIND, PERICIAL_PLANNING_ARTIFACT_ID, self.get_pericial_planning)
        if found is None:
            return _not_started("planejamento")
        record, snapshot = found
        coverage = snapshot.coverage
        decision = _item_decision(coverage.pending_items, coverage.reviewed_items)
        if snapshot.upstream_stale:
            return _stale("planejamento", decision, record, len(snapshot.upstream_stale_reasons),
                          *_counted("ITEMS_AWAITING_REVIEW", coverage.pending_items))
        if coverage.pending_items:
            return StageStatus("planejamento", "AWAITING_REVIEW", "AVAILABLE", "CURRENT", decision,
                               (_reason("ITEMS_AWAITING_REVIEW", coverage.pending_items),), record.revision, record.created_at)
        if coverage.readiness is ReadinessStatus.READY:
            return StageStatus("planejamento", "READY", "AVAILABLE", "CURRENT", decision,
                               (_reason("PLANNING_READY"),), record.revision, record.created_at)
        state = "ATTENTION" if coverage.readiness is ReadinessStatus.BLOCKED else "IN_PROGRESS"
        return StageStatus("planejamento", state, "AVAILABLE", "CURRENT", decision,
                           (_reason(f"PLANNING_{coverage.readiness.value}", len(coverage.readiness_reasons)),
                            *_counted("ITEMS_DEFERRED", coverage.deferred_items)),
                           record.revision, record.created_at)

    def _inspection(self, workspace_id) -> StageStatus:
        found = self._artifact(workspace_id, INSPECTION_SESSION_ARTIFACT_KIND, INSPECTION_SESSION_ARTIFACT_ID, self.get_inspection_session)
        if found is None:
            return _not_started("vistoria", "NOT_TRACKED")
        record, session = found
        coverage = session.coverage
        facts = (
            *_counted("ITEMS_PENDING", coverage.pending_items),
            *_counted("ITEMS_COMPLETED", coverage.completed_items),
            *_counted("ITEMS_PARTIAL", coverage.partial_items),
            *_counted("ITEMS_NOT_EXECUTED", coverage.not_executed_items),
            *_counted("ITEMS_NOT_APPLICABLE", coverage.not_applicable_items),
            *_counted("ITEMS_BLOCKED", coverage.blocked_items),
        )
        if session.upstream_stale:
            return _stale("vistoria", "NOT_TRACKED", record, len(session.upstream_stale_reasons), *facts)
        state = "IN_PROGRESS" if coverage.pending_items or not coverage.total_items else "RECORDED"
        if not coverage.total_items:
            facts = (_reason("NO_ITEMS"),)
        return StageStatus("vistoria", state, "AVAILABLE", "CURRENT", "NOT_TRACKED", facts, record.revision, record.created_at)

    def _evidence(self, technical) -> StageStatus:
        found = self._unwrap(technical)
        if found is None:
            return _not_started("evidencias")
        record, snapshot = found
        states = Counter(item.review_state for item in snapshot.evidence_assessments)
        pending = states[EvidenceReviewState.PENDING]
        decision = _item_decision(pending, states[EvidenceReviewState.APPROVED] + states[EvidenceReviewState.REJECTED])
        facts = (
            *_counted("EVIDENCE_AWAITING_REVIEW", pending),
            *_counted("EVIDENCE_APPROVED", states[EvidenceReviewState.APPROVED]),
            *_counted("EVIDENCE_REJECTED", states[EvidenceReviewState.REJECTED]),
        )
        if snapshot.upstream_stale:
            return _stale("evidencias", decision, record, len(snapshot.upstream_stale_reasons), *facts)
        if pending:
            state = "AWAITING_REVIEW"
        elif not snapshot.evidence_items:
            state, facts = "IN_PROGRESS", (_reason("NO_EVIDENCE"),)
        else:
            state = "RECORDED"
        return StageStatus("evidencias", state, "AVAILABLE", "CURRENT", decision, facts, record.revision, record.created_at)

    def _findings(self, technical) -> StageStatus:
        found = self._unwrap(technical)
        if found is None:
            return _not_started("constatacoes")
        record, snapshot = found
        decided = {decision.proposal_id for decision in snapshot.decisions}
        pending = sum(1 for proposal in snapshot.finding_proposals if proposal.proposal_id not in decided)
        unresolved = sum(1 for conflict in snapshot.conflicts if conflict.status is ConflictStatus.UNRESOLVED)
        decision = _item_decision(pending, len(snapshot.finding_proposals) - pending)
        facts = (
            *_counted("PROPOSALS_AWAITING_DECISION", pending),
            *_counted("CONFLICTS_UNRESOLVED", unresolved),
            *_counted("FINDINGS_EFFECTIVE", len(snapshot.findings)),
        )
        if snapshot.upstream_stale:
            return _stale("constatacoes", decision, record, len(snapshot.upstream_stale_reasons), *facts)
        if not snapshot.finding_proposals:
            return StageStatus("constatacoes", "NOT_STARTED", "AVAILABLE", "CURRENT", "NONE",
                               (_reason("NO_PROPOSALS"),), record.revision, record.created_at)
        state = "ATTENTION" if unresolved else "AWAITING_REVIEW" if pending else "RECORDED"
        return StageStatus("constatacoes", state, "AVAILABLE", "CURRENT", decision, facts, record.revision, record.created_at)

    def _defects(self, workspace_id) -> StageStatus:
        found = self._artifact(
            workspace_id, CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND, CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID,
            self.get_construction_defect_analysis,
        )
        if found is None:
            return _not_started("analise-tecnica")
        record, snapshot = found
        decision = "COMPLETE" if snapshot.reviews else "NONE"
        gate = _reason(f"GATE_{snapshot.gate}")
        if snapshot.upstream_stale:
            return _stale("analise-tecnica", decision, record, len(snapshot.upstream_stale_reasons), gate)
        state = "ATTENTION" if snapshot.gate == "BLOQUEADO_PARA_REDACAO" else "RECORDED"
        return StageStatus("analise-tecnica", state, "AVAILABLE", "CURRENT", decision,
                           (gate, *_counted("PATHOLOGY_REVIEWS", len(snapshot.reviews))), record.revision, record.created_at)

    @staticmethod
    def _report_decision(state: ReportState) -> str:
        return {ReportState.REVIEWED: "REVIEWED", ReportState.APPROVED: "APPROVED"}.get(state, "NONE")

    def _report_drafting(self, report) -> StageStatus:
        found = self._unwrap(report)
        if found is None:
            return _not_started("laudo")
        record, snapshot, persisted = found
        decision = self._report_decision(persisted)
        coverage = () if snapshot.coverage.complete else (_reason("COVERAGE_INCOMPLETE", len(snapshot.coverage.reasons)),)
        if snapshot.upstream_stale:
            return _stale("laudo", decision, record, len(snapshot.upstream_stale_reasons), _reason(f"REPORT_{persisted.value}"))
        if snapshot.state is ReportState.SUPERSEDED:
            return StageStatus("laudo", "ATTENTION", "AVAILABLE", "CURRENT", decision,
                               (_reason("REPORT_SUPERSEDED"),), record.revision, record.created_at)
        state = {
            ReportState.DRAFT: "IN_PROGRESS", ReportState.REVIEWED: "AWAITING_REVIEW", ReportState.APPROVED: "APPROVED",
        }[snapshot.state]
        return StageStatus("laudo", state, "AVAILABLE", "CURRENT", decision,
                           (_reason(f"REPORT_{snapshot.state.value}"), *coverage), record.revision, record.created_at)

    def _report_review(self, report) -> StageStatus:
        found = self._unwrap(report)
        if found is None:
            return _not_started("revisao", "NONE", _reason("REPORT_NOT_STARTED"))
        record, snapshot, persisted = found
        decision = self._report_decision(persisted)
        if snapshot.upstream_stale:
            return _stale("revisao", decision, record, len(snapshot.upstream_stale_reasons), _reason(f"REPORT_{persisted.value}"))
        if snapshot.state is ReportState.SUPERSEDED:
            return StageStatus("revisao", "ATTENTION", "AVAILABLE", "CURRENT", decision,
                               (_reason("REPORT_SUPERSEDED"),), record.revision, record.created_at)
        if snapshot.state is ReportState.DRAFT:
            return StageStatus("revisao", "NOT_STARTED", "AVAILABLE", "CURRENT", decision,
                               (_reason("REPORT_NOT_REVIEWED"),), record.revision, record.created_at)
        if snapshot.state is ReportState.REVIEWED:
            return StageStatus("revisao", "AWAITING_REVIEW", "AVAILABLE", "CURRENT", decision,
                               (_reason("REPORT_AWAITING_APPROVAL"),), record.revision, record.created_at)
        return StageStatus("revisao", "APPROVED", "AVAILABLE", "CURRENT", decision,
                           (_reason("REPORT_APPROVED"),), record.revision, record.created_at)

    def _delivery(self, workspace_id) -> StageStatus:
        if self.revisions.latest(workspace_id, DELIVERY_SNAPSHOT_ARTIFACT_KIND, DELIVERY_SNAPSHOT_ARTIFACT_ID) is None:
            return _not_started("exportar")
        if self.get_delivery_snapshot is None:
            raise _ServiceMissing()
        record, snapshot = self.get_delivery_snapshot.execute(workspace_id)
        roles = {artifact.role for artifact in snapshot.artifacts}
        if not roles:
            artifacts = (_reason("NO_ARTIFACTS"),)
        elif DeliveryRole.MAIN_REPORT in roles and DeliveryRole.DERIVED_PDF not in roles:
            artifacts = (_reason("WORD_PRESENT"), _reason("PDF_ABSENT"))
        elif DeliveryRole.MAIN_REPORT in roles:
            artifacts = (_reason("WORD_PRESENT"), _reason("PDF_PRESENT"))
        else:
            artifacts = (_reason("WORD_ABSENT"),)
        origin = snapshot.stale_origin_state if snapshot.state is DeliveryState.STALE else snapshot.state
        decision = "APPROVED" if origin in {DeliveryState.APPROVED, DeliveryState.FINALIZED, DeliveryState.DELIVERED} else "NONE"
        if snapshot.state is DeliveryState.STALE:
            if "UPSTREAM_AUTHORITY_UNAVAILABLE" in snapshot.stale_reasons:
                return StageStatus("exportar", "UNAVAILABLE", "UNAVAILABLE", "NOT_EVALUATED", decision,
                                   (_reason("UPSTREAM_AUTHORITY_UNAVAILABLE"), *artifacts), record.revision, record.created_at)
            return _stale("exportar", decision, record, len(snapshot.stale_reasons), *artifacts)
        if snapshot.state is DeliveryState.SUPERSEDED:
            return StageStatus("exportar", "ATTENTION", "AVAILABLE", "CURRENT", decision,
                               (_reason("DELIVERY_SUPERSEDED"),), record.revision, record.created_at)
        state = {
            DeliveryState.DRAFT: "IN_PROGRESS", DeliveryState.READY_FOR_REVIEW: "AWAITING_REVIEW",
            DeliveryState.APPROVED: "APPROVED", DeliveryState.FINALIZED: "APPROVED", DeliveryState.DELIVERED: "APPROVED",
        }[snapshot.state]
        return StageStatus("exportar", state, "AVAILABLE", "CURRENT", decision,
                           (_reason(f"DELIVERY_{snapshot.state.value}"), *artifacts), record.revision, record.created_at)

    def _budget(self, workspace_id) -> StageStatus:
        found = self._artifact(workspace_id, BUDGET_SNAPSHOT_ARTIFACT_KIND, BUDGET_SNAPSHOT_ARTIFACT_ID, self.get_budget_snapshot)
        if found is None:
            return _not_started("orcamento", "NOT_TRACKED", _reason("OPTIONAL_STAGE"))
        record, budget = found
        return StageStatus("orcamento", "RECORDED", "AVAILABLE", "NOT_EVALUATED", "NOT_TRACKED",
                           (_reason(f"FINANCIAL_{budget.status.value}"), _reason("OPTIONAL_STAGE")), record.revision, record.created_at)


class _ServiceMissing(Exception):
    """A composicao nao tem a autoridade desta etapa (ex.: sem armazenamento privado)."""
