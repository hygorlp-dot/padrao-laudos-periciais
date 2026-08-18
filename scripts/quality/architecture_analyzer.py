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
    ".github/workflows/capability-protected.yml",
    "config/architecture-capability-transfers-v2.json",
    "config/architecture-policy-v1.json",
    "config/capability-protected-artifacts-v1.json",
    "schemas/architecture-baseline-v1.schema.json",
    "scripts/quality/architecture_analyzer.py",
    "scripts/quality/ast_inventory.py",
    "scripts/quality/capability_trust_anchor.py",
    "scripts/quality/repository_inventory.py",
)
PROTECTED_TRANSITION_PATH = "config/architecture-protected-transition-v1.json"
PROTECTED_TRANSITION_SUPPORT_PREFIXES = (
    "docs/arquitetura/",
    "docs/superpowers/plans/",
    "tests/test_architecture",
)
PROTECTED_TRANSITION_SUPPORT_SCOPES = {
    "CAPABILITY_BOOTSTRAP_V1": {
        "prefixes": (
            "scripts/quality/capability_",
            "tests/test_capability_",
        ),
        "paths": (
            "config/capability-exceptions-v1.json",
            "config/capability-protected-transition-v1.json",
            "scripts/quality/verify_core.py",
            "tests/test_repository_safety_gate.py",
        ),
    },
}


def _support_path_in_scope(scope: str, path: str) -> bool:
    scope_rule = PROTECTED_TRANSITION_SUPPORT_SCOPES.get(scope)
    if scope_rule is None:
        return False
    return path in scope_rule["paths"] or path.startswith(scope_rule["prefixes"])


def _git_path_identity(root: Path, commit: str, path: str) -> tuple[str, str, str] | None:
    result = subprocess.run(
        ["git", "ls-tree", commit, "--", path],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if result.returncode or not result.stdout.strip():
        return None
    metadata, listed_path = result.stdout.splitlines()[0].split("\t", 1)
    if listed_path != path:
        return None
    mode, object_type, object_id = metadata.split()
    return (mode, object_type, object_id)


def _protected_transition_valid(
    root: Path,
    protected_base: str,
    candidate: str,
    base_objects: dict[str, tuple[str, str, str]],
    candidate_objects: dict[str, tuple[str, str, str]],
    changed_artifacts: list[str],
) -> bool:
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{candidate}:{PROTECTED_TRANSITION_PATH}"],
            cwd=root,
            text=True,
        )
        transition = json.loads(raw)
        schema_version = transition.get("schemaVersion")
        expected_keys = (
            {"schemaVersion", "transitionId", "protectedBaseSha", "artifacts", "supportScope", "supportArtifacts"}
            if schema_version == "3.0.0"
            else {"schemaVersion", "transitionId", "protectedBaseSha", "artifacts"}
        )
        if set(transition) != expected_keys:
            return False
        if schema_version not in {"1.0.0", "2.0.0", "3.0.0"}:
            return False
        if transition.get("transitionId") != "ARCHITECTURE_TRUST_ANCHOR_ROTATION_V1":
            return False
        if transition.get("protectedBaseSha") != protected_base:
            return False
        rows = transition.get("artifacts")
        if not isinstance(rows, list) or len(rows) != len(changed_artifacts):
            return False
        expected = {
            path: (base_objects.get(path), candidate_objects.get(path))
            for path in changed_artifacts
        }
        if any(
            (base_object is not None and base_object[:2] not in {("100644", "blob"), ("100755", "blob")})
            or candidate_object is None
            or candidate_object[:2] not in {("100644", "blob"), ("100755", "blob")}
            for base_object, candidate_object in expected.values()
        ):
            return False
        if schema_version == "1.0.0" and any(
            base_object is None or base_object[:2] != candidate_object[:2]
            for base_object, candidate_object in expected.values()
        ):
            return False
        declared = {}
        for row in rows:
            row_keys = (
                {"path", "baseBlobSha", "candidateBlobSha"}
                if schema_version == "1.0.0"
                else {
                    "path", "baseMode", "baseObjectType", "baseBlobSha",
                    "candidateMode", "candidateObjectType", "candidateBlobSha",
                }
            )
            if not isinstance(row, dict) or set(row) != row_keys:
                return False
            path = row.get("path")
            if path in declared or path not in expected:
                return False
            if schema_version == "1.0.0":
                declared[path] = (row.get("baseBlobSha"), row.get("candidateBlobSha"))
            else:
                declared[path] = (
                    None
                    if row.get("baseMode") is None
                    and row.get("baseObjectType") is None
                    and row.get("baseBlobSha") is None
                    else (row.get("baseMode"), row.get("baseObjectType"), row.get("baseBlobSha")),
                    (row.get("candidateMode"), row.get("candidateObjectType"), row.get("candidateBlobSha")),
                )
        exact_expected = (
            {path: (base[2], candidate_object[2]) for path, (base, candidate_object) in expected.items()}
            if schema_version == "1.0.0"
            else expected
        )
        if declared != exact_expected:
            return False
        support_paths: set[str] = set()
        if schema_version == "3.0.0":
            support_scope = transition.get("supportScope")
            if support_scope not in PROTECTED_TRANSITION_SUPPORT_SCOPES:
                return False
            support_rows = transition.get("supportArtifacts")
            if not isinstance(support_rows, list):
                return False
            support_row_keys = {
                "path", "baseMode", "baseObjectType", "baseBlobSha",
                "candidateMode", "candidateObjectType", "candidateBlobSha",
            }
            allowed_regular = {("100644", "blob"), ("100755", "blob")}
            declared_support: dict[str, tuple[tuple[str, str, str] | None, tuple[str, str, str]]] = {}
            for support_row in support_rows:
                if not isinstance(support_row, dict) or set(support_row) != support_row_keys:
                    return False
                support_path = support_row.get("path")
                if not isinstance(support_path, str):
                    return False
                if (
                    support_path in declared_support
                    or support_path in expected
                    or support_path in PROTECTED_ARCHITECTURE_ARTIFACTS
                    or not _support_path_in_scope(support_scope, support_path)
                ):
                    return False
                base_triple_raw = (
                    support_row.get("baseMode"), support_row.get("baseObjectType"), support_row.get("baseBlobSha"),
                )
                candidate_triple_raw = (
                    support_row.get("candidateMode"),
                    support_row.get("candidateObjectType"),
                    support_row.get("candidateBlobSha"),
                )
                if all(item is None for item in base_triple_raw):
                    declared_base: tuple[str, str, str] | None = None
                elif all(isinstance(item, str) for item in base_triple_raw) and base_triple_raw[:2] in allowed_regular:
                    declared_base = base_triple_raw
                else:
                    return False
                if not all(isinstance(item, str) for item in candidate_triple_raw):
                    return False
                if candidate_triple_raw[:2] not in allowed_regular:
                    return False
                declared_support[support_path] = (declared_base, candidate_triple_raw)
            for support_path, (declared_base, declared_candidate) in declared_support.items():
                actual_base = _git_path_identity(root, protected_base, support_path)
                if actual_base != declared_base:
                    return False
                actual_candidate = _git_path_identity(root, candidate, support_path)
                if actual_candidate != declared_candidate:
                    return False
            support_paths = set(declared_support)
        diff = subprocess.run(
            ["git", "diff", "--name-only", "-z", protected_base, candidate],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        changed_paths = {item.decode("utf-8") for item in diff.split(b"\0") if item}
        allowed_exact = set(changed_artifacts) | {PROTECTED_TRANSITION_PATH} | support_paths
        return all(
            path in allowed_exact or path.startswith(PROTECTED_TRANSITION_SUPPORT_PREFIXES)
            for path in changed_paths
        )
    except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError, subprocess.CalledProcessError):
        return False


