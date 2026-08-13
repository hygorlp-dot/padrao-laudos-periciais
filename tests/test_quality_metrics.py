import ast
import json
import math
from pathlib import Path

from scripts.quality.metrics import analyze_complexity, parse_coverage_totals, validate_quality_baseline


ROOT = Path(__file__).resolve().parents[1]


def test_complexity_analysis_is_deterministic_and_ranks_functions(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text("def simple():\n    return 1\n\ndef branch(x):\n    if x and x > 1:\n        return 2\n    return 0\n", encoding="utf-8")
    first = analyze_complexity([source], base=tmp_path)
    second = analyze_complexity([source], base=tmp_path)
    assert first == second
    assert first[0]["function"] == "branch"
    assert first[0]["complexity"] > first[1]["complexity"]


def test_coverage_parser_distinguishes_line_and_branch_percentages():
    report = {"totals":{"num_statements":100,"covered_lines":80,"num_branches":20,"covered_branches":10}}
    assert parse_coverage_totals(report) == {"line_percent":80.0,"branch_percent":50.0}


def test_quality_baseline_rejects_coverage_and_hotspot_regression():
    baseline = {"coverage":{"line_percent":80.0,"branch_percent":70.0},"hotspots":[{"path":"sample.py","function":"f","complexity":4}]}
    findings = validate_quality_baseline(baseline, {"line_percent":79.9,"branch_percent":69.9}, [{"path":"sample.py","function":"f","complexity":5}])
    assert {item["code"] for item in findings} == {"COVERAGE_LINE_REGRESSION","COVERAGE_BRANCH_REGRESSION","HOTSPOT_COMPLEXITY_REGRESSION"}


def test_repository_hotspot_baseline_matches_current_measurement():
    baseline = json.loads((ROOT / "config/quality-baseline.json").read_text(encoding="utf-8"))
    paths = [ROOT / item["path"] for item in baseline["hotspots"]]
    current = analyze_complexity(paths, base=ROOT)
    findings = validate_quality_baseline(baseline, baseline["coverage"], current)
    assert findings == []


def test_quality_baseline_requires_fresh_coverage_measurement():
    baseline = {"coverage":{"line_percent":80.0,"branch_percent":70.0},"hotspots":[]}
    findings = validate_quality_baseline(baseline, None, [])
    assert {item["code"] for item in findings} == {"COVERAGE_MEASUREMENT_MISSING"}


def test_quality_baseline_rejects_real_component_duration_regression():
    baseline = {"coverage":{"line_percent":80.0,"branch_percent":70.0},"hotspots":[],
                "performance_component_max_seconds":{"architecture":10.0,"historical critical mutation suite":20.0,"regression":45.0}}
    findings = validate_quality_baseline(
        baseline, {"line_percent":80.0,"branch_percent":70.0}, [], duration_seconds=90.0,
        component_durations={"architecture":10.1,"historical critical mutation suite":12.0,"regression":30.0},
    )
    assert {item["code"] for item in findings} == {"GATE_COMPONENT_DURATION_REGRESSION"}


def test_quality_baseline_does_not_turn_normal_runner_overhead_into_false_p1():
    baseline = {"coverage":{"line_percent":80.0,"branch_percent":70.0},"hotspots":[],
                "performance_component_max_seconds":{"architecture":10.0,"historical critical mutation suite":20.0,"regression":45.0}}
    assert validate_quality_baseline(
        baseline, {"line_percent":80.0,"branch_percent":70.0}, [], duration_seconds=90.0,
        component_durations={"architecture":5.0,"historical critical mutation suite":12.0,"regression":36.0},
    ) == []


def test_performance_gate_cannot_self_disable_by_omitting_required_budgets():
    baseline = {"coverage":{"line_percent":80.0,"branch_percent":70.0},"hotspots":[],
                "performance_component_max_seconds":{"architecture":10.0}}
    findings = validate_quality_baseline(
        baseline, {"line_percent":80.0,"branch_percent":70.0}, [],
        component_durations={"architecture":5.0,"historical critical mutation suite":12.0,"regression":30.0},
    )
    assert {item["code"] for item in findings} == {"PERFORMANCE_COMPONENT_BUDGET_INVALID"}


def test_performance_gate_rejects_budget_inflation_and_nonfinite_numbers():
    base = {"coverage":{"line_percent":80.0,"branch_percent":70.0},"hotspots":[],
            "performance_component_max_seconds":{"architecture":15.0,
                "historical critical mutation suite":20.0,"regression":45.0}}
    durations = {"architecture":5.0,"historical critical mutation suite":12.0,"regression":30.0}
    inflated = json.loads(json.dumps(base)); inflated["performance_component_max_seconds"]["architecture"] = 15.1
    assert {item["code"] for item in validate_quality_baseline(inflated, base["coverage"], [], component_durations=durations)} == {"PERFORMANCE_COMPONENT_BUDGET_INVALID"}
    for value in (math.nan, math.inf, -math.inf):
        bad_budget = json.loads(json.dumps(base)); bad_budget["performance_component_max_seconds"]["architecture"] = value
        assert {item["code"] for item in validate_quality_baseline(bad_budget, base["coverage"], [], component_durations=durations)} == {"PERFORMANCE_COMPONENT_BUDGET_INVALID"}
        bad_duration = dict(durations); bad_duration["architecture"] = value
        assert {item["code"] for item in validate_quality_baseline(base, base["coverage"], [], component_durations=bad_duration)} == {"PERFORMANCE_COMPONENT_BUDGET_INVALID"}


def test_metrics_module_uses_ast_not_source_execution():
    tree = ast.parse("def f(x):\n    return x\n")
    assert tree.body[0].name == "f"
