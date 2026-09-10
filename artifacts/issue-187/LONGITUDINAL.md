# Issue #187 — longitudinal normal-surface oracle

## Stable checkpoint

- Branch: `issue-187-longitudinal-oracle`
- HEAD: `563b684`
- PR: #196 (draft)
- Production changes: none
- Synthetic/private data only: yes
- Private egress: false

## Evidence

`python -m pytest tests/test_product_integration_oracle_v1.py::test_longitudinal_oracle_starts_with_synthetic_pje_through_product_bridge -q`

Result: `1 passed`.

`python -m pytest tests/test_product_integration_oracle_v1.py -q`

Result: `11 passed`.

`python -m ruff check tests/test_product_integration_oracle_v1.py` and
`git diff --check` passed.

## Single synthetic history proven

The test uses `build_pericial_application` and the browser-facing `/app-api`
surface for one workspace and one synthetic PJe export. It preserves plural
parties and representatives in the judicial domain, then executes:

PJe intake → Case Analysis and human reviews → Process Case → Planning and
approval → offline Inspection with observation, measurement and original photo
hash → sync → PAT_FINAL and professional approval → separate Technical
Findings and approval → Report with PATHOLOGY and TECHNICAL_FINDING claims →
approved Word Delivery → closed Budget → backup → recovery verify/staging/
promotion in a fresh runtime → reopen.

The reopened Case Analysis, Planning, Inspection, PAT, Technical Findings,
Report, Delivery and Budget payloads match the pre-backup snapshots exactly,
including revisions and canonical digests. Process Case and PJe intake also
match exactly. Delivery remains Word/DOCM; no local final PDF is claimed.

## Platform/coverage boundary

The mutable staging/promotion recovery authority is explicitly Windows-only;
the longitudinal oracle carries the repository's `WINDOWS_MUTABLE_RECOVERY`
skip marker and therefore skips on unsupported platforms rather than treating
`RECOVERY_PLATFORM_UNSUPPORTED` as a product failure. The oracle is a normal
surface integration proof, not a claim that the full Human RC or UI/Data Layer
is complete.

Independent systemic review at exact HEAD found P0=0, P1=0 and only this P2
platform-selection note; independent PR review likewise found no P0/P1.
