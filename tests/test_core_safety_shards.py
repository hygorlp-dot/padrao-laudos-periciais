"""V7-4A (#259): sharding do regression e agregador closed-set falham fechado.

Cada teste de mutação parte de uma evidência sintética VÁLIDA (que agrega PASS)
e aplica exatamente uma corrupção; o agregador precisa recusá-la.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from coverage import CoverageData

from scripts.quality import core_safety_shards as shards
from scripts.quality.core_safety_plan import gate_plan, stage


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
OTHER_SHA = "b" * 40
SOURCE = "def f(x):\n    if x:\n        return 1\n    return 2\n\n\ndef g():\n    return 3\n"
GATE_ARCS = [(-1, 1), (1, 7), (7, -1), (-1, 2), (2, 3), (3, -1)]
DRIFT_ARCS = [(-1, 1), (1, 7), (7, -1), (-1, 2), (2, 4), (4, -1)]
NEEDS_OK = {job: {"result": "success", "outputs": {}} for job in shards.REQUIRED_JOBS}
GATE_REPORT = "CORE SAFETY GATE\n\n" + "".join(f"[PASS] {name}\n" for name in shards.EXPECTED_GATE_CHECKS) + (
    "TARGET_SECONDS = 60.0\nOBSERVED_SECONDS = 300.0\nTIMING_STATUS = WARNING\n\nRESULT: PASS\nDURATION_SECONDS: 300.000\n"
)
SHARD_FILES = {"alpha": ["tests/test_b.py"], "beta": ["tests/test_c.py", "tests/test_d.py"]}
NODES = {
    "tests/test_a.py": ["tests/test_a.py::test_one", "tests/test_a.py::test_two"],
    "tests/test_b.py": ["tests/test_b.py::test_one"],
    "tests/test_c.py": ["tests/test_c.py::test_one", "tests/test_c.py::test_two[x]"],
    "tests/test_d.py": ["tests/test_d.py::test_one"],
    "tests/test_e2e.py": ["tests/test_e2e.py::test_e2e"],
}


def _argv() -> list[str]:
    return [sys.executable, "-m", "coverage", "run", "--branch", "--data-file=coverage-quality-v2.data",
            "--source=src", "-m", "pytest", "tests", "-q", "--ignore=tests/test_excluded.py"]


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _coverage(path: Path, root: Path, arcs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = CoverageData(str(path))
    data.add_arcs({str(root / "src" / "mod.py"): list(arcs)})
    data.write()


def _node_report(nodes, *, collect_only, outcome="passed", exitstatus=0):
    return {"schema": shards.NODE_REPORT_SCHEMA, "exitstatus": exitstatus, "collect_only": collect_only,
            "collected": sorted(nodes), "outcomes": {} if collect_only else {node: outcome for node in sorted(nodes)}}


def _repo(tmp_path: Path, *, line=60.0, branch=50.0) -> Path:
    root = tmp_path / "repo"
    for name in [*NODES, "tests/test_excluded.py", "tests/test_architecture_analyzer_v1.py"]:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("def test_one():\n    pass\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src/mod.py").write_text(SOURCE, encoding="utf-8")
    _write_json(root / shards.MANIFEST_PATH, {
        "schemaVersion": "1.0.0", "manifestId": shards.MANIFEST_ID,
        "shards": [{"id": shard_id, "files": files} for shard_id, files in SHARD_FILES.items()],
    })
    _write_json(root / "config/quality-baseline.json", {
        "coverage": {"line_percent": line, "branch_percent": branch}, "hotspots": [], "full_gate_max_seconds": 60.0,
    })
    return root


def _evidence(root: Path, tmp_path: Path) -> Path:
    evidence = tmp_path / "evidence"
    manifest_sha = shards.sha256_file(root / shards.MANIFEST_PATH)
    _coverage(evidence / "gate" / shards.GATE_DATA, root, GATE_ARCS)
    _write_json(evidence / "gate/gate-evidence.json", {
        "schema": shards.GATE_SCHEMA, "sha": SHA, "exit_code": 0, "manifest_sha256": manifest_sha,
        "report": GATE_REPORT, "coverage_file": shards.GATE_DATA,
        "coverage_sha256": shards.sha256_file(evidence / "gate" / shards.GATE_DATA),
    })
    offloaded = {path for files in SHARD_FILES.values() for path in files}
    full = [node for nodes in NODES.values() for node in nodes]
    gate = [node for path, nodes in NODES.items() if path not in offloaded for node in nodes]
    _write_json(evidence / "inventory/inventory-evidence.json", {
        "schema": shards.INVENTORY_SCHEMA, "sha": SHA, "manifest_sha256": manifest_sha,
        "full": _node_report(full, collect_only=True), "gate": _node_report(gate, collect_only=True),
    })
    for shard_id, files in SHARD_FILES.items():
        directory = evidence / f"shard-{shard_id}"
        data = directory / f"shard-{shard_id}.data"
        _coverage(data, root, GATE_ARCS[:3])
        _write_json(directory / "shard-evidence.json", {
            "schema": shards.SHARD_SCHEMA, "shard": shard_id, "sha": SHA, "exit_code": 0, "seconds": 12.5,
            "manifest_sha256": manifest_sha, "coverage_file": data.name, "coverage_sha256": shards.sha256_file(data),
            "nodes": _node_report([node for path in files for node in NODES[path]], collect_only=False),
        })
    return evidence


def _aggregate(root, evidence, *, sha=SHA, needs=None):
    return shards.aggregate(evidence, sha=sha, needs=NEEDS_OK if needs is None else needs,
                            root=root, workdir=evidence, argv=_argv())


def _edit(path: Path, change) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def valid(tmp_path):
    root = _repo(tmp_path)
    evidence = _evidence(root, tmp_path)
    summary = _aggregate(root, evidence)
    assert summary["result"] == "PASS", summary["errors"]
    assert summary["semantic_status"] == "PASS"
    assert [name for name, _ in summary["checks"]] == list(shards.EXPECTED_GATE_CHECKS)
    return root, evidence


def _assert_fails(root, evidence, code, **kwargs):
    summary = _aggregate(root, evidence, **kwargs)
    assert summary["result"] == "FAIL"
    assert any(error.startswith(code) for error in summary["errors"]), summary["errors"]
    return summary


# ------------------------------------------------------------------ manifest

def test_manifest_partition_is_derived_from_the_protected_regression_command(tmp_path):
    root = _repo(tmp_path)
    manifest = shards.load_manifest(root)
    assert shards.validate_manifest(manifest, root, _argv()) == []
    assert shards.regression_test_files(root, _argv()) == sorted(NODES)
    assert shards.gate_files(manifest, root, _argv()) == ["tests/test_a.py", "tests/test_e2e.py"]
    assert shards.gate_addopts(manifest) == (
        "--ignore=tests/test_b.py --ignore=tests/test_c.py --ignore=tests/test_d.py"
    )


@pytest.mark.parametrize(("mutate", "code"), [
    (lambda m: m["shards"][1]["files"].append("tests/test_b.py"), "SHARD_FILE_DUPLICATED"),
    (lambda m: m["shards"][0]["files"].append("tests/test_excluded.py"), "SHARD_FILE_NOT_IN_REGRESSION"),
    (lambda m: m["shards"][0]["files"].append("tests/test_architecture_analyzer_v1.py"), "SHARD_FILE_NOT_IN_REGRESSION"),
    (lambda m: m["shards"][0]["files"].append("tests/test_missing.py"), "SHARD_FILE_NOT_IN_REGRESSION"),
    (lambda m: m["shards"][1].update(id="alpha"), "SHARD_ID_DUPLICATED"),
    (lambda m: m["shards"][1].update(files=[]), "SHARD_EMPTY"),
    (lambda m: m["shards"][1].update(id="gate"), "SHARD_ID_INVALID"),
    (lambda m: m["shards"][1]["files"].reverse(), "SHARD_FILES_NOT_SORTED"),
    (lambda m: m.update(shards=[]), "MANIFEST_SHARDS_MISSING"),
    (lambda m: m.update(manifestId="OTHER"), "MANIFEST_ID_INVALID"),
    (lambda m: m["shards"].append({"id": "all", "files": ["tests/test_a.py", "tests/test_e2e.py"]}), "GATE_PARTITION_EMPTY"),
])
def test_invalid_manifest_is_rejected(tmp_path, mutate, code):
    root = _repo(tmp_path)
    manifest = shards.load_manifest(root)
    mutate(manifest)
    assert any(error.startswith(code) for error in shards.validate_manifest(manifest, root, _argv()))


def test_new_test_file_falls_into_gate_partition_and_is_never_lost(tmp_path):
    root = _repo(tmp_path)
    (root / "tests/test_new.py").write_text("def test_new():\n    pass\n", encoding="utf-8")
    manifest = shards.load_manifest(root)
    assert "tests/test_new.py" in shards.gate_files(manifest, root, _argv())
    assert "--ignore=tests/test_new.py" not in shards.gate_addopts(manifest)


def test_shard_argv_is_the_judge_regression_command_with_only_target_and_data_file_changed(tmp_path):
    root = _repo(tmp_path)
    manifest = shards.load_manifest(root)
    argv = shards.shard_argv(manifest, "beta", data_file="shard-beta.data", nodes_file="n.json", argv=_argv())
    expected = _argv()
    expected[5] = "--data-file=shard-beta.data"
    expected[9:10] = ["tests/test_c.py", "tests/test_d.py"]
    assert argv == expected + ["-p", shards.NODES_PLUGIN, "--core-safety-nodes=n.json"]
    with pytest.raises(shards.ShardError):
        shards.shard_argv(manifest, "missing", data_file="x", nodes_file="y", argv=_argv())


def test_collect_argv_reproduces_full_and_gate_partitions(tmp_path):
    root = _repo(tmp_path)
    manifest = shards.load_manifest(root)
    full = shards.collect_argv(manifest, "full", nodes_file="f.json", python="py", argv=_argv())
    gate = shards.collect_argv(manifest, "gate", nodes_file="g.json", python="py", argv=_argv())
    assert full[:5] == ["py", "-m", "pytest", "tests", "-q"]
    assert f"--ignore={shards.ARCHITECTURE_SUITE}" in full and "--collect-only" in full
    assert set(gate) - set(full) == {"--ignore=tests/test_b.py", "--ignore=tests/test_c.py",
                                     "--ignore=tests/test_d.py", "--core-safety-nodes=g.json"}
    with pytest.raises(shards.ShardError):
        shards.collect_argv(manifest, "other", nodes_file="x", argv=_argv())


def test_real_regression_command_has_the_shape_sharding_relies_on():
    regression = list(stage("regression", gate_plan("full", ROOT)).argv)
    tail = shards._pytest_tail(regression)
    assert tail.count("tests") == 1
    assert any(item.startswith("--data-file=") for item in regression)
    assert "--branch" in regression and any(item.startswith("--source=") for item in regression)
    assert not any(item in {"-k", "-m", "--deselect"} for item in tail)


def test_repository_manifest_is_valid_and_offloads_only_regression_files():
    manifest = shards.load_manifest(ROOT)
    assert shards.validate_manifest(manifest, ROOT) == []
    regression = set(shards.regression_test_files(ROOT))
    offloaded = set(shards.offloaded_files(manifest))
    assert offloaded < regression
    assert set(shards.gate_files(manifest, ROOT)) | offloaded == regression
    # Os E2Es explícitos também continuam no regression do gate (duplicação
    # intencional preservada: nenhuma remoção sem prova de coverage).
    assert {"tests/test_final_closure_r7.py", "tests/test_aceitacao_final_motor_v1.py"} <= set(
        shards.gate_files(manifest, ROOT)
    )


def test_ignore_never_drops_an_explicit_path_so_explicit_stages_stay_intact(tmp_path):
    # O gate poda a partição offloaded só com --ignore (via PYTEST_ADDOPTS).
    # Estágios explícitos do verify_core e a mutation suite chamam pytest com
    # caminho explícito: --ignore não pode zerá-los (exit 5 contaria como
    # mutante "morto").
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_x.py"],
        cwd=tmp_path, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTEST_ADDOPTS": "--ignore=tests/test_x.py"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


# ------------------------------------------------------------------ aggregator mutants

def test_valid_sharded_evidence_reconstructs_the_closed_check_set(valid):
    root, evidence = valid
    summary = _aggregate(root, evidence)
    assert all(ok for _name, ok in summary["checks"])
    assert summary["timing_status"] == "WARNING"
    assert {name for name, _ok, _detail in summary["evidence"]} == {
        "regression shard alpha", "regression shard beta", "node inventory", "coverage partition equivalence",
    }


def test_missing_shard_fails_closed(valid):
    root, evidence = valid
    import shutil
    shutil.rmtree(evidence / "shard-beta")
    summary = _assert_fails(root, evidence, "SHARD_MISSING:beta")
    assert dict(summary["checks"])["regression"] is False


def test_shard_removed_from_manifest_but_still_reporting_fails_closed(valid):
    root, evidence = valid
    _edit(root / shards.MANIFEST_PATH, lambda m: m["shards"].pop())
    _assert_fails(root, evidence, "SHARD_UNEXPECTED:beta")


def test_file_removed_from_manifest_breaks_evidence_binding(valid):
    root, evidence = valid
    _edit(root / shards.MANIFEST_PATH, lambda m: m["shards"][1]["files"].remove("tests/test_d.py"))
    _assert_fails(root, evidence, "EVIDENCE_MANIFEST_MISMATCH")


def test_wrong_sha_shard_is_rejected(valid):
    root, evidence = valid
    _edit(evidence / "shard-alpha/shard-evidence.json", lambda p: p.update(sha=OTHER_SHA))
    _assert_fails(root, evidence, "EVIDENCE_SHA_MISMATCH:shard:alpha")


def test_wrong_candidate_sha_rejects_every_artifact(valid):
    root, evidence = valid
    summary = _assert_fails(root, evidence, "EVIDENCE_SHA_MISMATCH", sha=OTHER_SHA)
    assert {"EVIDENCE_SHA_MISMATCH:gate", "EVIDENCE_SHA_MISMATCH:inventory"} <= set(summary["errors"])


def test_red_shard_is_never_ignored(valid):
    root, evidence = valid
    _edit(evidence / "shard-beta/shard-evidence.json", lambda p: p.update(exit_code=1))
    summary = _assert_fails(root, evidence, "SHARD_FAILED:beta")
    assert summary["semantic_status"] == "FAIL"


def test_failed_node_inside_green_exit_code_is_never_ignored(valid):
    root, evidence = valid
    _edit(evidence / "shard-alpha/shard-evidence.json",
          lambda p: p["nodes"]["outcomes"].update({"tests/test_b.py::test_one": "failed"}))
    _assert_fails(root, evidence, "SHARD_NODES_FAILED:alpha")


def test_collected_but_not_executed_node_fails_closed(valid):
    root, evidence = valid
    _edit(evidence / "shard-beta/shard-evidence.json",
          lambda p: p["nodes"]["outcomes"].pop("tests/test_c.py::test_two[x]"))
    _assert_fails(root, evidence, "SHARD_NODES_NOT_ALL_EXECUTED:beta")


def test_shard_that_silently_drops_a_node_breaks_inventory(valid):
    root, evidence = valid

    def drop(payload):
        payload["nodes"]["collected"].remove("tests/test_c.py::test_two[x]")
        payload["nodes"]["outcomes"].pop("tests/test_c.py::test_two[x]")
    _edit(evidence / "shard-beta/shard-evidence.json", drop)
    _assert_fails(root, evidence, "NODE_INVENTORY_MISMATCH")


def test_shard_running_other_files_cannot_hide_its_own(valid):
    root, evidence = valid

    def swap(payload):
        payload["nodes"] = _node_report(NODES["tests/test_a.py"] + NODES["tests/test_c.py"], collect_only=False)
    _edit(evidence / "shard-beta/shard-evidence.json", swap)
    summary = _assert_fails(root, evidence, "SHARD_RAN_FOREIGN_FILES:beta")
    assert any(error.startswith("SHARD_FILES_WITHOUT_NODES:beta") for error in summary["errors"])
    assert any(error.startswith("NODE_INVENTORY_MISMATCH") for error in summary["errors"])


def test_two_shards_reporting_the_same_node_is_an_overlap(valid):
    root, evidence = valid

    def steal(payload):
        payload["nodes"] = _node_report(NODES["tests/test_b.py"] + NODES["tests/test_c.py"]
                                        + NODES["tests/test_d.py"], collect_only=False)
    _edit(evidence / "shard-beta/shard-evidence.json", steal)
    _assert_fails(root, evidence, "NODE_INVENTORY_OVERLAP")


def test_clock_dependent_node_id_in_gate_partition_is_proved_by_file_and_count(valid):
    # Caso real (CI de #261): test_delivery_foundation_v1 parametriza com bytes
    # de zip que embutem o timestamp DOS do import; o node é o mesmo, o ID
    # muda entre a coleta integral e a coleta do gate (processos distintos).
    root, evidence = valid
    _edit(evidence / "inventory/inventory-evidence.json",
          lambda p: p["gate"].update(collected=sorted(
              node.replace("test_two", "test_two[\\xb1A]") for node in p["gate"]["collected"])))
    summary = _aggregate(root, evidence)
    assert summary["result"] == "PASS", summary["errors"]


def test_gate_partition_losing_a_node_still_fails_by_count(valid):
    root, evidence = valid
    _edit(evidence / "inventory/inventory-evidence.json",
          lambda p: p["gate"]["collected"].remove("tests/test_a.py::test_two"))
    _assert_fails(root, evidence, "NODE_INVENTORY_MISMATCH")


def test_gate_partition_counts_shifted_between_files_fail(valid):
    # Total preservado (A -1, E2E +1): a prova do gate é por arquivo, não só por soma.
    root, evidence = valid

    def shift(payload):
        payload["gate"]["collected"].remove("tests/test_a.py::test_two")
        payload["gate"]["collected"].append("tests/test_e2e.py::test_extra")
        payload["gate"]["collected"].sort()
    _edit(evidence / "inventory/inventory-evidence.json", shift)
    _assert_fails(root, evidence, "NODE_INVENTORY_MISMATCH")


def test_shard_branch_outside_gate_is_drift_even_with_same_lines(valid):
    # Mesmas linhas do gate, arco novo (2 -> -1): a equivalência vale para branches.
    root, evidence = valid
    data = evidence / "shard-alpha/shard-alpha.data"
    _coverage(data, root, GATE_ARCS[:3] + [(-1, 2), (2, -1)])
    _edit(evidence / "shard-alpha/shard-evidence.json", lambda p: p.update(coverage_sha256=shards.sha256_file(data)))
    _assert_fails(root, evidence, "PARTITION_COVERAGE_DRIFT:shard-alpha.data")


def test_shard_coverage_without_branch_data_is_rejected(valid):
    root, evidence = valid
    data = evidence / "shard-alpha/shard-alpha.data"
    data.unlink()
    line_only = CoverageData(str(data))
    line_only.add_lines({str(root / "src" / "mod.py"): [1, 7]})
    line_only.write()
    _edit(evidence / "shard-alpha/shard-evidence.json", lambda p: p.update(coverage_sha256=shards.sha256_file(data)))
    _assert_fails(root, evidence, "COMBINED_COVERAGE_INVALID")


def test_shard_node_report_with_failed_exitstatus_or_duplicates_is_rejected(valid):
    root, evidence = valid
    _edit(evidence / "shard-alpha/shard-evidence.json", lambda p: p["nodes"].update(exitstatus=1))
    _assert_fails(root, evidence, "SHARD_EVIDENCE_INVALID:alpha")
    _edit(evidence / "shard-alpha/shard-evidence.json", lambda p: p["nodes"].update(
        exitstatus=0, collected=p["nodes"]["collected"] * 2))
    _assert_fails(root, evidence, "SHARD_EVIDENCE_INVALID:alpha")


def test_unexpected_job_in_needs_fails_closed(valid):
    root, evidence = valid
    _assert_fails(root, evidence, "JOB_UNEXPECTED:other",
                  needs={**NEEDS_OK, "other": {"result": "success"}})


@pytest.mark.parametrize("check", ["E2E negative", "regression", "privacy"])
def test_semantic_failure_with_timing_finding_is_never_labelled_semantic_pass(check):
    # A presença de FULL_GATE_DURATION_REGRESSION não pode rotular como só-temporal
    # uma execução em que outro check falhou.
    report = (GATE_REPORT.replace(f"[PASS] {check}\n", f"[FAIL] {check}\n")
              .replace("[PASS] quality non-regression", "[FAIL] quality non-regression")
              .replace("RESULT: PASS\n", "RESULT: FAIL\nQUALITY_NON_REGRESSION | QUALITY_GATE | "
                       "FULL_GATE_DURATION_REGRESSION | x | P1\n"))
    assert shards.semantic_status(shards.parse_gate_report(report)) == "FAIL"


def test_semantic_label_requires_the_closed_check_set():
    report = GATE_REPORT.replace("[PASS] schemas\n", "")
    assert shards.semantic_status(shards.parse_gate_report(report)) == "FAIL"
    timing_only = (GATE_REPORT.replace("[PASS] quality non-regression", "[FAIL] quality non-regression")
                   .replace("RESULT: PASS\n", "RESULT: FAIL\nQUALITY_NON_REGRESSION | QUALITY_GATE | "
                            "FULL_GATE_DURATION_REGRESSION | x | P1\n"))
    assert shards.semantic_status(shards.parse_gate_report(timing_only)) == "PASS"
    assert shards.semantic_status(shards.parse_gate_report(timing_only.replace("[PASS] schemas\n", ""))) == "FAIL"


def test_clock_dependent_node_id_in_a_shard_fails_closed(valid):
    # Em shard a igualdade é por ID exato: um ID instável lá não é aceito.
    root, evidence = valid

    def mutate(payload):
        nodes = [n.replace("test_two[x]", "test_two[y]") for n in payload["nodes"]["collected"]]
        payload["nodes"] = _node_report(nodes, collect_only=False)
    _edit(evidence / "shard-beta/shard-evidence.json", mutate)
    _assert_fails(root, evidence, "NODE_INVENTORY_MISMATCH")


def test_altered_reference_inventory_fails_closed(valid):
    root, evidence = valid
    _edit(evidence / "inventory/inventory-evidence.json",
          lambda p: p["full"]["collected"].append("tests/test_a.py::test_hidden"))
    _assert_fails(root, evidence, "NODE_INVENTORY_MISMATCH")


def test_gate_partition_running_an_offloaded_file_is_detected(valid):
    root, evidence = valid
    _edit(evidence / "inventory/inventory-evidence.json",
          lambda p: p["gate"]["collected"].append("tests/test_b.py::test_one"))
    _assert_fails(root, evidence, "GATE_PARTITION_HAS_OFFLOADED_FILE")


def test_missing_shard_coverage_file_is_partial_combine_and_fails(valid):
    root, evidence = valid
    (evidence / "shard-alpha/shard-alpha.data").unlink()
    summary = _assert_fails(root, evidence, "SHARD_COVERAGE_IDENTITY_MISMATCH:alpha")
    assert "COMBINED_COVERAGE_INCOMPLETE" in summary["errors"]


def test_substituted_shard_coverage_file_is_rejected(valid):
    root, evidence = valid
    _coverage(evidence / "shard-alpha/shard-alpha.data", root, GATE_ARCS[:2])
    _assert_fails(root, evidence, "SHARD_COVERAGE_IDENTITY_MISMATCH:alpha")


def test_substituted_gate_coverage_file_is_rejected(valid):
    root, evidence = valid
    _coverage(evidence / "gate" / shards.GATE_DATA, root, GATE_ARCS[:3])
    _assert_fails(root, evidence, "GATE_COVERAGE_IDENTITY_MISMATCH")


def test_shard_covering_code_outside_gate_coverage_is_partition_drift(valid):
    root, evidence = valid
    data = evidence / "shard-beta/shard-beta.data"
    _coverage(data, root, DRIFT_ARCS)
    _edit(evidence / "shard-beta/shard-evidence.json", lambda p: p.update(coverage_sha256=shards.sha256_file(data)))
    _assert_fails(root, evidence, "PARTITION_COVERAGE_DRIFT:shard-beta.data")


@pytest.mark.parametrize(("line", "branch", "code"), [
    (66.7, 50.0, "COMBINED_COVERAGE_LINE_REGRESSION"),
    (60.0, 50.1, "COMBINED_COVERAGE_BRANCH_REGRESSION"),
])
def test_combined_coverage_regression_is_never_masked(tmp_path, line, branch, code):
    root = _repo(tmp_path, line=line, branch=branch)
    evidence = _evidence(root, tmp_path)
    summary = _assert_fails(root, evidence, code)
    assert dict(summary["checks"])["quality non-regression"] is False


def test_missing_mutation_suite_check_breaks_the_closed_set(valid):
    root, evidence = valid
    report = GATE_REPORT.replace("[PASS] historical critical mutation suite\n", "")
    _edit(evidence / "gate/gate-evidence.json", lambda p: p.update(report=report))
    summary = _assert_fails(root, evidence, "GATE_CHECK_SET_NOT_CLOSED")
    assert dict(summary["checks"])["historical critical mutation suite"] is False


@pytest.mark.parametrize("check", ["E2E negative", "historical critical mutation suite", "privacy",
                                   "schemas", "capability cutover tests", "regression"])
def test_semantic_failure_in_gate_always_blocks(valid, check):
    root, evidence = valid
    report = GATE_REPORT.replace(f"[PASS] {check}\n", f"[FAIL] {check}\n").replace("RESULT: PASS", "RESULT: FAIL")
    _edit(evidence / "gate/gate-evidence.json", lambda p: p.update(report=report, exit_code=1))
    summary = _assert_fails(root, evidence, "GATE_NOT_PASS")
    assert summary["semantic_status"] == "FAIL"
    assert dict(summary["checks"])[check] is False


def test_gate_report_saying_pass_with_red_exit_code_is_rejected(valid):
    root, evidence = valid
    _edit(evidence / "gate/gate-evidence.json", lambda p: p.update(exit_code=1))
    _assert_fails(root, evidence, "GATE_NOT_PASS")


def test_timing_only_failure_is_reported_separately_and_still_blocks(valid):
    root, evidence = valid
    report = (GATE_REPORT.replace("[PASS] quality non-regression", "[FAIL] quality non-regression")
              .replace("TIMING_STATUS = WARNING", "TIMING_STATUS = FAIL")
              .replace("RESULT: PASS\n", "RESULT: FAIL\nQUALITY_NON_REGRESSION | QUALITY_GATE | "
                       "FULL_GATE_DURATION_REGRESSION | {'code': 'FULL_GATE_DURATION_REGRESSION'} | P1\n"))
    _edit(evidence / "gate/gate-evidence.json", lambda p: p.update(report=report, exit_code=1))
    summary = _assert_fails(root, evidence, "GATE_NOT_PASS")
    assert summary["semantic_status"] == "PASS"
    assert summary["timing_status"] == "FAIL"


def test_coverage_regression_never_hides_behind_timing(valid):
    root, evidence = valid
    report = (GATE_REPORT.replace("[PASS] quality non-regression", "[FAIL] quality non-regression")
              .replace("RESULT: PASS\n", "RESULT: FAIL\nQUALITY_NON_REGRESSION | QUALITY_GATE | "
                       "FULL_GATE_DURATION_REGRESSION | x | P1\nQUALITY_NON_REGRESSION | QUALITY_GATE | "
                       "COVERAGE_LINE_REGRESSION | x | P1\n"))
    _edit(evidence / "gate/gate-evidence.json", lambda p: p.update(report=report, exit_code=1))
    assert _aggregate(root, evidence)["semantic_status"] == "FAIL"


@pytest.mark.parametrize("result", ["skipped", "failure", "cancelled", None])
@pytest.mark.parametrize("job", shards.REQUIRED_JOBS)
def test_any_required_job_not_successful_fails_closed(valid, job, result):
    root, evidence = valid
    needs = json.loads(json.dumps(NEEDS_OK))
    if result is None:
        needs.pop(job)
    else:
        needs[job]["result"] = result
    _assert_fails(root, evidence, f"JOB_NOT_SUCCESSFUL:{job}", needs=needs)


def test_malformed_evidence_fails_closed(valid):
    root, evidence = valid
    (evidence / "shard-beta/shard-evidence.json").write_text("{not json", encoding="utf-8")
    _assert_fails(root, evidence, "SHARD_EVIDENCE_INVALID:beta")
    (evidence / "inventory/inventory-evidence.json").write_text("[]", encoding="utf-8")
    _assert_fails(root, evidence, "INVENTORY_INVALID")
    (evidence / "gate/gate-evidence.json").unlink()
    _assert_fails(root, evidence, "GATE_EVIDENCE_INVALID")


def test_collect_only_report_cannot_impersonate_an_executed_shard(valid):
    root, evidence = valid
    _edit(evidence / "shard-alpha/shard-evidence.json", lambda p: p["nodes"].update(collect_only=True, outcomes={}))
    _assert_fails(root, evidence, "SHARD_EVIDENCE_INVALID:alpha")


def test_cli_aggregate_without_evidence_or_needs_fails_closed(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CORE_SAFETY_TEST_NEEDS", "{bad")
    assert shards.main(["aggregate", "--evidence-dir", str(tmp_path), "--sha", SHA,
                        "--needs-env", "CORE_SAFETY_TEST_NEEDS"]) == 1
    out = capsys.readouterr().out
    assert "RESULT: FAIL" in out and "SEMANTIC_STATUS = FAIL" in out


# ------------------------------------------------------------------ workflow topology

def _workflow() -> str:
    return (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")


def _job_block(workflow: str, job: str) -> str:
    match = re.search(rf"^  {re.escape(job)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", workflow, re.MULTILINE | re.DOTALL)
    assert match, job
    return match.group(1)


def test_core_safety_aggregator_is_the_required_check_and_cannot_be_skipped():
    workflow = _workflow()
    aggregator = _job_block(workflow, "core-safety")
    assert "if: always()" in aggregator
    needs = re.search(r"needs: \[([^\]]+)\]", aggregator).group(1)
    assert sorted(item.strip() for item in needs.split(",")) == sorted(shards.REQUIRED_JOBS)
    assert "NEEDS_JSON: ${{ toJSON(needs) }}" in aggregator
    assert "scripts.quality.core_safety_shards aggregate" in aggregator and "--needs-env NEEDS_JSON" in aggregator
    assert "continue-on-error" not in workflow


def test_workflow_matrix_is_exactly_the_manifest_shards():
    block = _job_block(_workflow(), "regression-shard")
    ids = re.search(r"shard: \[([^\]]+)\]", block).group(1)
    assert [item.strip() for item in ids.split(",")] == [s["id"] for s in shards.load_manifest(ROOT)["shards"]]
    assert "fail-fast: false" in block


def test_every_core_safety_job_binds_evidence_to_the_exact_checkout_sha():
    workflow = _workflow()
    for job in ("core-gate", "inventory", "regression-shard"):
        block = _job_block(workflow, job)
        assert "git rev-parse HEAD" in block and "GITHUB_SHA" in block, job
        assert "upload-artifact@" in block, job
    assert "download-artifact@" in _job_block(workflow, "core-safety")


# ------------------------------------------------------------------ plan / node plugin

def test_plan_is_extracted_from_the_judge_and_matches_its_real_commands():
    captured = []

    def runner(command, **_):
        captured.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    from scripts.quality.verify_core import run_gate
    run_gate("full", ROOT, runner=runner, tracked_files=[])
    plan = gate_plan("full", ROOT)
    assert sorted(item.argv for item in plan) == sorted(captured)
    assert [item.name for item in plan] == [
        name for name in shards.EXPECTED_GATE_CHECKS
        if name not in {"invariants", "fixtures", "privacy", "quality non-regression"}
    ]


def test_sharding_tooling_never_acquires_process_capability():
    # Ferramentas não-dispositivas: nenhuma executa processo (a execução é do
    # workflow e do verify_core protegido).
    for name in ("core_safety_plan", "core_safety_shards", "core_safety_nodes"):
        source = (ROOT / f"scripts/quality/{name}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(subprocess|multiprocessing|os\.system)", source, re.MULTILINE), name


def test_node_plugin_records_exact_outcomes(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n"
        "def test_ok():\n    pass\n"
        "def test_bad():\n    assert False\n"
        "@pytest.mark.skip(reason='x')\ndef test_skip():\n    pass\n"
        "@pytest.fixture\ndef broken():\n    yield\n    raise RuntimeError('teardown')\n"
        "def test_teardown(broken):\n    pass\n",
        encoding="utf-8",
    )
    report = tmp_path / "nodes.json"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", shards.NODES_PLUGIN,
         f"--core-safety-nodes={report}", "test_sample.py"],
        cwd=tmp_path, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT)},
    )
    assert completed.returncode == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["exitstatus"] == 1 and payload["collect_only"] is False
    assert payload["outcomes"] == {
        "test_sample.py::test_bad": "failed", "test_sample.py::test_ok": "passed",
        "test_sample.py::test_skip": "skipped", "test_sample.py::test_teardown": "failed",
    }
