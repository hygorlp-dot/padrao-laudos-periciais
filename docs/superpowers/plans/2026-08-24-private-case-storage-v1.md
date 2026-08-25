# PRIVATE_CASE_STORAGE_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and reopen private bytes bound to exactly one `PericiaWorkspace`, with deterministic identity, integrity, provenance, atomic visibility and local filesystem isolation.

**Architecture:** Application owns immutable private-content records, a dedicated repository port and three explicit use cases. Infrastructure implements that port under one runtime-configured, singleton-anchored flat private root using UUID-only physical identities, canonical manifests, SHA-256 verification, no-replace hard-link publication, a commit marker, a write-ahead intent journal and an independent confirmation anchor. POSIX operations are root-`dir_fd` relative; Windows keeps the only ancestor anchored by the open singleton. SQLite remains the workspace authority and is not expanded with blobs or an unrelated metadata table.

**Tech Stack:** Python 3 standard library (`dataclasses`, `enum`, `hashlib`, `json`, `os`, `pathlib`, `tempfile`, `uuid`), existing SQLite workspace repository, pytest/Hypothesis.

## Global Constraints

- Delivery Issue: #107; parent concern: #13; base: `dd2d74cc4a0baec555c47677f1c8fc67ce46ec3b`.
- No UI, HTTP/Local API endpoint, browser storage, OCR/PDF/PJe intake, provider, network, telemetry or external dependency.
- No private bytes in Git, SQLite, `ArtifactRevision` payload JSON, logs, URLs or review packages.
- Private root is explicit runtime configuration; tests use temporary directories and synthetic bytes only.
- `FAIL_CLOSED`, `NO_SILENT_LOSS`, `WORKSPACE_ISOLATION`, `CONTENT_INTEGRITY`, `PATH_CONTAINMENT`, `NO_PATH_TRAVERSAL`, `NO_PRIVATE_DATA_EGRESS`.
- Same bytes or human filename create distinct workspace-local import records; no global/cross-workspace deduplication.
- No update/delete API and no silent corruption repair.

---

### Task 1: Define the Application private-content contract

**Files:**
- Modify: `scripts/backend_contract/application/models.py`
- Modify: `scripts/backend_contract/application/ports.py`
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `scripts/backend_contract/application/__init__.py`
- Create: `tests/test_private_case_storage_v1.py`

**Interfaces:**
- Produces: `PrivateContentId`, `PrivateContentOrigin.LOCAL_IMPORT`, `PrivateContentMetadata`, `PrivateContent`, `PrivateContentRepository`, `PrivateContentNotFound`, `StorePrivateContent`, `GetPrivateContent`, `ListPrivateContents`.
- `PrivateContentRepository.store(metadata, content) -> PrivateContentMetadata` is create-only; `get(workspace_id, content_id) -> PrivateContent | None`; `list_all(workspace_id) -> tuple[PrivateContentMetadata, ...]`.
- `StorePrivateContent` receives explicit `max_content_bytes`; it validates a real workspace, exact `bytes`, literal filename/media type/origin, generates UUID/time, computes size/SHA-256 and verifies the repository returned the same metadata.

- [ ] **Step 1: Write RED model/port tests**

  Add tests that import the interfaces above and assert canonical UUIDs, frozen literal metadata, exact SHA-256/size, invalid timestamps/media/origin, exact three-method port surface and no physical path field.

- [ ] **Step 2: Run RED**

  Run: `python -m pytest tests/test_private_case_storage_v1.py -q`

  Expected: collection failure because the private-content Application contract does not exist.

- [ ] **Step 3: Implement the minimal records and port**

  Records validate exact types, timezone-aware timestamps, lowercase SHA-256 and content fidelity. Content IDs accept only canonical UUID strings; original filenames are UTF-8 metadata and never path components.

- [ ] **Step 4: Add RED service tests, then implement services**

  Use real SQLite workspaces and the filesystem adapter once available. Prove nonexistent workspace rejection, configured in-memory size ceiling, generated identity/time, repository-result identity verification, missing content, listing isolation and repository error propagation.

### Task 2: Implement atomic local private filesystem storage

**Files:**
- Create: `scripts/backend_contract/infrastructure/private_filesystem.py`
- Modify: `scripts/backend_contract/infrastructure/__init__.py`
- Modify: `tests/test_private_case_storage_v1.py`

**Interfaces:**
- Produces: `LocalPrivateContentStore(private_root)` implementing
  `PrivateContentRepository`, with `close()` and context-manager lifecycle. The
  runtime pre-provisions the absolute root, regular `.store-lock` trust anchor
  and empty regular `.commit-log`/`.commit-anchor` before adapter composition.
- Layout: um namespace plano sob `<root>` com nomes canônicos
  `<workspace_uuid>.<content_uuid>.<member>`; all caller-facing results omit this path.
- Manifest fields are exact and schema-versioned; `metadata.sha256` binds canonical manifest bytes; manifest binds content size/hash, workspace and content IDs.

- [ ] **Step 1: Add RED round-trip/reopen tests**

  Cover zero bytes, binary NUL bytes, Unicode filename/media metadata, duplicate filenames, identical bytes as distinct records, deterministic listing and close/reopen across new SQLite/filesystem store instances.

