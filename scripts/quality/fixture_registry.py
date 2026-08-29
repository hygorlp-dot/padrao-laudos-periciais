"""Validate the global fixture registry without opening private references."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


def _finding(reason: str, test: str, detail: str) -> dict:
    return {"invariant": "NO_SILENT_LOSS", "boundary": "REPOSITORY", "teste": test, "motivo": reason, "severidade": "P1", "detalhe": detail}


def _fixture_directories(source: str, root: Path) -> set[Path]:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(isinstance(target, ast.Name) and target.id == "PASTAS_FIXTURES" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            return set()
        directories: set[Path] = set()
        for item in node.value.elts:
            parts: list[str] = []
            while isinstance(item, ast.BinOp) and isinstance(item.op, ast.Div) and isinstance(item.right, ast.Constant) and isinstance(item.right.value, str):
                parts.append(item.right.value); item = item.left
            if not isinstance(item, ast.Name) or item.id != "RAIZ":
                return set()
            directories.add(root.joinpath(*reversed(parts)).resolve())
        return directories
    return set()


def validate_fixture_registry(root: Path) -> list[dict]:
    registry_path = root / "tests/fixtures/core-fixtures.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [_finding("REGISTRY_INVALIDO", str(registry_path), str(exc))]
    entries = registry.get("fixtures", [])
    registered = {entry.get("arquivo") for entry in entries if isinstance(entry, dict)}
    actual = {path.relative_to(root).as_posix() for path in (root / "tests/fixtures").rglob("*.json") if not path.name.endswith("registry.json") and path.name != "core-fixtures.json"}
    findings = [_finding("FIXTURE_ORFA", path, "arquivo sem registry") for path in sorted(actual - registered)]
    findings += [_finding("REGISTRY_STALE", path, "registry sem arquivo") for path in sorted(registered - actual)]
    required = {"arquivo", "dominio", "schema", "consumer", "finalidade", "expected"}
    discovery_directories: set[Path] = set()
    validator_path=root/"scripts/validar_schemas.py"
    if validator_path.is_file():
        try:
            discovery_directories=_fixture_directories(validator_path.read_text(encoding="utf-8"), root)
        except (OSError, SyntaxError, ValueError):
            discovery_directories=set()
    for entry in entries:
        if not isinstance(entry, dict) or not required <= set(entry):
            findings.append(_finding("REGISTRY_INVALIDO", str(entry), "campos obrigatórios ausentes")); continue
        consumer_spec = str(entry["consumer"]); parts = consumer_spec.split("::")
        consumer = root / parts[0]
        if not consumer.is_file() or len(parts) < 2:
            findings.append(_finding("FIXTURE_NAO_EXERCITADA", entry["arquivo"], str(entry["consumer"])))
        else:
            source=consumer.read_text(encoding="utf-8",errors="replace")
            symbols_ok=all(re.search(rf"\b(?:def|class)\s+{re.escape(symbol)}\b",source) for symbol in parts[1:])
            fixture=Path(entry["arquivo"])
            discovery=(consumer_spec=="scripts/validar_schemas.py::principal" and (root/fixture.parent).resolve() in discovery_directories)
            referenced=fixture.name in source or fixture.as_posix() in source
            if not symbols_ok or not (discovery or referenced):
                findings.append(_finding("FIXTURE_NAO_EXERCITADA", entry["arquivo"], consumer_spec))
        schema = entry.get("schema")
        if schema and not (root / "schemas" / schema).is_file():
            findings.append(_finding("SCHEMA_STALE", entry["arquivo"], schema))
        if entry.get("expected") not in {"VALID", "INVALID", "DATASET"}:
            findings.append(_finding("REGISTRY_INVALIDO", entry["arquivo"], "expected inválido"))
        if entry.get("provenance") != "SYNTHETIC":
            findings.append(_finding("FIXTURE_PROVENIENCIA_NAO_SINTETICA", entry["arquivo"], "provenance deve ser SYNTHETIC"))
    return findings
