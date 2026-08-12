"""Recalculate review independence from observable identifiers."""


def evaluate_independence(implementer: dict, reviewer: dict, expected_head: str) -> dict:
    reasons = []
    for key in ("execution_id", "context_id", "worktree"):
        if not reviewer.get(key) or reviewer.get(key) == implementer.get(key):
            reasons.append(f"{key.upper()}_NOT_INDEPENDENT")
    if reviewer.get("implementation_write_access") is not False:
        reasons.append("IMPLEMENTATION_WRITE_ACCESS")
    if reviewer.get("private_context_received") is not False:
        reasons.append("PRIVATE_CONTEXT_SHARED")
    if reviewer.get("head_sha") != expected_head:
        reasons.append("STALE_REVIEW")
    if reviewer.get("persisted_evidence") is not True:
        reasons.append("EVIDENCE_NOT_PERSISTED")
    return {"independence_proven": not reasons, "reasons": reasons}
