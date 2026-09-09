# Construction-Defect PAT Product Reachability V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the vendored `executing-plans` workflow task by task. Every production behavior follows strict RED/GREEN, and the final frozen HEAD receives independent review and systemic audit.

**Goal:** Make the existing construction-defect motor and its lossless `PAT_FINAL` output reachable from the normal local product surface, professionally reviewable, report-grounding, portable through backup/recovery and reopenable without terminal use.

**Architecture:** A source-neutral backend contract owns an immutable `CONSTRUCTION_DEFECT_ANALYSIS_V1` artifact bound to exact Process Case, Case Analysis, Planning and Inspection revisions. A Planning-layer adapter, injected only at the approved application composition root, maps explicit professional observation contexts plus canonical snapshots into the existing `motor_vicios` input contracts and returns the existing validated `analise-motor-vicios` payload. The artifact preserves canonical-to-legacy identity links and the full PAT graph without flattening it into generic findings. Professional reviews remain append-only and only an approved PAT may become Report provenance. Local API, ProductBridge and React expose purpose-specific operations; no generic process execution, egress or second pathology engine is introduced.

**Tech Stack:** Python dataclasses/enums, existing artifact-revision repository and authority guard, JSON Schema 2020-12, existing `scripts.motor_vicios` pipeline, Local API/OpenAPI/ProductBridge, React 19/TypeScript/Vitest, pytest.

## Global constraints

- Issue #188; parent #187; branch `fix/188-construction-defect-pat-reachability`; base `4f3247bea7d12d41db1b630b063176e8db8ebbe1`.
- Synthetic fixtures only; never access `referencias/privadas/`; `PRIVATE_EGRESS = FALSE`.
- Reuse `scripts.motor_vicios`; do not create a second pathology engine or reinterpret PAT as a generic Technical Finding.
- `PAT_FINAL` is the engine-final proposal graph, not a professional decision. Only an append-only review by the Inspection-bound professional makes an individual PAT effective.
- Explicit observation context is professional input. The adapter must never guess manifestation, system, element, outcome, allegation link, question link or method from prose.
- Canonical source IDs remain preserved through explicit identity links even where the legacy engine requires `ALG/QUE/QT/OBS/MED/FOT/PAT` aliases.
- Report prose may cite only an effective, current PAT. Report never mutates PAT and stale PAT demotes dependent Report/Delivery through normal revision binding.
- Preserve existing generic Stage 6 Technical Snapshot. Construction-defect specialization is additive and optional for non-construction disciplines.
- UI is a productivity tool: no animation on frequent/keyboard operations; domain authority remains server-owned; simple, technical and audit levels stay distinct.
- One mutation owner per shared boundary. #187 oracle harness and unrelated documentation reconciliation remain outside this PR.

## Causal DAG and critical path

`Process Case + reviewed Case Analysis + reviewed Planning + current Inspection`
→ `explicit construction-defect observation contexts`
→ `lossless canonical/legacy identity manifest`
→ `existing motor_vicios execution with egress disabled`
→ `validated PAT_FINAL artifact`
→ `append-only professional PAT review`
→ `effective PAT provenance in Report`
→ `Report/Delivery staleness binding`
→ `portable artifact validator`
→ `backup / verify / staging / promote / reopen`
→ `Local API / ProductBridge / React reachability`
→ `adversarial matrix`
→ `terminal assurance / reviews / PR / post-main`.

Critical path: explicit identity-preserving adapter → persisted authority/review → Report binding → recovery portability. Schema/UI lanes may proceed only after the domain contract freezes. The backend application service owns artifact mutation; the adapter only computes a deterministic proposal.

## Pre-terminal adversarial matrix

- Unknown, cross-workspace or duplicate observation/claim/question IDs.
- Context for a statement/photo instead of a direct observation.
- Observation context omits manifestation, method or explicit outcome.
- Measurement/photo is linked to a different Inspection item.
- Adapter invents source identity or changes raw value/unit/photo hash.
- Engine output is not `PAT_FINAL`, fails the existing schema/gate, or contains a PAT without a canonical identity manifest.
- Engine attempts online search/egress or receives a search provider.
- PAT becomes effective without the Inspection-bound professional, reason, action and server timestamp.
- Review history is overwritten, branched or applied to an unknown PAT.
- Report cites proposed/rejected/stale/foreign PAT or assigns a higher authority than its professional review.
- Upstream Case Analysis/Planning/Inspection or PAT revision changes after Report approval.
- Backup omits the PAT artifact, accepts unsupported schema, corrupts identity links or reopens with changed bytes.
- Local API/bridge accepts a generic engine/subprocess route, invalid verb/suffix, oversized body or workspace mismatch.
- UI reports success after backend failure, loses a successful retry, or hides stale/review state.

---

