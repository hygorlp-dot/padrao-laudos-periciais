# ADR — PR Timing Observability V1

## Status

Accepted for Issue #113.

## Context

The full Core gate has an immutable 60-second target. A pull-request runner can exceed that target because of host variance even when every semantic, privacy, coverage, mutation, architecture, and capability check succeeds. Treating that observation as an architectural authorization or retry signal created bootstrap recursion without improving product correctness.

The duration finding already originates in `scripts/quality/metrics.py`. The protected executor, package initializer, workflows, Architecture Analyzer, and Capability Analyzer must remain unchanged.

## Decision

`validate_quality_baseline` owns the timing disposition:

- exact `GITHUB_EVENT_NAME=pull_request` selects `PR_ADVISORY`;
- push, protected main, and ordinary local execution select `STRICT`;
- the target remains exactly `60.0` seconds;
- every timed execution emits `TARGET_SECONDS`, `OBSERVED_SECONDS`, and `TIMING_STATUS`;
- PR advisory mode omits only `FULL_GATE_DURATION_REGRESSION` from blocking findings;
- all other findings remain blocking without filtering or downgrade;
- missing, malformed, non-finite, negative, or unknown-policy evidence produces `TIMING_EVIDENCE_INVALID` and fails closed.

Calls that do not request a duration measurement retain the existing behavior used by complexity-only validation.

## Trust boundary

This decision does not introduce a timing judge, change branch protection, or let candidate code select a protected executable. `scripts/quality/verify_core.py`, `.github/workflows/core-safety.yml`, `scripts/quality/__init__.py`, and both protected analyzers remain byte-identical to protected main. Existing architecture-protected and capability-protected controls continue to judge the candidate independently.

## Consequences

Pull requests receive stable timing telemetry without a timing-only merge deadlock. Semantic or privacy failure still makes the same gate fail. Protected main and local terminal assurance remain strict, so the 60-second contract is neither raised nor waived.
