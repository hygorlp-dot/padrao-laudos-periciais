# Productization Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned, integrity-checked workspace backup and staging restore foundation that preserves every historical revision and private-content provenance without mutating active storage.

**Architecture:** A canonical JSON backup envelope owns release/storage compatibility, workspace identity, append-only artifact revisions, private-content metadata and base64 bytes, plus SHA-256 member hashes and a root digest. Restore validates the complete envelope, supported version window, every checksum, revision sequence, canonical domain deserialization and private metadata before writing only to empty staging repositories; promotion/rollback remain an explicit outer operation, so an active case is never overwritten. Existing SQLite migrations and private filesystem ports remain the storage authorities.

**Tech Stack:** Python 3.14 standard library, immutable application models, SQLite repositories, local private-content store, pytest, JSON Schema.

## Global Constraints

- `OLD_VALID_STATE → MIGRATION → NEW_VALID_STATE`; no silent semantic reinterpretation.
- Historical normative/source snapshots and derived revision history remain byte-semantically immutable.
- Recovery success requires canonical domain deserialization after restore and reopen.
- Supported compatibility window is explicit and finite; future versions fail closed.
- Restore never overwrites active storage; staging failure leaves the active workspace unchanged.
- Synthetic fixtures only; `referencias/privadas/` is never accessed; `PRIVATE_EGRESS = FALSE`.
- Optional SBOM, signing, OSV, CodeQL and C1 automation are out of scope.

---

### Task 1: Compatibility and Migration Contract

**Files:**
- Create: `scripts/backend_contract/productization.py`
- Create: `schemas/workspace-backup-v1.schema.json`
- Create: `tests/test_productization_foundation_v1.py`
- Modify: `config/schema-versions.json`

**Interfaces:**
- Produces: `ProductRelease`, `CompatibilityWindow`, `WorkspaceBackup`, `migrate_backup_mapping(value)`, `workspace_backup_from_mapping(value)`.
- Consumes: canonical payload JSON and existing domain `*_from_mapping` validators.

- [ ] Write RED tests proving V1 roundtrip, deterministic V0→V1 migration, future/expired versions fail closed, unknown fields fail, and migration preserves revision payload/checksum/provenance exactly.
- [ ] Run `python -m pytest tests/test_productization_foundation_v1.py -q` and confirm failure because the module/schema do not exist.
- [ ] Implement immutable dataclasses, exact-field parsing, finite supported window `{0, 1}`, explicit V0→V1 member-hash migration, V1 idempotence and published strict schema.
- [ ] Add the backup schema policy to `config/schema-versions.json`, including all provenance-bearing material fields as protected.
- [ ] Run the focused tests and schema-version gate; commit `feat(stage11): add product compatibility contract`.

### Task 2: Backup and Canonical Integrity Verification

**Files:**
- Modify: `scripts/backend_contract/productization.py`
- Modify: `scripts/backend_contract/infrastructure/sqlite.py`
- Test: `tests/test_productization_foundation_v1.py`

**Interfaces:**
- Produces: `CreateWorkspaceBackup.execute(workspace_id) -> bytes`, `VerifyWorkspaceBackup.execute(payload) -> WorkspaceBackup`, and `SQLiteArtifactRevisionRepository.list_workspace(workspace_id)`.
- Consumes: workspace repository, revision repository, optional private-content repository/stream, canonical artifact validators.

- [ ] Write RED tests with a synthetic workspace containing multiple historical revisions and private content; assert deterministic bytes, exact workspace scope, member/root SHA-256, source snapshot payload preservation and no network calls.
- [ ] Write adversarial RED tests for changed payload, checksum, revision gap/order, duplicated identity, foreign workspace record, malformed base64, altered private bytes and unknown artifact kind.
- [ ] Implement workspace-wide ordered revision listing and backup creation that reads authenticated private streams, hashes canonical members, and emits no path/token/secret.
- [ ] Implement verification that recalculates hashes, reconstructs `ArtifactRevision`/`PrivateContentMetadata`, and routes every supported canonical artifact kind through its domain deserializer; generic legacy kinds are rejected from portable recovery.
- [ ] Run focused/property tests and commit `feat(stage11): create verified workspace backups`.

### Task 3: Staging Restore, Reopen and Rollback

**Files:**
- Modify: `scripts/backend_contract/productization.py`
- Test: `tests/test_productization_foundation_v1.py`

**Interfaces:**
- Produces: `RestoreWorkspaceBackup.execute(payload) -> RestoreReceipt`, `ReopenRestoredWorkspace.execute(workspace_id) -> WorkspaceRecoveryDiagnostic`.
- Consumes: verified backup, empty staging workspace/revision/private repositories.

- [ ] Write RED tests proving restore recreates workspace, every revision identity/checksum/order and private byte exactly, then reopens through canonical deserializers.
- [ ] Write RED rollback tests proving non-empty target, write conflict, injected private-store failure and corrupt package never mutate the active repositories and never report success.
- [ ] Implement preflight verification before writes, require an empty staging target, write original identities in order, verify reopened records again, and return a receipt containing backup digest, release/storage versions and counts.
- [ ] Make failures sanitized and explicit; no recovery path may reinterpret or regenerate a historical snapshot.
- [ ] Run focused fault-injection tests and commit `feat(stage11): restore backups through verified staging`.

### Task 4: Support Diagnostics and Terminal Assurance

**Files:**
- Modify: `scripts/backend_contract/productization.py`
- Modify: `tests/fixtures/core-fixtures.json` if a fixture is added
- Test: `tests/test_productization_foundation_v1.py`

**Interfaces:**
- Produces: `collect_support_diagnostics(...) -> SupportDiagnostic` containing only versions, counts, integrity status and sanitized error codes.

- [ ] Write RED tests proving diagnostics expose no payload, filename, path, token, private bytes or exception details and remain useful for compatibility/corruption classification.
- [ ] Implement release/storage/schema versions, supported upgrade window, integrity status, artifact/private counts and stable diagnostic codes with `private_egress=False`.
- [ ] Run `change_impact` on the exact changed paths and all boundary-selected tests.
- [ ] Freeze HEAD; run pre-terminal adversarial matrix, sibling-defect sweep and three independent read-only reviews concurrently.
- [ ] Run exactly one full pytest regression, frontend assurance if impacted, and one `python -m scripts.quality.verify_core --full`; preserve timing debt classification without redundant reruns.
- [ ] Push, open PR closing #162, wait for protected CI, merge, run post-main focused recovery/reopen verification, and stop for the human decision on Field Mobile Foundation.

## Self-Review

- Spec coverage: migration, compatibility window, immutable history, backup, integrity verification, restore/reopen, staging rollback, corruption fail-closed, release version and sanitized diagnostics are each mapped above.
- Scope exclusions: no AI automation, mobile, C1 controls, court submission, security scanner or release signing is introduced.
- Type consistency: backup verification returns the same immutable `WorkspaceBackup` consumed by restore; restore receipt records the digest verified before and after reopen.
- Placeholder scan: no deferred implementation placeholder remains in the plan.
