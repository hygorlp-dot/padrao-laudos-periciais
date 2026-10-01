"""V7-4: atribuicao temporal BASE x HEAD (decisao humana "2-III" registrada na #256)."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.quality import timing_attribution as attribution


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40


def _log(path: Path, seconds, status="ATTRIBUTION_REQUIRED", target=60.0, extra=""):
    path.write_text(f"CORE SAFETY GATE\nTARGET_SECONDS = {target}\nOBSERVED_SECONDS = {seconds}\nTIMING_STATUS = {status}\n{extra}RESULT: PASS\n", encoding="utf-8")
    return str(path)


GATE_CHECKS = (
    "invariants", "fixtures", "privacy", "property tests", "gate tests", "compileall",
    "historical critical mutation suite", "quality V2", "schemas", "E2E positive",
    "E2E negative", "capability cutover tests", "regression", "coverage report",
    "diff check", "quality non-regression",
)
TIMING_FINDING = ("QUALITY_NON_REGRESSION | QUALITY_GATE | FULL_GATE_DURATION_REGRESSION | "
                  "{'code': 'FULL_GATE_DURATION_REGRESSION', 'severity': 'P1'} | P1")


def _base(path: Path, seconds, status="ATTRIBUTION_REQUIRED", failing=(), findings=(), result=None):
    """Saída completa de um verify_core --full da BASE (formato de _print)."""
    timing = f"TARGET_SECONDS = 60.0\nOBSERVED_SECONDS = {seconds}\nTIMING_STATUS = {status}\n"
    checks = "".join(f"[{'FAIL' if name in failing else 'PASS'}] {name}\n" for name in GATE_CHECKS)
    result = result or ("FAIL" if failing else "PASS")
    body = "".join(f"{line}\n" for line in findings)
    path.write_text(f"{timing}CORE SAFETY GATE\n\n{checks}\nRESULT: {result}\n{body}DURATION_SECONDS: {seconds}\n",
                    encoding="utf-8")
    return str(path)


def _decide(tmp_path, base_log, base_exit, head=1300.0):
    return attribution.main(["decide", "--head-log", _log(tmp_path / "h", head), "--base-log", base_log,
                             "--base-exit-code", str(base_exit), "--base-sha", SHA])


def test_within_reference_needs_no_base(tmp_path):
    assert attribution.main(["requires-base", "--head-log", _log(tmp_path / "h", 700.0, "PASS")]) == attribution.EXIT_WITHIN_REFERENCE


def test_over_reference_requires_base(tmp_path):
    assert attribution.main(["requires-base", "--head-log", _log(tmp_path / "h", 1300.0)]) == attribution.EXIT_ATTRIBUTION_REQUIRED


@pytest.mark.parametrize("head, base, expected", [
    (1300.0, 1250.0, attribution.EXIT_WITHIN_REFERENCE),  # runner lento para os dois: drift
    (1374.9, 1250.0, attribution.EXIT_WITHIN_REFERENCE),  # abaixo de 10%
    (1375.1, 1250.0, attribution.EXIT_INVALID),           # regressao material do candidato
    (1300.0, 900.0, attribution.EXIT_INVALID),
    # Decisao humana na #109: material_threshold = max(60 s, BASE * 0.10).
    (1340.0, 1250.0, attribution.EXIT_WITHIN_REFERENCE),  # 90 s < 10% da BASE (125 s)
    (172.23367269999994, 151.3636335000001, attribution.EXIT_WITHIN_REFERENCE),  # main 04dfb71: +20,9 s < 60 s
    (210.0, 150.0, attribution.EXIT_WITHIN_REFERENCE),    # delta = 60 s exatos nao excede
    (210.1, 150.0, attribution.EXIT_INVALID),             # delta > 60 s com BASE curta
])
def test_only_material_candidate_delta_blocks(tmp_path, capsys, head, base, expected):
    base_log = _base(tmp_path / "b", base, "FAIL", failing=("quality non-regression",), findings=(TIMING_FINDING,))
    code = attribution.main(["decide", "--head-log", _log(tmp_path / "h", head), "--base-log", base_log,
                             "--base-exit-code", "1", "--base-sha", SHA])
    assert code == expected
    output = capsys.readouterr().out
    assert f"BASE_SHA = {SHA}" in output and "HEAD_SECONDS" in output and "BASE_SECONDS" in output


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nan", "negative", "invalid_status", "no_file"])
def test_invalid_evidence_fails_closed(tmp_path, damage):
    head = tmp_path / "h"
    if damage == "missing":
        head.write_text("RESULT: PASS\n", encoding="utf-8")
    elif damage == "duplicate":
        _log(head, 1300.0, extra="OBSERVED_SECONDS = 10.0\n")
    elif damage == "nan":
        _log(head, "nan")
    elif damage == "negative":
        _log(head, -1.0)
    elif damage == "invalid_status":
        _log(head, 1300.0, "INVALID")
    args = ["requires-base", "--head-log", str(head if damage != "no_file" else tmp_path / "absent")]
    assert attribution.main(args) == attribution.EXIT_INVALID


def test_decide_refuses_inexact_base_and_head_within_reference(tmp_path):
    base = _base(tmp_path / "b", 1000.0)
    ok = ["--base-exit-code", "0"]
    assert attribution.main(["decide", "--head-log", _log(tmp_path / "h", 1300.0), "--base-log", base, *ok, "--base-sha", "main"]) == attribution.EXIT_INVALID
    assert attribution.main(["decide", "--head-log", _log(tmp_path / "h2", 900.0, "PASS"), "--base-log", base, *ok, "--base-sha", SHA]) == attribution.EXIT_INVALID
    assert attribution.main(["decide", "--head-log", _log(tmp_path / "h3", 1300.0), "--base-log", _base(tmp_path / "b2", 0.0), *ok, "--base-sha", SHA]) == attribution.EXIT_INVALID


# ---------------------------------------------------------------- BASE semantic validity
# Uma BASE semanticamente inválida nunca serve de referência temporal (ela
# poderia elevar o limite do candidato). Só uma falha EXCLUSIVAMENTE temporal da
# política antiga é aceita.

@pytest.mark.parametrize("status", ["ATTRIBUTION_REQUIRED", "PASS", "WARNING"])
def test_semantically_green_base_is_accepted(tmp_path, status):
    assert _decide(tmp_path, _base(tmp_path / "b", 1250.0, status), 0) == attribution.EXIT_WITHIN_REFERENCE


def test_legacy_timing_only_failed_base_is_accepted(tmp_path):
    base = _base(tmp_path / "b", 1250.0, "FAIL", failing=("quality non-regression",), findings=(TIMING_FINDING,))
    assert _decide(tmp_path, base, 1) == attribution.EXIT_WITHIN_REFERENCE


@pytest.mark.parametrize(("check", "finding"), [
    ("regression", "FAIL_CLOSED | CORE | regression | 1 failed | P0"),
    ("privacy", "PII_DENY_BY_DEFAULT | REPOSITORY | referencias/privadas/x.pdf | referência privada rastreada | P0"),
    ("schemas", "SOURCE_TRUTH | REPOSITORY | schemas | schema inválido | P1"),
    ("E2E negative", "ESSENTIAL_INPUT_REMOVAL_DEGRADES_RESULT | MOTOR | E2E negative | 1 failed | P0"),
    ("E2E positive", "SOURCE_TRUTH | MOTOR | E2E positive | 1 failed | P1"),
])
def test_semantically_failed_base_is_invalid_even_with_timing_finding(tmp_path, capsys, check, finding):
    base = _base(tmp_path / "b", 1250.0, "FAIL", failing=(check, "quality non-regression"),
                 findings=(finding, TIMING_FINDING))
    assert _decide(tmp_path, base, 1) == attribution.EXIT_INVALID
    assert "TIMING_ATTRIBUTION = INVALID" in capsys.readouterr().out


@pytest.mark.parametrize("check", ["regression", "privacy", "schemas", "E2E negative"])
def test_red_semantic_check_is_invalid_even_if_only_a_timing_finding_is_printed(tmp_path, check):
    # O conjunto de checks vermelhos decide, não só os findings impressos.
    base = _base(tmp_path / "b", 1250.0, "FAIL", failing=(check, "quality non-regression"), findings=(TIMING_FINDING,))
    assert _decide(tmp_path, base, 1) == attribution.EXIT_INVALID


def test_coverage_regression_in_base_is_not_a_timing_only_failure(tmp_path):
    coverage = ("QUALITY_NON_REGRESSION | QUALITY_GATE | COVERAGE_LINE_REGRESSION | "
                "{'code': 'COVERAGE_LINE_REGRESSION'} | P1")
    base = _base(tmp_path / "b", 1250.0, "FAIL", failing=("quality non-regression",), findings=(coverage, TIMING_FINDING))
    assert _decide(tmp_path, base, 1) == attribution.EXIT_INVALID
    only_coverage = _base(tmp_path / "b2", 1250.0, "ATTRIBUTION_REQUIRED", failing=("quality non-regression",),
                          findings=(coverage,))
    assert _decide(tmp_path, only_coverage, 1) == attribution.EXIT_INVALID


@pytest.mark.parametrize(("status", "failing", "findings", "result", "exit_code"), [
    ("ATTRIBUTION_REQUIRED", (), (), "PASS", 1),                                         # exit != RESULT
    ("FAIL", ("quality non-regression",), (TIMING_FINDING,), "FAIL", 0),                  # exit descartado
    ("ATTRIBUTION_REQUIRED", (), (), "FAIL", 1),                                          # FAIL sem check vermelho
    ("WARNING", ("quality non-regression",), (TIMING_FINDING,), "FAIL", 1),               # status incoerente
    ("FAIL", ("quality non-regression",), (), "FAIL", 1),                                 # sem finding
    ("ATTRIBUTION_REQUIRED", (), (TIMING_FINDING,), "PASS", 0),                           # PASS com finding
])
def test_incoherent_base_report_or_exit_code_is_invalid(tmp_path, status, failing, findings, result, exit_code):
    base = _base(tmp_path / "b", 1250.0, status, failing=failing, findings=findings, result=result)
    assert _decide(tmp_path, base, exit_code) == attribution.EXIT_INVALID


def test_stderr_noise_after_duration_is_not_a_finding(tmp_path):
    path = tmp_path / "b"
    _base(path, 1250.0)
    path.write_text(path.read_text(encoding="utf-8") + "DeprecationWarning: noise at exit\n", encoding="utf-8")
    assert _decide(tmp_path, str(path), 0) == attribution.EXIT_WITHIN_REFERENCE


@pytest.mark.parametrize("damage", ["missing_check", "extra_check", "duplicated_result", "no_result", "truncated",
                                    "no_duration"])
def test_incomplete_or_malformed_base_report_is_invalid(tmp_path, damage):
    path = tmp_path / "b"
    _base(path, 1250.0)
    text = path.read_text(encoding="utf-8")
    text = {
        "missing_check": text.replace("[PASS] schemas\n", ""),
        "extra_check": text.replace("[PASS] diff check\n", "[PASS] diff check\n[PASS] bonus\n"),
        "duplicated_result": text.replace("RESULT: PASS\n", "RESULT: PASS\nRESULT: PASS\n"),
        "no_result": text.replace("RESULT: PASS\n", ""),
        "truncated": text.split("[PASS] regression")[0],
        "no_duration": text.split("DURATION_SECONDS")[0],
    }[damage]
    path.write_text(text, encoding="utf-8")
    assert _decide(tmp_path, str(path), 0) == attribution.EXIT_INVALID


def test_reordered_check_set_is_invalid(tmp_path):
    path = tmp_path / "b"
    _base(path, 1250.0)
    text = path.read_text(encoding="utf-8").replace("[PASS] invariants\n[PASS] fixtures\n",
                                                    "[PASS] fixtures\n[PASS] invariants\n")
    path.write_text(text, encoding="utf-8")
    assert _decide(tmp_path, str(path), 0) == attribution.EXIT_INVALID


@pytest.mark.parametrize("finding", [
    "QUALITY_NON_REGRESSION | QUALITY_GATE | FULL_GATE_DURATION_REGRESSION | P1",
    "QUALITY_NON_REGRESSION | QUALITY_GATE | FULL_GATE_DURATION_REGRESSION | x | P1 | extra",
])
def test_timing_finding_with_wrong_field_count_is_invalid(tmp_path, finding):
    base = _base(tmp_path / "b", 1250.0, "FAIL", failing=("quality non-regression",), findings=(finding,))
    assert _decide(tmp_path, base, 1) == attribution.EXIT_INVALID


def test_pass_result_with_failed_timing_status_is_invalid(tmp_path):
    assert _decide(tmp_path, _base(tmp_path / "b", 1250.0, "FAIL", result="PASS"), 0) == attribution.EXIT_INVALID


def test_base_exit_code_is_mandatory_and_numeric(tmp_path):
    base = _base(tmp_path / "b", 1250.0)
    with pytest.raises(SystemExit):
        attribution.main(["decide", "--head-log", _log(tmp_path / "h", 1300.0), "--base-log", base, "--base-sha", SHA])
    assert attribution.main(["decide", "--head-log", _log(tmp_path / "h", 1300.0), "--base-log", base,
                             "--base-exit-code", "", "--base-sha", SHA]) == attribution.EXIT_INVALID


def test_workflow_makes_attribution_mandatory_and_identical_for_pr_and_main():
    workflow = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow and "branches: [main]" in workflow
    blocks = workflow.split("\n      - ")
    step = next(block for block in blocks if block.startswith("name: Timing attribution BASE vs HEAD"))
    assert "continue-on-error" not in step and "\n        if:" not in step
    assert "github.event.pull_request.base.sha || github.event.before" in step
    assert "timing_attribution requires-base" in step and "timing_attribution decide" in step
    # O exit code da BASE é capturado logo após o verify_core da BASE e entregue à decisão.
    base_run = step.split('python -m scripts.quality.verify_core "--full"', 1)[1]
    assert "$baseCode = $LASTEXITCODE" in base_run.split("\n", 2)[1]
    assert "--base-exit-code $baseCode" in step
    assert "if ($LASTEXITCODE -ne 3) { exit 1 }" in step and step.rstrip().endswith("exit $LASTEXITCODE")
    verify = next(block for block in blocks if block.startswith("name: Verify frozen Core V1"))
    # Sharded core-gate (#259): o log do HEAD é capturado em gate-report.txt e o
    # exit code do verify_core é propagado ao fim do passo.
    assert "python -m scripts.quality.verify_core --full *> gate-report.txt" in verify
    assert "$code = $LASTEXITCODE" in verify and verify.rstrip().endswith("exit $code")
    assert "continue-on-error" not in workflow


def test_attribution_module_does_not_acquire_process_capability():
    source = (ROOT / "scripts/quality/timing_attribution.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "popen", "multiprocessing", "importlib", "eval(", "exec("):
        assert forbidden not in source
