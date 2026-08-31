# Budget Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a workspace-isolated, append-only pericial financial domain whose proposals, approvals, payments, expenses, and balances cannot alter or imply technical merit.

**Architecture:** Add a strict canonical `PericialBudget` snapshot and JSON Schema, then expose it through application services backed by the existing artifact-revision repository. The Local API, OpenAPI contract, Product Bridge, and a progressively disclosed workspace view consume only the financial snapshot; no technical snapshot is an input to budget calculations or state transitions.

**Tech Stack:** Python 3.14 dataclasses/Decimal, JSON Schema, SQLite artifact revisions, local HTTP API, React/TypeScript, Vitest, Pytest.

## Global Constraints

- `FINANCIAL_DOMAIN != TECHNICAL_MERIT`.
- `BUDGET_PROPOSAL != COURT_APPROVED_FEES`.
- Append-only proposal, court-decision, expense, payment, and actual-cost history.
- Synthetic fixtures only; `PRIVATE_EGRESS = FALSE`.
- No AI Automation Foundation work and no external payment/billing integration.
- One mutation owner for the Budget Snapshot boundary.

---

### Task 1: Canonical financial graph

**Files:**
- Create: `scripts/backend_contract/budget_foundation.py`
- Create: `schemas/budget-snapshot-v1.schema.json`
- Create: `tests/fixtures/budget-snapshot-v1.json`
- Create: `tests/test_budget_foundation_v1.py`

**Interfaces:**
- Produces `PericialBudget`, `BudgetItem`, `ProfessionalEffortEstimate`, `TravelEstimate`, `ThirdPartyEstimate`, `Expense`, `FeeProposal`, `ProposalRevision`, `CourtApprovedAmount`, `ReceivedPayment`, `OutstandingAmount`, `FinancialStatus`, strict mapping parsers, and deterministic balance calculation.

- [ ] Write failing tests for strict round-trip, Decimal-safe money, proposal/approval distinction, financial/technical field rejection, revision chronology, and derived outstanding amount.
- [ ] Run `python -m pytest tests/test_budget_foundation_v1.py -q` and confirm RED because the module does not exist.
- [ ] Implement immutable value objects and aggregate invariants; reject floats, negative money, duplicate identities, ambiguous chronology, cross-workspace links, and any technical confidence/finding fields.
- [ ] Add strict schema and synthetic fixture; confirm fixture/schema/domain equality.
- [ ] Run focused tests and Ruff; commit `feat(stage9): add canonical budget graph`.

### Task 2: Append-only application authority and reopen

**Files:**
- Create: `scripts/backend_contract/application/budget_foundation.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Test: `tests/test_budget_foundation_v1.py`
- Test: `tests/test_local_persistence_v1.py`

**Interfaces:**
- Produces `GetBudgetSnapshot`, `ListBudgetHistory`, `SaveBudgetSnapshot`, and command services for proposals, court approvals, expenses, payments, and status changes using optimistic expected revisions.

- [ ] Write RED tests proving missing snapshot, append-only revisions, stale-write rejection, exact reopen, workspace isolation, proposal supersession, independent court approval, and payment-derived outstanding amount.
- [ ] Implement validated persistence through the existing artifact revision repository; no technical repository/service may be injected.
- [ ] Add adversarial tests showing budget changes leave technical mappings byte-identical and technical snapshots cannot be accepted as budget inputs.
- [ ] Run focused persistence/application tests; commit `feat(stage9): persist append-only budget history`.

### Task 3: Local API and canonical contract

**Files:**
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/product_bridge/transport.py`
- Modify: `scripts/backend_contract/product_bridge/server.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `tests/test_api_contract_foundation_v1.py`
- Modify: `tests/test_local_api_v1.py`
- Modify: `tests/test_product_bridge_v1.py`

**Interfaces:**
- Adds GET/POST `/v1/workspaces/{workspace_id}/budget-snapshot`, GET `/history`, and explicit POST commands for proposals, court approvals, expenses, payments, and status transitions.

- [ ] Write RED route/DTO/allowlist tests, including unknown fields, float money, wrong workspace, stale revision, and technical-field contamination.
- [ ] Implement application-only DTO validation and exact response envelopes.
- [ ] Extend OpenAPI exact-path inventory and Product Bridge allowlists without adding external origins or document upload capability.
- [ ] Run API/bridge/boundary tests; commit `feat(stage9): expose budget contract locally`.

### Task 4: Professional budget workspace

**Files:**
- Create: `frontend/src/data/budgetSnapshot.ts`
- Create: `frontend/src/workspaces/BudgetFoundationView.tsx`
- Create: `frontend/src/workspaces/BudgetFoundationView.test.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/routes/routeCatalog.ts`
- Modify: `frontend/src/styles/shell.css`
- Modify: frontend network-boundary inventories in Python tests.

**Interfaces:**
- Provides a financial-only workspace view with totals, proposal versus court approval, received/outstanding amounts, revision history, and explicit forms for financial commands.

- [ ] Write RED Vitest cases for empty/reopen states, proposal/approval visual separation, history, errors, and absence of technical-confidence language.
- [ ] Implement typed same-origin data access and progressively disclosed UI; use no decorative animation and preserve reduced-motion behavior.
- [ ] Add route/navigation and responsive styling following existing workspace patterns.
- [ ] Run typecheck, lint, Vitest, and build; commit `feat(stage9): add budget workspace`.

### Task 5: Adversarial matrix, freeze, review, and delivery

**Files:**
- Modify only tests/docs required by demonstrated findings.

**Interfaces:**
- Produces terminal evidence for all Stage 9 acceptance criteria.

- [ ] Run `change_impact` for every changed boundary and focused shards during RED/GREEN.
- [ ] Execute sibling-defect sweep for monetary precision, revision identity, workspace leakage, proposal/approval conflation, overpayment, negative values, and technical contamination.
- [ ] Run the pre-terminal adversarial matrix and read-only shadow systemic review; repair every material finding with a new RED test.
- [ ] Freeze HEAD, run frontend assurance, one full Pytest regression, and one `python -m scripts.quality.verify_core --full`.
- [ ] Run independent adversarial, systemic, and security reviews concurrently on the exact frozen HEAD; require `P0=0` and `P1=0`.
- [ ] Push, open a PR closing Issue #160, await protected CI, merge normally, run focused post-main assurance, and stop before AI Automation Foundation.

## Self-review

- Spec coverage: every required entity is in Task 1; separation, revisions, approval distinction, reopen, isolation, and privacy have explicit tests and gates.
- Placeholder scan: no deferred implementation placeholders or unspecified error-handling steps.
- Type consistency: every downstream layer consumes `PericialBudget` and application commands; technical snapshots are never an input.