- [ ] **Step 2: Implement minimal filesystem GREEN**

  Validate the pre-provisioned configured root and both control files, acquire
  its existing trust-anchor lock without creating bytes, bind directory identity
  across acquisition, hold
  one exclusive kernel singleton, derive only flat canonical UUID names, fsync
  a physical workspace/content/nonce intent before any data mutation, then fsync
  the matching write-ahead journal entry and write workspace/content/nonce-bound
  staging files directly below the anchored root, fsync them, publish by
  no-replace hard links while retaining identity aliases, atomically publish the
  staged visibility marker, fsync the independent confirmation anchor, and keep
  the staging aliases as durable identity evidence before returning
  metadata. Analyze every journal/anchor/group/staging state before mutation,
  then recover or
  reject every known crash state on reopen without deleting evidence on a
  failed recovery.

- [ ] **Step 3: Add RED integrity/failure tests**

  Corrupt/truncate bytes, alter metadata or checksum, add unexpected entries, remove files, inject finalization failure and collide content IDs. Expect typed fail-closed repository errors, no visible partial record and no overwrite.

- [ ] **Step 4: Implement fail-closed read/cleanup GREEN**

  Require exact root inventory, grupos completos confirmados, journal coerente,
  objetos regulares não-reparse, JSON canônico, checksum exato do manifesto e
  verificação model/content. Roll back only the exact pending WAL transaction by
  adding no-replace `.retired.*` hardlinks bound to captured inode identity;
  never unlink after a separate identity check, and consume WAL only after all
  members are durably inert. Canonicalize and fsync a uniquely attributable
  torn intent before retirement, using a pre-WAL fsynced physical intent to
  recover even the first partial append. Require all four final/staging identity
  pairs for every committed record. Bind every retired inode to an exact aborted
  intent, reconcile its link count against all root-owned aliases, and re-audit
  the complete prefix after retirement before consuming WAL. Unknown valid-shaped
  names and replacements fail closed or become inert without destructive cleanup.
  Attribute short torn WAL only to an unmarked physical intent, reject a complete
  group without WAL before anchor mutation, reserve the full 18-entry abort
  footprint before the first mutation, flush every newly published hardlink
  identity on Windows, bind Windows storage to the runtime's trusted local
  volume, and detach raw descriptors before any potentially ambiguous close.
  Revalidate link counts after reads, reject reparse ancestry, close the singleton
  handle even after unlock failure, prevent inherited-process operations/unlock,
  flush rollback hardlinks, and compare ledger snapshots before truncation.

### Task 3: Prove containment, isolation and privacy

**Files:**
- Modify: `tests/test_private_case_storage_v1.py`
- Create: `docs/arquitetura/private-case-storage-v1.md`

**Interfaces:**
- Consumes the Task 1/2 public interfaces only; no browser/API surface.

- [ ] **Step 1: Add adversarial identity/path tests**

  Store literal filenames containing `..`, absolute POSIX, drive-letter, UNC and mixed separators and prove they remain metadata while physical paths stay UUID-only beneath root. Reject malformed/noncanonical content identities.

- [ ] **Step 2: Add symlink/reparse and substitution tests**

  Reject a real symlink where supported and mechanically test Windows reparse detection. Prove A cannot get/list B and copied/substituted B identity fails manifest binding.

- [ ] **Step 3: Add no-egress/no-log/no-tracked-byte checks**

  Assert the adapter imports no network client, content never enters logs, test roots are outside the checkout, and `git ls-files referencias/privadas/*` is empty.

- [ ] **Step 4: Document the bounded operational contract**

  Record runtime root configuration, UUID-only layout, atomicity/integrity limits, duplicate behavior, absence of encryption/authenticity claims, recovery behavior and explicit out-of-scope items.

### Task 4: Assure and deliver

**Files:**
- Modify only files proven necessary by Tasks 1-3.

- [ ] Run focused tests and mutation-minded adversarial checks.
- [ ] Run Application, persistence and architecture suites.
- [ ] Run changed-file Ruff, `git diff --check`, privacy scans and `python -m scripts.quality.change_impact <changed files>`.
- [ ] Run full pytest and `python -m scripts.quality.verify_core --full`.
- [ ] Commit coherent changes, push, open a PR closing #107 and referencing #13, and bind all evidence to the exact HEAD.
- [ ] Require exact-head `core-safety`, `architecture-protected`, `capability-protected`, independent PR Reviewer, Systemic Auditor, and one external diversity review because private filesystem persistence is high risk.
- [ ] Fix reproduced P0/P1 through fresh RED/GREEN cycles; invalidate stale HEAD evidence.
- [ ] Reconcile base/head/checks/reviews, merge normally with a merge commit, verify protected main, close #107 and stop.

## Self-review

- Every requirement in the milestone maps to an Application, filesystem, isolation, reopen, privacy or assurance test above.
- No migration is planned because bytes and their bounded manifest belong to the dedicated filesystem repository; SQLite remains workspace authority only.
- No physical path, arbitrary binary payload or egress capability crosses into ArtifactRevision, API or UI.
- The plan contains no placeholder implementation or later-stage document-intake work.
