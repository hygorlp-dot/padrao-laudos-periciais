# PR Timing Observability V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make full-gate duration advisory only for pull requests while every semantic, privacy, regression, coverage, mutation, architecture, and capability failure remains blocking.

**Architecture:** Keep `scripts/quality/verify_core.py`, protected workflows, package initializer, Architecture Analyzer, and Capability Analyzer byte-identical. Put the timing disposition in `scripts/quality/metrics.py`, the existing owner of `FULL_GATE_DURATION_REGRESSION`: exact GitHub `pull_request` execution selects `PR_ADVISORY`; push/main and ordinary local execution remain `STRICT`. Emit a stable three-line timing observation while returning only non-timing findings in advisory mode.

**Tech Stack:** Python 3.13+, pytest, existing first-party quality metrics and Core Safety gate.

## Global Constraints

- `full_gate_max_seconds` remains exactly `60.0`.
- No test, coverage source, mutation suite, schema, privacy check, architecture gate, or capability gate may be removed or filtered.
- `scripts/quality/__init__.py`, `scripts/quality/verify_core.py`, `scripts/quality/architecture_analyzer.py`, workflows, branch protection, and capability registries/transitions remain unchanged.
- Missing, malformed, non-finite, or negative timing evidence fails closed.
- PR advisory mode suppresses only exact `FULL_GATE_DURATION_REGRESSION`; every other finding remains blocking.

---

### Task 1: Timing policy contract

**Files:**
- Modify: `tests/test_quality_metrics.py`
- Modify: `tests/test_repository_safety_gate.py`
- Modify: `scripts/quality/metrics.py`

**Interfaces:**
- Consumes: `validate_quality_baseline(..., duration_seconds=...)` and `GITHUB_EVENT_NAME`.
- Produces: constants `TIMING_POLICY_STRICT`, `TIMING_POLICY_PR_ADVISORY`; structured stdout fields `TARGET_SECONDS`, `OBSERVED_SECONDS`, `TIMING_STATUS`.

- [x] Add RED unit tests proving PR overrun becomes warning, strict overrun remains finding, invalid evidence fails, target is exactly 60.0, and semantic findings survive advisory timing.
- [x] Add RED integration tests around `run_gate("full")` with deterministic fake subprocesses proving semantic, privacy, and regression failures remain blocking alongside an advisory overrun.
- [x] Run the focused tests and confirm they fail only because the timing policy contract does not exist.
- [x] Implement the smallest policy resolver and timing emitter in `metrics.py`; do not alter `verify_core.py`.
- [x] Run focused tests to GREEN, then run existing metrics/repository-safety suites.

### Task 2: Decision record and immutable-surface guards

**Files:**
- Create: `docs/arquitetura/decisoes/ADR-pr-timing-observability-v1.md`
- Modify: `tests/test_repository_safety_gate.py`

**Interfaces:**
- Consumes: existing `core-safety.yml` invocation and protected quality artifacts.
- Produces: executable proof that no test filtering or protected artifact mutation was introduced.

- [x] Add RED/characterization assertions that the regression command keeps its existing suite set and that protected `verify_core.py`, initializer, analyzer, and workflow remain identical to protected main.
- [x] Record why metrics owns timing disposition, why exact `pull_request` is advisory, and why push/main/local stay strict.
- [x] Run focused suites and `git diff --check`.

### Task 3: Terminal assurance and delivery

**Files:**
- Verify only the files listed above.

**Interfaces:**
- Consumes: final exact HEAD.
- Produces: mergeable PR for Issue #113 with no protected-artifact rotation.

- [ ] Run change-impact, changed-file Ruff, privacy/repository-safety tests, full pytest, and `python -m scripts.quality.verify_core --full` in strict local mode.
- [ ] Push the exact HEAD and require architecture-protected, capability-protected, and PR-mode core-safety success.
- [ ] Run fresh isolated PR Reviewer and Systemic Auditor; run one external diversity review only if governance requires it.
- [ ] Freeze, merge normally, validate protected main, close Issue #113, and close PRs #110/#112 as superseded while retaining evidence.
