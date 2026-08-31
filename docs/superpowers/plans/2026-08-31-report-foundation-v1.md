# Report Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the vendored `executing-plans` workflow to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an upstream-bound canonical judicial report, expert-profile authority, CPC content gates, safe Word-template binding, and professional review lifecycle without allowing prose or rendering to promote source authority.

**Architecture:** `ReportSnapshot` consumes exact Case Analysis, Inspection and Technical Snapshot revisions. Material paragraphs carry an explicit authority class and machine provenance; answers additionally require a question, effective finding, assessed evidence, method and latest professional decision. A separate deterministic template-binding boundary accepts only validated report/profile/template manifests, mutates whitelisted placeholders, and structurally proves that protected OOXML mechanics remain intact.

**Tech Stack:** Python 3.14 dataclasses/JSON Schema/application revision store, synthetic OOXML ZIP fixtures, local API/OpenAPI/product bridge, React/TypeScript workbench, pytest/Vitest.

## Global Constraints

- `REPORT_TEXT_CANNOT_PROMOTE_SOURCE_AUTHORITY = TRUE`.
- Authority classes are exactly `ALLEGED`, `DECIDED_BY_COURT`, `DOCUMENTED`, `OBSERVED`, `MEASURED`, `TECHNICALLY_FOUND`, `PROFESSIONALLY_CONCLUDED`.
- Article 319 is a process-context completeness matrix; Article 473 is a binding delivery-content gate.
- Default profile is `JUSTICA_PLURAL_CHAPTER_4`, Arial 11, justified, 1.15 spacing, 1.25 cm first-line indent, A4, 2/2/3/2 cm margins; court overrides remain explicit.
- Expert identity comes only from the canonical master profile.
- Drafts remain editable; only explicit professional approval may create an approved report, and no report becomes a delivery artifact automatically.
- Synthetic fixtures only; no `referencias/privadas` access and no external egress.
- One mutation owner per shared boundary; full terminal assurance only on the final frozen HEAD.

## Causal DAG and critical path

`ExpertProfile + upstream bindings -> canonical report graph -> CPC/traceability gates -> revision lifecycle -> template binding -> API/UI -> terminal review`.

Safe parallel lanes after the graph contract freezes: JSON Schema/fixtures, OOXML structural tests, and read-only UI/API boundary mapping. Mutation ownership remains domain owner for semantic types, application owner for persistence/gates, document owner for OOXML, and frontend owner for presentation.

## Pre-terminal adversarial matrix

- Text claims a higher authority than its linked upstream source.
- Answer cites a proposal, rejected/stale finding, wrong question, wrong evidence/method, or superseded decision.
- CPC 473 passes with a required section missing or placeholder content.
- Article 319 context treats absent data as inferred data.
- Profile data is duplicated or overridden inside a report/template.
- Draft/reviewed report becomes approved without a professional decision, or an old approval survives upstream change.
- Template binding removes/duplicates bookmarks, fields, styles, content controls, numbering, macros, or canonical single-source placeholders.
- Captioned image lacks an alt description; TOC/page/figure/table fields disappear.
- Workspace or revision identity crosses boundaries; private egress becomes possible.

---

### Task 1: Canonical report graph, expert profile, schema and synthetic fixture

**Files:**
- Create: `scripts/backend_contract/report_foundation.py`
- Create: `schemas/report-snapshot-v1.schema.json`
- Create: `tests/fixtures/report-snapshot-v1.json`
- Modify: `tests/fixtures/core-fixtures.json`
- Create: `tests/test_report_foundation_v1.py`

**Interfaces:**
- Produces `ExpertMasterProfile`, `ReportSourceSnapshot`, `ReportSection`, `ReportClaim`, `ReportAnswer`, `ReportReviewDecision`, `ReportCoverage`, and `ReportSnapshot` plus strict mapping serializers.
- Every material claim carries exact authority classification and typed provenance; report answers reference an effective finding and preserve its full technical chain.

- [ ] Write tests that fail because the report module does not exist and pin every required model, strict unknown-key rejection, unique identities, canonical section ordering, editorial defaults, and synthetic fixture/schema parity.
- [ ] Run `python -m pytest tests/test_report_foundation_v1.py -q` and preserve the import RED.
- [ ] Implement the minimum immutable graph and strict mapper; derive coverage rather than trusting flags.
- [ ] Add adversarial tests proving text cannot upgrade authority, profile fields cannot be duplicated, legal conclusions/final delivery fields are rejected, and stale or non-effective technical findings cannot support conclusions or answers.
- [ ] Re-run focused tests and commit `feat(stage7): add canonical report authority graph`.

