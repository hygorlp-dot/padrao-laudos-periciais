"""Build a minimal, sanitized review package manifest."""
from __future__ import annotations
import re
from pathlib import PurePosixPath

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


def build_review_package(*, issue: int, base_sha: str, head_sha: str,
                         changed_files: list[str], affected_boundaries: list[str] | None = None,
                         invariants: list[str] | None = None, adrs: list[str] | None = None,
                         schemas: list[str] | None = None, tests: list[str] | None = None,
                         test_results: dict | None = None, ci: str = "UNKNOWN",
                         privacy: str = "UNKNOWN", dependencies: list[str] | None = None,
                         sanitization_receipt: dict | None = None,
                         deploy_impact: str = "NONE", merge_base: str | None = None) -> dict:
    paths = sorted({_safe_path(path) for path in changed_files})
    receipt = sanitization_receipt or {}
    receipt_files = receipt.get("files")
    receipt_valid = (
        receipt.get("allowed") is True and receipt.get("head_sha") == head_sha
        and receipt.get("reasons") == [] and isinstance(receipt_files, list)
        and all(isinstance(item, dict) and set(item) == {"path", "sha256"} for item in receipt_files)
    )
    if not (isinstance(issue, int) and issue > 0 and SHA.fullmatch(base_sha) and SHA.fullmatch(head_sha)
            and (merge_base is None or SHA.fullmatch(merge_base))):
        raise ValueError("issue and exact SHAs are required")
    if not receipt_valid or privacy not in {"UNKNOWN", "PASS"}:
        raise ValueError("exact-head sanitization receipt is required")
    return {
        "schema_version": "1.0.0", "issue": issue, "base_sha": base_sha,
        "head_sha": head_sha, "merge_base": merge_base or base_sha,
        "changed_files": paths, "affected_boundaries": sorted(set(affected_boundaries or [])),
        "invariants": sorted(set(invariants or [])), "adrs": _safe_paths(adrs),
        "schemas": _safe_paths(schemas), "tests": _safe_paths(tests),
        "test_results": test_results or {}, "ci": ci, "privacy": "PASS",
        "dependencies": _safe_paths(dependencies), "deploy_impact": deploy_impact,
        "private_data_included": False,
        "sanitization_receipt": receipt,
    }
