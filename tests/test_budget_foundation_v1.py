from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.application.budget_foundation import (
    AddFeeProposal,
    GetBudgetHistory,
    GetBudgetSnapshot,
    RecordCourtApproval,
    RecordExpense,
    RecordPayment,
    SaveBudgetSnapshot,
    StartBudgetSnapshot,
)
from scripts.backend_contract.application.ports import RepositoryConflict

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
    with pytest.raises(ValueError, match="proposal trail"):
        replace(value, proposal_revisions=())
    earlier = replace(value.proposals[0], proposed_at="2026-08-30T12:00:00+00:00")
    later = replace(value.proposals[0], proposal_id="PROPOSAL-2", revision=2, proposed_at="2026-08-29T12:00:00+00:00")
    later_trail = ProposalRevision("REVISION-2", "PROPOSAL-2", 2, "REVISION-1", "Revisão", "2026-08-29T12:00:00+00:00")
    with pytest.raises(ValueError, match="chronology"):
        replace(value, proposals=(earlier, later), proposal_revisions=(*value.proposal_revisions, later_trail))


def test_financial_status_cannot_claim_a_lifecycle_state_the_ledger_does_not_support() -> None:
    value = budget()
    with pytest.raises(ValueError, match="status"):
        replace(value, status=FinancialStatus.RECEIVED)
    with pytest.raises(ValueError, match="status"):
        replace(value, status=FinancialStatus.DRAFT)
    fully_received = replace(
        value,
        payments=(replace(value.payments[0], amount="2200.00"),),
        status=FinancialStatus.RECEIVED,
    )
    assert fully_received.outstanding.amount == "0.00"
    assert replace(fully_received, status=FinancialStatus.CLOSED).status is FinancialStatus.CLOSED


def test_payment_requires_positive_value_prior_approval_and_authority_chronology() -> None:
    with pytest.raises(ValueError, match="positive"):
        replace(budget().payments[0], amount="0.00")
    with pytest.raises(ValueError, match="payment authority chronology"):
        replace(budget(), court_approvals=())
    with pytest.raises(ValueError, match="payment authority chronology"):
        replace(budget(), payments=(replace(budget().payments[0], received_on="2026-08-31"),))
    with pytest.raises(ValueError, match="court approval chronology"):
        replace(budget(), court_approvals=(*budget().court_approvals, CourtApprovedAmount("APPROVAL-2", "DECISION-2", "2300.00", "BRL", "2026-08-31")))