def _protected_artifact_findings(root: Path, protected_base: str, candidate: str) -> list[dict]:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", protected_base, candidate],
        cwd=root,
        capture_output=True,
    )
    if ancestor.returncode:
        return [_finding(
            "ARCHITECTURE_PROTECTED_BASE_INVALID",
            "scripts/quality/architecture_analyzer.py",
            1,
            "protected base is not an ancestor of candidate",
        )]
    def tree_objects(commit: str) -> dict[str, tuple[str, str, str]] | None:
        # Exact-path lookup preserves a tree at a protected file path for fail-closed type validation.
        result = subprocess.run(
            ["git", "ls-tree", commit, "--", *PROTECTED_ARCHITECTURE_ARTIFACTS],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            return None
        objects = {}
        try:
            for line in result.stdout.splitlines():
                metadata, path = line.split("\t", 1)
                mode, object_type, object_id = metadata.split()
                if path in objects or path not in PROTECTED_ARCHITECTURE_ARTIFACTS:
                    return None
                objects[path] = (mode, object_type, object_id)
        except (TypeError, ValueError):
            return None
        return objects

    base_objects = tree_objects(protected_base)
    candidate_objects = tree_objects(candidate)
    if base_objects is None or candidate_objects is None:
        return [_finding(
            "ARCHITECTURE_PROTECTED_ARTIFACT_UNAVAILABLE",
            "scripts/quality/architecture_analyzer.py",
            1,
            "protected artifact identity could not be loaded",
        )]
    changed_artifacts = [
        path for path in PROTECTED_ARCHITECTURE_ARTIFACTS
        if base_objects.get(path) != candidate_objects.get(path)
    ]
    if not changed_artifacts:
        return []
    if _protected_transition_valid(
        root, protected_base, candidate, base_objects, candidate_objects, changed_artifacts,
    ):
        return []
    findings = [_finding(
        "ARCHITECTURE_PROTECTED_TRANSITION_INVALID",
        PROTECTED_TRANSITION_PATH,
        1,
        "protected artifact change lacks an exact dedicated transition",
    )]
    for path in changed_artifacts:
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
    for source, (path, tree) in sorted(parsed.items()):
        package = path.endswith("/__init__.py")
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names if alias.name == "scripts" or alias.name.startswith("scripts.")]
            elif isinstance(node, ast.ImportFrom):
                try: base = _resolve_from(node, source, package)
                except ValueError as exc:
                    findings.append(_finding("INVALID_RELATIVE_IMPORT", path, node.lineno, str(exc))); continue
                if base == "scripts" or base.startswith("scripts."):
                    targets = [f"{base}.{alias.name}" if alias.name != "*" else base for alias in node.names]
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
