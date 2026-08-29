import hashlib
import json
import subprocess
import threading
from pathlib import Path


from scripts.quality.change_impact import impact_for_paths, main as impact_main
from scripts.quality.config import registry_lock, validate_configuration
from scripts.quality.fixture_registry import validate_fixture_registry
from scripts.quality import verify_core
from scripts.quality.verify_core import GateResult, check_private_tracking, run_gate


ROOT = Path(__file__).resolve().parents[1]


PROTECTED_TIMING_SURFACE_SHA256 = {
    ".github/workflows/core-safety.yml": "5a499f0844e528f46c34a57d7663addd0d69b2a000d9a677da57bbc953158765",
    "scripts/quality/__init__.py": "b3824e776de859b9a48131b04cfc738c925badc4d42c0475eaf919e4e1665e5b",
    "scripts/quality/verify_core.py": "ae2e5928db5917fd4d9f4e9ad8ec9c13e65ebd4ade9f533ab0235b3440275598",
    "scripts/quality/architecture_analyzer.py": "b0ebd34400c0a456b14e44eea747cfa88c30d1f988a2659d75087f2cf6fdf036",
    "scripts/quality/capability_analyzer.py": "a082879716d75e2b35c271ab89b93b13b4e56163592cb4f522b924eace766303",
}


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


def _write_timing_gate_inputs(root: Path) -> None:
    _write(root / "config/quality-baseline.json", {
        "coverage": {"line_percent": 100.0, "branch_percent": 100.0},
        "hotspots": [],
        "full_gate_max_seconds": 60.0,
    })
    _write(root / "coverage-quality-v2.json", {
        "totals": {
            "num_statements": 1,
            "covered_lines": 1,
            "num_branches": 0,
            "covered_branches": 0,
        },
    })


def _successful_gate_runner(command, **_):
    return subprocess.CompletedProcess(command, 0, "", "")


def _run_timed_pull_request_gate(monkeypatch, tmp_path, runner=_successful_gate_runner, tracked_files=None):
    _write_timing_gate_inputs(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setattr(verify_core, "validate_configuration", lambda _root: [])
    monkeypatch.setattr(verify_core, "validate_fixture_registry", lambda _root: [])
    timestamps = iter((0.0, 61.0, 61.0))
    monkeypatch.setattr(verify_core.time, "perf_counter", lambda: next(timestamps))
    return run_gate(
        "full",
        tmp_path,
        runner=runner,
        tracked_files=[] if tracked_files is None else tracked_files,
    )


def test_pull_request_timing_warning_does_not_fail_an_otherwise_green_gate(monkeypatch, tmp_path, capsys):
    result = _run_timed_pull_request_gate(monkeypatch, tmp_path)

    assert result.result == "PASS"
    assert result.exit_code == 0
    assert ("quality non-regression", True) in result.checks
    assert result.findings == ()
    assert "TIMING_STATUS = WARNING" in capsys.readouterr().out


def test_pull_request_timing_warning_never_masks_semantic_command_failure(monkeypatch, tmp_path):
    def runner(command, **_):
        failed = "tests/test_core_properties.py" in command
        return subprocess.CompletedProcess(command, 7 if failed else 0, "", "semantic failure" if failed else "")

    result = _run_timed_pull_request_gate(monkeypatch, tmp_path, runner=runner)

    assert result.result == "FAIL"
    assert result.exit_code != 0
    assert any(item["teste"] == "property tests" for item in result.findings)


def test_pull_request_timing_warning_never_masks_regression_failure(monkeypatch, tmp_path):
    def runner(command, **_):
        failed = "coverage" in command and "run" in command
        return subprocess.CompletedProcess(command, 7 if failed else 0, "", "regression failure" if failed else "")

    result = _run_timed_pull_request_gate(monkeypatch, tmp_path, runner=runner)

    assert result.result == "FAIL"
    assert result.exit_code != 0
    assert any(item["teste"] == "regression" and item["severidade"] == "P0" for item in result.findings)


def test_pull_request_timing_warning_never_masks_private_tracking(monkeypatch, tmp_path):
    result = _run_timed_pull_request_gate(
        monkeypatch,
        tmp_path,
        tracked_files=["referencias/privadas/caso.pdf"],
    )

    assert result.result == "FAIL"
    assert result.exit_code != 0
    assert any(item["invariant"] == "PII_DENY_BY_DEFAULT" for item in result.findings)


def test_pr_timing_observability_preserves_protected_execution_surface():
    observed = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in PROTECTED_TIMING_SURFACE_SHA256
    }
    assert observed == PROTECTED_TIMING_SURFACE_SHA256


def test_pr_timing_observability_keeps_immutable_sixty_second_target():
    baseline = json.loads((ROOT / "config/quality-baseline.json").read_text(encoding="utf-8"))
    assert baseline["full_gate_max_seconds"] == 60.0


def test_full_gate_overlaps_independent_mutation_and_regression_suites():
    regression_started = threading.Event()
    e2e_started = threading.Event()
    capability_started = threading.Event()
    overlaps = {}

    def runner(command, **_):
        joined = " ".join(command)
        if "coverage run" in joined:
            regression_started.set()
            overlaps["e2e"] = e2e_started.wait(timeout=0.5)
            overlaps["capability"] = capability_started.wait(timeout=0.5)
        elif "historical_critical_mutants_are_all_killed" in joined:
            overlaps["mutation"] = regression_started.wait(timeout=0.5)
        elif joined.endswith("tests/test_core_properties.py"):
            overlaps["property"] = regression_started.wait(timeout=0.5)
        elif "test_final_closure_r7.py" in joined:
            e2e_started.set()
        elif "pytest -q tests/test_capability_analyzer_v1.py" in joined:
            capability_started.set()
        return subprocess.CompletedProcess(command, 0, "", "")

    run_gate("full", ROOT, runner=runner, tracked_files=[])

    assert overlaps == {"property": True, "mutation": True, "e2e": True, "capability": True}


