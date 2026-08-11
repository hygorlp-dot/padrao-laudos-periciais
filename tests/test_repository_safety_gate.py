import json
import subprocess
from pathlib import Path

import pytest

from scripts.quality.change_impact import impact_for_paths, main as impact_main
from scripts.quality.config import registry_lock, validate_configuration
from scripts.quality.fixture_registry import validate_fixture_registry
from scripts.quality import verify_core
from scripts.quality.verify_core import GateResult, check_private_tracking, run_gate


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _valid_config(root: Path) -> None:
    _write(root / "config/core-invariants.json", {"schema_version": "1.0.0", "invariants": [{
        "id": "FAIL_CLOSED", "descricao": "Falhar fechado", "severidade": "P0",
        "boundaries": ["TRIAGE"], "testes": ["tests/test_gate.py"], "global": True, "bloqueante": True,
    }]})
    _write(root / "config/core-boundaries.json", {"schema_version": "1.0.0", "boundaries": [{
        "id": "TRIAGE", "paths": ["scripts/triagem_pericial/"], "invariants": ["FAIL_CLOSED"],
        "schemas": [], "tests": ["tests/test_gate.py"], "consumers": [],
    }]})
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests/test_gate.py").write_text("def test_gate(): pass\n", encoding="utf-8")
    invariants=json.loads((root/"config/core-invariants.json").read_text())
    boundaries=json.loads((root/"config/core-boundaries.json").read_text())
    _write(root/"config/core-registry-lock.json",registry_lock(invariants,boundaries,"synthetic"))


def test_invalid_invariant_and_boundary_without_configuration_fail(tmp_path):
    _valid_config(tmp_path)
    invariants = json.loads((tmp_path / "config/core-invariants.json").read_text())
    invariants["invariants"][0]["testes"] = []
    _write(tmp_path / "config/core-invariants.json", invariants)
    boundaries = json.loads((tmp_path / "config/core-boundaries.json").read_text())
    boundaries["boundaries"].append({"id": "MOTOR"})
    _write(tmp_path / "config/core-boundaries.json", boundaries)
    findings = validate_configuration(tmp_path)
    assert {item["invariant"] for item in findings} >= {"FAIL_CLOSED", "CONFIGURATION"}


def test_empty_registries_and_asymmetric_mapping_fail(tmp_path):
    _write(tmp_path / "config/core-invariants.json", {"schema_version":"1.0.0","invariants":[]})
    _write(tmp_path / "config/core-boundaries.json", {"schema_version":"1.0.0","boundaries":[]})
    assert validate_configuration(tmp_path)
    _valid_config(tmp_path)
    boundaries=json.loads((tmp_path/"config/core-boundaries.json").read_text())
    boundaries["boundaries"][0]["invariants"].append("EXTRA")
    _write(tmp_path/"config/core-boundaries.json",boundaries)
    assert validate_configuration(tmp_path)


def test_truncated_registry_and_missing_consumer_fail(tmp_path):
    _valid_config(tmp_path)
    boundaries=json.loads((tmp_path/"config/core-boundaries.json").read_text())
    boundaries["boundaries"][0]["consumers"]=["MISSING_CONSUMER"]
    _write(tmp_path/"config/core-boundaries.json",boundaries)
    assert validate_configuration(tmp_path)
    boundaries["boundaries"][0]["consumers"]=[]
    _write(tmp_path/"config/core-boundaries.json",boundaries)
    invariants=json.loads((tmp_path/"config/core-invariants.json").read_text())
    _write(tmp_path/"config/core-registry-lock.json",registry_lock(invariants,boundaries,"synthetic"))
    invariants["invariants"]=[]
    _write(tmp_path/"config/core-invariants.json",invariants)
    assert validate_configuration(tmp_path)


def test_fixture_registry_detects_orphan_stale_and_unexercised(tmp_path):
    fixtures = tmp_path / "tests/fixtures"
    _write(fixtures / "orphan.json", {"x": 1})
    _write(fixtures / "core-fixtures.json", {"schema_version": "1.0.0", "fixtures": [{
        "arquivo": "tests/fixtures/missing.json", "dominio": "CORE", "schema": None,
        "consumer": "tests/test_missing.py", "finalidade": "stale", "expected": "VALID",
    }]})
    findings = validate_fixture_registry(tmp_path)
    reasons = {item["motivo"] for item in findings}
    assert {"FIXTURE_ORFA", "REGISTRY_STALE", "FIXTURE_NAO_EXERCITADA"} <= reasons


