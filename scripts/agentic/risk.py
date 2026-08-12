"""Classify repository changes without external calls."""
from __future__ import annotations

TRIGGER_PATHS = {
    "scripts/backend_contract/": "AI_AUTHORITY_CHANGE",
    "scripts/agentic/": "BOOTSTRAP_GOVERNANCE_CHANGE",
    "schemas/review-multiagente.schema.json": "BOOTSTRAP_GOVERNANCE_CHANGE",
    "scripts/conhecimento_privado/": "PRIVATE_EGRESS_CHANGE",
    "scripts/motor_vicios/": "CAUSALITY_CHANGE",
    "scripts/auditoria_pericial/": "MATERIAL_GATE_CHANGE",
}


def classify_change_risk(paths: list[str]) -> dict:
    normalized = sorted({path.replace("\\", "/") for path in paths})
    triggers = sorted({trigger for path in normalized for prefix, trigger in TRIGGER_PATHS.items() if path.startswith(prefix)})
    unknown = bool(normalized) and not triggers
    if unknown:
        triggers = ["MATERIAL_ARCHITECTURE_CHANGE"]
    risk = "HIGH" if triggers else "LOW"
    return {"risk": risk, "triggers": triggers, "paths": normalized, "conservative": unknown}
