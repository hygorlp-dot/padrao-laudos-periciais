# Field Mobile Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable a minimum offline inspection workflow that reuses the canonical Stage 5 model, preserves original media authority, and synchronizes through explicit revision-aware conflict adjudication.

**Architecture:** A core contract serializes only the scoped inspection snapshot, its planning/source authorities, device session and media manifest. Application services prepare and adjudicate packages against current canonical revisions; infrastructure persists packages and private media locally with exact hashes. The existing Local API and InspectionSession React view expose preparation, offline/sync state and visible conflicts without moving professional judgment into the UI.

**Tech Stack:** Python 3.13+, dataclasses, canonical JSON/SHA-256, existing SQLite/private filesystem repositories, pytest/Hypothesis, React 19, TypeScript, Vitest, CSS.

## Global Constraints

- `OFFLINE != UNTRUSTED`; every package is exact, versioned and hash-bound.
- `SYNC != SILENT_OVERWRITE`; material divergence returns visible conflicts.
- `MOBILE_CAPTURE != PROFESSIONAL_CONCLUSION`; packages contain field records only.
- `DEVICE_STATE != CANONICAL_SERVER_STATE`; packages retain base authority and device identity.
- `PHOTO_PREVIEW != ORIGINAL_EVIDENCE`; only original private bytes and SHA-256 are authoritative.
- Reuse `InspectionSession` and its Stage 5 record types; no mobile-only evidence model.
- Synthetic fixtures only; no cloud/network egress or external service.
- UX uses large controls, minimum typing, explicit offline/sync status and reduced-motion support.

---

### Task 1: Canonical Offline Package Contract

**Files:**
- Create: `scripts/backend_contract/field_mobile.py`
- Create: `schemas/offline-inspection-package-v1.schema.json`
- Create: `tests/test_field_mobile_foundation_v1.py`
- Modify: `config/schema-versions.json`

**Interfaces:**
- Consumes: `InspectionSession`, `inspection_session_to_mapping`, and `inspection_session_from_mapping` from Stage 5.
- Produces: `OfflineInspectionPackage`, `OfflineMediaManifest`, `offline_package_from_mapping`, `offline_package_to_mapping`, and canonical package bytes/hash helpers.

- [ ] **Step 1: Write failing contract tests** for exact fields, workspace/inspection/plan/source binding, device/session/package revisions, canonical Stage 5 round-trip, unknown fields, wrong workspace and malformed media SHA-256.
- [ ] **Step 2: Run** `python -m pytest tests/test_field_mobile_foundation_v1.py -q` and confirm RED because `field_mobile` does not exist.
- [ ] **Step 3: Implement immutable dataclasses and exact mapping** with schema version `1.0.0`, positive revisions, timezone-aware timestamps, unique media identities and `InspectionSession` validation delegated to Stage 5.
- [ ] **Step 4: Add the JSON Schema and schema registry entry** with exact object shapes and no additional properties.
- [ ] **Step 5: Run focused contract/schema tests** and commit `feat(stage12): add canonical offline inspection package`.

### Task 2: Local Offline Store and Media Authority

**Files:**
- Create: `scripts/backend_contract/infrastructure/field_mobile.py`
- Modify: `tests/test_field_mobile_foundation_v1.py`
- Modify: `tests/test_private_case_storage_v1.py`

**Interfaces:**
- Consumes: canonical package bytes and existing `LocalPrivateContentStore` controls.
- Produces: `OfflineInspectionStore.create(root)`, `save(package, media)`, `reopen(package_id)`, `close()`, and `OfflinePackageEnvelope`.

- [ ] **Step 1: Write failing storage tests** proving offline reopen after process restart, exact original media bytes/hash, restrictive local-only roots, workspace isolation, duplicate media rejection, corrupted package/media fail-closed and zero network imports.
- [ ] **Step 2: Run focused tests and confirm RED** because the store is absent.
- [ ] **Step 3: Implement a device-local store** that uses canonical JSON plus the existing private-content custody for originals, writes controls with complete-write/fsync semantics, and verifies package hash, media manifest and Stage 5 deserialization on every reopen.
- [ ] **Step 4: Add adversarial path tests** for UNC/device paths, symlink/reparse ancestry, replacement, truncation, hardlinks and cross-workspace media.
- [ ] **Step 5: Run focused persistence/private tests** and commit `feat(stage12): persist verified offline inspection packages`.

### Task 3: Revision-Aware Sync and Replay Protection

**Files:**
- Create: `scripts/backend_contract/application/field_mobile.py`
- Modify: `scripts/backend_contract/application/ports.py` only if an existing generic operation cannot express the service.
- Modify: `tests/test_field_mobile_foundation_v1.py`

