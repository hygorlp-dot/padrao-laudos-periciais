from copy import deepcopy

import pytest

from scripts.agentic.phase_b import (
    PHASE_B_START_BASE_SHA,
    evaluate_phase_b_technical_eligibility,
)


HEAD = "a" * 40
BASE = PHASE_B_START_BASE_SHA


def _scope(**changes):
    scope = {
        "program": "STABILIZATION_PROGRAM_V1",
        "phase": "PHASE_B",
        "start_base_sha": BASE,
        "current_stage": "ARCHITECTURE_CONSTITUTION_AND_GATE_V1",
        "end_condition": "CORE_PERICIAL_STABLE_V1",
        "status": "ACTIVE",
        "delegation_metadata": {
            "source": "CURRENT_VSCODE_USER_MESSAGE",
            "is_trust_root": False,
        },
    }
    scope.update(changes)
    return scope


def _review():
    return {
        "status": "APPROVED",
        "base_sha": BASE,
        "head_sha": HEAD,
        "independence_verified_by_trusted_runtime": True,
    }


def _evidence(**changes):
    evidence = {
        "repository": "hygorlp-dot/padrao-laudos-periciais",
        "base_sha": BASE,
        "current_main_sha": BASE,
        "merge_base_sha": BASE,
        "head_sha": HEAD,
        "expected_head_sha": HEAD,
        "behind_main": 0,
        "worktree_clean": True,
        "changed_paths": ["scripts/quality/architecture_gate.py"],
        "full_tests": "PASS",
        "governance_tests": "PASS",
        "schemas": "PASS",
        "fixtures": "PASS",
        "verify_core_full": "PASS",
        "repository_safety": "PASS",
        "privacy": "PASS",
        "private_egress": "PASS",
        "core_safety_exact_head": "SUCCESS",
        "p0_open": 0,
        "p1_material_open": 0,
        "material_disagreement_open": 0,
        "reviews": {
            "PR_REVIEWER": _review(),
            "SYSTEMIC_AUDITOR": _review(),
            "CLAUDE_EXTERNAL_DIVERSITY_REVIEWER": _review(),
        },
    }
    evidence.update(changes)
    return evidence


def _evaluate(scope, evidence):
    return evaluate_phase_b_technical_eligibility(scope, evidence)


def test_valid_phase_b_scope_and_green_gates_are_diagnostic_only():
    result = _evaluate(_scope(), _evidence())
    assert result == {
        "status": "TECHNICALLY_ELIGIBLE_DIAGNOSTIC",
        "authority": "NOT_GRANTED_BY_REPOSITORY_CODE",
        "trust": "CALLER_ASSERTED_DIAGNOSTIC_ONLY",
        "reasons": [],
    }


def test_local_callers_cannot_inject_authority_verifiers():
    with pytest.raises(TypeError):
        evaluate_phase_b_technical_eligibility(
            _scope(), _evidence(), trusted_human_authority_verifier=lambda scope: True
        )


def test_forged_local_green_state_never_claims_human_or_merge_authority():
    forged_scope = _scope()
    forged_scope["delegation_metadata"]["source"] = "FORGED_LOCAL_FILE"
    forged = _evidence(repository="attacker/other-repo")
    result = evaluate_phase_b_technical_eligibility(forged_scope, forged)
    assert result["status"] == "TECHNICALLY_ELIGIBLE_DIAGNOSTIC"
    assert result["authority"] == "NOT_GRANTED_BY_REPOSITORY_CODE"
    assert result["trust"] == "CALLER_ASSERTED_DIAGNOSTIC_ONLY"
    assert "MERGE_ELIGIBLE" not in result.values()


