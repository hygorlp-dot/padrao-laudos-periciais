# PROCESS_CASE_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o perito registre, corrija, salve e reabra os dados processuais básicos de uma perícia real no seu `PericiaWorkspace`.

**Architecture:** A feature reutiliza `ArtifactRevisionRepository` como registro append-only de um único artefato processual por workspace (`PROCESS_CASE`/`PROCESS_CASE`), pois essa semântica já representa corretamente estado corrigível com histórico e integridade. Dois Application Services específicos compõem o workspace port e o revision port; Local API e product bridge expõem somente GET/POST exatos, e uma tela React local mantém o estado de edição sem lógica de domínio material.

**Tech Stack:** Python 3 stdlib, Application ports/services existentes, SQLite revision store existente, Local API e product bridge existentes, React 19, TypeScript 6, Vitest, pytest e Playwright MCP apenas para assurance manual.

## Global Constraints

- `BASE_SHA = d111595879c67018786a1e9ba5c66d71597d5d5b` na criação da branch.
- Issue `#105`; branch `feat/105-process-case-v1`.
- Sem migration ou tabela nova: correções são revisões append-only do artefato processual fixo.
- Campos V1 exatos: `numero_processo`, `tribunal`, `vara`, `comarca_municipio`, `uf`, `parte_requerente`, `parte_requerida`.
- Nenhum campo é obrigatório; valores textuais são preservados sem trim, upper-case ou normalização destrutiva.
- Uma única ação primária na página: `Salvar dados do processo`; sem autosave.
- Nenhum UUID como conteúdo principal; nenhum dado processual em URL, query string, storage do browser ou logs.
- Browser nunca recebe `X-Local-API-Token`; bridge permanece same-origin, loopback, allowlist exato e sem CORS.
- `/app-api`, `/assets` e SPA fallback permanecem fail-closed.
- Sem dependência nova, framework CRUD, command/event bus, router, state store, UI kit, branding ou motion ornamental.
- Outras etapas do shell permanecem placeholders existentes.

---

## File Map

- Modify `scripts/backend_contract/application/models.py`: `ProcessCaseData` e `ProcessCaseSnapshot` imutáveis.
- Modify `scripts/backend_contract/application/services.py`: `GetProcessCase` e `SaveProcessCase`, usando os ports existentes.
- Modify `scripts/backend_contract/application/__init__.py`: exports explícitos da nova capability.
- Modify `scripts/backend_contract/local_api/transport.py`: DTO e rota exata `/v1/workspaces/{id}/process-case`.
- Modify `scripts/backend_contract/local_api/composition.py`: composição dos dois novos services.
- Modify `scripts/backend_contract/product_bridge/transport.py`: allowlist exato `/app-api/v1/workspaces/{id}/process-case`.
- Create `frontend/src/data/processCase.ts`: boundary browser-facing e validação exata de DTO.
- Create `frontend/src/data/processCase.test.ts`: contrato do fetch relativo, fidelity e erros sanitizados.
- Create `frontend/src/workspaces/ProcessCaseView.tsx`: loading/form/save/success/error da etapa Processo.
- Create `frontend/src/workspaces/ProcessCaseView.test.tsx`: fluxo e acessibilidade do formulário.
- Modify `frontend/src/workspaces/WorkspaceView.tsx`: renderiza o formulário somente na rota Processo.
- Modify `frontend/src/routes/routeCatalog.ts`: descrição real da etapa Processo.
- Modify `frontend/src/styles/shell.css`: formulário técnico simples, responsivo e sem card soup.
- Create `tests/test_process_case_v1.py`: Application + persistência + reopen + Local API + E2E real.
- Modify `tests/test_product_bridge_v1.py`: proxy/Origin/cross-site/token/namespaces.
- Modify `tests/test_first_navigable_pericia_boundaries_v1.py`: autoriza a nova data boundary frontend sem permitir domínio no bridge.

### Task 1: Fix the application contract with RED tests

**Files:**
- Create: `tests/test_process_case_v1.py`
- Modify: `scripts/backend_contract/application/models.py`
- Modify: `scripts/backend_contract/application/services.py`
- Modify: `scripts/backend_contract/application/__init__.py`

