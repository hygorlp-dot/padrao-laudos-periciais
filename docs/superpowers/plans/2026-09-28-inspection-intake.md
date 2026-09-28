# PR C — inspection facts and source-grounded case intake (#239)

Base: stable PR B candidate `8da37d4` (same tree as local `39c96ca`); this remains a local causal stack until
predecessors are integrated. The user's final-convergence handoff authorizes
this design. Existing writable owners and review authority are retained.

## Inspection

An optional structured visit context belongs to InspectionSession: physical
date/start/end, weather, temperature, relative humidity and explicitly confirmed
attendants. Session creation time remains application history, never the date
of the physical visit. A dedicated command stamps the existing expert profile
and confirmation time, guards the current revision and invalidates review when
material facts change. Generic saves/offline edits cannot manufacture that
confirmation. Legacy mappings omit the absent extension.

Offer confirmed property/location and known participants as choices. Selecting
a person is not evidence of attendance; the explicit confirmation is required.
Existing session instruments/methods are reusable for new measurements. Their
selection neither proves calibration nor creates a technical finding.

## Case intake

Use the current local PDF/OCR reader and current CaseAnalysis source inventory.
Question proposals require explicit origin headings and numbered source blocks;
retain original number, exact text, document identity, physical page(s), excerpt
and extraction method. Recompute the proposal on acceptance; preserve the
working question → finding → answer chain and existing professional review.
Ambiguous documents stay source-review tasks, never invented questions.

The recurring document inventory is CaseAnalysis-owned. Source matches remain
proposals; no match means only not found in the current ingested material.
Professionally confirmed absence requires an explicit reason and the existing
expert identity. A mention of a document is not proof that it is attached.

## Checks and limits

RED/green tests cover legacy bytes, invalid dates/units, false attendance,
generic-save bypass, concurrent changes, source replay, duplicate questions,
logical PJe page boundaries and absence-vs-not-found. Exercise UI through the
existing local bridge and recovery through the existing backup verifier.
No remote parser/provider, private fixtures, trust-plane or protected Word work.
Cross-workspace instrument/method catalog persistence is deferred: reuse the
existing case records first. Reference reuse uses existing ReportReference
copies with explicit acceptance, never a mutable link to an old report.
