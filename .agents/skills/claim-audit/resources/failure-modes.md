# Failure Modes Catalog

Common patterns of ungrounded claims to watch for during auditing.

## Universal Failure Modes

### 1. Decorative Citations
Claim that would be made regardless, dressed up with a reference.

> "The authors use standard deep learning techniques [Methods]."

If Methods just lists model names, this is unsubstantiated—"standard techniques" adds nothing from the source.

### 2. Interpolation
Filling gaps with plausible-sounding details not in source.

> "The dataset spans science, history, and current events [Appendix H]."

If Appendix H lists dataset names but not topic domains, this is interpolated.

### 3. Slanted Framing
Presenting deliberate choices as oversights.

> "The paper doesn't compare against uncertainty baselines."

If the paper explicitly explains why they omit this comparison, presenting it as a gap is slanted. Fair version: "The authors deliberately omit baseline comparisons, arguing X—though one might counter that Y."

### 4. Unmarked Editorializing
Presenting interpretation as factual report.

> "The assumption is strong."

This is evaluation, not source content. Should be framed: "Assumption 2 posits X—this seems strong because Y."

### 5. Specificity Mismatch
Generic claim with specific citation.

> "The model performs well [Table 3]."

If Table 3 has specific numbers, why aren't you citing them? Generic summary of specific data suggests the citation is decorative.

### 6. Common Knowledge as Finding
Obvious claims attributed to source.

> "As the paper notes, neural networks learn from data [Section 1]."

This is common knowledge. If Section 1 doesn't make a specific novel point about this, the citation is padding.

## Human-Specific Failure Modes

### 7. Confirmation Citation
Citing sources that don't actually support the claim, selected because they seem like they should.

> "Studies show that X increases Y [Smith 2020]."

If Smith 2020 actually found a null result or studied something else, this is confirmation citation—the author cited what they expected to find, not what the source says.

### 8. Authority Padding
Citing prestigious sources for claims they don't specifically make.

> "As Einstein noted, simplicity is key in physics [Einstein 1905]."

If Einstein 1905 doesn't discuss simplicity as a principle, this is borrowing authority for an unrelated claim.

### 9. Hedge Stacking
Using multiple weak sources to imply strong support.

> "X is well-established [1, 2, 3, 4, 5]."

If each source only tangentially relates, quantity doesn't create quality. Check if any single source actually establishes X.

### 10. Temporal Mismatch
Citing outdated sources for claims about current state.

> "The standard approach uses method X [Johnson 1998]."

If the field has changed since 1998, this may misrepresent current practice.

### 11. Scope Creep
Generalizing beyond what the source's sample/context supports.

> "People prefer X [Study of 50 undergraduates]."

The source studied a narrow population; the claim implies universality.

### 12. Disproportionate Remediation
Over-revising a minor claim, adding complexity that exceeds the accuracy gain.

> Original: "sold roughly 500,000 copies"
> Over-remediated: Three sentences explaining the historiographical dispute

If the claim is illustrative and the core argument doesn't depend on it, extensive revision may harm clarity more than the original imprecision. Use lighter-touch options (hedge, footnote, or accept imprecision).

## Red Flags in Writing

Quick triggers that suggest a claim needs scrutiny:

- "The authors note that..." + common knowledge
- Specific citation + generic claim
- "Interestingly,..." + thing the writer finds interesting, not the source
- "However,..." + critique without acknowledging source's response
- "Reportedly..." + unclear where this was reported
- "Studies show..." + no specific study cited
- "It is well-established..." + no establishment cited
