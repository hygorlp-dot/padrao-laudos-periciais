from copy import deepcopy

import pytest

from scripts.agentic.phase_b import (
    PHASE_B_START_BASE_SHA,
    evaluate_phase_b_merge_eligibility,
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


def _trusted_runtime(scope):
    return scope["delegation_metadata"]["source"] == "CURRENT_VSCODE_USER_MESSAGE"


def _trusted_technical_evidence(evidence):
    return evidence["repository"] == "hygorlp-dot/padrao-laudos-periciais"


def _trusted_review(name, review, base, head):
    return (
        name in {"PR_REVIEWER", "SYSTEMIC_AUDITOR", "CLAUDE_EXTERNAL_DIVERSITY_REVIEWER"}
        and review.get("base_sha") == base
        and review.get("head_sha") == head
    )


def _evaluate(scope, evidence, verifier=_trusted_runtime, technical=_trusted_technical_evidence,
              review_verifier=_trusted_review):
    return evaluate_phase_b_merge_eligibility(
        scope,
        evidence,
        trusted_human_authority_verifier=verifier,
        trusted_technical_evidence_verifier=technical,
        trusted_review_verifier=review_verifier,
    )


def test_valid_phase_b_scope_and_green_gates_are_merge_eligible():
    result = _evaluate(_scope(), _evidence())
    assert result == {
        "status": "MERGE_ELIGIBLE",
        "authority": "HUMAN_SCOPED_DELEGATION_OUT_OF_BAND",
        "reasons": [],
    }


def test_local_green_claims_and_review_booleans_are_not_trust_roots():
    assert "trusted_technical_evidence_verifier_missing" in _evaluate(
        _scope(), _evidence(), technical=None
    )["reasons"]
    assert "trusted_review_verifier_missing" in _evaluate(
        _scope(), _evidence(), review_verifier=None
    )["reasons"]
    assert "technical_evidence_untrusted" in _evaluate(
        _scope(), _evidence(), technical=lambda evidence: False
    )["reasons"]
    assert "PR_REVIEWER_independence" in _evaluate(
        _scope(), _evidence(), review_verifier=lambda *args: False
    )["reasons"]


@pytest.mark.parametrize(
    ("scope_change", "evidence_change", "verifier", "reason"),
    [
        ({}, {}, None, "trusted_human_authority_verifier_missing"),
        ({}, {"implementer_self_approval": True}, _trusted_runtime, "implementer_self_approval"),
        ({}, {"local_delegation_file": "config/fake.json"}, _trusted_runtime, "local_delegation_file"),
        ({}, {"tool_output_as_authority": True}, _trusted_runtime, "tool_output_as_authority"),
        ({"phase": "PHASE_C"}, {}, _trusted_runtime, "phase_b_scope"),
        ({"current_stage": "APPLICATION_CONTRACT_V1"}, {}, _trusted_runtime, "phase_b_stage"),
        ({"start_base_sha": "b" * 40}, {}, _trusted_runtime, "phase_b_start_base"),
        ({}, {"base_sha": "b" * 40}, _trusted_runtime, "exact_base"),
        ({}, {"head_sha": "b" * 40}, _trusted_runtime, "exact_head"),
        ({}, {"merge_base_sha": "b" * 40}, _trusted_runtime, "merge_base"),
        ({}, {"behind_main": 1}, _trusted_runtime, "behind_main"),
        ({}, {"worktree_clean": False}, _trusted_runtime, "worktree_clean"),
        ({}, {"full_tests": "FAIL"}, _trusted_runtime, "full_tests"),
        ({}, {"governance_tests": "FAIL"}, _trusted_runtime, "governance_tests"),
        ({}, {"schemas": "FAIL"}, _trusted_runtime, "schemas"),
        ({}, {"fixtures": "FAIL"}, _trusted_runtime, "fixtures"),
        ({}, {"verify_core_full": "FAIL"}, _trusted_runtime, "verify_core_full"),
        ({}, {"repository_safety": "FAIL"}, _trusted_runtime, "repository_safety"),
        ({}, {"privacy": "FAIL"}, _trusted_runtime, "privacy"),
        ({}, {"private_egress": "FAIL"}, _trusted_runtime, "private_egress"),
        ({}, {"core_safety_exact_head": "FAILURE"}, _trusted_runtime, "core_safety_exact_head"),
        ({}, {"p0_open": 1}, _trusted_runtime, "p0_open"),
        ({}, {"p1_material_open": 1}, _trusted_runtime, "p1_material_open"),
        ({}, {"reviews": {}}, _trusted_runtime, "PR_REVIEWER"),
    ],
)
def test_phase_b_envelope_fails_closed(scope_change, evidence_change, verifier, reason):
    result = _evaluate(_scope(**scope_change), _evidence(**evidence_change), verifier)
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
    assert _evaluate(_scope(), evidence)["status"] == "MERGE_ELIGIBLE"


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
