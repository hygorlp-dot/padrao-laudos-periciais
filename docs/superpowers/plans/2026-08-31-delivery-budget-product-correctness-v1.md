# Delivery and Budget Product Correctness V1 Implementation Plan

> Scope amendment (human decision): local final PDF is deferred by the frozen
> protected trust boundary. Production delivery renders the authoritative bound
> DOCX/DOCM only; the diagnostic PDF and future-converter fidelity oracles can
> never satisfy professional finalization. Issue #169 records the deferred
> process capability and is closed as not planned.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make final PDF delivery faithful to the bound Word artifact and expose the complete authorized Stage 9 financial workflow with truthful court-reference semantics and a read-only CLOSED state.

**Architecture:** Delivery will bind one approved report/template into DOCX/DOCM first, create a macro-free conversion copy, and pass those exact bytes to a local Office converter; no independent text renderer may create a final PDF. Budget additions remain explicit append-only application commands. Court authority uses an explicitly external/raw reference because no canonical JudicialDecision resolver currently exists. The frontend only invokes those commands and omits every mutation affordance after closure.

**Tech Stack:** Python 3.13 dataclasses/application services, local Word/LibreOffice conversion, OOXML/PDF validation, JSON Schema/OpenAPI, React 19/TypeScript/Vitest.

## Global Constraints

- Base SHA is `5e3d1fd1ba3f3f28135fb9e3fe88cd4369cb5bd1`; Issue is #168 and branch is `feat/168-delivery-budget-product-correctness`.
- `PRIVATE_EGRESS = FALSE`; conversion is local only.
- `TEXT_ONLY_DIAGNOSTIC_PDF != FINAL_PROFESSIONAL_PDF`.
- No arbitrary raw `BudgetSnapshot` editing; all writes are explicit commands with server-owned identity and derived totals.
- Preserve append-only delivery and financial histories, stale propagation, workspace isolation, and backend CLOSED immutability.
- Do not implement Stage 10, a new product stage, productization redesign, trust/governance/timing work, PJe submission, cloud conversion, or external billing.
- Run focused RED/GREEN checks during implementation and one terminal full assurance only on the frozen final HEAD.

---

### Task 1: Faithful final PDF from the bound Word artifact

**Files:**
- Modify: `tests/test_delivery_foundation_v1.py`
- Modify: `scripts/backend_contract/delivery_renderer.py`
- Modify: `scripts/backend_contract/application/delivery_foundation.py`
- Create: `scripts/backend_contract/infrastructure/office_pdf.py`
- Modify: `scripts/backend_contract/local_api/composition.py`

**Interfaces:**
- Consumes: `render_word_candidate(...).output_bytes` and `safe_pdf_conversion_copy(content, output_format)`.
- Produces: `LocalOfficePdfConverter.convert(word_bytes: bytes, source_format: str) -> bytes`; `RenderDeliveryPackage.pdf_converter`.

