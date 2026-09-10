# Product Maturity Report V1

This report is derived from `config/product-maturity-v1.json` and the
first-party longitudinal product-integrity oracle. It records implementation
truth; it is not authorization to begin a later stage.

## Current-effective result

- Protected main SHA: `27175535933a2ff2185ffbd02819796274cdbeff`.
- PR #196 longitudinal oracle is merged and has an independent post-main proof: `11 passed` using synthetic data only.
  The final report-only/assurance SHA is recorded by the protected CI/review
  package after stable freeze; no moving branch name substitutes for either.
- Stages 0–9, 11 and 12 have implemented foundations covered by first-party
  boundary tests.
- Stage 8 supports the authoritative bound Word artifact. Local final PDF
  fidelity remains deferred by the protected trust boundary and is not claimed.
- Roadmap V6 Item 2, full product longitudinal reachability, is complete.
- Stage 10 is `IMPLEMENTED_PROPOSAL_ONLY`; it is not autonomous authority and does not make Human RC ready.
- `HUMAN_RC_READY = FALSE` and `PRODUCT_ROADMAP_STAGE_0_TO_12_COMPLETE = FALSE` because PDF fidelity and human acceptance remain outstanding.

## Historical status

Earlier reports recorded stale protected/PR SHAs and Stage 10 as
`NOT_IMPLEMENTED_OR_NOT_PROVEN`. Those statements remain historical records;
the current-effective state above is derived from merged main and the fresh
post-main oracle.

## Longitudinal assurance boundary

The product oracle joins the reviewed Case Analysis, reviewed Planning,
canonical Inspection and offline synchronization, professionally controlled
Technical Findings, approved Report, immutable Word Delivery, financially
separate Budget, and verified backup/restore/reopen chain. It also asserts
workspace isolation, append-only history, monotonic stale propagation and
absence of user-visible or persisted mojibake in the governed product roots.

Stage 10 is within the implemented foundation but remains proposal-only:

`SOURCE_VALUE → AI_PROPOSAL → ENGINE_DECISION → PROFESSIONAL_OVERRIDE`

AI output never becomes effective authority by itself. Explicit provider,
context/source binding, structured output, application revalidation,
append-only audit and token/cost ceilings are covered by first-party tests.

## Verified outcomes

- Field/Mobile recovery: canonical Inspection reuse, revision-aware offline
  synchronization and original-media SHA-256 closure are covered; pending
  offline work blocks backup before workspace acquisition.
- Backup/restore/reopen: exact revision identities, checksums, payload history
  and every private source/media/template/final-artifact byte are compared after
  recovery. Canonical process-metadata and OCR-cache artifacts remain
  recoverable. Cross-workspace inner payloads and incomplete dependency graphs
  fail closed.
- Authority oracle: Report approval and professional identity must resolve in
  the exact bound Report; generic or foreign authority is rejected.
- Stale oracle: a previously stale source cannot become current by restoring
  old bytes, and an upstream binding change demotes delivered state to `STALE`.
- Financial separation: Budget/court/payment history has no authority edge into
  Technical Findings, Report or Delivery.
- Word delivery: final DOCX/DOCM bytes are hash-bound and structurally revalidated on
  backup verification/recovery. Local final PDF remains unavailable fail-closed.
- Workspace oracle: two-workspace/foreign inner identities fail closed.
- Private egress: `FALSE`; all oracle fixtures and execution are local and
  synthetic.

## Gate accounting and debt

- Target release gate: `P0 = 0`, `P1 = 0` after independent terminal review.
- P2 observations must be recorded in the final review package and do not imply
  Stage 10 readiness.
- Historical timing debt: the prior stable-main `verify_core --full` recorded
  `FULL_GATE_DURATION_REGRESSION` at 159.755 seconds against the historical
  60-second threshold; the post-main run observed 345.693 seconds. Semantic
  gates passed and the timing debt remains explicitly visible rather than being
  hidden by retries.
- Human RC readiness: `FALSE`; professional acceptance is still required.
- Historical timing debt remains nonblocking and tracked in Issue #192; this
  reconciliation does not alter the 60-second threshold or hide the debt.
