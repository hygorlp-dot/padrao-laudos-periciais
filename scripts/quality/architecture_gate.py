"""Deterministic static architecture gate; target modules are never imported."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath


def _module(path: str) -> str:
    value = path[:-3].replace("/", ".")
    return value[:-9] if value.endswith(".__init__") else value


def _safe_path(path: str) -> str:
    normalized = PurePosixPath(path).as_posix()
    if (not path or "\\" in path or PureWindowsPath(path).drive or normalized.startswith("/")
            or ".." in PurePosixPath(normalized).parts or normalized != path):
        raise ValueError(f"noncanonical architecture path: {path}")
    if normalized.casefold().startswith("referencias/privadas/"):
        raise ValueError("private architecture path forbidden")
    return normalized


def _python_files(root: Path) -> list[str]:
    return sorted(
        _safe_path(path.relative_to(root).as_posix())
        for path in (root / "scripts").rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _resolve_from(node: ast.ImportFrom, source: str, is_package: bool) -> str:
    package = source.split(".") if is_package else source.split(".")[:-1]
    if node.level:
        base = package[: max(0, len(package) - node.level + 1)]
        return ".".join(base + ([node.module] if node.module else []))
    return node.module or ""


def _imports(tree: ast.AST, source: str, is_package: bool, modules: set[str]) -> tuple[list[dict], set[str]]:
    edges: set[tuple[str, int]] = set()
    dynamic: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.update((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, source, is_package)
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base and alias.name != "*" else base
                edges.add((candidate if candidate in modules else base, node.lineno))
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else ""
            )
            if name in {"append", "extend", "insert", "remove"} and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "sys" and node.func.value.attr == "path":
                dynamic.add("RUNTIME_IMPORT_PATH_MUTATION")
            elif name in {"__import__", "import_module"}:
                if (not node.args or not isinstance(node.args[0], ast.Constant)
                        or not isinstance(node.args[0].value, str) or node.args[0].value.startswith(".")):
                    dynamic.add("DYNAMIC_IMPORT_UNRESOLVED")
                else:
                    edges.add((node.args[0].value, node.lineno))
    return ([{"target": target, "line": line} for target, line in sorted(edges)], dynamic)


def _owner(path: str, components: list[dict]) -> list[str]:
    return sorted(item["id"] for item in components if any(path.startswith(prefix) for prefix in item.get("prefixes", [])))


def _registry_findings(registry: dict) -> list[dict]:
    ids = [item.get("id") for item in registry.get("components", [])]
    prefixes = [prefix for item in registry.get("components", []) for prefix in item.get("prefixes", [])]
    forbidden = {(item.get("source"), item.get("target")) for item in registry.get("forbiddenComponentEdges", [])}
    layers = {"QUALITY_GOVERNANCE", "DOMAIN_CORE", "APPLICATION", "INFRASTRUCTURE"}
    declared_layers = {item.get("layer") for item in registry.get("components", [])}
    allowed_layers = {(item.get("source"), item.get("target")) for item in registry.get("allowedLayerEdges", [])}
    invalid = (registry.get("schemaVersion") != "1.0.0" or not isinstance(registry.get("baselineSha"), str)
               or len(registry.get("baselineSha", "")) != 40 or len(ids) != len(set(ids))
               or len(prefixes) != len(set(prefixes)) or declared_layers != layers
               or any(source not in layers or target not in layers for source, target in allowed_layers))
    by_id = {item.get("id"): item.get("layer") for item in registry.get("components", [])}
    if not any(by_id.get(source) == "DOMAIN_CORE" and by_id.get(target) == "QUALITY_GOVERNANCE" for source, target in forbidden):
        invalid = True
    for prefix in prefixes:
        try: _safe_path(prefix[:-1] if prefix.endswith("/") else prefix)
        except ValueError: invalid = True
    return [{"code": "ARCHITECTURE_REGISTRY_POLICY_INVALID"}] if invalid else []


def analyze_architecture(root: Path, registry: dict) -> dict:
    root = root.resolve(); paths = _python_files(root); modules_by_path = {path: _module(path) for path in paths}
    path_by_module = {module: path for path, module in modules_by_path.items()}; modules = set(path_by_module)
    findings: list[dict] = _registry_findings(registry); edges: list[dict] = []
    components = registry.get("components", [])
    owners: dict[str, str] = {}
    for path, module in modules_by_path.items():
        matches = _owner(path, components)
        if len(matches) != 1:
            findings.append({"code": "ARCHITECTURE_OWNER_MISSING" if not matches else "ARCHITECTURE_OWNER_AMBIGUOUS", "path": path, "owners": matches})
        else:
            owners[module] = matches[0]
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8-sig"), filename=path)
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append({"code": "ARCHITECTURE_SOURCE_UNPARSEABLE", "path": path, "detail": type(exc).__name__})
            continue
        imported, dynamic = _imports(tree, module, path.endswith("/__init__.py"), modules)
        for code in sorted(dynamic): findings.append({"code": code, "path": path, "module": module})
        for item in imported:
            target = item["target"]
            candidates = [known for known in modules if target == known or target.startswith(known + ".")]
            sibling = source_package = module if path.endswith("/__init__.py") else module.rsplit(".", 1)[0]
            sibling = f"{source_package}.{target}"
            if sibling in modules: candidates.append(sibling)
            if not candidates:
                root_name = target.split(".", 1)[0]
                if target.startswith("scripts.") or root_name not in getattr(sys, "stdlib_module_names", set()) | set(registry.get("externalImportRoots", [])):
                    findings.append({"code": "FIRST_PARTY_IMPORT_UNRESOLVED", "path": path, "target": target, "line": item["line"]})
                continue
            resolved = max(candidates, key=lambda value: (len(value), value))
            if resolved != module:
                edges.append({"source": module, "target": resolved, "line": item["line"], "sourcePath": path, "targetPath": path_by_module[resolved]})
    module_rows = [
        {"module": module, "path": path, "component": owners.get(module)}
        for path, module in modules_by_path.items()
    ]
    return {"modules": sorted(module_rows, key=lambda x: x["path"]), "edges": sorted(edges, key=lambda x: (x["source"], x["target"], x["line"])), "findings": sorted(findings, key=lambda x: (x["code"], x.get("path", ""), x.get("target", "")))}


def validate_architecture(root: Path, registry: dict) -> list[dict]:
    report = analyze_architecture(root, registry); findings = list(report["findings"])
    owners = {item["module"]: item["component"] for item in report["modules"] if item["component"]}
    layers_by_component = {item.get("id"): item.get("layer") for item in registry.get("components", [])}
    allowed_layers = {(item.get("source"), item.get("target")) for item in registry.get("allowedLayerEdges", [])}
    forbidden = {(item["source"], item["target"]): item["rule"] for item in registry.get("forbiddenComponentEdges", [])}
    debt = {(item["source"], item["target"]): item for item in registry.get("acceptedCurrentDependencies", [])}
    observed_cross: set[tuple[str, str]] = set()
    observed_lines: dict[tuple[str, str], set[str]] = {}
    for edge in report["edges"]:
        source_component, target_component = owners.get(edge["source"]), owners.get(edge["target"])
        if not source_component or not target_component or source_component == target_component:
            continue
        key = (edge["source"], edge["target"]); observed_cross.add(key)
        observed_lines.setdefault(key, set()).add(f'{edge["sourcePath"]}:{edge["line"]}')
        layer_edge = (layers_by_component.get(source_component), layers_by_component.get(target_component))
        if (source_component, target_component) in forbidden or layer_edge not in allowed_layers:
            rule = forbidden.get((source_component, target_component), "LAYER_DIRECTION")
            if key not in debt:
                findings.append({"code": "FORBIDDEN_ARCHITECTURE_EDGE", **edge, "rule": rule})
        elif key not in debt:
            findings.append({"code": "UNREGISTERED_CROSS_COMPONENT_EDGE", **edge, "sourceComponent": source_component, "targetComponent": target_component})
    for key, item in debt.items():
        if key not in observed_cross:
            findings.append({"code": "STALE_ARCHITECTURE_EXCEPTION", "source": key[0], "target": key[1]})
        if item.get("classification") not in {"ACCEPTED_CURRENT_DEPENDENCY", "POTENTIAL_VIOLATION"} or not item.get("evidence") or not item.get("disposition"):
            findings.append({"code": "ARCHITECTURE_EXCEPTION_INVALID", "source": key[0], "target": key[1]})
        elif item.get("evidence") not in observed_lines.get(key, set()):
            findings.append({"code": "ARCHITECTURE_EXCEPTION_EVIDENCE_MISMATCH", "source": key[0], "target": key[1]})
        if not _edge_exists_at_baseline(root, registry.get("baselineSha", ""), key[0], key[1]):
            findings.append({"code": "ARCHITECTURE_EXCEPTION_NOT_IN_BASELINE", "source": key[0], "target": key[1]})
    accepted_mutations = set(registry.get("acceptedRuntimePathMutations", []))
    observed_mutations = {item.get("module") for item in report["findings"] if item["code"] == "RUNTIME_IMPORT_PATH_MUTATION"}
    findings = [item for item in findings if item["code"] != "RUNTIME_IMPORT_PATH_MUTATION" or item.get("module") not in accepted_mutations]
    for module in sorted(accepted_mutations - observed_mutations):
        findings.append({"code": "STALE_RUNTIME_PATH_EXCEPTION", "module": module})
    for module in sorted(accepted_mutations):
        if not _mutation_exists_at_baseline(root, registry.get("baselineSha", ""), module):
            findings.append({"code": "RUNTIME_PATH_EXCEPTION_NOT_IN_BASELINE", "module": module})
    component_edges = {(owners[e["source"]], owners[e["target"]]) for e in report["edges"] if owners.get(e["source"]) and owners.get(e["target"]) and owners[e["source"]] != owners[e["target"]]}
    observed_cycles = _cycles(component_edges)
    accepted_cycles = {tuple(sorted(item)) for item in registry.get("acceptedComponentCycles", [])}
    for cycle in sorted(observed_cycles - accepted_cycles): findings.append({"code": "NEW_ARCHITECTURE_CYCLE", "components": list(cycle)})
    for cycle in sorted(accepted_cycles - observed_cycles): findings.append({"code": "STALE_ARCHITECTURE_CYCLE", "components": list(cycle)})
    return sorted(findings, key=lambda x: (x["code"], x.get("source", x.get("path", "")), x.get("target", "")))


def _cycles(edges: set[tuple[str, str]]) -> set[tuple[str, ...]]:
    nodes = sorted({value for edge in edges for value in edge}); graph = {node: [] for node in nodes}
    for source, target in sorted(edges): graph[source].append(target)
    index = 0; stack: list[str] = []; active: set[str] = set(); indices = {}; low = {}; result = set()
    def visit(node: str):
        nonlocal index
        indices[node] = low[node] = index; index += 1; stack.append(node); active.add(node)
        for target in graph[node]:
            if target not in indices: visit(target); low[node] = min(low[node], low[target])
            elif target in active: low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component = []
            while True:
                value = stack.pop(); active.remove(value); component.append(value)
                if value == node: break
            if len(component) > 1: result.add(tuple(sorted(component)))
    for node in nodes:
        if node not in indices: visit(node)
    return result


def _edge_exists_at_baseline(root: Path, sha: str, source: str, target: str) -> bool:
    source_path = source.replace(".", "/") + ".py"
    package_path = source.replace(".", "/") + "/__init__.py"
    for path, is_package in ((source_path, False), (package_path, True)):
        completed = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=root, capture_output=True)
        if completed.returncode:
            continue
        try: tree = ast.parse(completed.stdout.decode("utf-8-sig"), filename=path)
        except (UnicodeError, SyntaxError): return False
        imported, _ = _imports(tree, source, is_package, {target})
        for item in imported:
            spelling = item["target"]
            if spelling == target or target.startswith(spelling + "."):
                return True
            package = source if is_package else source.rsplit(".", 1)[0]
            if f"{package}.{spelling}" == target:
                return True
    return False


def _mutation_exists_at_baseline(root: Path, sha: str, module: str) -> bool:
    for path in (module.replace(".", "/") + ".py", module.replace(".", "/") + "/__init__.py"):
        completed = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=root, capture_output=True)
        if completed.returncode: continue
        try: tree = ast.parse(completed.stdout.decode("utf-8-sig"), filename=path)
        except (UnicodeError, SyntaxError): return False
        _, dynamic = _imports(tree, module, path.endswith("/__init__.py"), set())
        return "RUNTIME_IMPORT_PATH_MUTATION" in dynamic
    return False


def load_and_validate(root: Path) -> list[dict]:
    try:
        status = subprocess.run(["git", "status", "--porcelain", "--", "scripts", "config/core-architecture-v1.json"], cwd=root, capture_output=True, text=True)
        if status.returncode != 0 or status.stdout.strip():
            return [{"code": "ARCHITECTURE_WORKTREE_NOT_EXACT_HEAD"}]
        registry = json.loads((root / "config/core-architecture-v1.json").read_text(encoding="utf-8"))
        return validate_architecture(root, registry)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [{"code": "ARCHITECTURE_REGISTRY_INVALID", "detail": str(exc)}]
