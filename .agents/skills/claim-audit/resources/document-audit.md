# Document Audit Protocol

Extended protocol for auditing complete documents (papers, articles, reports).

## Step 1: Sample Claims

Don't audit everything. Focus on:
- Claims central to the argument (load-bearing)
- Claims with specific numbers or statistics
- Claims that seem surprising or convenient for the author
- Claims that directly support the author's conclusion

## Step 2: Locate Sources

For each sampled claim, find the cited source. Note if:
- Source is accessible (can you verify?)
- Source is primary vs. secondary
- Source is peer-reviewed, preprint, or grey literature

## Step 3: Apply the Protocol

Run standard audit (fidelity, delta, fairness) on each claim.

## Step 4: Assess Patterns

Look for systematic issues:
- Do errors favor the author's position? (motivated reasoning)
- Are the same sources over-relied upon?
- Is there citation diversity or echo chamber?
- Do hedges disappear between source and claim?

## Step 5: Recommend Proportionate Fixes

For each flagged claim, recommend a remediation strategy appropriate to its salience. Avoid recommending heavy revision for illustrative claims.

## Document Audit Output Format

```
DOCUMENT: [title/description]
CLAIMS SAMPLED: [n]
CLAIMS VERIFIED: [n]

SUMMARY:
- Grounded: X%
- Weakly grounded: X%
- Interpolated: X%
- Unsubstantiated: X%
- Wrong: X%

SALIENCE BREAKDOWN:
- Load-bearing claims flagged: [n]
- Supporting claims flagged: [n]
- Illustrative claims flagged: [n]

PATTERNS DETECTED:
- [any systematic issues]

FLAGGED CLAIMS:
[detailed audit of problematic claims, with remediation recommendations]
```

## Batch Audit Summary Format

| # | Claim | Type | Salience | Fidelity | Δ | Verdict | Remediation |
|---|-------|------|----------|----------|---|---------|-------------|
| 1 | "b ≈ 0.377..." | factual | load-bearing | accurate | high | GROUNDED | none |
| 2 | "assumption is strong" | editorial | supporting | n/a | n/a | GROUNDED-EDITORIAL | none |
| 3 | "sold 500,000 copies" | factual | illustrative | stretched | high | WEAKLY GROUNDED | footnote |
| 4 | "doesn't compare..." | interpretive | load-bearing | accurate | high | SLANTED | inline revision |

Then expand on flagged items (INTERPOLATED, SLANTED, UNSUBSTANTIATED, WRONG), with remediation recommendations proportionate to salience.

## Domain-Specific Calibration

Different fields have different citation norms:

| Domain | Tolerance for | Watch for |
|--------|--------------|-----------|
| **Academic** | Precise claims only | Overclaiming, p-hacking citations |
| **Journalism** | Some interpretation | Confirmation bias, source laundering |
| **Legal** | Precise precedent | Distinguishing on weak grounds |
| **Technical docs** | Accuracy over style | Outdated references |
| **Opinion/Editorial** | Explicit interpretation | Unmarked editorializing |
| **General nonfiction** | Illustrative examples | Disproportionate remediation |

Calibrate strictness to context. A blog post has different standards than a systematic review.
