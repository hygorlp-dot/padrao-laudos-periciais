"""Non-authoritative Phase-B policy diagnostics.

Only the authenticated orchestration environment can combine these diagnostics
with the human's scoped delegation. Repository code never grants merge authority.
"""
from __future__ import annotations

import re
from .risk import classify_change_risk


PHASE_B_START_BASE_SHA = "2c9495d060a681aec8cb26c152d82d3689759b91"
SHA = re.compile(r"^[0-9a-f]{40}$")
PHASE_B_STAGES = (
    "PHASE_B_AUTONOMY_BOOTSTRAP_V1",
    "ARCHITECTURE_CONSTITUTION_AND_GATE_V1",
    "INTEGRATION_GUARDIAN_RESEARCH_V1",
    "INTEGRATION_GUARDIAN_V1",
    "HOTSPOT_CHARACTERIZATION_V1",
    "MOTOR_REFACTOR_V1",
    "DELIMITACAO_REFACTOR_V1",
    "PLANEJAMENTO_REFACTOR_V1",
    "GOLDEN_FORENSIC_CORPUS_V1",
    "DETERMINISM_REPLAY_GUARDIAN_RESEARCH_V1",
    "DETERMINISM_REPLAY_GUARDIAN_V1",
    "SEMANTIC_DETERMINISM_AND_REPLAY_V1",
    "RESILIENCE_GUARDIAN_RESEARCH_V1",
    "RESILIENCE_GUARDIAN_V1",
    "CRITICAL_MUTATION_AND_FAULT_INJECTION_V1",
    "CORE_TERMINAL_ASSURANCE_V1",
)


def _review_reasons(
    name: str,
    review: object,
    base: str,
    head: str,
) -> list[str]:
    if not isinstance(review, dict):
        return [name]
    reasons = []
    if review.get("status") != "APPROVED": reasons.append(name)
    if review.get("base_sha") != base: reasons.append(f"{name}_base")
    if review.get("head_sha") != head: reasons.append(f"{name}_head")
    return reasons


def evaluate_phase_b_technical_eligibility(scope: dict, evidence: dict) -> dict:
    """Return caller-asserted diagnostics; never return merge authorization."""
    reasons: list[str] = []
    for forbidden in ("implementer_self_approval", "local_delegation_file", "tool_output_as_authority"):
        if forbidden in evidence:
            reasons.append(forbidden)

    if scope.get("program") != "STABILIZATION_PROGRAM_V1" or scope.get("phase") != "PHASE_B":
        reasons.append("phase_b_scope")
    if scope.get("start_base_sha") != PHASE_B_START_BASE_SHA: reasons.append("phase_b_start_base")
    if scope.get("current_stage") not in PHASE_B_STAGES: reasons.append("phase_b_stage")
    if scope.get("end_condition") != "CORE_PERICIAL_STABLE_V1": reasons.append("phase_b_end_condition")
    if scope.get("status") != "ACTIVE": reasons.append("phase_b_expired")
    metadata = scope.get("delegation_metadata")
    if not isinstance(metadata, dict) or metadata.get("is_trust_root") is not False:
        reasons.append("delegation_metadata_not_authority")

    base = evidence.get("base_sha")
    head = evidence.get("head_sha")
    if not isinstance(base, str) or not SHA.fullmatch(base) or base != evidence.get("current_main_sha"):
        reasons.append("exact_base")
    if not isinstance(head, str) or not SHA.fullmatch(head) or head != evidence.get("expected_head_sha") or head == base:
        reasons.append("exact_head")
    if evidence.get("merge_base_sha") != base: reasons.append("merge_base")
    if evidence.get("behind_main") != 0: reasons.append("behind_main")
    if evidence.get("worktree_clean") is not True: reasons.append("worktree_clean")

    required = {
        "full_tests": "PASS", "governance_tests": "PASS", "schemas": "PASS",
        "fixtures": "PASS", "verify_core_full": "PASS", "repository_safety": "PASS",
        "privacy": "PASS", "private_egress": "PASS", "core_safety_exact_head": "SUCCESS",
        "p0_open": 0, "p1_material_open": 0, "material_disagreement_open": 0,
    }
    reasons.extend(key for key, expected in required.items() if evidence.get(key) != expected)

    changed_paths = evidence.get("changed_paths")
    if not isinstance(changed_paths, list) or not changed_paths or any(not isinstance(path, str) or not path for path in changed_paths):
        reasons.append("changed_paths")
        claude_required = True
    else:
        claude_required = bool(classify_change_risk(changed_paths)["triggers"])

    reviews = evidence.get("reviews") if isinstance(evidence.get("reviews"), dict) else {}
    for name in ("PR_REVIEWER", "SYSTEMIC_AUDITOR"):
        reasons.extend(_review_reasons(name, reviews.get(name), base, head))
    if claude_required:
        name = "CLAUDE_EXTERNAL_DIVERSITY_REVIEWER"
        reasons.extend(_review_reasons(name, reviews.get(name), base, head))

    if reasons:
        return {
            "status": "BLOCKED",
            "authority": "NOT_GRANTED_BY_REPOSITORY_CODE",
            "trust": "CALLER_ASSERTED_DIAGNOSTIC_ONLY",
            "reasons": sorted(set(reasons)),
        }
    return {
        "status": "TECHNICALLY_ELIGIBLE_DIAGNOSTIC",
        "authority": "NOT_GRANTED_BY_REPOSITORY_CODE",
        "trust": "CALLER_ASSERTED_DIAGNOSTIC_ONLY",
        "reasons": [],
    }
