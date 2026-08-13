"""Validação e execução isolada do corpus histórico de mutações críticas."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_BASE_SHA = "15e77be13fa5aae96325d20fab322809e40e816f"
CRITICAL_MUTANTS = frozenset(f"MUT-{number:03d}" for number in range(1, 11))


def _finding(code: str, bug_id: str, detail: str) -> dict:
    return {"code": code, "bug_id": bug_id, "detail": detail, "severity": "P1"}


def _node_path(reference: str) -> str:
    return reference.split("::", 1)[0]


def validate_historical_registry(registry: dict, root: Path) -> list[dict]:
    findings: list[dict] = []
    if registry.get("schema_version") != "1.0.0" or registry.get("core_base_sha") != EXPECTED_BASE_SHA:
        findings.append(_finding("QUALITY_CONFIG_STALE", "REGISTRY", "schema/base divergente"))
    bugs = registry.get("bugs")
    if not isinstance(bugs, list) or not bugs:
        return findings + [_finding("HISTORICAL_REGISTRY_EMPTY", "REGISTRY", "bugs ausentes")]
    seen_ids: set[str] = set()
    seen_mutants: set[str] = set()
    for bug in bugs:
        bug_id = bug.get("id", "SEM_ID")
        if bug_id in seen_ids:
            findings.append(_finding("HISTORICAL_BUG_DUPLICATE", bug_id, "id duplicado"))
        seen_ids.add(bug_id)
        tests = bug.get("regression_tests") or []
        if not tests:
            findings.append(_finding("HISTORICAL_BUG_WITHOUT_REGRESSION", bug_id, "teste ausente"))
        for test in tests:
            if not (root / _node_path(test)).is_file():
                findings.append(_finding("HISTORICAL_TEST_NOT_FOUND", bug_id, test))
        mutant = bug.get("mutation_equivalent")
        if not mutant:
            findings.append(_finding("HISTORICAL_BUG_WITHOUT_MUTATION", bug_id, "mutante ausente"))
        else:
            seen_mutants.add(mutant)
        if not bug.get("boundary") or not bug.get("invariants"):
            findings.append(_finding("HISTORICAL_TRACEABILITY_MISSING", bug_id, "boundary/invariante ausente"))
    missing = CRITICAL_MUTANTS - seen_mutants
    if missing:
        findings.append(_finding("HISTORICAL_CRITICAL_MUTANTS_MISSING", "REGISTRY", ",".join(sorted(missing))))
    return findings


def load_registry(root: Path) -> dict:
    return json.loads((root / "config" / "historical-bugs.json").read_text(encoding="utf-8"))


def load_mutants(root: Path) -> list[dict]:
    return json.loads((root / "config" / "historical-mutants.json").read_text(encoding="utf-8"))["mutants"]


def validate_mutant_definitions(mutants: list[dict], root: Path) -> list[dict]:
    findings: list[dict] = []
    for mutant in mutants:
        mutant_id = mutant.get("id", "SEM_ID")
        source = root / str(mutant.get("source", ""))
        if not source.is_file():
            findings.append(_finding("MUTATION_SOURCE_NOT_FOUND", mutant_id, str(source)))
            continue
        text = source.read_text(encoding="utf-8")
        if not mutant.get("search") or text.count(mutant["search"]) != 1 or mutant.get("replacement") == mutant.get("search"):
            findings.append(_finding("MUTATION_SEARCH_NOT_UNIQUE", mutant_id, mutant.get("search", "")))
        test_path = str(mutant.get("test", "")).split(" ", 1)[0]
        if not (root / test_path).is_file():
            findings.append(_finding("MUTATION_TEST_NOT_FOUND", mutant_id, test_path))
    return findings


def _copy_workspace(root: Path, target: Path) -> None:
    ignored = shutil.ignore_patterns(".*", "*-temp", "*-temp-*", "venv", "__pycache__", "referencias")
    shutil.copytree(root, target, ignore=ignored, dirs_exist_ok=True)


def execute_historical_suite(root: Path, *, mutants: list[dict] | None = None, timeout: int = 30) -> dict:
    definitions = mutants if mutants is not None else load_mutants(root)
    invalid = [item["bug_id"] for item in validate_mutant_definitions(definitions, root)]
    if invalid:
        return {"total": len(definitions), "killed": 0, "survived": [], "invalid": sorted(set(invalid)), "results": []}
    killed: list[str] = []
    survived: list[str] = []
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="historical-mutations-") as temporary:
        sandbox = Path(temporary) / "repo"
        _copy_workspace(root, sandbox)
        for mutant in definitions:
            source = sandbox / mutant["source"]
            original = source.read_text(encoding="utf-8")
            source.write_text(original.replace(mutant["search"], mutant["replacement"], 1), encoding="utf-8", newline="\n")
            for cache in sandbox.rglob("__pycache__"):
                shutil.rmtree(cache, ignore_errors=True)
            command = [sys.executable, "-m", "pytest", "-q", *mutant["test"].split()]
            try:
                completed = subprocess.run(command, cwd=sandbox, capture_output=True, text=True, timeout=timeout)
                status = "KILLED" if completed.returncode != 0 else "SURVIVED"
                (killed if status == "KILLED" else survived).append(mutant["id"])
                results.append({"id": mutant["id"], "status": status, "test": mutant["test"], "exit_code": completed.returncode})
            except subprocess.TimeoutExpired:
                results.append({"id": mutant["id"], "status": "INVALID", "test": mutant["test"], "exit_code": None})
                invalid.append(mutant["id"])
            finally:
                source.write_text(original, encoding="utf-8", newline="\n")
    return {"total": len(definitions), "killed": len(killed), "survived": sorted(survived), "invalid": sorted(set(invalid)), "results": results}
