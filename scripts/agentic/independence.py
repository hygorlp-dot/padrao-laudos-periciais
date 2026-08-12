"""Recalculate review independence from observable identifiers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


def _evidence_path(root: Path, value: str) -> Path:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("unsafe evidence path")
    resolved = (root / candidate.as_posix()).resolve()
    resolved.relative_to(root.resolve())
    return resolved


def verify_independence_evidence(evidence: dict, expected_head: str, root: Path) -> list[str]:
    reasons = []
    try:
        record_paths = [_evidence_path(root, evidence[key]) for key in
                        ("execution_record", "context_record", "checkout_record", "permissions_record", "persisted_review")]
    except (KeyError, TypeError, ValueError):
        return ["STRUCTURED_EVIDENCE_INVALID"]
    if any(not path.is_file() for path in record_paths):
        return ["EVIDENCE_RECORD_NOT_FOUND"]
    if any(not path.read_bytes() for path in (record_paths[0], record_paths[1], record_paths[3])):
        return ["EVIDENCE_RECORD_EMPTY"]
    try:
        checkout = json.loads(record_paths[2].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["CHECKOUT_RECORD_INVALID"]
    if checkout != {"head_sha": expected_head, "isolated": True, "clean": True, "read_only": True}:
        reasons.append("CHECKOUT_RECORD_NOT_PROVEN")
    digest = hashlib.sha256(record_paths[4].read_bytes()).hexdigest()
    if digest != evidence.get("persisted_review_sha256"):
        reasons.append("PERSISTED_REVIEW_HASH_MISMATCH")
    if evidence.get("checkout_head_sha") != expected_head:
        reasons.append("CHECKOUT_HEAD_NOT_PROVEN")
    return reasons


def evaluate_independence(implementer: dict, reviewer: dict, expected_head: str, *, evidence_root: Path | None = None) -> dict:
    reasons = []
    for key in ("execution_id", "context_id", "worktree"):
        if not reviewer.get(key) or reviewer.get(key) == implementer.get(key):
            reasons.append(f"{key.upper()}_NOT_INDEPENDENT")
    if reviewer.get("implementation_write_access") is not False:
        reasons.append("IMPLEMENTATION_WRITE_ACCESS")
    if reviewer.get("private_context_received") is not False:
        reasons.append("PRIVATE_CONTEXT_SHARED")
    if reviewer.get("head_sha") != expected_head:
        reasons.append("STALE_REVIEW")
    if reviewer.get("persisted_evidence") is not True:
        reasons.append("EVIDENCE_NOT_PERSISTED")
    evidence = reviewer.get("evidence")
    required = {"execution_record", "context_record", "checkout_record", "checkout_head_sha",
                "permissions_record", "persisted_review", "persisted_review_sha256"}
    if not isinstance(evidence, dict) or not required <= set(evidence):
        reasons.append("STRUCTURED_EVIDENCE_MISSING")
    else:
        if evidence.get("checkout_head_sha") != expected_head:
            reasons.append("CHECKOUT_HEAD_NOT_PROVEN")
        digest = evidence.get("persisted_review_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            reasons.append("PERSISTED_REVIEW_HASH_INVALID")
        if any(not isinstance(evidence.get(key), str) or not evidence[key].strip()
               for key in required - {"persisted_review_sha256"}):
            reasons.append("STRUCTURED_EVIDENCE_INVALID")
        if evidence_root is None:
            reasons.append("EVIDENCE_ROOT_MISSING")
        else:
            reasons.extend(verify_independence_evidence(evidence, expected_head, evidence_root))
    return {"independence_proven": not reasons, "reasons": reasons}
