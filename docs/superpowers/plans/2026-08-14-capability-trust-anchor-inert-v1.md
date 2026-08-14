# Capability Trust Anchor Inert V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preinstall a capability-free, inert, base-owned trust anchor that can validate an exact future PR-C artifact transition without analyzing or authorizing capability.

**Architecture:** The already-protected architecture verifier adds the capability workflow, verifier, and registry to its protected artifact set through one exact architecture trust-anchor rotation. The new capability verifier reads only Git object identities and a closed JSON registry/transition manifest; `INERT_TRUST_ANCHOR` validates custody and returns no capability findings. PR-C will later supply the analyzer and policy as candidate artifacts through the exact transition mechanism.

**Tech Stack:** Python 3.13+, Git object database, JSON, pytest 9.1.1, GitHub Actions.

## Global Constraints

- Issue `#51` is the only implementation scope.
- `ARCHITECTURE_DYNAMIC_BOUNDARY_SEPARATION_V2` remains active.
- `GENERAL_DYNAMIC_SEMANTIC_ENUMERATION` remains exhausted; no fourth repair is allowed.
- Dynamic execution/import/reflection remains open for `CAPABILITY_ANALYZER_V1` in `config/architecture-capability-transfers-v2.json`.
- PR44 remains frozen and is never merged.
- PR-T is capability-free and `INERT_TRUST_ANCHOR`; it does not analyze or authorize capability.
- Fail closed on malformed configuration, Git failure, identity mismatch, deletion, duplicate, omitted artifact, non-ancestor base, or out-of-scope change.
- No secrets, provider, network egress, runtime dependency, or pericial data.

---

### Task 0: Prepare architecture custody in a dedicated protected rotation

**Files:**
- Modify: `scripts/quality/architecture_analyzer.py`
- Modify: `tests/test_architecture_analyzer_v1.py`
- Create: `config/architecture-protected-transition-v1.json`

**Interfaces:**
- Consumes: the base-owned architecture protected-transition verifier from merge `d96e3dda05d52590e4882f92834191cf65ea1f21`.
- Produces: future custody identities for `.github/workflows/capability-protected.yml`, `config/capability-protected-artifacts-v1.json`, and `scripts/quality/capability_trust_anchor.py` without introducing those bytes in the same rotation.

- [ ] **Step 1: Write and verify the failing custody test**

  Run: `python -m pytest tests/test_architecture_analyzer_v1.py::test_architecture_anchor_custodies_inert_capability_trust_root -q` before implementation and observe the three missing paths.

- [ ] **Step 2: Add only the three future identities and exact transition manifest**

  Modify `PROTECTED_ARCHITECTURE_ARTIFACTS`; do not add the capability workflow, verifier, or registry yet. Bind the changed analyzer base/candidate blobs in `config/architecture-protected-transition-v1.json`.

- [ ] **Step 3: Verify, review, merge, and require post-main green**

  Execute focused and full gates, exact-head CI and three fresh terminal reviews. Merge by merge commit. Continue Task 1 only from the green merged base.

### Task 1: Inert capability transition verifier

**Files:**
- Create: `tests/test_capability_trust_anchor_v1.py`
- Create: `scripts/quality/capability_trust_anchor.py`
- Create: `config/capability-protected-artifacts-v1.json`

**Interfaces:**
- Consumes: `validate_inert_trust_anchor(root: Path, protected_base: str, candidate: str) -> list[dict]` inputs from the protected workflow.
- Produces: an empty list for unchanged protected artifacts or an exact dedicated transition; otherwise deterministic P1 findings with `analyzer = "CAPABILITY_TRUST_ANCHOR_V1"`.

