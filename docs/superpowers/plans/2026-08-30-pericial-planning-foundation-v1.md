# Pericial Planning Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: execute each task with strict RED/GREEN, then review the frozen terminal HEAD independently. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform a reviewed Case Analysis snapshot into a traceable plan proposal whose effective professional state changes only through explicit, append-only professional review.

**Architecture:** A source-neutral planning domain owns immutable proposal items, exact Case Analysis derivations, review history, coverage and readiness. The application boundary binds every derivation to the latest persisted Case Analysis, stores plans through the existing atomic artifact revision repository, and marks reopened plans stale when their upstream digest changes. The Local API/product bridge expose the canonical DTO, while React renders a professional planning route without field findings, answers or conclusions.

**Tech Stack:** Python 3.13 dataclasses, JSON Schema 2020-12, existing Application/SQLite/Local API layers, OpenAPI 3.1, React 19, TypeScript, Vite/Vitest, plain CSS.

## Global Constraints

- Issue #150; branch `feat/150-pericial-planning-foundation-v1`; base `0070e2bf2678b1bc609472a64bfab9fbb71c8ff6`.
- Synthetic fixtures only; never access `referencias/privadas/`; private egress remains denied.
- `PLAN_PROPOSAL != PROFESSIONAL_DECISION`; `METHOD_CANDIDATE != APPROVED_METHOD`.
- `QUESTION != METHOD`; `QUESTION != ANSWER`; `QUESTION != TECHNICAL_FINDING`.
- Every material proposal item carries a non-empty rationale, canonical Case Analysis item IDs and exact copied source provenance that is validated against the upstream snapshot.
- Proposal content and derivation are immutable after first persistence; `APPROVE`, `REJECT`, `MODIFY` and `DEFER` are append-only decisions with reviewer, reason, timestamp and revision.
- Technical-standard metadata remains separate from case facts; no copyrighted standard text is stored.
- No field capture, actual measurement/photo, technical finding, causality, liability, question answer or final report.
- No new dependency, trust mechanism, governance predecessor, verifier baseline or protected workflow change.
- UI is a productivity tool: static information hierarchy, no decorative motion, clear loading/empty/error/retry states, and existing reduced-motion behavior.

## Causal DAG and critical path

`latest Case Analysis identity/digest` → `derivation authority` → `canonical plan proposal + review ledger` → `honest readiness/coverage` → `atomic save/reopen + upstream stale` → `Local API/Bridge` → `professional planning route` → `adversarial matrix` → `terminal assurance/reviews/PR/post-main`.

The domain/application boundary is the critical path. Schema/fixture and UI presentation are parallel-safe only after the domain names and DTO are frozen. One mutation owner controls shared API, OpenAPI and routing files.

---

### Task 1: Canonical proposal, derivation and professional-review ledger

**Files:**
- Create: `scripts/backend_contract/pericial_planning.py`
- Create: `schemas/pericial-planning-snapshot-v1.schema.json`
- Create: `tests/fixtures/pericial-planning-snapshot-v1.json`
- Create: `tests/test_pericial_planning_v1.py`

**Interfaces:**
- Consumes: `CaseAnalysisSnapshot`, `SourceProvenance` and canonical analysis item/occurrence identities.
- Produces: `PlanningSnapshot`, `PericialPlan`, all required planning item types, `PlanningDecision`, `PlanningCoverage`, `pericial_planning_from_mapping`, `pericial_planning_to_mapping`, `validate_against_case_analysis`, `with_upstream_staleness`.

- [ ] Write failing tests that import every required type and deserialize a synthetic snapshot containing objectives, issues, question links, documents, information, inspection, measurement, photo, equipment, access, method/procedure/sampling candidates, safety, external support, risks and gaps.
- [ ] Run `python -m pytest -q tests/test_pericial_planning_v1.py` and confirm missing-module RED.
- [ ] Implement bounded immutable dataclasses and exact JSON mapping; require a derivation on every material item and keep normative metadata distinct from source provenance.
- [ ] Run focused tests and confirm GREEN.
- [ ] Add RED adversarials for missing/foreign Case Analysis IDs, forged occurrence/SHA, question-as-answer fields, method auto-approval, duplicate identities, dangling question links, destructive proposal replacement, review revision/order conflicts and dishonest readiness/coverage.
- [ ] Implement only the validation required to close those adversarials; validate the synthetic fixture with JSON Schema and runtime semantics.
- [ ] Run focused tests, Ruff and `git diff --check`; commit `feat: add canonical pericial planning model`.

### Task 2: Atomic persistence, reopen and upstream staleness

**Files:**
- Create: `scripts/backend_contract/application/pericial_planning.py`
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `tests/test_pericial_planning_v1.py`
- Modify: `tests/test_local_api_v1.py`

**Interfaces:**
- Consumes: latest canonical Case Analysis record/snapshot and existing `append_if_latest` artifact revisions.
- Produces: `SavePericialPlan.execute(workspace_id, snapshot, expected_revision)` and `GetPericialPlan.execute(workspace_id)`.

