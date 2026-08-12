"""Aggregate independent findings conservatively."""

ORDER = {"P0": 0, "P1": 1, "P2": 2}


def aggregate_findings(groups: list[list[dict]]) -> list[dict]:
    merged: dict[str, dict] = {}
    for finding in (item for group in groups for item in group):
        code = finding["code"]
        current = merged.setdefault(code, {"code": code, "severity": finding["severity"], "evidence": []})
        if ORDER[finding["severity"]] < ORDER[current["severity"]]:
            current["severity"] = finding["severity"]
        evidence = finding.get("evidence")
        if evidence and evidence not in current["evidence"]:
            current["evidence"].append(evidence)
    return sorted(merged.values(), key=lambda item: (ORDER[item["severity"]], item["code"]))