**Interfaces:**
- Consumes: current planning/inspection artifact revisions, canonical offline package, exact private media authority and existing `SaveInspectionSession(expected_revision=...)`.
- Produces: `PrepareOfflineInspection`, `AdjudicateOfflineInspectionSync`, `SyncDecision`, `SyncConflict`, and `SyncConflictKind`.

- [ ] **Step 1: Write failing preparation tests** proving minimum package scope, exact plan/source/session binding and no technical findings, report, budget or unrelated private content.
- [ ] **Step 2: Write failing sync matrix tests** for same-item concurrent edit, stale plan, changed source, deleted item, duplicate media, workspace mismatch, device replay and clean unchanged-base acceptance.
- [ ] **Step 3: Confirm RED**, then implement deterministic adjudication that returns conflicts without mutation; only a conflict-free package may call canonical save with the exact expected revision.
- [ ] **Step 4: Add replay receipt as an append-only artifact** keyed by package/device session, and prove a second submission fails visibly without changing inspection history.
- [ ] **Step 5: Add property tests** for order invariance, irrelevant unrelated workspace changes, no silent loss and media manifest permutation.
- [ ] **Step 6: Run application/Stage 5 tests** and commit `feat(stage12): adjudicate revision-aware field sync`.

### Task 4: Local API and Field UX

**Files:**
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `tests/test_local_api_v1.py`
- Modify: `frontend/src/data/inspectionSession.ts`
- Modify: `frontend/src/workspaces/InspectionSessionView.tsx`
- Modify: `frontend/src/workspaces/InspectionSessionView.test.tsx`
- Modify: `frontend/src/styles/shell.css`

**Interfaces:**
- Consumes: prepare/sync application services and existing inspection envelope.
- Produces: `POST /v1/workspaces/{id}/inspection-session/offline-packages`, `POST /v1/workspaces/{id}/inspection-session/offline-sync`, typed client methods, and visible offline/sync UI state.

- [ ] **Step 1: Write failing Local API tests** for exact DTOs, workspace mismatch, stale/replay conflict response, no mutation on conflict and sanitized errors.
- [ ] **Step 2: Write failing React tests** for offline-ready status, pending sync, conflict list, retry, 44px-equivalent field controls and no professional-conclusion language.
- [ ] **Step 3: Confirm RED**, then wire the two endpoints and typed data functions without adding remote URLs or background egress.
- [ ] **Step 4: Implement the field status strip and responsive capture layout**: checklist first, sticky save/sync actions, explicit `Sem conexão`, `Salvo neste dispositivo`, `Conflito requer revisão`; frequent capture actions remain instant.
- [ ] **Step 5: Add only functional state transitions** at 180ms using opacity/transform and a `prefers-reduced-motion` zero-duration path; no looping or decorative motion.
- [ ] **Step 6: Run Vitest, TypeScript build and Local API tests** and commit `feat(stage12): expose offline field workflow`.

### Task 5: Adversarial Matrix and Terminal Assurance

**Files:**
- Modify: `tests/test_field_mobile_foundation_v1.py`
- Modify: `docs/superpowers/plans/2026-08-31-field-mobile-foundation-v1.md` only to mark executed evidence.

**Interfaces:**
- Consumes: complete Stage 12 diff.
- Produces: frozen reviewed HEAD and acceptance evidence.

- [ ] **Step 1: Run change-impact mapping** and all boundary-selected tests.
- [ ] **Step 2: Execute adversarial matrix** covering package tampering, private-media substitution, replay, concurrent edits, stale authorities, deleted items, device/session mismatch, path aliases and offline reopen.
- [ ] **Step 3: Run independent PR review and systemic audit** on the exact frozen HEAD; repair any P0/P1 through a new RED test and invalidate stale reviews.
- [ ] **Step 4: Run one full pytest regression, frontend test/build, Ruff/diff checks and one `python -m scripts.quality.verify_core --full` on the stable HEAD.
- [ ] **Step 5: Push, open PR closing Issue #164, monitor protected CI, merge normally, verify post-main and stop for the required human decision.

## Self-Review

- Spec coverage: offline scope/binding, all Stage 5 capture classes, media originals/hash, revision-aware conflicts, replay, isolation, reopen, no egress and mobile UX are each owned by Tasks 1–4.
- No placeholder behavior: every conflict and gate has an explicit test target and owner.
- Type consistency: package → store → prepare/adjudicate → Local API/UI uses the same `OfflineInspectionPackage` and canonical `InspectionSession` throughout.
- Critical path: Task 1 → Task 2/Task 3 → Task 4 → Task 5. Tasks 2 and 3 may proceed as independent read-only/mutation boundaries once Task 1 is committed.
