# Recovery namespace identity-continuity reconciliation (#183 / PR #186)

> **Execution note:** apply `executing-plans`, test-driven development,
> safety engineering, systematic debugging and the repository safety gate.
> `36dcfe9550ccb902bf1b5dd5dae37dca48fd11c2` is invalidated. No review approval
> from an earlier SHA is reusable.

**Goal:** Bind recovery child creation to its first physical handle and bind
final cleanup to the expected physical identity through namespace removal,
without a pathname rebind gap, external mutation or optimistic success.

**Scope:** Issue #183 / PR #186 only. No Delivery/PDF, AI, Skills, Budget,
packaging, trust-plane, branch-protection, egress or merge changes.

## Causal DAG and critical path

```text
A14 creation P0 ----> H.3 authority contract ----> creation RED
                                               \-> relative NtCreateFile create
A14/B14 removal P0 -> durable expected identity -> removal RED
                                               \-> handle-bound disposition
both repairs -> focused GREEN -> prior matrices -> sibling/systemic sweep
             -> pre-terminal gates -> one verify_core --full
             -> exact commit/push/protected CI -> parallel A15/B15
```

The critical path is the two physical-identity primitives and their durable
handoff. Official-API research is the only safe parallel lane before GREEN.
One mutation owner owns every shared recovery boundary. A15/B15 start only
after protected CI is green on the exact frozen HEAD.

## Task 1: Freeze architecture and API choice

**Files:**
- Modify: `docs/arquitetura/recuperacao-transacional-v1.md`
- Create: this plan

- [x] Map every create/open/validate/write/close/unlink/rmdir/path reconstruction.
- [x] Record creation, removal, TOCTOU and commit-oracle contracts.
- [x] Compare official Windows API candidates and choose a narrow recovery-only primitive.
- [x] Incorporate the independent 24-criterion research report reference and SHA-256.

## Task 2: Add deterministic RED proofs

**Files:**
- Modify: `tests/test_recovery_transaction_v1.py`

- [x] Reproduce post-create/pre-first-handle replacement with an external sentinel.
- [x] Assert no quarantine, SQLite, private content or intent is written externally.
- [x] Reproduce close-before-rmdir replacement and false success.
- [x] Cover explicit DISCARD and ABANDON identity handoff before staging close.
- [x] Cover identical logical tree/control bytes with different physical identity.
- [x] Prove intent retention, retry identity continuity and positive convergence.
- [x] Run the exact selection against the invalid HEAD and record RED evidence.

## Task 3: Implement atomic Windows child creation

**Files:**
- Modify: `scripts/backend_contract/application/workspace_recovery.py`
- Modify only if needed: `scripts/backend_contract/infrastructure/productization.py`

- [x] Add private ctypes definitions for documented user-mode `NtCreateFile`.
- [x] Create a one-component directory relative to the held parent with `FILE_CREATE`.
- [x] Return/bind the created handle identity before any first write.
- [x] Use the primitive for absent recovery base and `recovery-<uuid>` creation.
- [x] Preserve POSIX `dir_fd` / `O_NOFOLLOW` behavior.

## Task 4: Keep expected identity through terminal removal

**Files:**
- Modify: `scripts/backend_contract/application/workspace_recovery.py`
- Modify: `tests/test_recovery_transaction_v1.py`

- [x] Version the cleanup intent to include its expected physical identity.
- [x] Capture identity before `staging.discard()` in every explicit cleanup path.
- [x] On Windows, open the exact child with `DELETE` and no delete-sharing.
- [x] Remove child/root directories with `SetFileInformationByHandle`.
- [x] Require `FILE_STANDARD_INFO.DeletePending` before consuming the handle.
- [x] Prove expected namespace absence under the still-held parent before intent GC.
- [x] Retain on replacement, uncertainty or ambiguous close; never delete the replacement.
- [x] Preserve exact `FileExists`, quarantine ordering and one-shot close behavior.

## Task 5: Focused GREEN and adversarial expansion

- [x] Run the 23-scenario creation/removal/identity selection on Python 3.13.
- [x] Run complete recovery transaction and reachability boundaries on Python 3.13.
- [x] Run the focused boundary on Python 3.14.
- [x] Run prior disposition, ancestry/reparse, descriptor ambiguity, process-death,
      restart and concurrency matrices.
- [x] Perform `SIBLING_DEFECT_SWEEP_V2` over all recovery namespace consumers.
- [x] Perform `PRE_TERMINAL_ADVERSARIAL_MATRIX_V1` and read-only
      `SHADOW_SYSTEMIC_REVIEW_V2`; fix only reproduced same-cause gaps.

Evidence before terminal freeze:

- identity-continuity selection: `16 passed, 106 deselected` on Python 3.13
  and Python 3.14; the parametrized oracles cover the 23 required scenarios;
- complete recovery boundary: `120 passed, 2 skipped` on Python 3.13;
- change-impact recovery consumers: `69 passed`; adjacent productization/PJe/
  integration consumers: `60 passed`;
- the sibling sweep reproduced and repaired two same-cause gaps before freeze:
  child-directory deletion errors were swallowed, and a prior `COLLECT` intent
  could not resume after its internal controls had already been consumed;
- the pre-terminal shadow report is persisted outside the repository at
  `%TEMP%/pr186-preterminal-shadow-systemic-review.md` and contains no private
  data.

## Task 6: Stable terminal candidate

- [x] Run Ruff, mojibake, schema/fixture and diff/config safety gates.
- [x] Run the complete backend suite; frontend was not run because its tree did
      not change (`2799 passed, 8 skipped, 104 subtests passed`).
- [ ] Freeze source, commit the exact candidate and verify a clean worktree.
- [ ] Run `python -m scripts.quality.verify_core --full` exactly once on that SHA.
- [ ] Push and require protected CI on the identical `headRefOid`.
- [ ] Make no mutation after terminal freeze.

## Task 7: Independent terminal assurance

- [ ] Start A15 reviewer and B15 systemic auditor concurrently, in separate
      read-only checkouts with explicit BASE/HEAD and SHA-bound reports.
- [ ] Do not share findings between reviewers.
- [ ] If either reports same-family P0/P1, stop without A16/B16 and declare
      `RECOVERY_NAMESPACE_IDENTITY_MODEL_STILL_INCOMPLETE`.
- [ ] Do not merge PR #186.
