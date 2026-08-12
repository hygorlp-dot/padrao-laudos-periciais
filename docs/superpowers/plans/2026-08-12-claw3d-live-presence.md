# Claw3D Live Agent Presence Implementation Plan

> **For agentic workers:** execute each task with TDD and independent review checkpoints.

**Goal:** Expose truthful, local-only live presence for the five agent roles without granting Claw3D authority over workflow or the Core.

**Architecture:** A standard-library Python state store owns per-agent lifecycle, atomic persistence, cross-process locking and stale recovery in a shared runtime directory independent of worktrees. A loopback HTTP bridge exposes a privacy-minimal snapshot; PowerShell wrappers and a non-blocking sink provide local operations and lifecycle instrumentation.

**Tech Stack:** Python standard library, PowerShell, pytest, Markdown.

## Global Constraints

- Stacked dependency: PR #32; this branch cannot merge first.
- `CLAW3D_IS_NON_AUTHORITATIVE`; all observability failures are non-blocking.
- Loopback bind only; no token or external egress.
- Snapshot contains only agent ID, display name, operational state and timestamp.
- Runtime state is local, ignored and shared explicitly across worktrees.

---

### Task 1: State contract and lifecycle

- [ ] Write RED tests for five agents, transitions, parallel updates, atomicity, heartbeat, stale recovery and privacy-minimal snapshots.
- [ ] Implement a locked atomic state store and lifecycle context manager.
- [ ] Prove operational errors do not propagate into the wrapped workflow.

### Task 2: Loopback bridge and operator scripts

- [ ] Write RED tests for `/presence`, `/health`, loopback enforcement and graceful shutdown.
- [ ] Implement the local HTTP bridge and Start/Stop/Get/Set PowerShell scripts.
- [ ] Add opt-in auto-start through `CLAW3D_LIVE_PRESENCE_ENABLED=1` without changing execution policy permanently.

### Task 3: Governance integration and acceptance

- [ ] Register `CLAW3D_IS_NON_AUTHORITATIVE` and the observability boundary.
- [ ] Document Claw3D setup, lifecycle hooks and worktree behavior.
- [ ] Run focused tests, smoke endpoint, full suite, privacy, `verify_core --full` and CI.
- [ ] Obtain independent PR review and systemic audit on the final HEAD; keep the stacked PR draft.
