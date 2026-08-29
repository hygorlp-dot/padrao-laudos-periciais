# E1B Lint and Publication Privacy Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete E1B by eliminating the repository-wide Ruff baseline without product-semantic changes and adding deterministic current-tree/reachable-history privacy assurance with advisory Gitleaks.

**Architecture:** Keep secret detection and repository-specific privacy policy separate: pinned Gitleaks scans secrets, while a first-party scanner enforces private-path/content and synthetic-fixture provenance contracts. Integrate both through existing engineering workflows without creating a protected judge or changing branch protection.

**Tech Stack:** Python 3.13, pytest, Ruff 0.16.3, Gitleaks 8.30.1, GitHub Actions, PowerShell.

## Global Constraints

- Base is exactly `2d7bf9c839c6e141d099bf5e4d68bce5043b5f60`; Issue is `#137`.
- No product-semantic change, private data access/egress, force push, admin bypass, new protected judge, or branch-protection change.
- Gitleaks remains advisory in E1B; the existing first-party safety gate remains the blocking privacy authority.
- Scan both the current tracked tree and all commits reachable from refs available to the checkout.
- Never print matched private content; findings expose only sanitized rule/path metadata.
- Fixture provenance is explicit and synthetic; absence or real/private derivation fails closed.
- One mutation owner per shared boundary.

## Causal DAG and ownership

`baseline -> {Ruff cleanup, privacy RED tests, pinned Gitleaks acquisition} -> first-party scanner -> workflow/gate integration -> adversarial matrix -> shadow review -> terminal freeze -> assurance/reviews -> merge/post-main`

Critical path: privacy contract and trust-safe Gitleaks routing through workflow integration. Root owns `scripts/quality/**`, privacy tests/config, workflows, docs, and final synthesis. Parallel Ruff owners receive disjoint file sets.

---

### Task 1: Preserve semantics while eliminating Ruff findings

**Files:**
- Modify: only files reported by `uv run ruff check .`
- Test: existing focused tests for each touched module plus repository-wide Ruff

**Interfaces:**
- Consumes: existing public imports and runtime behavior at the E1A base
- Produces: identical behavior with `ruff check .` returning zero findings

- [ ] **Step 1: Capture the failing baseline**

Run `uv run ruff check . --output-format concise` and retain the exact rule/file inventory. Expected: 80 findings (`F401=41`, `E731=16`, `E402=9`, `E401=8`, `F821=4`, `F811=2`).

- [ ] **Step 2: Repair public re-exports without deleting API**

Replace dynamic export discovery in `scripts/backend_contract/__init__.py` with explicit redundant aliases or an explicit `__all__`, then run `uv run pytest tests/test_backend_contract.py -q`.

- [ ] **Step 3: Repair remaining findings by causal class**

Use named local functions for E731, split E401 imports, preserve deliberate late-import ordering with narrow `# noqa: E402` only where tests prove it is required, remove genuinely unused imports, and resolve F821 through the existing defined normalization authority rather than suppression.

- [ ] **Step 4: Prove focused behavior and global cleanliness**

Run affected test modules, then `uv run ruff check .`. Expected: zero findings.

### Task 2: Define first-party privacy and fixture-provenance contracts with RED tests

**Files:**
- Create: `scripts/quality/publication_privacy.py`
- Create: `tests/test_publication_privacy_e1b.py`
- Modify: `scripts/quality/fixture_registry.py`
- Modify: `tests/fixtures/core-fixtures.json`
- Modify: `tests/test_repository_safety_gate.py`

**Interfaces:**
- Produces: `scan_current_tree(root: Path) -> list[dict]`, `scan_reachable_history(root: Path) -> list[dict]`, and fixture registry validation requiring `provenance = "SYNTHETIC"`

- [ ] **Step 1: Write current-tree RED tests**

Create synthetic temporary Git repositories proving tracked `referencias/privadas/**`, forbidden private path markers, and real-case-derived fixture provenance produce sanitized findings while approved synthetic fixtures do not.

- [ ] **Step 2: Write reachable-history RED tests**

Commit a synthetic forbidden marker, remove it, and assert history scanning still detects the introducing reachable commit without returning matched content. Add branch/merge reachability and unreachable-object controls.

- [ ] **Step 3: Run RED**

Run `uv run pytest tests/test_publication_privacy_e1b.py tests/test_repository_safety_gate.py -q`. Expected: failures because scanner functions and provenance enforcement do not yet exist.

- [ ] **Step 4: Implement the minimum scanner and fixture contract**

