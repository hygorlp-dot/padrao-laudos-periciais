"""Métricas first-party de cobertura e complexidade para non-regression."""
from __future__ import annotations

import ast
import math
from pathlib import Path


BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Match, ast.comprehension)
# Politica temporal hibrida (V7-4, decisao humana "2-III" registrada na #256).
# A mesma evidencia tem a mesma leitura em PR e em main: dentro da referencia
# passa; acima dela a duracao sozinha nao prova regressao do candidato (o runner
# varia), entao o gate exige atribuicao BASE x HEAD no mesmo runner, feita por
# `scripts.quality.timing_attribution`. Evidencia invalida falha fechada sempre.
TIMING_POLICY_HYBRID = "HYBRID"
TIMING_STATUS_ATTRIBUTION_REQUIRED = "ATTRIBUTION_REQUIRED"
_TIMING_POLICIES = {TIMING_POLICY_HYBRID}


def _timing_policy(explicit: str | None) -> str | None:
    if explicit is not None:
        return explicit if explicit in _TIMING_POLICIES else None
    return TIMING_POLICY_HYBRID


def _emit_timing(target: float | None, observed: float | None, status: str) -> None:
    print(f"TARGET_SECONDS = {target if target is not None else 'INVALID'}")
    print(f"OBSERVED_SECONDS = {observed if observed is not None else 'INVALID'}")
    print(f"TIMING_STATUS = {status}")


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
    timing_policy: str | None = None,
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
    if duration_seconds is None and timing_policy is None:
        return findings

    policy = _timing_policy(timing_policy)
    try:
        limit = float(baseline["full_gate_max_seconds"])
        duration = float(duration_seconds) if duration_seconds is not None else None
    except (KeyError, TypeError, ValueError):
        limit = None
        duration = None

    evidence_valid = (
        policy is not None
        and limit is not None
        and duration is not None
        and math.isfinite(limit)
        and math.isfinite(duration)
        and limit > 0
        and duration >= 0
    )
    if not evidence_valid:
        _emit_timing(limit if limit is not None and math.isfinite(limit) else None,
                     duration if duration is not None and math.isfinite(duration) else None, "INVALID")
        findings.append({
            "code": "TIMING_EVIDENCE_INVALID",
            "severity": "P1",
            "expected": baseline.get("full_gate_max_seconds"),
            "actual": duration_seconds,
            "policy": timing_policy,
        })
        return findings

    if duration > limit:
        # Nao e aprovacao: o passo de atribuicao do workflow e obrigatorio e bloqueia
        # regressao material do candidato (ou evidencia ausente) contra a BASE.
        _emit_timing(limit, duration, TIMING_STATUS_ATTRIBUTION_REQUIRED)
    else:
        _emit_timing(limit, duration, "PASS")
    return findings


def validate_complexity_baseline(baseline: dict, complexity: list[dict]) -> list[dict]:
    return [
        item for item in validate_quality_baseline(baseline, baseline.get("coverage", {}), complexity)
        if item["code"] == "HOTSPOT_COMPLEXITY_REGRESSION"
    ]
