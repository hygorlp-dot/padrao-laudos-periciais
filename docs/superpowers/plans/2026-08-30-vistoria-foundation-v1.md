# Vistoria Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: execute each task with strict RED/GREEN, then review the frozen terminal HEAD independently. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute an approved Pericial Planning snapshot as a structured, reopenable field-work record without converting observations, statements, measurements or media into findings or conclusions.

**Architecture:** A source-neutral inspection domain owns the plan snapshot binding, typed field records, raw measurement pairs, private-media references, limitations, coverage and review. The application boundary atomically binds every saved session to the latest non-stale approved planning revision and verifies referenced photo bytes against workspace-private metadata. Existing artifact revisions and private storage remain the only authorities. The Local API/product bridge expose strict DTOs; React renders a restrained field-work route optimized for keyboard use and future offline adaptation, without adding sync.

**Tech Stack:** Python 3.13 dataclasses, JSON Schema 2020-12, existing SQLite/private-content/Application/Local API layers, OpenAPI 3.1, React 19, TypeScript, Vite/Vitest, plain CSS.

## Global Constraints

- Issue #152; branch `feat/152-vistoria-foundation-v1`; base `7d6b99053fbdf797bedcf921e8fe5494a709943f`.
- Synthetic fixtures/bytes only; never access `referencias/privadas/`; private egress remains denied.
- `PARTY_ALLEGATION != FIELD_OBSERVATION`; `DOCUMENTED_FACT != FIELD_OBSERVATION`; `FIELD_OBSERVATION != TECHNICAL_FINDING`.
- `MEASUREMENT != INTERPRETATION`; preserve the exact raw value/unit pair and provenance.
- `PHOTO != CONCLUSION`; original private bytes plus verified SHA-256 are authoritative, previews are not.
- Party statements remain typed statements; professional notes remain notes.
- A session cannot execute or persist against a stale/unapproved planning snapshot.
- No causality, responsibility, answers to quesitos, technical findings or report prose.
- No new trust mechanism, governance predecessor, offline synchronization or external integration.
- UI is a productivity tool: no decorative motion; only existing fast functional transitions and reduced-motion behavior.

## Causal DAG and critical path

`latest approved Planning identity/revision/digest` -> `immutable InspectionPlanSnapshot` -> `typed field records + raw provenance` -> `private photo integrity` -> `honest item status/limitations/coverage` -> `atomic save/reopen` -> `Local API/Bridge` -> `field-work route` -> `adversarial matrix` -> `terminal assurance/reviews/PR/post-main`.

The domain/application authority boundary is the critical path. Schema/fixture and presentation become parallel-safe only after names and DTOs freeze. One mutation owner controls shared persistence, API, OpenAPI, bridge and routing boundaries.

---

### Task 1: Canonical inspection domain, schema and synthetic fixture

**Files:**
- Create: `scripts/backend_contract/vistoria.py`
- Create: `schemas/inspection-session-v1.schema.json`
- Create: `tests/fixtures/inspection-session-v1.json`
- Create: `tests/test_vistoria_foundation_v1.py`

- [ ] Write RED imports/deserialization tests covering every required entity, observation type and execution state.
- [ ] Implement immutable bounded dataclasses, strict mapping and JSON Schema parity.
- [ ] Add RED adversarials for semantic flattening, duplicate/dangling IDs, missing provenance, interpretation/conclusion fields, destroyed raw pairs, false calibration claims, unbound media and dishonest coverage.
- [ ] Implement the minimum invariants and run focused GREEN, Ruff and `git diff --check`.
- [ ] Commit `feat: add canonical inspection session model`.

### Task 2: Planning authority, private-media integrity and reopen persistence

**Files:**
- Create: `scripts/backend_contract/application/vistoria.py`
- Modify: `scripts/backend_contract/application/services.py` only if a typed photo import adapter is required.
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `tests/test_vistoria_foundation_v1.py`

- [ ] Write RED tests for exact latest approved planning binding, stale/unreviewed plan denial, workspace isolation, optimistic conflict and reopen equivalence.
- [ ] Write RED tests verifying each `PhotoRecord` content ID, original SHA-256 and media type against the same workspace private store under the shared authority guard.
- [ ] Implement atomic append/reopen via existing artifact revisions and read-time upstream reconciliation; do not copy media bytes into artifacts.
- [ ] Add limitation propagation and exact coverage recomputation tests; close only demonstrated defects.
- [ ] Run focused storage/application regression, Ruff and `git diff --check`.
- [ ] Commit `feat: persist plan-bound inspection sessions`.

### Task 3: Local API, bridge and OpenAPI contract

**Files:**
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/local_api/server.py`
- Modify: `scripts/backend_contract/product_bridge/server.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `tests/test_local_api_v1.py`
- Modify: `tests/test_product_bridge_v1.py`

- [ ] Write RED tests for private-token GET/PUT, strict payloads, stale planning, photo mismatch, invalid workspace/revision and exact bridge allowlist.
- [ ] Implement `GET/PUT /v1/workspaces/{workspace_id}/inspection-session` and same-origin `/app-api` mirror with sanitized errors and existing limits.
- [ ] Publish exact schema refs and semantic-boundary metadata; prove runtime/schema parity.
- [ ] Run focused API/bridge regression, Ruff and `git diff --check`.
- [ ] Commit `feat: expose canonical inspection session API`.

### Task 4: Field-work workspace

**Files:**
- Create: `frontend/src/data/inspectionSession.ts`
- Create: `frontend/src/workspaces/InspectionSessionView.tsx`
- Create: `frontend/src/workspaces/InspectionSessionView.test.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/routes/routeCatalog.ts` if canonical labels require it.
- Modify: `frontend/src/styles/shell.css`

- [ ] Write RED UI/parser tests for loading, empty, error/retry, reopen, all item states, typed records, photo authority labels, limitations and coverage.
- [ ] Implement strict same-origin/no-store data access and accessible grouped item panels optimized for keyboard entry.
- [ ] Ensure the UI never labels evidence candidates as findings/conclusions and never treats a preview as authority.
- [ ] Run focused UI tests, frontend regression/build/lint and accessibility/motion self-review.
- [ ] Commit `feat: deliver structured inspection workspace`.

### Task 5: Adversarial closure and normal delivery

- [ ] Run `SIBLING_DEFECT_SWEEP_V2`, pre-terminal adversarial matrix and read-only systemic review before freezing.
- [ ] Freeze one candidate HEAD; run one full regression and one `python -m scripts.quality.verify_core --full` only.
- [ ] Run independent PR review and systemic audit concurrently on the exact frozen HEAD; external diversity only if the deterministic gate requires a sanitized package.
- [ ] Resolve all causal P0/P1 findings with focused RED/GREEN and refreeze only if mutated.
- [ ] Push, open protected PR linked to #152, await protected checks, merge normally and run focused post-main acceptance.
- [ ] Close #152 with evidence, declare Stage 5 complete, identify Evidence and Technical Findings Foundation as next, and stop for the required human decision.
