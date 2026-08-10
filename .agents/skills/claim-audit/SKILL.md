---
name: claim-audit
description: Audit claims for grounding using information-theoretic reasoning. Use for "verify this claim", "fact-check", "audit for hallucination", "check my sources", or evaluating whether citations support assertions. Works for AI and human-authored text.
license: MIT
metadata:
  version: "0.2.4"
  author: mhalle
---

# Claim Audit

Evaluate whether claims are grounded in cited evidence or unsubstantiated, using the scrub-and-probe method from compression theory.

## Core Principle

A claim is **grounded** if the cited evidence is actually doing informational work—removing it would change the claim. A claim is **unsubstantiated** if the same assertion would be made without the evidence (the citation is decorative).

Empirically, hallucinations decrease by ~0.13 per additional nat of information provided.

This applies equally to:
- AI-generated text (detecting hallucination)
- Human-authored text (detecting unsupported claims, citation padding)
- Your own writing (self-audit)

## Claim Taxonomy

| Type | Description | Audit Focus |
|------|-------------|-------------|
| **FACTUAL** | Reports what source says | Does source actually say this? |
| **INTERPRETIVE** | Characterizes or evaluates source | Is interpretation warranted? |
| **SYNTHETIC** | Combines multiple sources | Does synthesis follow from parts? |
| **EDITORIAL** | Reviewer's own judgment | Is it marked as opinion? |

Editorial claims are not confabulations if clearly framed as interpretation.

## Claim Salience

| Salience | Description | Audit Priority |
|----------|-------------|----------------|
| **LOAD-BEARING** | Argument fails if claim is wrong | High scrutiny |
| **SUPPORTING** | Strengthens but not essential | Medium scrutiny |
| **ILLUSTRATIVE** | Color, examples, conventional figures | Note issues only |

Match remediation effort to salience. See `resources/remediation.md` for strategies.

## Audit Protocol

For each claim, evaluate three dimensions:

### 1. Source Fidelity
Does the claim accurately represent what the source says?

- **Accurate**: Claim matches source content
- **Stretched**: Claim goes slightly beyond source
- **Interpolated**: Claim fills gaps with plausible details not in source
- **Contradicted**: Source says something different
- **Unsupported**: Source doesn't address this
- **Inaccessible**: Cannot verify (source unavailable, paywalled, broken link)

### 2. Information Delta (Δ)
How much does the evidence reduce uncertainty?

- **High Δ**: Claim is specific; wouldn't know this without source
- **Medium Δ**: Claim is plausible; source confirms
- **Low Δ**: Claim is generic; source is decorative
- **Zero Δ**: Would make this claim regardless of source
- **Negative Δ**: Source contradicts claim

### 3. Rhetorical Fairness (for interpretive/editorial claims)
Is the framing fair to the source?

- **Fair**: Presents source's reasoning before critiquing
- **Slanted**: Presents deliberate choices as oversights
- **Strawman**: Misrepresents position to critique it
- **Uncharitable**: Ignores source's own acknowledgment of limitations

## Output Format

```
CLAIM: [the assertion]
TYPE: [factual / interpretive / synthetic / editorial]
SALIENCE: [load-bearing / supporting / illustrative]
CITES: [source references]

SOURCE FIDELITY: [accurate / stretched / interpolated / contradicted / unsupported / inaccessible]
INFORMATION DELTA: [high / medium / low / zero / negative]
RHETORICAL FAIRNESS: [fair / slanted / strawman / uncharitable] (if interpretive/editorial)

VERDICT: [see below]
CONFIDENCE: [high / medium / low]
RECOMMENDED REMEDIATION: [see resources/remediation.md]
NOTES: [specifics]

SUPPORTING EVIDENCE: (if grounded/weakly grounded)
- Source: [title/author/publication]
- URL/DOI: [link]
- Snippet: "[quoted text supporting the claim]"
```

## Verdict Criteria

| Verdict | Criteria |
|---------|----------|
| **GROUNDED** | Factual + accurate + high Δ |
| **GROUNDED-EDITORIAL** | Editorial claim clearly marked as interpretation |
| **WEAKLY GROUNDED** | Accurate but low Δ, or stretched slightly |
| **INTERPOLATED** | Plausible details added beyond source |
| **SLANTED** | Accurate but rhetorically unfair framing |
| **UNSUBSTANTIATED** | Zero Δ or unsupported; citation decorative |
| **INSUFFICIENT** | ISR < 1; evidence exists but inadequate for claim's specificity |
| **UNVERIFIABLE** | Source inaccessible; cannot confirm or deny |
| **WRONG** | Contradicted by source |

