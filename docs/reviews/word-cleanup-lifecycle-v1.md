# Word cleanup lifecycle — causal #319

Refs #319; refs #316; blocks draft #318. This change starts from main
`152edad3fd9b70e3eef41b8c5c406699a2d5a196` and contains no PAT patch.

## Native evidence

All documents were synthetic; no private RC, Office log contents, network,
installation, or termination of unrelated Word processes was used.

The minimal sequence was N-01 DOCX, N-02 DOCM, then
`test_native_docm_reaches_word_as_exact_authoritative_bytes`. Passive Windows
inspection correlated the exact Additional log with its owning WINWORD process:
PID 56404, creation `2026-10-14 01:12:59.576000` UTC, a verified member of the
product Job. The process held
file handles 968/3648 and a 4 MiB mapped region of the first Additional log.
At the first delete failure, `01:13:02.126983` UTC, that same mapped file raised
WinError 32 and the pinned Word process handle returned `WAIT_TIMEOUT` (258).
The Python worker and console handles were already signalled (0).

The same condition was observed in the subsequent DOCM renders. Restart Manager
queried after the initial failure found no owner: the process could finish
during that query. Its result therefore does not supersede the immediate handle
observation. Job accounting and physical process completion are different
conditions during `TerminateJobObject`. The controlled TEMP/TMP places Office
diagnostics inside the sensitive render root; that location remains unchanged.

The separate native regression failed before the production patch with
`AssertionError: cleanup lifecycle WinError [32]`. It records actual deletion
errors without injecting a lock and exercises the real converter and Word.

## Correction

The parent pins handles for processes observed in its exact Job, verifies Job
membership before adopting them, and retains the handles through termination.
The bounded containment wait now requires both zero active Job processes and
signalled worker/member handles. It waits on a pending process instead of the
already-exited Python worker. Every retained handle is released on exit.

The existing 5-second containment windows and cleanup policy are unchanged.
Ownership ambiguity and a process that does not complete still fail closed.
No residue is accepted, no Diagnostics exclusion is added, and PDF authority,
fidelity, COM binding, macro restrictions, and Job kill-on-close are unchanged.

## Focal qualification

- Native RED: WinError 32; GREEN: native regression passed.
- Minimal Word preflight and first causal default-template test: PASS.
- Final implementation SHA-256:
  `59e1ff0eeb13ea496a697fa9a6f5ccc1d80349c51a4c6d84fa9ebc6f3817166e`.
- Three predeclared final stability iterations: 4/4 PASS each, no render-root
  residue. Earlier iterations precede the final handle-release adjustment and
  are not counted as the final stability proof.
- Native matrix: 19 PASS, one existing macro-carrying DOCM fixture gap SKIP.
  Bystander preservation, timeout, authoritative DOCM bytes, and fidelity passed;
  all 21 observed product render roots were removed.
- Containment/renderer/authority regression: 305 PASS. It includes permanent
  sensitive cleanup refusal, invalid/missing PDF, ambiguous membership, and
  unsignalled owned processes. No test was weakened to accept residue.

The native matrix also emitted the existing synthetic template-authoring RPC
diagnostic `0x800706be` while pytest and its process returned zero. That helper
is outside the product Job and is not changed by this UOW. Native VBA fixture
coverage is not claimed. Product-owned handles and render trees are the scoped
containment evidence, not a claim that every Word instance on the desktop exited.

The single local integral gate passed all 16 stages in 1909.242 seconds on this
final implementation. Its timing status is `ATTRIBUTION_REQUIRED`; protected CI
must provide candidate attribution. The interrupted broad handle probes were
cancelled without terminating Word, and their exact owned render roots were
removed afterward through the unchanged bounded product cleanup. Original #317
diagnostic trees were preserved. No inspection installed tools or used network.

Local receipts and passive probes are preserved outside Git. Exact-commit gates, reviews,
exact-HEAD external-diversity decision, CI, merge and the single post-main proof
must be recorded against the final candidate before #319 becomes terminal.

`FILES_DELETED=0`; `PRIVATE_EGRESS=FALSE`; `HUMAN_RC_READY=FALSE`.
PR #318 remains draft at `409e9a19fee9c8e5f0feaeda5ac622c93576abe4`.
`FULL_GATE_318_AUTHORIZED=FALSE`. No Proxy RC or next UOW is authorized here.
