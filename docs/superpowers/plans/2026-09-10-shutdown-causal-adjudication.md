# Protected slow-drip shutdown causal adjudication plan

> **For agentic workers:** Execute this plan task-by-task in the isolated Issue #206 worktree. Keep PR #205, PR #203 and trust infrastructure unchanged.

**Goal:** Determine whether the protected slow-drip shutdown P0 is a ProductBridge defect, a harness temporal-contract defect, or causally attributable to PR #205, using reproducible synthetic evidence.

**Architecture:** The investigation compares the exact PR #205 tree (`355ca6b0b6f0bafa8176f3300c481b7cdeb166e0`) with protected main (`285f3a6e138aa787a83843f0acb2f126f2d1bd49`) using the same test node and isolated temporary roots. Any instrumentation is test-only, bounded and sanitised. Production shutdown behavior and protected gate semantics are not changed until a deterministic RED proves a root cause.

**Tech Stack:** Python 3.13/3.14 on Windows, pytest, `threading.Event`/`Barrier`, existing ProductBridge synthetic fixtures, first-party `verify_core` and protected CI.

## Global Constraints

- `PR205_HEAD=355ca6b0b6f0bafa8176f3300c481b7cdeb166e0`; do not modify or rebase PR #205 during adjudication.
- `PR203_HEAD=dc6fb672476450d901305db2a3126f6e4cb448d7`; do not modify or rebase PR #203.
- `PRIVATE_EGRESS=FALSE`; use synthetic fixtures only and never access `referencias/privadas/`.
- Do not increase the 500 ms assertion, add retries/sleeps/skips/xfail, alter test selection, weaken gates, or change trust semantics.
- Preserve `ACTUAL_STALLED_SHUTDOWN => FAIL`.
- Final verifier reporting must separate semantic result, timing result and exit code.

---

### Task 1: Capture exact A/A baseline without source mutation

**Files:**
- Read only: `tests/test_product_bridge_v1.py:1011-1061`
- Read only: `scripts/backend_contract/product_bridge/server.py:81-145,338-440`
- Evidence: `C:/tmp/issue-206-evidence/aa-matrix.md`

- [ ] Run the exact parametrized node ten times on the PR #205 checkout and record per-variant elapsed time, close-thread completion, request-worker liveness, listener socket state and residual thread state.
- [ ] Run the same node ten times on a detached checkout of protected main `285f3a6e138aa787a83843f0acb2f126f2d1bd49` with identical environment and isolated `TEMP`/`TMP` directories.
- [ ] Record the command, Python version, commit SHA, pass/fail count and sanitized observations in `aa-matrix.md`; do not publish raw tracebacks, paths, tokens or request bodies.
- [ ] Compare the two distributions and classify only `NON_REPRODUCTION`, `BASELINE_REPRODUCES`, `CANDIDATE_ONLY`, or `BOTH_REPRODUCE`; do not infer cause from repetition alone.

### Task 2: Add a deterministic test-only event trace (RED prerequisite)

**Files:**
- Modify only test code: `tests/test_product_bridge_v1.py`
- Test helper if required: `tests/helpers/product_bridge_shutdown_trace.py`

- [ ] Write a failing diagnostic test first that asserts an ordered bounded trace containing `RUNTIME_CLOSE_STARTED`, `BRIDGE_CLOSE_STARTED`, `SERVER_SHUTDOWN_STARTED`, `SERVER_SHUTDOWN_COMPLETED`, `LISTENER_CLOSED`, `REQUEST_WORKER_EXITED`, `LOCAL_API_CLOSE_STARTED`, `LOCAL_API_CLOSE_COMPLETED` and `RUNTIME_CLOSE_COMPLETED`.
- [ ] Run the diagnostic test and verify it fails for the intended missing trace/progress condition, not because of a fixture or syntax error.
- [ ] Implement only test-side probes/monkeypatches around existing close methods and thread state; never add production logging, network calls or mutable global state.
- [ ] Bound every wait with an explicit event/deadline and redact all file paths, tokens, request data and raw tracebacks.
- [ ] Run the diagnostic test again and retain the RED/GREEN outputs in the evidence directory.

