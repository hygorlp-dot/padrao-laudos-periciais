# Delivery Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the vendored `executing-plans` workflow to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finalize and deliver immutable DOCX/DOCM/PDF packages whose bytes are exactly bound to approved upstream snapshots, with SHA-256 verification, explicit professional approval, stale propagation, and append-only revision history.

**Architecture:** A canonical `DeliverySnapshot` records exact workspace, source, Case Analysis, Planning, Inspection, Technical Findings and Report revision/digest bindings plus template identity, renderer version, professional decisions and an explicit package manifest. Rendering is a protected private-storage boundary that may produce candidate bytes but cannot finalize them. Finalization verifies every manifest entry and records hashes; delivery is a later explicit transition. Any authoritative dependency mismatch derives `STALE`, while correction/reissue creates a new revision and never overwrites delivered bytes.

**Tech Stack:** Python 3.14 dataclasses/JSON Schema/application revision store, deterministic OOXML ZIP processing, local LibreOffice conversion adapter, SHA-256 private-content verification, local API/OpenAPI/product bridge, React/TypeScript, pytest/Vitest.

## Global Constraints

- `DELIVERY_ARTIFACT = EXACT_APPROVED_SNAPSHOT`.
- Finalization and delivery are explicit professional actions; rendering, opening, downloading or finding existing bytes never promotes state.
- Authoritative bindings include workspace, source, Case Analysis, Planning, Inspection, Technical Findings and Report exact identities/revisions/digests, plus template identity, rendering version and professional approval.
- A changed authoritative dependency derives `STALE`; stale records are not silently regenerated or kept final.
- Delivered bytes are immutable. Reissue creates a new revision and preserves every prior record and artifact hash.
- All artifact bytes remain in the existing private filesystem boundary; no external egress or court filing automation.
- Synthetic fixtures only; never access `referencias/privadas`.
- Backend owns lifecycle, hash verification, workspace isolation and stale derivation; the frontend only presents commands and results.
- One mutation owner per shared boundary; one full terminal assurance on the stable frozen HEAD.

## Causal DAG and critical path

`exact authority graph -> canonical delivery state machine -> append-only persistence/stale reconciliation -> protected rendering/private bytes -> package finalization/hash verification -> API/UI -> terminal review`.

Safe parallel lanes after the graph freezes: schema/fixture parity, DOCX/PDF renderer threat tests, and read-only API/UI boundary mapping. Mutation ownership remains domain owner for semantic types, application owner for lifecycle/CAS, renderer owner for document bytes, infrastructure owner for private storage, and frontend owner for presentation.

## Pre-terminal adversarial matrix

- Report approval or any upstream revision/digest differs after rendering/finalization/delivery.
- Existing output bytes or a successful download silently promote a delivery state.
- Finalization accepts a missing, extra, reordered, altered or cross-workspace package entry.
- SHA-256 is trusted from client metadata instead of recomputed from reopened private bytes.
- A delivered filename/content identifier is overwritten or reused for different bytes.
- Reissue erases, mutates or hides the superseded delivery and its manifest.
- DOCX/DOCM loses protected OOXML mechanics; DOCM macro identity changes; PDF is empty, malformed or no longer corresponds to the bound source artifact.
- Annex/photo/technical/supporting entries are unlabeled, duplicated or omitted from the explicit manifest.
- Stale delivery is silently regenerated or remains marked current/final.
- Workspace identity, content identifier or artifact bytes cross tenant boundaries.
- API/UI infers approval, exposes private filesystem paths, or implies external court filing.

---

### Task 1: Canonical delivery graph, schema and synthetic fixture

**Files:**
- Create: `scripts/backend_contract/delivery_foundation.py`
- Create: `schemas/delivery-snapshot-v1.schema.json`
- Create: `tests/fixtures/delivery-snapshot-v1.json`
- Modify: `tests/fixtures/core-fixtures.json`
- Create: `tests/test_delivery_foundation_v1.py`

- [x] Write tests that fail because the delivery module does not exist and pin strict bindings, lifecycle states, package roles/formats, revision identities, professional decisions and unknown-key rejection.
- [x] Run the focused test and preserve the import RED.
- [x] Implement the minimum immutable graph and strict serializers; derive manifest and lifecycle validity rather than trusting client flags.
- [x] Add adversarial tests for incomplete authority chains, duplicate entries, illegal transitions, client-supplied derived state and delivery fields inside upstream artifacts.
- [x] Run focused tests and commit `feat(stage8): add canonical delivery graph`.

