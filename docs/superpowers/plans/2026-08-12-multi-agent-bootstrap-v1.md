# Multi-Agent Bootstrap V1 Implementation Plan

> **For agentic workers:** execute each task with TDD and an independent review checkpoint.

**Goal:** Establish first-party, fail-closed governance for autonomous multi-agent development and final external diversity review.

**Architecture:** A small `scripts.agentic` package owns deterministic policy decisions and JSON contracts. Repository documentation and Skills define operating procedures; tests prove independence, privacy, staleness, review validation, ranking, self-recovery and merge blocking without changing the forensic runtime.

**Tech Stack:** Python standard library, JSON Schema Draft 2020-12, pytest, Markdown.

## Global Constraints

- Stacked dependency: PR #30; no Bootstrap merge before that dependency.
- No Core forensic runtime or pericial schema change.
- External egress is deny-by-default and excludes private/case content.
- Claude is used only on a stable final HEAD when the deterministic gate requires it.
- Review independence and exact HEAD binding must be mechanically proven.

---

### Task 1: Deterministic governance contracts

**Files:** `scripts/agentic/`, `schemas/review-multiagente.schema.json`, `tests/test_agentic_governance.py`

- [ ] Write RED tests for role selection, risk/external-review classification, independence, sanitization, review validation, finding aggregation, ranking, self-recovery and merge gate.
- [ ] Confirm the tests fail because the package is absent.
- [ ] Implement the minimum first-party package and schema.
- [ ] Run the focused tests and adversarial variants.

### Task 2: Canonical memory and agent protocols

**Files:** `docs/arquitetura/`, `docs/padroes/protocolo-*.md`, `.agents/skills/*/SKILL.md`, `AGENTS.md`

- [ ] Add canonical architecture documents and the nine approved ADRs.
- [ ] Add concise protocols and Skills for autonomy, research, independent review, systemic audit and external diversity review.
- [ ] Add guards proving canonical precedence, role separation, Claude call budget and stacked dependency.

### Task 3: Repository safety integration

**Files:** `config/core-invariants.json`, `config/core-boundaries.json`, `config/core-registry-lock.json`, `scripts/validar_schemas.py`, fixture registry/tests

- [ ] Register the AGENTIC_GOVERNANCE boundary and its blocking invariants.
- [ ] Register valid/invalid synthetic review fixtures and update the canonical lock.
- [ ] Run impact mapping, schema/fixture validation, privacy guards and the full repository gate.

### Task 4: Independent acceptance and delivery

- [ ] Commit and push the stacked branch without mixing PR #30 commits.
- [ ] Open a draft PR with the dependency and merge block explicit.
- [ ] Obtain independent PR review and systemic audit on the exact final HEAD.
- [ ] Persist a sanitized review package and evidence tied to the SHA.
- [ ] Leave Claude review deferred and the PR unmerged until PR #30 is merged and one final external review succeeds.
