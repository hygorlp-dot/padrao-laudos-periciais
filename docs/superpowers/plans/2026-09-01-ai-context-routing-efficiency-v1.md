# AI Context Routing Efficiency V1 — Implementation Plan

**Issue:** #3, Stage 10 slice S10-B  
**Protected base:** `cdedc83d45ce315325e3ca4efed210746a3b3930`

## Causal DAG and critical path

```text
frozen provenance/budget contracts
  -> local retrieval port + deterministic context selection
     -> exact audited AIRequest construction
  -> deterministic model routing
  -> exact-identity local result cache
     -> stale/cross-workspace adversarial matrix
        -> protected terminal assurance
```

Critical path: context identity and budget invariants -> application builder ->
stale/cache and cross-workspace proofs. Model routing is an independent pure
domain lane until integration.

One mutation owner applies all changes to the shared AI boundary. No provider,
network, UI, canonical authority command, or private-data egress is added.

## Tasks

1. Add RED tests for immutable context candidates, exact source provenance,
   deterministic priority/tie-breaking, token budgets, mandatory contrary
   evidence, and fail-closed overflow.
2. Implement a local retrieval port and context builder that emits only
   `AIContextSegment` values represented by the final egress/context manifest.
3. Add RED tests and implement a deterministic auditable model router over
   task class, risk, reasoning, context size, latency/cost ceilings, and strict
   structured-output support.
4. Add RED tests and implement an optional exact-identity cache key containing
   workspace, provider/profile/model, prompt/schema/context hashes and model
   parameters. Reject stale source revisions and cross-workspace reuse.
5. Run sibling sweep and the pre-terminal adversarial/legacy matrix: forged
   refs/hashes, deleted or changed sources, contrary evidence pressure,
   deterministic tie cases, cache collision/replay, and non-AI startup.
6. Freeze one exact HEAD, run selected legacy/change-impact tests, one backend
   regression, frontend gates, Ruff/diff-check, `verify_core --full`, independent
   review, systemic audit, protected CI, and the external-diversity gate if
   recalculated triggers require it.

## Non-goals

- No vector database, embeddings service, whole-case upload, custom prompt
  cache, retries, domain proposal integration, UI, or multi-agent framework.
- No S10-C canonical command or professional-review integration.
- No Stage 10 completion claim.
