# Field Mobile Productization Recovery V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the recovery seam between workspace backup/restore and offline Field/Mobile without weakening device revocation, workspace isolation, provenance, or private-data controls.

**Architecture:** Stage 11 backup receives an explicit Stage 12 readiness authority and fails closed while any recoverable, corrupt, or unresolved offline state exists. Successful sync remains the only bridge into portable canonical history; backup verification then proves closure between Inspection media references and private original bytes. Device storage retains authenticated local encryption under an explicitly limited threat model, while an append-only revocation generation enables a new device identity without reviving or migrating the revoked identity.

**Tech Stack:** Python dataclasses, AES-GCM, local filesystem/SQLite repositories, JSON/OpenAPI, React 19, TypeScript, pytest, Vitest.

## Global Constraints

- `PENDING_OFFLINE_DATA + WORKSPACE_BACKUP = FAIL_CLOSED`.
- `DEVICE_KEY` is never serialized into `WorkspaceBackup`.
- `THREAT_MODEL_A = accidental/plaintext exposure`; complete theft of the application storage tree is explicitly not claimed as protected by the current portable-key implementation.
- `REVOKED_DEVICE_ID_NEVER_REVIVES = TRUE`; replacement creates a new identity and storage generation.
- Old pending ciphertext is preserved but remains inaccessible after revocation; no silent migration, deletion, or overwrite.
- Only synchronized canonical Inspection media enter normal workspace backup/restore.
- Synthetic fixtures only; `PRIVATE_EGRESS = FALSE`; no cloud secret service, subprocess, generic native loader, or new trust model.
- Stage 10, Delivery, Budget, timing-gate redesign, cloud sync and PR-D are out of scope.

---

### Task 1: Pending Offline Backup Gate and Synced Media Closure

**Files:**
- Modify: `scripts/backend_contract/infrastructure/productization.py`
- Modify: `scripts/backend_contract/infrastructure/field_mobile.py`
- Test: `tests/test_productization_foundation_v1.py`
- Test: `tests/test_field_mobile_foundation_v1.py`

**Interfaces:**
- Produces: `DeviceOfflineVaultRegistry.assert_workspace_backup_ready(workspace_id) -> None`.
- Changes: `CreateWorkspaceBackup` requires `assert_backup_ready` and calls it before reading workspace state.
- Produces: `_inspection_private_references(payload) -> dict[content_id, sha256]` used by `VerifyWorkspaceBackup`.

- [ ] Add a RED integration test: prepare/update an offline package to revision N+1, call backup with the registry readiness authority, and require `ValueError("pending offline field work must be synchronized before backup")` before any backup bytes are returned.
- [ ] Add RED tests proving corrupt pending inventory also blocks backup and no device key or offline ciphertext is emitted in the workspace backup.
- [ ] Add a RED synchronized path: sync the package, create backup, restore to `RecoveryStaging`, reopen the Inspection snapshot, and verify every photo/video/sketch reference resolves to exact private bytes and SHA-256.
- [ ] Add RED resealing attacks that remove referenced media bytes or replace the referenced private SHA and require `RepositoryIntegrityError` during verification before restore mutation.
- [ ] Implement the readiness authority and mandatory backup dependency; list pending state under the device/workspace lock and fail closed on pending or corrupt entries.
- [ ] Implement Inspection-only private-reference closure in backup verification; do not generalize unrelated artifact semantics.
- [ ] Run `python -m pytest tests/test_productization_foundation_v1.py tests/test_field_mobile_foundation_v1.py -q` and commit `fix: block backups with unresolved offline work`.

### Task 2: Offline Lineage, Corruption Visibility and Retryable Sync

**Files:**
- Modify: `scripts/backend_contract/infrastructure/field_mobile.py`
- Modify: `scripts/backend_contract/application/field_mobile.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `frontend/src/data/fieldMobile.ts`
- Modify: `frontend/src/workspaces/InspectionSessionView.tsx`
- Test: `tests/test_field_mobile_foundation_v1.py`
- Test: `tests/test_local_api_v1.py`
- Test: `frontend/src/workspaces/InspectionSessionView.test.tsx`

**Interfaces:**
- Produces: `PendingOfflineInventory(items, conflicts)` and `DeviceOfflineVault.inventory_pending_packages()`.
- Produces: `mark_superseded(previous_package_id, replacement_package_id)` and `superseding_package_id(package_id)`.
- Produces: `begin_sync(package, expected_revision)`, `complete_sync(package, saved_revision)`, and `recover_interrupted_sync(package, current_record, current_snapshot)` using authenticated local journal records.

- [ ] Add RED tests proving update revisions leave only the newest package sync-eligible while predecessors return visible `SUPERSEDED_PACKAGE` conflicts and remain preserved on disk.
- [ ] Add RED tests with one valid package plus corrupt/truncated package, media, or receipt; inventory must retain the valid item and surface stable corruption conflicts rather than silently dropping data or poisoning all reopen.
- [ ] Add a RED receipt-failure test: canonical save succeeds, final receipt write fails, and the next sync recognizes the exact already-applied package and completes idempotently without a second Inspection revision.
- [ ] Implement authenticated supersession markers and inventory results; update API/UI to expose visible conflicts while reopening the newest valid package.
- [ ] Implement a write-ahead authenticated sync journal before canonical save and idempotent recovery after exact snapshot/hash comparison; contradictory state remains a visible conflict.
- [ ] Run focused Field/API/UI tests and commit `fix: preserve recoverable offline sync lineage`.

### Task 3: Device Threat Model and Revocation Replacement Lifecycle

**Files:**
- Modify: `scripts/backend_contract/infrastructure/field_mobile.py`
- Modify: `scripts/backend_contract/application/field_mobile.py`
- Modify: `scripts/backend_contract/local_api/composition.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `contracts/openapi-v1.json`
- Modify: `frontend/src/data/fieldMobile.ts`
- Modify: `frontend/src/workspaces/InspectionSessionView.tsx`
- Modify: `frontend/src/workspaces/InspectionSessionView.test.tsx`
- Test: `tests/test_field_mobile_foundation_v1.py`
- Test: `tests/test_local_api_v1.py`

