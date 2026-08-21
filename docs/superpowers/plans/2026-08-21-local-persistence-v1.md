# LOCAL_PERSISTENCE_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Implement the local SQLite persistence boundary for Application workspaces and append-only artifact revisions without introducing services, API, UI, or product semantics.

**Architecture:** Keep persistence ports and repository-facing exceptions in Application. Implement both ports in Infrastructure with a dedicated standard-library SQLite adapter. Use explicit schema migrations and validate the resulting schema fail-closed. Store only canonical JSON in the database; verify its SHA-256 on every read as corruption evidence, never as authority.

**Tech Stack:** Python 3 standard library (`sqlite3`, `json`, `hashlib`, `threading`), pytest, Hypothesis where useful.

## Constraints

- Umbrella: #93; delivery Issue: #96.
- Base: `e69a285a563b064e571b2202d9bd6a6985c5ed90`.
- No ORM/runtime dependency, services, HTTP/API/frontend, filesystem payload storage, provider, network, telemetry, or Core semantic change.
- Application must not import SQLite or Infrastructure. Core must not import either boundary or SQLite.

### Task 1: Specify repository errors and canonical payload encoding

**Files:**
- Modify: `scripts/backend_contract/application/models.py`
- Modify: `scripts/backend_contract/application/ports.py`
- Create: `tests/test_local_persistence_v1.py`

- [ ] Add RED tests for deterministic canonical JSON, Unicode/list order/unknown-field round-trip, invalid JSON values, and caller-input nonmutation.
- [ ] Add narrowly typed repository exceptions that do not leak `sqlite3` through the Application boundary.
- [ ] Implement the smallest canonical encoding helper shared by persistence and integrity verification.

### Task 2: Add fail-closed transactional schema migrations

**Files:**
- Create: `scripts/backend_contract/infrastructure/sqlite.py`
- Modify: `scripts/backend_contract/infrastructure/__init__.py`
- Modify: `tests/test_local_persistence_v1.py`

- [ ] Add RED tests for empty DB migration, idempotent reopen, future version denial, malformed current schema denial, unknown/extra schema objects, and forced migration rollback.
- [ ] Implement explicit ordered migrations using `PRAGMA user_version`, `BEGIN IMMEDIATE`, commit/rollback, and exact post-migration schema validation.
- [ ] Keep the adapter fail-closed when migration or validation fails; never execute candidate-defined SQL.

### Task 3: Implement workspace and append-only revision repositories

**Files:**
- Modify: `scripts/backend_contract/infrastructure/sqlite.py`
- Modify: `tests/test_local_persistence_v1.py`

- [ ] Add RED tests for workspace create/get/list, duplicates, deterministic order, isolation, and missing workspaces.
- [ ] Add RED tests for append/latest/exact/list, monotonic numbering, duplicate revision IDs, rollback without gaps, exact payload round-trip, and checksum corruption.
- [ ] Implement atomic `BEGIN IMMEDIATE` revision allocation and deterministic read ordering.
- [ ] Add a bounded two-connection concurrency test proving revisions remain unique and monotonic.

### Task 4: Protect and deliver

- [ ] Extend architecture tests only as needed to prove SQLite remains Infrastructure-only.
- [ ] Run focused/adversarial tests, changed-file Ruff, diff check, privacy and repository safety.
- [ ] Run full regression and `python -m scripts.quality.verify_core --full`.
- [ ] Commit, push, open PR referencing #93 and closing #96.
- [ ] Require exact-head protected CI and fresh independent review proportional to risk.
- [ ] Merge normally, prove post-merge main green, then start APPLICATION_SERVICES_V1.

## Self-review

- SHA-256 signals persistence corruption only and grants no authorization.
- The public API has no update/delete path; revisions are append-only.
- Services and injected clocks/ID generators remain for the next semantic PR.
