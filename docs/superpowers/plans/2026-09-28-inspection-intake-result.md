# Inspection facts and source intake — candidate result (#239)

This causal change follows the stable property-entry candidate. It adds no
remote service and does not change protected Word/PDF or trust infrastructure.

## Implemented

- InspectionSession owns an optional physical visit date, start/end, observed
  weather, measured temperature/humidity and explicitly confirmed attendees.
  The dedicated revision-guarded command stamps the existing expert identity.
  Session creation time is not substituted for the visit date. Generic saves
  and offline updates cannot invent confirmation. Legacy bytes omit the field.
- The inspection form can reuse the confirmed property address and offer known
  party/owner names. A suggested person starts unconfirmed. Instrument identity
  and method procedure can be copied from earlier records in this inspection;
  each new reading remains explicit and does not inherit calibration claims.
- CaseAnalysis receives local PDF/OCR question proposals with original text,
  numbering, explicit origin, document identity, page span, excerpt and method.
  Acceptance recomputes the proposal against current private bytes, rejects
  stale revisions and avoids exact duplicates. Existing professional review,
  question-to-finding and question-to-answer authority remain intact.
- Nine recurring document categories have source proposals and independent
  professional confirmation. Not found in the ingested material is never
  automatically promoted to absent from the case. Confirmation requires a
  reason, the expert profile and source documents for presence.
- Backup verification replays question provenance against the original local
  PDF/OCR source, and checks profile ownership for visit/inventory confirmation.

## Causal verification

New visit/intake imports failed before implementation. Focused tests exercise
literal extraction, PJe physical-page boundaries, no inferred origin, document
title versus a narrative mention, duplicate acceptance, authorization, stale
revision, forged confirmation and resealed-backup source fabrication.

258 affected case/inspection/report/API/bridge/recovery tests passed; the later
offline regression (including a forged visit context) passed 68 tests. The
instrument reuse UI test verifies blank current reading and no copied
calibration. Build/TypeScript, ESLint and affected Ruff checks passed.

Actual local UI checks used API-seeded synthetic workspaces, then confirmed and
reloaded a changed visit condition and accepted/reloaded a source question.
Desktop screenshots were inspected at 1280 px with no horizontal overflow in
the new forms. Artifacts are outside Git under `C:/tmp/plp-239-C-ui/` and
`C:/tmp/plp-239-C-ui2/`. This is not claimed as the final full normal-UI oracle.
An empty photo library returns the existing expected 404; no new JS exception
was observed. The existing whole-shell mobile minimum remains outside scope.

The unconstrained full frontend run timed out in a long existing ProcessCase
typing test, contaminating the next mock. Its isolated 15 tests passed; the
full suite then passed 210 tests in 31 files with two workers, without changing
test timeouts (33.46 seconds).
Final exact-SHA independent review, privacy and full core results are recorded
outside this candidate to keep review evidence tied to an immutable commit.

## Deliberate limits

Question extraction supports explicit origin headings and numbered blocks.
Ambiguous/multicolumn or unsupported source structures continue through the
existing source review; no result is not proof of no questions. The extractor
does not paraphrase, interpret legal content or infer which party asked.

Cross-workspace instrument/method catalogs remain deferred: the existing
inspection records support safe reuse without adding a parallel persistence
owner. Structured references retain the current report-owned model; references
from another matter require explicit selection and applicability review.
Visit/inventory/question metadata enter professional report presentation in
the following report-presentation change, not through an editable second copy.
