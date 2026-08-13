"""Deterministic architecture-only analyzer; inspected modules are never imported."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

from .ast_inventory import module_name, parse_source
from .repository_inventory import canonical_python_path, tracked_python_inventory


def _finding(code: str, path: str, line: int, detail: str) -> dict:
    return {"analyzer": "ARCHITECTURE_ANALYZER_V1", "code": code, "severity": "P1", "canonicalPath": path, "line": line, "detail": detail, "normalizedAstSha256": hashlib.sha256(detail.encode()).hexdigest()}


def _resolve_from(node: ast.ImportFrom, source: str, package: bool) -> str:
    if not node.level:
        return node.module or ""
    parts = source.split(".") if package else source.split(".")[:-1]
    base = parts[: max(0, len(parts) - node.level + 1)]
    return ".".join(base + ([node.module] if node.module else []))


def _target_exists(target: str, modules: set[str]) -> str | None:
    current = target
    while current:
        if current in modules:
            return current
        current = current.rpartition(".")[0]
    return None


def _owner(path: str, components: list[dict]) -> tuple[str | None, bool]:
    matches = []
    for component in components:
        if any(path == prefix or path.startswith(prefix) for prefix in component["paths"]):
            matches.append(component["id"])
    return (matches[0] if len(matches) == 1 else None, len(matches) > 1)


def _cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    cycles: set[tuple[str, ...]] = set()

    def visit(node: str, stack: tuple[str, ...]):
        if node in stack:
            cycle = stack[stack.index(node):]
            rotations = [cycle[index:] + cycle[:index] for index in range(len(cycle))]
            cycles.add(min(rotations))
            return
        for target in sorted(graph.get(node, ())):
            visit(target, stack + (node,))

    for node in sorted(graph):
        visit(node, ())
    return sorted(cycles)


def analyze_sources(sources: dict[str, str], policy: dict) -> dict:
    roots = tuple(policy["productionRoots"])
    components = policy["components"]
    findings: list[dict] = []
    parsed: dict[str, tuple[str, ast.AST]] = {}
    for raw_path in sorted(sources):
        path = canonical_python_path(raw_path, roots)
        try:
            parsed[module_name(path)] = (path, parse_source(path, sources[raw_path]))
        except SyntaxError as exc:
            findings.append(_finding("ARCHITECTURE_SOURCE_PARSE_FAILURE", path, exc.lineno or 1, str(exc)))
    modules = set(parsed)
    module_rows = []
    owner_by_module: dict[str, str | None] = {}
    for module, (path, _tree) in sorted(parsed.items()):
        owner, ambiguous = _owner(path, components)
        owner_by_module[module] = owner
        module_rows.append({"module": module, "path": path, "component": owner})
        if ambiguous:
            findings.append(_finding("AMBIGUOUS_COMPONENT_OWNERSHIP", path, 1, "multiple component path matches"))
        elif owner is None:
            findings.append(_finding("UNOWNED_FIRST_PARTY_MODULE", path, 1, "no component owns source"))
    edges: set[tuple[str, str, int]] = set()
    dynamic_functions = {"__import__", "importlib.import_module", "runpy.run_module", "runpy.run_path"}
    for source, (path, tree) in sorted(parsed.items()):
        package = path.endswith("/__init__.py")
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names if alias.name == "scripts" or alias.name.startswith("scripts.")]
            elif isinstance(node, ast.ImportFrom):
                base = _resolve_from(node, source, package)
                if base == "scripts" or base.startswith("scripts."):
                    targets = [f"{base}.{alias.name}" if alias.name != "*" else base for alias in node.names]
            elif isinstance(node, ast.Call):
                func = node.func.id if isinstance(node.func, ast.Name) else None
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    func = f"{node.func.value.id}.{node.func.attr}"
                if func in dynamic_functions:
                    findings.append(_finding("DYNAMIC_ARCHITECTURE_BYPASS", path, node.lineno, ast.dump(node, include_attributes=False)))
            for target in targets:
                resolved = _target_exists(target, modules)
                if resolved is None:
                    findings.append(_finding("UNRESOLVED_FIRST_PARTY_IMPORT", path, node.lineno, target))
                elif resolved != source:
                    edges.add((source, resolved, node.lineno))
    component_by_id = {item["id"]: item for item in components}
    for source, target, line in sorted(edges):
        source_owner, target_owner = owner_by_module.get(source), owner_by_module.get(target)
        if source_owner and target_owner and source_owner != target_owner:
            allowed = set(component_by_id[source_owner].get("allowedDependencies", component_by_id[source_owner].get("allowedConsumers", [])))
            if target_owner not in allowed:
                findings.append(_finding("DISALLOWED_COMPONENT_DEPENDENCY", parsed[source][0], line, f"{source_owner}->{target_owner}"))
    graph = {module: set() for module in modules}
    for source, target, _line in edges:
        graph[source].add(target)
    for cycle in _cycles(graph):
        path = parsed[cycle[0]][0]
        findings.append(_finding("ARCHITECTURE_CYCLE", path, 1, " -> ".join(cycle + (cycle[0],))))
    return {
        "analyzer": "ARCHITECTURE_ANALYZER_V1",
        "policyVersion": policy["policyVersion"],
        "modules": module_rows,
        "edges": [{"source": s, "target": t, "line": line} for s, t, line in sorted(edges)],
        "findings": sorted(findings, key=lambda item: (item["canonicalPath"], item["line"], item["code"], item["detail"])),
    }


def analyze_repository(root: Path, policy: dict) -> dict:
    paths = tracked_python_inventory(root, tuple(policy["productionRoots"]))
    sources = {path: (root / path).read_text(encoding="utf-8") for path in paths}
    result = analyze_sources(sources, policy)
    result["inventorySha256"] = hashlib.sha256("\n".join(paths).encode()).hexdigest()
    return result


def apply_exact_baseline(root: Path, result: dict, baseline: dict) -> dict:
    commit = baseline.get("baselineCommit", "")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=root, capture_output=True)
    if ancestor.returncode:
        result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", "scripts/quality/architecture_analyzer.py", 1, "baseline is not an ancestor"))
        return result
    exceptions = baseline.get("exceptions", [])
    seen: set[tuple] = set()
    approved: set[tuple] = set()
    finding_keys = {(item["code"], item["canonicalPath"], item["line"], item["normalizedAstSha256"]) for item in result["findings"]}
    for item in exceptions:
        key = (item.get("code"), item.get("canonicalPath"), item.get("line"), item.get("normalizedAstSha256"))
        if key in seen:
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item.get("canonicalPath", "scripts/quality/architecture_analyzer.py"), 1, "duplicate exception"))
            continue
        seen.add(key)
        if key not in finding_keys:
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item.get("canonicalPath", "scripts/quality/architecture_analyzer.py"), item.get("line", 1), "stale exception without matching finding"))
            continue
        if not all(item.get(field) for field in ("owner", "justification", "disposition", "reviewBy")):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item.get("canonicalPath", "scripts/quality/architecture_analyzer.py"), item.get("line", 1), "incomplete exception evidence"))
            continue
        try:
            if date.fromisoformat(item["reviewBy"]) < date.today():
                raise ValueError("expired")
        except ValueError:
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item["canonicalPath"], item.get("line", 1), "expired or invalid review date"))
            continue
        try:
            baseline_blob = subprocess.check_output(["git", "show", f"{commit}:{item['canonicalPath']}"], cwd=root)
            current_blob = (root / item["canonicalPath"]).read_bytes()
        except (KeyError, OSError, subprocess.CalledProcessError):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item.get("canonicalPath", "scripts/quality/architecture_analyzer.py"), 1, "exception blob unavailable"))
            continue
        digest = hashlib.sha256(current_blob).hexdigest()
        if current_blob != baseline_blob or digest != item.get("wholeFileSha256"):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item["canonicalPath"], item.get("line", 1), "whole-file blob mismatch"))
            continue
        approved.add(key)
    result["findings"] = [item for item in result["findings"] if (item["code"], item["canonicalPath"], item["line"], item["normalizedAstSha256"]) not in approved]
    result["approvedDebtCount"] = len(approved)
    return result


def run_architecture_gate(root: Path) -> list[dict]:
    try:
        policy = json.loads((root / "config/architecture-policy-v1.json").read_text(encoding="utf-8"))
        baseline = json.loads((root / "config/architecture-baseline-v1.json").read_text(encoding="utf-8"))
        return apply_exact_baseline(root, analyze_repository(root, policy), baseline)["findings"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        return [_finding("ARCHITECTURE_ANALYZER_FAILURE", "scripts/quality/architecture_analyzer.py", 1, str(exc))]
