"""Build a minimal, sanitized review package manifest."""
from __future__ import annotations


def build_review_package(*, issue: int, base_sha: str, head_sha: str,
                         changed_files: list[str], affected_boundaries: list[str] | None = None,
                         invariants: list[str] | None = None, adrs: list[str] | None = None,
                         schemas: list[str] | None = None, tests: list[str] | None = None,
                         test_results: dict | None = None, ci: str = "UNKNOWN",
                         privacy: str = "UNKNOWN", dependencies: list[str] | None = None,
                         deploy_impact: str = "NONE", merge_base: str | None = None) -> dict:
    paths = sorted({path.replace("\\", "/") for path in changed_files})
    if any(path.startswith("referencias/privadas/") for path in paths):
        raise ValueError("private path cannot enter review package")
    if not (isinstance(issue, int) and issue > 0 and len(base_sha) == 40 and len(head_sha) == 40):
        raise ValueError("issue and exact SHAs are required")
    return {
        "schema_version": "1.0.0", "issue": issue, "base_sha": base_sha,
        "head_sha": head_sha, "merge_base": merge_base or base_sha,
        "changed_files": paths, "affected_boundaries": sorted(set(affected_boundaries or [])),
        "invariants": sorted(set(invariants or [])), "adrs": sorted(set(adrs or [])),
        "schemas": sorted(set(schemas or [])), "tests": sorted(set(tests or [])),
        "test_results": test_results or {}, "ci": ci, "privacy": privacy,
        "dependencies": sorted(set(dependencies or [])), "deploy_impact": deploy_impact,
        "private_data_included": False,
    }
