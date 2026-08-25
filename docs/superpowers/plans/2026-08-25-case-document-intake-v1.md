# CASE_DOCUMENT_INTAKE_V1 Implementation Plan

> **Issue:** #117

**Goal:** Import, persist, list and open PDF case documents through the real
local product stack without exposing filesystem authority, private paths or the
Local API token to the browser.

**Architecture:** Add three document-specific Application use cases over the
existing immutable `PrivateContentRepository`. Expose only exact workspace-bound
material routes in the Local API and Product Bridge. Transfer PDF bytes as a
bounded raw body; treat the encoded original filename only as metadata. Compose
the already-protected filesystem store from one explicit pre-provisioned private
root. Render a workspace-aware `Materiais` view with empty, importing, ready and
controlled error states.

**Constraints:** PDF only; synthetic fixtures only; no OCR, PJe automation,
cloud/provider/network, semantic classification, generic filesystem endpoint,
absolute path in browser-facing data, storage redesign or private-data egress.

## Task 1: Application document boundary

- [ ] Write RED tests for valid PDF import, exact bytes/hash/provenance, invalid
  PDF, unsupported media type, oversized input and workspace isolation.
- [ ] Implement minimal typed document use cases by composing the existing
  private-content services and records.
- [ ] Keep filename literal metadata; never derive a physical name from it.

## Task 2: Local API and Product Bridge

- [ ] Write RED tests for exact POST/list/read routes, private-read token
  requirement, canonical workspace/content IDs, controlled failures and binary
  responses.
- [ ] Add exact allowlisted bridge routes and forward only the validated PDF
  media type plus encoded filename metadata.
- [ ] Compose and close the explicit private store with the product runtime;
  require explicit private-root provisioning in the CLI.
- [ ] Prove duplicate filenames do not collide, A/B isolation survives reopen,
  and no browser-facing response contains a private path or token.

## Task 3: Real UI

- [ ] Write RED data-layer and component tests for empty, import-in-progress,
  ready, retryable error, invalid file and open-document behavior.
- [ ] Add the dedicated workspace route `/materiais` after `Processo`.
- [ ] Implement accessible file selection/import and the smallest useful list,
  preserving visible focus and responsive layout without decorative motion.

## Task 4: Assurance and delivery

- [ ] Run focused Python/frontend/adversarial suites, changed-file Ruff, lint,
  typecheck, build, repository safety, privacy, full regression and
  `verify_core --full`.
- [ ] Push one exact HEAD, require protected CI and fresh independent PR
  Reviewer/Systemic Auditor. Use external diversity only if current governance
  classifies the stable diff as requiring it.
- [ ] Merge normally only with P0=0/P1=0, verify protected main and close #117.
- [ ] Continue to `MATERIAL_CATALOG_V1` only after this capability is stable.
