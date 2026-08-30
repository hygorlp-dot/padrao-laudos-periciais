# Case Analysis Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: execute each task with strict RED/GREEN, then review the frozen terminal HEAD independently.

**Goal:** Transform already-stored synthetic documentary evidence into a traceable, source-grounded, human-reviewable case map without producing pericial conclusions.

**Architecture:** A source-neutral domain module owns immutable analysis entities, provenance, coverage, staleness, indexing and targeted retrieval. Existing append-only artifact revisions provide persistence and workspace isolation. Minimal Local API/Bridge endpoints expose snapshots, and the existing React shell renders `/pericias/:workspaceId/analise` in the established Calibrated Process Ledger world.

**Tech Stack:** Python 3.13 dataclasses, existing Application/SQLite/Local API layers, OpenAPI 3.1, React 19, TypeScript, Vite/Vitest, plain CSS.

## Global Constraints

- Synthetic fixtures only; never read `referencias/privadas/`.
- No conclusions, causality, liability, answers to quesitos, planning, inspection, report, budget, AI gateway or new tooling predecessor.
- JDM participant identities are referenced; no alternative party model.
- Every material item has exact workspace/document/SHA/page-or-span/source-revision provenance.
- Proposal never becomes effective without explicit human review.
- Existing protected judges, capability policy and support scopes remain unchanged.

## Causal DAG and critical path

`source/JDM contracts` → `document index + canonical analysis model` → `targeted retrieval + coverage/staleness` → `append-only persistence/reopen` → `Local API/Bridge` → `useful analysis route` → `terminal assurance/reviews/PR/post-main`.

The domain/index lane is the critical path. UI presentation begins only after a real API DTO exists. Official PJe/CNJ research is read-only and nonblocking.

---

### Task 1: Canonical analysis and process document index

**Files:**
- Create: `scripts/backend_contract/case_analysis.py`
- Create: `schemas/case-analysis-snapshot-v1.schema.json`
- Create: `tests/fixtures/case-analysis-snapshot-v1.json`
- Create: `tests/test_case_analysis_v1.py`

**Interfaces:**
- Produces `CaseAnalysisSnapshot`, `ProcessDocumentIndex`, `case_analysis_from_mapping`, `query_analysis`.
- Consumes canonical JDM IDs only as references.

- [ ] Write failing tests for every required entity, exact provenance, N:N claim relations, honest coverage, stale source changes, conflicts as proposals, human derivation, unchanged-hash reuse and targeted query scan counts.
- [ ] Run `uv run python -m pytest -q tests/test_case_analysis_v1.py` and confirm missing-symbol RED.
- [ ] Implement immutable bounded contracts and deterministic indices without pericial conclusion fields.
- [ ] Validate the synthetic fixture against JSON Schema and semantic deserializer.
- [ ] Run focused tests and commit.

### Task 2: Append-only persistence and Local API contract

**Files:**
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `tests/test_local_api_v1.py`
- Modify: `tests/test_product_bridge_v1.py`

**Interfaces:**
- Produces `GET/PUT /v1/workspaces/{workspace}/case-analysis` and matching `/app-api` bridge allowlist.
- Stores canonical snapshots as existing append-only artifact revisions.

- [ ] Write failing save/reopen/workspace-isolation/invalid-provenance/API tests.
- [ ] Confirm route/service RED.
- [ ] Implement the minimum route through the canonical semantic deserializer and existing revision repository.
- [ ] Add OpenAPI request/response component and sanitized errors.
- [ ] Run vertical API/bridge regression and commit.

### Task 3: Useful Stage 3 route

**Files:**
- Create: `frontend/src/data/caseAnalysis.ts`
- Create: `frontend/src/workspaces/CaseAnalysisView.tsx`
- Create: `frontend/src/workspaces/CaseAnalysisView.test.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/styles/shell.css`

**Interfaces:**
- Consumes the product bridge case-analysis DTO.
- Presents overview, index, timeline, JDM participant references, arguments, decisions, object, questions, technical documents, gaps, proposed conflicts, coverage and provenance drill-down.

- [ ] Write failing UI/data tests for loading, error, unavailable/partial coverage, full content, provenance details and no conclusions.
- [ ] Confirm component/data RED.
- [ ] Implement the route in Operate mode, inheriting Calibrated Process Ledger; minimal motion only for disclosure, disabled under reduced motion.
- [ ] Run frontend test/build/accessibility checks and commit.

### Task 4: Adversarial closure and delivery

**Files:** all changed files above plus fixture registry when required.

- [ ] Run sibling sweep for foreign-case contamination, attachment metadata promotion, missing source, changed SHA, cross-workspace refs, unsupported role and destructive human overwrite.
- [ ] Run change-impact selected tests, full regression, Ruff, frontend tests/build and `verify_core --full` once on stable HEAD.
- [ ] Run the Impeccable detector and bounded desktop/mobile visual inspection.
- [ ] Obtain exact-HEAD PR Reviewer, Systemic Auditor and Shadow Review concurrently; repair P0/P1 causally.
- [ ] Push, open protected PR, merge normally, run post-main acceptance and close #121.
