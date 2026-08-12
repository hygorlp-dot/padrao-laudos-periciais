"""Build a minimal, sanitized review package manifest."""
from __future__ import annotations
import re
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


def build_review_package(*, issue: int, base_sha: str, head_sha: str,
                         changed_files: list[str], affected_boundaries: list[str] | None = None,
                         invariants: list[str] | None = None, adrs: list[str] | None = None,
                         schemas: list[str] | None = None, tests: list[str] | None = None,
                         test_results: dict | None = None, ci: str = "UNKNOWN",
                         privacy: str = "UNKNOWN", dependencies: list[str] | None = None,
                         external_context: list[dict] | None = None,
                         deploy_impact: str = "NONE", merge_base: str | None = None) -> dict:
    paths = sorted({_safe_path(path) for path in changed_files})
    if not (isinstance(issue, int) and issue > 0 and SHA.fullmatch(base_sha) and SHA.fullmatch(head_sha)
            and (merge_base is None or SHA.fullmatch(merge_base))):
        raise ValueError("issue and exact SHAs are required")
    if privacy not in {"UNKNOWN", "PASS"}:
        raise ValueError("privacy is derived from first-party sanitization")
    receipt = sanitize_external_context(external_context or [], expected_head=head_sha)
    if receipt.get("allowed") is not True:
        raise ValueError("external context failed first-party sanitization")
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
