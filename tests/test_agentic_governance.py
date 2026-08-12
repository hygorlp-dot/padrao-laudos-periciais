import json
import hashlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.agentic import (
    aggregate_findings,
    build_review_package,
    classify_change_risk,
    evaluate_external_diversity_gate,
    evaluate_independence,
    evaluate_merge_gate,
    evaluate_merge_gate_for_paths,
    next_recovery_action,
    rank_boundaries,
    sanitize_external_context,
    select_agent_role,
    validate_review_output,
)


ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
BASE = "b" * 40


def _review(**overrides):
    review = {
        "schema_version": "1.0.0",
        "review_id": "review-001",
        "execution_id": "execution-review-001",
        "review_type": "PR_REVIEW",
        "base_sha": BASE,
        "head_sha": HEAD,
        "independence": {
            "separate_execution": True,
            "separate_context": True,
            "isolated_checkout": True,
            "implementation_write_access": False,
            "private_context_received": False,
            "independence_proven": True,
            "evidence": {
                "execution_record": "codex-task/review-001",
                "context_record": "context/review-001",
                "checkout_record": "worktree/review-001",
                "checkout_head_sha": HEAD,
                "permissions_record": "read-only",
                "persisted_review": "docs/reviews/review-001.json",
                "persisted_review_sha256": "d" * 64,
            },
        },
        "architecture_status": "CONFORME",
        "architectural_challenges": [],
        "findings": [],
        "code_ranking": [{
            "boundary": "AGENTIC_GOVERNANCE", "intrinsic_risk": "HIGH",
            "robustness": "B", "engineering_priority": 1,
            "evidence": "Merge and external-review gates are fail-closed.",
        }],
        "engineering_priorities": ["Preserve exact-HEAD binding."],
        "p0_open": 0,
        "p1_material_open": 0,
        "residual_risks": ["External reviewer availability."],
        "conclusion": "APPROVED",
    }
    review.update(overrides)
    return review


def test_risk_and_external_diversity_are_deterministic_and_fail_closed():
    change = classify_change_risk(["scripts/backend_contract/revisions.py"])
    assert change["risk"] == "HIGH"
    assert "AI_AUTHORITY_CHANGE" in change["triggers"]
    assert evaluate_external_diversity_gate(change["triggers"])["claude_required"] is True
    assert evaluate_external_diversity_gate([])["claude_required"] is False
    with pytest.raises(ValueError):
        evaluate_external_diversity_gate(["UNKNOWN_TRIGGER"])
    mixed = classify_change_risk(["scripts/backend_contract/revisions.py", "unknown/new.py"])
    assert mixed["conservative"] is True and "MATERIAL_ARCHITECTURE_CHANGE" in mixed["triggers"]


def test_every_material_external_trigger_requires_one_final_review():
    triggers = {
        "MATERIAL_ARCHITECTURE_CHANGE", "AI_AUTHORITY_CHANGE", "AI_GATEWAY_CHANGE",
        "PRIVATE_EGRESS_CHANGE", "PII_SECURITY_CHANGE", "MULTIMODAL_EVIDENCE_CHANGE",
        "EVIDENCE_CHAIN_CHANGE", "CAUSALITY_CHANGE", "NORM_APPLICABILITY_CHANGE",
        "MATERIAL_GATE_CHANGE", "DESTRUCTIVE_PERSISTENCE_CHANGE", "P0_FOUND",
        "P1_MATERIAL_FOUND", "CODEX_REVIEW_DISAGREEMENT",
        "SYSTEMIC_CONFIDENCE_INSUFFICIENT", "REPEATED_MATERIAL_FINDING",
        "HIGH_RISK_RELEASE", "BOOTSTRAP_GOVERNANCE_CHANGE",
    }
    assert all(evaluate_external_diversity_gate([trigger])["claude_required"] for trigger in triggers)


def test_roles_are_separated_and_material_work_uses_full_sequence():
    assert select_agent_role("IMPLEMENT") == "IMPLEMENTER"
    assert select_agent_role("RESEARCH") == "RESEARCHER"
    assert select_agent_role("PR_REVIEW") == "PR_REVIEWER"
    assert select_agent_role("SYSTEMIC_AUDIT") == "SYSTEMIC_AUDITOR"
    with pytest.raises(ValueError):
        select_agent_role("AUTO_APPROVE")