**Interfaces:**
- Produces: `ProcessCaseData`, `ProcessCaseSnapshot`, `GetProcessCase.execute(workspace_id)`, `SaveProcessCase.execute(workspace_id, data, expected_revision)`.
- Consumes: `WorkspaceRepository`, `ArtifactRevisionRepository`, `Clock`, `IdGenerator`.

- [ ] **Step 1: Write literal RED tests for empty/get/save/correction/isolation**

  Test that an existing workspace with no revision returns a snapshot with `revision=None`, `updated_at=None` and all seven fields as empty strings. Save literal Unicode/spacing values, read them unchanged, save a correction as revision 2, prove the prior revision remains, prove A/B isolation, and require `WorkspaceNotFound` for a missing workspace.

- [ ] **Step 2: Verify the RED**

  Run `python -m pytest -q tests/test_process_case_v1.py -k 'application'`; expect import failures for the absent model/services.

- [ ] **Step 3: Implement the smallest model/services**

  `ProcessCaseData.from_mapping()` requires the exact seven keys and string values, validates UTF-8 compatibility and preserves content byte-for-byte. `GetProcessCase` checks workspace existence, reads the latest fixed artifact, and returns empty state when absent. `SaveProcessCase` checks workspace existence and appends only when `expected_revision` still matches atomically; the generic artifact writer rejects the reserved process-case identity.

- [ ] **Step 4: Verify GREEN**

  Re-run the application subset and the existing `tests/test_application_services_v1.py`.

### Task 2: Prove real SQLite correction and reopen semantics

**Files:**
- Extend: `tests/test_process_case_v1.py`
- Production: reuse `scripts/backend_contract/infrastructure/sqlite.py`, adding only the atomic expected-revision append proven necessary by the stale-client RED.

**Interfaces:**
- Consumes: `SQLiteApplicationStore`, `GetProcessCase`, `SaveProcessCase`.
- Produces: real database evidence for revision 1, revision 2, latest state, reopen and A/B isolation.

- [ ] **Step 1: Write persistence RED tests**

  Create workspaces A/B in a file-backed store, save different literal data, correct A, close, reopen, and assert A latest is revision 2, B latest is revision 1, both payloads remain isolated, and A revision 1 is still readable.

- [ ] **Step 2: Verify RED before composition exists**

  Run `python -m pytest -q tests/test_process_case_v1.py -k 'sqlite or reopen or isolation'` and confirm failure is the missing process services.

- [ ] **Step 3: Reach GREEN without schema expansion**

  Use the existing append-only repository; do not add SQL, tables or migrations unless the test mechanically proves the existing semantics incompatible.

- [ ] **Step 4: Verify GREEN**

  Run the persistence subset plus `tests/test_local_persistence_v1.py`.

### Task 3: Add the minimal Local API contract

**Files:**
- Extend: `tests/test_process_case_v1.py`
- Modify: `scripts/backend_contract/local_api/transport.py`
- Modify: `scripts/backend_contract/local_api/composition.py`

**Interfaces:**
- Produces: GET/POST `/v1/workspaces/{canonical_uuid}/process-case`.
- Response: exact `{workspace_id,revision,updated_at,data}`; POST body exact `{expected_revision:int|null,data:{seven fields}}`.

- [ ] **Step 1: Write transport RED tests**

  Cover valid GET, valid POST, stale-revision conflict 409, response/workspace identity binding, missing workspace, malformed/extra/missing body, wrong content type/length, missing token, deterministic DTO, unsupported method, canonical path and sanitized repository failures.

- [ ] **Step 2: Verify RED**

  Run `python -m pytest -q tests/test_process_case_v1.py -k 'local_api'`; expect the new route to return 404.

- [ ] **Step 3: Implement exact routing and composition**

  Add two fields to `LocalApiServices`, compose the two services from existing repositories, recognize only the exact raw route, reuse POST authentication/body parsing, and map the immutable snapshot to JSON without exposing revision history.

- [ ] **Step 4: Verify GREEN**

  Run the Local API subset and all `tests/test_local_api_v1.py`.

### Task 4: Extend only the product bridge allowlist

**Files:**
- Modify: `tests/test_product_bridge_v1.py`
- Modify: `tests/test_first_navigable_pericia_boundaries_v1.py`
- Modify: `scripts/backend_contract/product_bridge/transport.py`

