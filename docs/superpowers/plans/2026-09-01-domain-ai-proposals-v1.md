# Domain AI Proposals V1 — Implementation Plan

**Issue:** #3, Stage 10 slice S10-C
**Protected base:** `4e5536350d4dcdc053d9358f4b2488a698eb752a`

## Causal DAG and critical path

```text
generic immutable AIProposal + exact source refs
  -> domain task registry + strict structured-output schema
     -> source-grounded proposal validator
        -> report upstream-authority prerequisites
           -> authority/adversarial matrix
              -> protected terminal assurance
```

The critical path is proposal payload validation: every material item must cite
an exact source already bound to the generic `AIProposal`, forbidden authority
claims fail closed, and the output remains a proposal view only. Report drafting
adds a prerequisite gate over reviewed/effective canonical inputs. No canonical
mutation command is injected or exposed.

One mutation owner applies all changes to this shared AI/domain boundary. No UI,
provider/network change, model-callable tool, multi-agent orchestration, or
Stage 10 eval/productization work is included.

## Tasks

1. RED: define the five domain task families and exact allowed proposal item
   kinds; generate strict JSON schemas with no authority fields.
2. GREEN: validate immutable domain proposal views against the original
   `AIProposal` workspace and exact source identities.
3. RED/GREEN: reject unsourced/unknown/cross-workspace items, hidden approval or
   decision fields, invalid task-kind combinations, and empty material output.
4. RED/GREEN: require reviewed Case Analysis, applicable professional Planning,
   effective Technical Findings, professional decisions, and canonical question
   links before report-draft proposals can be validated.
5. Run sibling/adversarial tests proving zero `HumanReviewDecision`,
   `PlanningDecision`, `ProfessionalDecision`, effective finding, approved report,
   delivery, court approval, or budget-close mutation.
6. Freeze exact HEAD and execute terminal regression, frontend gates,
   `verify_core --full`, independent review, systemic audit, protected CI, and
   external diversity if the recalculated final-path triggers require it.