Enumerate tracked files using Git, inspect blobs without entering `referencias/privadas/`, scan reachable commit diffs/blobs using bounded subprocess calls, and return only sanitized metadata. Require every registered fixture entry to declare synthetic provenance.

- [ ] **Step 5: Run focused GREEN**

Repeat the focused tests. Expected: pass.

### Task 3: Add pinned advisory Gitleaks and deterministic acquisition

**Files:**
- Create: `.gitleaks.toml`
- Create: `scripts/quality/run_gitleaks.ps1`
- Create: `tests/test_gitleaks_e1b.py`
- Modify: `docs/terceiros/quality-tooling-v2.md`

**Interfaces:**
- Consumes: official Gitleaks 8.30.1 Windows/Linux release assets with recorded SHA-256 digests
- Produces: one entry point supporting `current-tree` and `reachable-history`, redacted output, and advisory exit classification

- [ ] **Step 1: Write RED architecture tests**

Assert the wrapper pins version `8.30.1`, verifies platform-specific SHA-256 before extraction, passes `--redact=100`, invokes both `gitleaks dir` and `gitleaks git --log-opts=--all`, and never uses floating refs or an unverified executable.

- [ ] **Step 2: Run RED**

Run `uv run pytest tests/test_gitleaks_e1b.py -q`. Expected: fail because configuration/wrapper is absent.

- [ ] **Step 3: Implement deterministic wrapper and patterns**

Download only the official release asset for the runner platform, verify the recorded digest, extract to an ephemeral directory, run both scans with the repository config, redact all secrets, and delete ephemeral scanner output on exit.

- [ ] **Step 4: Verify locally**

Run architecture tests and the wrapper against the clean tree/history. Classify any historical findings without publishing secret content.

### Task 4: Integrate existing gates and CI without changing protected policy

**Files:**
- Modify: `scripts/quality/verify_core.py`
- Modify: `.github/workflows/lint.yml`
- Modify: `.github/workflows/core-safety.yml`
- Modify: `tests/test_repository_safety_gate.py`
- Modify: `docs/padroes/padrao-governanca-desenvolvimento.md`
- Modify: `docs/terceiros/quality-tooling-v2.md`

**Interfaces:**
- Consumes: first-party privacy scanner and Gitleaks wrapper
- Produces: blocking first-party current-tree/reachable-history privacy gates plus informational Gitleaks evidence

- [ ] **Step 1: Write RED integration tests**

Assert `verify_core --full` calls both first-party scan modes, CI checks out full history where scanning occurs, Ruff is clean/actionable, Gitleaks remains advisory, and pre-publication history scanning is documented as required.

- [ ] **Step 2: Run RED**

Run the focused architecture/safety tests and confirm the missing integration is the failure cause.

- [ ] **Step 3: Implement integration**

Wire sanitized findings into the existing privacy result, add full-history checkout only to the relevant workflow, and run advisory Gitleaks without adding a required check or changing branch protection.

- [ ] **Step 4: Run focused GREEN and actionlint**

Run focused tests and `actionlint`. Expected: pass.

### Task 5: Adversarial matrix, sibling sweep, and terminal assurance

**Files:**
- Modify: tests from Tasks 2–4 only when a causal gap is reproduced

**Interfaces:**
- Consumes: integrated E1B implementation
- Produces: stable reviewed terminal HEAD

- [ ] **Step 1: Execute sibling and legacy sweeps**

Cover renamed/deleted files, non-default reachable branches, merge commits, binary/invalid UTF-8 blobs, path case/separators, synthetic false positives, output redaction, timeouts, missing Git/Gitleaks, and no access to private directories.

- [ ] **Step 2: Run the pre-terminal adversarial matrix**

Confirm current-tree leak, historical-only leak, real-derived provenance, malformed registry, unverified binary, and incomplete checkout all fail closed in the appropriate authority.

- [ ] **Step 3: Run shadow systemic review read-only**

Provide cause, invariants, focused diff, matrix and sibling results; repair any in-scope P0/P1 before freeze.

- [ ] **Step 4: Freeze and verify once**

Run change-impact focused tests, `uv run ruff check .`, Gitleaks current/history, full pytest, `python -m scripts.quality.verify_core --full`, actionlint and zizmor on the stable HEAD.

- [ ] **Step 5: Independent reviews and delivery**

Obtain independent PR Reviewer and Systemic Auditor reports for exact base/head, repair in-scope findings causally, merge normally only with protected checks and P0/P1=0, then execute fresh-main acceptance and persist sanitized evidence to Issues #137 and #124.
