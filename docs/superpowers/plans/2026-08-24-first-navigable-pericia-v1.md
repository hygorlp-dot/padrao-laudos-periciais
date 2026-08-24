# FIRST_NAVIGABLE_PERICIA_V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar a primeira vertical slice funcional em que o usuário lista, cria, abre, navega e reabre uma perícia persistida em SQLite sem expor o token da Local API ao browser.

**Architecture:** O browser usa somente rotas relativas same-origin contra um `Trusted Local Product Bridge` stdlib em `127.0.0.1`. O bridge serve o build React, valida Host/Origin/Fetch Metadata, encaminha somente list/get/create para a Local API existente e injeta o token no hop servidor→Local API; Application Services e SQLite continuam como autoridades abaixo da Local API.

**Tech Stack:** Python stdlib (`http.server`, `http.client`, `threading`), Local API/Application/SQLite existentes, React 19, TypeScript 6, Vite 8, Vitest e pytest.

## Global Constraints

- `MAIN_SHA = 24be92dab7372304b0c4e978fb498672f4f2374b` na criação da branch.
- `PRODUCT_BRAND = UNDEFINED`; `UI_DESCRIPTOR = Sistema Pericial`.
- `URL_IS_WORKSPACE_CONTEXT`; nenhuma identidade ativa em React global state, localStorage ou sessionStorage.
- `BROWSER_NEVER_SEES_LOCAL_API_TOKEN`; o token não entra em HTML, JS, DOM, storage, URL, respostas, logs, screenshots ou erros.
- Bridge e Local API escutam somente `127.0.0.1`; nenhuma CORS permissiva ou request externo.
- Zero dependência nova por padrão; não adicionar router, query framework, desktop framework, state store ou UI kit.
- Não alterar Core, semântica pericial, schema SQLite, Application Services ou contrato de segurança da Local API.
- Não iniciar Process/Case, Vistoria, Evidências, Laudo, IA, release ou installer.
- Preservar shell/design aprovado; uma ação primária por vista; sem redesign e sem motion decorativa.

---

## File Map

- Create `scripts/backend_contract/product_bridge/__init__.py`: boundary público mínimo do bridge.
- Create `scripts/backend_contract/product_bridge/transport.py`: política browser-facing, allowlist de rotas, static serving e forwarding byte-for-byte.
- Create `scripts/backend_contract/product_bridge/server.py`: listener loopback e lifecycle HTTP.
- Create `scripts/backend_contract/product_bridge/composition.py`: composition root que possui Local API, bridge e shutdown.
- Create `scripts/backend_contract/product_bridge/__main__.py`: runtime local explícito, sem token em argumentos/logs.
- Create `frontend/src/data/workspaces.ts`: `listWorkspaces`, `getWorkspace`, `createWorkspace` e validação de DTO.
- Create `frontend/src/workspaces/WorkspaceDirectory.tsx`: loading/empty/list/create/error da home.
- Create `frontend/src/workspaces/WorkspaceView.tsx`: carregamento do contexto real e placeholders vinculados.
- Modify `frontend/src/routes/routeCatalog.ts`: resolver diretório e rotas `/pericias/{id}/...`.
- Modify `frontend/src/app/router.ts`: navegação programática browser-native e foco previsível.
- Modify `frontend/src/app/App.tsx`: composição dos estados e título da rota.
- Modify `frontend/src/ui/{AppShell,Sidebar,TopBar,StatusState}.tsx`: contexto ativo, navegação contextual e estados acessíveis.
- Modify `frontend/src/styles/shell.css`: ledger/list/form/error sem cards decorativos.
- Modify `frontend/src/app/App.test.tsx`: comportamento real de home/create/open/deep-link/back-forward/not-found.
- Create `frontend/src/data/workspaces.test.ts`: DTO, erros e contrato de fetch relativo sem token.
- Create `tests/test_product_bridge_v1.py`: segurança adversarial, forwarding e lifecycle.
- Create `tests/test_first_navigable_pericia_v1.py`: E2E real bridge→Local API→Application→SQLite→reopen.
- Modify `tests/test_frontend_shell_boundaries_v1.py`: permitir somente a superfície `/app-api/v1/workspaces` e proibir token/SQL/domínio.
- Create `tests/test_first_navigable_pericia_boundaries_v1.py`: imports e capacidades exatas do bridge.

