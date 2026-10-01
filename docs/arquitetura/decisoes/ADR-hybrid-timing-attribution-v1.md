# ADR — Hybrid timing attribution V1 (V7-4)

## Status

Accepted. Human decision "2-III" recorded in Issue #256 (2026-10-01). Supersedes the
event-specific disposition of `ADR-pr-timing-observability-v1.md`.

## Context

The same full-gate evidence was read differently by event: a pull request above 60 s
was `WARNING` (green) and the push to `main` was `FAIL`. With the current suite
(~12–17 min on hosted Windows runners) every merge turned `main` red although every
semantic stage passed. An absolute wall-clock sample cannot separate runner drift from
candidate cost.

## Decision

- One policy (`HYBRID`) for pull requests and `main`. A local `verify_core --full` emits the
  same `PASS`/`ATTRIBUTION_REQUIRED` evidence but does not run the BASE attribution, which
  only the protected workflow performs.
- The semantic full gate is unchanged and blocking; timing never hides a semantic,
  coverage, hotspot or privacy finding.
- `config/quality-baseline.json` `full_gate_max_seconds` stays byte-identical at the
  historical **60 s** reference (#259 keeps it out of scope). At or below it the timing
  status is `PASS`. With the current suite every protected run is above it, so the BASE
  attribution runs on every PR and every `main` push; reducing that cost is #259.
- Above it the status is `ATTRIBUTION_REQUIRED` and the mandatory workflow step
  "Timing attribution BASE vs HEAD" measures the exact BASE commit (PR base SHA, or
  `github.event.before` on `main`) on the same runner and blocks only when
  `HEAD − BASE > max(60 s, BASE × 0.10)`, the materiality rule authorized by the human
  decision on #109 (material delta attributable to the candidate). The absolute 60-second
  floor absorbs single-sample runner variance: on `main` `04dfb71` the same tree measured
  151.0 s on the PR and 172.2 s on push, so a 10%-only threshold produced a false red.
- Missing, duplicated, non-finite, negative or unknown evidence, an inexact BASE SHA,
  or a failed BASE checkout fails closed.
- The full paired `BASE → HEAD → HEAD → BASE` protocol (#109) is reserved for the final
  RC, release, quality-system changes and suspected timing regressions.

## Trust boundary

`scripts/quality/verify_core.py` (capability-pinned) is unchanged. The decision module
`scripts/quality/timing_attribution.py` reads evidence files only and acquires no
process capability; process orchestration lives in the protected workflow. The
workflow hash pinned in `tests/test_repository_safety_gate.py` is rotated in the same
change, under the recorded human decision.

## Consequences

`main` and pull requests agree. Duration stays visible on every run. A candidate that
makes the gate materially slower than its BASE still blocks; a slow runner alone does
not. When attribution is required the job runs the gate twice (timeout raised to
60 min).
