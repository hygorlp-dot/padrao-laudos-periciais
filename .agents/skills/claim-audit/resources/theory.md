# Theoretical Framework: Information-Theoretic Grounding

This reference provides additional detail on the formal concepts underlying the claim audit skill. For attribution and provenance, see the main SKILL.md.

## The Core Insight: Hallucination as Compression Failure

Language models minimize expected conditional description length across input orderings:

```
𝔼_π[ℓ(Y | Γ_π(X))]
```

This makes them "Bayesian in expectation, not in realization." When the information budget is insufficient for a claim's complexity, the model fills gaps with plausible-sounding content—a predictable compression failure, not a mysterious reasoning breakdown.

## Information Delta (Δ̄)

The **Information Delta** measures how much evidence reduces uncertainty about a claim.

Formally, Δ̄ is the expected KL divergence between a reference distribution P and permutation-averaged model predictions:

```
Δ̄ := 𝔼_π[KL(P ∥ S_π)]
```

In simplified terms:
- p₀ = prior probability of the claim (before seeing evidence)
- p₁ = posterior probability of the claim (after seeing evidence)

```
Δ ≈ log(p₁/p₀)
```

A high Δ means the evidence did substantial informational work. A low or zero Δ means the claim would be made regardless of the evidence.

## The Expectation-level Decompression Law (EDFL)

This is the paper's central theorem linking information budgets to reliability.

For rare events with low prior mass q̄, achieving reliability (1-ε) requires:

```
Δ̄ ≥ (1−ε)log(1/q̄) + O(q̄) nats
```

**Intuition:** The rarer a claim (lower q̄), the more information you need to support it reliably. Extraordinary claims require extraordinary evidence—formalized.

**Empirical finding:** Hallucinations decrease by approximately 0.13 per additional nat of information.

## Prior Probability (q̄)

The prior q̄(x) represents the model's baseline confidence before seeing specific evidence:

```
q̄(x) = 𝔼_π[q_π(x)]
```

This is computed by averaging predictions across different orderings of the evidence. For conservative bounds, use q_lo = min across permutations.

When q̄ is already high, the evidence provides no additional bits—the claim would be made regardless. This is the mechanism behind decorative citations.

## Information Sufficiency Ratio (ISR)

The **ISR** determines whether available evidence is sufficient to trust a claim:

```
ISR(x) = Δ̄(x) / B2T(x; h*)
```

Where B2T (Bits-to-Trust) is the information required for target reliability h*.

**Decision rule:**
- ISR ≥ 1 → sufficient evidence, claim supportable
- ISR < 1 → insufficient evidence, abstain or flag

When ISR ≈ 0, the citation provides no bits-to-trust—it's decorative.

**Empirical result:** ISR = 1.0 threshold achieves near-0% hallucinations with 24% abstention rate.

## Operational Planners

The paper provides three tools for pre-generation risk assessment:

| Planner | Definition | Use |
|---------|------------|-----|
| **B2T** (Bits-to-Trust) | KL(Ber(1−h*) ∥ Ber(q_lo)) | Information needed for target reliability |
| **RoH** (Risk-of-Hallucination) | 1 − p_max(Δ̄, q̄) | Achievable error given available budget |
| **ISR** (Information Sufficiency Ratio) | Δ̄ / B2T | Answer/abstain decision threshold |

## Positional Jensen Penalty

Models show different confidence depending on evidence ordering. The Jensen gap quantifies this:

```
𝔍_Γ(P,θ) = 𝔼_π[KL(P‖p_θ(·|Γ_π))] − KL(P‖p̄_θ) ≥ 0
```

**Empirical measurements:**
- Qwen2-7B: 0.1041 nats/token mean Jensen gap
- Llama-3.1-8B: 0.00982 nats/token mean Jensen gap

This explains why the same evidence can yield different confidence levels depending on presentation order.

## Martingale Violation Bound

Order-induced prediction deviations scale logarithmically:

```
𝔼_π|R_π(x)| ≤ O(log n)
```

**Empirical scaling:** Mean absolute residuals follow a + b·ln(n) pattern:
- Qwen2-7B: b ≈ 0.377
- Llama-3.1-8B: b ≈ 0.147

This bounds how much ordering effects can distort predictions as evidence length grows.

## Confabulation as Zero-Delta Claims

A **confabulation** (or hallucination) occurs when:
- A claim is presented as grounded in evidence
- But the claim would be made with equal confidence without that evidence
- The citation is decorative, not load-bearing

In information-theoretic terms: the prior q̄ is already high enough that the evidence provides no additional bits. The model defaults to prior probabilities, making answers indistinguishable from guessing at that prior mass level.

## Interpolation as Excess Claims

**Interpolation** occurs when:
- Evidence provides some information (Δ > 0)
- But the claim exceeds what that information supports
- Plausible details are filled in beyond the source

The claim "borrows" credibility from real evidence to support content not actually in the source. The information budget covers part of the claim but not all of it.

## Salience: A Pragmatic Extension

Pure information theory treats all bits equally. But in practice, some claims matter more than others for an argument's validity.

**Salience** is a pragmatic weighting added to this skill (not present in the source paper) that acknowledges the cost of remediation must be weighed against the importance of the claim being remediated:

- Load-bearing claims: high salience, deserve full scrutiny
- Illustrative claims: low salience, may tolerate imprecision

## Application to Human vs. AI Writing

The same framework applies to both:

| Context | Zero-Δ failure mode | Common name |
|---------|---------------------|-------------|
| AI | Model generates plausible content not in source | Hallucination |
| Human | Author cites source that doesn't support claim | Citation padding |

The underlying mechanism is identical: presenting a claim as grounded when it would be made regardless of the evidence.

## Limitations of the Framework

The source paper acknowledges several constraints:

1. **Binary adjudication:** EDFL's guarantees are tightest for Bernoulli (yes/no) predicates. Multi-class extension exists via one-vs-rest but is less sharp.

2. **Scale effects:** The relationship between model scale and positional bias needs systematic investigation across architectures.

3. **Known priors:** The framework assumes q̄ can be estimated. In practice, this requires sampling across permutations or using domain knowledge.

## References

- Chlon, L., Karim, A., & Chlon, M. (2025). Predictable Compression Failures: Why Language Models Actually Hallucinate. arXiv:2509.11208
- Strawberry MCP implementation: https://github.com/leochlon/pythea/tree/main/strawberry
