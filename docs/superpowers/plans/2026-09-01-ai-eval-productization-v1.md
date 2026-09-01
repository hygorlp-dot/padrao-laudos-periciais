# AI Eval Productization V1 — Implementation Plan

**Issue:** #3, Stage 10 slice S10-D
**Protected base:** `ffc1d9db5e2f5dfa92ff3a7db6d5ec2afbec49e0`

## Causal DAG and critical path

```text
synthetic longitudinal oracle identities
  -> versioned adversarial AI eval dataset
     -> immutable per-case observations with source/profile/version telemetry
        -> deterministic separated metrics + hard safety gate
           -> baseline regression and cost ceilings
              -> Stage 10 longitudinal adversarial oracle
                 -> protected terminal assurance
```

Critical path: dataset completeness and observation identity -> source/authority
metrics -> hard gate. Cost/latency aggregation and baseline comparison are pure
parallel lanes until the final eval report. One mutation owner controls the eval
contracts and fixture. No model call, private data, external telemetry, UI,
multi-agent framework, batch API, or new provider is added.

## Tasks

1. Add `AI_EVAL_DATASET_V1`, derived only from synthetic longitudinal Stage 3–11
   identities, with all required adversarial scenario classes and exact expected
   source/workspace outcomes.
2. RED/GREEN immutable dataset/observation contracts bound to dataset version,
   case, workspace, provider/profile/model, prompt/schema hashes, token/cost and
   latency telemetry, and human review outcome.
3. RED/GREEN deterministic metrics for schema validity, grounding/recall,
   unsourced proposals, wrong authority promotion, human actions, tokens, cached
   tokens, estimated cost, latency, self-authorization and cross-workspace use.
4. RED/GREEN hard gates: zero authority/cross-workspace/unsourced material
   violations; complete case coverage; no single subjective aggregate score.
5. Add configurable preflight run/workspace/session token and cost ceilings with
   fail-closed local accounting and no external telemetry.
6. Add golden comparison over quality dimensions, grounding, authority, cost and
   latency, preserving profile/model/prompt/schema versions.
7. Execute the longitudinal Stage 10 adversarial matrix across S10-A/B/C plus the
   dataset, then freeze one exact HEAD for terminal assurance, independent review,
   systemic audit, protected CI, normal merge and post-main oracle.
