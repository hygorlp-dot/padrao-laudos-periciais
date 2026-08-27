# REALISTIC_CASE_SURROGATE_ALPHA1_V1 Implementation Plan

> **Issue:** #128

**Goal:** Recover every supported process-metadata candidate available in a
realistic private PDF while preserving the schema-v4 rule that automatic data
remains non-effective until explicit human confirmation.

**Architecture:** Keep extraction local and deterministic. Scan native text
across the bounded document rather than only the first twelve pages, while
keeping OCR on a separate small budget and reporting every unprocessed page.
Derive only contractually deterministic justice candidates from checksum-valid
CNJ evidence. Present distinct ambiguous/conflicting candidates as explicit
review actions without pre-filling or confirming them. Allow the existing
loopback Product Bridge enough bounded time for the synchronous local scan.

**Safety constraints:** `INCORRECT + CONFIDENT` and `UNSUPPORTED + EFFECTIVE`
remain prohibited. No cloud/OCR/provider, telemetry, new field, automatic
confirmation, private path/token exposure, private fixture, PDF content, case
identifier, filename or screenshot may enter Git/GitHub.

## Task 1: Native coverage and bounded OCR separation

- [x] Add a synthetic many-page RED test proving default extraction visits a
  supported candidate after page 12 and reports complete coverage.
- [x] Add a RED test proving expanded OCR remains independently bounded after
  increasing native-page coverage.
- [x] Implement the smallest independent native-page, total-text and expanded
  OCR budgets; retain truthful `PARTIAL`/`NOT_PROCESSED` states at every bound.
- [x] Add boundary siblings for a candidate on the last page, a long earlier
  page, and an unavailable/OCR-limited page.

## Task 2: Useful fail-closed metadata candidates

- [x] Add RED tests proving a checksum-valid but unanchored CNJ remains
  `AMBIGUOUS` while its deterministic justice-branch/tribunal candidates retain
  exact occurrence provenance.
- [x] Preserve primary-anchor rejection, conflicting-CNJ behavior, OCR
  confidence bounds and schema-v4 non-confidence.
- [x] Implement only deterministic candidate derivation already represented by
  the production fields; do not infer unsupported locality, parties or unit.

## Task 3: Human-review presentation and local transport envelope

- [x] Add frontend RED tests proving distinct `AMBIGUOUS` candidates are visible,
  selectable by keyboard/click and never pre-filled or persisted without the
  existing explicit confirmation action.
- [x] Reuse the existing candidate affordance for `AMBIGUOUS` and `CONFLICTING`
  states, deduplicating repeated occurrences while retaining displayed source
  provenance.
- [x] Add a Product Bridge RED test for the bounded 30-second local processing
  envelope and set only that existing loopback timeout default; do not change
  payload, network or external-authority boundaries.

## Task 4: Focused and adversarial assurance

- [x] Run the focused extraction, OCR, metadata-flow, Process UI and Product
  Bridge suites, including malformed, repeated, multi-page, isolation,
  persistence/reopen and privacy siblings.
- [x] Re-run the private surrogate locally using only sanitized counts/booleans;
  require stable bytes/hash, complete or truthfully partial coverage, surfaced
  supported candidates, exact provenance and zero confident false positives.
- [x] Confirm no private PDF/path/value/screenshot entered the worktree or Git
  history.

## Task 5: Terminal delivery

- [x] Run changed-file Ruff, frontend lint/typecheck/build, `git diff --check`,
  repository safety, privacy/current-tree and publication-history scans.
- [x] Run exactly one terminal full regression and exactly one terminal
  `python -m scripts.quality.verify_core --full`.
- [ ] Publish one PR, require exact-head protected CI, one fresh independent PR
  Reviewer and one fresh Systemic Auditor; use diversity only if classified as
  required by current governance.
- [ ] Merge normally only with P0=0/P1=0, validate fresh protected main, then
  perform a fresh end-to-end surrogate run. Stop for the explicit production
  human-confirmation click if the product reaches that authority boundary.
