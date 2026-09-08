# Recovery filesystem trust-anchor reconciliation (#183 / PR #186)

> **Execution note:** apply `executing-plans`, TDD, safety engineering and the
> repository safety gate. `e5993c0f` is invalidated; no terminal candidate is
> created before every pre-terminal gate is green.

**Goal:** Make every recovery enumeration, open, sidecar operation and cleanup
fail closed unless the complete local ancestry from the filesystem root through
`.sqlite3.recovery` and the selected `recovery-<uuid>` remains under continuous
custody.

**Causal DAG / critical path**

```text
map every pathname consumer
  -> freeze trust-anchor model in architecture
  -> RED ancestry/junction/TOCTOU matrix
  -> narrow custody primitive
       -> staging create/open custody
       -> startup/list/intent-GC base custody
       -> destructive child/descendant custody
  -> focused GREEN + prior fault-injection regression
  -> sibling/systemic sweep
  -> stable-HEAD terminal assurance and protected CI
  -> independent A14 and B14
```

One mutation owner owns the shared recovery namespace boundary. Independent
review lanes start only after the stable HEAD is frozen.

## Task 1: Freeze the filesystem authority model

**Files:**
- Modify: `docs/arquitetura/recuperacao-transacional-v1.md`

1. Record the filesystem root as the first trust anchor.
2. Record component-by-component no-follow acquisition and continuous custody.
3. Specify POSIX `dir_fd` and narrow Win32 directory-handle semantics.
4. Specify all rejected alternatives and the TOCTOU/crash matrix.
5. Commit the documentation checkpoint before production changes.

## Task 2: Add deterministic RED proofs

**Files:**
- Modify: `tests/test_recovery_transaction_v1.py`

1. Add a shared external-tree hash/sentinel oracle and safe junction fixture.
2. Cover base/parent junctions with empty, marker, descriptor, journal and
   cleanup-intent external trees.
3. Exercise startup collection/reconstruction, list, stage, discard, abandon,
   retries and intent GC.
4. Inject base/root swaps, rename attempts, late junctions and descendant
   reparses.
5. Assert zero external open-for-write, intent publication, deletion or byte
   change, plus a normal-namespace control.
6. Run the new selection and observe failure against `e5993c0f`.
7. Commit the RED checkpoint.

## Task 3: Implement the narrow recovery custody boundary

**Files:**
- Create: `scripts/backend_contract/infrastructure/recovery_filesystem.py`
- Modify: `scripts/backend_contract/infrastructure/productization.py`
- Modify: `scripts/backend_contract/application/workspace_recovery.py`
- Modify: `scripts/backend_contract/local_api/composition.py`

1. Implement local/absolute validation and component-wise acquisition.
2. On POSIX, use held directory descriptors and relative namespace operations.
3. On Windows, open directories themselves with no reparse traversal and no
   delete sharing; validate directory/reparse attributes and stable identity;
   consume each handle before its one close attempt.
4. Make recovery-base creation and child creation/open retain custody through
   staging lifetime.
5. Route startup enumeration, sidecar publication/read/GC and cleanup through
   base custody before any traversal or mutation.
6. Replace child anchor-file custody with directory-handle custody on Windows,
   preventing an external write during acquisition.
7. Keep the existing durable disposition, quarantine ordering, exact-byte
   `FileExists`, and no-double-close contracts unchanged.

## Task 4: Focused GREEN and adversarial matrix

1. Run the new ancestry/TOCTOU selection on Python 3.13.
2. Run the complete recovery boundary tests on Python 3.13.
3. Run the same focused boundary on Python 3.14 as compatibility evidence.
4. Run the prior cleanup fault-injection/process-death/concurrency matrix.
5. Perform `SIBLING_DEFECT_SWEEP_V2` over every recovery namespace consumer.
6. Fix only same-cause defects and repeat focused checks.

## Task 5: Stable terminal candidate

1. Run Ruff, mojibake, schema/fixture and diff/config safety gates.
2. Run the complete backend suite (frontend only if affected).
3. Run `python -m scripts.quality.verify_core --full` exactly once on the stable
   frozen HEAD.
4. Commit, verify clean worktree, push the exact SHA and require protected CI.
5. Only after CI passes, run A14 and B14 concurrently in isolated read-only
   checkouts with explicit BASE/HEAD.
6. If either finds P0/P1 in ancestry/reparse/custody/path identity/namespace,
   stop without A15/B15 and return to architecture.

