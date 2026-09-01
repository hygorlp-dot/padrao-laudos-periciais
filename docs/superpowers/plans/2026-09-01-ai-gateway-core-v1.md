# AI Gateway Core V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the smallest audited, deny-by-default AI boundary without granting AI any canonical professional authority.

**Architecture:** Pure domain contracts describe requests, responses, proposals, runs, egress manifests and model profiles. An application service evaluates egress before provider invocation, validates structured output, persists an immutable run for every attempt and persists proposals only after validation. The concrete OpenAI adapter is confined to infrastructure and uses the official Responses API with strict JSON Schema; existing canonical commands remain untouched.

**Tech Stack:** Python 3.13–3.14, frozen dataclasses, `jsonschema`, existing append-only artifact repository, official pinned `openai-python` SDK, Pytest/Ruff.

## Global Constraints

- Protected base is `4d9420347518b5a5aad3eec02c85602b3fd00b83`.
- Issue #3 is the Stage 10 umbrella; this PR is only `S10-A — AI_GATEWAY_CORE_V1` and uses `Refs #3`.
- `AI_PROPOSAL != EFFECTIVE_VALUE`; no canonical review, approval, delivery, budget or technical command is callable by the model.
- Remote egress defaults to deny; no real API call, paid request, private fixture or `referencias/privadas/` access is permitted in tests.
- Secrets are read only at adapter construction from the process environment and are never persisted, logged, returned or included in error text.
- Only infrastructure may import `openai`; domain and application remain SDK-independent.
- Provider failure must leave the non-AI product usable.
- Existing protected judges, capability policies, support scopes and branch protection remain unchanged.

---

## Causal DAG and critical path

`domain contracts → egress decision → provider port → audited execution → OpenAI adapter → adversarial assurance`

Safe parallel/read-only lanes are dependency/API verification and sibling-boundary inspection. There is one mutation owner for the shared application boundary and one for dependency metadata. The critical path is egress denial before any provider call, followed by immutable AIRun persistence on success, refusal and failure.

### Task 1: Immutable AI contracts and egress policy

**Files:**
- Create: `scripts/backend_contract/ai_gateway.py`
- Test: `tests/test_ai_gateway_core_v1.py`

**Interfaces:**
- Produces: `EgressClass`, `EgressManifest`, `AIModelProfile`, `AIRequest`, `AIResponse`, `AIProposal`, `AIRun`, `UsageRecord`, `EgressPolicy.evaluate(request)`.
- All IDs, timestamps, hashes, workspace identities, source references and exact enum values are validated at construction.

- [ ] Write tests proving default remote denial, workspace/source/hash validation, proposal/run separation, immutable payloads, secret-shaped field rejection and that confidence has no authority field.
- [ ] Run `python -m pytest tests/test_ai_gateway_core_v1.py -q` and confirm RED because the module is absent.
- [ ] Implement frozen contracts and the minimal deterministic policy: `LOCAL_ONLY` is locally admissible; remote classes require an exact manifest, and private content additionally requires explicit authorization.
- [ ] Rerun the focused tests and confirm GREEN.
- [ ] Commit `feat: define audited AI gateway contracts`.

### Task 2: SDK-independent provider port and audited execution service

**Files:**
- Create: `scripts/backend_contract/application/ai_gateway.py`
- Modify: `scripts/backend_contract/application/__init__.py`
- Modify: `scripts/backend_contract/ports.py`
- Test: `tests/test_ai_gateway_core_v1.py`

**Interfaces:**
- Consumes: Task 1 contracts and existing `WorkspaceRepository`, `ArtifactRevisionRepository`, `Clock`, `IdGenerator`.
- Produces: `AIProvider.execute(request, profile) -> AIResponse`, `RunAIProposal.execute(request, profile) -> AIProposal`, artifact kinds `AI_RUN` and `AI_PROPOSAL`.

- [ ] Add RED tests with an in-memory recording provider proving policy denial calls the provider zero times, cross-workspace references fail closed, malformed/extra provider output cannot be persisted, every permitted attempt records one AIRun, and successful proposals are separately append-only.
- [ ] Confirm focused RED failures for missing service behavior.
- [ ] Implement `RunAIProposal` with the exact order: workspace check → policy decision → provider call → strict `jsonschema` validation → server-owned proposal/run IDs → append AIRun → append proposal. On refusal/provider error, append a sanitized AIRun and raise a stable local error without secrets.
- [ ] Confirm GREEN and run sibling repository/application tests selected by change impact.
- [ ] Commit `feat: execute AI proposals through audited application boundary`.

### Task 3: Official OpenAI Responses adapter and deterministic dependency

**Files:**
- Create: `scripts/backend_contract/infrastructure/openai_provider.py`
- Modify: `scripts/backend_contract/infrastructure/__init__.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/test_openai_provider_v1.py`

**Interfaces:**
- Consumes: `AIRequest`, `AIResponse`, `AIModelProfile`; an injected official SDK client in tests.
- Produces: `OpenAIProvider` and `EnvironmentOpenAIClientFactory`.

- [ ] Add RED contract tests proving the adapter sends only the audited manifest context, uses Responses API strict `json_schema`, sets `store=False`, enforces timeout/max output, translates refusal/usage/cached tokens/response ID, rejects extra or malformed output and never exposes the API key.
- [ ] Confirm RED because the adapter and pinned SDK are absent.
- [ ] Add the current official `openai-python` dependency under the existing deterministic `uv` policy.
- [ ] Implement the infrastructure-only adapter using an injected client and direct `OPENAI_API_KEY` environment lookup at construction; never read a secret during domain/application execution.
- [ ] Run adapter and capability-analyzer tests; prove `PROCESS_NAMESPACE_ACQUISITION = 0` and no protected artifact changed.
- [ ] Commit `feat: add protected OpenAI Responses adapter`.

### Task 4: Adversarial matrix, documentation and slice freeze

**Files:**
- Create: `docs/arquitetura/ai-gateway-core-v1.md`
- Modify: `tests/test_ai_gateway_core_v1.py`
- Modify: `tests/test_openai_provider_v1.py`

**Interfaces:**
- Produces: executable evidence for S10-A acceptance and operational configuration documentation.

- [ ] Add adversarial tests for forged source hashes, cross-workspace context, private egress without authorization, prompt injection remaining inert data, wrong schema/extra fields, refusal, timeout, invalid credentials, rate limit, cost/token ceilings and AIRun history rewrite.
- [ ] Document dependency direction, secret setup, deny-by-default behavior, retention claim limits, audit fields and explicitly prohibited authority.
- [ ] Run focused tests, sibling defect sweep, change-impact tests, Ruff and `git diff --check` during RED/GREEN.
- [ ] Freeze one exact HEAD; run one backend regression and one `verify_core --full`, classify historical duration separately, then run independent PR review and systemic audit.
- [ ] Push, open a protected PR with `Refs #3`, require protected CI, merge normally, and run the focused post-main oracle. Do not close #3 or start S10-B until S10-A post-main passes.

## Self-review

- Spec coverage: S10-A abstractions, strict structured output, AIRun audit, egress/privacy, secrets, provider abstraction, official SDK, usage/cost fields, bounded failure semantics and no authority mutation are mapped above.
- Deliberately deferred to authorized later slices: retrieval/context budgeting/router/cache (S10-B), canonical proposal use cases/UI (S10-C), deterministic eval corpus and longitudinal AI metrics (S10-D).
- Placeholder scan: no implementation step depends on an undefined later slice.
- Type consistency: the provider returns `AIResponse`; only `RunAIProposal` creates server-owned `AIRun` and `AIProposal` records.
