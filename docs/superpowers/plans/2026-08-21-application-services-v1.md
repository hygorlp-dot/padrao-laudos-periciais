# APPLICATION_SERVICES_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task.

**Goal:** Add thin, deterministic Application services over the stabilized workspace and artifact-revision ports without introducing API, UI, infrastructure, or product semantics.

**Architecture:** Model each use case as one explicit service with an `execute` method. Inject only the repository needed by that use case and inject a timezone-aware `Clock` plus UUID `IdGenerator` where technical metadata must be created. Convert optional repository reads into explicit Application not-found errors, preserve repository failures unchanged, and snapshot artifact payloads before delegation so callers are never mutated through a port implementation.

**Tech Stack:** Python 3 standard library (`datetime`, `uuid`, `json`), typing Protocols, pytest.

## Constraints

- Umbrella: #93; delivery Issue: #98.
- Base: `cd39dfc36ce09e0d7580772d503d507ca673d919`.
- No SQL/SQLite/Infrastructure imports in Application; no HTTP/API/frontend/CLI/provider/network/telemetry/Core semantic change.
- No generic service framework, container, mediator, event bus, Unit of Work, or hidden transaction abstraction.
- Inputs and outputs remain governed by the existing Application models and repository ports.

### Task 1: Specify deterministic technical dependencies and explicit errors

**Files:**
- Modify: `scripts/backend_contract/application/ports.py`
- Create: `scripts/backend_contract/application/services.py`
- Create: `tests/test_application_services_v1.py`

- [ ] Add RED tests for `Clock` and `IdGenerator` protocols with timezone-aware datetime and UUID results.
- [ ] Add an explicit artifact-revision not-found error alongside the existing workspace error.
- [ ] Prove generated identity/time validation fails before persistence when injected dependencies violate their contracts.

### Task 2: Implement workspace services

**Files:**
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `tests/test_application_services_v1.py`

- [ ] Add RED tests for create/get/list workspace use cases, deterministic metadata, empty lists, missing workspace behavior, and repository-error propagation.
- [ ] Implement `CreateWorkspace`, `GetWorkspace`, and `ListWorkspaces` with one repository dependency each plus technical generators only where required.

### Task 3: Implement artifact revision services

**Files:**
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `tests/test_application_services_v1.py`

- [ ] Add RED tests for append/latest/exact/list operations, missing revision behavior, deterministic generated revision metadata, stable ordering delegated from the port, and repository-error propagation.
- [ ] Prove append snapshots arbitrary valid JSON without mutating caller input even if a repository fake mutates its received value.
- [ ] Implement `AppendArtifactRevision`, `GetLatestArtifact`, `GetArtifactRevision`, and `ListArtifactRevisions` without duplicating Core or persistence semantics.

### Task 4: Export, guard boundaries, and deliver

**Files:**
- Modify: `scripts/backend_contract/application/__init__.py`
- Modify: `tests/test_application_boundaries_v1.py` only if required by the existing architecture contract.

- [ ] Export the explicit services, generator protocols, and not-found error through the Application package.
- [ ] Prove Application remains Infrastructure/SQLite-free and services contain no network/provider/runtime integration.
- [ ] Run focused/adversarial tests, changed-file Ruff, diff check, privacy and repository safety.
- [ ] Run full regression and `python -m scripts.quality.verify_core --full`.
- [ ] Commit, push, open a draft PR referencing #93 and closing #98.
- [ ] Require exact-head protected CI and fresh independent Reviewer/Systemic Auditor; use one diversity path only if the repository risk contract requires it.
- [ ] Merge normally, prove post-merge main green, close #93, and stop before LOCAL_API_V1/frontend.

## Self-review

- Services create only technical IDs/timestamps and make no pericial decisions.
- `None` from read ports never leaks as an ambiguous service result.
- Caller payloads are isolated before crossing the injected repository boundary.
- Application imports neither Infrastructure nor SQLite.