- [ ] **Step 1: Write failing behavior tests**

  Add real temporary Git repositories proving: unchanged inert artifacts pass; a protected artifact mutation without a manifest fails; exact manifest identities pass; deletion, duplicate/omitted rows, malformed/extra keys, non-ancestor base, and mixed production changes fail; the transfer ledger remains unchanged and open.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest tests/test_capability_trust_anchor_v1.py -q`

  Expected: collection fails because `scripts.quality.capability_trust_anchor` does not exist.

- [ ] **Step 3: Implement the minimal inert verifier**

  Implement fixed paths, closed-key JSON validation, `git merge-base --is-ancestor`, batched `git ls-tree`, exact blob comparison, and exact `config/capability-protected-transition-v1.json` validation. Do not import AST, inspect Python source, load capability policy, or execute candidate code.

- [ ] **Step 4: Verify GREEN**

  Run: `python -m pytest tests/test_capability_trust_anchor_v1.py -q`

  Expected: all tests pass.

### Task 2: Protected inert workflow and architecture custody

**Files:**
- Create: `.github/workflows/capability-protected.yml`
- Modify: `scripts/quality/architecture_analyzer.py`
- Modify: `tests/test_architecture_analyzer_v1.py`
- Create: `config/architecture-protected-transition-v1.json`

**Interfaces:**
- Consumes: base-owned `validate_inert_trust_anchor(...)` and exact `pull_request_target` base/head SHAs.
- Produces: a protected workflow that runs only the inert custody verifier and exits nonzero on findings.

- [ ] **Step 1: Write failing workflow/custody tests**

  Add tests that execute the architecture protected-artifact function against a synthetic future candidate and prove the three new anchor paths cannot change without an exact transition. Assert the workflow has read-only permissions, base/candidate isolated checkouts, exact SHA environment, no secrets/deploy, and invokes only `validate_inert_trust_anchor`.

- [ ] **Step 2: Verify RED**

  Run: `python -m pytest tests/test_architecture_analyzer_v1.py tests/test_capability_trust_anchor_v1.py -q`

  Expected: failures identify the absent workflow and absent protected artifact custody.

- [ ] **Step 3: Implement minimal workflow and protected rotation**

  Add the three capability trust-anchor paths to `PROTECTED_ARCHITECTURE_ARTIFACTS`, create the inert workflow, and generate the exact architecture transition manifest for the changed protected analyzer blob from base `d96e3dda05d52590e4882f92834191cf65ea1f21` to the staged candidate commit.

- [ ] **Step 4: Verify GREEN and adversarial regression**

  Run: `python -m pytest tests/test_architecture_analyzer_v1.py tests/test_capability_trust_anchor_v1.py tests/test_architecture_dynamic_boundary_v2.py tests/test_repository_safety_gate.py -q`

  Expected: all tests pass and the four dynamic capability P1 transfers remain open.

### Task 3: First-party gates and review package

**Files:**
- Modify only if required by first-party validation: `config/architecture-protected-transition-v1.json`
- Persist outside the worktree: `.git/phase-b-runtime/RETURN_HANDOFF.md`, `.git/phase-b-runtime/supervisor-v5-state.json`

**Interfaces:**
- Consumes: exact base/head, changed path list, tests and review requirements.
- Produces: merge-eligible evidence only after exact-head CI and three fresh terminal reviews.

- [ ] **Step 1: Run impact and focused gates**

  Run: `python -m scripts.quality.change_impact <changed paths>` and the focused pytest command from Task 2.

- [ ] **Step 2: Run full verification**

  Run: `python -m scripts.quality.verify_core --full`.

- [ ] **Step 3: Commit and publish surgically**

  Stage only Issue `#51` paths, commit with Conventional Commits, push the existing branch, and open one non-draft PR referencing `Closes #51`.

- [ ] **Step 4: Require terminal evidence**

  Poll exact-head CI and require identifiable `PR_REVIEWER`, `SYSTEMIC_AUDITOR`, and sanitized external-diversity review artifacts. Any new HEAD invalidates them.

- [ ] **Step 5: Merge and verify main**

  Merge only with a merge commit, poll post-merge `main` to green, then continue to PR-C.
