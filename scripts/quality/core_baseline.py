"""Deterministic, observational Core baseline built only from Git blobs."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath


BASELINE_OUTPUTS = {
    "config/core-stable-baseline-v1.json",
    "config/core-stable-baseline-v1.sha256",
    "docs/stabilization/core-stable-baseline-v1.md",
}
PRIVATE_PREFIX = "referencias/privadas/"
ANALYZER_VERSION = "1.0.0"
SUPPORTED_BASELINES = {"V1": ANALYZER_VERSION}
TRUSTED_EVIDENCE = {
    ("V1", "8530584c82061fb35018afd6638032ba8798b105"): "ee132b36672e7d5c8c5392124c8977bb70c7d6b478cec801b02f9ec642f0680c"
}
CORE_CONFIGS = {
    "config/core-boundaries.json", "config/core-invariants.json",
    "config/core-registry-lock.json", "config/quality-baseline.json",
    "config/schema-versions.json", "config/historical-bugs.json",
    "config/historical-mutants.json", "tests/fixtures/core-fixtures.json",
}
GOVERNANCE_FILES = {
    "AGENTS.md", ".github/workflows/core-safety.yml", "requirements.txt",
    "requirements-dev.txt", "docs/arquitetura/arquitetura-core-pericial.md",
    "docs/arquitetura/arquitetura-sistema.md",
    "docs/padroes/padrao-governanca-desenvolvimento.md",
    "docs/padroes/protocolo-pesquisa-ranking.md",
}
BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.Match, ast.comprehension)
CONTROL_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)
HOTSPOTS = (
    ("scripts/motor_vicios/motor.py", "executar"),
    ("scripts/triagem_pericial/gerar_delimitacao.py", "gerar"),
    ("scripts/planejamento_pericial/gerar_plano.py", "gerar"),
)


def _git(repo: Path, *args: str, text: bool = False):
    completed = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return completed.stdout.decode("utf-8") if text else completed.stdout


def _exact_sha(repo: Path, revision: str) -> str:
    sha = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}", text=True).strip()
    if len(sha) != 40 or any(char not in "0123456789abcdef" for char in sha):
        raise ValueError("invalid base SHA")
    return sha


def _tree(repo: Path, sha: str) -> list[str]:
    raw = _git(repo, "ls-tree", "-rz", "--name-only", sha)
    paths = [item.decode("utf-8") for item in raw.split(b"\0") if item]
    return sorted(paths)


def _blob(repo: Path, sha: str, path: str) -> bytes:
    return _git(repo, "show", f"{sha}:{path}")


def _json_blob(repo: Path, sha: str, path: str) -> dict:
    return json.loads(_blob(repo, sha, path).decode("utf-8-sig"))


def validate_evidence(evidence: dict, *, baseline_version: str, sha: str) -> str:
    if evidence.get("coreBaseSha") != sha:
        raise ValueError("behavioral evidence SHA mismatch")
    digest = hashlib.sha256(canonical_bytes(evidence)).hexdigest()
    if TRUSTED_EVIDENCE.get((baseline_version, sha)) != digest:
        raise ValueError("behavioral evidence is not the pinned V1 receipt")
    return digest


def _safe_path(path: str) -> str:
    windows_path = PureWindowsPath(path)
    normalized = PurePosixPath(path).as_posix()
    if "\\" in path or windows_path.drive:
        raise ValueError(f"noncanonical path: {path}")
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        raise ValueError(f"unsafe path: {path}")
    if normalized.casefold() == PRIVATE_PREFIX.rstrip("/").casefold() or normalized.casefold().startswith(PRIVATE_PREFIX.casefold()):
        raise ValueError(f"private path forbidden: {path}")
    canonical = normalized + "/" if path.endswith("/") else normalized
    if canonical != path:
        raise ValueError(f"noncanonical path: {path}")
    return canonical


def _expand_path(spec: str, tracked: set[str]) -> set[str]:
    spec = _safe_path(spec)
    if spec not in tracked:
        matches = {path for path in tracked if path.startswith(spec)}
        if not matches:
            raise ValueError(f"registered path matches no tracked content: {spec}")
        return matches
    return {spec}


def _category(path: str) -> str:
    if path.startswith("scripts/") and path.endswith(".py"):
        return "CORE_RUNTIME" if not path.startswith(("scripts/quality/", "scripts/agentic/", "scripts/terceiros/")) else "CORE_CONTRACT"
    if path.startswith("schemas/"): return "SCHEMA"
    if path.startswith("tests/fixtures/"): return "FIXTURE"
    if path.startswith("tests/"): return "TEST"
    if path == "config/core-invariants.json": return "INVARIANT"
    if path == "config/core-boundaries.json": return "BOUNDARY"
    if path.startswith("config/"): return "QUALITY_CONFIG"
    return "GOVERNANCE_RELEVANT_TO_CORE"


def _manifest_paths(repo: Path, sha: str, boundaries: dict, invariants: dict, fixtures: dict) -> list[str]:
    tracked = set(_tree(repo, sha))
    selected = set((CORE_CONFIGS | GOVERNANCE_FILES) & tracked)
    for boundary in boundaries["boundaries"]:
        for spec in boundary.get("paths", []):
            selected.update(_expand_path(spec, tracked))
        selected.update(boundary.get("tests", []))
        selected.update(name if name.startswith("schemas/") else f"schemas/{name}" for name in boundary.get("schemas", []))
    for invariant in invariants["invariants"]:
        selected.update(test.split("::", 1)[0] for test in invariant.get("testes", []))
    selected.update(item["arquivo"] for item in fixtures.get("fixtures", []))
    selected.update(path for path in tracked if path.startswith("schemas/") and path.endswith(".json"))
    selected.update(path for path in tracked if path.startswith("tests/test") and path.endswith(".py"))
    if "scripts/validar_schemas.py" in tracked:
        selected.add("scripts/validar_schemas.py")
    missing = sorted(path for path in selected if path not in tracked and path not in BASELINE_OUTPUTS)
    if missing:
        raise ValueError(f"registered tracked content missing: {missing}")
    result = []
    for path in sorted(selected & tracked):
        path = _safe_path(path)
        if path not in BASELINE_OUTPUTS and not path.endswith((".pyc", ".pdf", ".docx", ".zip")):
            result.append(path)
    return result


def _module_name(path: str) -> str:
    value = path[:-3].replace("/", ".")
    return value[:-9] if value.endswith(".__init__") else value


def _imports(tree: ast.AST, module: str, *, is_package: bool) -> list[str]:
    imports: set[str] = set()
    package = module.split(".") if is_package else module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: max(0, len(package) - node.level + 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            if target: imports.add(target)
    return sorted(imports)


def _max_nesting(node: ast.AST, depth: int = 0) -> int:
    maximum = depth
    for child in ast.iter_child_nodes(node):
        next_depth = depth + 1 if isinstance(child, CONTROL_NODES) else depth
        maximum = max(maximum, _max_nesting(child, next_depth))
    return maximum


def _function_metric(path: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    decisions = 1
    for child in ast.walk(node):
        if child is node: continue
        if isinstance(child, BRANCH_NODES): decisions += 1
        elif isinstance(child, ast.BoolOp): decisions += max(1, len(child.values) - 1)
        elif isinstance(child, ast.Try): decisions += len(child.handlers) + bool(child.orelse) + bool(child.finalbody)
    parameters = len(node.args.posonlyargs) + len(node.args.args) + len(node.args.kwonlyargs) + bool(node.args.vararg) + bool(node.args.kwarg)
    return {
        "path": path, "function": node.name, "line": node.lineno,
        "physicalLoc": getattr(node, "end_lineno", node.lineno) - node.lineno + 1,
        "statementCount": sum(isinstance(item, ast.stmt) for item in ast.walk(node)),
        "decisionCountCandidate": decisions, "maxControlNesting": _max_nesting(node),
        "parameters": parameters, "returns": sum(isinstance(item, ast.Return) for item in ast.walk(node)),
        "raises": sum(isinstance(item, ast.Raise) for item in ast.walk(node)),
        "exceptionHandlers": sum(isinstance(item, ast.ExceptHandler) for item in ast.walk(node)),
    }


def canonical_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def semantic_bytes(payload: dict) -> bytes:
    semantic = {key: value for key, value in payload.items() if key != "semanticFingerprint"}
    return canonical_bytes(semantic)


def build_baseline(repo: Path, revision: str, *, baseline_version: str = "V1", evidence: dict | None = None) -> dict:
    repo = repo.resolve()
    if SUPPORTED_BASELINES.get(baseline_version) != ANALYZER_VERSION:
        raise ValueError("baseline/analyzer version mismatch")
    sha = _exact_sha(repo, revision)
    evidence_digest = validate_evidence(evidence, baseline_version=baseline_version, sha=sha) if evidence is not None else None
    boundaries = _json_blob(repo, sha, "config/core-boundaries.json")
    invariants = _json_blob(repo, sha, "config/core-invariants.json")
    fixtures = _json_blob(repo, sha, "tests/fixtures/core-fixtures.json")
    paths = _manifest_paths(repo, sha, boundaries, invariants, fixtures)
    manifest = []
    modules = []
    symbols = []
    imports_by_module: dict[str, list[str]] = {}
    metrics: dict[tuple[str, str], dict] = {}
    for path in paths:
        content = _blob(repo, sha, path)
        manifest.append({"path": path, "sizeBytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "category": _category(path)})
        if path.startswith("scripts/") and path.endswith(".py"):
            module = _module_name(path)
            try:
                tree = ast.parse(content.decode("utf-8-sig"), filename=path)
            except (SyntaxError, UnicodeDecodeError):
                modules.append({"path": path, "module": module, "astStatus": "UNPARSEABLE"})
                continue
            top = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            explicit_exports: set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        explicit_exports.update(item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str))
            module_imports = _imports(tree, module, is_package=path.endswith("/__init__.py"))
            imports_by_module[module] = module_imports
            modules.append({"path": path, "module": module, "astStatus": "PARSED", "symbolCount": len(top), "imports": module_imports})
            for node in top:
                symbols.append({"path": path, "module": module, "name": node.name, "kind": "CLASS" if isinstance(node, ast.ClassDef) else "FUNCTION", "visibility": "EXPORTED" if node.name in explicit_exports else ("INTERNAL" if node.name.startswith("_") else "PUBLIC_BY_CONVENTION"), "line": node.lineno})
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    metrics[(path, node.name)] = _function_metric(path, node)
    module_names = sorted({item["module"] for item in modules})
    edges = []
    external = set()
    stdlib = getattr(sys, "stdlib_module_names", set())
    for source, targets in imports_by_module.items():
        for target in targets:
            candidates = [name for name in module_names if target == name or target.startswith(name + ".")]
            sibling = source.rsplit(".", 1)[0] + "." + target
            if sibling in module_names:
                candidates.append(sibling)
            internal = max(candidates, key=lambda name: (len(name), name)) if candidates else None
            if internal:
                edges.append({"from": source, "to": internal})
            else:
                root = target.split(".", 1)[0]
                if root and root not in stdlib and root not in {"scripts", "tests"}:
                    external.add(root)
    hotspot_metrics = []
    for path, function in HOTSPOTS:
        if (path, function) in metrics:
            hotspot_metrics.append(metrics[(path, function)])
    invariant_inventory = [{key: item.get(key) for key in ("id", "severidade", "global", "bloqueante", "boundaries", "testes")} for item in invariants["invariants"]]
    boundary_inventory = [{key: item.get(key) for key in ("id", "paths", "invariants", "schemas", "tests", "consumers")} for item in boundaries["boundaries"]]
    behavioral = evidence.get("behavioralBaseline") if evidence else {
        "status": "NOT_YET_PROVEN", "evidenceLevel": "NOT_YET_PROVEN"
    }
    payload = {
        "baselineVersion": baseline_version,
        "analyzerVersion": ANALYZER_VERSION,
        "coreBaseSha": sha,
        "evidenceReceiptSha256": evidence_digest,
        "coreManifest": manifest,
        "moduleInventory": sorted(modules, key=lambda item: item["path"]),
        "symbolInventory": sorted(symbols, key=lambda item: (item["path"], item["line"], item["name"])),
        "dependencyEdges": sorted(edges, key=lambda item: (item["from"], item["to"])),
        "externalDependencies": sorted(external),
        "invariantInventory": sorted(invariant_inventory, key=lambda item: item["id"]),
        "boundaryInventory": sorted(boundary_inventory, key=lambda item: item["id"]),
        "schemaBaseline": {"paths": sorted(item["path"] for item in manifest if item["category"] == "SCHEMA")},
        "schemaDependencies": sorted({schema for item in boundary_inventory for schema in (item.get("schemas") or [])}),
        "configDependencies": sorted(item["path"] for item in manifest if item["category"] in {"INVARIANT", "BOUNDARY", "QUALITY_CONFIG"}),
        "fixtureBaseline": {"registeredCount": len(fixtures.get("fixtures", [])), "paths": sorted(item["arquivo"] for item in fixtures.get("fixtures", []))},
        "testBaseline": {
            "testFiles": sorted(item["path"] for item in manifest if item["category"] == "TEST"),
            "propertyTests": ["tests/test_core_properties.py", "tests/test_core_properties_v2.py"],
            "e2ePositive": "tests/test_final_closure_r7.py",
            "e2eNegative": "tests/test_aceitacao_final_motor_v1.py",
            "evidenceLevels": ["PROVEN_BY_TEST", "PROTECTED_BY_GATE", "DOCUMENTED_ONLY", "NOT_YET_PROVEN"],
        },
        "behavioralBaseline": behavioral,
        "gateBaseline": evidence.get("gateBaseline", []) if evidence else [],
        "hotspotMetrics": hotspot_metrics,
        "metricDefinition": {"version": "1.0.0", "decisionCountCandidate": "1 + AST branch nodes + boolean operands + try paths", "complexityIsAutomaticRefactorTrigger": False},
        "riskRegister": [
            {"id": "RISK-HOTSPOT-MOTOR", "category": "COMPLEXITY", "intrinsicRisk": "HIGH", "robustness": "B", "engineeringPriority": 1, "evidence": ["scripts/motor_vicios/motor.py::executar", "tests/test_core_properties.py"], "observation": "Dense evidence, causality, norm, coverage and gate orchestration; metrics are signals, not a refactor trigger."},
            {"id": "RISK-HOTSPOT-DELIMITATION", "category": "COUPLING", "intrinsicRisk": "HIGH", "robustness": "C", "engineeringPriority": 1, "evidence": ["scripts/triagem_pericial/gerar_delimitacao.py::gerar"], "observation": "Domain-producing entrypoint reads repository-layout paths and emits wall-clock metadata."},
            {"id": "RISK-HOTSPOT-PLANNING", "category": "TESTABILITY", "intrinsicRisk": "HIGH", "robustness": "B", "engineeringPriority": 2, "evidence": ["scripts/planejamento_pericial/gerar_plano.py::gerar"], "observation": "Planning, coverage, provenance and status share an entrypoint with filesystem/time coupling."},
            {"id": "RISK-REPLAY-NONDETERMINISM", "category": "REPLAY", "intrinsicRisk": "MEDIUM", "robustness": "C", "engineeringPriority": 2, "evidence": ["scripts/motor_vicios/pipeline.py", "scripts/triagem_pericial/gerar_delimitacao.py", "scripts/planejamento_pericial/gerar_plano.py"], "observation": "UUID/time metadata requires normalization in future replay and semantic determinism work."},
            {"id": "RISK-ARCHITECTURE-GATE-ABSENT", "category": "ARCHITECTURE_BOUNDARY", "intrinsicRisk": "MEDIUM", "robustness": "D", "engineeringPriority": 1, "evidence": ["docs/arquitetura/arquitetura-core-pericial.md", "config/core-boundaries.json"], "observation": "Core authority is documented and boundaries exist, but target layer direction is not yet mechanically enforced."},
        ],
        "gapMatrix": [
            {"area": "Architecture Constitution", "currentState": "Core authority documented", "evidence": ["docs/arquitetura/arquitetura-core-pericial.md"], "gap": "Layer ownership and dependency direction not fully constituted", "nextProgramStage": "ARCHITECTURE_CONSTITUTION_AND_GATE_V1"},
            {"area": "Architecture Gate", "currentState": "Boundary path registry and change-impact gate", "evidence": ["config/core-boundaries.json", "scripts/quality/change_impact.py"], "gap": "No UI/API/Infrastructure -> Application -> Core import gate", "nextProgramStage": "ARCHITECTURE_CONSTITUTION_AND_GATE_V1"},
            {"area": "Hotspot Characterization", "currentState": "Static metrics and existing regression tests", "evidence": ["config/quality-baseline.json", "tests/test_core_properties.py"], "gap": "No complete entrypoint characterization matrix", "nextProgramStage": "HOTSPOT_CHARACTERIZATION_V1"},
            {"area": "Golden Forensic Corpus", "currentState": "Synthetic fixtures and E2E positive/negative", "evidence": ["tests/fixtures/core-fixtures.json"], "gap": "No future Golden Forensic Corpus", "nextProgramStage": "GOLDEN_FORENSIC_CORPUS_V1"},
            {"area": "Semantic Determinism", "currentState": "Idempotence and order invariance registered", "evidence": ["config/core-invariants.json", "tests/test_core_properties.py"], "gap": "Time/UUID normalization and full semantic determinism contract pending", "nextProgramStage": "SEMANTIC_DETERMINISM_V1"},
            {"area": "Replay", "currentState": "No canonical replay harness", "evidence": ["scripts/motor_vicios/pipeline.py"], "gap": "Replay identity and normalization pending", "nextProgramStage": "REPLAY_V1"},
            {"area": "Critical Mutation", "currentState": "Historical critical mutation suite", "evidence": ["config/historical-mutants.json", "scripts/quality/historical_mutations.py"], "gap": "Campaign expansion remains future work", "nextProgramStage": "CRITICAL_MUTATION_V1"},
            {"area": "Fault Injection", "currentState": "Quality V2 fault tests", "evidence": ["tests/test_quality_hardening_v2.py"], "gap": "Domain-wide fault matrix pending", "nextProgramStage": "FAULT_INJECTION_V1"},
            {"area": "Terminal Stable Audit", "currentState": "Independent review protocols and gates", "evidence": ["docs/padroes/protocolo-revisao-multiagente.md"], "gap": "Final stable audit follows all stabilization stages", "nextProgramStage": "TERMINAL_STABLE_AUDIT_V1"},
        ],
    }
    payload["semanticFingerprint"] = hashlib.sha256(semantic_bytes(payload)).hexdigest()
    return payload


def verify_baseline(payload: dict, expected_fingerprint: str) -> list[str]:
    actual = hashlib.sha256(semantic_bytes(payload)).hexdigest()
    if payload.get("semanticFingerprint") != actual or actual != expected_fingerprint.strip():
        return ["BASELINE_FINGERPRINT_MISMATCH"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fingerprint", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    evidence = json.loads(args.evidence.read_text(encoding="utf-8")) if args.evidence else None
    payload = build_baseline(args.repo, args.sha, evidence=evidence)
    data = canonical_bytes(payload)
    digest = hashlib.sha256(semantic_bytes(payload)).hexdigest()
    if args.check:
        if not args.output or not args.fingerprint or not args.output.is_file() or not args.fingerprint.is_file():
            print("BASELINE_ARTIFACT_MISSING", file=sys.stderr); return 1
        findings = []
        if args.output.read_bytes() != data: findings.append("BASELINE_PAYLOAD_MISMATCH")
        findings.extend(verify_baseline(payload, args.fingerprint.read_text(encoding="ascii")))
        if findings:
            print("\n".join(findings), file=sys.stderr); return 1
        print(f"BASELINE_OK {digest}"); return 0
    if not args.output or not args.fingerprint:
        print("output and fingerprint are required", file=sys.stderr); return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    args.fingerprint.write_text(digest + "\n", encoding="ascii")
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
