"""Fail-closed exact baseline exception matching for capability findings."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import jsonschema

from scripts.quality.ast_inventory import module_name


def _git(repo: Path, *args: str, text: bool = True):
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=text)
    if completed.returncode:
        raise RuntimeError("Git object unavailable")
    return completed.stdout


def _key_from_finding(item: dict) -> tuple:
    return (
        item.get("code"), item.get("canonicalPath"), item.get("module"),
        item.get("location", {}).get("line"), item.get("location", {}).get("column"),
        item.get("normalizedAstSha256"), item.get("policyVersion"), item.get("analyzer"),
    )


def _key_from_exception(item: dict) -> tuple:
    return (
        item.get("findingCode"), item.get("canonicalPath"), item.get("module"),
        item.get("acquisitionLocation", {}).get("line"), item.get("acquisitionLocation", {}).get("column"),
        item.get("normalizedAcquisitionAstSha256"), item.get("policyVersion"),
        "CAPABILITY_ANALYZER_V1" if item.get("analyzerVersion") == "1.0.0" else None,
    )


def apply_exact_exceptions(
    repo: Path,
    findings: list[dict],
    protected_baseline: str,
    candidate: str,
    *,
    registry_path: str,
    schema_path: Path,
    now: date,
) -> list[dict]:
    """Suppress only exact findings authorized by an unchanged ancestor registry."""
    original = list(findings)
    try:
        if _git(repo, "merge-base", "--is-ancestor", protected_baseline, candidate).strip():
            return original
        baseline_raw = _git(repo, "show", f"{protected_baseline}:{registry_path}")
        candidate_raw = _git(repo, "show", f"{candidate}:{registry_path}")
        if baseline_raw != candidate_raw:
            return original
        registry = json.loads(baseline_raw)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(registry, dict) or set(registry) != {"schemaVersion", "exceptions"}:
            return original
        if registry.get("schemaVersion") != "1.0.0" or not isinstance(registry.get("exceptions"), list):
            return original
        rows = registry["exceptions"]
        keys = [_key_from_exception(row) for row in rows if isinstance(row, dict)]
        if len(keys) != len(rows) or len(keys) != len(set(keys)):
            return original
        finding_keys = {_key_from_finding(item) for item in original}
        approved: set[tuple] = set()
        for row, key in zip(rows, keys):
            jsonschema.validate(row, schema)
            if key not in finding_keys or row["ruleVersion"] != "1.0.0":
                return original
            if module_name(row["canonicalPath"]) != row["module"]:
                return original
            if date.fromisoformat(row["reviewBy"]) < now:
                return original
            source_commit = row["baselineCommit"]
            if _git(repo, "merge-base", "--is-ancestor", source_commit, protected_baseline).strip():
                return original
            baseline_blob = _git(repo, "show", f"{source_commit}:{row['canonicalPath']}", text=False)
            candidate_blob = _git(repo, "show", f"{candidate}:{row['canonicalPath']}", text=False)
            if baseline_blob != candidate_blob or hashlib.sha256(candidate_blob).hexdigest() != row["wholeFileSha256"]:
                return original
            approved.add(key)
        return [item for item in original if _key_from_finding(item) not in approved]
    except (
        OSError, RuntimeError, UnicodeError, ValueError, TypeError, KeyError,
        json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError,
    ):
        return original
