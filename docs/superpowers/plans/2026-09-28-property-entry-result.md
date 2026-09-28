# PR B — reusable entry and version-bound report identity

Scope: #239, following the stable #246 candidate. This local branch is stacked
until PR A is integrated; it is not a release or Human RC result.

## Implemented

- One PROPERTY_RECORD_V1 owner for 22 property/address/contract fields. Neither
  process parties nor coordinates are writable here. The property panel reads
  confirmed SITE_LOCATION coordinates and links to the existing location view.
- Local explicit-label PDF proposals retain document identity/checksum, page,
  excerpt, extraction method, confidence and conflict state. Selecting a proposal
  does not save it. Confirmation rereads current sources and preserves other
  fields; concurrent saves require reloading. Collapsing the panel preserves
  unsaved typing. Claimant is never silently used as owner.
- Existing ten ProcessCase fields and their extraction/review are unchanged.
  Reports capture the exact confirmed process and property revisions. Source
  changes make the report stale; new versions recapture current data and restart
  review. Existing serialized reports omit absent optional captures as before.
- The professional output uses captured process number/court and property facts.
  Backups validate captured values against their exact source revisions/digests
  and preserve property evidence plus the confirming professional identity.
- The existing workspace-scoped ExpertMasterProfile remains the only writable
  professional identity. Its form is available in Process and Report. Explicit
  reuse previews only another workspace's professional profile and saves a new
  local revision through the existing owner; it copies no case data.
- Planning and inspection reuse a read-only property summary. The report view
  displays its own captured revision, not a live value presented as historical.

## Extraction investigation and limits

| Information | Disposition |
| --- | --- |
| Existing ten process identity fields | Preserve current source extraction/review; no parallel editor. |
| Development, company, program, contract number/value, habite-se, address and areas | Explicit-label proposals in the canonical property record; never automatic facts. |
| Appointment decision and questions | Existing CaseAnalysis owns these; investigate intake/recoverability in C instead of adding property fields. |
| Subject/action, claim amount, prior report identity/professional/date/estimate | No source-independent default. Narrative interpretation needs the existing CaseAnalysis source/review path; an arbitrary amount/date/professional in a PDF is not sufficient grounding for auto-fill. |
| Qualifications, IBAPE and office identity | Existing profile fields are reused first. No speculative extra persistence or trust authority introduced. |

The proposal extractor is deliberately limited to explicit labels in pages the
existing local PDF reader can read. An empty result is not a finding that the
information is absent from the case. It does not infer ownership, cause, legal
qualification or truth from an allegation.

## Evidence before final independent review

- 453 affected backend/domain/API/bridge/recovery tests passed; 17 focused
  property/process tests passed after the final version/dependency checks.
- Frontend build and lint passed; 205 tests passed before the last coordinate
  reference/collapse regression, whose focused tests also passed.
- Actual local product UI: created a synthetic workspace, configured its
  professional, saved property values and reloaded them successfully. Synthetic
  screenshots are external to the repository at `C:/tmp/plp-239-ui/`.
- Desktop at 1280 px was inspected. At 390 px the existing body minimum of
  760 px remains, including with the new property panel closed; this is an
  existing whole-shell limitation, not claimed as mobile readiness.
- The change-impact mapper conservatively requests the full invariant set for
  these product paths. Full gate and final independent review remain mandatory.
- No private reports, reference PDF text/images, provider, geocoder, protected
  Word/PDF runtime file or trust-plane change is included.

## Independent review corrections

The independent reviewer and systemic auditor inspected candidate `980bd11`.
The material findings were reproduced before correction:

- Save validated process revision N but could guard N+1 after a second read.
  Dependencies now bind the exact captured process/property revision and digest;
  an intervening commit conflicts without appending the report.
- A resealed backup could claim an invented page/excerpt/extraction method while
  retaining genuine document bytes. Recovery now replays the existing local PDF
  reader and explicit-label extraction and requires the exact evidence match.
  This also passed with a synthetic scanned PDF and the real local OCR engine.
  If the pinned reader/model cannot reproduce evidence, verification fails
  explicitly; it does not certify unverified provenance.
- Partial process captures cannot be approved when process number or court is
  missing. The review screen explains the captured identity deficiency.
- Canonical audit export includes process/property captures and their evidence.

After these fixes: 228 affected backend tests passed; 207 frontend tests passed
with one worker; TypeScript/build, ESLint and affected Ruff checks passed.
Earlier frontend runs concurrent with the heavy core gate timed out on long
typing tests. The isolated full run passed without increasing timeouts.
Final exact-commit independent closure and the fresh full core gate are pending.
