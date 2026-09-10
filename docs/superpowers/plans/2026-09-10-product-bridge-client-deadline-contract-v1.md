# Issue #199 — ProductBridge test-client deadline contract

## Causal finding

The PR196 terminal run reproduced a second harness boundary with the same
class of defect: `tests/test_product_bridge_v1.py::request` still constructed
`HTTPConnection(..., timeout=5)`. A valid fsync-heavy ProductBridge operation
could therefore time out in `CLIENT_GETRESPONSE` while the upstream server
completed the handler and response.

This is test-harness-only. Production ProductBridge, Local API, Recovery,
trust boundaries, gates, test selection, coverage, and egress are unchanged.

## RED/GREEN

The deterministic contract first failed because `request` had no explicit
deadline parameter (`2` behavioral failures plus six bound-validation
`TypeError`s). After the repair:

```text
tests/test_product_bridge_deadline_contract_v1.py  8 passed in 6.33s
```

The probe uses a real loopback Local API upstream and ProductBridge proxy,
holds a valid service operation for 5.2 seconds, and then requires a 200
response with the bounded client timeout. A non-releasing service still
raises `TimeoutError` at an explicit short bound. Invalid values (boolean,
non-positive, non-finite, and above 30 seconds) fail closed.

## Contract

`request` now uses a finite, positive client socket-I/O timeout capped at
30 seconds. The `HTTPConnection` value bounds each blocking connect/send/read
operation; it is not a wall-clock deadline for the complete request lifecycle.
The ProductBridge server's request-acquisition and upstream deadlines are not
changed.

## Safety

No retry, sleep, skip, arbitrary unbounded timeout, production mutation,
trust-model change, or egress was introduced. Existing ProductBridge tests
retain their full selection and coverage.
