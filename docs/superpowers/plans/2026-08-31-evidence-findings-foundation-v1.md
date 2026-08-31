# Evidence and Technical Findings Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `executing-plans`; execute every material behavior with strict RED/GREEN and review the frozen terminal HEAD independently. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reopenable, workspace-isolated technical snapshot whose only valid progression is source/observation → assessed evidence → applied method → technical finding proposal → explicit professional decision/effective finding.

**Architecture:** A source-neutral `technical_findings` domain owns strict graph identities, promotion/review states, method traceability, proposal/effective-finding separation, conflicts, uncertainty and derived coverage. The application boundary atomically binds a snapshot to the latest Case Analysis and Inspection Session revisions/digests and marks it stale when either authority changes. Existing artifact revisions remain persistence authority; Local API/product bridge expose a same-origin DTO and React presents a restrained evidence-chain workbench with no material domain logic.

**Tech Stack:** Python dataclasses and enums, JSON Schema 2020-12, existing artifact revision/application/Local API layers, OpenAPI 3.1, React 19, TypeScript, Vite/Vitest and existing CSS.

## Global Constraints

- Issue #154; branch `feat/154-evidence-findings-foundation-v1`; base `64058f0bc0f492e212c9fb87c8942af7262809c7`.
- Synthetic fixtures only; never access `referencias/privadas/`; `PRIVATE_EGRESS = FALSE`.
- Mandatory chain: `SOURCE / OBSERVATION -> EVIDENCE -> METHOD -> TECHNICAL_FINDING -> PROFESSIONAL_DECISION`; no silent skip.
- `ALLEGATION != EVIDENCE`; `DOCUMENT != EVIDENCE_BY_ITSELF`; `OBSERVATION != TECHNICAL_FINDING`; `MEASUREMENT != TECHNICAL_FINDING`.
- `METHOD_OUTPUT != PROFESSIONAL_DECISION`; `TECHNICAL_FINDING_PROPOSAL != PROFESSIONAL_DECISION`; `AI_PROPOSAL` is never effective by itself.
- `TECHNICAL_FINDING != LIABILITY`; no legal fault, contractual responsibility, judicial outcome or polished report answer.
- Preserve supporting and contrary evidence, unresolved/resolved conflicts, limitations and uncertainty.
- Preserve `PROFESSIONAL_OVERRIDE > ENGINE_DECISION > SOURCE_VALUE`; only an explicit professional decision makes a material technical conclusion effective.
- Question links point to findings; they never contain or generate an auto-final answer.
- UI material logic stays in the domain/application boundary. High-frequency and keyboard interactions have no motion; existing reduced-motion behavior remains authoritative.

## Causal DAG and critical path

`latest Case Analysis revision/digest + latest Inspection Session revision/digest` → `immutable TechnicalSourceSnapshot` → `explicit EvidenceSourceLink + EvidenceAssessment` → `reviewed EvidenceItem` → `MethodInput + MethodApplication + MethodOutput` → `TechnicalFindingProposal` → `dependencies/conflicts/limitations/uncertainty/question links` → `ProfessionalDecision` → `effective TechnicalFinding` → `derived TechnicalCoverage` → `atomic save/reopen/stale reconciliation` → `Local API/Bridge/OpenAPI` → `evidence-chain workbench` → `adversarial matrix` → `terminal assurance/reviews/PR/post-main`.

The graph invariant and professional-authority boundary is the critical path. Schema/fixture may proceed once entity names freeze; API and UI wait for the DTO. One mutation owner controls the shared persistence/API/route boundaries.

## Pre-terminal adversarial matrix

- Direct document/observation/measurement promotion without assessment: reject.
- Evidence with no exact source identity, relevance, proposition, limitation review or review state: reject.
- Method with missing/unreviewed evidence input, procedure, parameters, output, limitation, normative provenance or execution revision: reject.
- Proposal without reviewed evidence and applied method: reject.
- Effective finding without owned approved/modified professional decision: reject.
- AI/engine/source decision outranking explicit professional override: reject.
- Contrary evidence omitted, dangling or hidden by a resolved conflict without reasoning/decision: reject.
- Finding without explicit limitation and uncertainty records (including explicit none with rationale): reject.
- Question link containing answer/final prose or targeting a proposal rather than an effective finding: reject.
- Cross-workspace, cross-owner, duplicate, dangling or stale graph links: reject.
- Reordered irrelevant evidence must not change effective findings or coverage.
- Removing essential evidence must stale/block dependent method/finding effectiveness.