**Interfaces:**
- Produces: GET/POST `/app-api/v1/workspaces/{canonical_uuid}/process-case` forwarded to the exact Local API route.

- [ ] **Step 1: Write bridge RED tests**

  Assert exact forwarding, no browser token, required same-origin Origin and `Sec-Fetch-Site` for POST, external/cross-site rejection, malformed UUID rejection, sibling route rejection, `/app-api` root JSON reservation, missing assets JSON 404 and unknown safe GET SPA fallback.

- [ ] **Step 2: Verify RED**

  Run `python -m pytest -q tests/test_product_bridge_v1.py tests/test_first_navigable_pericia_boundaries_v1.py`; expect the exact process route to remain closed.

- [ ] **Step 3: Implement one exact route family**

  Extend `_proxy_target()` only for canonical workspace ID plus terminal `process-case`, with GET/POST only. Do not add wildcard forwarding or domain parsing to the bridge.

- [ ] **Step 4: Verify GREEN**

  Re-run both files and the existing first navigable E2E tests.

### Task 5: Prove the real end-to-end path and restart

**Files:**
- Extend: `tests/test_process_case_v1.py`

**Interfaces:**
- Consumes: real `ProductRuntime`, Local API listener, Application Services and file-backed SQLite.
- Produces: terminal no-mock proof A/B → close → reopen → A/B.

- [ ] **Step 1: Write the real E2E RED**

  Start a product runtime with temporary frontend build/database, create A/B through the bridge, GET empty A, POST literal A/B data through browser-facing endpoints, correct A, close runtime, reopen the same database, and GET exact latest values for both workspaces.

- [ ] **Step 2: Verify RED**

  Run `python -m pytest -q tests/test_process_case_v1.py -k 'real_vertical_slice'`; expect process-case proxy/route absence.

- [ ] **Step 3: Reach GREEN through the production path**

  Use no mocks, no direct SQLite access in the assertion path and no token in browser-facing requests.

- [ ] **Step 4: Verify GREEN**

  Run all `tests/test_process_case_v1.py` and the prior first navigable suite.

### Task 6: Add the browser data boundary with RED tests

**Files:**
- Create: `frontend/src/data/processCase.test.ts`
- Create: `frontend/src/data/processCase.ts`
- Modify: `tests/test_first_navigable_pericia_boundaries_v1.py`

**Interfaces:**
- Produces: `ProcessCaseData`, `ProcessCaseSnapshot`, `getProcessCase(workspaceId, signal?)`, `saveProcessCase(workspaceId, data, signal?)`.
- Consumes: only the relative `/app-api/v1/workspaces/{id}/process-case` route.

- [ ] **Step 1: Write data-boundary RED tests**

  Assert canonical workspace ID, exact response keys/types, fidelity of leading/trailing spaces and accents, full seven-field POST, no token/storage/external URL, status mapping and rejection of malformed/expanded responses.

- [ ] **Step 2: Verify RED**

  Run `npm.cmd test -- src/data/processCase.test.ts`; expect missing module/exports.

- [ ] **Step 3: Implement the minimal fetch boundary**

  Reuse the workspace error vocabulary where appropriate, use relative fetch with `credentials: same-origin` and `cache: no-store`, and never normalize field values.

- [ ] **Step 4: Verify GREEN**

  Re-run data tests and existing workspace data tests.

### Task 7: Deliver the real Processo form