def test_canonical_synthetic_fixture_matches_schema_and_domain() -> None:
    root = Path(__file__).parents[1]
    payload = json.loads((root / "tests/fixtures/budget-snapshot-v1.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "schemas/budget-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    assert budget_snapshot_to_mapping(budget_snapshot_from_mapping(payload)) == payload


def test_application_persists_reopens_and_lists_append_only_budget_history() -> None:
    class Revisions:
        def __init__(self): self.calls = []
        def append_if_latest(self, **kwargs): self.calls.append(kwargs); return type("Record", (), {"revision": len(self.calls), "payload": kwargs["payload"]})()
    class Latest:
        def __init__(self, revisions): self.revisions = revisions
        def execute(self, *_args):
            if not self.revisions.calls: raise RuntimeError("missing")
            call = self.revisions.calls[-1]
            return type("Record", (), {"revision": len(self.revisions.calls), "payload": call["payload"]})()
    class History:
        def __init__(self, revisions): self.revisions = revisions
        def execute(self, *_args): return tuple(type("Record", (), {"revision": index, "payload": call["payload"]})() for index, call in enumerate(self.revisions.calls, 1))
    class Clock:
        def now(self): return datetime.fromisoformat("2026-08-31T12:00:00+00:00")
    class Ids:
        def new_uuid(self): return "22222222-2222-4222-8222-222222222222"

    revisions = Revisions(); latest = Latest(revisions)
    save = SaveBudgetSnapshot(revisions, latest, Clock(), Ids())
    first = save.execute(budget().workspace_id, budget(), None)
    second_budget = replace(
        budget(),
        revision=2,
        expenses=(*budget().expenses, Expense("EXPENSE-2", CostCategory.TRAVEL, "50.00", "BRL", "2026-09-03", "Deslocamento sintético")),
    )
    second = save.execute(budget().workspace_id, second_budget, 1)
    reopened_record, reopened = GetBudgetSnapshot(latest).execute(budget().workspace_id)
    history = GetBudgetHistory(History(revisions)).execute(budget().workspace_id)
    assert (first.revision, second.revision, reopened_record.revision) == (1, 2, 2)
    assert reopened == second_budget
    assert tuple(item.revision for item, _ in history) == (1, 2)
    assert all(call["expected_dependencies"] == () for call in revisions.calls)


def test_application_rejects_workspace_leak_stale_write_and_history_rewrite() -> None:
    class Latest:
        def execute(self, *_args): return type("Record", (), {"revision": 2, "payload": budget_snapshot_to_mapping(replace(budget(), revision=2))})()
    service = SaveBudgetSnapshot(object(), Latest(), object(), object())
    with pytest.raises(ValueError, match="workspace"):
        service.execute("22222222-2222-4222-8222-222222222222", budget(), None)
    with pytest.raises(RepositoryConflict):
        service.execute(budget().workspace_id, replace(budget(), revision=3), 1)
    with pytest.raises(ValueError, match="history"):
        changed = replace(budget(), revision=3, expenses=(replace(budget().expenses[0], description="Rewritten"),))
        service.execute(budget().workspace_id, changed, 2)


def test_closed_budget_is_terminal_at_the_repository_boundary() -> None:
    closed = replace(budget(), revision=2, payments=(replace(budget().payments[0], amount="2200.00"),), status=FinancialStatus.CLOSED)
    class Latest:
        def execute(self, *_args): return type("Record", (), {"revision": 2, "payload": budget_snapshot_to_mapping(closed)})()
    service = SaveBudgetSnapshot(object(), Latest(), object(), object())
    with pytest.raises(ValueError, match="closed"):
        service.execute(closed.workspace_id, replace(closed, revision=3), 2)


def test_financial_commands_create_distinct_append_only_authorities() -> None:
    class Get:
        def __init__(self, value): self.value = value
        def execute(self, _workspace): return type("Record", (), {"revision": self.value.revision})(), self.value
    class Save:
        def __init__(self): self.values = []
        def execute(self, _workspace, value, expected): self.values.append((value, expected)); return type("Record", (), {"revision": value.revision})()
    class Clock:
        def now(self): return datetime.fromisoformat("2026-08-31T12:00:00+00:00")
    class Ids:
        index = 0
        def new_uuid(self): self.index += 1; return f"00000000-0000-4000-8000-{self.index:012d}"

    empty = replace(budget(), revision=1, proposals=(), proposal_revisions=(), court_approvals=(), payments=(), expenses=(), status=FinancialStatus.DRAFT)
    save = Save(); ids = Ids(); clock = Clock()
    proposal_record, proposal = AddFeeProposal(Get(empty), save, clock, ids).execute(empty.workspace_id, expected_revision=1, amount="3000.00", currency="BRL", rationale="Proposta inicial")
    approval_record, approved = RecordCourtApproval(Get(proposal), save, ids).execute(empty.workspace_id, expected_revision=2, court_decision_id="DECISION-2", amount="2500.00", currency="BRL", decided_on="2026-09-01")
    expense_record, expensed = RecordExpense(Get(approved), save, ids).execute(empty.workspace_id, expected_revision=3, category="TRAVEL", amount="100.00", currency="BRL", incurred_on="2026-09-02", description="Deslocamento")
    payment_record, paid = RecordPayment(Get(expensed), save, ids).execute(empty.workspace_id, expected_revision=4, amount="1000.00", currency="BRL", received_on="2026-09-03", reference="Depósito")
    assert (proposal_record.revision, approval_record.revision, expense_record.revision, payment_record.revision) == (2, 3, 4, 5)
    assert proposal.proposed_total == "3000.00"
    assert approved.court_approved_total == "2500.00"
    assert paid.outstanding.amount == "1500.00"
    assert [expected for _, expected in save.values] == [1, 2, 3, 4]


def test_financial_commands_derive_status_after_final_payment_and_later_revisions() -> None:
    class Get:
        def __init__(self, value): self.value = value
        def execute(self, _workspace): return type("Record", (), {"revision": self.value.revision})(), self.value
    class Save:
        def execute(self, _workspace, value, _expected): return type("Record", (), {"revision": value.revision})()
    class Clock:
        def now(self): return datetime.fromisoformat("2026-09-04T12:00:00+00:00")
    class Ids:
        index = 0
        def new_uuid(self): self.index += 1; return f"00000000-0000-4000-8000-{self.index:012d}"

    ids = Ids(); save = Save(); value = budget()
    _, paid = RecordPayment(Get(value), save, ids).execute(value.workspace_id, expected_revision=1, amount="1200.00", currency="BRL", received_on="2026-09-04", reference="Quitação")
    assert paid.status is FinancialStatus.RECEIVED
    _, revised = AddFeeProposal(Get(paid), save, Clock(), ids).execute(value.workspace_id, expected_revision=2, amount="2700.00", currency="BRL", rationale="Proposta suplementar")
    assert revised.status is FinancialStatus.RECEIVED
    _, adjusted = RecordCourtApproval(Get(revised), save, ids).execute(value.workspace_id, expected_revision=3, court_decision_id="DECISION-2", amount="2700.00", currency="BRL", decided_on="2026-09-05")
    assert adjusted.status is FinancialStatus.PARTIALLY_RECEIVED
    assert adjusted.outstanding.amount == "500.00"


def test_start_budget_creates_empty_financial_snapshot_without_technical_authority() -> None:
    class Save:
        def execute(self, _workspace, value, expected): assert expected is None; return type("Record", (), {"revision": 1})()
    class Ids:
        def new_uuid(self): return "22222222-2222-4222-8222-222222222222"
    service = StartBudgetSnapshot(Save(), Ids())
    with pytest.raises(ValueError, match="resolver"):
        service.execute(budget().workspace_id, process_id="PROCESS-1", appointment_id=None)
    record, value = service.execute(budget().workspace_id, process_id=None, appointment_id=None)
    assert record.revision == 1
    assert value.status is FinancialStatus.DRAFT
    assert value.proposals == value.court_approvals == value.payments == ()
