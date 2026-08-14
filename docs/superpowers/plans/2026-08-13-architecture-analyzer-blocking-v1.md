# Architecture Analyzer Blocking V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate the PR-B1 architecture analyzer as a fail-closed `verify_core` gate from the protected PR-B1 base.

**Architecture:** Harden the existing analyzer at its candidate-tree, policy, schema, exception, ownership, loader-bypass, and cycle boundaries, then compose its findings into the existing gate. Keep capability analysis out of scope and preserve exact-tree inputs.

**Tech Stack:** Python 3, pytest, jsonschema, Git object plumbing, GitHub Actions.

## Global Constraints

- Issue #49 and branch `feat/architecture-analyzer-blocking-v1` only.
- PR #44 remains frozen and must never merge.
- TDD RED precedes every production behavior change.
- Fail closed on malformed, unavailable, stale, mismatched, or self-disabling enforcement inputs.
- Preserve exact-head CI, three fresh terminal reviews, merge commit, and post-merge green.
- Do not add capability policy or capability-analyzer behavior.

---

### Task 1: Harden deferred analyzer boundaries

**Files:**
- Modify: `tests/test_architecture_analyzer_v1.py`
- Modify: `scripts/quality/architecture_analyzer.py`
- Modify: `schemas/architecture-baseline-v1.schema.json` only if runtime validation exposes a schema gap

**Interfaces:**
- Consumes: `run_architecture_gate(root, candidate)` and the exact candidate Git tree.
- Produces: deterministic architecture findings or `ARCHITECTURE_ANALYZER_FAILURE` for invalid enforcement state.

- [ ] Add behavior tests for candidate-tree-only exception blobs, runtime schema rejection, bounded/iterative cycle analysis, class-wide loader aliases, protected-base policy/baseline identity, and relational owner/disposition validation.
- [ ] Run focused tests and confirm each new test fails for the missing behavior.
- [ ] Implement the minimum hardening in `architecture_analyzer.py`.
- [ ] Run focused tests and confirm all pass.

### Task 2: Activate blocking composition

**Files:**
- Modify: `tests/test_repository_safety_gate.py`
- Modify: `tests/test_architecture_analyzer_v1.py`
- Modify: `scripts/quality/verify_core.py`

**Interfaces:**
- Consumes: `run_architecture_gate(ROOT)` findings.
- Produces: an `architecture analyzer` check whose findings block `GateResult`.

- [ ] Add an integration test proving an architecture finding makes `run_gate` fail and a clean result passes.
- [ ] Run the integration test and confirm RED because composition is absent.
- [ ] Add the minimal fail-closed composition to `verify_core`.
- [ ] Run focused architecture and repository-gate tests to GREEN.

### Task 3: Adversarial regression and delivery gates

**Files:**
- Modify: implementation/tests only for reproduced P0/P1 findings.

**Interfaces:**
- Consumes: changed-file impact map and first-party verification commands.
- Produces: exact-head evidence for PR review and merge eligibility.

- [ ] Run adversarial/property tests named by the impact map.
- [ ] Run the full regression suite and `python -m scripts.quality.verify_core --full`.
- [ ] Commit and push the exact reviewed head; open PR referencing Issue #49.
- [ ] Poll exact-head CI, repair material P0/P1 via a fresh RED cycle, and invalidate stale reviews after any head change.
- [ ] Obtain three fresh terminal reviews, merge with a merge commit, and verify protected `main` locally and in CI.
- [ ] Refresh V5 handoff/state from remote truth and continue the next approved transition.