@pytest.mark.parametrize("mutation", [
    {"execution_id": "execution-implementer"},
    {"context_id": "context-implementer"},
    {"worktree": "C:/workspace/implementer"},
    {"implementation_write_access": True},
    {"private_context_received": True},
    {"head_sha": "c" * 40},
    {"persisted_evidence": False},
])
def test_independence_rejects_same_execution_context_worktree_stale_or_unpersisted(mutation):
    implementer = {"execution_id": "execution-implementer", "context_id": "context-implementer", "worktree": "C:/workspace/implementer"}
    reviewer = {
        "execution_id": "execution-reviewer", "context_id": "context-reviewer",
        "worktree": "C:/workspace/reviewer", "implementation_write_access": False,
        "private_context_received": False, "head_sha": HEAD, "persisted_evidence": True,
    }
    reviewer.update(mutation)
    assert evaluate_independence(implementer, reviewer, HEAD)["independence_proven"] is False


def _write_independence_evidence(root: Path):
    review = root / "reviews/review.json"
    review.parent.mkdir(parents=True)
    review.write_text('{"conclusion":"APPROVED"}', encoding="utf-8")
    for name in ("execution", "context", "permissions"):
        (root / f"reviews/{name}.txt").write_text(name, encoding="utf-8")
    (root / "reviews/checkout.json").write_text(json.dumps(
        {"head_sha": HEAD, "isolated": True, "clean": True, "read_only": True}), encoding="utf-8")
    return {"execution_record": "reviews/execution.txt", "context_record": "reviews/context.txt",
            "checkout_record": "reviews/checkout.json", "checkout_head_sha": HEAD,
            "permissions_record": "reviews/permissions.txt", "persisted_review": "reviews/review.json",
            "persisted_review_sha256": hashlib.sha256(review.read_bytes()).hexdigest()}


def test_independence_accepts_isolated_read_only_exact_head_review(tmp_path):
    result = evaluate_independence(
        {"execution_id": "impl", "context_id": "ctx-impl", "worktree": "C:/impl"},
        {"execution_id": "review", "context_id": "ctx-review", "worktree": "C:/review",
         "implementation_write_access": False, "private_context_received": False,
         "head_sha": HEAD, "persisted_evidence": True,
         "evidence": _write_independence_evidence(tmp_path)}, HEAD, evidence_root=tmp_path,
    )
    assert result == {"independence_proven": True, "reasons": []}


def test_independence_requires_verifiable_records_not_only_self_attested_booleans():
    result = evaluate_independence(
        {"execution_id": "impl", "context_id": "ctx-impl", "worktree": "C:/impl"},
        {"execution_id": "review", "context_id": "ctx-review", "worktree": "C:/review",
         "implementation_write_access": False, "private_context_received": False,
         "head_sha": HEAD, "persisted_evidence": True}, HEAD,
    )
    assert result["independence_proven"] is False
    assert "STRUCTURED_EVIDENCE_MISSING" in result["reasons"]


def test_review_package_is_first_party_exact_head_and_excludes_private_paths(tmp_path):
    public = tmp_path / "README.md"
    public.write_text("public", encoding="utf-8")
    package = build_review_package(
        issue=31, base_sha=BASE, head_sha=HEAD,
        changed_files=["README.md"], affected_boundaries=["AGENTIC_GOVERNANCE"],
        invariants=["INDEPENDENT_REVIEW_PROOF"], adrs=["ADR-independent-review-proof.md"],
        schemas=["review-multiagente.schema.json"], tests=["tests/test_agentic_governance.py"],
        test_results={"status": "PASS"}, ci="PASS", privacy="PASS",
        dependencies=[], deploy_impact="NONE",
    )
    assert package["head_sha"] == HEAD and package["private_data_included"] is False
    with pytest.raises(ValueError):
        build_review_package(issue=31, base_sha=BASE, head_sha=HEAD,
                             changed_files=["referencias/privadas/caso.pdf"])
    with pytest.raises(ValueError):
        build_review_package(issue=31, base_sha="x" * 40, head_sha=HEAD, changed_files=[])
    with pytest.raises(ValueError):
        build_review_package(issue=31, base_sha=BASE, head_sha=HEAD,
                             changed_files=["scripts/../referencias/privadas/caso.txt"])
    with pytest.raises(ValueError):
        build_review_package(issue=31, base_sha=BASE, head_sha=HEAD, changed_files=[],
                             tests=["../private/test.py"], dependencies=["referencias/privadas/x"])
    with pytest.raises(ValueError):
        build_review_package(issue=31, base_sha=BASE, head_sha=HEAD,
                             changed_files=["REFERENCIAS/PRIVADAS/caso.txt"])


