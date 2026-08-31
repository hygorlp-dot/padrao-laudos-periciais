from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.budget_foundation import (
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
)


def budget() -> PericialBudget:
    item = BudgetItem("ITEM-1", CostCategory.PROFESSIONAL_HOURS, "Análise técnica", "10.00", "150.00", "1500.00")
    proposal = FeeProposal("PROPOSAL-1", 1, "2500.00", "BRL", "2026-08-31T12:00:00+00:00", "Orçamento inicial")
    return PericialBudget(
        schema_version="1.0.0", budget_id="BUDGET-1", revision=1,
        workspace_id="11111111-1111-4111-8111-111111111111",
        process_id="PROCESS-1", appointment_id="APPOINTMENT-1",
        items=(item,), effort_estimates=(ProfessionalEffortEstimate("EFFORT-1", "EXPERT-1", "8.00", "150.00", "1200.00"),),
        travel_estimates=(TravelEstimate("TRAVEL-1", "40.00", "1.50", "60.00", "Visita sintética"),),
        third_party_estimates=(ThirdPartyEstimate("THIRD-1", "Laboratório sintético", "500.00", "BRL"),),
        expenses=(Expense("EXPENSE-1", CostCategory.EQUIPMENT, "100.00", "BRL", "2026-08-31", "Equipamento sintético"),),
        proposals=(proposal,), proposal_revisions=(ProposalRevision("REVISION-1", "PROPOSAL-1", 1, None, "Emissão inicial", "2026-08-31T12:00:00+00:00"),),
        court_approvals=(CourtApprovedAmount("APPROVAL-1", "DECISION-1", "2200.00", "BRL", "2026-09-01"),),
        payments=(ReceivedPayment("PAYMENT-1", "1000.00", "BRL", "2026-09-02", "Depósito judicial sintético"),),
        status=FinancialStatus.PARTIALLY_RECEIVED,
    )


def test_budget_snapshot_round_trip_and_derived_outstanding_are_exact() -> None:
    value = budget()
    assert value.outstanding.amount == "1200.00"
    assert value.proposed_total == "2500.00"
    assert value.court_approved_total == "2200.00"
    assert budget_snapshot_from_mapping(budget_snapshot_to_mapping(value)) == value


def test_budget_rejects_float_money_negative_values_and_technical_contamination() -> None:
    payload = budget_snapshot_to_mapping(budget())
    payload["items"][0]["unit_amount"] = 150.0
    with pytest.raises(ValueError):
        budget_snapshot_from_mapping(payload)
    with pytest.raises(ValueError):
        replace(budget(), expenses=(replace(budget().expenses[0], amount="-1.00"),))
    payload = budget_snapshot_to_mapping(budget())
    payload["technical_confidence"] = "HIGH"
    with pytest.raises(ValueError, match="fields"):
        budget_snapshot_from_mapping(payload)


def test_proposal_court_approval_and_payment_are_distinct_authorities() -> None:
    value = budget()
    assert value.proposals[0].amount != value.court_approvals[0].amount
    assert value.payments[0].amount != value.outstanding.amount
    with pytest.raises(ValueError, match="currency"):
        replace(value, payments=(replace(value.payments[0], currency="USD"),))


def test_proposal_revision_history_is_linear_and_append_only_by_identity() -> None:
    value = budget()
    duplicate = replace(value.proposal_revisions[0], revision_id="REVISION-2")
    with pytest.raises(ValueError, match="revision sequence"):
        replace(value, proposal_revisions=(value.proposal_revisions[0], duplicate))
    with pytest.raises(ValueError, match="identity"):
        replace(value, proposals=(value.proposals[0], value.proposals[0]))


def test_canonical_synthetic_fixture_matches_schema_and_domain() -> None:
    root = Path(__file__).parents[1]
    payload = json.loads((root / "tests/fixtures/budget-snapshot-v1.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "schemas/budget-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    assert budget_snapshot_to_mapping(budget_snapshot_from_mapping(payload)) == payload