**Interfaces:**
- Produces: `DeviceSecurityClassification(threat_model="A", protects_plaintext_at_rest=True, protects_complete_tree_copy=False)`.
- Produces: `DeviceOfflineVaultRegistry.replace_revoked_device(expected_device_id) -> str`.
- Produces: `ReplaceRevokedOfflineDevice.execute(workspace_id, expected_device_id) -> str` and `POST .../offline-device/replace`.

- [ ] Add RED tests explicitly proving a copied complete registry tree contains current portable key authority; assert diagnostics classify Threat Model A and never claim protection against complete directory theft.
- [ ] Add RED lifecycle tests: enroll A → capture/sync → revoke A → restart → A denied → replace with B → B captures/reopens/syncs; A remains denied after restart.
- [ ] Add RED tests for replacement before revocation, wrong/stale expected identity, concurrent replacement, tombstone deletion, and attempts to open old packages with B.
- [ ] Implement append-only revoked-identity tombstones, monotonically increasing device generation, and a generation-isolated vault directory for replacement identities. Preserve legacy generation-1 paths for existing active installations.
- [ ] Keep revocation confirmation explicit and update UI copy to warn that unsynchronized work becomes inaccessible. Add a separate replacement action after revocation; do not animate this high-consequence lifecycle.
- [ ] Run focused backend/OpenAPI/frontend tests and commit `feat: support safe offline device replacement`.

### Task 4: Cross-Workspace and Recovery Adversarial Matrix

**Files:**
- Modify: `scripts/backend_contract/application/field_mobile.py`
- Modify: `tests/test_field_mobile_foundation_v1.py`
- Modify: `tests/test_productization_foundation_v1.py`
- Modify: `tests/test_local_api_v1.py`
- Modify: `frontend/src/data/fieldMobile.test.ts`

**Interfaces:**
- Changes: `UpdateOfflineInspection` validates private metadata workspace as well as SHA-256.
- Produces: named acceptance matrix tests for Field/Mobile recovery.

- [ ] Add RED test where a foreign-workspace private-content dependency returns identical media bytes/hash; require rejection before the offline revision is saved.
- [ ] Add matrix coverage for inspection mismatch, expected package revision conflict, package/media tamper, missing key, wrong device, stale plan/source, concurrent edit, replay, revoked replay, cross-workspace package/media, and duplicate canonical media SHA.
- [ ] Add a no-egress guard proving Field/Mobile frontend URLs are same-origin relative and backend boundaries import no network client.
- [ ] Implement only the cross-workspace validation needed by the RED test; retain existing fail-closed behavior for already-green attacks.
- [ ] Run Field/Productization/API/frontend focused suites and commit `test: close field mobile recovery adversarial matrix`.

### Task 5: Backup Portability Version Semantics

**Files:**
- Modify: `scripts/backend_contract/infrastructure/productization.py`
- Modify: `tests/test_productization_foundation_v1.py`

**Interfaces:**
- Produces: `BACKUP_PORTABILITY_RELEASE` and `SUPPORTED_BACKUP_PORTABILITY_RELEASES`.
- Compatibility aliases: `PRODUCT_RELEASE_VERSION` and `SUPPORTED_PRODUCT_RELEASES` remain temporarily equal to the clarified constants so persisted values do not change.

- [ ] Add RED assertions that both declared portability releases verify after correct resealing and unknown releases fail closed.
- [ ] Rename/document internal semantics without changing serialized `product_release`, compatibility values, or storage format version.
- [ ] Run Productization tests and commit `docs: clarify backup portability release semantics`.

### Task 6: PR-C Terminalization

**Files:**
- Modify: this plan only to append exact execution evidence if governance requires it.

**Interfaces:**
- Produces: reviewed exact terminal SHA, PR closing #171, protected-main merge SHA and fresh post-main acceptance.

- [ ] Run sibling-defect sweep and the complete cross-stage adversarial matrix.
- [ ] Freeze exact HEAD; run one full backend regression, frontend tests/typecheck/lint/build, Ruff and `git diff --check`.
- [ ] Apply `repository-safety-gate` and run one `python -m scripts.quality.verify_core --full`; classify historical duration debt without retrying unchanged HEAD.
- [ ] Run independent PR review and independent systemic audit concurrently on the exact frozen HEAD; any material repair invalidates terminal evidence.
- [ ] Push, open PR with `Closes #171`, wait for protected CI, merge normally, and run fresh post-main focused recovery/orphan-media/device-lifecycle verification.
- [ ] Start PR-D only if PR-C post-main passes with P0=0/P1=0; otherwise stop on the unresolved material finding.

## Self-Review

- Spec coverage: C1 through C6, the required adversarial matrix, explicit threat-model classification, replacement lifecycle, synced backup/restore and orphan-media closure each have an owner and RED test.
- Scope: no Stage 10, Delivery/Budget redesign, trust model, subprocess, cloud service or timing-gate mutation appears.
- Type consistency: registry readiness feeds backup; sync produces canonical Inspection history; backup verifier resolves only canonical Inspection media; replacement never consumes old ciphertext.
- Placeholder scan: no deferred implementation placeholder remains.