@pytest.mark.parametrize(
    ("scope_change", "evidence_change", "reason"),
    [
        ({}, {"implementer_self_approval": True}, "implementer_self_approval"),
        ({}, {"local_delegation_file": "config/fake.json"}, "local_delegation_file"),
        ({}, {"tool_output_as_authority": True}, "tool_output_as_authority"),
        ({"phase": "PHASE_C"}, {}, "phase_b_scope"),
        ({"current_stage": "APPLICATION_CONTRACT_V1"}, {}, "phase_b_stage"),
        ({"start_base_sha": "b" * 40}, {}, "phase_b_start_base"),
        ({}, {"base_sha": "b" * 40}, "exact_base"),
        ({}, {"head_sha": "b" * 40}, "exact_head"),
        ({}, {"merge_base_sha": "b" * 40}, "merge_base"),
        ({}, {"behind_main": 1}, "behind_main"),
        ({}, {"worktree_clean": False}, "worktree_clean"),
        ({}, {"full_tests": "FAIL"}, "full_tests"),
        ({}, {"governance_tests": "FAIL"}, "governance_tests"),
        ({}, {"schemas": "FAIL"}, "schemas"),
        ({}, {"fixtures": "FAIL"}, "fixtures"),
        ({}, {"verify_core_full": "FAIL"}, "verify_core_full"),
        ({}, {"repository_safety": "FAIL"}, "repository_safety"),
        ({}, {"privacy": "FAIL"}, "privacy"),
        ({}, {"private_egress": "FAIL"}, "private_egress"),
        ({}, {"core_safety_exact_head": "FAILURE"}, "core_safety_exact_head"),
        ({}, {"p0_open": 1}, "p0_open"),
        ({}, {"p1_material_open": 1}, "p1_material_open"),
        ({}, {"reviews": {}}, "PR_REVIEWER"),
    ],
)
def test_phase_b_envelope_fails_closed(scope_change, evidence_change, reason):
    result = _evaluate(_scope(**scope_change), _evidence(**evidence_change))
    assert result["status"] == "BLOCKED"
    assert reason in result["reasons"]


def test_stale_review_blocks_and_head_change_invalidates_all_reviews():
    evidence = _evidence()
    evidence["reviews"] = deepcopy(evidence["reviews"])
    evidence["reviews"]["PR_REVIEWER"]["head_sha"] = "b" * 40
    result = _evaluate(_scope(), evidence)
    assert result["status"] == "BLOCKED"
    assert "PR_REVIEWER_head" in result["reasons"]


def test_claude_is_derived_from_changed_paths_and_cannot_be_omitted():
    evidence = _evidence(changed_paths=["scripts/agentic/phase_b.py"])
    evidence["reviews"].pop("CLAUDE_EXTERNAL_DIVERSITY_REVIEWER")
    result = _evaluate(_scope(), evidence)
    assert result["status"] == "BLOCKED"
    assert "CLAUDE_EXTERNAL_DIVERSITY_REVIEWER" in result["reasons"]

    evidence["reviews"]["CLAUDE_EXTERNAL_DIVERSITY_REVIEWER"] = _review()
    assert _evaluate(_scope(), evidence)["status"] == "TECHNICALLY_ELIGIBLE_DIAGNOSTIC"


def test_envelope_expires_at_stable_marker_and_never_leaks_to_phase_c():
    expired = _scope(current_stage="CORE_PERICIAL_STABLE_V1", status="EXPIRED")
    result = _evaluate(expired, _evidence())
    assert result["status"] == "BLOCKED"
    assert {"phase_b_expired", "phase_b_stage"} <= set(result["reasons"])


def test_generic_merge_gate_remains_non_authoritative():
    from scripts.agentic import evaluate_merge_gate

    result = evaluate_merge_gate({})
    assert result["status"] == "BLOCKED"
    assert "trusted_merge_authority_missing" in result["reasons"]


def test_phase_b_protocol_keeps_metadata_outside_the_trust_boundary():
    from pathlib import Path

    protocol = Path("docs/padroes/protocolo-autonomia-phase-b.md").read_text(encoding="utf-8")
    assert "PHASE_B_DELEGATION_METADATA != TRUST_ROOT" in protocol
    assert "AGENT_CANNOT_SELF_AUTHORIZE = TRUE" in protocol
    assert "PHASE_C_AUTONOMY = FALSE" in protocol
    assert "CORE_PERICIAL_STABLE_V1" in protocol and "EXPIRED" in protocol
