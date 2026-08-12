"""External diversity, recovery and merge gates."""
import re

SHA = re.compile(r"^[0-9a-f]{40}$")

EXTERNAL_TRIGGERS = {
    "MATERIAL_ARCHITECTURE_CHANGE", "AI_AUTHORITY_CHANGE", "AI_GATEWAY_CHANGE",
    "PRIVATE_EGRESS_CHANGE", "PII_SECURITY_CHANGE", "MULTIMODAL_EVIDENCE_CHANGE",
    "EVIDENCE_CHAIN_CHANGE", "CAUSALITY_CHANGE", "NORM_APPLICABILITY_CHANGE",
    "MATERIAL_GATE_CHANGE", "DESTRUCTIVE_PERSISTENCE_CHANGE", "P0_FOUND",
    "P1_MATERIAL_FOUND", "CODEX_REVIEW_DISAGREEMENT",
    "SYSTEMIC_CONFIDENCE_INSUFFICIENT", "REPEATED_MATERIAL_FINDING",
    "HIGH_RISK_RELEASE", "BOOTSTRAP_GOVERNANCE_CHANGE",
}


def evaluate_external_diversity_gate(triggers: list[str]) -> dict:
    unknown = sorted(set(triggers) - EXTERNAL_TRIGGERS)
    if unknown:
        raise ValueError(f"unknown external diversity triggers: {unknown}")
    active = sorted(set(triggers))
    return {"claude_required": bool(active), "triggers": active}


def next_recovery_action(findings: list[dict]) -> str:
    if any(item.get("severity") in {"P0", "P1"} for item in findings):
        return "REPRODUCE_TEST_FIX_REVERIFY"
    return "READY_FOR_FINAL_GATES"


def evaluate_merge_gate(state: dict) -> dict:
    reasons = []
    head = state.get("head_sha")
    expected_head = state.get("expected_head_sha")
    if not (isinstance(head, str) and SHA.fullmatch(head) and head == expected_head):
        reasons.append("head_sha")
    if not isinstance(state.get("claude_required"), bool):
        reasons.append("claude_required")
    triggers = state.get("claude_triggers", [])
    try:
        derived = evaluate_external_diversity_gate(triggers)["claude_required"]
    except (TypeError, ValueError):
        derived = None
        reasons.append("claude_triggers")
    if derived is None or state.get("claude_required") is not derived:
        reasons.append("claude_gate_consistency")
    required = {
        "tests": "PASS", "verify_core": "PASS",
        "ci": "PASS", "privacy": "PASS", "p0_open": 0, "p1_material_open": 0,
        "codex_review": "APPROVED", "systemic_audit": "APPROVED",
        "independence_proven": True, "codex_independence_evidence_verified": True,
        "systemic_independence_evidence_verified": True, "external_egress_gate": "PASS",
        "dependency_merged": True, "cross_model_disagreement_material": 0,
    }
    if state.get("claude_required") is True:
        required.update({"claude_review": "APPROVED", "claude_independence_proven": True,
                         "claude_independence_evidence_verified": True})
    for name in ("codex_review_head", "systemic_audit_head"):
        if state.get(name) != head:
            reasons.append(name)
    if state.get("claude_required") is True and state.get("claude_review_head") != head:
        reasons.append("claude_review_head")
    reasons.extend(key for key, value in required.items() if state.get(key) != value)
    return {"status": "APPROVED" if not reasons else "BLOCKED", "reasons": reasons}