---

### Task 1: Canonical technical reasoning graph

**Files:**
- Create: `scripts/backend_contract/technical_findings.py`
- Create: `schemas/technical-snapshot-v1.schema.json`
- Create: `tests/fixtures/technical-snapshot-v1.json`
- Create: `tests/test_technical_findings_foundation_v1.py`

**Interfaces:**
- Produces: `TechnicalSnapshot`, every canonical entity named by the authorization, `technical_snapshot_from_mapping(value)`, `technical_snapshot_to_mapping(snapshot)`.
- Consumes later: strict mapping shared by application, schema, API and UI.

- [ ] **Step 1: Write failing fixture/round-trip tests.** Import all required entities and deserialize a hand-authored synthetic chain with one supporting and one contrary evidence item, one method, one proposal, one explicit decision and one effective finding.
- [ ] **Step 2: Run RED.** Run `python -m pytest tests/test_technical_findings_foundation_v1.py -q`; expect import failure for `scripts.backend_contract.technical_findings`.
- [ ] **Step 3: Implement strict identities/enums/dataclasses and mapping.** Include explicit review/origin/decision states and exact source, owner and revision links; reject unknown keys and non-timezone timestamps.
- [ ] **Step 4: Add and observe RED adversarial graph tests.** Cover silent promotion, dangling/cross-owner links, missing contrary evidence, skipped method, decisionless effectiveness, legal/final-answer fields, dishonest coverage and precedence inversion.
- [ ] **Step 5: Implement graph validation and derived coverage minimally.** Effective findings must be derivable from owned proposal plus latest explicit `APPROVE`/`MODIFY` professional decision; `REJECT` never creates an effective finding.
- [ ] **Step 6: Publish strict schema parity and synthetic fixture registry entry.** Runtime and schema must accept/reject the same enum and required-field boundaries.
- [ ] **Step 7: Run focused GREEN, Ruff and `git diff --check`; commit `feat: add canonical technical reasoning graph`.**

### Task 2: Upstream authority, persistence, reopen and staleness