### Task 1: Characterize workspace routing and frontend data contract

**Files:**
- Modify: `frontend/src/app/App.test.tsx`
- Create: `frontend/src/data/workspaces.test.ts`
- Modify: `frontend/src/routes/routeCatalog.ts`
- Create: `frontend/src/data/workspaces.ts`

**Interfaces:**
- Produces: `Workspace`, `WorkspaceApiError`, `listWorkspaces()`, `getWorkspace(id)`, `createWorkspace(name)`, `resolveRoute(pathname)`, `workspacePath(id, stage?)`.
- Consumes: browser-native `fetch` and the fixed `/app-api/v1/workspaces` surface.

- [ ] **Step 1: Write RED routing tests**

  Add literal expectations for `/`, `/pericias/<canonical-uuid>`, `/pericias/<canonical-uuid>/vistoria`, unknown stage, malformed ID and the workspace-aware next-stage path. The production break caught is loss of workspace identity or acceptance of ambiguous routing.

- [ ] **Step 2: Write RED data tests**

  Assert real exported functions call only relative URLs, decode exact `{workspace_id,name,created_at}` DTOs, preserve caller `name`, map 404/409/503/500 to semantic errors and reject malformed/extra-field responses. Assert no `X-Local-API-Token` header is sent.

- [ ] **Step 3: Verify RED**

  Run `npm test -- src/data/workspaces.test.ts src/app/App.test.tsx`; expect missing exports/old routes to fail for the intended reasons.

- [ ] **Step 4: Implement the minimal route resolver and data module**

  Use a canonical lowercase UUID regex, literal workflow slugs and relative fetch. Send only `Content-Type: application/json` for create, use `cache: no-store`, derive no IDs/timestamps, and expose only sanitized error kinds/messages.

- [ ] **Step 5: Verify GREEN and commit**

  Run the focused Vitest command and commit `feat(product): add workspace routing and data contract`.

### Task 2: Build the fail-closed product bridge transport

**Files:**
- Create: `scripts/backend_contract/product_bridge/__init__.py`
- Create: `scripts/backend_contract/product_bridge/transport.py`
- Create: `tests/test_product_bridge_v1.py`
- Create: `tests/test_first_navigable_pericia_boundaries_v1.py`

**Interfaces:**
- Produces: `BridgeResponse`, `ProductBridge`, `ProductBridgeConfig`.
- Consumes: exact upstream address/token supplied by composition and an explicit frontend build directory.

- [ ] **Step 1: Write RED security and forwarding tests**

  Cover exact Host, external Origin, `Origin: null`, missing/wrong Origin on POST, `Sec-Fetch-Site: cross-site`, same-origin POST, no ACAO wildcard, route allowlist, body-size/content-type/duplicate-header rejection, token absence from repr/body/static files and upstream failure→sanitized 503.

- [ ] **Step 2: Write RED boundary tests**

  Parse production imports and prove the bridge has no `sqlite3`, Infrastructure, Application or Core import; only `composition.py` may import `local_api.composition`; no direct SQL text; outbound client target is constructor-pinned literal loopback.

- [ ] **Step 3: Verify RED**

  Run `python -m pytest -q tests/test_product_bridge_v1.py tests/test_first_navigable_pericia_boundaries_v1.py`; expect missing package/classes.

- [ ] **Step 4: Implement minimal transport**

  Serve only `index.html`, same-tree hashed assets and explicit SPA paths. Proxy only list/get/create, preserve upstream status/body and safe response headers, inject `X-Local-API-Token` internally, reject unknown methods/paths and never log request material.

- [ ] **Step 5: Verify GREEN and commit**

  Re-run both test files and commit `feat(product): add secure local product bridge`.

### Task 3: Compose coordinated local runtime and real SQLite reopen proof

**Files:**
- Create: `scripts/backend_contract/product_bridge/server.py`
- Create: `scripts/backend_contract/product_bridge/composition.py`
- Create: `scripts/backend_contract/product_bridge/__main__.py`
- Extend: `tests/test_product_bridge_v1.py`
- Create: `tests/test_first_navigable_pericia_v1.py`

**Interfaces:**
- Produces: `ProductRuntime`, `build_product_runtime(database, frontend_root, config=None, token=None)` and `python -m scripts.backend_contract.product_bridge`.
- Consumes: `build_local_api()` exclusively; no direct Application/SQLite access.