def test_architecture_findings_are_enforced_by_protected_workflow():
    workflow = (ROOT / ".github/workflows/architecture-protected.yml").read_text(encoding="utf-8")
    assert "pull_request_target" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "run_architecture_gate" in workflow
    assert "sys.exit(1 if findings else 0)" in workflow


def test_architecture_trust_boundary_suite_is_partitioned_from_timed_regression():
    # scripts/quality/verify_core.py itself must stay untouched: it is also a
    # capability-protected artifact, and this partition is deliberately kept
    # workflow-owned (PYTEST_ADDOPTS) to avoid a second, unrelated trust-boundary
    # rotation for a change that is really about CI orchestration only.
    workflow = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")
    step_blocks = workflow.split("\n      - ")

    architecture_blocks = [
        block for block in step_blocks if "tests/test_architecture_analyzer_v1.py" in block
        and "PYTEST_ADDOPTS" not in block
    ]
    assert len(architecture_blocks) == 1
    architecture_step = architecture_blocks[0]
    assert "run: python -m pytest -q tests/test_architecture_analyzer_v1.py" in architecture_step
    assert "continue-on-error" not in architecture_step
    assert "\n        if:" not in architecture_step

    verify_core_blocks = [
        block for block in step_blocks if "scripts.quality.verify_core --full" in block
    ]
    assert len(verify_core_blocks) == 1
    verify_core_step = verify_core_blocks[0]
    assert 'PYTEST_ADDOPTS: "--ignore=tests/test_architecture_analyzer_v1.py"' in verify_core_step
    assert "continue-on-error" not in verify_core_step
    assert "\n        if:" not in verify_core_step


def test_core_safety_workflow_never_hoists_env_above_step_level():
    # PYTEST_ADDOPTS must stay step-scoped (8-space indent under the Verify
    # frozen Core V1 step). A future job-level (4-space) or workflow-level
    # (0-space) `env:` block would apply to every step in the job, including
    # "Architecture trust-boundary suite" — and unlike --ignore, a filter such
    # as -k/-m/--deselect silently zeroes out that step's explicit-path pytest
    # invocation (0 collected, exit code 0) rather than erroring, so the
    # per-step string checks above would not catch it. Guard the YAML
    # structure directly instead of relying on step-block text alone.
    workflow_lines = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8").splitlines()
    non_step_env_lines = [line for line in workflow_lines if line in {"env:", "    env:"}]
    assert non_step_env_lines == []


def test_verify_core_regression_command_excludes_heavy_trust_boundary_suites():
    # Superseded design note: the original architecture-only partition (PR #63/#64)
    # deliberately kept verify_core.py byte-identical to main and injected the
    # exclusion purely via the workflow's PYTEST_ADDOPTS, specifically to avoid
    # touching a capability-protected artifact before the cross-control-plane
    # handshake existed (see PR #65/#66). That handshake now lets a real
    # capability rotation also authorize an exact verify_core.py change, so this
    # PR's own rotation legitimately hardcodes the growing set of heavy
    # architecture/capability trust-boundary suites directly into the "regression"
    # command's ignore list (in addition to, not instead of, the workflow-level
    # PYTEST_ADDOPTS for the architecture suite specifically) — every excluded
    # suite still runs, just outside the 60-second timed budget, either via its
    # own dedicated CI step or a separate explicit verify_core stage.
    captured = {}

    def runner(command, **_):
        joined = " ".join(command)
        if "coverage run" in joined:
            captured["regression"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    run_gate("full", ROOT, runner=runner, tracked_files=[])

    for excluded in (
        "--ignore=tests/test_architecture_analyzer_v1.py",
        "--ignore=tests/test_architecture_capability_trust_anchor_v1.py",
        "--ignore=tests/test_architecture_capability_control_plane_rotation_v1.py",
        "--ignore=tests/test_capability_analyzer_v1.py",
        "--ignore=tests/test_capability_exceptions_v1.py",
        "--ignore=tests/test_capability_contracts_v1.py",
    ):
        assert excluded in captured["regression"]


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
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"pytest==9.1.1"' in project
    assert (ROOT / "uv.lock").is_file()


def test_safety_gate_v2_names_historical_and_quality_checks_without_renaming_ci():
    source = (ROOT / "scripts/quality/verify_core.py").read_text(encoding="utf-8")
    assert "historical critical mutation suite" in source
    assert "quality V2" in source
    core = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")
    assert "name: core-safety" in core
    assert "python -m scripts.quality.verify_core --full" in core


def test_quality_depth_is_optional_first_party_without_secrets_or_deploy():
    workflow = (ROOT / ".github/workflows/quality-depth.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in workflow and "schedule" in workflow
    assert "python -m scripts.quality.deep_quality" in workflow
    assert "secrets" not in workflow.casefold() and "deploy" not in workflow.casefold()
    assert "pull_request" not in workflow


def test_uv_is_the_single_dependency_authority_with_exact_dev_tools():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"mutmut==3.7.0"' in project
    assert '"coverage==7.15.4"' in project
    runtime_section, dev_section = project.split("[dependency-groups]", 1)
    assert "mutmut" not in runtime_section and "coverage" not in runtime_section
    assert "mutmut" in dev_section and "coverage" in dev_section
    runtime_export = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    dev_export = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert runtime_export.startswith("# This file was autogenerated by uv")
    assert dev_export.startswith("# This file was autogenerated by uv")
