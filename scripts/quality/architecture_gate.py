"""Deterministic static architecture gate; target modules are never imported."""
from __future__ import annotations

import ast
import json
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


def _imports(tree: ast.AST, source: str, is_package: bool, modules: set[str]) -> tuple[list[dict], bool]:
    edges: set[tuple[str, int]] = set()
    dynamic = False
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
            if name in {"__import__", "import_module"}:
                if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                    dynamic = True
                else:
                    edges.add((node.args[0].value, node.lineno))
    return ([{"target": target, "line": line} for target, line in sorted(edges)], dynamic)


def _owner(path: str, components: list[dict]) -> list[str]:
    return sorted(item["id"] for item in components if any(path.startswith(prefix) for prefix in item.get("prefixes", [])))


def analyze_architecture(root: Path, registry: dict) -> dict:
    root = root.resolve(); paths = _python_files(root); modules_by_path = {path: _module(path) for path in paths}
    path_by_module = {module: path for path, module in modules_by_path.items()}; modules = set(path_by_module)
    findings: list[dict] = []; edges: list[dict] = []
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
        if dynamic:
            findings.append({"code": "DYNAMIC_IMPORT_UNRESOLVED", "path": path})
        for item in imported:
            target = item["target"]
            candidates = [known for known in modules if target == known or target.startswith(known + ".")]
            if not candidates:
                if target.startswith("scripts."):
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
    forbidden = {(item["source"], item["target"]): item["rule"] for item in registry.get("forbiddenComponentEdges", [])}
    debt = {(item["source"], item["target"]): item for item in registry.get("acceptedCurrentDependencies", [])}
    observed_cross: set[tuple[str, str]] = set()
    for edge in report["edges"]:
        source_component, target_component = owners.get(edge["source"]), owners.get(edge["target"])
        if not source_component or not target_component or source_component == target_component:
            continue
        key = (edge["source"], edge["target"]); observed_cross.add(key)
        if (source_component, target_component) in forbidden:
            findings.append({"code": "FORBIDDEN_ARCHITECTURE_EDGE", **edge, "rule": forbidden[(source_component, target_component)]})
        elif key not in debt:
            findings.append({"code": "UNREGISTERED_CROSS_COMPONENT_EDGE", **edge, "sourceComponent": source_component, "targetComponent": target_component})
    for key, item in debt.items():
        if key not in observed_cross:
            findings.append({"code": "STALE_ARCHITECTURE_EXCEPTION", "source": key[0], "target": key[1]})
        if item.get("classification") not in {"ACCEPTED_CURRENT_DEPENDENCY", "POTENTIAL_VIOLATION"} or not item.get("evidence") or not item.get("disposition"):
            findings.append({"code": "ARCHITECTURE_EXCEPTION_INVALID", "source": key[0], "target": key[1]})
    return sorted(findings, key=lambda x: (x["code"], x.get("source", x.get("path", "")), x.get("target", "")))


def load_and_validate(root: Path) -> list[dict]:
    try:
        registry = json.loads((root / "config/core-architecture-v1.json").read_text(encoding="utf-8"))
        return validate_architecture(root, registry)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [{"code": "ARCHITECTURE_REGISTRY_INVALID", "detail": str(exc)}]
