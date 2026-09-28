# Final product convergence implementation plan

> **For agentic workers:** use the repository's executing-plans skill task by task. The user's handoff approves this sequence; no additional approval ceremony is required for ordinary implementation.

**Goal:** prepare the HF report authoring candidate for the expert's Windows Human RC, preserving every merged phase and reducing repeated entry.

**Architecture:** keep one writable owner per fact and capture its revision in the report. Present effective technical findings independently of PAT. Evolve professional presentation without changing the fourteen-section domain model or protected Word execution.

**Tech stack:** Python domain/application, local persistence/API, React/TypeScript, protected Word 16 conversion and PDF fidelity.

## Global constraints

- Reconciled baseline: `3070fec887c05fb97b6a83882d34df254efdc27b`; PRs 240–245 and 247 are already merged.
- No private egress, no case-derived fixtures, no duplicate authority, no automatic PAT approval.
- Word is authoritative; PDF is derived; original photos are immutable.
- Do not change `office_word_worker.py`, `office_pdf.py`, contained COM authority or trust infrastructure for layout.
- Keep #192 outside this work; report verify_core semantic checks, timing and exit code separately.
- Independent PR reviewer and systemic auditor on each material exact candidate SHA. No extra review rounds absent demonstrated material defects.
- No Human RC PASS claim; #238 is the real expert's subsequent validation.

## Preparation — mandatory field audit

- [x] Reconcile current GitHub main and existing phases/issues.
- [x] Record the authorized #246 decision on GitHub.
- [x] Inventory every user-entered field, dynamic field definition and writable owner before adding features. See the adjacent entry-field audit (180 patterns; no runtime productivity claim).
- [x] Verify each remaining P2 against the current source and focused UI behavior. External read-only audit: `C:/tmp/plp-246-p2-audit.md`.

## PR A — #246 summary reachability and reproduced UX

**Files:** `scripts/backend_contract/application/report_foundation.py`, `scripts/backend_contract/report_foundation.py`, `scripts/backend_contract/delivery_renderer.py`, `frontend/src/workspaces/ReportFoundationView.tsx`, their focused tests, and only UI files identified by reproduced P2 evidence.

**Interface:** keep `SET_FINDINGS_TABLE` with empty values. Read the report's bound `TechnicalSnapshot`; compare workspace, snapshot identity, revision, digest and stale state. Select only findings backed by the latest APPROVE/MODIFY decision for their proposal. Capture finding provenance at that technical revision. Retain legacy PATHOLOGY rows for exact deserialization; new rows use technical authority. Scope and proposition are displayed as scope and technical finding, without inventing environment/classification. New report versions rebuild the table from current effective authority.

- [ ] RED: current effective findings with no PAT must produce rows; proposal-only and rejected/superseded decisions must not. Cross-workspace, stale content/revision and stale upstream must reject without save.
- [ ] RED: canonical save rejects forged row content; upstream changes make the existing report stale; next version recaptures valid current rows.
- [ ] RED UI: a draft without pathology shows the summary action and submits no user-entered source IDs.
- [ ] Implement minimum domain/application/presentation changes and preserve legacy mapping.
- [ ] Repair only reproduced high-value P2; use existing field/grid and human-label conventions, no new animation.
- [ ] Run focused tests, affected frontend suites, TypeScript, ESLint, build, affected report/default-template/delivery checks; real Word proof only once at the layout candidate freeze.
- [ ] Freeze, record verification, independent exact-SHA reviews, publish PR and follow ordinary CI/merge without bypass.

## PR B — ownership and process proposals

Starts only after PR A has a stable causal result. Use the field audit to implement a canonical property record and source-grounded proposals. Existing ProcessCase remains owner of its ten reviewed process fields. Property owner is distinct from claimant; coordinates remain SITE_LOCATION-owned. Audit profile reuse before adding persistence. Capture document/page/excerpt/method and confirmation status; never silently replace a confirmed value. Unit and integration tests exercise cross-case isolation, proposal/confirmed precedence and report staleness.

## PR C — reusable inspection and case automation

Starts only after PR B is stable. Add genuinely absent inspection header fields and confirmed attendants. Reuse expert/property/location. Extend exact question proposals and document inventory through existing extraction/review paths. Preserve original question origin/number/text/page. Distinguish not found in ingested material from professionally confirmed absent. Reusable methods/instruments/references must fit existing local authority; broad new persistence is deferred.

## PR D — HF professional presentation

Starts only after PR C is stable. Inspect the seven user-authorized PDFs locally for shared visual grammar only; never commit their text, images, personal facts or derived fixtures. Build `HF_CONSTRUCTION_DEFECT_REPORT_STYLE_V1`: first page, real index, synthesis, grey chapter bars, compact tables, manifestation cards, questions, optional budget and closing, all bound to canonical owners. Keep source facts and technical decisions distinct from presentation. Test versioned identity/profile capture, computed numbering and building age from source dates. Generate synthetic real Word/PDF and inspect page breaks, headings, captions, tables and signatures against the reference family. No protected Word capability expansion.

## PR E — final short proof and reconciliation

Starts only after PR D is stable. Run the synthetic normal-flow proof, relevant regressions, architecture, capability routing and backup/isolated recovery/reopen. Measure actual input/repetition/internal-ID/screen-switch counts, without invented productivity percentages. Update #239/#246/#238/#124 only for verified changes. Report all handoff status fields and leave Human RC to the expert.