**Files:**
- Create: `scripts/backend_contract/application/technical_findings.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `tests/test_technical_findings_foundation_v1.py`

**Interfaces:**
- Produces: `StartTechnicalSnapshot.execute(workspace_id)`, `GetTechnicalSnapshot.execute(workspace_id)`, `SaveTechnicalSnapshot.execute(workspace_id, snapshot, expected_revision)`.
- Consumes: latest Case Analysis and Inspection Session records/snapshots plus artifact revision repository and shared authority guard.

- [ ] **Step 1: Write RED tests for start bindings.** A start operation must capture exact upstream IDs, revisions, checksums/digests and source revision while creating an empty, not-effective chain; honestly partial Vistoria remains allowed.
- [ ] **Step 2: Write RED tests for atomic save/reopen/isolation.** Cover optimistic conflict, workspace mismatch, missing upstream, stale upstream, exact round-trip and shared authority-guard use.
- [ ] **Step 3: Implement immutable upstream binding and artifact persistence.** Add expected dependency records for both upstream authorities; never copy private media bytes.
- [ ] **Step 4: Write RED stale-propagation tests.** Changing Case Analysis or Vistoria identity/revision/digest must mark reopened TechnicalSnapshot stale and prohibit save/professional effectiveness.
- [ ] **Step 5: Implement read-time reconciliation and save-time fail-closed validation.** Recompute chain coverage and authority every save; never trust persisted coverage/effective status alone.
- [ ] **Step 6: Run focused application/storage GREEN, Ruff and `git diff --check`; commit `feat: persist upstream-bound technical snapshots`.**

### Task 3: Local API, bridge and OpenAPI

**Files:**
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/product_bridge/transport.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `tests/test_local_api_v1.py`
- Modify: `tests/test_product_bridge_v1.py`
- Modify: architecture/network allowlist tests only where the new canonical client is the demonstrated cause.

**Interfaces:**
- Produces: private-token `GET/POST/PUT /v1/workspaces/{workspace_id}/technical-snapshot` and same-origin `/app-api` mirror.
- Consumes: strict application DTO conversion and Stage 2 services.

- [ ] **Step 1: Write RED route tests.** Cover start/get/save, strict request keys, invalid revision/workspace, stale upstream, missing service and sanitized errors.
- [ ] **Step 2: Implement Local API routes through application-owned serializers.** Transport must not import the domain directly; preserve payload/token limits and no-store responses.
- [ ] **Step 3: Write RED bridge allowlist tests and implement exact GET/POST/PUT mapping.** Reject suffixes, unsupported verbs and malformed workspace identities.
- [ ] **Step 4: Publish OpenAPI schema refs and semantic boundary metadata.** Assert the published contract references `technical-snapshot-v1.schema.json` exactly.
- [ ] **Step 5: Run focused API/bridge/architecture GREEN, Ruff and `git diff --check`; commit `feat: expose technical snapshot API`.**

### Task 4: Evidence-chain workbench

**Files:**
- Create: `frontend/src/data/technicalSnapshot.ts`
- Create: `frontend/src/workspaces/TechnicalFindingsView.tsx`
- Create: `frontend/src/workspaces/TechnicalFindingsView.test.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/routes/routeCatalog.ts` only for accurate Stage 6 copy/next-stage link.
- Modify: `frontend/src/styles/shell.css`

**Interfaces:**
- Produces: a strict same-origin client and `/evidencias` workbench.
- Consumes: TechnicalSnapshot envelope and POST/PUT API; no material promotion/authority computation in React.

- [ ] **Step 1: Write RED parser/view tests.** Cover loading, honest empty/start, error/retry, stale warning, reopen, source inventory, evidence assessment, contrary evidence, method trace, proposal versus effective finding, uncertainty/limitations, question links and explicit professional decision.
- [ ] **Step 2: Implement strict client parsing and no-store operations.** Reject malformed envelopes and keep all fetches under same-origin `/app-api`.
- [ ] **Step 3: Implement the workbench with progressive disclosure.** Simple level shows chain status; technical level edits structured records; audit level exposes IDs/revisions/provenance. Labels must state that proposals are not effective conclusions.
- [ ] **Step 4: Keep professional authority explicit.** Approval/modification/rejection requires named professional, reason and timestamp supplied through the save DTO; no default approval and no AI auto-action.
- [ ] **Step 5: Apply the motion frequency gate.** Use no animation for record editing/keyboard actions; reuse only existing fast state transitions and reduced-motion rules. No new dependency.
- [ ] **Step 6: Run focused Vitest, full frontend tests, build, lint and accessibility/motion self-review; commit `feat: deliver evidence-chain workbench`.**

### Task 5: Adversarial closure and normal protected delivery

- [ ] Run `SIBLING_DEFECT_SWEEP_V2` across source/evidence/method/proposal/decision sibling boundaries and execute the pre-terminal adversarial matrix.
- [ ] Run read-only `SHADOW_SYSTEMIC_REVIEW_V2` before freezing; repair every causal P0/P1 via its own RED/GREEN cycle.
- [ ] Freeze one candidate HEAD; run one full regression and one `python -m scripts.quality.verify_core --full` on that SHA only.
- [ ] Run independent PR review and systemic audit concurrently on the exact frozen HEAD; preserve any strict timing failure visibly and classify causality without redundant reruns.
- [ ] Push, open a protected PR linked with `Closes #154`, await all protected checks and merge normally without bypass.
- [ ] Run focused post-main acceptance on the merge commit; confirm Issue #154 closed and stop for the human decision authorizing `REPORT_FOUNDATION`.
