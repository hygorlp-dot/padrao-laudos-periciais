# Product Maturity Report V1

This report is derived from `config/product-maturity-v1.json` and the
first-party longitudinal product-integrity oracle. It records implementation
truth; it is not authorization to begin a later stage.

## Current-effective result

- Protected main SHA (evidence base): `08263c5566e96a2cc3f4327d351906c314d5415b`. The frozen
  `FINAL_RC_CANDIDATE_SHA` is the merge of the V7-5/V7-6 reconciliation and is
  recorded in Issues #256 and #238 (a commit cannot carry its own SHA).
- Roadmap V7 (#256), pre-RC closure:
  - V7-1 visit facts and quesitos intake (#255);
  - V7-2 F8 — a delivery-support PDF never enters the case source inventory (#253, PR #257);
  - V7-3 F7 — explicit, empty successors for a stale Planning (PR #258), Inspection
    with professional, record-by-record reuse by lineage (PR #260), Technical Findings
    and Construction Defect Analysis (PR #262); predecessors stay immutable;
  - V7-4 hybrid timing attribution (decision `2-III`): the semantic gate blocks; above
    the unchanged 60-second reference the same runner measures BASE and only a
    candidate delta above `max(60 s, BASE × 0.10)` blocks, identically on pull requests
    and `main` (sharded core-safety, #259 and #261);
  - V7-5 this reconciliation;
  - V7-6 `tests/test_v7_final_rc_oracle_v1.py`: the product as a real OS process,
    killed and restarted on the same storage, covering F8, F7, PJe exclusion and
    re-enable, workspace isolation, backup verify and, on the Windows runner,
    staging → explicit promote → reopen in a new process.
- The longitudinal oracle (`tests/test_product_integration_oracle_v1.py`) continues to
  prove the full happy path on the same SHA.
- Stages 0–9, 11 and 12 have implemented foundations covered by first-party
  boundary tests.
- Stage 8 delivers the authoritative bound Word artifact and a derived PDF
  rendered locally by Microsoft Word 16 in the contained worker (#204, #223),
  accepted only after structural and visual fidelity checks and bound by
  SHA-256 (#202, #203). Word stays authoritative; any refusal leaves the Word
  and no PDF.
- Stage 10 is `IMPLEMENTED_PROPOSAL_ONLY`; it is not autonomous authority.
- `HUMAN_RC_READY = TRUE`: every automated pre-RC step is closed. Human acceptance
  (`HUMAN_RC_WINDOWS_V2`, #238) has not been executed; `HUMAN_RC_ACCEPTED = FALSE`,
  no real case has been run and there is no installer (`PACKAGING_GAP`).
- `PRODUCT_ROADMAP_STAGE_0_TO_12_COMPLETE = FALSE` because Stage 10 is proposal-only
  and human acceptance remains outstanding.
- Repository visibility: GitHub reports the repository as public while earlier text
  described it as private. Changing visibility is a pending human decision; it does
  not block the synthetic Human RC. Real data is never versioned in any case.

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
  backup verification/recovery. The derived PDF is hash-bound to the exact Word
  bytes it was rendered from and is never carried across a re-render.
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
- Human RC readiness: `TRUE`; professional acceptance (#238) is still required.
- Historical timing debt (#192) is superseded by the hybrid attribution policy
  (`docs/arquitetura/decisoes/ADR-hybrid-timing-attribution-v1.md`); the 60-second
  reference is unchanged and the runtime cost is tracked in Issue #259.
