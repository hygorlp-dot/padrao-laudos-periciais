"""Runtime semantic checks in addition to JSON Schema validation."""


def validate_review_output(review: dict, *, expected_head: str) -> list[dict]:
    findings = []
    if review.get("head_sha") != expected_head:
        findings.append({"code": "STALE_REVIEW", "severity": "P0"})
    independence = review.get("independence", {})
    independent = (
        independence.get("separate_execution") is True
        and independence.get("separate_context") is True
        and independence.get("isolated_checkout") is True
        and independence.get("implementation_write_access") is False
        and independence.get("private_context_received") is False
        and independence.get("independence_proven") is True
    )
    if not independent:
        findings.append({"code": "INDEPENDENCE_NOT_PROVEN", "severity": "P0"})
    if review.get("conclusion") == "APPROVED" and (review.get("p0_open") != 0 or review.get("p1_material_open") != 0):
        findings.append({"code": "INCONSISTENT_APPROVAL", "severity": "P0"})
    return findings
