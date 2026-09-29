# PR B: canonical entry and grounded proposals

Authorized by #239 and the user's final-convergence handoff. PR A has a stable
causal result at e13c1f5; this isolated branch is stacked locally while A's
remote checks complete. It must be rebased onto integrated A before publication.

## Contract

- `PropertyRecord` is the sole structured owner of property identity/address,
  ownership, areas and construction characteristics. Coordinates stay in
  SITE_LOCATION; claimant/defendant stay in ProcessCase.
- A property field is saved through an explicit professional confirmation.
  A deterministic extraction is a proposal with document checksum, page,
  excerpt, method and confidence/conflict state. Confirming a proposal rereads
  current workspace sources. A new proposal never replaces a saved value.
- Existing ten ProcessCase fields and their review are preserved. Additional
  case-context extraction must use that owner/review path or stay clearly
  proposed, with no parallel writable copy of the same fact.
- Property/process captures are version-bound in reports. Upstream changes
  make dependent reports stale; old approved snapshots remain unchanged.
- Existing ExpertMasterProfile storage is workspace scoped. Explicit reuse
  can copy only professional identity into a new workspace's existing profile
  owner; it must never copy case data or rewrite historical report captures.
- UI: one property panel within Process, reused read-only in planning/inspection
  and report. Show human source labels and expandable provenance. No internal
  IDs to type, remote geocoder, provider, AI or new trust plane.

## Verification sequence

1. RED: property validation/unknown or coordinate fields; claimant not owner;
   exact source proposal, conflicts, explicit confirmation, wrong workspace,
   optimistic revision and saved-value preservation.
2. Domain/application/storage/transport/UI vertical slice and backup closure.
3. Report source capture, source changes/staleness and next-version behavior.
4. Profile reuse and source-grounded process proposal extensions, preserving
   legacy serialization where optional data is absent.
5. Focused regressions, affected frontend checks, privacy/tree/history scans,
   exact-candidate independent reviews, ordinary PR/CI/merge.