## Confidence Calibration

Based on Information Sufficiency Ratio (ISR = available evidence / required evidence):

| Confidence | Criteria |
|------------|----------|
| **High** | ISR ≥ 1; evidence clearly sufficient for claim |
| **Medium** | 0.5 ≤ ISR < 1; partial support, some extrapolation |
| **Low** | ISR < 0.5; evidence largely decorative or inaccessible |

When confidence is low, prefer conservative verdicts and recommend hedging.

## Evidence Documentation

When a claim is marked as GROUNDED or WEAKLY GROUNDED, provide the supporting evidence:

**For each source:**
- Full citation (title/author/publication)
- Direct URL or DOI
- Relevant snippet (1-3 sentences of quoted text supporting the claim)

This serves two purposes:
1. Allows readers to verify the grounding themselves
2. Makes it easy to convert the audit into properly cited content

## Inaccessible Sources

When a cited source cannot be verified:

1. **Note the limitation** — Mark fidelity as "inaccessible"
2. **Assess the claim independently** — Is it plausible? Common knowledge? Extraordinary?
3. **Check secondary sources** — Does anyone else cite this source for this claim?
4. **Verdict options:**
   - UNVERIFIABLE if claim depends entirely on inaccessible source
   - WEAKLY GROUNDED if claim is plausible and low-stakes
   - Flag for follow-up if claim is load-bearing

## Self-Audit Checklist

1. **List all factual claims** — anything verifiable
2. **Classify salience** — load-bearing, supporting, or illustrative?
3. **Identify the source** — cited, contextual, or assumed?
4. **Check source fidelity** — go back and verify
5. **Flag editorial framing** — is opinion marked as such?
6. **Check rhetorical fairness** — is the source's reasoning presented?
7. **Choose proportionate remediation** — match fix to importance

## Resources

- `resources/theory.md` — Information-theoretic framework, formal definitions, EDFL
- `resources/failure-modes.md` — 12 common failure patterns with examples
- `resources/remediation.md` — Remediation strategies and decision tree
- `resources/document-audit.md` — Protocol for auditing complete documents

## Subagent Strategies for Self-Audit

When an agent audits its own claims, there is inherent risk of bias—the same reasoning that produced the claim may rationalize its grounding. To mitigate this:

**Use a separate subagent for auditing:**
- Spawn a subagent with only the claim and cited sources (not the full conversation context)
- The subagent evaluates grounding without access to the original reasoning
- This creates epistemic separation between claim-generation and claim-verification

**Adversarial framing:**
- Instruct the auditing subagent to actively look for ways the claim could be ungrounded
- Ask: "What would need to be true in the source for this claim to be WRONG?"

**Blind audit:**
- Present claims without indicating which you generated vs. which came from users
- Prevents motivated reasoning toward defending your own outputs

**Cross-check specific extractions:**
- Have the subagent independently extract what the source says, then compare to the claim
- Divergence reveals interpolation or stretching

## Provenance

This skill is a qualitative interpretation of quantitative concepts from:

- **Paper:** [Predictable Compression Failures](https://arxiv.org/abs/2509.11208) (Chlon, Karim, & Chlon, Hassana Labs)
- **MCP Implementation:** [Strawberry](https://github.com/leochlon/pythea/tree/main/strawberry)

The skill translates mathematical constructs (KL divergence, ISR thresholds) into heuristic judgments. It cannot compute actual information-theoretic quantities—it approximates through reasoning. See `resources/theory.md` for formal definitions and the README for detailed mapping.

## Updates

- **Repository:** https://github.com/mhalle/claim-audit
- **Latest release:** https://github.com/mhalle/claim-audit/releases/latest/download/claim-audit.skill
- **Version API:** https://api.github.com/repos/mhalle/claim-audit/releases/latest

To check for updates:
1. Fetch the version API URL above and extract the `tag_name` field (e.g., "v0.1.2")
2. Compare to the current skill version in the frontmatter
3. If a newer version exists, inform the user and offer to download the latest .skill file
4. Present the downloaded .skill file as an output file so the user can install it
