import json
from pathlib import Path

import pytest

from scripts.quality.historical_mutations import validate_historical_registry
from scripts.quality.schema_versions import validate_schema_version_matrix
from scripts.quality.deep_quality import run_mutmut


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def test_historical_registry_rejects_missing_regression_and_mutation():
    registry = _load("historical-bugs.json")
    broken = json.loads(json.dumps(registry))
    broken["bugs"][0]["regression_tests"] = []
    broken["bugs"][0]["mutation_equivalent"] = None
    findings = validate_historical_registry(broken, ROOT)
    assert {item["code"] for item in findings} >= {
        "HISTORICAL_BUG_WITHOUT_REGRESSION",
        "HISTORICAL_BUG_WITHOUT_MUTATION",
    }


def test_historical_registry_covers_all_critical_mutants_and_existing_tests():
    findings = validate_historical_registry(_load("historical-bugs.json"), ROOT)
    assert findings == []
    mutants = {bug["mutation_equivalent"] for bug in _load("historical-bugs.json")["bugs"]}
    assert {f"MUT-{number:03d}" for number in range(1, 11)} <= mutants


def test_schema_version_matrix_rejects_unknown_policy_and_destructive_migration():
    matrix = _load("schema-versions.json")
    missing_policy = json.loads(json.dumps(matrix))
    del missing_policy["schemas"][0]["future_version_policy"]
    assert any(x["code"] == "SCHEMA_VERSION_WITHOUT_POLICY" for x in validate_schema_version_matrix(missing_policy, ROOT))

    destructive = json.loads(json.dumps(matrix))
    destructive["schemas"][0]["material_fields"] = ["campo_inexistente"]
    assert any(x["code"] == "MIGRATION_MATERIAL_FIELD_UNPROTECTED" for x in validate_schema_version_matrix(destructive, ROOT))


def test_quality_baseline_is_versioned_and_nonempty():
    baseline = _load("quality-baseline.json")
    assert baseline["schema_version"] == "1.0.0"
    assert baseline["coverage"]["line_percent"] > 0
    assert baseline["coverage"]["branch_percent"] > 0
    assert baseline["hotspots"]
    assert baseline["historical_mutants_total"] == 10


def test_quality_configuration_stale_fails_closed():
    registry = _load("historical-bugs.json")
    registry["core_base_sha"] = "stale"
    findings = validate_historical_registry(registry, ROOT)
    assert any(item["code"] == "QUALITY_CONFIG_STALE" for item in findings)


def test_no_private_fixture_is_registered():
    registry = _load("historical-bugs.json")
    serialized = json.dumps(registry, ensure_ascii=False).replace("\\", "/")
    assert "referencias/privadas/" not in serialized


def test_deep_mutation_tool_unavailable_fails_explicitly(monkeypatch):
    monkeypatch.setattr("scripts.quality.deep_quality.shutil.which", lambda _: None)
    assert run_mutmut() == 2


@pytest.mark.parametrize("name", ["SCHEMA_VERSION_FIDELITY", "MIGRATION_NO_SILENT_LOSS"])
def test_new_invariants_are_registered_and_bound(name):
    invariants = _load("core-invariants.json")["invariants"]
    boundaries = _load("core-boundaries.json")["boundaries"]
    assert name in {item["id"] for item in invariants}
    assert any(name in item["invariants"] for item in boundaries)
