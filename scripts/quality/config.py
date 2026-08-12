"""Load and validate the canonical invariant and boundary registries."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

INVARIANT_FIELDS = {"id", "descricao", "severidade", "boundaries", "testes", "global", "bloqueante"}
BOUNDARY_FIELDS = {"id", "paths", "invariants", "schemas", "tests", "consumers"}
FROZEN_CORE_SHA = "71dea5d95d9843d08fe1547b6b52812ddd060511"


def _fingerprint(values) -> str:
    payload=json.dumps(sorted(values),ensure_ascii=True,separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def registry_lock(invariant_doc: dict, boundary_doc: dict, core_base_sha: str) -> dict:
    invariant_ids=[item.get("id") for item in invariant_doc.get("invariants",[]) if isinstance(item,dict)]
    boundary_ids=[item.get("id") for item in boundary_doc.get("boundaries",[]) if isinstance(item,dict)]
    return {"schema_version":"1.0.0","core_base_sha":core_base_sha,
            "invariants_count":len(invariant_ids),"invariants_fingerprint":_fingerprint(invariant_ids),
            "boundaries_count":len(boundary_ids),"boundaries_fingerprint":_fingerprint(boundary_ids)}


def load_registries(root: Path) -> tuple[dict, dict]:
    with (root / "config/core-invariants.json").open(encoding="utf-8") as stream:
        invariants = json.load(stream)
    with (root / "config/core-boundaries.json").open(encoding="utf-8") as stream:
        boundaries = json.load(stream)
    return invariants, boundaries


def _finding(invariant: str, boundary: str, test: str, reason: str, severity: str = "P1") -> dict:
    return {"invariant": invariant, "boundary": boundary, "teste": test, "motivo": reason, "severidade": severity}


def validate_configuration(root: Path) -> list[dict]:
    try:
        invariant_doc, boundary_doc = load_registries(root)
    except (OSError, json.JSONDecodeError) as exc:
        return [_finding("CONFIGURATION", "REPOSITORY", "registry", str(exc), "P0")]
    findings: list[dict] = []
    invariants = invariant_doc.get("invariants")
    boundaries = boundary_doc.get("boundaries")
    if invariant_doc.get("schema_version") != "1.0.0" or not isinstance(invariants, list):
        findings.append(_finding("CONFIGURATION", "REPOSITORY", "core-invariants.json", "config de invariantes inválida", "P0"))
        invariants = invariants if isinstance(invariants, list) else []
    if boundary_doc.get("schema_version") != "1.0.0" or not isinstance(boundaries, list):
        findings.append(_finding("CONFIGURATION", "REPOSITORY", "core-boundaries.json", "config de boundaries inválida", "P0"))
        boundaries = boundaries if isinstance(boundaries, list) else []
    if not invariants:
        findings.append(_finding("CONFIGURATION", "REPOSITORY", "core-invariants.json", "registro de invariantes vazio", "P0"))
    if not boundaries:
        findings.append(_finding("CONFIGURATION", "REPOSITORY", "core-boundaries.json", "registro de boundaries vazio", "P0"))
    invariant_ids = {item.get("id") for item in invariants if isinstance(item, dict)}
    boundary_ids = {item.get("id") for item in boundaries if isinstance(item, dict)}
    lock = {}
    try:
        lock=json.loads((root/"config/core-registry-lock.json").read_text(encoding="utf-8"))
        expected=registry_lock(invariant_doc,boundary_doc,lock.get("core_base_sha"))
        if lock != expected:
            findings.append(_finding("CONFIGURATION","REPOSITORY","core-registry-lock.json","registro diverge do lock canônico","P0"))
    except (OSError,json.JSONDecodeError) as exc:
        findings.append(_finding("CONFIGURATION","REPOSITORY","core-registry-lock.json",f"lock ausente ou inválido: {exc}","P0"))
    if None in invariant_ids or len(invariant_ids) != len(invariants):
        findings.append(_finding("CONFIGURATION", "REPOSITORY", "core-invariants.json", "IDs de invariantes ausentes ou duplicados", "P0"))
    if None in boundary_ids or len(boundary_ids) != len(boundaries):
        findings.append(_finding("CONFIGURATION", "REPOSITORY", "core-boundaries.json", "IDs de boundaries ausentes ou duplicados", "P0"))
    for item in invariants:
        if not isinstance(item, dict) or not INVARIANT_FIELDS <= set(item):
            findings.append(_finding("CONFIGURATION", "REPOSITORY", "core-invariants.json", "invariante sem configuração completa", "P0")); continue
        if item["severidade"] not in {"P0", "P1", "P2"} or not isinstance(item["global"], bool) or not isinstance(item["bloqueante"], bool):
            findings.append(_finding(item["id"], "REPOSITORY", "core-invariants.json", "tipos ou severidade inválidos", "P0"))
        if not item["testes"]:
            findings.append(_finding(item["id"], "REPOSITORY", "registry", "invariante sem teste associado", item["severidade"]))
        for test in item["testes"]:
            if not (root / test.split("::", 1)[0]).is_file():
                findings.append(_finding(item["id"], "REPOSITORY", test, "teste associado inexistente", item["severidade"]))
        for boundary in item["boundaries"]:
            if boundary not in boundary_ids:
                findings.append(_finding(item["id"], boundary, "core-invariants.json", "boundary desconhecido", "P0"))
    for item in boundaries:
        if not isinstance(item, dict) or not BOUNDARY_FIELDS <= set(item):
            findings.append(_finding("CONFIGURATION", str(item.get("id") if isinstance(item, dict) else "UNKNOWN"), "core-boundaries.json", "boundary sem configuração completa", "P0")); continue
        if not item["paths"] or not item["tests"] or not item["invariants"]:
            findings.append(_finding("CONFIGURATION", item["id"], "core-boundaries.json", "boundary sem paths, invariantes ou testes", "P0"))
        for invariant in item["invariants"]:
            if invariant not in invariant_ids:
                findings.append(_finding(invariant, item["id"], "core-boundaries.json", "invariante desconhecido", "P0"))
            else:
                declared = next(inv for inv in invariants if inv.get("id") == invariant)
                if item["id"] not in declared.get("boundaries", []):
                    findings.append(_finding(invariant, item["id"], "registry symmetry", "boundary não declarado pelo invariante", "P1"))
        for consumer in item["consumers"]:
            if consumer not in boundary_ids:
                findings.append(_finding("CONFIGURATION",item["id"],"core-boundaries.json",f"consumer inexistente: {consumer}","P1"))
        for test in item["tests"]:
            if not (root / test.split("::", 1)[0]).is_file():
                findings.append(_finding("CONFIGURATION", item["id"], test, "teste de boundary inexistente", "P1"))
    for invariant in invariants:
        for boundary_id in invariant.get("boundaries", []):
            boundary = next((item for item in boundaries if item.get("id") == boundary_id), None)
            if boundary and invariant.get("id") not in boundary.get("invariants", []):
                findings.append(_finding(invariant["id"], boundary_id, "registry symmetry", "invariante não declarado pelo boundary", "P1"))
    if lock.get("core_base_sha") == FROZEN_CORE_SHA:
        from .historical_mutations import load_mutants, validate_historical_registry, validate_mutant_definitions
        from .metrics import analyze_complexity, validate_complexity_baseline
        from .schema_versions import validate_schema_version_matrix
        required = ("historical-bugs.json", "historical-mutants.json", "schema-versions.json", "quality-baseline.json")
        for name in required:
            if not (root / "config" / name).is_file():
                findings.append(_finding("CONFIGURATION", "QUALITY_GATE", name, "configuração V2 ausente", "P1"))
        if all((root / "config" / name).is_file() for name in required):
            historical = json.loads((root / "config/historical-bugs.json").read_text(encoding="utf-8"))
            for item in validate_historical_registry(historical, root):
                findings.append(_finding("HISTORICAL_REGRESSION", "QUALITY_GATE", item["bug_id"], item["code"], "P1"))
            for item in validate_mutant_definitions(load_mutants(root), root):
                findings.append(_finding("HISTORICAL_REGRESSION", "QUALITY_GATE", item["bug_id"], item["code"], "P1"))
            matrix = json.loads((root / "config/schema-versions.json").read_text(encoding="utf-8"))
            for item in validate_schema_version_matrix(matrix, root):
                findings.append(_finding("SCHEMA_VERSION_FIDELITY", "QUALITY_GATE", item["schema"], item["code"], "P1"))
            baseline = json.loads((root / "config/quality-baseline.json").read_text(encoding="utf-8"))
            paths = [root / item["path"] for item in baseline.get("hotspots", [])]
            complexity = analyze_complexity(paths, base=root) if paths and all(path.is_file() for path in paths) else []
            for item in validate_complexity_baseline(baseline, complexity):
                findings.append(_finding("QUALITY_NON_REGRESSION", "QUALITY_GATE", item["code"], str(item), "P1"))
    return findings
