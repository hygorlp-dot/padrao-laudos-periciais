"""Canonical financial graph, deliberately independent from technical merit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import json
from typing import Any, TypeVar


class CostCategory(StrEnum):
    FEES = "FEES"
    PROFESSIONAL_HOURS = "PROFESSIONAL_HOURS"
    TRAVEL = "TRAVEL"
    ASSISTANTS = "ASSISTANTS"
    EQUIPMENT = "EQUIPMENT"
    TESTS_LABORATORY = "TESTS_LABORATORY"
    THIRD_PARTY_SERVICES = "THIRD_PARTY_SERVICES"
    ADMINISTRATIVE_COSTS = "ADMINISTRATIVE_COSTS"
    REVISIONS = "REVISIONS"
    EXPENSES = "EXPENSES"


class FinancialStatus(StrEnum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COURT_APPROVED = "COURT_APPROVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} is invalid")


def _money(value: object, name: str) -> Decimal:
    if type(value) is not str:
        raise ValueError(f"{name} must be a decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} is invalid") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent != -2:
        raise ValueError(f"{name} requires a non-negative two-decimal amount")
    return amount


def _day(value: object, name: str) -> None:
    _text(value, name)
    date.fromisoformat(value)  # type: ignore[arg-type]


def _instant(value: object, name: str) -> None:
    _text(value, name)
    parsed = datetime.fromisoformat(value)  # type: ignore[arg-type]
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} requires timezone")


@dataclass(frozen=True, slots=True)
class BudgetItem:
    item_id: str
    category: CostCategory
    description: str
    quantity: str
    unit_amount: str
    total_amount: str

    def __post_init__(self) -> None:
        _text(self.item_id, "item_id"); _text(self.description, "description")
        quantity = _money(self.quantity, "quantity")
        unit = _money(self.unit_amount, "unit_amount")
        total = _money(self.total_amount, "total_amount")
        if quantity * unit != total:
            raise ValueError("budget item total diverges")


@dataclass(frozen=True, slots=True)
class ProfessionalEffortEstimate:
    estimate_id: str
    professional_id: str
    estimated_hours: str
    hourly_amount: str
    total_amount: str

    def __post_init__(self) -> None:
        _text(self.estimate_id, "estimate_id"); _text(self.professional_id, "professional_id")
        if _money(self.estimated_hours, "estimated_hours") * _money(self.hourly_amount, "hourly_amount") != _money(self.total_amount, "total_amount"):
            raise ValueError("effort estimate total diverges")


@dataclass(frozen=True, slots=True)
class TravelEstimate:
    estimate_id: str
    distance_km: str
    amount_per_km: str
    total_amount: str
    description: str

    def __post_init__(self) -> None:
        _text(self.estimate_id, "estimate_id"); _text(self.description, "description")
        if _money(self.distance_km, "distance_km") * _money(self.amount_per_km, "amount_per_km") != _money(self.total_amount, "total_amount"):
            raise ValueError("travel estimate total diverges")


@dataclass(frozen=True, slots=True)
class ThirdPartyEstimate:
    estimate_id: str
    provider_description: str
    amount: str
    currency: str

    def __post_init__(self) -> None:
        _text(self.estimate_id, "estimate_id"); _text(self.provider_description, "provider_description"); _text(self.currency, "currency"); _money(self.amount, "amount")


@dataclass(frozen=True, slots=True)
class Expense:
    expense_id: str
    category: CostCategory
    amount: str
    currency: str
    incurred_on: str
    description: str

    def __post_init__(self) -> None:
        _text(self.expense_id, "expense_id"); _text(self.currency, "currency"); _text(self.description, "description"); _money(self.amount, "amount"); _day(self.incurred_on, "incurred_on")


@dataclass(frozen=True, slots=True)
class FeeProposal:
    proposal_id: str
    revision: int
    amount: str
    currency: str
    proposed_at: str
    rationale: str

    def __post_init__(self) -> None:
        _text(self.proposal_id, "proposal_id"); _text(self.currency, "currency"); _text(self.rationale, "rationale"); _money(self.amount, "amount"); _instant(self.proposed_at, "proposed_at")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("proposal revision is invalid")


@dataclass(frozen=True, slots=True)
class ProposalRevision:
    revision_id: str
    proposal_id: str
    revision: int
    supersedes_revision_id: str | None
    reason: str
    revised_at: str

    def __post_init__(self) -> None:
        _text(self.revision_id, "revision_id"); _text(self.proposal_id, "proposal_id"); _text(self.reason, "reason"); _instant(self.revised_at, "revised_at")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("proposal revision sequence is invalid")
        if self.supersedes_revision_id is not None:
            _text(self.supersedes_revision_id, "supersedes_revision_id")


@dataclass(frozen=True, slots=True)
class CourtApprovedAmount:
    approval_id: str
    court_decision_id: str
    amount: str
    currency: str
    decided_on: str

    def __post_init__(self) -> None:
        _text(self.approval_id, "approval_id"); _text(self.court_decision_id, "court_decision_id"); _text(self.currency, "currency"); _money(self.amount, "amount"); _day(self.decided_on, "decided_on")


@dataclass(frozen=True, slots=True)
class ReceivedPayment:
    payment_id: str
    amount: str
    currency: str
    received_on: str
    reference: str

    def __post_init__(self) -> None:
        _text(self.payment_id, "payment_id"); _text(self.currency, "currency"); _text(self.reference, "reference"); _money(self.amount, "amount"); _day(self.received_on, "received_on")


@dataclass(frozen=True, slots=True)
class OutstandingAmount:
    amount: str
    currency: str


def derive_financial_status(
    proposals: tuple[FeeProposal, ...],
    court_approvals: tuple[CourtApprovedAmount, ...],
    payments: tuple[ReceivedPayment, ...],
) -> FinancialStatus:
    if payments:
        approved = Decimal(court_approvals[-1].amount) if court_approvals else Decimal("0.00")
        received = sum((_money(item.amount, "payment") for item in payments), Decimal("0.00"))
        return FinancialStatus.RECEIVED if received == approved else FinancialStatus.PARTIALLY_RECEIVED
    if court_approvals:
        return FinancialStatus.COURT_APPROVED
    if proposals:
        return FinancialStatus.PROPOSED
    return FinancialStatus.DRAFT


@dataclass(frozen=True, slots=True)
class PericialBudget:
    schema_version: str
    budget_id: str
    revision: int
    workspace_id: str
    process_id: str | None
    appointment_id: str | None
    items: tuple[BudgetItem, ...]
    effort_estimates: tuple[ProfessionalEffortEstimate, ...]
    travel_estimates: tuple[TravelEstimate, ...]
    third_party_estimates: tuple[ThirdPartyEstimate, ...]
    expenses: tuple[Expense, ...]
    proposals: tuple[FeeProposal, ...]
    proposal_revisions: tuple[ProposalRevision, ...]
    court_approvals: tuple[CourtApprovedAmount, ...]
    payments: tuple[ReceivedPayment, ...]
    status: FinancialStatus

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0": raise ValueError("budget schema version is invalid")
        _text(self.budget_id, "budget_id"); _text(self.workspace_id, "workspace_id")
        if type(self.revision) is not int or self.revision < 1: raise ValueError("budget revision is invalid")
        for name in ("process_id", "appointment_id"):
            if getattr(self, name) is not None: _text(getattr(self, name), name)
        collections = (self.items, self.effort_estimates, self.travel_estimates, self.third_party_estimates, self.expenses, self.proposals, self.proposal_revisions, self.court_approvals, self.payments)
        if any(type(value) is not tuple for value in collections): raise ValueError("budget collections must be tuples")
        identities = [tuple(getattr(item, next(field.name for field in fields(item) if field.name.endswith("_id"))) for item in values) for values in collections]
        if any(len(value) != len(set(value)) for value in identities): raise ValueError("budget identity must be unique")
        currencies = {item.currency for values in (self.third_party_estimates, self.expenses, self.proposals, self.court_approvals, self.payments) for item in values}
        if len(currencies) > 1: raise ValueError("budget currency must be uniform")
        for index, item in enumerate(self.proposal_revisions, 1):
            if item.revision != index or (index == 1 and item.supersedes_revision_id is not None) or (index > 1 and item.supersedes_revision_id != self.proposal_revisions[index - 2].revision_id):
                raise ValueError("proposal revision sequence is invalid")
        if len(self.proposals) != len(self.proposal_revisions) or any(
            proposal.revision != index
            or trail.revision != index
            or proposal.proposal_id != trail.proposal_id
            for index, (proposal, trail) in enumerate(zip(self.proposals, self.proposal_revisions, strict=True), 1)
        ):
            raise ValueError("proposal trail diverges")
        proposal_instants = [datetime.fromisoformat(item.proposed_at) for item in self.proposals]
        revision_instants = [datetime.fromisoformat(item.revised_at) for item in self.proposal_revisions]
        if proposal_instants != sorted(proposal_instants) or revision_instants != sorted(revision_instants):
            raise ValueError("proposal chronology is invalid")
        if sum((_money(item.amount, "payment") for item in self.payments), Decimal("0.00")) > Decimal(self.court_approved_total):
            raise ValueError("received payments exceed court-approved amount")
        expected_status = derive_financial_status(self.proposals, self.court_approvals, self.payments)
        if self.status is FinancialStatus.CLOSED:
            if expected_status is not FinancialStatus.RECEIVED:
                raise ValueError("financial status is unsupported by ledger")
        elif self.status is not expected_status:
            raise ValueError("financial status is unsupported by ledger")

    @property
    def proposed_total(self) -> str:
        return self.proposals[-1].amount if self.proposals else "0.00"

    @property
    def court_approved_total(self) -> str:
        return self.court_approvals[-1].amount if self.court_approvals else "0.00"

    @property
    def outstanding(self) -> OutstandingAmount:
        currency = next((item.currency for values in (self.court_approvals, self.proposals) for item in reversed(values)), "BRL")
        received = sum((_money(item.amount, "payment") for item in self.payments), Decimal("0.00"))
        return OutstandingAmount(f"{Decimal(self.court_approved_total) - received:.2f}", currency)


T = TypeVar("T")


def _strict(cls: type[T], value: object, conversions: dict[str, Any] | None = None) -> T:
    if type(value) is not dict or set(value) != {field.name for field in fields(cls)}:
        raise ValueError(f"{cls.__name__} fields are invalid")
    data = dict(value)
    for name, converter in (conversions or {}).items(): data[name] = converter(data[name])
    return cls(**data)


def budget_snapshot_to_mapping(value: PericialBudget) -> dict[str, Any]:
    mapping = json.loads(json.dumps(asdict(value), ensure_ascii=False))
    mapping["outstanding"] = asdict(value.outstanding)
    return mapping


def budget_snapshot_from_mapping(value: object) -> PericialBudget:
    expected = {field.name for field in fields(PericialBudget)} | {"outstanding"}
    if type(value) is not dict or set(value) != expected: raise ValueError("PericialBudget fields are invalid")
    data = dict(value); supplied_outstanding = data.pop("outstanding")
    converters: dict[str, tuple[type, dict[str, Any]]] = {
        "items": (BudgetItem, {"category": CostCategory}), "effort_estimates": (ProfessionalEffortEstimate, {}),
        "travel_estimates": (TravelEstimate, {}), "third_party_estimates": (ThirdPartyEstimate, {}),
        "expenses": (Expense, {"category": CostCategory}), "proposals": (FeeProposal, {}),
        "proposal_revisions": (ProposalRevision, {}), "court_approvals": (CourtApprovedAmount, {}), "payments": (ReceivedPayment, {}),
    }
    for name, (cls, nested) in converters.items():
        if type(data[name]) is not list: raise ValueError(f"{name} is invalid")
        data[name] = tuple(_strict(cls, item, nested) for item in data[name])
    data["status"] = FinancialStatus(data["status"])
    result = _strict(PericialBudget, data)
    if supplied_outstanding != asdict(result.outstanding): raise ValueError("outstanding amount diverges")
    return result