def test_fixture_consumer_must_be_real_node_that_references_fixture(tmp_path):
    _write(tmp_path/"tests/fixtures/case.json",{"x":1})
    _write(tmp_path/"tests/fixtures/core-fixtures.json",{"schema_version":"1.0.0","fixtures":[{
        "arquivo":"tests/fixtures/case.json","dominio":"CORE","schema":None,
        "consumer":"tests/test_unrelated.py::test_unrelated","finalidade":"case","expected":"DATASET"}]})
    (tmp_path/"tests/test_unrelated.py").write_text("def test_unrelated(): assert True\n",encoding="utf-8")
    findings=validate_fixture_registry(tmp_path)
    assert any(item["motivo"]=="FIXTURE_NAO_EXERCITADA" for item in findings)


def test_schema_discovery_requires_real_configured_fixture_directory(tmp_path):
    _write(tmp_path/"tests/fixtures/x/case.json",{"x":1})
    _write(tmp_path/"tests/fixtures/core-fixtures.json",{"schema_version":"1.0.0","fixtures":[{
        "arquivo":"tests/fixtures/x/case.json","dominio":"CORE","schema":None,
        "consumer":"scripts/validar_schemas.py::principal","finalidade":"case","expected":"DATASET"}]})
    (tmp_path/"scripts").mkdir(parents=True)
    (tmp_path/"scripts/validar_schemas.py").write_text("marker='x'\ndef principal(): return 0\n",encoding="utf-8")
    assert any(item["motivo"]=="FIXTURE_NAO_EXERCITADA" for item in validate_fixture_registry(tmp_path))


def test_private_tracking_artificial_is_fail_closed():
    findings = check_private_tracking(["README.md", "referencias/privadas/caso.pdf"])
    assert findings and findings[0]["invariant"] == "PII_DENY_BY_DEFAULT"


def test_unknown_path_has_conservative_change_impact(tmp_path):
    _valid_config(tmp_path)
    impact = impact_for_paths(["novo/diretorio/arquivo.py"], tmp_path)
    assert impact["conservative"] is True
    assert impact["boundaries"] == ["TRIAGE"]
    assert impact["invariants"] == ["FAIL_CLOSED"]


def test_verify_core_propagates_error_and_never_reports_false_pass(tmp_path):
    _valid_config(tmp_path)
    _write(tmp_path / "tests/fixtures/core-fixtures.json", {"schema_version": "1.0.0", "fixtures": []})

    def runner(command, **_):
        failed = "pytest" in command
        return subprocess.CompletedProcess(command, 7 if failed else 0, "", "synthetic failure" if failed else "")

    result = run_gate("fast", tmp_path, runner=runner, tracked_files=[])
    assert result.exit_code != 0
    assert result.result == "FAIL"
    assert any(item["teste"] == "property tests" for item in result.findings)


def test_verify_core_main_propagates_exit_code(monkeypatch):
    failed = GateResult("FAIL", 9, (), ({"invariant":"FAIL_CLOSED","boundary":"CORE","teste":"x","motivo":"y","severidade":"P0"},), 0.0)
    monkeypatch.setattr(verify_core, "run_gate", lambda *_args, **_kwargs: failed)
    assert verify_core.main(["--fast"]) == 9


def test_repository_configuration_is_complete_and_impact_is_specific():
    assert validate_configuration(ROOT) == []
    assert validate_fixture_registry(ROOT) == []
    impact = impact_for_paths(["scripts/extracao_pje/segmentar_documentos.py"], ROOT)
    assert {"PJE_EXTRACTION", "PJE_MANIFEST"} <= set(impact["boundaries"])
    assert {"NO_SILENT_LOSS", "NO_SILENT_PAGE_LOSS", "EXACT_PAGE_ACCOUNTING", "ORDER_INVARIANCE"} <= set(impact["invariants"])


def test_change_impact_cli_and_ci_use_first_party_gate(capsys):
    assert impact_main(["scripts/extracao_pje/segmentar_documentos.py"], root=ROOT) == 0
    output = capsys.readouterr().out
    assert "BOUNDARIES_TOUCHED" in output and "INVARIANTS_REQUIRED" in output
    workflow = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")
    assert "python -m scripts.quality.verify_core --full" in workflow
    assert "secrets" not in workflow.casefold() and "deploy" not in workflow.casefold()
    dependencies=(ROOT/"requirements-dev.txt").read_text(encoding="utf-8")
    assert "pytest==9.1.1" in dependencies
