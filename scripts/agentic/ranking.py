"""Validate and sort evidence-backed engineering rankings."""

RISKS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
ROBUSTNESS = {"A", "B", "C", "D", "E"}


def rank_boundaries(entries: list[dict]) -> list[dict]:
    for item in entries:
        if (item.get("intrinsic_risk") not in RISKS or item.get("robustness") not in ROBUSTNESS
                or not isinstance(item.get("engineering_priority"), int)
                or item["engineering_priority"] < 1 or not str(item.get("evidence", "")).strip()):
            raise ValueError("ranking must be valid and evidence-backed")
    return sorted((dict(item) for item in entries), key=lambda item: (item["engineering_priority"], item["boundary"]))
