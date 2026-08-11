"""Matriz mecânica dos contratos de versão e migração existentes."""
from __future__ import annotations

from pathlib import Path


def _finding(code: str, schema: str, detail: str) -> dict:
    return {"code": code, "schema": schema, "detail": detail, "severity": "P1"}


def validate_schema_version_matrix(matrix: dict, root: Path) -> list[dict]:
    findings: list[dict] = []
    schemas = matrix.get("schemas")
    if matrix.get("schema_version") != "1.0.0" or not isinstance(schemas, list) or not schemas:
        return [_finding("SCHEMA_VERSION_MATRIX_INVALID", "MATRIX", "matriz vazia ou versão inválida")]
    for item in schemas:
        name = item.get("schema", "SEM_SCHEMA")
        required = ("current_version", "versions_supported", "future_version_policy", "consumers", "material_fields")
        if any(key not in item for key in required):
            findings.append(_finding("SCHEMA_VERSION_WITHOUT_POLICY", name, "política incompleta"))
            continue
        schema_path = root / "schemas" / name
        if not schema_path.is_file():
            findings.append(_finding("SCHEMA_FILE_NOT_FOUND", name, str(schema_path)))
        migrator = item.get("migrator")
        if migrator and not (root / migrator.split(":", 1)[0]).is_file():
            findings.append(_finding("MIGRATOR_NOT_FOUND", name, migrator))
        protected = set(item.get("protected_material_fields", ()))
        material = set(item.get("material_fields", ()))
        if not material <= protected:
            findings.append(_finding("MIGRATION_MATERIAL_FIELD_UNPROTECTED", name, ",".join(sorted(material - protected))))
        if item["current_version"] not in item["versions_supported"]:
            findings.append(_finding("CURRENT_SCHEMA_VERSION_UNSUPPORTED", name, item["current_version"]))
        if item["future_version_policy"] != "FAIL_CLOSED":
            findings.append(_finding("FUTURE_SCHEMA_VERSION_NOT_FAIL_CLOSED", name, item["future_version_policy"]))
    return findings
