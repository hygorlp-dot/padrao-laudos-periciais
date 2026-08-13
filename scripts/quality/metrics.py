"""Métricas first-party de cobertura e complexidade para non-regression."""
from __future__ import annotations

import ast
import math
from pathlib import Path


BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Match, ast.comprehension)
REQUIRED_PERFORMANCE_COMPONENTS = frozenset({"architecture", "historical critical mutation suite", "regression"})
MAX_PERFORMANCE_COMPONENT_SECONDS = {
    "architecture": 15.0,
    "historical critical mutation suite": 20.0,
    "regression": 45.0,
}


def _function_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    complexity = 1
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, BRANCH_NODES):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(1, len(child.values) - 1)
        elif isinstance(child, ast.Try):
            complexity += len(child.handlers) + bool(child.orelse) + bool(child.finalbody)
    return complexity


def analyze_complexity(paths: list[Path], *, base: Path) -> list[dict]:
    results: list[dict] = []
    for path in sorted(set(paths)):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.resolve().relative_to(base.resolve()).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                results.append({"path": relative, "function": node.name, "complexity": _function_complexity(node),
                                "line": node.lineno, "length": (getattr(node, "end_lineno", node.lineno) - node.lineno + 1)})
    return sorted(results, key=lambda item: (-item["complexity"], -item["length"], item["path"], item["function"]))


def parse_coverage_totals(report: dict) -> dict:
    totals = report["totals"]
    line = 100.0 * totals["covered_lines"] / totals["num_statements"] if totals["num_statements"] else 100.0
    branch = 100.0 * totals["covered_branches"] / totals["num_branches"] if totals["num_branches"] else 100.0
    return {"line_percent": round(line, 3), "branch_percent": round(branch, 3)}


def validate_quality_baseline(
    baseline: dict,
    coverage: dict | None,
    complexity: list[dict],
    *,
    duration_seconds: float | None = None,
    component_durations: dict[str, float] | None = None,
) -> list[dict]:
    findings: list[dict] = []
    if coverage is None:
        findings.append({"code": "COVERAGE_MEASUREMENT_MISSING", "severity": "P1"})
    else:
        for key, code in (("line_percent", "COVERAGE_LINE_REGRESSION"), ("branch_percent", "COVERAGE_BRANCH_REGRESSION")):
            if float(coverage.get(key, 0)) < float(baseline.get("coverage", {}).get(key, 0)):
                findings.append({"code": code, "severity": "P1", "expected": baseline["coverage"][key], "actual": coverage.get(key)})
    current = {(item["path"], item["function"]): item["complexity"] for item in complexity}
    for expected in baseline.get("hotspots", []):
        key = (expected["path"], expected["function"])
        if key not in current or current[key] > expected["complexity"]:
            findings.append({"code": "HOTSPOT_COMPLEXITY_REGRESSION", "severity": "P1", "expected": expected, "actual": current.get(key)})
    budgets = baseline.get("performance_component_max_seconds")
    if component_durations is not None:
        if (not isinstance(budgets, dict) or set(budgets) != REQUIRED_PERFORMANCE_COMPONENTS
                or any(type(value) not in {int, float} or not math.isfinite(value) or value <= 0
                       or value > MAX_PERFORMANCE_COMPONENT_SECONDS[name] for name, value in budgets.items())
                or not REQUIRED_PERFORMANCE_COMPONENTS <= set(component_durations)
                or any(type(component_durations[name]) not in {int, float}
                       or not math.isfinite(component_durations[name]) or component_durations[name] < 0
                       for name in REQUIRED_PERFORMANCE_COMPONENTS)):
            findings.append({"code": "PERFORMANCE_COMPONENT_BUDGET_INVALID", "severity": "P1"})
        else:
            for component in sorted(REQUIRED_PERFORMANCE_COMPONENTS):
                actual, limit = float(component_durations[component]), float(budgets[component])
                if actual > limit:
                    findings.append({"code": "GATE_COMPONENT_DURATION_REGRESSION", "severity": "P1",
                                     "component": component, "expected": limit, "actual": actual})
    return findings


def validate_complexity_baseline(baseline: dict, complexity: list[dict]) -> list[dict]:
    return [
        item for item in validate_quality_baseline(baseline, baseline.get("coverage", {}), complexity)
        if item["code"] == "HOTSPOT_COMPLEXITY_REGRESSION"
    ]