### Task 2: Append-only lifecycle, exact reconciliation and stale propagation

**Files:**
- Create: `scripts/backend_contract/application/delivery_foundation.py`
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `tests/test_delivery_foundation_v1.py`

- [ ] Write failing tests for start/get/reopen, exact latest-authority binding, optimistic concurrency, explicit review/approval/finalize/deliver transitions, stale derivation and reissue/supersede history.
- [ ] Verify focused REDs.
- [ ] Implement application services over `ArtifactRevision`, recomputing current authority digests on every reopen/material command.
- [ ] Add sibling/adversarial tests for authority ties, approval replay, stale approval, silent overwrite, history loss, revision branching and workspace crossing.
- [ ] Run focused application tests and commit `feat(stage8): enforce delivery lifecycle and stale history`.

### Task 3: Protected DOCX/DOCM/PDF rendering and private package integrity

**Files:**
- Create: `scripts/backend_contract/delivery_renderer.py`
- Create: `scripts/backend_contract/infrastructure/local_document_renderer.py`
- Modify: `scripts/backend_contract/infrastructure/private_filesystem.py` only if the existing immutable content API lacks a required safe primitive.
- Modify: `tests/test_delivery_foundation_v1.py`

- [ ] Write failing synthetic tests for approved-report template binding, DOCX/DOCM output, local PDF conversion, package roles, SHA-256 recomputation after reopening, and immutable content identifiers.
- [ ] Verify RED.
- [ ] Implement candidate rendering through the Stage 7 safe template binder, private artifact storage and a timeout-bounded local conversion port; never use external egress.
- [ ] Make finalization reopen every private object, validate format/signature/size, recompute SHA-256 and atomically bind the explicit manifest.
- [ ] Add malformed ZIP/PDF, macro mismatch, conversion failure, byte tampering, filename collision, missing annex and cross-workspace adversarial tests.
- [ ] Render representative synthetic DOCX/PDF fixtures to PNG and inspect all pages when local tooling is available; retain structural checks as independent evidence.
- [ ] Run focused tests and commit `feat(stage8): finalize protected private delivery packages`.

### Task 4: Local API, OpenAPI, bridge and delivery workbench

**Files:**
- Modify: `contracts/openapi-v1.json`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/product_bridge/transport.py`
- Create: `frontend/src/data/deliverySnapshot.ts`
- Create: `frontend/src/workspaces/DeliveryFoundationView.tsx`
- Create: `frontend/src/workspaces/DeliveryFoundationView.test.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/styles/shell.css`
- Modify: affected API/bridge/boundary tests.

- [ ] Complete the required frontend skill references before UI mutation, then write failing API/bridge/parser/UI tests for empty/start/loading/error/stale, exact bindings, manifest, hash verification, explicit transitions, reissue and download.
- [ ] Verify RED.
- [ ] Implement private-token local routes and same-origin bridge commands with strict workspace validation and no filesystem-path disclosure.
- [ ] Implement an accessible delivery workbench that distinguishes render, review, finalize, deliver, stale and reissue; do not imply PJe filing.
- [ ] Run Vitest, typecheck, build, lint and affected Python boundaries; commit `feat(stage8): expose delivery finalization workbench`.

### Task 5: Safety gate, independent reviews, terminal assurance and normal delivery

**Files:** all diff files plus this plan.

- [ ] Run change-impact mapping, focused affected suites, schema checks, Ruff, frontend checks and `git diff --check`.
- [ ] Execute `SIBLING_DEFECT_SWEEP_V2`, the pre-terminal adversarial matrix and a read-only shadow systemic review on an exact clean HEAD; repair every P0/P1 RED-first.
- [ ] Freeze the final HEAD and run exactly one full pytest regression and one `python -m scripts.quality.verify_core --full`; classify historical timing debt without weakening semantic gates.
- [ ] Run independent terminal reviews concurrently on the frozen SHA and retain identifiable evidence.
- [ ] Push, open a PR closing Issue #158, wait for protected CI, merge normally, and run focused post-main acceptance without redundant terminal suites.
- [ ] Stop with `DELIVERY_FOUNDATION_V1 = COMPLETE`, `NEXT_CANONICAL_STAGE = BUDGET_FOUNDATION`, and `HUMAN_DECISION_REQUIRED = TRUE`.
