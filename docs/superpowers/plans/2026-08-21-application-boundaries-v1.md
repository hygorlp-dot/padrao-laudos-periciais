# APPLICATION_BOUNDARIES_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Establish the minimal Application Layer model and port boundary above the stabilized pericial Core without persistence, services, API, or UI.

**Architecture:** Keep existing `scripts/backend_contract` root modules as Core contracts. Add explicit `application/` and `infrastructure/` subpackages inside the already-owned BACKEND component so the protected architecture policy does not need rotation. Application may import Core and defines ports; Infrastructure may import Application; Core cannot import either child boundary; Application cannot import SQLite or Infrastructure.

**Tech Stack:** Python 3 standard library, dataclasses, typing Protocol, AST-based architecture tests, pytest/unittest.

## Constraints

- Umbrella: #93; delivery Issue: #94.
- Base: `5e7218066fc918147eb4c886fd2eee895c990d51`.
- No SQL, sqlite3, migration, persistence implementation, application services, filesystem payload, HTTP, API, frontend, provider, network, telemetry, or runtime dependency.
- Do not rewrite existing Core contracts or protected architecture artifacts.

### Task 1: Define minimal immutable application records

**Files:**
- Create: `scripts/backend_contract/application/__init__.py`
- Create: `scripts/backend_contract/application/models.py`
- Create: `tests/test_application_boundaries_v1.py`

- [ ] Add RED behavioral tests for valid and invalid `PericiaWorkspace` and `ArtifactRevision` records.
- [ ] Implement frozen, slotted records with explicit technical identity and no judicial/pericial conclusion semantics.
- [ ] Prove no input mutation and no implicit ID/time generation in the records.

### Task 2: Define simple persistence ports

**Files:**
- Create: `scripts/backend_contract/application/ports.py`
- Modify: `tests/test_application_boundaries_v1.py`

- [ ] Add RED structural/behavioral protocol tests.
- [ ] Define `WorkspaceRepository` and `ArtifactRevisionRepository` Protocols with explicit create/get/list and append/latest/exact/list operations.
- [ ] Keep atomic revision-number allocation behind the revision repository boundary; do not add generic repository, service locator, event bus, CQRS, or DI framework.

### Task 3: Protect dependency direction

**Files:**
- Create: `scripts/backend_contract/infrastructure/__init__.py`
- Create: `tests/test_application_architecture_v1.py`

- [ ] Add RED AST tests for Core → Application/Infrastructure, Application → Infrastructure/SQLite, allowed Infrastructure → Application, and cycles.
- [ ] Add only package markers needed for the declared boundaries.
- [ ] Run architecture analyzer and capability analyzer against the exact candidate tree.

### Task 4: Assure and deliver

- [ ] Run focused tests and changed-file Ruff.
- [ ] Run full regression, Golden Corpus through `verify_core --full`, repository safety, privacy, and diff check.
- [ ] Classify risk, commit, push, open PR referencing #93 and closing #94.
- [ ] Require exact-head protected CI and proportional independent review.
- [ ] Merge normally and verify exact post-main before starting LOCAL_PERSISTENCE_V1.

## Self-review

- This PR creates the boundary contract only; SQLite and services are deliberately absent.
- Existing Core behavior and public exports remain unchanged.
- No protected policy rotation or trust-bootstrap work is introduced.
