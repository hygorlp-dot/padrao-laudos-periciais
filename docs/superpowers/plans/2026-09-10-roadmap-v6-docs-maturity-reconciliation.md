# Roadmap V6 Documentation Reconciliation Plan

> **For agentic workers:** Execute the tasks in order with a fresh verification checkpoint after each documentation group.

**Goal:** Reconcile the canonical roadmap and product maturity documentation with the merged longitudinal oracle, protected main, and the implemented AI/Recovery state without changing production behavior.

**Architecture:** Documentation remains a read-only projection of verified repository evidence. Historical claims stay visible, while current-effective status records the post-main oracle and merged SHA. Stage 10 is documented as implemented with proposal-only authority; local final PDF remains deferred.

**Tech Stack:** Markdown, JSON, repository quality scripts, pytest documentation/oracle checks.

## Global Constraints

- `PRIVATE_EGRESS = FALSE`.
- No production code, trust boundary, branch protection, gate threshold, or test selection changes.
- Preserve historical status separately from current-effective status.
- Do not create a Skill without a reproduced gap.
- Do not claim Human RC or real-case acceptance.
- Keep local final PDF fail-closed and non-final.

---

### Task 1: Reconcile the canonical roadmap Issue

**Files:**
- Update GitHub Issue #124 only through its canonical issue body/comment.

**Interfaces:**
- Consumes: merged main `27175535933a2ff2185ffbd02819796274cdbeff`, closed #187, open #192, protected gate/review evidence.
- Produces: current roadmap state identifying Item 2 complete and docs/maturity as the next work.

- [x] Record the new main SHA, `ROADMAP_V6_ITEM_2 = COMPLETE`, `#187 = CLOSED / POST_MAIN_ORACLE_PASS`, and preserve #192 as nonblocking timing debt.
- [x] Keep Stage 8 PDF deferral and Stage 10 proposal-only authority explicit.
- [x] Do not rewrite or delete the historical roadmap narrative.

### Task 2: Reconcile machine-readable maturity

**Files:**
- Modify: `config/product-maturity-v1.json`

**Interfaces:**
- Consumes: post-main longitudinal oracle and protected CI evidence.
- Produces: current statuses for stages 0–12, Item 2, Stage 10 implementation, PDF deferral, and Human RC not-ready state.

- [x] Set `generated_from` to the current longitudinal evidence label without removing schema compatibility.
- [x] Set Stage 10 to implemented/proven proposal-only status and retain its explicit authorization/readiness distinction.
- [x] Add current main SHA, Item 2 completion, Human RC false, and timing-debt metadata.
- [x] Validate JSON parsing and run the repository quality checks that consume this file.

### Task 3: Reconcile the maturity report

**Files:**
- Modify: `docs/PRODUCT_MATURITY_REPORT_V1.md`

**Interfaces:**
- Consumes: the reconciled JSON and post-main oracle evidence.
- Produces: an auditable report distinguishing historical versus current-effective status.

- [x] Replace stale protected/PR SHAs with main `27175535933a2ff2185ffbd02819796274cdbeff` and the merged PR evidence.
- [x] Mark the longitudinal oracle and Item 2 complete while preserving PDF deferral and Human RC not-ready.
- [x] Document Stage 10 contracts: explicit provider, source binding, structured output, application revalidation, append-only audit and token ceilings.
- [x] Preserve the historical timing-debt note and state that it is not silently corrected here.

### Task 4: Reconcile user-facing operating documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/manual-operacional.md`

**Interfaces:**
- Consumes: current maturity report and actual normal-surface oracle.
- Produces: accurate user-facing status without claiming unsupported PDF, terminal-free Human RC, or real-case completion.

- [x] Describe the available synthetic/local product journey through Recovery/Reopen and authoritative Word Delivery.
- [x] State that local final PDF is unavailable/fail-closed and not equivalent to the final professional artifact.
- [x] State that Stage 10 AI is proposal-only and never promotes itself to effective authority.
- [x] Keep real-case execution and Human RC as pending professional acceptance.

### Task 5: Verification and delivery

**Files:**
- Read: all changed documentation and JSON.

**Interfaces:**
- Consumes: all documentation changes.
- Produces: one reviewable documentation PR with no production mutation.

- [x] Run JSON parse, Ruff/compile where applicable, `git diff --check`, and relevant maturity/oracle tests.
- [x] Run `python -m scripts.quality.change_impact` for changed files.
- [x] Confirm no private files, external egress, product code, or gate changes.
- [ ] Obtain independent reviewer and systemic auditor evidence on the frozen documentation HEAD before merge.
