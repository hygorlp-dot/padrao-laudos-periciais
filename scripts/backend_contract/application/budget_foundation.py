"""Append-only application authority for the financial Budget Snapshot."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..budget_foundation import (
    BudgetItem,
    CostCategory,
    CourtApprovedAmount,
    Expense,
    FeeProposal,
    FinancialStatus,
    PericialBudget,
    ProfessionalEffortEstimate,
    ProposalRevision,
    ReceivedPayment,
    ThirdPartyEstimate,
    TravelEstimate,
    budget_snapshot_from_mapping,
    budget_snapshot_to_mapping,
    derive_financial_status,
    normalize_legacy_budget_mapping,
)
from .models import thaw_payload
from .ports import RepositoryConflict


BUDGET_SNAPSHOT_ARTIFACT_KIND = "BUDGET_SNAPSHOT_V1"
BUDGET_SNAPSHOT_ARTIFACT_ID = "BUDGET-SNAPSHOT"
_SCHEMA = Path(__file__).resolve().parents[3] / "schemas" / "budget-snapshot-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker())
_HISTORY_FIELDS = (
    "items", "effort_estimates", "travel_estimates", "third_party_estimates", "expenses",
    "proposals", "proposal_revisions", "court_approvals", "payments",
)


def _derived_total(left: str, right: str) -> str:
    try:
        values = (Decimal(left), Decimal(right))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("budget factors must be decimal strings") from exc
    if any(value.as_tuple().exponent != -2 or not value.is_finite() or value < 0 for value in values):
        raise ValueError("budget factors require non-negative two-decimal values")
    return f"{values[0] * values[1]:.2f}"


def _payload(value: object) -> object:
    return value if type(value) is dict else thaw_payload(value)


def validated_budget_snapshot_from_mapping(value: object) -> PericialBudget:
    try:
        value = normalize_legacy_budget_mapping(value)
        _VALIDATOR.validate(value)
        return budget_snapshot_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Budget Snapshot payload") from exc


def budget_snapshot_to_validated_mapping(value: PericialBudget) -> dict:
    mapping = budget_snapshot_to_mapping(value)
    _VALIDATOR.validate(mapping)
    return mapping


def _preserves_history(predecessor: PericialBudget, candidate: PericialBudget) -> bool:
    return all(getattr(candidate, name)[:len(getattr(predecessor, name))] == getattr(predecessor, name) for name in _HISTORY_FIELDS)


@dataclass(frozen=True, slots=True)
class SaveBudgetSnapshot:
    revisions: object
    get_latest_revision: object
    clock: object
    ids: object

    def execute(self, workspace_id, snapshot: PericialBudget, expected_revision: int | None):
        if type(snapshot) is not PericialBudget or snapshot.workspace_id != str(workspace_id):
            raise ValueError("Budget Snapshot workspace is invalid")
        if expected_revision is None:
            if snapshot.revision != 1:
                raise ValueError("initial Budget Snapshot revision is invalid")
        else:
            if type(expected_revision) is not int or expected_revision < 1:
                raise ValueError("Budget Snapshot expected revision is invalid")
            record = self.get_latest_revision.execute(workspace_id, BUDGET_SNAPSHOT_ARTIFACT_KIND, BUDGET_SNAPSHOT_ARTIFACT_ID)
            if record.revision != expected_revision:
                raise RepositoryConflict("expected Budget Snapshot revision is not latest")
            predecessor = validated_budget_snapshot_from_mapping(_payload(record.payload))
            if predecessor.status is FinancialStatus.CLOSED:
                raise ValueError("closed Budget Snapshot is immutable")
            if snapshot.budget_id != predecessor.budget_id or snapshot.revision != predecessor.revision + 1:
                raise ValueError("Budget Snapshot identity or revision changed")
            if snapshot.process_id != predecessor.process_id or snapshot.appointment_id != predecessor.appointment_id:
                raise ValueError("Budget Snapshot process links are immutable")
            if not _preserves_history(predecessor, snapshot):
                raise ValueError("Budget Snapshot history cannot be rewritten")
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Budget Snapshot clock requires timezone")
        return self.revisions.append_if_latest(
            workspace_id=workspace_id, artifact_kind=BUDGET_SNAPSHOT_ARTIFACT_KIND,
            artifact_id=BUDGET_SNAPSHOT_ARTIFACT_ID, revision_id=str(self.ids.new_uuid()),
            created_at=now.isoformat(), payload=budget_snapshot_to_validated_mapping(snapshot),
            expected_revision=expected_revision, expected_dependencies=(),
        )


@dataclass(frozen=True, slots=True)
class GetBudgetSnapshot:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, BUDGET_SNAPSHOT_ARTIFACT_KIND, BUDGET_SNAPSHOT_ARTIFACT_ID)
        return record, validated_budget_snapshot_from_mapping(_payload(record.payload))


@dataclass(frozen=True, slots=True)
class GetBudgetHistory:
    list_revisions: object

    def execute(self, workspace_id):
        records = self.list_revisions.execute(workspace_id, BUDGET_SNAPSHOT_ARTIFACT_KIND, BUDGET_SNAPSHOT_ARTIFACT_ID)
        return tuple((record, validated_budget_snapshot_from_mapping(_payload(record.payload))) for record in records)


@dataclass(frozen=True, slots=True)
class StartBudgetSnapshot:
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, process_id: str | None, appointment_id: str | None):
        if process_id is not None or appointment_id is not None:
            raise ValueError("Budget Snapshot links require a workspace authority resolver")
        value = PericialBudget(
            schema_version="1.0.0", budget_id=f"BUDGET-{str(self.ids.new_uuid()).upper()}", revision=1,
            workspace_id=str(workspace_id), process_id=process_id, appointment_id=appointment_id,
            items=(), effort_estimates=(), travel_estimates=(), third_party_estimates=(), expenses=(),
            proposals=(), proposal_revisions=(), court_approvals=(), payments=(), status=FinancialStatus.DRAFT,
        )
        return self.save_snapshot.execute(workspace_id, value, None), value


@dataclass(frozen=True, slots=True)
class AddBudgetItem:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, category: str, description: str, quantity: str, unit_amount: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        item = BudgetItem(
            f"ITEM-{str(self.ids.new_uuid()).upper()}", CostCategory(category), description,
            quantity, unit_amount, _derived_total(quantity, unit_amount),
        )
        value = replace(predecessor, revision=predecessor.revision + 1, items=(*predecessor.items, item))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class AddProfessionalEffortEstimate:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, professional_id: str, estimated_hours: str, hourly_amount: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        estimate = ProfessionalEffortEstimate(
            f"EFFORT-{str(self.ids.new_uuid()).upper()}", professional_id, estimated_hours,
            hourly_amount, _derived_total(estimated_hours, hourly_amount),
        )
        value = replace(predecessor, revision=predecessor.revision + 1, effort_estimates=(*predecessor.effort_estimates, estimate))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class AddTravelEstimate:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, distance_km: str, amount_per_km: str, description: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        estimate = TravelEstimate(
            f"TRAVEL-{str(self.ids.new_uuid()).upper()}", distance_km, amount_per_km,
            _derived_total(distance_km, amount_per_km), description,
        )
        value = replace(predecessor, revision=predecessor.revision + 1, travel_estimates=(*predecessor.travel_estimates, estimate))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class AddThirdPartyEstimate:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, provider_description: str, amount: str, currency: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        estimate = ThirdPartyEstimate(
            f"THIRD-{str(self.ids.new_uuid()).upper()}", provider_description, amount, currency,
        )
        value = replace(predecessor, revision=predecessor.revision + 1, third_party_estimates=(*predecessor.third_party_estimates, estimate))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class AddFeeProposal:
    get_snapshot: object
    save_snapshot: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, amount: str, currency: str, rationale: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision: raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        revision = len(predecessor.proposals) + 1
        proposal_id = f"PROPOSAL-{str(self.ids.new_uuid()).upper()}"
        revision_id = f"PROPOSAL-REVISION-{str(self.ids.new_uuid()).upper()}"
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None: raise ValueError("Budget proposal clock requires timezone")
        proposal = FeeProposal(proposal_id, revision, amount, currency, now.isoformat(), rationale)
        prior = predecessor.proposal_revisions[-1].revision_id if predecessor.proposal_revisions else None
        trail = ProposalRevision(revision_id, proposal_id, revision, prior, rationale, now.isoformat())
        proposals = (*predecessor.proposals, proposal)
        value = replace(predecessor, revision=predecessor.revision + 1, proposals=proposals, proposal_revisions=(*predecessor.proposal_revisions, trail), status=derive_financial_status(proposals, predecessor.court_approvals, predecessor.payments))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class RecordCourtApproval:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, external_court_decision_reference: str, amount: str, currency: str, decided_on: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision: raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        approval = CourtApprovedAmount(f"APPROVAL-{str(self.ids.new_uuid()).upper()}", external_court_decision_reference, amount, currency, decided_on)
        approvals = (*predecessor.court_approvals, approval)
        value = replace(predecessor, revision=predecessor.revision + 1, court_approvals=approvals, status=derive_financial_status(predecessor.proposals, approvals, predecessor.payments))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class RecordExpense:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, category: str, amount: str, currency: str, incurred_on: str, description: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision: raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        expense = Expense(f"EXPENSE-{str(self.ids.new_uuid()).upper()}", CostCategory(category), amount, currency, incurred_on, description)
        value = replace(predecessor, revision=predecessor.revision + 1, expenses=(*predecessor.expenses, expense))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class RecordPayment:
    get_snapshot: object
    save_snapshot: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, amount: str, currency: str, received_on: str, reference: str):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision: raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        payment = ReceivedPayment(f"PAYMENT-{str(self.ids.new_uuid()).upper()}", amount, currency, received_on, reference)
        payments = (*predecessor.payments, payment)
        value = replace(predecessor, revision=predecessor.revision + 1, payments=payments, status=derive_financial_status(predecessor.proposals, predecessor.court_approvals, payments))
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value


@dataclass(frozen=True, slots=True)
class CloseBudgetSnapshot:
    get_snapshot: object
    save_snapshot: object

    def execute(self, workspace_id, *, expected_revision: int):
        record, predecessor = self.get_snapshot.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Budget Snapshot revision is not latest")
        if predecessor.status is not FinancialStatus.RECEIVED:
            raise ValueError("only a fully received Budget Snapshot can be closed")
        value = replace(predecessor, revision=predecessor.revision + 1, status=FinancialStatus.CLOSED)
        return self.save_snapshot.execute(workspace_id, value, expected_revision), value
