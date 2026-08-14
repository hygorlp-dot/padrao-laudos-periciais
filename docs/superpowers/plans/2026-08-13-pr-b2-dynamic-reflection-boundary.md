# PR-B2 Dynamic Reflection Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the five reproducible dynamic-loading bypasses on PR #50 without broadening its architecture-gate activation scope.

**Architecture:** Extend the analyzer's expression resolution at the AST boundary so protected loader/import semantics survive inline `Attribute`, `Subscript`, and reflective `Call` chains. Keep execution static and fail closed; do not import inspected modules or alter the approved baseline.

**Tech Stack:** Python `ast`, pytest, first-party quality gates.

## Global Constraints

- Issue #49 and branch `feat/architecture-analyzer-blocking-v1` only.
- Preserve PR #44 frozen and never merge it.
- TDD RED before production changes; exact-head CI; three fresh terminal reviews.
- Never access `referencias/privadas/` or weaken a gate.

---

### Task 1: Preserve protected semantics through inline expressions

**Files:**
- Modify: `scripts/quality/architecture_analyzer.py`
- Test: `tests/test_architecture_analyzer_v1.py`

**Interfaces:**
- Consumes: `_resolve_binding(node, bindings)` and `_protected_binding(node, bindings)`.
- Produces: `DYNAMIC_ARCHITECTURE_BYPASS` for the five exact reviewer reproductions.

- [ ] **Step 1: Write the failing parameterized regression test**

Add the five literal sources from `PR50-DYNAMIC-REFLECTION-LOADER-BYPASS` and assert each emits `DYNAMIC_ARCHITECTURE_BYPASS` through `analyze_sources`.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/test_architecture_analyzer_v1.py -k inline_reflection -q`

Expected: five failing cases because the protected semantic marker is lost at intermediate AST nodes.

- [ ] **Step 3: Implement the minimal recursive semantic resolution**

Resolve constant-key protected namespace subscripts, class-wide loader attributes, `globals()`/`__builtins__` indirection, `sys.modules['importlib']`, and constant `operator.attrgetter` calls without executing source.

- [ ] **Step 4: Run focused and adversarial tests**

Run the focused test, the entire analyzer test module, change-impact tests, and negative controls proving ordinary subscripts/calls are not classified as dynamic loading.

- [ ] **Step 5: Run first-party full gate and commit**

Run `python -m scripts.quality.verify_core --full`, commit only the plan/test/analyzer files, and push the Issue branch.

### Task 2: Exact-head assurance and transition

**Files:**
- Update outside the repository: common-Git-dir `phase-b-runtime/RETURN_HANDOFF.md` and `supervisor-v5-state.json`.

**Interfaces:**
- Consumes: remote PR head SHA, exact-head CI result, three independent persisted terminal reviews.
- Produces: merge commit only if every fail-closed condition is satisfied, followed by a green post-merge `main` run.

- [ ] **Step 1: Poll exact-head CI to completion**
- [ ] **Step 2: Run three fresh independent read-only terminal reviews on the exact SHA**
- [ ] **Step 3: Repair any P0/P1 under V5 budgets and invalidate stale reviews**
- [ ] **Step 4: Merge with a merge commit, then verify post-merge `main` green**
- [ ] **Step 5: Reconstruct remote truth and update both runtime cache files**
