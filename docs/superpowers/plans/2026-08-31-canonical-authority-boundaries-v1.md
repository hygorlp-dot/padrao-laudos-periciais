# Canonical Authority Boundaries V1 Implementation Plan

> **For agentic workers:** Execute each task with first-party TDD, safety engineering, independent review, and the repository safety gate.

**Goal:** Close PR-A findings A1–A5 without adding Stage 10 or weakening provenance, workspace isolation, or professional authority.

**Architecture:** Remove the network-reachable generic revision mutation and centralize ownership of every application artifact kind. Replace privileged full-snapshot mutations with server-owned commands that load the current predecessor, append authority history, derive effective state, and persist under CAS. Provide proposal-only non-AI bootstrap commands for Case Analysis and Planning.

**Tech Stack:** Python 3 application/domain services, SQLite revision repository, JSON Schema/OpenAPI, React/TypeScript local UI, pytest/Vitest.

## Global Constraints

- Synthetic fixtures only; private egress remains false.
- Source text, source occurrence identity, prior decisions, and effective-finding lineage are immutable.
- IDs, timestamps, review revisions, professional identity, supersession, effective findings, and privileged coverage are server-owned.
- Initial Case Analysis has no human review authority; initial Planning is proposal-only.
- No Stage 10, timing, trust-anchor, branch-protection, or protected-judge changes.

---

### Task 1: A1 canonical artifact ownership and generic-write removal

**Files:**
- Create: `scripts/backend_contract/application/artifact_ownership.py`
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `scripts/backend_contract/application/__init__.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `scripts/backend_contract/infrastructure/productization.py`
- Test: `tests/test_canonical_authority_boundaries_v1.py`
- Test: `tests/test_local_api_v1.py`
- Test: `tests/test_productization_foundation_v1.py`

**Produces:** one registry containing every application-owned kind and portability validator; no generic POST mutation route/service.

- [ ] Write parameterized service/HTTP attacks for all canonical kinds and unknown backup poisoning; confirm RED.
- [ ] Add the ownership registry and make productization derive its canonical validator inventory from it.
- [ ] Remove `AppendArtifactRevision` from composition/public application exports and reject generic POST with no repository mutation.
- [ ] Preserve generic revision reads only; prove legitimate specialized histories still back up and restore.
- [ ] Run A1 adversarial and backup regression tests; commit.

### Task 2: A2 full-snapshot privilege guards

**Files:**
- Modify: `scripts/backend_contract/application/case_analysis.py`
- Modify: `scripts/backend_contract/application/pericial_planning.py`
- Modify: `scripts/backend_contract/application/vistoria.py`
- Modify: `scripts/backend_contract/application/technical_findings.py`
- Modify: `scripts/backend_contract/application/report_foundation.py`
- Modify: `scripts/backend_contract/application/delivery_foundation.py`
- Modify: `scripts/backend_contract/application/budget_foundation.py`
- Test: `tests/test_canonical_authority_boundaries_v1.py`

**Produces:** initial/update guards that reject client-created or rewritten privileged authority while leaving nonprivileged mutable data reachable.

- [ ] Add one RED initial-forgery and one predecessor-rewrite test per dedicated snapshot boundary.
- [ ] Classify and compare privileged collections/state against the predecessor or require authority-free initial state.
- [ ] Keep dedicated command transitions valid; reject full-snapshot privilege injection.
- [ ] Run the parameterized privilege sweep and affected domain suites; commit.

### Task 3: A4 server-owned Case Analysis review and effective projection

**Files:**
- Modify: `scripts/backend_contract/case_analysis.py`
- Modify: `scripts/backend_contract/application/case_analysis.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `schemas/case-analysis-snapshot-v1.schema.json`
- Modify: `frontend/src/data/caseAnalysis.ts`
- Modify: `frontend/src/workspaces/CaseAnalysisView.tsx`
- Test: `tests/test_case_analysis_v1.py`
- Test: `tests/test_local_api_v1.py`
- Test: `frontend/src/workspaces/CaseAnalysisView.test.tsx`

**Produces:** `ReviewCaseAnalysisItem` with `CONFIRM|CORRECT|REJECT`, contiguous append-only history, server IDs/time, and an explicit stale-aware effective reviewed value.

