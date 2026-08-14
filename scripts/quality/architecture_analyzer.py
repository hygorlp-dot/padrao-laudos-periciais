"""Deterministic architecture-only analyzer; inspected modules are never imported."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from datetime import date
from pathlib import Path

import jsonschema

from .ast_inventory import module_name, parse_source
from .repository_inventory import candidate_tree, canonical_python_path, tree_python_sources


PROTECTED_ARCHITECTURE_ARTIFACTS = (
    ".github/workflows/architecture-protected.yml",
    "config/architecture-policy-v1.json",
    "schemas/architecture-baseline-v1.schema.json",
    "scripts/quality/architecture_analyzer.py",
    "scripts/quality/ast_inventory.py",
    "scripts/quality/repository_inventory.py",
)


def _protected_artifact_findings(root: Path, protected_base: str, candidate: str) -> list[dict]:
    findings = []
    for path in PROTECTED_ARCHITECTURE_ARTIFACTS:
        def blob(commit: str) -> str | None:
            result = subprocess.run(
                ["git", "rev-parse", f"{commit}:{path}"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip() if result.returncode == 0 else None

        base_blob = blob(protected_base)
        candidate_blob = blob(candidate)
        if base_blob != candidate_blob:
            findings.append(_finding(
                "ARCHITECTURE_PROTECTED_ARTIFACT_MISMATCH",
                path,
                1,
                "candidate enforcement artifact differs from protected base",
            ))
    return findings


def _finding(code: str, path: str, line: int, detail: str) -> dict:
    return {"analyzer": "ARCHITECTURE_ANALYZER_V1", "code": code, "severity": "P1", "canonicalPath": path, "line": line, "detail": detail, "normalizedAstSha256": hashlib.sha256(detail.encode()).hexdigest()}


def _resolve_from(node: ast.ImportFrom, source: str, package: bool) -> str:
    if not node.level:
        return node.module or ""
    parts = source.split(".") if package else source.split(".")[:-1]
    remove = node.level - 1
    if remove > len(parts):
        raise ValueError("relative import beyond top-level package")
    base = parts[: len(parts) - remove] if remove else parts
    return ".".join(base + ([node.module] if node.module else []))


def _target_exists(target: str, modules: set[str], *, import_from: bool = False) -> str | None:
    if target in modules:
        return target
    if import_from:
        parent = target.rpartition(".")[0]
        if parent in modules:
            return parent
    return None


def _owner(path: str, components: list[dict]) -> tuple[str | None, bool]:
    matches = []
    for component in components:
        if any(path == prefix or path.startswith(prefix) for prefix in component["paths"]):
            matches.append(component["id"])
    return (matches[0] if len(matches) == 1 else None, len(matches) > 1)


def _cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    nodes = set(graph)
    for targets in graph.values():
        nodes.update(targets)
    visited: set[str] = set()
    order: list[str] = []
    for start in sorted(nodes):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(sorted(graph.get(start, ())))) ]
        while stack:
            node, targets = stack[-1]
            try:
                target = next(targets)
            except StopIteration:
                order.append(node); stack.pop(); continue
            if target not in visited:
                visited.add(target); stack.append((target, iter(sorted(graph.get(target, ())))))
    reverse = {node: set() for node in nodes}
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    visited.clear(); components: list[tuple[str, ...]] = []
    for start in reversed(order):
        if start in visited:
            continue
        component: list[str] = []; stack = [start]; visited.add(start)
        while stack:
            node = stack.pop(); component.append(node)
            for target in sorted(reverse[node], reverse=True):
                if target not in visited:
                    visited.add(target); stack.append(target)
        if len(component) > 1 or start in graph.get(start, set()):
            components.append(tuple(sorted(component)))
    return sorted(components)


def _attribute_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr); node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id); return ".".join(reversed(parts))
    return None


def _resolve_binding(node: ast.AST, bindings: dict[str, str]) -> str | None:
    dotted = _attribute_name(node)
    if dotted is not None:
        if dotted in bindings:
            return bindings[dotted]
        root, separator, remainder = dotted.partition(".")
        resolved = bindings.get(root, root)
        return f"{resolved}.{remainder}" if separator else resolved
    if isinstance(node, ast.Attribute):
        owner = _resolve_binding(node.value, bindings)
        if owner:
            return f"{owner}.{node.attr}"
        if node.attr in {"exec_module", "load_module"}:
            return f"dynamic.loader.{node.attr}"
    if isinstance(node, ast.Subscript):
        owner = _resolve_binding(node.value, bindings)
        member = _constant_string(node.slice)
        namespace = owner.removesuffix(".__dict__") if owner else None
        if namespace in {"__builtins__", "builtins", "globals.__builtins__"} and member == "__import__":
            return "builtins.__import__"
        if namespace in {"importlib", "runpy"} and member in {"import_module", "run_module", "run_path"}:
            return f"{namespace}.{member}"
        if owner == "globals" and member == "__builtins__":
            return "globals.__builtins__"
        if owner == "sys.modules" and member == "importlib":
            return "importlib"
        if owner and member:
            return f"{owner}.{member}"
    if isinstance(node, ast.Call):
        function = _resolve_binding(node.func, bindings)
        if function == "globals" and not node.args:
            return "globals"
        if function in {"getattr", "vars"} and node.args:
            owner = _resolve_binding(node.args[0], bindings)
            if function == "vars" and owner:
                return f"{owner}.__dict__"
            member = _constant_string(node.args[1]) if len(node.args) >= 2 else None
            if owner and member:
                return f"{owner}.{member}"
        if function and function.endswith(".__getattribute__") and node.args:
            member = _constant_string(node.args[0])
            if member:
                return f"{function.removesuffix('.__getattribute__')}.{member}"
        if function == "operator.attrgetter" and node.args:
            member = _constant_string(node.args[0])
            if member:
                return f"operator.attrgetter:{member}"
        if function and function.startswith("operator.attrgetter:") and node.args:
            owner = _resolve_binding(node.args[0], bindings)
            if owner:
                return f"{owner}.{function.partition(':')[2]}"
    return None


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _constant_string(node.left), _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _protected_namespace_reflection(node: ast.AST, bindings: dict[str, str]) -> bool:
    protected = {"builtins", "importlib", "runpy"}
    if isinstance(node, ast.Attribute) and node.attr == "__dict__":
        owner = _resolve_binding(node.value, bindings)
        return bool(owner and owner.split(".", 1)[0] in protected)
    if isinstance(node, ast.Call) and _resolve_binding(node.func, bindings) in {"getattr", "vars"} and node.args:
        owner = _resolve_binding(node.args[0], bindings)
        if owner and owner.split(".", 1)[0] in protected:
            return True
        return _protected_namespace_reflection(node.args[0], bindings)
    if isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)):
        return any(_protected_namespace_reflection(child, bindings) for child in ast.iter_child_nodes(node))
    return False


def _protected_binding(node: ast.AST, bindings: dict[str, str]) -> str | None:
    if _protected_namespace_reflection(node, bindings):
        return "dynamic.protected_namespace_reflection"
    if (isinstance(node, ast.Call) and _resolve_binding(node.func, bindings) == "getattr"
            and len(node.args) >= 2):
        owner = _resolve_binding(node.args[0], bindings)
        member = _constant_string(node.args[1])
        reflected = f"{owner}.{member}" if owner and member else None
        if reflected in {"builtins.__import__", "importlib.import_module", "runpy.run_module", "runpy.run_path"}:
            return reflected
    if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Call)
            and _resolve_binding(node.value.func, bindings) == "vars" and node.value.args):
        owner = _resolve_binding(node.value.args[0], bindings)
        member = _constant_string(node.slice)
        reflected = f"{owner}.{member}" if owner and member else None
        if reflected in {"builtins.__import__", "importlib.import_module", "runpy.run_module", "runpy.run_path"}:
            return reflected
    for part in ast.walk(node):
        resolved = _resolve_binding(part, bindings)
        if resolved and (resolved in {"builtins.__import__", "importlib.import_module", "runpy.run_module", "runpy.run_path"} or resolved.endswith((".exec_module", ".load_module")) or resolved.startswith(("sys.meta_path", "sys.path_hooks"))):
            return resolved
    return None


def _binding_targets(node: ast.AST) -> list[str]:
    dotted = _attribute_name(node)
    if dotted:
        return [dotted]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [item for child in node.elts for item in _binding_targets(child)]
    return []


def analyze_sources(sources: dict[str, str], policy: dict) -> dict:
    if policy.get("policyVersion") != "1.0.0" or not isinstance(policy.get("components"), list):
        raise ValueError("architecture policy invalid")
    layers = {item.get("layer") for item in policy["components"]}
    if None in layers or not layers <= set(policy.get("allowedLayerDependencies", {})):
        raise ValueError("architecture layer policy incomplete")
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
        bindings: dict[str, str] = {"__import__": "builtins.__import__"}
        ordered_nodes = sorted(ast.walk(tree), key=lambda item: (getattr(item, "lineno", 0), getattr(item, "col_offset", 0)))
        for node in ordered_nodes:
            if isinstance(node, ast.Import):
                for alias in node.names: bindings[alias.asname or alias.name.split(".")[0]] = alias.name
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*": bindings[alias.asname or alias.name] = f"{node.module or ''}.{alias.name}".strip(".")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                protected = _protected_binding(node, bindings)
                if protected:
                    bindings[node.name] = protected
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                resolved = (_resolve_binding(value, bindings) or _protected_binding(value, bindings)) if value is not None else None
                for target in targets:
                    for name in _binding_targets(target):
                        if resolved:
                            bindings[name] = resolved
                        else:
                            bindings.pop(name, None)
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names if alias.name == "scripts" or alias.name.startswith("scripts.")]
            elif isinstance(node, ast.ImportFrom):
                try: base = _resolve_from(node, source, package)
                except ValueError as exc:
                    findings.append(_finding("INVALID_RELATIVE_IMPORT", path, node.lineno, str(exc))); continue
                if base == "scripts" or base.startswith("scripts."):
                    targets = [f"{base}.{alias.name}" if alias.name != "*" else base for alias in node.names]
            elif isinstance(node, ast.Call):
                func = _resolve_binding(node.func, bindings) or _protected_binding(node.func, bindings)
                if func in dynamic_functions or func == "builtins.__import__" or (func and func.endswith((".exec_module", ".load_module", ".protected_namespace_reflection"))) or (func and func.startswith(("sys.meta_path.", "sys.path_hooks."))):
                    findings.append(_finding("DYNAMIC_ARCHITECTURE_BYPASS", path, node.lineno, ast.dump(node, include_attributes=False)))
            for target in targets:
                resolved = _target_exists(target, modules, import_from=isinstance(node, ast.ImportFrom))
                if resolved is None:
                    findings.append(_finding("UNRESOLVED_FIRST_PARTY_IMPORT", path, node.lineno, target))
                elif resolved != source:
                    edges.add((source, resolved, node.lineno))
    component_by_id = {item["id"]: item for item in components}
    allowed_layers = {key: set(value) for key, value in policy["allowedLayerDependencies"].items()}
    for source, target, line in sorted(edges):
        source_owner, target_owner = owner_by_module.get(source), owner_by_module.get(target)
        if source_owner and target_owner and source_owner != target_owner:
            allowed = set(component_by_id[source_owner].get("allowedDependencies", component_by_id[source_owner].get("allowedConsumers", [])))
            if target_owner not in allowed:
                findings.append(_finding("DISALLOWED_COMPONENT_DEPENDENCY", parsed[source][0], line, f"{source_owner}->{target_owner}"))
            source_layer, target_layer = component_by_id[source_owner]["layer"], component_by_id[target_owner]["layer"]
            if target_layer not in allowed_layers.get(source_layer, set()):
                findings.append(_finding("DISALLOWED_LAYER_DEPENDENCY", parsed[source][0], line, f"{source_layer}->{target_layer}"))
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


def analyze_repository(root: Path, policy: dict, candidate: str = "HEAD", expected_tree: str | None = None) -> dict:
    commit, tree = candidate_tree(root, candidate, expected_tree=expected_tree)
    sources = tree_python_sources(root, tree, tuple(policy["productionRoots"]))
    result = analyze_sources(sources, policy)
    result.update(candidateCommitSha=commit, candidateTreeSha=tree)
    result["inventorySha256"] = hashlib.sha256("\n".join(f"{path}\0{hashlib.sha256(text.encode()).hexdigest()}" for path, text in sources.items()).encode()).hexdigest()
    return result


def apply_exact_baseline(root: Path, result: dict, baseline: dict, *, protected_base: str | None = None) -> dict:
    commit = baseline.get("baselineCommit", "")
    candidate = result.get("candidateCommitSha", "HEAD")
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", commit, candidate], cwd=root, capture_output=True)
    if ancestor.returncode:
        result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", "scripts/quality/architecture_analyzer.py", 1, "baseline is not an ancestor"))
        return result
    try:
        if protected_base:
            protected_registry = json.loads(subprocess.check_output(["git", "show", f"{protected_base}:config/architecture-baseline-v1.json"], cwd=root, text=True))
            if commit not in {protected_base, protected_registry.get("baselineCommit")}:
                result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", "config/architecture-baseline-v1.json", 1, "baseline is not authorized by protected base")); return result
        candidate_baseline = json.loads(subprocess.check_output(["git", "show", f"{candidate}:config/architecture-baseline-v1.json"], cwd=root, text=True))
        artifact_source = protected_base or candidate
        schema_blob = subprocess.check_output(["git", "show", f"{artifact_source}:schemas/architecture-baseline-v1.schema.json"], cwd=root)
        jsonschema.validate(baseline, json.loads(schema_blob))
        if candidate_baseline != baseline:
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", "config/architecture-baseline-v1.json", 1, "baseline does not match exact candidate blob")); return result
        policy_blob = subprocess.check_output(["git", "show", f"{artifact_source}:config/architecture-policy-v1.json"], cwd=root)
    except (jsonschema.ValidationError, jsonschema.SchemaError, json.JSONDecodeError) as exc:
        result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", "config/architecture-baseline-v1.json", 1, f"schema validation failed: {exc.message}")); return result
    except subprocess.CalledProcessError:
        result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", "scripts/quality/architecture_analyzer.py", 1, "protected baseline artifact unavailable")); return result
    if baseline.get("policyVersion") != result.get("policyVersion") or baseline.get("policySha256") != hashlib.sha256(policy_blob).hexdigest():
        result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", "scripts/quality/architecture_analyzer.py", 1, "policy identity mismatch")); return result
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
        try:
            baseline_registry = json.loads(subprocess.check_output(["git", "show", f"{commit}:config/architecture-baseline-v1.json"], cwd=root, text=True))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item["canonicalPath"], item.get("line", 1), "exception registry did not preexist in baseline")); continue
        if item not in baseline_registry.get("exceptions", []):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item["canonicalPath"], item.get("line", 1), "exception did not preexist in baseline")); continue
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
            current_blob = subprocess.check_output(["git", "show", f"{candidate}:{item['canonicalPath']}"], cwd=root)
        except (KeyError, subprocess.CalledProcessError):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item.get("canonicalPath", "scripts/quality/architecture_analyzer.py"), 1, "exception blob unavailable"))
            continue
        digest = hashlib.sha256(current_blob).hexdigest()
        if current_blob != baseline_blob or digest != item.get("wholeFileSha256"):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item["canonicalPath"], item.get("line", 1), "whole-file blob mismatch"))
            continue
        owner_by_path = {row["path"]: row["component"] for row in result.get("modules", [])}
        if item.get("owner") != owner_by_path.get(item["canonicalPath"]) or item.get("disposition") not in baseline.get("allowedDispositions", []):
            result["findings"].append(_finding("ARCHITECTURE_BASELINE_INVALID", item["canonicalPath"], item.get("line", 1), "owner or disposition mismatch"))
            continue
        approved.add(key)
    result["findings"] = [item for item in result["findings"] if (item["code"], item["canonicalPath"], item["line"], item["normalizedAstSha256"]) not in approved]
    result["approvedDebtCount"] = len(approved)
    return result


def run_architecture_gate(root: Path, candidate: str = "HEAD") -> list[dict]:
    try:
        commit, tree = candidate_tree(root, candidate)
        expected = os.environ.get("ARCHITECTURE_EXPECTED_HEAD_SHA")
        if expected and commit != expected:
            return [_finding("ARCHITECTURE_ANALYZER_FAILURE", "scripts/quality/architecture_analyzer.py", 1, "candidate does not match exact expected head")]
        baseline = json.loads(subprocess.check_output(["git", "show", f"{commit}:config/architecture-baseline-v1.json"], cwd=root, text=True))
        protected_base = os.environ.get("ARCHITECTURE_PROTECTED_BASE_SHA") or None
        if protected_base:
            protected_findings = _protected_artifact_findings(root, protected_base, commit)
            if protected_findings:
                return protected_findings
        policy_source = protected_base or commit
        policy = json.loads(subprocess.check_output(["git", "show", f"{policy_source}:config/architecture-policy-v1.json"], cwd=root, text=True))
        return apply_exact_baseline(root, analyze_repository(root, policy, commit, tree), baseline, protected_base=protected_base)["findings"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        return [_finding("ARCHITECTURE_ANALYZER_FAILURE", "scripts/quality/architecture_analyzer.py", 1, str(exc))]
