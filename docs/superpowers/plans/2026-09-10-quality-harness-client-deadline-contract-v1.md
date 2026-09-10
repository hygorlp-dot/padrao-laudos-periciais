# Issue #197 — quality-harness client deadline contract

## Scope

This change is test-harness-only. It addresses the fixed five-second client
deadline that can classify a valid, slow Local API operation as `TimeoutError`
while the protected server continues to `RESPONSE_COMPLETED` under runner
load. No production Local API, Recovery, trust boundary, gate, test
selection, or coverage behavior is changed.

## Causal contract

The harness now distinguishes these bounded layers:

- `CLIENT_TRANSPORT_DEADLINE`: explicit `http_request(..., timeout=...)`,
  finite, positive, and capped at 30 seconds;
- `SERVER_REQUEST_ACQUISITION_DEADLINE`: existing
  `LocalServerConfig.request_timeout_seconds`, unchanged;
- `APPLICATION_OPERATION_DURATION`: may exceed the old five-second client
  default for fsync-heavy Recovery work;
- scenario/suite deadlines: still supplied by pytest and the existing test
  harness.

Recovery transaction helpers use an explicit 30-second client operation
  bound. This is a bounded test-client contract, not a production timeout or
  a retry.

## RED evidence

Before the contract was present, the deterministic test-only probe failed
because `http_request` had no explicit operation-deadline parameter:

```text
2 failed in 0.65s
http_request must expose an explicit bounded operation deadline
```

The probe held a valid local service operation until the old five-second
client bound was exceeded, then released it and required the valid 200
response. The same probe required a genuinely blocked operation to fail at a
short explicit deadline.

## GREEN evidence

Focused runs on the Issue #197 branch:

```text
tests/test_client_deadline_contract_v1.py       10 passed in 5.97s
tests/test_local_api_v1.py                     225 passed in 12.09s
backup + recovery transaction                   150 passed, 8 skipped in 121.86s
pytest harness + contract + Local API          261 passed in 17.79s
ruff (all changed test files)                   All checks passed!
git diff --check                                passed
```

The adversarial contract covers slow-valid success, true hang timeout, fast
success, server exception sanitization, and invalid/unbounded deadline
values. Existing Local API tests continue to cover malformed/wrong responses
and connection-loss behavior; the complete Local API focused suite remains
green.

## Safety conclusion

The repair only changes test callers and the test HTTP helper. It does not
alter production semantics, server deadlines, permissions, trust, retry,
sleep, or failure classification for a real hang. Egress remains zero.

The original protected timeout evidence is preserved in Issue #192 and the
PR196 investigation artifacts. PR196 is not modified or unblocked by this
change.
