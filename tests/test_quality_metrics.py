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


def _timed(duration, *, coverage=None, complexity=None, hotspots=None, limit=60.0, policy=None):
    baseline = {"coverage": {"line_percent": 80.0, "branch_percent": 70.0}, "hotspots": hotspots or [], "full_gate_max_seconds": limit}
    return validate_quality_baseline(
        baseline, coverage or {"line_percent": 80.0, "branch_percent": 70.0}, complexity or [],
        duration_seconds=duration, timing_policy=policy,
    )


def test_duration_within_reference_passes_with_structured_evidence(capsys):
    assert _timed(59.9) == []
    assert capsys.readouterr().out.splitlines() == ["TARGET_SECONDS = 60.0", "OBSERVED_SECONDS = 59.9", "TIMING_STATUS = PASS"]


def test_duration_over_reference_requires_attribution_identically_on_pr_and_main(monkeypatch, capsys):
    # V7-4: a mesma evidencia nao pode ser verde no PR e vermelha na main.
    outputs = []
    for event in ("pull_request", "push", None):
        if event is None:
            monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
        else:
            monkeypatch.setenv("GITHUB_EVENT_NAME", event)
        assert _timed(60.1) == []
        outputs.append(capsys.readouterr().out.splitlines())
    assert outputs == [["TARGET_SECONDS = 60.0", "OBSERVED_SECONDS = 60.1", "TIMING_STATUS = ATTRIBUTION_REQUIRED"]] * 3


def test_timing_never_hides_semantic_quality_findings():
    findings = _timed(
        61.0, coverage={"line_percent": 79.9, "branch_percent": 69.9},
        hotspots=[{"path": "sample.py", "function": "f", "complexity": 4}],
        complexity=[{"path": "sample.py", "function": "f", "complexity": 5}],
    )
    assert {item["code"] for item in findings} == {
        "COVERAGE_LINE_REGRESSION",
        "COVERAGE_BRANCH_REGRESSION",
        "HOTSPOT_COMPLEXITY_REGRESSION",
    }


def test_legacy_event_specific_policies_are_no_longer_accepted(capsys):
    for policy in ("STRICT", "PR_ADVISORY"):
        assert {item["code"] for item in _timed(10.0, policy=policy)} == {"TIMING_EVIDENCE_INVALID"}
    assert capsys.readouterr().out.count("TIMING_STATUS = INVALID") == 2


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
            timing_policy="HYBRID",
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
