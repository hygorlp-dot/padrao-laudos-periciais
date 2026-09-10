# Issue #187 Baseline

HEAD: `e0171c3380926af457d52d82dc778f870cf3596a`
Provenance: synthetic fixtures only; no private case material or external service.

## Fresh protected-main evidence

- `python -m pytest tests/test_product_integration_oracle_v1.py -q` — `10 passed`.
- `python -m pytest tests/test_product_bridge_v1.py -q` — `62 passed`.
- `python -m pytest tests/test_pje_workspace_bridge_v1.py tests/test_pje_backup_semantic_closure_v1.py -q` — `14 passed`.
- `python -m pytest tests/test_backup_recovery_reachability_v1.py -q` — `27 passed`.

## Current gap classification

The existing D1–D11 oracle proves the long chain through the Local API and
persists/compares synthetic snapshots and hashes. The ProductBridge suite proves
many stage commands and the recovery journey, but no single test currently starts
from a synthetic PJe export and carries that same history through the ProductBridge
surface into Delivery, Budget, Backup, Recovery and Reopen. This is classified as
an oracle coverage gap, not a product defect, until a normal-surface RED proves
otherwise.
