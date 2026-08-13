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
    evaluate_repository_merge_gate,
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
    (root / "reviews/execution.json").write_text(json.dumps(
        {"execution_id": "execution-review-001", "role": "PR_REVIEWER", "provider_record": "codex-task/exec-review"}), encoding="utf-8")
    (root / "reviews/context.json").write_text(json.dumps(
        {"context_id": "ctx-review", "separate_from_implementer": True, "private_context_received": False}), encoding="utf-8")
    (root / "reviews/permissions.json").write_text(json.dumps(
        {"read_only": True, "implementation_write_access": False}), encoding="utf-8")
    (root / "reviews/checkout.json").write_text(json.dumps(
        {"head_sha": HEAD, "isolated": True, "clean": True, "read_only": True, "worktree": "C:/isolated/review"}), encoding="utf-8")
    return {"execution_record": "reviews/execution.json", "context_record": "reviews/context.json",
            "checkout_record": "reviews/checkout.json", "checkout_head_sha": HEAD,
            "permissions_record": "reviews/permissions.json", "persisted_review": "reviews/review.json",
            "persisted_review_sha256": hashlib.sha256(review.read_bytes()).hexdigest()}


def test_independence_accepts_isolated_read_only_exact_head_review(tmp_path):
    result = evaluate_independence(
        {"execution_id": "impl", "context_id": "ctx-impl", "worktree": "C:/impl"},
        {"execution_id": "review", "context_id": "ctx-review", "worktree": "C:/review",
         "implementation_write_access": False, "private_context_received": False,
         "head_sha": HEAD, "persisted_evidence": True,
         "evidence": _write_independence_evidence(tmp_path)}, HEAD, evidence_root=tmp_path,
    )
    assert result == {
        "independence_proven": False,
        "local_consistency_verified": True,
        "reasons": ["TRUSTED_INDEPENDENCE_AUTHORITY_MISSING"],
    }


def test_independence_requires_verifiable_records_not_only_self_attested_booleans():
    result = evaluate_independence(
        {"execution_id": "impl", "context_id": "ctx-impl", "worktree": "C:/impl"},
        {"execution_id": "review", "context_id": "ctx-review", "worktree": "C:/review",
         "implementation_write_access": False, "private_context_received": False,
         "head_sha": HEAD, "persisted_evidence": True}, HEAD,
    )
    assert result["independence_proven"] is False
    assert "STRUCTURED_EVIDENCE_MISSING" in result["reasons"]


def test_independence_rejects_nonempty_but_forged_evidence_records(tmp_path):
    evidence = _write_independence_evidence(tmp_path)
    (tmp_path / evidence["execution_record"]).write_text("forged", encoding="utf-8")
    result = evaluate_independence(
        {"execution_id": "impl", "context_id": "ctx-impl", "worktree": "C:/impl"},
        {"execution_id": "review", "context_id": "ctx-review", "worktree": "C:/review",
         "implementation_write_access": False, "private_context_received": False,
         "head_sha": HEAD, "persisted_evidence": True, "evidence": evidence},
        HEAD, evidence_root=tmp_path,
    )
    assert result["independence_proven"] is False


