"""External diversity, recovery and merge gates."""
import re
import json
import subprocess
import hashlib
from pathlib import Path
from jsonschema import Draft202012Validator
from .risk import classify_change_risk
from .review import validate_review_output
from .independence import verify_independence_evidence

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
    if not isinstance(findings, list) or any(
        not isinstance(item, dict) or item.get("severity") not in {"P0", "P1", "P2"}
        for item in findings
    ):
        return "BLOCK_INVALID_FINDINGS"
    if any(item["severity"] in {"P0", "P1"} for item in findings):
        return "REPRODUCE_TEST_FIX_REVERIFY"
    return "NO_MATERIAL_FINDING_DIAGNOSTIC_ONLY"


def evaluate_merge_gate(state: dict) -> dict:
    """Evaluate policy diagnostics without granting merge authority."""
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
    # Caller-supplied booleans are useful diagnostics but are not a trust root.
    # This public helper must never authorize a merge by itself.
    reasons.append("trusted_merge_authority_missing")
    return {"status": "BLOCKED", "reasons": sorted(set(reasons))}


def evaluate_merge_gate_for_paths(state: dict, changed_paths: list[str]) -> dict:
    """Bind the merge decision to risk derived from the actual changed paths."""
    risk = classify_change_risk(changed_paths)
    derived = evaluate_external_diversity_gate(risk["triggers"])
    bound = dict(state, claude_required=derived["claude_required"], claude_triggers=derived["triggers"])
    return evaluate_merge_gate(bound)


def evaluate_repository_merge_gate(root: Path, base_sha: str, head_sha: str, state: dict,
                                   *, reviews: list[dict]) -> dict:
    """Recompute risk, but never treat repository-local review files as authority.

    Local JSON and hashes can prove consistency and exact-HEAD binding.  They
    cannot prove that a different actor produced them, because the change
    producer can write the same files.  Until an external trust root is
    integrated, repository evidence remains auditable but cannot authorize a
    merge or establish independent review.
    """
    if not (SHA.fullmatch(base_sha) and SHA.fullmatch(head_sha) and base_sha != head_sha
            and state.get("expected_base_sha") == base_sha and (root / ".git").exists()):
        raise ValueError("exact repository SHAs are required")
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", base_sha, head_sha], cwd=root, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        changed = subprocess.check_output(["git", "diff", "--name-only", base_sha, head_sha], cwd=root, text=True).splitlines()
    except subprocess.CalledProcessError as exc:
        raise ValueError("cannot derive canonical changeset") from exc
    review_types = {"PR_REVIEW": "codex", "SYSTEMIC_AUDIT": "systemic", "EXTERNAL_DIVERSITY": "claude"}
    verified = {}
    identities = set()
    schema_path = root / "schemas/review-multiagente.schema.json"
    if not schema_path.is_file():
        schema_path = Path(__file__).resolve().parents[2] / "schemas/review-multiagente.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for review in reviews:
        semantic_findings = validate_review_output(review, expected_head=head_sha)
        local_integrity_findings = [
            item for item in semantic_findings
            if item.get("code") != "TRUSTED_INDEPENDENCE_AUTHORITY_MISSING"
        ]
        if list(Draft202012Validator(schema).iter_errors(review)) or local_integrity_findings:
            continue
        if review.get("conclusion") != "APPROVED":
            continue
        evidence = review.get("independence", {}).get("evidence", {})
        if verify_independence_evidence(evidence, head_sha, root):
            continue
        kind = review_types.get(review.get("review_type"))
        expected_role = {"codex": "PR_REVIEWER", "systemic": "SYSTEMIC_AUDITOR", "claude": "CLAUDE_EXTERNAL_DIVERSITY_REVIEWER"}.get(kind)
        try:
            execution = json.loads((root / evidence["execution_record"]).read_text(encoding="utf-8"))
            context = json.loads((root / evidence["context_record"]).read_text(encoding="utf-8"))
            checkout = json.loads((root / evidence["checkout_record"]).read_text(encoding="utf-8"))
            persisted = json.loads((root / evidence["persisted_review"]).read_text(encoding="utf-8"))
        except (OSError, KeyError, json.JSONDecodeError):
            continue
        expected_persisted = json.loads(json.dumps(review))
        expected_persisted["independence"]["evidence"].pop("persisted_review_sha256", None)
        identity = (execution.get("execution_id"), context.get("context_id"), checkout.get("worktree"), execution.get("provider_record"))
        if (review.get("base_sha") != base_sha or execution.get("role") != expected_role
                or review.get("execution_id") != execution.get("execution_id")
                or persisted != expected_persisted or identity in identities or any(not value for value in identity)):
            continue
        if kind:
            identities.add(identity)
            verified[kind] = review
    # Deliberately do not promote locally verified artifacts to independent
    # approval.  A producer can forge distinct-looking executions, contexts,
    # worktrees and hashes.  Human merge authority (or a future external,
    # cryptographically verifiable issuer) is the trust boundary.
    bound = dict(state, head_sha=head_sha, expected_head_sha=head_sha,
                 codex_review="UNTRUSTED_LOCAL_EVIDENCE" if "codex" in verified else "MISSING",
                 systemic_audit="UNTRUSTED_LOCAL_EVIDENCE" if "systemic" in verified else "MISSING",
                 codex_review_head=head_sha if "codex" in verified else None,
                 systemic_audit_head=head_sha if "systemic" in verified else None,
                 independence_proven=False,
                 codex_independence_evidence_verified=False,
                 systemic_independence_evidence_verified=False,
                 claude_review="UNTRUSTED_LOCAL_EVIDENCE" if "claude" in verified else "MISSING",
                 claude_review_head=head_sha if "claude" in verified else None,
                 claude_independence_proven=False,
                 claude_independence_evidence_verified=False)
    result = evaluate_merge_gate_for_paths(bound, changed)
    result["reasons"] = sorted(set(result["reasons"] + ["trusted_independence_authority_missing"]))
    result["status"] = "BLOCKED"
    return result