- [ ] **Step 1: Write RED lifecycle/E2E tests**

  Start on port 0 with an actual temporary build and database; prove empty list, create `Perícia de teste`, real UUID/timestamp, list/get, two legitimate creates without loss, deep-link returns shell, close, reopen same DB and retrieve the same workspace.

- [ ] **Step 2: Add failure tests**

  Prove non-loopback config fails before listener start, frontend root missing fails closed, partial startup closes owned resources, repeated close is safe and token never appears in `repr(ProductRuntime)`.

- [ ] **Step 3: Verify RED**

  Run `python -m pytest -q tests/test_product_bridge_v1.py tests/test_first_navigable_pericia_v1.py`; expect lifecycle symbols missing.

- [ ] **Step 4: Implement server/composition/CLI**

  Start Local API first, bind bridge on literal loopback, set exact public origin from bound port, own both lifecycles under a lock, close bridge then Local API, and print only the local product URL from CLI.

- [ ] **Step 5: Verify GREEN and commit**

  Run focused tests and commit `feat(product): compose navigable local runtime`.

### Task 4: Deliver home, create, list and active-workspace UX

**Files:**
- Create: `frontend/src/workspaces/WorkspaceDirectory.tsx`
- Create: `frontend/src/workspaces/WorkspaceView.tsx`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/ui/AppShell.tsx`
- Modify: `frontend/src/ui/Sidebar.tsx`
- Modify: `frontend/src/ui/TopBar.tsx`
- Modify: `frontend/src/ui/StatusState.tsx`
- Modify: `frontend/src/app/App.test.tsx`

**Interfaces:**
- Consumes: Task 1 data/routing functions.
- Produces: user-observable directory/create/open/deep-link/not-found behavior.

- [ ] **Step 1: Write RED user-flow tests**

  Cover loading announcement, `Nenhuma perícia cadastrada`, one `Nova perícia` primary action, inline labeled form, empty/whitespace error, API error, list semantics, create→workspace URL, open existing, active name in topbar, Vistoria active on deep-link, controlled missing workspace, and keyboard/back-forward focus behavior.

- [ ] **Step 2: Verify RED**

  Run `npm test -- src/app/App.test.tsx`; expect the old placeholder shell to fail the new behaviors.

- [ ] **Step 3: Implement minimal React flow**

  Keep async state local to directory/view components, abort stale fetches, expose retry only on operational error, disable duplicate submit, focus the main heading after navigation and never store workspace identity outside the URL.

- [ ] **Step 4: Verify GREEN and commit**

  Run focused frontend tests and commit `feat(product): add navigable pericia workflow`.

### Task 5: Extend the approved ledger visual system without redesign

**Files:**
- Modify: `frontend/src/styles/shell.css`
- Modify: `frontend/src/styles/global.css` only if an accessibility state requires it.

**Interfaces:**
- Consumes: semantic markup from Task 4 and existing DESIGN.md tokens.
- Produces: technical ledger list, inline form, active workspace context and error/loading states at 1280×800 and 1440×900.

- [ ] **Step 1: Establish the visual contract**

  Preserve graphite rail/mineral plane, Aptos hierarchy, rare ochre, flat rules and existing 140ms functional transitions. Add no new entrance animation; keyboard actions remain instant and reduced motion remains complete.

- [ ] **Step 2: Implement CSS in one bounded pass**

  Use a semantic ledger row rather than repeated cards, one primary action, associated error text, visible disabled/focus states, real-content overflow handling and no UUID prominence.

- [ ] **Step 3: Run mechanical detector once**

  Run `node .agents/skills/impeccable/scripts/detect.mjs --json frontend/src/workspaces/WorkspaceDirectory.tsx frontend/src/workspaces/WorkspaceView.tsx frontend/src/styles/shell.css`; resolve only concrete in-scope findings.

- [ ] **Step 4: Verify and commit**

  Run frontend tests, typecheck and lint; commit `feat(product): present pericias as a technical ledger`.

### Task 6: Harden boundaries, token custody and integration contracts

**Files:**
- Modify: `tests/test_frontend_shell_boundaries_v1.py`
- Extend: `tests/test_first_navigable_pericia_boundaries_v1.py`
- Extend: `tests/test_product_bridge_v1.py`

**Interfaces:**
- Consumes: complete frontend and bridge implementation.
- Produces: executable proof of no token/SQL/domain/egress bypass.

- [ ] **Step 1: Update the frontend network boundary RED**

  Replace the former total-fetch ban with an AST/source contract that permits only `frontend/src/data/workspaces.ts` and only relative `/app-api/v1/workspaces` requests. Keep token, storage, WebSocket/EventSource/sendBeacon and external URL bans.

- [ ] **Step 2: Add adversarial mutation cases**

  Cover encoded traversal, absolute-form request targets, proxy artifact routes, malformed UUID, duplicate Host/Origin/length, body mismatch and token-shaped marker scans across built frontend and HTTP responses.

- [ ] **Step 3: Verify RED then GREEN**

  Run the three boundary/security test files before and after minimal hardening; document the exact root cause for each discovered failure rather than patching symptoms.

- [ ] **Step 4: Commit**

  Commit `test(product): harden local bridge boundaries`.

### Task 7: Terminal local assurance and draft PR

**Files:**
- Modify: `docs/superpowers/plans/2026-08-24-first-navigable-pericia-v1.md` only to check completed steps/evidence if useful.

**Interfaces:**
- Produces: exact terminal HEAD, draft PR and evidence package.

- [ ] **Step 1: Run focused and real E2E tests**

  Run frontend tests, bridge/security tests, E2E create/list/open/reopen, boundary tests, typecheck, ESLint, build and `npm audit`.

- [ ] **Step 2: Run repository safety**

  Run `change_impact`, indicated focused tests, changed-file Ruff, repository safety, privacy scan, `git diff --check`, full pytest and `python -m scripts.quality.verify_core --full`.

- [ ] **Step 3: Reconcile and push**

  Confirm clean branch ancestry from current `origin/main`, commit remaining coherent evidence, push without force and open draft PR `feat(product): add first navigable pericia` with `Closes #103`.