- [ ] Add RED tests for initial review forgery, history rewrite, cross-workspace target, stale effect, CAS, and client ID/time injection.
- [ ] Implement effective projection without changing source `text` or provenance.
- [ ] Implement the review command and route using server-owned identity/clock/IDs.
- [ ] Make Planning derivation consume the effective projection and expose item review UI.
- [ ] Run backend/frontend A4 suites; commit.

### Task 4: A4 usable non-AI Case Analysis bootstrap

**Files:**
- Modify: `scripts/backend_contract/application/case_analysis.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `frontend/src/data/caseAnalysis.ts`
- Modify: `frontend/src/workspaces/CaseAnalysisView.tsx`
- Test: `tests/test_case_analysis_v1.py`
- Test: `tests/test_local_api_v1.py`
- Test: `frontend/src/workspaces/CaseAnalysisView.test.tsx`

**Produces:** a server-owned start command from stored documents/JDM and user-authored proposal commands for each Stage 3 material category, all with exact selected-source provenance.

- [ ] Add RED tests proving a normal user cannot start without documents/provenance and can create every authorized category without handcrafted JSON.
- [ ] Implement an empty canonical bootstrap bound to live document inventory and JDM.
- [ ] Add closed proposal commands that accept source occurrence selections, never conclusions or review authority.
- [ ] Add empty-state start and proposal-entry UI; run vertical tests; commit.

### Task 5: A5 proposal-only Planning bootstrap

**Files:**
- Modify: `scripts/backend_contract/application/pericial_planning.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `frontend/src/data/pericialPlanning.ts`
- Modify: `frontend/src/workspaces/PericialPlanningView.tsx`
- Test: `tests/test_pericial_planning_v1.py`
- Test: `tests/test_local_api_v1.py`
- Test: `frontend/src/workspaces/PericialPlanningView.test.tsx`

**Produces:** `StartPericialPlanning` derived from non-stale reviewed Case Analysis with empty decisions and all statuses `PENDING`.

- [ ] Add RED initial decision/status injection and empty-state bootstrap tests.
- [ ] Enforce initial proposal-only invariants in `SavePericialPlanning`.
- [ ] Generate conservative proposal items from effective reviewed Case Analysis with exact derivation/provenance and server identities.
- [ ] Add start route and UI action; retain `ReviewPericialPlanning` as the only status transition.
- [ ] Run A5 vertical tests; commit.

### Task 6: A3 server-owned Technical authority and immutable lineage

**Files:**
- Modify: `scripts/backend_contract/technical_findings.py`
- Modify: `scripts/backend_contract/application/technical_findings.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `frontend/src/data/technicalSnapshot.ts`
- Modify: `frontend/src/workspaces/TechnicalFindingsView.tsx`
- Test: `tests/test_technical_findings_foundation_v1.py`
- Test: `tests/test_local_api_v1.py`
- Test: `frontend/src/workspaces/TechnicalFindingsView.test.tsx`

**Produces:** proposal commands separated from trusted professional review commands; predecessor authority graph is append-only and findings/coverage are server-derived.

- [ ] Add RED AI-like self-authorization, identity/time forgery, prior-decision rewrite/deletion, stale/nonleaf supersession, and cross-workspace attacks.
- [ ] Restrict full snapshot save to initial empty/proposal-safe state or internal command persistence.
- [ ] Implement proposal commands for evidence, methods, and findings that cannot create effective state.
- [ ] Implement professional review commands using server-owned professional profile, IDs, clock, supersession, effective finding, and coverage derivation.
- [ ] Replace frontend full-authority construction with command DTOs; run vertical/adversarial tests; commit.

### Task 7: PR-A terminal assurance

**Files:** all files changed above.

- [ ] Run sibling-defect sweep and pre-terminal adversarial matrix for A1–A5.
- [ ] Run change-impact tests, frontend test/typecheck/lint, full pytest once, and `verify_core --full` once on frozen HEAD.
- [ ] Run independent PR review and systemic audit concurrently on the exact HEAD.
- [ ] Preserve historical timing debt separately; require product/security P0=0 and P1=0.
- [ ] Push, open PR referencing #166, pass protected CI, merge normally, and verify post-main.
