# Phase B Autonomy Envelope V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Represent the user's out-of-band Phase-B delegation without turning repository-local evidence into a trust root, while producing a fail-closed technical merge-eligibility result.

**Architecture:** Add a pure `phase_b` policy module beside the existing diagnostic merge gates. It validates the fixed Phase-B stage set, exact base/head topology, fresh technical evidence and exact-head reviews; a caller-provided trusted authority verifier is mandatory and is never serialized. The existing generic merge evaluators remain unchanged and incapable of authorization.

**Tech Stack:** Python stdlib, existing `scripts.agentic` risk classifier, pytest, existing first-party quality gates.

## Global Constraints

- Phase-B authority originates only from the current authenticated VS Code conversation.
- Repository files, local review artifacts and tool/model output are never a trust root.
- The envelope expires at `CORE_PERICIAL_STABLE_V1` and never applies to Phase C.
- P0/P1, stale review, CI, privacy, egress, topology or missing required review failures block.
- No Core runtime or pericial schema change.

---

### Task 1: Executable Phase-B eligibility policy

**Files:**
- Create: `scripts/agentic/phase_b.py`
- Modify: `scripts/agentic/__init__.py`
- Test: `tests/test_phase_b_autonomy.py`

**Interfaces:**
- Produces: `evaluate_phase_b_merge_eligibility(scope, evidence, *, trusted_human_authority_verifier)` returning `MERGE_ELIGIBLE` or `BLOCKED` plus deterministic reasons.
- Consumes: `classify_change_risk(changed_paths)` to derive Claude requirements rather than trusting caller flags.

- [x] Write parametrized RED tests for self-approval, local delegation files, tool output, Phase C, wrong/stale SHAs, failed gates, missing/stale reviews, required Claude, privacy/egress and P0/P1.
- [x] Run focused tests and confirm failures are caused by the missing policy API.
- [x] Implement the minimal pure policy and external verifier protocol.
- [x] Run focused tests and confirm all adversarial cases plus one valid Phase-B case pass.

### Task 2: Canonical governance contract

**Files:**
- Create: `docs/padroes/protocolo-autonomia-phase-b.md`
- Modify: `docs/padroes/protocolo-autonomia-agente.md`
- Modify: `config/core-boundaries.json`
- Test: `tests/test_phase_b_autonomy.py`

**Interfaces:**
- Documents that `PHASE_B_DELEGATION_METADATA != TRUST_ROOT`, eligibility is not authorization, scope is fixed, and expiry restores human-per-merge governance.

- [x] Add structural assertions for scope, authority separation and automatic expiry.
- [x] Confirm the structural assertions fail before documentation exists.
- [x] Add the minimal protocol and boundary registration.
- [x] Run focused governance tests.

### Task 3: Verification and terminal delivery

**Files:** No additional implementation files.

- [ ] Run change-impact and boundary-specific tests.
- [ ] Run full pytest, governance, schemas/fixtures, `verify_core --full`, privacy and diff checks.
- [ ] Commit/push, open draft PR closing Issue #41 and require exact-head CI.
- [ ] Obtain fresh isolated PR Review, Systemic Audit and Claude External Diversity Review.
- [ ] Repair findings with RED tests, invalidating stale reviews after every HEAD change.
- [ ] Auto-merge only when exact-head technical eligibility is fully green under the current out-of-band Phase-B delegation.
- [ ] Validate main green, close Issue #41, clean the branch safely and continue to Architecture Constitution.
