# Product

<!-- impeccable:product-schema 1 -->

> Status: CURRENT AUTHORITY for the implemented product. Sources are the live
> route catalog, workspaces, data clients, Local API/Application Layer and
> accepted ADRs. Candidate SHAs, CI results and Human RC rounds belong to
> `config/product-maturity-v1.json`, the roadmap and Human RC issues.
> No future UX increment or real case evidence is represented as implemented.

## Platform

web

## Stack

Local desktop/browser application: React, TypeScript and Vite with plain CSS
and browser-native navigation; Python modular monolith with Domain,
Application, Infrastructure, Local API (`/app-api`) and Product Bridge layers.
The protected forensic Core remains below those layers. Case revisions persist
in local SQLite; installation settings use a separate local store. Private
source, media, templates and final artifacts stay in a local private root.

The composition root is `scripts/planejamento_pericial/app_composition.py`.
The product listens on `127.0.0.1` and serves a built frontend. Word artifacts
are produced locally; derived PDF conversion requires Microsoft Word 16 on
Windows. There is no distributed installer.

## Users

A court-appointed engineering expert (perito judicial) preparing, reviewing
and delivering technical work. Long desktop sessions require traceable values,
predictable navigation and explicit professional decisions.

## Product Purpose

Professional local software for judicial engineering expert work, initially
covering construction defects and pathological manifestations in buildings.
It connects case sources, analysis, planning, inspection, technical findings,
report, Word delivery, financially separate fee budget and recoverable backup.
The expert owns criteria, technical conclusions and approval.

## Positioning

The interface follows forensic work rather than technical modules or AI
features. A source value or proposal is never effective professional authority
by itself. The functional descriptor is “Sistema Pericial”; no commercial
brand, logo, sigla or tagline has been authorized.

## Operating Context

`frontend/src/routes/routeCatalog.ts` defines the implemented navigation.
Within a case, the prefix is `/pericias/<workspace-id>`; `/` in the table below
means the case root. Global Perícias, Configurações and Recuperação are outside
that prefix.

| Route | Implemented surface |
|---|---|
| Global `/` | open an existing local workspace or create one |
| Case `/` | current workflow projection, stages needing attention and next available action; unavailable status stays explicit |
| `/processo` | process identification, plural participants and representatives, source-bound process-number suggestions and layered property proposals; the expert confirms effective values |
| `/materiais` | local PDF/PJe ingestion, processing state and retry; exclusion/re-enable of PJe pieces |
| `/analise` | case analysis of parties, allegations, quesitos and documents, with provenance and review |
| `/planejamento` | object, material questions and field plan; explicit succession when upstream authority changes |
| `/vistoria` | observations, measurements, photos, statements and local field/mobile package; successor inspection with record-by-record reuse |
| `/evidencias` | evidence review, methods and decisions on technical proposals |
| `/constatacoes` | effective findings with evidence, method and decision |
| `/analise-tecnica` | construction-defect/PAT analysis and professional decisions; stale predecessors remain immutable |
| `/laudo` | report authoring, editorial profile, figures, references and citations |
| `/revisao` | report review and legal-editorial preflight; unresolved information/validation markers block final Word |
| `/exportar` | authoritative Word DOCX/DOCM and locally derived, fidelity-checked PDF |
| `/orcamento` | fee proposals, judicial decisions, expenses and receipts, separate from technical merit |
| `/recuperacao` | backup verification, staging, explicit promotion and reopen |
| Global `/recuperacao` | recovery even when no case exists |
| Global `/configuracoes` | installation defaults, professional/editorial profiles, visual assets, Word template, test document, history and restore |

Settings authority follows:

`INSTALLATION DEFAULT → NEW CASE SNAPSHOT → CASE → REPORT → WORD`

Installation defaults do not travel in a case backup. New cases copy defaults
and their assets into a case snapshot. Later global edits do not silently change
existing cases: updating a case from settings requires an explicit confirmed
action. Report and Word use the case snapshot. A selected custom Word template
is the visual authority for that report. Sources:
`ADR-consolidacao-configuracoes-participantes-v1.md` and
`scripts/backend_contract/application/installation_settings.py`.

## Capabilities and Constraints

- `AI = PROPOSAL_ONLY`: `SOURCE_VALUE → AI_PROPOSAL → ENGINE_DECISION → PROFESSIONAL_OVERRIDE`.
  The assistant is unavailable by default; installation does not authorize a provider.
- `PROFESSIONAL_DECISION = HUMAN`: approval and signature belong to the expert;
  legal qualifications belong to the Court.
- `WORD = AUTHORITATIVE`: final Word bytes are bound by hash and structurally revalidated.
- `PDF = DERIVED_LOCAL`: Word 16 conversion must pass structural and visual
  fidelity checks and bind to the exact Word bytes. Refusal preserves Word and
  produces no professional PDF.
- `PRIVATE_EGRESS = FALSE`: no cloud OCR, external maps, analytics, telemetry,
  remote settings sync or external AI by default. OCR is local and optional;
  extraction does not invent missing content.
- Append-only revisions, workspace isolation, monotonic stale propagation and
  fail-closed backup/recovery protect the authority chain.
- `PROPOSAL != FACT`, `SOURCE != DECISION`, `NOT_OBSERVED != NONEXISTENT`.
- Domain logic stays below the UI. Source code contains no case secrets, remote
  fonts/assets or real case material.
- Automated synthetic assurance is distinct from human acceptance. Installer,
  accepted Human RC and real-case execution remain unproven deliverables.

## Brand Commitments

Voice is concise, professional and action-oriented in Brazilian Portuguese.
An expert’s configured logo, watermark, cover/header/footer apply to reports
through the case snapshot; they do not establish a product brand.

## Evidence on Hand

Public fixtures, golden corpus and product oracles are synthetic. They verify
implementation and authority boundaries, not professional acceptance or a real
case. No customer claims, photographs or metrics may be fabricated.

## Product Principles

- Follow the professional workflow, with one primary action per view.
- Keep normal work simple; technical and audit detail are available on demand.
- Preserve professional decisions, provenance and recoverability.
- Keep assurance proportional to risk and report unavailable states honestly.

## Accessibility & Inclusion

Semantic landmarks, keyboard navigation, visible focus, real links,
`aria-current`, live-region feedback and reduced-motion support are implemented
patterns. Long content and reduced desktop widths remain explicit QA concerns,
not a blanket claim of flawless accessibility.

## Historical origin

`FRONTEND_SHELL_V1` and its 2026-08-23 plan record the initial shell milestone.
Those historical limits no longer describe the current product. Future roadmap
work is not promoted into this document before its capabilities are integrated.
