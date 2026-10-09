"""Validate the global fixture registry without opening private references."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path


def _finding(reason: str, test: str, detail: str) -> dict:
    return {"invariant": "NO_SILENT_LOSS", "boundary": "REPOSITORY", "teste": test, "motivo": reason, "severidade": "P1", "detalhe": detail}


def _fixture_directory_names(source: str) -> set[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not any(isinstance(target, ast.Name) and target.id == "PASTAS_FIXTURES" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            return set()
        directories: set[str] = set()
        for item in node.value.elts:
            parts: list[str] = []
            while isinstance(item, ast.BinOp) and isinstance(item.op, ast.Div) and isinstance(item.right, ast.Constant) and isinstance(item.right.value, str):
                parts.append(item.right.value); item = item.left
            if not isinstance(item, ast.Name) or item.id != "RAIZ":
                return set()
            directories.add("/".join(reversed(parts)))
        return directories
    return set()


def _fixture_directories(source: str, root: Path) -> set[Path]:
    return {(root / name).resolve() for name in _fixture_directory_names(source)}


def validate_fixture_registry(root: Path, *, files=None, read_text=None) -> list[dict]:
    """Optional indexed reader lets hygiene reuse the registry without indirect I/O.

    Existing callers retain filesystem discovery. With an indexed reader, every
    consumer/validator/schema lookup stays in that public inventory.
    """
    indexed = frozenset(files) if files is not None else None

    def text(path):
        if indexed is not None:
            return read_text(path) if path in indexed else None
        try:
            return (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def exists(path):
        return text(path) is not None if indexed is not None else (root / path).is_file()

    registry_path = root / "tests/fixtures/core-fixtures.json"
    try:
        registry = json.loads(text("tests/fixtures/core-fixtures.json") or "")
    except (OSError, json.JSONDecodeError) as exc:
        return [_finding("REGISTRY_INVALIDO", str(registry_path), str(exc))]
    entries = registry.get("fixtures", [])
    registered = {entry.get("arquivo") for entry in entries if isinstance(entry, dict)}
    actual = {path for path in indexed if path.startswith("tests/fixtures/")
              and path != "tests/fixtures/core-fixtures.json"} if indexed is not None else {
        path.relative_to(root).as_posix()
        for path in (root / "tests/fixtures").rglob("*")
        if path.is_file()
        and path != registry_path
    }
    findings = [_finding("FIXTURE_ORFA", path, "arquivo sem registry") for path in sorted(actual - registered)]
    findings += [_finding("REGISTRY_STALE", path, "registry sem arquivo") for path in sorted(registered - actual)]
    required = {"arquivo", "dominio", "schema", "consumer", "finalidade", "expected"}
    discovery_directories = set()
    validator_source = text("scripts/validar_schemas.py")
    if validator_source is not None:
        try:
            discovery_directories = (_fixture_directory_names(validator_source) if indexed is not None
                                     else _fixture_directories(validator_source, root))
        except (OSError, SyntaxError, ValueError):
            discovery_directories=set()
    for entry in entries:
        if not isinstance(entry, dict) or not required <= set(entry):
            findings.append(_finding("REGISTRY_INVALIDO", str(entry), "campos obrigatórios ausentes")); continue
        consumer_spec = str(entry["consumer"]); parts = consumer_spec.split("::")
        source = text(parts[0])
        if source is None or len(parts) < 2:
            findings.append(_finding("FIXTURE_NAO_EXERCITADA", entry["arquivo"], str(entry["consumer"])))
        else:
            symbols_ok=all(re.search(rf"\b(?:def|class)\s+{re.escape(symbol)}\b",source) for symbol in parts[1:])
            fixture=Path(entry["arquivo"])
            directory = fixture.parent.as_posix() if indexed is not None else (root / fixture.parent).resolve()
            discovery=(consumer_spec=="scripts/validar_schemas.py::principal" and directory in discovery_directories)
            referenced=fixture.name in source or fixture.as_posix() in source
            if not symbols_ok or not (discovery or referenced):
                findings.append(_finding("FIXTURE_NAO_EXERCITADA", entry["arquivo"], consumer_spec))
        schema = entry.get("schema")
        if schema and not exists("schemas/" + schema):
            findings.append(_finding("SCHEMA_STALE", entry["arquivo"], schema))
        if entry.get("expected") not in {"VALID", "INVALID", "DATASET"}:
            findings.append(_finding("REGISTRY_INVALIDO", entry["arquivo"], "expected inválido"))
        if entry.get("provenance") != "SYNTHETIC":
            findings.append(_finding("FIXTURE_PROVENIENCIA_NAO_SINTETICA", entry["arquivo"], "provenance deve ser SYNTHETIC"))
    return findings
