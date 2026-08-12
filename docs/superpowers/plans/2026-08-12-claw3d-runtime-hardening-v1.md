# Claw3D Runtime Hardening V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` and preserve the existing PR #34 branch.

**Goal:** Eliminate duplicate execution, false readiness, unsafe orphan handling and related runtime failures without changing Core semantics.

**Architecture:** Prepare best-effort observability before a single subprocess boundary. Treat `/health` as liveness and `/presence` plus instance identity as readiness. Keep Claw3D local and non-authoritative.

**Tech Stack:** Python stdlib, PowerShell, pytest.

## Global Constraints

- No product features, frontend, API or pericial schema changes.
- No modification of upstream Claw3D.
- No private data access or egress.
- TDD and full repository safety verification are mandatory.

### Task 1: Exactly-once execution
- [x] Reproduce fallback after post-spawn failure and add RED tests.
- [x] Restrict fallback to pre-execution preparation.
- [x] Verify argv and exit-code fidelity.

### Task 2: Readiness and corrupted state
- [x] Reproduce health-success/presence-failure.
- [x] Return structured degradation and recover malformed state safely.
- [x] Exercise concurrent presence requests.

### Task 3: Verified bridge lifecycle
- [x] Serialize startup attempts and verify PID/token/health/presence.
- [x] Persist PID metadata atomically only after readiness.
- [x] Detect orphan and stale PID states without killing unproven processes.
- [x] Test idempotent and parallel startup.

### Task 4: Regression and review
- [x] Calibrate the full-gate ceiling to 75 seconds for real Windows subprocess lifecycle tests; semantic checks remain unchanged.
- [ ] Run full regression and repository gates.
- [ ] Run real subprocess and bridge smokes.
- [ ] Commit/push PR #34 and obtain three independent reviews.
- [ ] Repair P0/P1 findings and reverify.
