# Protected Validator Schema Bootstrap V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install closed V1+V2 protected-transition parsing through a V1-compatible transition fully judged by OLD_JUDGE_V1.

**Architecture:** Keep the protected-base workflow and judge selection unchanged. Extend only the base-custodied analyzer so schema `1.0.0` accepts the exact legacy blob fields and schema `2.0.0` accepts exact canonical path, Git mode, object type, and blob identity fields; dispatch is fixed by the schema version inside the trusted parser and every unknown or hybrid shape fails closed.

**Tech Stack:** Python 3.13, pytest, Git object/tree plumbing, GitHub Actions.

## Global Constraints

- PR #53 remains `SUPERSEDED_FOR_BOOTSTRAP_SEQUENCE` and its HEAD must never merge.
- PR-S starts from clean `origin/main` and uses only a V1 manifest judged by OLD_JUDGE_V1.
- Retain V1; do not start PR-C or change capability policy, Architecture Analyzer scope, trust boundaries, pericial semantics, PR #44, or the four transferred P1s.
- Unknown, hybrid, malformed, duplicate, omitted, wrong-base, mismatch, non-ancestor, and Git-read failures block.
- Candidate code cannot select the parser, policy, protected base, or trusted executable.

---

### Task 1: Closed dual protected-transition parser

**Files:**
- Modify: `scripts/quality/architecture_analyzer.py`
- Modify: `tests/test_architecture_analyzer_v1.py`
- Modify: `config/architecture-protected-transition-v1.json`
- Create: `docs/superpowers/plans/2026-08-14-protected-validator-schema-bootstrap-v1.md`

**Interfaces:**
- Consumes: protected base SHA, exact candidate SHA, and Git tree identities loaded by the trusted analyzer.
- Produces: `_protected_transition_valid(...) -> bool` supporting exact schemas `1.0.0` and `2.0.0` only.

- [x] **Step 1: Write failing behavioral tests**

Add real temporary-Git-repository tests proving exact V2 mode-aware rotation is accepted and unknown, hybrid, malformed, duplicate, omitted, wrong-base, mismatch, non-ancestor, and Git-read failures are rejected while the existing exact V1 rotation remains accepted.

- [x] **Step 2: Verify RED**

Run: `python -m pytest tests/test_architecture_analyzer_v1.py -k "transition" -q`

Expected: the exact V2 acceptance test fails because OLD_JUDGE_V1 supports only schema `1.0.0` and legacy row fields.

- [x] **Step 3: Implement the minimum dual parser**

Load exact `(mode, object_type, object_id)` tuples from `git ls-tree`; dispatch only on trusted constants `1.0.0` and `2.0.0`; validate exact top-level and row key sets; retain V1 blob semantics and require V2 full identity equality. Catch Git, Unicode, JSON, unpacking, and type failures and return `False`.

- [x] **Step 4: Verify focused GREEN and adversarial regression**

Run: `python -m pytest tests/test_architecture_analyzer_v1.py -q`

Expected: all focused tests pass with no warnings.

- [ ] **Step 5: Install the bootstrap through OLD_JUDGE_V1**

Update the transition manifest as schema `1.0.0` with the exact base and candidate blob OIDs for `scripts/quality/architecture_analyzer.py`. Verify by executing the analyzer bytes from `origin/main` against the exact candidate commit.

- [ ] **Step 6: Run repository assurance and terminal review gates**

Run mapped tests, `python -m scripts.quality.verify_core --full`, exact-head CI, then fresh independent Reviewer, Systemic Auditor, and Claude external diversity review. Merge PR-S with a merge commit only if all exact-head gates pass; verify post-merge main green before creating the fresh mode-identity PR.
