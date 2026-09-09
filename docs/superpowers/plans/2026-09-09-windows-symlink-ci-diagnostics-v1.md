# Windows Symlink CI Diagnostics V1 — Implementation Plan

**Issue:** #192
**Blocked PR:** #191
**Branch:** `fix/192-windows-symlink-ci-diagnostics`
**Base:** protected `main` at `d6d0cd1e69a09d59c2200b9e689319bb8c17f926`

## Causal DAG

1. Windows hosted CI can create symlinks and therefore runs four tests skipped
   by the local unprivileged Windows account.
2. The same protected bytes vary between zero, one, two, and three regression
   failures across hosted runs.
3. `verify_core` intentionally reports only the last captured pytest line, so
   the failed node identities are lost.
4. Without the node identities, changing product or tests would be speculative.
5. First add a bounded, sanitized pytest-session diagnostic outside the
   protected verifier/workflow; then use one CI execution to identify the real
   failing boundary and design a causal repair.

Critical path: `diagnostic RED -> diagnostic GREEN -> hosted evidence -> root
cause -> deterministic repair`. PR #191 remains frozen throughout.

## Constraints

- Do not modify `scripts/quality/verify_core.py`, protected workflows, judges,
  branch protection, or product code.
- Do not skip, deselect, weaken, or replace the four symlink contracts.
- Emit only repository-owned pytest node IDs; no payloads, paths, secrets, or
  private data.
- Keep clean-run output unchanged.
- Preserve pytest exit status and all existing test selection.

## Tasks

1. Add a RED proving failed call/setup/teardown reports are deduplicated,
   sorted, JSON-escaped, and emitted on stderr at unconfigure time.
2. Implement the minimum hooks in `tests/conftest.py`.
3. Run focused harness tests and the affected four-test local capability
   matrix, then inspect change impact and diff hygiene.
4. Push a diagnostic PR. Its first hosted `core-safety` run is expected to
   expose exact failing node IDs if nondeterminism recurs; it is not a merge
   candidate until the underlying failure is causally repaired.