@pytest.mark.parametrize("unsafe", [
    {"path": "referencias/privadas/caso.pdf", "content": "x"},
    {"path": "review.txt", "content": "CPF 123.456.789-09"},
    {"path": "review.txt", "content": "email pessoa@example.com"},
    {"path": "review.txt", "content": "ghp_abcdefghijklmnopqrstuvwxyz123456"},
    {"path": "review.txt", "content": "Processo 1234567-89.2026.8.05.0001"},
    {"path": "review.txt", "content": "Telefone (71) 99999-1234"},
    {"path": "review.txt", "content": "Endereço: Rua Exemplo, 123"},
    {"path": "review.txt", "content": "petição inicial com dados das partes"},
    {"path": "scripts/../referencias/privadas/caso.txt", "content": "x"},
])
def test_external_context_sanitizer_blocks_private_pii_and_secrets(unsafe):
    result = sanitize_external_context([unsafe])
    assert result["allowed"] is False and result["files"] == []


def test_external_context_sanitizer_allows_only_public_first_party_text():
    content = (ROOT / "scripts/agentic/gates.py").read_text(encoding="utf-8")
    result = sanitize_external_context([{"path": "scripts/agentic/gates.py", "content": content}])
    assert result["allowed"] is True
    assert result["files"][0]["path"] == "scripts/agentic/gates.py"
    assert len(result["files"][0]["sha256"]) == 64
    assert sanitize_external_context([{"path": "exports/review.txt", "content": "public"}])["allowed"] is False
    assert sanitize_external_context([{"path": "scripts/agentic/gates.py", "content": "forged"}])["allowed"] is False


def test_external_context_cannot_override_the_canonical_repository_root(tmp_path):
    source = tmp_path / "scripts/forged.py"
    source.parent.mkdir()
    source.write_text("public", encoding="utf-8")
    with pytest.raises(TypeError):
        sanitize_external_context([{"path": "scripts/forged.py", "content": "public"}], root=tmp_path)


