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

## Post-reboot evidence and bounded diagnostic increment

The first hosted run at `5e6162e1f72a51386be73fd3f09838c30138645f`
identified this non-symlink node:

`tests/test_recovery_transaction_v1.py::test_journal_corrompido_sobrevive_a_reabertura_como_sobrevive_ao_fechamento`

Therefore `SYMLINK_ONLY_HYPOTHESIS` is invalidated or incomplete. Fresh local
executions on Windows with Python 3.13.15 passed for the exact node, for the
exact node under coverage, and for its two immediate journal neighbors under
coverage. No product repair is authorized from that evidence.

The single additional diagnostic increment is limited to: node ID, pytest
phase, exception class obtained from `call.excinfo`, repository-relative
location, and a categorical message (assertion, numeric OS error, or redacted).
It never emits the raw exception message or an absolute path and does not
change test selection, assertions, timeout, workflow, or `verify_core`.

## Owner-authorized observability promotion adjudication

The later owner directive for Human RC readiness supersedes only the
diagnostic-only merge restriction above. It authorizes promotion to permanent
`FIRST_PARTY_TEST_FAILURE_OBSERVABILITY` when the harness remains product- and
selection-neutral, private-safe, bounded, and green on the exact protected
HEAD with independent review.

Independent review of `14deb4a54be70b21a8769c3f067e1c665dc83bd5`
correctly blocked promotion: raw parameter payloads could escape through
`report.nodeid`, the diagnostic collection was unbounded, and a later
`pytest_unconfigure` hook could displace the marker from the final stderr
line. The causal repair redacts all parameter values, accepts only real
repository-owned test identities and non-private repository locations, caps
fields and failure count, and emits after all non-wrapper unconfigure hooks.
Promotion still requires fresh exact-HEAD protected CI, reviewer, and systemic
audit evidence with P0/P1 equal to zero. It does not establish a recovery
defect or a root cause for Issue #192.
