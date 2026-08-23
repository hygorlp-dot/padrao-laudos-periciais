# Frontend Shell V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a professional, desktop-first React shell with predictable workflow routing and no domain or Local API integration.

**Architecture:** A self-contained `frontend/` Vite application owns presentation and navigation state only. A small browser-history router maps canonical paths to static route descriptors; `AppShell` composes semantic navigation, context header and page content, while reusable status components render loading, empty, error and ready presentation states.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, ESLint and plain CSS.

## Global Constraints

- Base SHA: `19d0117961f9e60480dfec7d42440670008bc26f`.
- `FRONTEND_SHELL_V1 != FIRST_NAVIGABLE_PERICIA_V1`.
- `DOMAIN_LOGIC_STAYS_BELOW_UI`; no Core, Application, Infrastructure, SQLite or Local API imports.
- `LOCAL_API_SECURITY_UNCHANGED = TRUE`; no token, fetch, XHR, WebSocket or automatic network request.
- No external fonts, CDN assets, analytics, telemetry, state manager, UI kit, Tailwind, desktop host or service worker.
- Desktop-first verification at 1280x800 and 1440x900; mobile/release work remains out of scope.
- Motion is limited to short functional hover/focus feedback and disabled under `prefers-reduced-motion`.
- Terminal boundary: merge, post-main green, then STOP before `FIRST_NAVIGABLE_PERICIA_V1`.

## Design direction

- **Mode:** Operate — a frequent-use technical workspace.
- **Subject:** a digital forensic engineering dossier used under neutral office light.
- **Palette:** Mineral `#F2F4F1`, Paper `#FCFDFB`, Graphite `#18201D`, Slate `#5C655F`, Rule `#D6DCD7`, Inspection ochre `#7B570D`.
- **Typography:** `Aptos Display` for restrained headings, `Aptos` for interface text, and `Cascadia Mono` only for route/status metadata; all use system fallbacks and no downloads.
- **Layout:** a fixed workflow rail, compact context bar and one continuous content plane rather than a grid of cards.
- **Signature:** the sidebar is a calibrated process ledger — one vertical rule connects exact stage indexes, and the active stage becomes a solid index tab without decorative motion.
- **Primary action:** on the empty home, `Conhecer o fluxo` navigates to Processo; route pages expose only one `Avancar para ...` navigation action when a next stage exists.
- **Motion weighting:** Emil primary, Jakub secondary; keyboard navigation is instant, pointer hover uses a 140ms custom curve, and reduced motion removes transitions.

```text
+----------------------+-----------------------------------------------+
| Sistema Pericial     | Contexto: nenhuma pericia selecionada        |
| 00 Inicio            +-----------------------------------------------+
| 01 Processo          |                                               |
| 02 Analise           |  Processo                                     |
| ... vertical rail    |  Estrutura pronta para receber este fluxo.   |
| 10 Exportar          |                                               |
|                      |  [ Avancar para Analise ]                     |
+----------------------+-----------------------------------------------+
```

---

### Task 1: Establish the isolated frontend toolchain

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/package-lock.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/eslint.config.js`
- Create: `frontend/index.html`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Node 24 and npm.
- Produces: `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`, and Vite development/preview servers.

- [ ] **Step 1: Add the minimal package manifest** with React/Vite runtime and Vitest/Testing Library/ESLint development dependencies; do not add routing, state, icon or CSS frameworks.
- [ ] **Step 2: Add strict TypeScript, Vite and ESLint configuration** scoped to `frontend/` and a jsdom test environment.
- [ ] **Step 3: Add `index.html`** with Portuguese language, viewport metadata, local-only CSP, root mount and the auditable design-direction comment as the first body child.
- [ ] **Step 4: Install dependencies with `npm.cmd install`** to produce the exact lockfile and confirm `npm.cmd run typecheck` fails only because application files do not yet exist.

### Task 2: Specify routing and shell behavior with RED tests

**Files:**
- Create: `frontend/src/app/App.test.tsx`
- Create: `frontend/src/test/setup.ts`
- Create: `tests/test_frontend_shell_boundaries_v1.py`

**Interfaces:**
- Consumes: Testing Library and Vitest.
- Produces: behavioral contracts for `App`, `navigate`, canonical routes, navigation semantics and frontend source boundaries.

- [ ] **Step 1: Write RED route tests** asserting all eleven canonical paths render their exact heading and unknown paths render the controlled `Pagina nao encontrada` fallback.
- [ ] **Step 2: Write RED navigation tests** asserting active links expose `aria-current="page"`, Tab reaches real links, Enter updates `window.location.pathname`, and `popstate` restores the selected route.
- [ ] **Step 3: Write RED state tests** for `loading`, `empty`, `error` and `ready`, including accessible status semantics and actionable copy without internal details.
- [ ] **Step 4: Write the Python boundary RED** that recursively rejects imports/references to Core, Python Infrastructure, SQLite and Local API internals; rejects secrets/token literals and browser network primitives in production frontend source.
- [ ] **Step 5: Run `npm.cmd test` and the Python boundary test** and confirm failure is caused by the missing shell implementation.

### Task 3: Implement the navigable application shell

**Files:**
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/src/app/router.ts`
- Create: `frontend/src/routes/routeCatalog.ts`
- Create: `frontend/src/ui/AppShell.tsx`
- Create: `frontend/src/ui/Sidebar.tsx`
- Create: `frontend/src/ui/TopBar.tsx`
- Create: `frontend/src/ui/PageHeader.tsx`
- Create: `frontend/src/ui/StatusState.tsx`