- [ ] **Step 1: Write failing delivery tests** proving that the converter receives the exact bound Word-derived conversion copy; a PDF from another report/template is rejected; the old text-only candidate is not accepted as final; converter absence fails closed; and the resulting PDF preserves literal `m² ° µ ≤ ≥`, report content, pages, table/image resources, headers/footers, and numbering declared by the synthetic template.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_delivery_foundation_v1.py` and confirm failures occur because final PDF still bypasses Word and lacks a converter boundary.
- [ ] **Step 3: Implement the minimum repair:** classify `render_pdf_candidate` as diagnostic-only or remove it from finalization; convert a sanitized exact Word copy via an injected local converter; support Microsoft Word COM on Windows and headless LibreOffice when present; use an isolated temporary directory; deny network/external OOXML relationships; validate PDF bytes and reopen them before persistence.
- [ ] **Step 4: Run** `python -m pytest -q tests/test_delivery_foundation_v1.py` and require PASS.
- [ ] **Step 5: Run an actual local synthetic Word-to-PDF probe** when Word/LibreOffice is available, render the PDF pages with Poppler, inspect the PNGs, and verify text/page/resource invariants without committing generated artifacts.
- [ ] **Step 6: Commit** `fix: bind final PDF to approved Word artifact`.

### Task 2: Complete append-only Budget commands

**Files:**
- Modify: `tests/test_budget_foundation_v1.py`
- Modify: `tests/test_local_api_v1.py`
- Modify: `tests/test_api_contract_foundation_v1.py`
- Modify: `scripts/backend_contract/application/budget_foundation.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`

**Interfaces:**
- Produces explicit commands `AddBudgetItem`, `AddProfessionalEffortEstimate`, `AddTravelEstimate`, and `AddThirdPartyEstimate` with `expected_revision` and server-owned IDs.
- Each command appends one canonical domain value and delegates totals/status validation to `PericialBudget`.

- [ ] **Step 1: Write failing application/API tests** for professional hours/team effort, travel, equipment, laboratory, third-party, administrative costs, and actual expenses; assert server-owned IDs, exact Decimal-string arithmetic, stale revision conflict, cross-workspace rejection, no raw snapshot endpoint, and immutable earlier ledger entries.
- [ ] **Step 2: Run** `python -m pytest -q tests/test_budget_foundation_v1.py tests/test_local_api_v1.py tests/test_api_contract_foundation_v1.py` and confirm the new command routes are missing.
- [ ] **Step 3: Implement the four append commands**, register them in composition and strict DTO routes, and document the command schemas in OpenAPI. Reuse existing expense/proposal/payment commands for equipment/laboratory/administrative actual costs and proposal revisions.
- [ ] **Step 4: Run the focused command/API tests** and require PASS.
- [ ] **Step 5: Commit** `feat: expose complete authorized budget commands`.

### Task 3: Truthful external court-decision reference

**Files:**
- Modify: `tests/test_budget_foundation_v1.py`
- Modify: `tests/test_local_api_v1.py`
- Modify: `schemas/budget-snapshot-v1.schema.json`
- Modify: `tests/fixtures/budget-snapshot-v1.json`
- Modify: `scripts/backend_contract/budget_foundation.py`
- Modify: `scripts/backend_contract/application/budget_foundation.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`

**Interfaces:**
- Replaces canonical-looking `court_decision_id` authority with `external_court_decision_reference`, a nonempty human-entered reference explicitly classified as external/raw.
- Legacy persisted input is migrated explicitly at deserialization and canonical output always uses the truthful field; no value is asserted to identify a canonical JudicialDecision.

- [ ] **Step 1: Write failing tests** that reject `court_decision_id` on new command payloads, accept an explicit external reference, preserve it append-only, and prevent a same-looking string from being treated as canonical judicial authority.
- [ ] **Step 2: Run the focused Budget/schema/API tests** and confirm RED on the old field semantics.
- [ ] **Step 3: Implement the field rename and explicit compatibility read**, update schema/fixture/OpenAPI, and keep workspace/revision checks at the command boundary.
- [ ] **Step 4: Run the focused tests** and require PASS.
- [ ] **Step 5: Commit** `fix: make court decision reference authority explicit`.

### Task 4: Complete Budget UI and CLOSED read-only state

**Files:**
- Modify: `frontend/src/data/budgetSnapshot.ts`
- Modify: `frontend/src/workspaces/BudgetFoundationView.tsx`
- Modify: `frontend/src/workspaces/BudgetFoundationView.test.tsx`
- Modify: `frontend/src/styles.css` only if existing layout classes cannot express the new static history sections.

**Interfaces:**
- Consumes the explicit command endpoints from Tasks 2-3.
- Produces no domain calculations except exact display formatting; server remains monetary/status authority.

- [ ] **Step 1: Write failing Vitest tests** for every reachable Budget concept and for CLOSED: no proposal/approval/expense/payment/close controls, while balances, expenses, proposals/revisions, approvals, payments, and full revision history remain visible.
- [ ] **Step 2: Run** `npm.cmd test -- --run src/workspaces/BudgetFoundationView.test.tsx` and confirm RED because the UI lacks the new operations and still exposes CLOSED mutation forms.
- [ ] **Step 3: Extend typed API commands and UI forms/history sections.** Gate the entire command region with `status !== "CLOSED"`; render a static professional closed-state notice with no decorative motion; preserve keyboard/accessibility semantics and exact BigInt money display.
- [ ] **Step 4: Run the focused Vitest file** and require PASS; rapidly interact with forms to confirm no queued visual transitions and verify reduced-motion behavior remains unaffected.
- [ ] **Step 5: Commit** `feat: complete budget workflow and close UI read only`.

### Task 5: Adversarial matrix, frozen HEAD, review, and protected delivery

**Files:**
- Create or modify: `tests/test_delivery_budget_product_correctness_v1.py`
- Modify only causal production/tests if a mechanically reproduced sibling defect appears.

**Interfaces:**
- Consumes all B1-B4 boundaries and produces terminal evidence for Issue #168.

- [ ] **Step 1: Add adversarial tests** for lost PDF table/image/Unicode, wrong report revision/template, stale delivery, rewrite of proposal/approval/expense/payment, incorrect outstanding, cross-workspace financial reference, fake canonical court decision, post-CLOSED mutation, and CLOSED UI actions.
- [ ] **Step 2: Run the boundary-selected focused backend and frontend suites**, execute `python -m scripts.quality.change_impact <changed-files>`, and repair only mechanically reproduced causal/sibling defects.
- [ ] **Step 3: Freeze one exact HEAD and run once:** full pytest; frontend test/typecheck/lint/build; Ruff; `git diff --check`; and `python -m scripts.quality.verify_core --full`. Classify the historical 60-second timing debt separately without retry or threshold change.
- [ ] **Step 4: Dispatch independent PR review and systemic read-only audit on the exact frozen HEAD; adjudicate findings with `receiving-code-review`; invalidate reviews if HEAD changes.
- [ ] **Step 5: Push, open the PR with `Closes #168`, monitor protected CI, and merge normally only if all required checks and P0/P1 acceptance permit.
- [ ] **Step 6: On the exact merged main SHA, rerun the focused longitudinal acceptance oracle; record B1-B4, totals, CI, P0/P1/P2, private egress, and remaining debt; stop without PR-C or Stage 10.

## Self-Review

- Spec coverage: B1 fidelity/Unicode/Word binding, B2 all authorized Stage 9 concepts, B3 explicit authority, B4 CLOSED read-only, adversarial/terminal/post-main gates are each assigned.
- Placeholder scan: no deferred implementation placeholders; every production task has an explicit RED command, causal change, GREEN command, and commit boundary.
- Type consistency: `external_court_decision_reference` is used across domain, DTO, schema, OpenAPI, TypeScript, UI, and tests; converter consumes exact sanitized Word bytes and returns PDF bytes only.