### Task 3: Force controlled scheduler pressure without arbitrary sleeps

**Files:**
- Modify only test code: `tests/test_product_bridge_v1.py`
- Create evidence: `C:/tmp/issue-206-evidence/controlled-pressure.md`

- [ ] Add a test-only deterministic seam using `Barrier`/`Event` to hold the request worker at a known close boundary while allowing the server/listener to execute its normal shutdown path.
- [ ] Exercise the fixed `request_timeout_seconds=0.1`, dripper interval approximately `0.04s` and existing `closing.join(timeout=0.5)` contract without changing those production/test values.
- [ ] Demonstrate a case where all owned workers and listener close, state remains valid, but wall-clock completion exceeds 500 ms; capture phase timestamps and states.
- [ ] Demonstrate a separate true-hang case where a worker is held indefinitely until the bounded test deadline; assert the test fails closed and releases the seam in `finally`.
- [ ] Run both tests and record exact outcomes, elapsed buckets and sanitized phase traces.

### Task 4: Causal classification and minimal correction decision

**Files:**
- Read-only comparison of `git diff 285f3a6...355ca6b -- scripts/backend_contract/product_bridge tests/test_product_bridge_v1.py`
- Evidence: `C:/tmp/issue-206-evidence/classification.md`

- [ ] If the controlled trace proves eventual correct shutdown with only the 500 ms wall-clock assertion exceeded, classify `HARNESS_TEMPORAL_CONTRACT_DEFECT` and explicitly reject a ProductBridge defect.
- [ ] If any worker remains alive unbounded, listener does not close, state is invalid, or `close()` never returns, classify `PRODUCT_BRIDGE_SHUTDOWN_DEFECT` and open a separate product-fix branch; do not patch #205/#203.
- [ ] Classify `PR205_CAUSAL_DEFECT` only if byte-level comparison and a controlled experiment prove the Phase A workflow/manifest changes alter shutdown behavior; otherwise record `PR205_CAUSALITY=NOT_ESTABLISHED`.
- [ ] Do not change code until one classification is supported by deterministic RED/GREEN evidence.

### Task 5: Implement only the proven fix (if applicable)

**Files:**
- Harness-only outcome: modify `tests/test_product_bridge_v1.py` and its test helper.
- Product outcome: create a new Issue-linked branch and modify the smallest ProductBridge file implicated by the trace; do not touch PR #205/#203.

- [ ] For a harness defect, replace only the false wall-clock assertion with a documented progress-aware bounded contract while retaining the true-hang adversarial test.
- [ ] For a product defect, write the failing regression test first, implement one minimal shutdown fix, and re-run the true-hang adversarial test.
- [ ] Reject retries, arbitrary sleeps, timeout inflation, test skips and any change to protected trust/gate semantics.

### Task 6: Terminal assurance for the causal UOW

**Files:**
- No production changes outside the proven Issue #206 scope.
- Evidence: `C:/tmp/issue-206-evidence/terminal-report.md`

- [ ] Run focused ProductBridge tests and sibling sweep.
- [ ] Run Ruff, compile/diff/privacy checks and repository safety gate.
- [ ] Run exactly one `python -m scripts.quality.verify_core --full` on the frozen candidate and report `SEMANTIC_RESULT`, `TIMING_RESULT` and `EXIT_CODE` separately.
- [ ] Run protected CI, then request independent PR review and systemic audit on the exact frozen SHA.
- [ ] Merge normally only if all required gates are green and P0/P1 are zero; otherwise leave the causal UOW blocked with evidence.
- [ ] Only after a green harness/product fix is merged to protected main, rebase/revalidate PR #205 without adding Phase B or worker code.

## Self-review checklist

- Scope remains linked to #192/#206 and never modifies PR #205/#203.
- No production conclusion is made from isolated repetition alone.
- The controlled RED distinguishes elapsed-time false P0 from an actual stuck worker.
- A true-hang adversarial path remains fail-closed.
- Historical timing debt remains recorded separately and is not silently erased.
