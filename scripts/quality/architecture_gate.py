"""Deterministic static architecture gate; target modules are never imported."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import hashlib
import re
from functools import lru_cache
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


EXPECTED_BASELINE_SHA = "0fe2d659f7cfabcb28563651306f2504e09945b3"
EXPECTED_POLICY_SHA256 = "77dc717ace9efb829744db69b7e528893b7fc1e9ebd27acded318ed79598b470"
EXPECTED_DETECTOR_AST_SHA256 = "1a1224475762957e6cbecff4865084f0a0eb5b2075909df355aa0cf3fc5c9467"
EXPECTED_ANALYZER_PROCESS_FINGERPRINT = "d053267e664b9f173031fa71140e427ae0abf1bbad320c0c329b62c572fb7e2d"


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _constant_string(node.left), _constant_string(node.right)
        return left + right if left is not None and right is not None else None
    return None


def _capability_fingerprint(module: str, item: dict) -> str:
    line = "" if item["code"] == "PROCESS_EXECUTION_CAPABILITY" else str(item["line"])
    return hashlib.sha256(f'{module}:{line}:{item["ast"]}'.encode()).hexdigest()


def _python_files(root: Path) -> list[str]:
    if not (root / ".git").exists():
        return sorted(_safe_path(path.relative_to(root).as_posix()) for path in (root / "scripts").rglob("*.py"))
    completed = subprocess.run(["git", "ls-files", "-s", "-z", "scripts/*.py", "scripts/**/*.py"], cwd=root, capture_output=True)
    if completed.returncode:
        raise RuntimeError("tracked architecture inventory unavailable")
    paths = []
    for item in completed.stdout.split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0]
        if mode not in {b"100644", b"100755"}:
            raise ValueError(f"non-regular architecture source: {raw_path.decode('utf-8', errors='replace')}")
        if raw_path.endswith(b".py"):
            paths.append(_safe_path(raw_path.decode("utf-8")))
    return sorted(paths)


def _resolve_from(node: ast.ImportFrom, source: str, is_package: bool) -> str:
    package = source.split(".") if is_package else source.split(".")[:-1]
    if node.level:
        base = package[: max(0, len(package) - node.level + 1)]
        return ".".join(base + ([node.module] if node.module else []))
    return node.module or ""


def _imports(tree: ast.AST, source: str, is_package: bool, modules: set[str]) -> tuple[list[dict], list[dict]]:
    edges: set[tuple[str, int, bool]] = set()
    dynamic: list[dict] = []
    aliases: dict[str, str] = {}
    loader_roots = {"importlib", "runpy", "pkgutil", "pydoc", "zipimport", "pkg_resources", "ctypes", "pickle"}
    detector = next((node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_imports"), None)
    detector_is_pinned = bool(detector and hashlib.sha256(ast.dump(detector, include_attributes=False).encode()).hexdigest() == EXPECTED_DETECTOR_AST_SHA256)
    def is_detector_implementation(node: ast.AST) -> bool:
        return bool(source == "scripts.quality.architecture_gate" and detector_is_pinned
                    and detector.lineno <= getattr(node, "lineno", -1) <= detector.end_lineno)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in {"exec", "eval"} and not is_detector_implementation(node):
            dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in {"compile", "FunctionType"} and not is_detector_implementation(node):
            dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, ast.Import):
            for alias in node.names: aliases[alias.asname or alias.name.split(".")[0]] = alias.name
            if any(alias.name == "subprocess" for alias in node.names):
                dynamic.append({"code": "PROCESS_EXECUTION_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
            if any(alias.name.split(".", 1)[0] in loader_roots for alias in node.names):
                dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names: aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}" if node.module else alias.name
            if node.module == "subprocess" and any(alias.name in {"run", "Popen", "call", "check_call", "check_output"} for alias in node.names):
                dynamic.append({"code": "PROCESS_EXECUTION_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
            if (node.module or "").split(".", 1)[0] in loader_roots:
                dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.update((alias.name, node.lineno, True) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, source, is_package)
            for alias in node.names:
                candidate = f"{base}.{alias.name}" if base and alias.name != "*" else base
                edges.add((candidate if candidate in modules else base, node.lineno, False))
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else ""
            )
            if name in {"append", "extend", "insert", "remove"} and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "sys" and node.func.value.attr == "path":
                dynamic.append({"code": "RUNTIME_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
            elif name in {"__import__", "import_module"}:
                if (not node.args or not isinstance(node.args[0], ast.Constant)
                        or not isinstance(node.args[0].value, str) or node.args[0].value.startswith(".")):
                    dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
                else:
                    edges.add((node.args[0].value, node.lineno, False))
        if isinstance(node, (ast.AugAssign, ast.Assign)) and "sys.path" in ast.unparse(node):
            dynamic.append({"code": "RUNTIME_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"exec", "eval"}:
            dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, ast.Call) and "subprocess" in ast.unparse(node) and "sys.executable" in ast.unparse(node):
            arguments = {_constant_string(child) for child in ast.walk(node)}
            if "-m" in arguments:
                dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, ast.ImportFrom) and node.module in {"sys", "importlib", "site", "builtins"}:
            dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        text = ast.unparse(node) if isinstance(node, (ast.Call, ast.Assign, ast.AugAssign)) else ""
        expanded = text
        for alias, origin in aliases.items():
            expanded = re.sub(rf"\b{re.escape(alias)}\b", origin, expanded)
        if isinstance(node, ast.Call) and re.search(r"\bos\.(?:system|popen|spawn\w*|exec\w*)\b", expanded):
            dynamic.append({"code": "PROCESS_EXECUTION_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if not is_detector_implementation(node) and any(token in expanded for token in (
            "sys.path", "vars(sys", "site.addsitedir", "vars(site", "importlib", "runpy",
            "pkgutil", "pydoc", "zipimport", "pkg_resources", "ctypes.pythonapi", "pickle.loads",
            "builtins", "__builtins__", "__import__", "PYTHONPATH", "sys.__dict__",
            "sys.meta_path", "sys.path_hooks", "sys.modules", "__loader__", "__spec__.loader",
        )):
            if isinstance(node, (ast.Call, ast.Assign, ast.AugAssign)):
                dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, (ast.Call, ast.Assign, ast.AugAssign)) and not is_detector_implementation(node):
            reflective = {
                _constant_string(child.slice) for child in ast.walk(node) if isinstance(child, ast.Subscript)
            }
            reflective.update(
                _constant_string(child.args[1]) for child in ast.walk(node)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                and child.func.id in {"getattr", "setattr"} and len(child.args) > 1
            )
            if reflective & {"__builtins__", "builtins", "__import__", "exec", "eval", "PYTHONPATH"}:
                dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"getattr", "setattr"} and node.args:
            subject = ast.unparse(node.args[0]); origin = aliases.get(subject, subject)
            attribute = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
            if origin in {"sys", "site", "importlib", "runpy", "builtins"} and (attribute is None or attribute in {"path", "addsitedir", "import_module", "run_module", "run_path", "exec", "eval"}):
                dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, ast.Assign) and "__import__" in ast.unparse(node):
            dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.Call)) and "PYTHON" in ast.unparse(node) and "PATH" in ast.unparse(node):
            dynamic.append({"code": "DYNAMIC_IMPORT_CAPABILITY", "line": node.lineno, "ast": ast.dump(node, include_attributes=False)})
    dynamic = [item for item in dynamic if not (
        source == "scripts.quality.architecture_gate" and detector_is_pinned
        and detector.lineno <= item["line"] <= detector.end_lineno
    )]
    return ([{"target": target, "line": line, "exact": exact}
             for target, line, exact in sorted(edges)], dynamic)


def _owner(path: str, components: list[dict]) -> list[str]:
    return sorted(item["id"] for item in components if any(path.startswith(prefix) for prefix in item.get("prefixes", [])))


def _registry_findings(registry: dict) -> list[dict]:
    policy = {key: registry.get(key) for key in ("components", "allowedLayerEdges", "externalImportRoots", "forbiddenComponentEdges", "acceptedComponentCycles", "acceptedImportCapabilityFingerprints", "acceptedImportCapabilityBlobs")}
    policy_digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    ids = [item.get("id") for item in registry.get("components", [])]
    prefixes = [prefix for item in registry.get("components", []) for prefix in item.get("prefixes", [])]
    forbidden = {(item.get("source"), item.get("target")) for item in registry.get("forbiddenComponentEdges", [])}
    layers = {"QUALITY_GOVERNANCE", "DOMAIN_CORE", "APPLICATION", "INFRASTRUCTURE"}
    declared_layers = {item.get("layer") for item in registry.get("components", [])}
    allowed_layers = {(item.get("source"), item.get("target")) for item in registry.get("allowedLayerEdges", [])}
    invalid = (registry.get("schemaVersion") != "1.0.0" or registry.get("baselineSha") != EXPECTED_BASELINE_SHA
               or policy_digest != EXPECTED_POLICY_SHA256
               or len(ids) != len(set(ids))
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
        for item in dynamic:
            fingerprint = _capability_fingerprint(module, item)
            findings.append({"code": item["code"], "path": path, "module": module, "line": item["line"], "fingerprint": fingerprint})
        for item in imported:
            target = item["target"]
            candidates = [known for known in modules if target == known or (
                not item["exact"] and target.startswith(known + ".")
            )]
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
    debt_rows = registry.get("acceptedCurrentDependencies", [])
    debt = {(item["source"], item["target"]): item for item in debt_rows}
    if len(debt) != len(debt_rows):
        findings.append({"code": "DUPLICATE_ARCHITECTURE_EXCEPTION"})
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
    accepted_capabilities = set(registry.get("acceptedImportCapabilityFingerprints", []))
    if len(accepted_capabilities) != len(registry.get("acceptedImportCapabilityFingerprints", [])):
        findings.append({"code": "DUPLICATE_IMPORT_CAPABILITY_EXCEPTION"})
    capability_codes = {"RUNTIME_IMPORT_CAPABILITY", "DYNAMIC_IMPORT_CAPABILITY", "PROCESS_EXECUTION_CAPABILITY"}
    observed_capabilities = {item.get("fingerprint") for item in report["findings"] if item["code"] in capability_codes}
    accepted_blobs = registry.get("acceptedImportCapabilityBlobs", {})
    def capability_accepted(item):
        if item.get("fingerprint") not in accepted_capabilities: return False
        path = item.get("path"); expected = accepted_blobs.get(item.get("module"))
        return bool(expected and path and hashlib.sha256((root / path).read_bytes()).hexdigest() == expected)
    findings = [item for item in findings if item["code"] not in capability_codes or not capability_accepted(item)]
    findings = [item for item in findings if item["code"] != "PROCESS_EXECUTION_CAPABILITY"
                or item.get("module") != "scripts.quality.architecture_gate"
                or item.get("fingerprint") != EXPECTED_ANALYZER_PROCESS_FINGERPRINT]
    for fingerprint in sorted(accepted_capabilities - observed_capabilities): findings.append({"code": "STALE_IMPORT_CAPABILITY_EXCEPTION", "fingerprint": fingerprint})
    baseline_capabilities = _baseline_capability_fingerprints(root, registry.get("baselineSha", ""))
    for fingerprint in sorted(accepted_capabilities - baseline_capabilities): findings.append({"code": "IMPORT_CAPABILITY_NOT_IN_BASELINE", "fingerprint": fingerprint})
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
    baseline_modules = set(_baseline_modules(str(root), sha))
    source_path = source.replace(".", "/") + ".py"
    package_path = source.replace(".", "/") + "/__init__.py"
    for path, is_package in ((source_path, False), (package_path, True)):
        content = _baseline_blob(str(root), sha, path)
        if content is None:
            continue
        try: tree = ast.parse(content.decode("utf-8-sig"), filename=path)
        except (UnicodeError, SyntaxError): return False
        imported, _ = _imports(tree, source, is_package, baseline_modules)
        for item in imported:
            spelling = item["target"]
            candidates = [known for known in baseline_modules if spelling == known or spelling.startswith(known + ".")]
            resolved = max(candidates, key=lambda value: (len(value), value)) if candidates else None
            if resolved == target:
                return True
            package = source if is_package else source.rsplit(".", 1)[0]
            if f"{package}.{spelling}" == target:
                return True
    return False


def _baseline_capability_fingerprints(root: Path, sha: str) -> set[str]:
    modules = set(_baseline_modules(str(root), sha)); result = set()
    for module in registry_capability_modules(root):
        path = module.replace(".", "/") + ".py"; content = _baseline_blob(str(root), sha, path)
        if content is None: continue
        try: tree = ast.parse(content.decode("utf-8-sig"), filename=path)
        except (UnicodeError, SyntaxError): continue
        _, capabilities = _imports(tree, module, False, modules)
        for item in capabilities:
            result.add(_capability_fingerprint(module, item))
    return result


def registry_capability_modules(root: Path) -> set[str]:
    return {
        "scripts.auditoria_pericial.executar_evals",
        "scripts.planejamento_pericial.aprofundar_delimitacao",
        "scripts.planejamento_pericial.gerar_processo",
        "scripts.planejamento_pericial.validar_resultados",
        "scripts.quality.fixture_registry",
        "scripts.vistoria_estruturada.gerar_vistoria",
        "scripts.agentic.gates",
        "scripts.agentic.package",
        "scripts.agentic.sanitize",
        "scripts.quality.architecture_gate",
        "scripts.quality.core_baseline",
        "scripts.quality.deep_quality",
        "scripts.quality.historical_mutations",
        "scripts.quality.verify_core",
        "scripts.terceiros.verificar_design_motion",
        "scripts.terceiros.verificar_superpowers",
        "scripts.terceiros.catalogar_repositorios",
        "scripts.terceiros.verificar_atualizacoes",
    }


@lru_cache(maxsize=8)
def _baseline_modules(root: str, sha: str) -> tuple[str, ...]:
    listed = subprocess.run(["git", "ls-tree", "-r", "--name-only", sha, "scripts"], cwd=root, capture_output=True, text=True)
    return tuple(sorted(_module(path) for path in listed.stdout.splitlines() if path.endswith(".py")))


@lru_cache(maxsize=256)
def _baseline_blob(root: str, sha: str, path: str) -> bytes | None:
    completed = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=root, capture_output=True)
    return completed.stdout if completed.returncode == 0 else None


def load_and_validate(root: Path) -> list[dict]:
    try:
        status = subprocess.run([
            "git", "status", "--porcelain", "--", "scripts", "config/core-architecture-v1.json",
            "docs/arquitetura/constituicao-core-pericial-v1.md",
        ], cwd=root, capture_output=True, text=True)
        if status.returncode != 0 or status.stdout.strip():
            return [{"code": "ARCHITECTURE_WORKTREE_NOT_EXACT_HEAD"}]
        def strict_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result: raise ValueError(f"duplicate architecture key: {key}")
                result[key] = value
            return result
        registry = json.loads((root / "config/core-architecture-v1.json").read_text(encoding="utf-8"), object_pairs_hook=strict_object)
        return validate_architecture(root, registry)
    except RuntimeError as exc:
        return [{"code": "ARCHITECTURE_INVENTORY_INVALID", "detail": str(exc)}]
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [{"code": "ARCHITECTURE_REGISTRY_INVALID", "detail": str(exc)}]
