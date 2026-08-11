import copy
import json
from pathlib import Path

import pytest

from scripts.backend_contract.errors import DomainError
from scripts.planejamento_pericial.migracoes import migrar_plano
from scripts.quality.schema_versions import validate_schema_version_matrix


ROOT = Path(__file__).resolve().parents[1]


def _legacy_plan() -> dict:
    current = json.loads((ROOT / "tests/fixtures/planejamento/plano-vistoria-valido.json").read_text(encoding="utf-8"))
    current["schema_version"] = "1.0.0"
    for requirement in current["requisitos_cobertura"]:
        requirement["id"] = "LEGACY-" + requirement["item_planejado"]
    return current


def test_schema_version_matrix_is_complete_and_fail_closed():
    matrix = json.loads((ROOT / "config/schema-versions.json").read_text(encoding="utf-8"))
    assert validate_schema_version_matrix(matrix, ROOT) == []
    assert all(item["future_version_policy"] == "FAIL_CLOSED" for item in matrix["schemas"])


def test_current_version_is_accepted_without_mutation():
    current = json.loads((ROOT / "tests/fixtures/planejamento/plano-vistoria-valido.json").read_text(encoding="utf-8"))
    assert migrar_plano(current) == current


def test_legacy_migration_is_deterministic_and_preserves_material_fields():
    legacy = _legacy_plan()
    first = migrar_plano(legacy)
    second = migrar_plano(copy.deepcopy(legacy))
    assert first == second
    assert first["schema_version"] == "2.0.0"
    for field in ("requisitos_cobertura", "atividades", "medicoes", "fotografias", "ensaios", "documentos_a_solicitar"):
        assert field in first
        assert len(first[field]) == len(legacy[field])
    assert all("id" not in item and item.get("item_planejado") for item in first["requisitos_cobertura"])


def test_migration_is_idempotent_after_reaching_current_version():
    migrated = migrar_plano(_legacy_plan())
    assert migrar_plano(migrated) == migrated


@pytest.mark.parametrize("version", ["3.0.0", "0.9.0", None])
def test_unknown_future_or_unmigratable_version_fails_closed(version):
    plan = _legacy_plan()
    plan["schema_version"] = version
    with pytest.raises(DomainError):
        migrar_plano(plan)


def test_legacy_without_safe_coverage_identity_fails_explicitly():
    plan = _legacy_plan()
    plan["requisitos_cobertura"] = []
    with pytest.raises(DomainError):
        migrar_plano(plan)
