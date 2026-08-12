"""Build a minimal, sanitized review package manifest."""
from __future__ import annotations
import re
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
from .sanitize import sanitize_external_context

SHA = re.compile(r"^[0-9a-f]{40}$")


def _safe_path(value: str) -> str:
    raw = value.replace("\\", "/")
    path = PurePosixPath(raw)
    windows_absolute = len(raw) >= 3 and raw[1:3] == ":/"
    if path.is_absolute() or windows_absolute or ".." in path.parts:
        raise ValueError("unsafe review package path")
    normalized = path.as_posix()
    if normalized.casefold() == "referencias/privadas" or normalized.casefold().startswith("referencias/privadas/"):
        raise ValueError("private path cannot enter review package")
    return normalized


def _safe_paths(values: list[str] | None) -> list[str]:
    return sorted({_safe_path(value) for value in values or []})


def _path_hashes(values: list[str] | None) -> list[str]:
    return [hashlib.sha256(value.encode("utf-8")).hexdigest() for value in _safe_paths(values)]


ROOT = Path(__file__).resolve().parents[2]


def _registry_ids(filename: str, key: str) -> set[str]:
    data = json.loads((ROOT / "config" / filename).read_text(encoding="utf-8"))
    return {item["id"] for item in data[key]}


def _technical_ids(values: list[str] | None, allowed: set[str]) -> list[str]:
    result = sorted(set(values or []))
    if any(not isinstance(value, str) or value not in allowed for value in result):
        raise ValueError("only canonical technical identifiers are allowed")
    return result


def build_review_package(*, issue: int, base_sha: str, head_sha: str,
                         changed_files: list[str], affected_boundaries: list[str] | None = None,
                         invariants: list[str] | None = None, adrs: list[str] | None = None,
                         schemas: list[str] | None = None, tests: list[str] | None = None,
                         test_results: dict | None = None, ci: str = "UNKNOWN",
                         privacy: str = "UNKNOWN", dependencies: list[str] | None = None,
                         external_context: list[dict] | None = None,
                         deploy_impact: str = "NONE", merge_base: str | None = None) -> dict:
    paths = _path_hashes(changed_files)
    if not (isinstance(issue, int) and issue > 0 and SHA.fullmatch(base_sha) and SHA.fullmatch(head_sha)
            and (merge_base is None or SHA.fullmatch(merge_base))):
        raise ValueError("issue and exact SHAs are required")
    if privacy not in {"UNKNOWN", "PASS"}:
        raise ValueError("privacy is derived from first-party sanitization")
    if ci not in {"PASS", "FAIL", "UNKNOWN"} or deploy_impact not in {"NONE", "LOCAL", "PR", "RELEASE"}:
        raise ValueError("canonical status enums are required")
    result_status = (test_results or {}).get("status", "UNKNOWN")
    if set(test_results or {}) - {"status"} or result_status not in {"PASS", "FAIL", "UNKNOWN"}:
        raise ValueError("test results must contain only a canonical status")
    receipt = sanitize_external_context(external_context or [], expected_head=head_sha)
    if receipt.get("allowed") is not True:
        raise ValueError("external context failed first-party sanitization")
    return {
        "schema_version": "1.0.0", "issue": issue, "base_sha": base_sha,
        "head_sha": head_sha, "merge_base": merge_base or base_sha,
        "changed_file_hashes": paths,
        "affected_boundaries": _technical_ids(affected_boundaries, _registry_ids("core-boundaries.json", "boundaries")),
        "invariants": _technical_ids(invariants, _registry_ids("core-invariants.json", "invariants")),
        "schema_path_hashes": _path_hashes(schemas), "test_path_hashes": _path_hashes(tests),
        "test_results": {"status": result_status}, "ci": ci, "privacy": "PASS",
        "dependency_path_hashes": _path_hashes(dependencies), "deploy_impact": deploy_impact,
        "private_data_included": False,
        "sanitization_receipt": receipt,
    }
