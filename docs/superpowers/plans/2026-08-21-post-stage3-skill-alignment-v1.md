# POST_STAGE3_SKILL_ALIGNMENT_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the authorized skill and external-catalog knowledge surface before Application Layer product code begins.

**Architecture:** Keep upstream skill bytes immutable under `.agents/skills/frontend-design/`, with first-party precedence in `AGENTS.md` and auditable pin/blob metadata under `docs/terceiros/`. Keep Awesome Python and Public APIs as documentation-only discovery catalogs; neither becomes code, dependency, provider, or authority.

**Tech Stack:** Markdown, JSON provenance manifest, Python standard library, pytest, Git object IDs.

## Global Constraints

- Issue: #91; branch: `chore/91-post-stage3-skill-alignment`.
- Upstream frontend-design commit: `67a666efc8524ff7abaa266f84e514aa77aee48f`.
- Vendor only upstream `SKILL.md` and `LICENSE.txt`, byte-for-byte.
- No runtime/product behavior, dependency, API, database, frontend, provider, telemetry, or trust-boundary change.
- First-party governance and `ui-pericial` always outrank third-party frontend instructions.
- Catalog entries are discovery only and never approval.

---

### Task 1: Pin the official frontend-design skill

**Files:**
- Create: `.agents/skills/frontend-design/SKILL.md`
- Create: `.agents/skills/frontend-design/LICENSE.txt`
- Create: `docs/terceiros/frontend-design-blobs.json`
- Create: `scripts/terceiros/verificar_frontend_design.py`
- Modify: `tests/test_integracoes_externas.py`

**Interfaces:**
- Consumes: exact Git tree at the authorized upstream commit.
- Produces: `verificar() -> list[str]`, an offline byte-integrity and closed-file-set guard.

- [ ] **Step 1: Add RED provenance tests**

Add tests asserting the exact upstream repository, commit, path, Apache-2.0 license, destination, two-file closed set, blob identities, and `verificar() == []` only after the vendored files and manifest exist.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest tests/test_integracoes_externas.py -q`

Expected: failure because the frontend-design package/manifest/verifier does not exist.

- [ ] **Step 3: Retrieve and inspect the exact upstream tree without executing it**

Fetch only the pinned commit into a temporary Git repository, inspect `plugins/frontend-design/skills/frontend-design/{SKILL.md,LICENSE.txt}`, and compute Git blob IDs. Do not install or execute upstream code.

- [ ] **Step 4: Add the byte-exact files and offline verifier**

The verifier must reject missing, extra, or blob-divergent files and broken local Markdown links. It must not access the network or update files.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_integracoes_externas.py -q`

Expected: PASS.

### Task 2: Establish first-party precedence and controlled catalogs

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/terceiros/integracoes-agentes.md`
- Create: `docs/padroes/catalogo-externo-python.md`
- Create: `docs/padroes/catalogo-externo-apis.md`
- Create: `docs/padroes/matriz-skills-roadmap.md`
- Modify: `tests/test_governanca_desenvolvimento.py`

**Interfaces:**
- Consumes: existing governance, UI, research-ranking, egress, and review protocols.
- Produces: deterministic routing and decision rules for later roadmap phases.

- [ ] **Step 1: Add RED governance tests**

Add behavioral/structural governance assertions for the required frontend reading stack, explicit precedence, catalog discovery-only rules, pinned catalog references, and the roadmap matrix categories.

- [ ] **Step 2: Run focused governance tests and confirm RED**

Run: `python -m pytest tests/test_governanca_desenvolvimento.py tests/test_integracoes_externas.py tests/test_superpowers_safety.py -q`

Expected: failure because the new policies and routing do not exist.

- [ ] **Step 3: Write the minimum first-party documents and routing update**

Document all mandatory catalog gates and phase-to-skill classifications. Do not copy catalog contents, add submodules, dependencies, providers, or frontend implementation.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_governanca_desenvolvimento.py tests/test_integracoes_externas.py tests/test_superpowers_safety.py -q`

Expected: PASS.

### Task 3: Verify and deliver Phase A

**Files:**
- Verify all files changed since base `5fb0871ddb2ac4a98db7bef394458528c20b9161`.

**Interfaces:**
- Consumes: completed Phase A diff.
- Produces: exact-head assurance package for the PR that closes Issue #91
  (PR #92 in this execution).

- [ ] **Step 1: Run provenance, focused governance, diff, privacy, and Ruff checks**

Run the offline frontend verifier, focused pytest files, `git diff --check`, changed-Python Ruff, and confirm `git ls-files referencias/privadas/*` is empty.

- [ ] **Step 2: Run repository impact and complete regression**

Run `python -m scripts.quality.change_impact <changed paths>`, `python -m pytest -q`, and `python -m scripts.quality.verify_core --full`.

- [ ] **Step 3: Classify risk, commit, push, and open PR**

Use the first-party classifier; create a Conventional Commit and PR referencing `Closes #91`, with exact tests, privacy, and no-deploy statement.

- [ ] **Step 4: Require exact-head CI and proportional independent review**

All protected checks must be SUCCESS. Reviewers use fresh read-only checkouts and exact BASE/HEAD. Any material HEAD change invalidates affected evidence.

- [ ] **Step 5: Merge normally and verify post-main**

Require P0=0/P1 material=0, merge without squash/rebase/force, then run full regression and `verify_core --full` on the exact merge commit before continuing to APPLICATION_LAYER_V1.

## Self-review

- Spec coverage: upstream pin/license/provenance, precedence, both catalogs, roadmap matrix, AGENTS routing, no runtime behavior, full assurance and post-main transition are represented.
- Placeholder scan: no TBD/TODO/implement-later steps.
- Boundary check: Application Layer code is absent from this plan and must start only after Phase A post-main green.
