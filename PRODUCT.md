# Product

<!-- impeccable:product-schema 1 -->

> Status: CURRENT AUTHORITY for what the product is now. Derived from the live
> implementation (`frontend/src/routes/routeCatalog.ts`,
> `frontend/src/workspaces/`, `scripts/backend_contract/`) and the accepted
> architecture decisions in `docs/arquitetura/decisoes/`. Temporal state
> (candidate SHA, Human RC rounds, CI results) is not recorded here; it lives in
> the canonical roadmap issue and in `config/product-maturity-v1.json`.
> No case data, brand or commercial claim is inferred.

## Platform

web

## Stack

Existing codebase. Local desktop/browser application:

- frontend: React, TypeScript and Vite, plain CSS, browser-native navigation;
- backend: Python modular monolith (`scripts/backend_contract/`) with Domain,
  Application, Infrastructure, Local API (`/app-api`) and Product Bridge layers
  over the protected forensic Core (`scripts/extracao_pje/`,
  `scripts/triagem_pericial/`, `scripts/planejamento_pericial/`,
  `scripts/vistoria_estruturada/`, `scripts/motor_vicios/`,
  `scripts/redacao_pericial/`);
- persistence: local SQLite per installation (cases) plus a separate local
  installation-settings file; private case bytes in a local private root;
- Word rendering: DOCX/DOCM produced locally; PDF derived locally through
  Microsoft Word 16 on Windows.

The product listens on `127.0.0.1` only and is started by a local command over a
built frontend. There is no installer yet (`PACKAGING_GAP`).

## Users

The primary user is a court-appointed engineering expert (perito judicial)
preparing, reviewing and delivering forensic engineering work on a desktop,
often in long sessions. They need a calm, predictable workspace that keeps the
sequence of forensic work visible, keeps every value traceable to its source and
never decides on their behalf.

## Product Purpose

A professional local application for judicial engineering expert work,
initially focused on construction defects and pathological manifestations in
buildings. It takes a judicial case from the PJe export to an authoritative Word
report, a separate fee budget and a verifiable backup, while the forensic Core,
not the UI or an AI, remains the domain authority and the expert remains the
professional authority.

Success means the expert moves through the real workflow with every proposal
reviewable, every decision explicit and every artifact recoverable.

## Positioning

The interface follows the real progression of forensic work, not technical
modules, generic dashboards or AI features. Extraction and AI only propose;
the expert confirms, corrects or rejects, and that decision is recorded with its
source.

## Operating Context

Workflow implemented today (routes under `/pericias/<id>/…`, grouped as
Processo, Perícia, Laudo and Gestão):

| Step | Route | What happens |
|---|---|---|
| Perícias (start) | `/` | open an existing case workspace or create a new one |
| Início | `/` (in a case) | stage overview and this case's settings snapshot |
| Processo | `/processo` | process identification, participants by pole (active, passive, other participants) with representatives, and property data proposals by layer, each with its source |
| Materiais | `/materiais` | import PDFs (including PJe exports); two-phase ingestion with honest processing, retry and PJe document availability (exclude/re-enable a piece) |
| Análise | `/analise` | Case Analysis: parties, allegations, quesitos and documents from the record, with provenance |
| Planejamento | `/planejamento` | object, material questions, what to verify on site, site location; explicit succession when the analysis changes |
| Vistoria | `/vistoria` | observations, measurements, photographs (photo library), statements, field/mobile package; explicit successor inspection with record-by-record reuse |
| Evidências | `/evidencias` | technical chain: evidence review, method choice, decision on each technical proposal |
| Constatações | `/constatacoes` | effective findings ledger, each with evidence, method and decision |
| Análise técnica | `/analise-tecnica` | construction-defect analysis (PAT); the engine proposes, the expert decides; explicit empty successor when upstream authority changes |
| Laudo | `/laudo` | report authoring with editorial profile, figures, references and citations |
| Revisão | `/revisao` | report review and legal-editorial preflight; open `[INFORMAÇÃO NECESSÁRIA` / `[VALIDAÇÃO DO PERITO` markers block the final Word |
| Exportar | `/exportar` | delivery: authoritative Word (DOCX/DOCM) and the locally derived PDF |
| Orçamento | `/orcamento` | fee budget, financially separate from technical merit |
| Recuperação | `/recuperacao` (also outside any case) | backup verify → staging → explicit promotion → reopen |
| Configurações | `/configuracoes` (outside any case) | installation defaults: professional profile, editorial and legal-editorial profile, visual identity and assets, default/custom Word template, test document, history and restore |