### Task 1: Canonical PAT wrapper and deterministic existing-engine adapter

**Files:**
- Create: `scripts/backend_contract/construction_defect_analysis.py`
- Create: `scripts/planejamento_pericial/construction_defect_analysis_adapter.py`
- Create: `schemas/construction-defect-analysis-v1.schema.json`
- Create: `tests/fixtures/construction-defect-analysis-v1.json`
- Create: `tests/test_construction_defect_product_integration_v1.py`

**Interfaces:**
- Backend produces strict `ConstructionDefectSourceSnapshot`, `ObservationContext`, `CanonicalIdentityLink`, `PathologyReview`, `ConstructionDefectAnalysisSnapshot` and mapping helpers.
- Adapter exposes one purpose-specific `execute(...)` operation and imports the existing `executar_pipeline_motor`; it performs no persistence.

- [x] Write a RED that imports the missing contract and proves a hand-authored snapshot preserves a full existing PAT payload and canonical identity links.
- [x] Run focused pytest and verify failure is the missing production contract.
- [x] Implement the minimum immutable contract, derived effective PAT IDs and strict mapping/schema parity.
- [x] Write RED adapter tests from real canonical Case Analysis/Planning/Inspection objects with one direct observation, measurement and synthetic photo reference. Require exact aliases and raw provenance preservation.
- [x] Implement deterministic mapping and call the existing motor with `conhecimento={}` only. Validate the existing engine output against `analise-motor-vicios.schema.json`; reject non-`PAT_FINAL`. Preserve an honestly blocked gate as diagnostic state, but never expose it as professionally effective or Report-eligible.
- [x] Add REDs for missing/foreign contexts, invented links, duplicate aliases and egress-provider injection; implement fail-closed validation.
- [x] Run focused GREEN, schema validator, Ruff and `git diff --check`; commit the causal slice.

### Task 2: Application authority, persistence, review, staleness and recovery portability

**Files:**
- Create: `scripts/backend_contract/application/construction_defect_analysis.py`
- Modify: `scripts/backend_contract/application/ports.py`
- Modify: `scripts/backend_contract/application/artifact_ownership.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/product_bridge/composition.py`
- Modify: `scripts/planejamento_pericial/app_composition.py`
- Modify: `scripts/backend_contract/infrastructure/productization.py`
- Modify: `tests/test_construction_defect_product_integration_v1.py`
- Modify focused productization/recovery tests only where the new portable artifact requires proof.

**Interfaces:**
- `StartConstructionDefectAnalysis.execute(...)`, `GetConstructionDefectAnalysis.execute(workspace_id)` and `ReviewPathology.execute(...)`.
- Artifact kind `CONSTRUCTION_DEFECT_ANALYSIS_V1`, canonical singleton artifact ID, explicit dependencies and productization validator.

- [x] Write REDs for exact four-upstream binding, injected-adapter requirement, optimistic revision authority, append-only professional review and reopen.
- [x] Implement start/get/save/review with the shared authority guard; adapter output remains proposal-only and professional identity resolves from current Inspection.
- [x] Write REDs for changed Process Case, Case Analysis, Planning or Inspection; require honest stale reconciliation and prohibit further approval.
- [x] Implement staleness and dependency records without mutating historical PAT bytes.
- [x] Write RED backup/verify/restore/reopen tests requiring exact schema, revisions, checksums, identity manifest and reviews.
- [x] Register the portable artifact and strict compatibility validator; run focused GREEN and commit.

### Task 3: PAT-grounded Report authority without semantic flattening

**Files:**
- Modify: `scripts/backend_contract/report_foundation.py`
- Modify: `scripts/backend_contract/application/report_foundation.py`
- Modify: `schemas/report-snapshot-v1.schema.json`
- Modify: `tests/test_report_foundation_v1.py`
- Modify: `tests/test_construction_defect_product_integration_v1.py`

**Interfaces:**
- Optional exact PAT snapshot binding in `ReportSourceSnapshot`.
- `ReportProvenance(source_kind="PATHOLOGY", source_id="PAT-NNN", ...)` accepted only for an effective current PAT and assigned no authority beyond the explicit professional PAT review.

- [x] Write REDs: approved PAT may ground a Report claim; proposed/rejected/stale/foreign PAT must fail.
- [x] Extend Report start/save/reopen to bind the optional current PAT artifact, validate effective PAT provenance and add the dependency atomically.
- [x] Write RED for a later PAT/upstream revision demoting approved Report and downstream Delivery to stale; implement through existing read-time reconciliation.
- [x] Add a longitudinal RED proving `observation + measurement + photo -> PAT_FINAL -> professional review -> Report claim` with all IDs traceable.
- [x] Run focused Report/Delivery GREEN and commit.

### Task 4: Purpose-specific Local API, ProductBridge and React workbench