### Task 2: CPC gates, upstream-bound persistence, approval and reopen

**Files:**
- Create: `scripts/backend_contract/application/report_foundation.py`
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `tests/test_report_foundation_v1.py`

**Interfaces:**
- Consumes exact latest Case Analysis, Inspection, Technical Snapshot and Expert Profile identities/digests.
- Produces start/get/save/reopen operations with dependency CAS, Article 319 matrix, binding Article 473 gate, stale propagation and linear professional review decisions.

- [ ] Write failing tests for empty start, exact four-authority binding, context gaps remaining explicit, save CAS, stale propagation, reopen, and rejection of approval when Article 473 or answer traceability fails.
- [ ] Verify the focused REDs.
- [ ] Implement application services so authoring never changes upstream artifacts and approval requires a latest professional decision after every material claim/review input.
- [ ] Add sibling/adversarial tests for decision ties/branches, approval before evidence review, superseded approval, question/finding mismatch, missing mandatory sections and workspace crossing.
- [ ] Run focused application tests and commit `feat(stage7): enforce report content and approval gates`.

### Task 3: Deterministic safe Word template binding

**Files:**
- Create: `scripts/backend_contract/report_template.py`
- Create: `tests/fixtures/report-template-manifest-v1.json`
- Modify: `tests/test_report_foundation_v1.py`

**Interfaces:**
- Consumes validated `ReportSnapshot`, `ExpertMasterProfile`, template bytes and a strict binding manifest.
- Produces DOCX/DOCM bytes only for draft/review artifacts; never marks delivery. Returns an integrity report comparing protected mechanics before/after.

- [ ] Write synthetic in-memory DOCX/DOCM tests that fail for missing binder and assert preservation of content types, macro part (when present), bookmarks, `REF/PAGEREF/TOC/SEQ/PAGE/NUMPAGES`, styles, numbering and content controls.
- [ ] Verify RED.
- [ ] Implement whitelisted placeholder replacement with exact single-source cardinality and no arbitrary prose-to-document path.
- [ ] Add adversarial tests for duplicate canonical fields, absent placeholder, field corruption, path traversal/ZIP bomb limits, image without alt description and unapproved report binding.
- [ ] Verify structural integrity and deterministic output; commit `feat(stage7): bind reports to protected Word templates`.

### Task 4: Local API, OpenAPI, bridge and usable review workbench

**Files:**
- Modify: `contracts/openapi-v1.json`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/product_bridge/transport.py`
- Create: `frontend/src/data/reportSnapshot.ts`
- Create: `frontend/src/workspaces/ReportFoundationView.tsx`
- Create: `frontend/src/workspaces/ReportFoundationView.test.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/styles/shell.css`
- Modify: boundary/API tests.

**Interfaces:**
- Exposes private-token local GET/POST/PUT report snapshot routes and same-origin `/app-api` bridge only.
- UI edits presentation claims and explicit review actions; backend remains sole owner of CPC, authority, coverage and approval derivation.

- [ ] Write failing API/bridge/parser/UI tests for empty/start/loading/error/stale, authority badges, traceability drill-down, CPC gate visibility, master-profile read-only display and default draft state.
- [ ] Verify RED.
- [ ] Implement routes and strict response workspace validation.
- [ ] Implement the report workbench without material domain rules in React and without automatic approval/download.
- [ ] Run Vitest, build, lint and affected Python boundaries; commit `feat(stage7): expose report review foundation`.

### Task 5: Safety gate, independent reviews, terminal assurance and normal delivery

**Files:** all diff files plus this plan.

- [ ] Run change-impact mapping, focused affected suites, schema checks, Ruff, frontend tests/build/lint and `git diff --check`.
- [ ] Execute `PRE_TERMINAL_ADVERSARIAL_MATRIX_V1` and `SHADOW_SYSTEMIC_REVIEW_V2` independently on an exact clean HEAD; repair every P0/P1 with RED-first tests.
- [ ] Freeze the final HEAD and run exactly one full pytest regression and one `python -m scripts.quality.verify_core --full`; keep historical timing debt visible if reproduced.
- [ ] Run independent terminal adjudications concurrently on the frozen SHA.
- [ ] Push, open a PR closing Issue #156, wait for protected CI, merge normally, and run focused post-main acceptance without re-running terminal suites.
- [ ] Stop with `REPORT_FOUNDATION_V1 = COMPLETE`, `NEXT_CANONICAL_STAGE = DELIVERY_FOUNDATION`, and `HUMAN_DECISION_REQUIRED = TRUE`.