- [ ] **Step 4: Wait exact-head CI**

  Require required checks green on the exact HEAD. Any code change invalidates affected evidence.

### Task 8: Visual assurance, independent review, merge and post-main STOP

**Files:**
- No production file expected unless a reproduced P0/P1/visual defect requires TDD repair.

**Interfaces:**
- Produces: terminal review artifacts, protected merge and post-main evidence.

- [ ] **Step 1: Visual assurance**

  Run the real product runtime and inspect 1280×800/1440×900: empty, list, create, active workspace, Processo placeholder, missing workspace and API error; verify keyboard/focus/back-forward/refresh/deep-link. Never infer PASS without browser evidence.

- [ ] **Step 2: Independent reviews**

  On stable exact HEAD, dispatch isolated read-only PR Reviewer for UX/routing/data/accessibility and Systemic Auditor for token custody/Origin/Fetch Metadata/loopback/CSRF/egress/SQL/API bypass/lifecycle. Fix P0/P1 with RED and rerun affected evidence.

- [ ] **Step 3: External diversity once**

  After first-party P0/P1=0, sanitize BASE..HEAD and execute exactly one authorized external diversity attempt; no retry loop and no private data.

- [ ] **Step 4: Merge normally**

  Reconcile exact base/head, mergeability, required checks, reviews, `P0=0`, `P1=0` and visual PASS. Merge with merge commit only; no squash, rebase, force or bypass.

- [ ] **Step 5: Post-main verification and STOP**

  In a clean checkout run frontend smoke, product bridge smoke, real create/list/open/reopen, full regression, `verify_core --full` and protected main CI. Confirm Issue #103 closed/completed, declare `FIRST_NAVIGABLE_PERICIA_V1 = COMPLETE` and do not start `PROCESS_CASE_V1`.

## Self-Review

- Spec coverage: routing, bridge, token custody, Origin/Fetch Metadata, runtime lifecycle, narrow data module, all UX states, E2E/reopen, boundaries, visual assurance, reviews, merge and absolute STOP are mapped.
- Placeholder scan: no implementation step delegates unspecified error handling or testing; each behavior and command is named.
- Type consistency: `Workspace`, `WorkspaceApiError`, `resolveRoute`, `workspacePath`, `ProductBridge`, `ProductRuntime` and `build_product_runtime` are defined once and consumed consistently.
- Scope check: all tasks contribute directly to one testable vertical slice; no preparatory PR or independent subsystem is introduced.
