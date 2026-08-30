# Judicial Domain Model Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish immutable, provenance-bound judicial entities and relations before API Contract Foundation and Case Analysis.

**Architecture:** A source-system-neutral domain module owns the canonical vocabulary and validates one procedural-context graph. JSON Schema and synthetic fixtures mirror the same closed contract; legacy singular party fields are derived compatibility views only.

**Tech Stack:** Python dataclasses/enums, JSON Schema Draft 2020-12, pytest/jsonschema.

## Global Constraints

- Synthetic fixtures only; no real case data or private egress.
- Representative is not party; access is not participation; mention is not participation.
- Raw source labels and exact provenance are mandatory.
- Source adapters remain outside the canonical model.
- No trust, tooling, API, persistence, Bridge, or UI expansion.

---

### Task 1: Canonical graph contract

**Files:**
- Create: `tests/test_judicial_domain_model_v1.py`
- Create: `scripts/backend_contract/judicial_domain.py`

**Interfaces:**
- Produces immutable `JudicialEntity`, `ProcessParticipant`, `ProceduralRole`, `ProcessPole`, `RepresentationLink`, `AccessRelation`, `ParticipantStatus`, `ProceduralContext`, and `SourceProvenance`.

- [ ] Write tests that construct valid plural graphs and reject missing provenance, dangling links, access-only promotion, representative promotion, duplicate IDs, context mismatch, and invented normalization.
- [ ] Run `python -m pytest tests/test_judicial_domain_model_v1.py -q` and confirm RED because the module is absent.
- [ ] Implement only the immutable values and graph validation required by those tests.
- [ ] Re-run the focused test and confirm GREEN.

### Task 2: Synthetic serialization contract

**Files:**
- Create: `schemas/judicial-domain-model-v1.schema.json`
- Create: `tests/fixtures/judicial-domain-model-v1.json`
- Modify: `tests/test_judicial_domain_model_v1.py`

**Interfaces:**
- Consumes the canonical field names from Task 1.
- Produces a closed Draft 2020-12 schema and a multi-context synthetic acceptance matrix.

- [ ] Add RED tests validating the fixture and adversarial mutations against the schema.
- [ ] Add the closed schema and synthetic fixture with 1:1, plural poles, representation, MP roles, access-only entities, third parties, and unknown raw roles.
- [ ] Run focused tests and confirm every adversarial mutation fails closed.

### Task 3: Legacy compatibility projection

**Files:**
- Modify: `scripts/backend_contract/judicial_domain.py`
- Modify: `tests/test_judicial_domain_model_v1.py`

**Interfaces:**
- Produces `legacy_singular_party_view(context) -> dict[str, str] | None`.

- [ ] Add RED tests proving projection exists only for exactly one unambiguous active principal participant at each active/passive pole.
- [ ] Implement the projection without making it canonical authority.
- [ ] Verify plural, unknown, inactive, or ambiguous graphs return `None`.

### Task 4: Assurance and delivery

**Files:**
- Modify only files causally required by findings.

- [ ] Run focused tests, schema validation, sibling boundary tests, Ruff, diff checks, full regression, and `python -m scripts.quality.verify_core --full` once on frozen HEAD.
- [ ] Apply repository safety, independent PR review, systemic audit, and shadow systemic review.
- [ ] Push `feat/145-judicial-domain-model-foundation-v1`, open a normal PR referencing #145, and require protected CI before merge.