**Files:**
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/product_bridge/transport.py`
- Modify: `contracts/openapi-v1.json`
- Create: `frontend/src/data/constructionDefectAnalysis.ts`
- Create: `frontend/src/workspaces/ConstructionDefectAnalysisView.tsx`
- Create: `frontend/src/workspaces/ConstructionDefectAnalysisView.test.tsx`
- Modify: `frontend/src/workspaces/TechnicalFindingsView.tsx`
- Modify: `frontend/src/workspaces/ReportFoundationView.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx` only if a dedicated canonical route is demonstrably clearer than embedding the specialized panel.
- Modify: `frontend/src/styles/shell.css` only for existing visual-system reuse.
- Modify focused Local API/bridge/OpenAPI tests.

**Interfaces:**
- Same-origin `GET/POST /app-api/v1/workspaces/{workspace_id}/construction-defect-analysis` and purpose-specific `POST .../pathology-reviews`.
- UI collects explicit structured observation context, displays engine proposal/gate, exposes PAT review and audit identities, and never auto-approves.

- [x] Write route/parser/component REDs for absent/start/loading/error/stale, explicit context, proposal versus effective state, retry and backend-failure messaging.
- [x] Implement strict Local API/OpenAPI/bridge routes; reject unknown suffixes/verbs and never expose a generic engine runner.
- [x] Implement frontend data parsing and the smallest workbench. Keep all material validation server-side and add no motion to form/review operations.
- [x] Add Report source selection for effective PAT IDs without copying PAT conclusions silently into prose.
- [x] Run focused Vitest, typecheck, lint, build and Python API/bridge suites; perform the UI/motion self-check and commit.

### Task 5: Causal closure and return to #187

- [x] Execute `SIBLING_DEFECT_SWEEP_V2` across optional-specialization bindings, professional-review histories, portable artifact validators and Report provenance kinds.
- [x] Execute the pre-terminal adversarial matrix and a read-only `SHADOW_SYSTEMIC_REVIEW_V2`; repair each P0/P1 through a new RED/GREEN cycle.
- [x] Run change-impact suites, schema/fixture validation, Ruff, py_compile, frontend test/typecheck/lint/build, mojibake/config checks and `git diff --check`.
- [ ] Freeze one exact HEAD. Run one full regression and one `python -m scripts.quality.verify_core --full` on that SHA only.
- [ ] Push and open a protected PR with `Closes #188` and `Parent #187`; require protected CI on the exact SHA.
- [ ] Run independent reviewer and systemic auditor concurrently in isolated read-only checkouts on the terminal SHA; P0/P1 block merge.
- [ ] Merge normally without bypass, run focused post-main PAT reachability/recovery proof, close #188 and resume #187 automatically.

#### Terminal execution checkpoint

- Backend regression on `9fb9ecfc06eff5dfef8c220349e6bc7937b80955`: 2844 passed, 14 skipped and 104 subtests passed.
- Frontend regression on the same SHA: 20 files and 163 tests passed; typecheck, lint and build passed.
- Static/configuration gates passed: Ruff, compileall, 20 schemas, 34 fixtures, configuration, fixture registry, mojibake, change impact and diff check.
- The first `verify_core --full` invocation on that SHA is invalid assurance evidence. A single shared `PYTEST_ADDOPTS=--basetemp=...` was applied to the gate, while `verify_core` runs historical mutation and regression subprocesses concurrently. The shared destructive basetemp lifecycle caused cross-process pytest interference in quality, capability and regression collections. This is an execution-model failure, not a product verdict; the command is not to be rerun on that SHA.
- Form a new evidence-only candidate with production blobs unchanged. Carry forward the completed semantic regression by exact blob ancestry, then run `verify_core --full` once with an isolated fresh `TEMP`/`TMP` root and without a shared `--basetemp` override. A timing-only finding remains classified under the existing canonical duration debt.

#### Terminal review P1 architecture checkpoint

- Candidate `242d0bd1f9a2ac9ad324b2a35d27d0d1499ccc02` is invalidated. The independent reviewer reproduced a Process Case TOCTOU: the engine consumed one Process Case snapshot, while the proposal could be labeled with a later Process Case revision sampled after execution.
- New model: acquire one coherent `_Authorities` sample before engine execution; pass those exact domain snapshots to the engine; build `ConstructionDefectSourceSnapshot` from those exact records; let the existing guarded save resample current authorities and reject any intervening change before append.
- [x] Add a deterministic RED that changes Process Case inside the injected engine runner and requires fail-closed persistence with no proposal revision appended.
- [x] Apply the minimum start-command repair without changing the engine, schema, trust plane or public surface.
- [x] Run the focused causal test and sibling authority-change suite before forming a new candidate: four concurrent-authority variants, 79 PAT/Report/Delivery tests and two API/bridge surface tests passed.
