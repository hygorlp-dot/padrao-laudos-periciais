# Longitudinal Product Integrity Oracle V1 — Implementation Plan

**Issue:** #173  
**Branch:** `feat/173-longitudinal-product-integrity-oracle`  
**Base:** protected `main` at `67f074b2ca37d9ed998736b9c86dc90af325b89d`

## Scope and invariants

Build one synthetic, deterministic product oracle spanning Stages 3–9, 11 and
12. It must prove effective reviewed authority, immutable history, explicit
stale propagation, financial/technical separation, workspace isolation,
backup/restore/reopen integrity and truthful roadmap status. Stage 10 remains
not implemented/not proven. No private data or external egress is permitted.

## Causal DAG

1. Workspace and synthetic source authority
   -> reviewed Case Analysis
   -> reviewed Planning
   -> canonical Inspection and revision-aware offline/mobile synchronization
   -> professionally decided Technical Findings
   -> approved Report
   -> bound, verified and immutable final Word Delivery
   -> verified backup/restore/reopen.
2. Budget/court/expense/payment/closure is an independent financial lane joined
   only by process/workspace identity; it never becomes technical authority.
3. Workspace-isolation, mojibake and roadmap-truth checks are independent
   read-only/focused lanes and join before terminal freeze.

The critical path is monotonic source authority -> descendant stale propagation
-> restored effective authority. One mutation owner applies all shared-boundary
changes.

## Execution

### 1. RED — monotonic source authority

- Add a focused regression proving that a post-approval source mutation cannot
  be erased by restoring identical prior bytes before descendants are opened.
- Require Delivery and every affected descendant to remain stale until explicit
  review/reissue.
- Reproduce on current protected-base behavior before changing production.

### 2. GREEN — minimum authority repair

- Persist the smallest append-only/monotonic source-authority revision needed
  by the existing Case Analysis binding.
- Carry that authority transitively through existing snapshot bindings rather
  than introducing a parallel domain model.
- Preserve reopen compatibility with existing valid state through an explicit
  migration/default strategy; never silently reinterpret historical snapshots.

### 3. Longitudinal oracle

- Add `tests/test_product_integration_oracle_v1.py` using real application
  services and synthetic fixtures/bytes.
- Prove the complete authority chain, generic authority attacks, stale cuts,
  immutable histories, financial/technical separation, pending-offline backup
  refusal, synced-media backup/restore/reopen, and two-workspace isolation.
- Add only the smallest API/schema companion assertions required to prove
  reachability through current product composition.

### 4. Truth and presentation audits

- Remove only reproduced user-visible or persisted mojibake; do not blanket
  transcode repository history.
- Correct canonical maturity claims so Stage 10 is explicitly
  `NOT_IMPLEMENTED_OR_NOT_PROVEN` and Stage 0–12 completion remains false.
- Produce the product maturity report from verified oracle evidence.

### 5. Pre-terminal and terminal assurance

- Run the pre-terminal adversarial matrix and sibling-defect sweep against all
  authority/stale boundaries affected by the root cause.
- Run focused/change-impact tests during RED/GREEN; avoid redundant full runs.
- Freeze one stable exact HEAD, then run one full regression and one
  `python -m scripts.quality.verify_core --full`.
- Run independent PR review and systemic review on that exact SHA, then use
  protected CI, normal merge and post-main longitudinal verification.
- Close #173 only after post-main PASS. Stop; do not start Stage 10.
