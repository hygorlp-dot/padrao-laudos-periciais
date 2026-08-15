"""Side-effect-free capability acquisition analysis over one exact Git tree."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from scripts.quality.ast_inventory import module_name, parse_source
from scripts.quality.repository_inventory import candidate_tree, tree_python_sources


ANALYZER = "CAPABILITY_ANALYZER_V1"
_REQUIRED_POLICY_KEYS = {
    "policyVersion",
    "analyzerContractVersion",
    "capabilityClasses",
    "scanUniverse",
    "candidateIdentity",
    "processNamespaceCategories",
    "processNamespaces",
    "dynamicImportSurfaces",
    "dynamicExecutionSurfaces",
    "nativeOrExecutableDeserializationSurfaces",
    "mixedNamespaces",
    "mixedNamespaceMembers",
    "ruleMappings",
    "integrityBootstrap",
    "inlineSuppressionsAllowed",
    "wildcardExceptionsAllowed",
    "unknownSensitiveReflectionPolicy",
    "dynamicImportPolicy",
    "dynamicExecutionPolicy",
}


def _load_policy(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != _REQUIRED_POLICY_KEYS:
        raise ValueError("capability policy shape invalid")
    if value.get("policyVersion") != "1.0.0" or value.get("analyzerContractVersion") != "1.0.0":
        raise ValueError("capability policy version invalid")
    mappings = value.get("ruleMappings")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("capability rule mappings invalid")
    return value


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value)
        return f"{owner}.{node.attr}" if owner else None
    return None


def _normalized_sha(node: ast.AST) -> str:
    normalized = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class _CapabilityVisitor(ast.NodeVisitor):
    def __init__(self, path: str, policy: dict):
        self.path = path
        self.module = module_name(path)
        self.policy = policy
        self.findings: list[dict] = []
        self._seen: set[tuple[str, int, int]] = set()
        self._severity = {row["findingCode"]: row["severity"] for row in policy["ruleMappings"]}
        self._aliases: dict[str, str] = {}

    def _resolved_name(self, node: ast.AST) -> str | None:
        name = _qualified_name(node)
        if not name:
            return None
        root, separator, remainder = name.partition(".")
        resolved = self._aliases.get(root, root)
        return f"{resolved}.{remainder}" if separator else resolved

    def _add(self, code: str, node: ast.AST) -> None:
        location = (code, node.lineno, node.col_offset)
        if location in self._seen:
            return
        self._seen.add(location)
        self.findings.append(
            {
                "schemaVersion": "1.0.0",
                "analyzer": ANALYZER,
                "policyVersion": self.policy["policyVersion"],
                "code": code,
                "severity": self._severity[code],
                "canonicalPath": self.path,
                "module": self.module,
                "location": {"line": node.lineno, "column": node.col_offset},
                "normalizedAstSha256": _normalized_sha(node),
            }
        )

    @staticmethod
    def _builtin_subscript_name(node: ast.AST) -> str | None:
        if not isinstance(node, ast.Subscript):
            return None
        owner = node.value
        direct = isinstance(owner, ast.Name) and owner.id == "__builtins__"
        globals_builtins = (
            isinstance(owner, ast.Subscript)
            and isinstance(owner.value, ast.Call)
            and _qualified_name(owner.value.func) == "globals"
            and isinstance(owner.slice, ast.Constant)
            and owner.slice.value == "__builtins__"
        )
        if not direct and not globals_builtins:
            return None
        return node.slice.value if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str) else None

    def _contains_sys_modules(self, node: ast.AST) -> bool:
        return any(self._resolved_name(part) == "sys.modules" for part in ast.walk(node))

    def visit_Call(self, node: ast.Call) -> None:
        name = self._resolved_name(node.func)
        builtin_name = self._builtin_subscript_name(node.func)
        if name in {
            "eval", "exec", "compile", "builtins.eval", "builtins.exec", "builtins.compile",
            "types.CodeType", "types.FunctionType",
        } or builtin_name in {
            "eval",
            "exec",
            "compile",
        }:
            self._add("DYNAMIC_EXECUTION_ACQUISITION", node)
        elif name in {"__import__", "importlib.import_module"}:
            self._add("DYNAMIC_IMPORT_ACQUISITION", node)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "import_module" and self._contains_sys_modules(node.func.value):
            self._add("DYNAMIC_IMPORT_ACQUISITION", node)
        elif name in set(self.policy["nativeOrExecutableDeserializationSurfaces"]):
            self._add("EXECUTABLE_DESERIALIZATION_OR_NATIVE_LOADING", node)
        elif name in {f"os.{member}" for member in self.policy["mixedNamespaceMembers"]["os"]}:
            self._add("OS_PROCESS_MEMBER_ACQUISITION", node)
        elif name in {"getattr", "operator.getitem"} and any(
            self._resolved_name(part) in set(self.policy["mixedNamespaces"]) or
            (isinstance(part, ast.Call) and _qualified_name(part.func) == "vars")
            for part in ast.walk(node)
        ):
            self._add("SENSITIVE_NAMESPACE_ESCAPE", node)
        elif isinstance(node.func, ast.Call) and _qualified_name(node.func.func) == "itemgetter" and any(
            isinstance(part, ast.Call) and _qualified_name(part.func) == "vars" for part in ast.walk(node)
        ):
            self._add("UNKNOWN_SENSITIVE_REFLECTION", node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        if any(any(alias.name == root or alias.name.startswith(root + ".") for root in self.policy["processNamespaces"]) for alias in node.names):
            self._add("PROCESS_NAMESPACE_ACQUISITION", node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            if alias.name != "*":
                self._aliases[alias.asname or alias.name] = f"{module}.{alias.name}" if module else alias.name
        if any(module == root or module.startswith(root + ".") for root in self.policy["processNamespaces"]):
            self._add("PROCESS_NAMESPACE_ACQUISITION", node)
        if module == "os" and any(alias.name in self.policy["mixedNamespaceMembers"]["os"] for alias in node.names):
            self._add("OS_PROCESS_MEMBER_ACQUISITION", node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        name = self._resolved_name(node)
        if name in {f"os.{member}" for member in self.policy["mixedNamespaceMembers"]["os"]}:
            self._add("OS_PROCESS_MEMBER_ACQUISITION", node)
        elif name and name.endswith(".__dict__") and name.split(".", 1)[0] in self.policy["mixedNamespaces"]:
            self._add("SENSITIVE_NAMESPACE_ESCAPE", node)
        self.generic_visit(node)

    def visit_arguments(self, node: ast.arguments) -> None:
        for default in [*node.defaults, *node.kw_defaults]:
            if self._resolved_name(default) in {
                "eval", "exec", "compile", "builtins.eval", "builtins.exec", "builtins.compile",
            }:
                self._add("DYNAMIC_EXECUTION_ACQUISITION", default)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and self._resolved_name(node) in {
            "eval", "exec", "compile", "builtins.eval", "builtins.exec", "builtins.compile",
        }:
            self._add("DYNAMIC_EXECUTION_ACQUISITION", node)

    def _assignment_name(self, target: ast.AST) -> str | None:
        return self._resolved_name(target.value) if isinstance(target, ast.Subscript) else self._resolved_name(target)

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(self._assignment_name(target) in {"sys.meta_path", "sys.path_hooks"} for target in node.targets):
            self._add("SENSITIVE_NAMESPACE_ESCAPE", node)
        self.generic_visit(node)


def analyze_source(path: str, source: str, *, policy_path: Path) -> list[dict]:
    """Analyze one canonical Python source without Git or filesystem side effects."""
    policy = _load_policy(policy_path)
    parsed = parse_source(path, source)
    visitor = _CapabilityVisitor(path, policy)
    visitor.visit(parsed)
    return sorted(
        visitor.findings,
        key=lambda item: (item["canonicalPath"], item["location"]["line"], item["location"]["column"], item["code"]),
    )


def analyze_capabilities(
    repo: Path,
    candidate_commit_sha: str,
    candidate_tree_sha: str,
    *,
    policy_path: Path,
) -> list[dict]:
    """Return deterministic capability findings for the exact candidate commit tree."""
    policy = _load_policy(policy_path)
    _, tree = candidate_tree(repo, candidate_commit_sha, expected_tree=candidate_tree_sha)
    sources = tree_python_sources(repo, tree, tuple(policy["scanUniverse"]["productionRoots"]))
    findings: list[dict] = []
    for path, source in sources.items():
        parsed = parse_source(path, source)
        visitor = _CapabilityVisitor(path, policy)
        visitor.visit(parsed)
        findings.extend(visitor.findings)
    return sorted(
        findings,
        key=lambda item: (item["canonicalPath"], item["location"]["line"], item["location"]["column"], item["code"]),
    )
