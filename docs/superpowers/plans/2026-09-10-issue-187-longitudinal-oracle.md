# Issue 187 Longitudinal Product Oracle Implementation Plan

> **For agentic workers:** Execute each task with a RED/GREEN checkpoint and preserve the synthetic-only boundary.

**Goal:** Prove the complete synthetic product journey through the normal ProductBridge surface, including PJe intake, authority/revision continuity, Delivery/Word, Budget, Backup, Recovery and Reopen, and leave a reproducible evidence package for Human RC preparation.

**Architecture:** Reuse the existing Local API, ProductBridge, application services, persistence, and synthetic fixtures. Extend only the oracle tests and evidence/documentation unless a test exposes a causal product defect; each defect gets its own Issue/PR and returns to this oracle afterward. The oracle must compare immutable snapshots and hashes across a fresh runtime after Recovery rather than relying on in-memory state.

**Tech Stack:** Python, pytest, existing `build_product_runtime`, ProductBridge HTTP helpers, SQLite/private filesystem adapters, synthetic JSON fixtures, existing protected CI and `verify_core` gates.

## Global Constraints

- `provenance = SYNTHETIC` only; never access real case files, PJe, or external services.
- Normal operations use `Frontend/Data Layer -> /app-api -> ProductBridge -> Local API -> Application -> Domain/Persistence` where the route exists.
- `NORMAL_OPERATION_REQUIRES_TERMINAL = 0` must be demonstrated, not assumed.
- Preserve proposal/effective authority, snapshot immutability, provenance, workspace isolation, fail-closed stale propagation, and no silent overwrite.
- Do not add a second framework or production tooling predecessor; no production mutation without a reproduced RED.
- A material defect becomes one causal Issue/PR and must return to this oracle after protected merge.

---

### Task 1: Rehydrate and freeze the existing oracle baseline

**Files:**
- Read: `tests/test_product_integration_oracle_v1.py`
- Read: `tests/test_product_bridge_v1.py`
- Read: `tests/test_backup_recovery_reachability_v1.py`
- Read: `tests/test_pje_workspace_bridge_v1.py`
- Read: `tests/test_pje_backup_semantic_closure_v1.py`
- Create: `artifacts/issue-187/BASELINE.md` (synthetic execution evidence only)

**Interfaces:**
- Consumes the existing synthetic fixture builders and ProductBridge/local runtime helpers.
- Produces a frozen baseline with exact SHA, selected test commands, pass/skip counts, and identified surface gaps.

- [ ] Run the existing longitudinal, bridge, PJe, backup/recovery, and semantic-closure suites on protected `main`.
- [ ] Record only reproducible facts: command, exit code, counts, platform, and exact HEAD.
- [ ] Confirm whether the existing D1-D11 test uses ProductBridge or Local API directly and classify any missing normal-surface proof as a test gap, not a product failure.
- [ ] Commit the baseline evidence without private data.

### Task 2: Add the single normal-surface synthetic longitudinal oracle

**Files:**
- Modify: `tests/test_product_integration_oracle_v1.py`
- Reuse: `tests/test_product_bridge_v1.py` request/build helpers and existing synthetic fixture constructors.

**Interfaces:**
- Consumes `build_product_runtime`, ProductBridge HTTP requests, existing report/template/budget payload builders, and synthetic PJe material bytes.
- Produces one test that records stable IDs/digests after each stage and asserts the same values after fresh-runtime Recovery/Reopen.

- [ ] Write one failing test that starts `build_product_runtime`, creates a workspace, imports a synthetic PJe document through `/app-api`, verifies PJe intake/parties/representation/metadata, and continues through Case Analysis, Planning, Inspection, Evidence, PAT, Technical Findings, Report, Delivery, Budget and Backup.
- [ ] Drive every available operation through ProductBridge; use direct Local API only for contracts not exposed by the normal surface and mark that exception explicitly.
- [ ] Close the first runtime, create a fresh runtime/process context, perform Recovery through ProductBridge, reopen the workspace, and compare workspace identity, revisions, approved PAT, findings, Report, Delivery, Budget, evidence/media IDs and relevant hashes.
- [ ] Assert `NORMAL_OPERATION_REQUIRES_TERMINAL == 0`, synthetic provenance, no cross-workspace mutation, no false final PDF claim, and no silent overwrite.
- [ ] Run the new test and verify a meaningful RED caused by the missing surface or invariant, not by a test defect.

### Task 3: Implement the minimum causal product repair, if Task 2 finds one

**Files:**
- Modify only the production boundary identified by the RED.
- Test: the failing oracle test plus a focused regression in the nearest existing suite.

**Interfaces:**
- Consumes the exact failing request/response and root-cause evidence from Task 2.
- Produces the smallest production change preserving existing authority, privacy and route allowlists.

- [ ] Identify the root cause from the failing boundary; do not repair by broadening a proxy, adding a generic route, or weakening a gate.
- [ ] Implement the smallest fix after the RED is recorded.
- [ ] Run the focused test GREEN, then adversarial sibling cases for wrong method/path/workspace/revision/authority and partial failure.
- [ ] Create a dedicated causal Issue/PR if the finding is P0/P1 or material; freeze the oracle branch until the repair is merged and return here afterward.

### Task 4: Complete oracle adversarial and longitudinal assertions

**Files:**
- Modify: `tests/test_product_integration_oracle_v1.py`
- Reuse: existing backup/recovery and authority test modules.

**Interfaces:**
- Consumes the green end-to-end fixture and persisted snapshot manifest.
- Produces deterministic assertions for stale upstream, stale PAT/Report/Delivery, wrong revision/workspace/professional, duplicate request, partial failure, interrupted operation, restart, recovery and stale artifact propagation.

- [ ] Add adversarial cases only where the single fixture can prove the invariant without introducing a second model.
- [ ] Assert `REPORT_STALE => DELIVERY_STALE`, `VERIFIED != PROMOTABLE`, `STAGED != PROMOTED`, explicit human promotion, cleanup-intent reconstruction and fail-closed unsupported recovery semantics.
- [ ] Verify private egress remains false and no private bytes leave the workspace boundary.

### Task 5: Terminal assurance and evidence package

**Files:**
- Create: `artifacts/issue-187/ORACLE_REPORT.md`
- Modify: `docs/PRODUCT_MATURITY_REPORT_V1.md`, `config/product-maturity-v1.json`, `README.md`, and `docs/manual-operacional.md` only after the oracle is genuinely PASS.

**Interfaces:**
- Consumes the frozen oracle HEAD, protected CI verdicts, independent reviewer/auditor evidence, and post-main proof.
- Produces the roadmap Item 2 status and Human RC preparation inputs without claiming Human RC itself.

- [ ] Run focused/change-impact tests during RED/GREEN; run one full terminal assurance on the stable frozen HEAD.
- [ ] Apply repository safety, privacy, Ruff/compile, `verify_core --full`, protected CI, independent reviewer, systemic auditor, and post-main verification.
- [ ] Update historical versus current-effective maturity scores only after all acceptance invariants are evidenced.
- [ ] Prepare synthetic RC fixture, startup instructions and human checklist; stop only when all `HUMAN_RC_READY` predicates are actually PASS.