def test_review_schema_and_runtime_reject_invalid_or_stale_output():
    schema = json.loads((ROOT / "schemas/review-multiagente.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(_review())) == []
    assert validate_review_output(_review(), expected_head=HEAD) == []
    invalid = _review(head_sha="c" * 40, conclusion="APPROVED", p1_material_open=1)
    findings = validate_review_output(invalid, expected_head=HEAD)
    assert {item["code"] for item in findings} >= {"STALE_REVIEW", "INCONSISTENT_APPROVAL"}
    forged = _review()
    forged["independence"]["separate_execution"] = False
    assert list(Draft202012Validator(schema).iter_errors(forged))
    assert any(item["code"] == "INDEPENDENCE_NOT_PROVEN" for item in validate_review_output(forged, expected_head=HEAD))
    inconsistent = _review(findings=[{"code": "MATERIAL", "severity": "P1", "evidence": "open"}])
    assert list(Draft202012Validator(schema).iter_errors(inconsistent))
    assert any(item["code"] == "INCONSISTENT_FINDING_COUNT" for item in validate_review_output(inconsistent, expected_head=HEAD))
    blocked_mismatch = _review(conclusion="BLOCKED", architecture_status="BLOQUEADO",
                               findings=[{"code": "OPEN", "severity": "P0", "evidence": "x"}])
    assert any(item["code"] == "FINDING_COUNT_MISMATCH" for item in validate_review_output(blocked_mismatch, expected_head=HEAD))


def test_findings_are_deduplicated_without_hiding_severity():
    combined = aggregate_findings([
        [{"code": "X", "severity": "P1", "evidence": "a"}],
        [{"code": "X", "severity": "P0", "evidence": "b"}],
    ])
    assert combined == [{"code": "X", "severity": "P0", "evidence": ["a", "b"]}]


def test_ranking_requires_evidence_and_is_stably_ordered():
    ranked = rank_boundaries([
        {"boundary": "LOW", "intrinsic_risk": "LOW", "robustness": "A", "engineering_priority": 3, "evidence": "isolated"},
        {"boundary": "HIGH", "intrinsic_risk": "HIGH", "robustness": "C", "engineering_priority": 1, "evidence": "merge authority"},
    ])
    assert [item["boundary"] for item in ranked] == ["HIGH", "LOW"]
    with pytest.raises(ValueError):
        rank_boundaries([{"boundary": "X", "intrinsic_risk": "HIGH", "robustness": "C", "engineering_priority": 1, "evidence": ""}])


def test_self_recovery_routes_material_findings_back_to_tdd():
    assert next_recovery_action([{"severity": "P1"}]) == "REPRODUCE_TEST_FIX_REVERIFY"
    assert next_recovery_action([]) == "READY_FOR_FINAL_GATES"


def test_merge_gate_derives_external_review_from_changed_paths():
    state = {
        "head_sha": HEAD, "expected_head_sha": HEAD, "tests": "PASS", "verify_core": "PASS",
        "ci": "PASS", "privacy": "PASS", "p0_open": 0, "p1_material_open": 0,
        "codex_review": "APPROVED", "systemic_audit": "APPROVED", "independence_proven": True,
        "codex_independence_evidence_verified": True, "systemic_independence_evidence_verified": True,
        "external_egress_gate": "PASS", "dependency_merged": True,
        "cross_model_disagreement_material": 0, "codex_review_head": HEAD, "systemic_audit_head": HEAD,
    }
    result = evaluate_merge_gate_for_paths(state, ["scripts/agentic/gates.py"])
    assert result["status"] == "BLOCKED" and "claude_review" in result["reasons"]


def test_merge_gate_blocks_stale_missing_external_review_ci_privacy_or_dependency():
    base = {
        "head_sha": HEAD, "expected_head_sha": HEAD, "tests": "PASS", "verify_core": "PASS",
        "ci": "PASS", "privacy": "PASS", "p0_open": 0, "p1_material_open": 0,
        "codex_review": "APPROVED", "systemic_audit": "APPROVED",
        "independence_proven": True, "codex_independence_evidence_verified": True,
        "systemic_independence_evidence_verified": True, "claude_required": True,
        "claude_triggers": ["BOOTSTRAP_GOVERNANCE_CHANGE"], "claude_review": "APPROVED",
        "claude_independence_proven": True, "claude_independence_evidence_verified": True,
        "external_egress_gate": "PASS",
        "codex_review_head": HEAD, "systemic_audit_head": HEAD, "claude_review_head": HEAD,
        "dependency_merged": True, "cross_model_disagreement_material": 0,
    }
    assert evaluate_merge_gate(base)["status"] == "APPROVED"
    missing_external_decision = dict(base)
    del missing_external_decision["claude_required"]
    assert evaluate_merge_gate(missing_external_decision)["status"] == "BLOCKED"
    for field, bad in (("expected_head_sha", "c" * 40), ("ci", "FAIL"), ("privacy", "UNKNOWN"),
                       ("claude_review", "DEFERRED"), ("dependency_merged", False)):
        candidate = dict(base, **{field: bad})
        assert evaluate_merge_gate(candidate)["status"] == "BLOCKED"
    no_heads = dict(base)
    no_heads.pop("head_sha")
    no_heads.pop("expected_head_sha")
    assert evaluate_merge_gate(no_heads)["status"] == "BLOCKED"


def test_governance_documents_encode_claude_budget_and_stacked_dependency():
    protocol = (ROOT / "docs/padroes/protocolo-external-diversity-review.md").read_text(encoding="utf-8")
    assert "NORMAL_PR = 0" in protocol and "HIGH_RISK_FINAL_HEAD = 1" in protocol
    assert "NO_CLAUDE_ON_INTERMEDIATE_HEAD = TRUE" in protocol
    autonomy = (ROOT / "docs/padroes/protocolo-autonomia-agente.md").read_text(encoding="utf-8")
    assert "DEFAULT_ACTION = DECIDE_AND_PROCEED" in autonomy
    assert "HUMAN_ESCALATION = EXCEPTION_ONLY" in autonomy