Settings flow (accepted decision D3/D8, ADR
`ADR-consolidacao-configuracoes-participantes-v1.md`):

`INSTALLATION DEFAULT → NEW CASE SNAPSHOT → CASE → REPORT → WORD`

Installation defaults live in their own local file and never travel in a case
backup. A new case copies the current defaults into its own snapshot; an
existing case changes only through an explicit "update from settings" with
confirmation. The report and the Word output use the case snapshot, never the
day's global default.

## Capabilities and Constraints

Authority (non-negotiable):

- `AI = PROPOSAL_ONLY`: `SOURCE_VALUE → AI_PROPOSAL → ENGINE_DECISION →
  PROFESSIONAL_OVERRIDE`; an AI proposal never becomes effective by itself.
  The AI assistant is unavailable by default.
- `PROFESSIONAL_DECISION = HUMAN`: technical content, criteria and conclusions
  belong to the expert; legal qualifications are reserved to the Court.
- `PROPOSAL != FACT`, `SOURCE != DECISION`, `NOT_OBSERVED != NONEXISTENT`,
  `SEARCH_FOUND_NOTHING != INFORMATION_DOES_NOT_EXIST`.
- `WORD = AUTHORITATIVE`: the bound Word/DOCM is the professional artifact,
  hash-bound and structurally revalidated.
- `PDF = DERIVED_LOCAL`: rendered locally by Word 16, accepted only after
  fidelity checks and bound by SHA-256 to the exact Word bytes; any refusal
  keeps the Word and produces no PDF.
- `PRIVATE_EGRESS = FALSE`: no cloud OCR, external maps, analytics, telemetry,
  remote settings sync or external AI by default.

Engineering constraints:

- Append-only revisions; predecessors stay immutable; stale state propagates
  monotonically.
- Workspace isolation; backup and recovery fail closed on foreign or incomplete
  graphs.
- The frontend holds no domain logic, secrets, remote fonts or remote assets.
- No real case material in the repository, fixtures, issues or logs.

Not yet available: installer/packaging, human acceptance of the release
candidate, execution on a real case.

## Brand Commitments

No commercial brand, name, sigla, logo or tagline is defined for the product.
The interface uses only the neutral functional descriptor "Sistema Pericial".
Visual identity configured by the expert in Configurações (logo, watermark,
background, header, footer, cover) applies to that expert's Word reports; it is
the expert's identity, not a product brand. Voice: concise, professional,
technical and action-oriented in Brazilian Portuguese; never a generic SaaS
dashboard, CRM, AI product or marketing page.

## Evidence on Hand

Only synthetic material exists in the repository: synthetic PJe exports,
fixtures, golden corpus and oracles. No real case content, customer claims,
metrics, photographs or brand assets are available, and the UI must not
fabricate them.

## Product Principles

- User workflow first: the product follows the forensic sequence.
- Simple by default; technical and audit detail only on demand.
- One primary action per view.
- Domain logic stays below the UI; proposals stay proposals until the expert
  decides.
- Assurance remains proportional to risk; no false success, no silent data loss.

## Accessibility & Inclusion

Semantic landmarks, real links, visible focus, keyboard navigation,
`aria-current`, sufficient contrast, live-region announcements for asynchronous
work and reduced-motion support. Layouts must work at reduced desktop widths
without horizontal scroll and with long names and large participant lists.

## Historical origin

The current surface grew from `FRONTEND_SHELL_V1` (human brief of 2026-08-23,
plan `docs/superpowers/plans/2026-08-23-frontend-shell-v1.md`), which provided
only the application shell, navigation and presentation states. That milestone
is a historical record; its scope limits ("shell only", "no domain use cases")
no longer describe the product and do not govern current work.