- [ ] Write RED tests for save/reopen equivalence, workspace isolation, exact latest Case Analysis revision/digest linkage, atomic competing revision rejection and proposal immutability across revisions.
- [ ] Run the new application tests and confirm missing-service/behavior RED.
- [ ] Implement canonical-schema validation, upstream linkage verification and atomic append-only persistence using the existing repository; do not add storage infrastructure.
- [ ] Write RED tests showing any changed latest Case Analysis digest marks the reopened plan stale while unchanged upstream preserves the same effective professional state.
- [ ] Implement read-time reconciliation without rewriting persisted history; run focused persistence tests GREEN.
- [ ] Run application/storage regression, Ruff and `git diff --check`; commit `feat: persist and reconcile pericial plans`.

### Task 3: Local API, product bridge and published contract

**Files:**
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/local_api/server.py`
- Modify: `scripts/backend_contract/product_bridge/server.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `tests/test_local_api_v1.py`
- Modify: `tests/test_product_bridge_v1.py`

**Interfaces:**
- Produces: `GET` and `PUT /v1/workspaces/{workspace_id}/pericial-planning`, mirrored only at `/app-api/v1/workspaces/{workspace_id}/pericial-planning`.
- Request: `{ "expected_revision": integer|null, "snapshot": PlanningSnapshot }`; response: `{ "revision": integer, "updated_at": string, "snapshot": PlanningSnapshot }`.

- [ ] Write RED tests for token-private GET/PUT, missing plan, invalid workspace/body/revision, semantic payload rejection, stale-upstream save rejection, generic-artifact bypass denial and exact bridge allowlist.
- [ ] Run Local API/bridge focused tests and confirm route RED.
- [ ] Wire the planning services through the existing composition root and sanitized error mapping; preserve request-size/time limits.
- [ ] Publish request/response schemas in OpenAPI using the external canonical planning schema and semantic-boundary metadata.
- [ ] Add contract parity tests proving schema and runtime reject the same authority violations.
- [ ] Run API/bridge/OpenAPI regression, Ruff and `git diff --check`; commit `feat: expose canonical pericial planning API`.

### Task 4: Useful professional planning route

**Files:**
- Create: `frontend/src/data/pericialPlanning.ts`
- Create: `frontend/src/workspaces/PericialPlanningView.tsx`
- Create: `frontend/src/workspaces/PericialPlanningView.test.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.test.tsx`
- Modify: `frontend/src/styles/shell.css`

**Interfaces:**
- Consumes: canonical planning envelope from same-origin `/app-api`.
- Presents: object, questions, controversies, required documents/information, inspection, measurements, photos, equipment, candidate methods/procedures/sampling, access/support/safety, gaps, risks, decisions, derivation drill-down and readiness reasons.

- [ ] Write RED UI/data tests for loading, empty, error/retry, READY/PARTIAL/BLOCKED, stale upstream, complete derivation display, proposal-vs-approved labels and absence of findings/answers/conclusions.
- [ ] Confirm missing module/component RED with `npm.cmd test -- --run src/workspaces/PericialPlanningView.test.tsx`.
- [ ] Implement a strict envelope parser, same-origin/no-store fetch, route wiring and a static three-level hierarchy (summary, technical groups, audit derivation); do not add decorative animation.
- [ ] Write RED tests for explicit `APPROVE`, `REJECT`, `MODIFY`, `DEFER` controls preserving the original proposal and persisting a new decision with optimistic revision.
- [ ] Implement the minimum accessible review form and save/error state; never synthesize reviewer identity, rationale or modified content.
- [ ] Run focused UI tests, full frontend tests, build and lint; self-check motion/accessibility rules; commit `feat: deliver professional planning workspace`.

### Task 5: Adversarial closure and normal delivery

**Files:** all changed files above.

**Interfaces:**
- Consumes: frozen candidate HEAD.
- Produces: P0=0/P1=0 evidence, protected PR, normal merge and post-main acceptance.

- [ ] Run `SIBLING_DEFECT_SWEEP_V2` across all planning collections for missing derivation, cross-workspace provenance, foreign analysis IDs, silent method adoption, question answers, destructive review history and stale false negatives.
- [ ] Run `PRE_TERMINAL_ADVERSARIAL_MATRIX_V1` covering workspace × upstream revision × item type × review action × readiness × reopen.
- [ ] Apply `repository-safety-gate`: change-impact mapping, boundary-selected tests, privacy/schema/invariant checks, Ruff, frontend tests/build/lint, one full regression and one `python -m scripts.quality.verify_core --full` on one stable frozen HEAD.
- [ ] Run bounded desktop/mobile visual inspection and reduced-motion/accessibility checks without private data.
- [ ] Obtain exact-HEAD PR Reviewer, Shadow Systemic Review and Systemic Auditor concurrently in independent read-only checkouts; repair every demonstrated P0/P1 and invalidate stale reviews.
- [ ] Push, open a protected PR with `Closes #150`, wait for normal checks, merge without bypass, verify the exact main tree, run focused post-main acceptance, record terminal evidence and stop for the human decision before `VISTORIA_FOUNDATION`.