**Interfaces:**
- Consumes: `window.location`, `history.pushState`, `popstate`, and a fixed route catalog.
- Produces: `App`, `useCurrentPath`, `navigate`, `WORKFLOW_ROUTES`, `AppShell` and `StatusState`.

- [ ] **Step 1: Implement the minimal browser-history router** with canonical pathname matching, popstate subscription and same-origin in-app link navigation; no remote I/O.
- [ ] **Step 2: Implement the fixed route catalog** for Inicio, Processo, Analise, Planejamento, Vistoria, Evidencias, Constatacoes, Analise Tecnica, Laudo, Revisao and Exportar using only presentation copy.
- [ ] **Step 3: Compose semantic landmarks** with skip link, `aside`, labeled `nav`, `header`, `main`, real anchors and `aria-current`.
- [ ] **Step 4: Implement the four presentation states** as a small discriminated prop contract; error copy remains sanitized and no state executes domain behavior.
- [ ] **Step 5: Run frontend and Python boundary tests** until all behavioral contracts are GREEN.

### Task 4: Build the committed visual world

**Files:**
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/global.css`
- Create: `frontend/src/styles/shell.css`

**Interfaces:**
- Consumes: semantic class names from Task 3.
- Produces: the calibrated process ledger, context bar, content plane, focus/hover states and desktop responsive behavior.

- [ ] **Step 1: Define the six-color token palette, type roles, spacing and one 140ms custom easing** without gradients, glass, remote fonts or ornamental shadows.
- [ ] **Step 2: Style the workflow rail and active index tab** so stage order is readable without relying on color; keep labels visible at both target desktop widths.
- [ ] **Step 3: Style content and status states** as one continuous technical document surface with a single primary action and no dashboard/card grid.
- [ ] **Step 4: Add visible focus, selection, scrollbar and reduced-motion rules**, then run frontend tests, typecheck, lint and build.

### Task 5: Verify visually and close the delivery

**Files:**
- Create: `.impeccable/review/desktop-1280x800.png`
- Create: `.impeccable/review/desktop-1440x900.png`
- Create: `DESIGN.md`
- Create: `.impeccable/design.json`
- Update: `docs/superpowers/plans/2026-08-23-frontend-shell-v1.md`

**Interfaces:**
- Consumes: production build and Vite preview.
- Produces: visual evidence, durable design record, review evidence, PR and post-main verification.

- [ ] **Step 1: Capture one batched visual pass** at 1280x800 and 1440x900; inspect overflow, sidebar, hierarchy, focus, empty state and every route.
- [ ] **Step 2: Apply at most one batched material visual-fix pass**, rebuild and capture one confirmation pass; stop cosmetic hunting after this ceiling.
- [ ] **Step 3: Run the Impeccable detector once** over changed frontend targets, fix mechanical findings only, and send screenshots plus the direction contract to a fresh finish reviewer.
- [ ] **Step 4: Record the shipped visual system in `DESIGN.md`** after the final render, then run frontend tests, typecheck, lint, build, Python boundary tests, change-impact tests, repository safety, `verify_core --full`, privacy and `git diff --check`.
- [ ] **Step 5: Commit and push selectively**, open a draft PR `feat(frontend): add pericial application shell` with `Closes #101`, wait for exact-head protected CI and request one independent proportional review.
- [ ] **Step 6: Reconcile base/head/mergeability**, merge normally after P0=0/P1=0, validate the exact merged main with frontend smoke/build and protected CI, confirm Issue #101 closed, declare `FRONTEND_SHELL_V1 = COMPLETE`, then STOP.

## Self-review

- Spec coverage: shell, workflow routing, visual states, accessibility, no-network/no-secret boundaries, build, visual verification, proportional review, merge, post-main and STOP are each assigned.
- Placeholder scan: no TODO/TBD or unspecified implementation step remains.
- Type consistency: the fixed route catalog feeds both router and sidebar; navigation owns only browser presentation state; status rendering is independent of route/domain behavior.
- Scope control: there is no Local API integration, case workflow, domain model, persistence, desktop host, release or mobile work.
