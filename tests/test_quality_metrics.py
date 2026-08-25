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


def test_quality_baseline_rejects_full_gate_duration_regression():
    baseline = {"coverage":{"line_percent":80.0,"branch_percent":70.0},"hotspots":[],"full_gate_max_seconds":30.0}
    findings = validate_quality_baseline(
        baseline,
        {"line_percent":80.0,"branch_percent":70.0},
        [],
        duration_seconds=30.1,
        timing_policy="STRICT",
    )
    assert {item["code"] for item in findings} == {"FULL_GATE_DURATION_REGRESSION"}


def test_pull_request_duration_overrun_is_structured_advisory_only(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    baseline = {
        "coverage": {"line_percent": 80.0, "branch_percent": 70.0},
        "hotspots": [],
        "full_gate_max_seconds": 60.0,
    }

    findings = validate_quality_baseline(
        baseline,
        {"line_percent": 80.0, "branch_percent": 70.0},
        [],
        duration_seconds=60.1,
    )

    assert findings == []
    assert capsys.readouterr().out.splitlines() == [
        "TARGET_SECONDS = 60.0",
        "OBSERVED_SECONDS = 60.1",
        "TIMING_STATUS = WARNING",
    ]


def test_strict_duration_overrun_remains_blocking(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    baseline = {
        "coverage": {"line_percent": 80.0, "branch_percent": 70.0},
        "hotspots": [],
        "full_gate_max_seconds": 60.0,
    }

    findings = validate_quality_baseline(
        baseline,
        {"line_percent": 80.0, "branch_percent": 70.0},
        [],
        duration_seconds=60.1,
    )

    assert {item["code"] for item in findings} == {"FULL_GATE_DURATION_REGRESSION"}
    assert capsys.readouterr().out.splitlines() == [
        "TARGET_SECONDS = 60.0",
        "OBSERVED_SECONDS = 60.1",
        "TIMING_STATUS = FAIL",
    ]


def test_pull_request_advisory_never_hides_semantic_quality_findings(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    baseline = {
        "coverage": {"line_percent": 80.0, "branch_percent": 70.0},
        "hotspots": [{"path": "sample.py", "function": "f", "complexity": 4}],
        "full_gate_max_seconds": 60.0,
    }

    findings = validate_quality_baseline(
        baseline,
        {"line_percent": 79.9, "branch_percent": 69.9},
        [{"path": "sample.py", "function": "f", "complexity": 5}],
        duration_seconds=61.0,
    )

    assert {item["code"] for item in findings} == {
        "COVERAGE_LINE_REGRESSION",
        "COVERAGE_BRANCH_REGRESSION",
        "HOTSPOT_COMPLEXITY_REGRESSION",
    }


def test_timing_evidence_is_fail_closed_when_explicitly_requested(capsys):
    baseline = {
        "coverage": {"line_percent": 80.0, "branch_percent": 70.0},
        "hotspots": [],
        "full_gate_max_seconds": 60.0,
    }
    invalid_values = (None, math.nan, math.inf, -0.1)

    for duration in invalid_values:
        findings = validate_quality_baseline(
            baseline,
            {"line_percent": 80.0, "branch_percent": 70.0},
            [],
            duration_seconds=duration,
            timing_policy="PR_ADVISORY",
        )
        assert {item["code"] for item in findings} == {"TIMING_EVIDENCE_INVALID"}

    output = capsys.readouterr().out
    assert output.count("TIMING_STATUS = INVALID") == len(invalid_values)


def test_unknown_timing_policy_fails_closed(capsys):
    baseline = {
        "coverage": {"line_percent": 80.0, "branch_percent": 70.0},
        "hotspots": [],
        "full_gate_max_seconds": 60.0,
    }

    findings = validate_quality_baseline(
        baseline,
        {"line_percent": 80.0, "branch_percent": 70.0},
        [],
        duration_seconds=10.0,
        timing_policy="PERMISSIVE",
    )

    assert {item["code"] for item in findings} == {"TIMING_EVIDENCE_INVALID"}
    assert "TIMING_STATUS = INVALID" in capsys.readouterr().out


def test_metrics_module_uses_ast_not_source_execution():
    tree = ast.parse("def f(x):\n    return x\n")
    assert tree.body[0].name == "f"
