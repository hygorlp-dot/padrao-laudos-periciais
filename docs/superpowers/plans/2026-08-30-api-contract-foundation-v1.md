# API Contract Foundation V1 — execution plan

Issue: #147

## Causal DAG

`canonical judicial schema + semantic deserializer`
→ `versioned reusable API component`
→ `single bounded ingress boundary`
→ `synthetic contract/adversarial tests`
→ `focused vertical regression`
→ `terminal assurance and independent reviews`.

Critical path: preserve semantic graph validation at API ingress. The OpenAPI
component is structural documentation and never replaces the canonical Python
deserializer.

## Scope

- Add no product endpoint, persistence, UI, trust mechanism, or tooling plane.
- Use the existing canonical schema and `procedural_context_from_mapping`.
- Reject malformed, ambiguous, oversized, structurally invalid, and
  semantically invalid JSON with a sanitized error.
- Use synthetic fixtures only.