**Files:**
- Create: `frontend/src/workspaces/ProcessCaseView.test.tsx`
- Create: `frontend/src/workspaces/ProcessCaseView.tsx`
- Modify: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/routes/routeCatalog.ts`
- Modify: `frontend/src/styles/shell.css`

**Interfaces:**
- Consumes: `getProcessCase()` and `saveProcessCase()`.
- Produces: controlled loading/empty/edit/save/success/error/reload behavior with one primary action.

- [ ] **Step 1: Write component RED tests**

  Cover loading status; seven labeled fields; initial empty state; exact field hydration; editing; one primary `Salvar dados do processo`; disabled/saving state; discreet success; sanitized retryable load error; save error preserving edits; workspace ID change isolation; abort on unmount; and keyboard focus after save/error.

- [ ] **Step 2: Verify RED**

  Run `npm.cmd test -- src/workspaces/ProcessCaseView.test.tsx`; expect the component to be absent.

- [ ] **Step 3: Implement the minimal React flow**

  Keep local state, abort stale requests, preserve unsaved user input on save failure, use semantic form/fieldset-free groupings, no modal/autosave, and no new motion. In `WorkspaceView`, replace only the Processo placeholder and suppress the next-stage primary link on that route.

- [ ] **Step 4: Add bounded CSS**

  Use a quiet two-column form grid at wide viewports and one column on constrained space, existing tokens, visible focus and no card soup; preserve reduced-motion behavior and avoid new animation.

- [ ] **Step 5: Verify GREEN**

  Run focused component/App tests, typecheck, ESLint and build.

### Task 8: Adversarial, repository-safety and terminal assurance

**Files:**
- Modify only tests if a real uncovered boundary requires an additional RED; no polish commits.

**Interfaces:**
- Produces: stable exact HEAD and evidence package.

- [ ] **Step 1: Run focused suites**

  Run process-case, Local API, bridge, persistence, first-navigable, boundary and frontend suites.

- [ ] **Step 2: Run repository safety**

  Run `python -m scripts.quality.change_impact <changed files>`, indicated tests, changed-file Ruff, privacy/egress scans, `git diff --check`, full pytest and `python -m scripts.quality.verify_core --full`.

- [ ] **Step 3: Push exact HEAD and wait CI**

  Require `core-safety`, `architecture-protected` and `capability-protected` on the exact HEAD. Global inherited Ruff remains informational only if changed files pass.

- [ ] **Step 4: Run terminal reviews once**

  Fresh isolated PR Reviewer and Systemic Auditor inspect exact BASE/HEAD, workspace isolation, correction/reopen semantics, API/bridge/token/privacy boundaries and absence of speculative architecture. After P0/P1=0, attempt external diversity exactly once; TOOL_FAILURE is recorded without retry and may use at most one isolated replacement auditor under the current contract.

### Task 9: Real visual assurance, freeze, merge and post-main STOP

**Files:**
- No code change after freeze unless a reproduced P0/P1 material requires TDD repair.

**Interfaces:**
- Produces: protected merge, post-main evidence and `PROCESS_CASE_V1 = COMPLETE`.

- [ ] **Step 1: Run Playwright visual assurance**

  On exact HEAD validate 1280x800 and 1440x900: HOME_READY, OPEN_PERICIA, PROCESSO_EMPTY/EDIT/SAVE/SAVED/REFRESH/DEEP_LINK/REOPEN/WORKSPACE_ISOLATION, Back/Forward, title focus, Tab/Shift+Tab, visible focus, invalid workspace/route, overflow/clipping, neutral branding, no raw JSON/stack/white screen/token/egress.

- [ ] **Step 2: Freeze and update PR**

  With all terminal evidence green, declare `CODE_FREEZE = TRUE`, update PR body with BASE/HEAD/capability/tests/CI/reviews/visual/privacy and mark ready.

- [ ] **Step 3: Reconcile and merge normally**

  Freshly require exact main, merge-base, behind=0, HEAD, clean worktree, mergeability and only protected checks authoritative. Merge with merge commit; never squash, rebase, force or bypass.

- [ ] **Step 4: Verify post-main and stop**

  Fast-forward a clean main checkout, run full Python regression, frontend tests/typecheck/lint/build, `verify_core --full`, confirm protected main green, clean worktree and Issue #105 closed. Declare `PROCESS_CASE_V1 = COMPLETE` and `STOP = TRUE`; do not create the next Issue/branch.

## Self-Review

- Spec coverage: all ten user actions, seven authorized fields, append-only correction, reopen, isolation, Local API/bridge security, frontend states, real E2E, visual assurance, reviews and absolute STOP have explicit tasks.
- Placeholder scan: every implementation step names exact files, interfaces, failing behavior and verification command; no future feature or generic error-handling placeholder remains.
- Type consistency: Python and TypeScript both use the same seven field names and `{workspace_id,revision,updated_at,data}` envelope.
- Scope check: no migration, architecture refactor, new dependency, autosave, structured Party model, later workflow stage or branding is introduced.