def _isolated_review_repository(tmp_path, monkeypatch):
    import subprocess
    import scripts.agentic.package as package_module
    import scripts.agentic.sanitize as sanitizer
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    files = {
        "config/core-boundaries.json": '{"boundaries":[{"id":"AGENTIC_GOVERNANCE"}]}',
        "config/core-invariants.json": '{"invariants":[{"id":"INDEPENDENT_REVIEW_PROOF"}]}',
        "docs/arquitetura/decisoes/ADR-independent-review-proof.md": "# ADR\n",
        "schemas/review-multiagente.schema.json": "{}\n",
        "tests/test_agentic_governance.py": "# synthetic test artifact\n",
    }
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "scripts/agentic").mkdir(parents=True)
    (tmp_path / "scripts/agentic/change.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    monkeypatch.setattr(package_module, "ROOT", tmp_path)
    monkeypatch.setattr(sanitizer, "ROOT", tmp_path)
    return package_module, base, head


def test_review_package_is_first_party_exact_head_and_excludes_private_paths(tmp_path, monkeypatch):
    package_module, actual_base, actual_head = _isolated_review_repository(tmp_path, monkeypatch)
    package = package_module.build_review_package(
        issue=36, base_sha=actual_base, head_sha=actual_head,
        changed_files=["README.md"], affected_boundaries=["AGENTIC_GOVERNANCE"],
        invariants=["INDEPENDENT_REVIEW_PROOF"],
        adrs=["docs/arquitetura/decisoes/ADR-independent-review-proof.md"],
        schemas=["schemas/review-multiagente.schema.json"], tests=["tests/test_agentic_governance.py"],
        test_results={"status": "PASS"}, ci="PASS", privacy="PASS",
        dependencies=[], deploy_impact="NONE",
    )
    assert package["head_sha"] == actual_head and package["private_data_included"] is False
    assert package["privacy"] == "PASS" and package["sanitization_receipt"]["head_sha"] == actual_head
    assert "changed_files" not in package and package["change_manifest"]
    assert set(package["change_manifest"][0]) == {"path_sha256", "content_sha256", "status"}
    with pytest.raises(TypeError):
        package_module.build_review_package(issue=36, base_sha=BASE, head_sha=HEAD, changed_files=[],
                             sanitization_receipt={"allowed": True, "head_sha": HEAD, "files": []})
    with pytest.raises(ValueError):
        package_module.build_review_package(issue=36, base_sha=actual_base, head_sha=actual_head,
                             changed_files=["docs/Maria-de-Souza-caso.md"],
                             affected_boundaries=["AUTORA_MARIA_DE_SOUZA"],
                             invariants=["CPF_123.456.789-09"],
                             test_results={"raw": "A autora Maria reside na Rua X, 123"},
                             deploy_impact="Parte Maria de Souza")
    with pytest.raises(ValueError):
        package_module.build_review_package(issue=36, base_sha=actual_base, head_sha=actual_head, changed_files=[],
                             affected_boundaries=["AUTORA_MARIA_DE_SOUZA"],
                             invariants=["CPF_12345678909"])
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
    for unsafe in ("C:/outside.txt", "referencias/privadas"):
        with pytest.raises(ValueError):
            build_review_package(issue=31, base_sha=BASE, head_sha=HEAD,
                                 changed_files=[unsafe], adrs=[unsafe], schemas=[unsafe],
                                 tests=[unsafe], dependencies=[unsafe])


def test_review_package_derives_merge_base_and_hashes_binary_blob_bytes(tmp_path, monkeypatch):
    import subprocess
    import scripts.agentic.package as package_module
    import scripts.agentic.sanitize as sanitizer
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/core-boundaries.json").write_text('{"boundaries":[]}', encoding="utf-8")
    (tmp_path / "config/core-invariants.json").write_text('{"invariants":[]}', encoding="utf-8")
    subprocess.run(["git", "add", "config"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    payload = b"\xff\xfe\x00\x81"
    (tmp_path / "asset.bin").write_bytes(payload)
    subprocess.run(["git", "add", "asset.bin"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "binary"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    monkeypatch.setattr(package_module, "ROOT", tmp_path)
    monkeypatch.setattr(sanitizer, "ROOT", tmp_path)
    package = package_module.build_review_package(
        issue=31, base_sha=base, head_sha=head, changed_files=[], repository_root=tmp_path,
    )
    assert package["merge_base"] == base
    assert package["change_manifest"] == [{
        "path_sha256": hashlib.sha256(b"asset.bin").hexdigest(),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "status": "PRESENT",
    }]
    with pytest.raises(ValueError):
        package_module.build_review_package(
            issue=31, base_sha=base, head_sha=head, changed_files=[],
            merge_base="0" * 40, repository_root=tmp_path,
        )
    with pytest.raises(ValueError, match="distinct base and head"):
        package_module.build_review_package(
            issue=31, base_sha=head, head_sha=head, changed_files=[],
            repository_root=tmp_path,
        )


def test_review_package_uses_nul_diff_for_unicode_path(tmp_path, monkeypatch):
    import subprocess
    import scripts.agentic.package as package_module
    import scripts.agentic.sanitize as sanitizer
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/core-boundaries.json").write_text('{"boundaries":[]}', encoding="utf-8")
    (tmp_path / "config/core-invariants.json").write_text('{"invariants":[]}', encoding="utf-8")
    subprocess.run(["git", "add", "config"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    path = "scripts/agentic/ação.py"
    (tmp_path / "scripts/agentic").mkdir(parents=True)
    payload = b"print('ok')\n"
    (tmp_path / path).write_bytes(payload)
    subprocess.run(["git", "add", "--", path], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "unicode"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    monkeypatch.setattr(package_module, "ROOT", tmp_path)
    monkeypatch.setattr(sanitizer, "ROOT", tmp_path)
    package = package_module.build_review_package(
        issue=31, base_sha=base, head_sha=head, changed_files=[], repository_root=tmp_path,
        ci="PASS",
    )
    assert package["change_manifest"] == [{
        "path_sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "status": "PRESENT",
    }]
    assert package["ci"] == {"declared_status": "PASS", "trusted": False}


def test_review_package_expands_rename_and_binds_all_auxiliary_artifacts(tmp_path, monkeypatch):
    import subprocess
    import scripts.agentic.package as package_module
    import scripts.agentic.sanitize as sanitizer
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/core-boundaries.json").write_text('{"boundaries":[]}', encoding="utf-8")
    (tmp_path / "config/core-invariants.json").write_text('{"invariants":[]}', encoding="utf-8")
    (tmp_path / "old.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "mv", "old.py", "new.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "rename"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    monkeypatch.setattr(package_module, "ROOT", tmp_path)
    monkeypatch.setattr(sanitizer, "ROOT", tmp_path)
    package = package_module.build_review_package(
        issue=31, base_sha=base, head_sha=head, changed_files=[], repository_root=tmp_path,
    )
    assert [item["status"] for item in package["change_manifest"]] == ["PRESENT", "DELETED"]
    with pytest.raises(ValueError, match="cannot read exact revision path"):
        package_module.build_review_package(
            issue=31, base_sha=base, head_sha=head, changed_files=[], repository_root=tmp_path,
            adrs=["docs/missing.md"], schemas=["schemas/missing.json"],
            dependencies=["missing.lock"],
        )


def test_review_package_marks_test_claims_untrusted_and_requires_head_paths(tmp_path, monkeypatch):
    package_module, actual_base, actual_head = _isolated_review_repository(tmp_path, monkeypatch)
    package = package_module.build_review_package(
        issue=36, base_sha=actual_base, head_sha=actual_head, changed_files=[],
        tests=["tests/test_agentic_governance.py"], test_results={"status": "PASS"},
    )
    assert package["test_results"] == {"declared_status": "PASS", "trusted": False}
    assert package["test_artifacts"][0]["content_sha256"]
    with pytest.raises(ValueError, match="cannot read exact revision path"):
        package_module.build_review_package(
            issue=36, base_sha=actual_base, head_sha=actual_head, changed_files=[],
            tests=["tests/does-not-exist.py"], test_results={"status": "PASS"},
        )


def test_review_package_contract_is_independent_of_outer_checkout_topology(tmp_path, monkeypatch):
    import subprocess
    package_module, base, head = _isolated_review_repository(tmp_path, monkeypatch)
    checkout_modes = (
        ["git", "switch", "main"],
        ["git", "switch", "-c", "feature-review"],
        ["git", "switch", "--detach", head],
    )
    for command in checkout_modes:
        subprocess.run(command, cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
        package = package_module.build_review_package(
            issue=36, base_sha=base, head_sha=head, changed_files=[], repository_root=tmp_path,
        )
        assert package["base_sha"] == base and package["head_sha"] == head
    with pytest.raises(ValueError, match="distinct base and head"):
        package_module.build_review_package(
            issue=36, base_sha=head, head_sha=head, changed_files=[], repository_root=tmp_path,
        )


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
    content = (ROOT / "scripts/agentic/roles.py").read_text(encoding="utf-8")
    result = sanitize_external_context([{"path": "scripts/agentic/roles.py", "content": content}])
    assert result["allowed"] is True
    assert set(result["files"][0]) == {"path_sha256", "content_sha256"}
    assert "content" not in result["files"][0]
    assert all(len(value) == 64 for value in result["files"][0].values())
    assert sanitize_external_context([{"path": "exports/review.txt", "content": "public"}])["allowed"] is False
    assert sanitize_external_context([{"path": "scripts/agentic/gates.py", "content": "forged"}])["allowed"] is False


def test_external_context_cannot_override_the_canonical_repository_root(tmp_path):
    source = tmp_path / "scripts/forged.py"
    source.parent.mkdir()
    source.write_text("public", encoding="utf-8")
    with pytest.raises(TypeError):
        sanitize_external_context([{"path": "scripts/forged.py", "content": "public"}], root=tmp_path)


def test_external_context_rejects_untracked_and_narrative_case_content(tmp_path, monkeypatch):
    import subprocess
    import scripts.agentic.sanitize as sanitizer
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    private_prose = "Requerente: Maria de Souza, proprietaria do imovel objeto da lide."
    (docs / "case.md").write_text(private_prose, encoding="utf-8")
    (docs / "untracked.md").write_text("public-looking", encoding="utf-8")
    subprocess.run(["git", "add", "docs/case.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    monkeypatch.setattr(sanitizer, "ROOT", tmp_path)
    assert sanitizer.sanitize_external_context([
        {"path": "docs/case.md", "content": private_prose}
    ])["allowed"] is False
    result = sanitizer.sanitize_external_context([
        {"path": "docs/untracked.md", "content": "public-looking"}
    ])
    assert result["allowed"] is False
    assert "PATH_NOT_ALLOWLISTED" in result["reasons"]


def test_external_context_is_bound_to_head_blob_and_governance_allowlist(tmp_path, monkeypatch):
    import subprocess
    import scripts.agentic.sanitize as sanitizer
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    target = tmp_path / "scripts/agentic/public.py"
    target.parent.mkdir(parents=True)
    target.write_text("PUBLIC = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "scripts/agentic/public.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    monkeypatch.setattr(sanitizer, "ROOT", tmp_path)
    target.write_text("Demandante Maria de Souza reside no apartamento objeto da acao.\n", encoding="utf-8")
    assert sanitizer.sanitize_external_context([{
        "path": "scripts/agentic/public.py", "content": target.read_text(encoding="utf-8")
    }])["allowed"] is False
    case = tmp_path / "docs/case.md"
    case.parent.mkdir(exist_ok=True)
    case.write_text("A autora Maria de Souza relatou infiltracao severa.", encoding="utf-8")
    subprocess.run(["git", "add", "docs/case.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "case"], cwd=tmp_path, check=True)
    assert sanitizer.sanitize_external_context([{
        "path": "docs/case.md", "content": case.read_text(encoding="utf-8")
    }])["allowed"] is False


def test_external_context_manifest_never_exports_raw_narrative(tmp_path, monkeypatch):
    import subprocess
    import scripts.agentic.sanitize as sanitizer
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    target = tmp_path / "scripts/agentic/public.py"
    target.parent.mkdir(parents=True)
    narrative = "# A autora Maria de Souza relatou infiltracao severa no apartamento.\n"
    target.write_text(narrative, encoding="utf-8")
    subprocess.run(["git", "add", "scripts/agentic/public.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=tmp_path, check=True)
    monkeypatch.setattr(sanitizer, "ROOT", tmp_path)
    result = sanitizer.sanitize_external_context([{"path": "scripts/agentic/public.py", "content": narrative}])
    assert result["allowed"] is True
    assert result["files"] == [{
        "path_sha256": hashlib.sha256("scripts/agentic/public.py".encode()).hexdigest(),
        "content_sha256": hashlib.sha256(narrative.encode()).hexdigest(),
    }]
    assert narrative not in json.dumps(result)


def test_review_schema_and_runtime_reject_invalid_or_stale_output():
    schema = json.loads((ROOT / "schemas/review-multiagente.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(_review())) == []
    assert {item["code"] for item in validate_review_output(_review(), expected_head=HEAD)} == {
        "TRUSTED_INDEPENDENCE_AUTHORITY_MISSING"
    }
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
    assert next_recovery_action([]) == "NO_MATERIAL_FINDING_DIAGNOSTIC_ONLY"
    assert next_recovery_action([{"unexpected": True}]) == "BLOCK_INVALID_FINDINGS"


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


def test_caller_supplied_merge_state_is_diagnostic_only_and_never_authorizes():
    forged = {
        "head_sha": HEAD, "expected_head_sha": HEAD, "tests": "PASS", "verify_core": "PASS",
        "ci": "PASS", "privacy": "PASS", "p0_open": 0, "p1_material_open": 0,
        "codex_review": "APPROVED", "systemic_audit": "APPROVED", "independence_proven": True,
        "codex_independence_evidence_verified": True, "systemic_independence_evidence_verified": True,
        "claude_required": False, "claude_triggers": [], "external_egress_gate": "PASS",
        "codex_review_head": HEAD, "systemic_audit_head": HEAD, "dependency_merged": True,
        "cross_model_disagreement_material": 0,
    }
    assert evaluate_merge_gate(forged) == {
        "status": "BLOCKED", "reasons": ["trusted_merge_authority_missing"]
    }
    assert evaluate_merge_gate_for_paths(forged, ["README.md"])["status"] == "BLOCKED"


def test_repository_merge_gate_derives_git_diff_and_verifies_persisted_reviews(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "scripts/agentic").mkdir(parents=True)
    (tmp_path / "scripts/agentic/gate.py").write_text("material", encoding="utf-8")
    subprocess.run(["git", "add", "scripts/agentic/gate.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    state = {"expected_base_sha": base, "tests": "PASS", "verify_core": "PASS", "ci": "PASS", "privacy": "PASS",
             "p0_open": 0, "p1_material_open": 0, "dependency_merged": True,
             "cross_model_disagreement_material": 0, "external_egress_gate": "PASS"}
    result = evaluate_repository_merge_gate(tmp_path, base, head, state, reviews=[])
    assert result["status"] == "BLOCKED"
    assert {"codex_review", "systemic_audit", "claude_review"} <= set(result["reasons"])


def test_repository_merge_gate_rejects_caller_claims_without_review_artifacts(tmp_path):
    state = {"head_sha": HEAD, "expected_head_sha": HEAD, "tests": "PASS", "verify_core": "PASS",
             "ci": "PASS", "privacy": "PASS", "p0_open": 0, "p1_material_open": 0,
             "codex_review": "APPROVED", "systemic_audit": "APPROVED", "independence_proven": True,
             "codex_independence_evidence_verified": True, "systemic_independence_evidence_verified": True,
             "external_egress_gate": "PASS", "dependency_merged": True,
             "cross_model_disagreement_material": 0}
    with pytest.raises(ValueError):
        evaluate_repository_merge_gate(tmp_path, BASE, HEAD, state, reviews=[])


def test_repository_merge_gate_rejects_forged_reviews_and_base_equal_head(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "x.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    with pytest.raises(ValueError):
        evaluate_repository_merge_gate(tmp_path, head, head, {"expected_base_sha": head}, reviews=[])


def test_repository_merge_gate_rejects_wrong_base_decoy_persisted_review_and_reused_identity(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Synthetic Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "scripts/agentic").mkdir(parents=True)
    (tmp_path / "scripts/agentic/x.py").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "scripts/agentic/x.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    state = {"expected_base_sha": base, "tests": "PASS", "verify_core": "PASS", "ci": "PASS", "privacy": "PASS",
             "p0_open": 0, "p1_material_open": 0, "dependency_merged": True,
             "cross_model_disagreement_material": 0, "external_egress_gate": "PASS"}
    forged = _review(base_sha="f" * 40, head_sha=head)
    result = evaluate_repository_merge_gate(tmp_path, base, head, state, reviews=[forged, forged, forged])
    assert result["status"] == "BLOCKED"


def test_repository_merge_gate_never_trusts_self_authored_local_review_evidence(tmp_path, monkeypatch):
    """Three coherent local identities still have the same untrusted author."""
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "producer@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Single Producer"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    (tmp_path / "scripts/agentic").mkdir(parents=True)
    (tmp_path / "scripts/agentic/gate.py").write_text("material", encoding="utf-8")
    subprocess.run(["git", "add", "scripts/agentic/gate.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    state = {"expected_base_sha": base, "tests": "PASS", "verify_core": "PASS", "ci": "PASS",
             "privacy": "PASS", "p0_open": 0, "p1_material_open": 0, "dependency_merged": True,
             "cross_model_disagreement_material": 0, "external_egress_gate": "PASS"}

    # Even if a producer supplies three apparently distinct, schema-shaped
    # reviews, repository-local evidence has no independent trust root.
    reviews = [_review(review_type=kind, base_sha=base, head_sha=head,
                       execution_id=f"forged-{index}")
               for index, kind in enumerate(("PR_REVIEW", "SYSTEMIC_AUDIT", "EXTERNAL_DIVERSITY"), 1)]
    for review in reviews:
        review["independence"]["evidence"]["checkout_head_sha"] = head
    verified_attempts = []
    import scripts.agentic.gates as gates_module
    monkeypatch.setattr(gates_module, "verify_independence_evidence",
                        lambda evidence, expected_head, root: verified_attempts.append(evidence) or ["UNTRUSTED"])
    result = evaluate_repository_merge_gate(tmp_path, base, head, state, reviews=reviews)
    assert result["status"] == "BLOCKED"
    assert "trusted_independence_authority_missing" in result["reasons"]
    assert len(verified_attempts) == 3


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
    diagnostic = evaluate_merge_gate(base)
    assert diagnostic["status"] == "BLOCKED"
    assert "trusted_merge_authority_missing" in diagnostic["reasons"]
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
