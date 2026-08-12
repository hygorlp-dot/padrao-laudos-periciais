"""Runtime semantic checks in addition to JSON Schema validation."""


def validate_review_output(review: dict, *, expected_head: str) -> list[dict]:
    findings = []
    if review.get("head_sha") != expected_head:
        findings.append({"code": "STALE_REVIEW", "severity": "P0"})
    independence = review.get("independence", {})
    evidence = independence.get("evidence", {})
    independent = (
        independence.get("separate_execution") is True
        and independence.get("separate_context") is True
        and independence.get("isolated_checkout") is True
        and independence.get("implementation_write_access") is False
        and independence.get("private_context_received") is False
        and independence.get("independence_proven") is True
        and isinstance(evidence, dict)
        and evidence.get("checkout_head_sha") == expected_head
        and isinstance(evidence.get("persisted_review_sha256"), str)
        and len(evidence["persisted_review_sha256"]) == 64
    )
    if not independent:
        findings.append({"code": "INDEPENDENCE_NOT_PROVEN", "severity": "P0"})
    if review.get("conclusion") == "APPROVED" and (review.get("p0_open") != 0 or review.get("p1_material_open") != 0):
        findings.append({"code": "INCONSISTENT_APPROVAL", "severity": "P0"})
    if review.get("conclusion") == "APPROVED" and any(
        item.get("severity") in {"P0", "P1"} for item in review.get("findings", []) if isinstance(item, dict)
    ):
        findings.append({"code": "INCONSISTENT_FINDING_COUNT", "severity": "P0"})
    actual_p0 = sum(item.get("severity") == "P0" for item in review.get("findings", []) if isinstance(item, dict))
    actual_p1 = sum(item.get("severity") == "P1" for item in review.get("findings", []) if isinstance(item, dict))
    if review.get("p0_open") != actual_p0 or review.get("p1_material_open") != actual_p1:
        findings.append({"code": "FINDING_COUNT_MISMATCH", "severity": "P0"})
    return findings
