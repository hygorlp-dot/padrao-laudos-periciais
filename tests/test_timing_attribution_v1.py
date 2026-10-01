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


def test_within_reference_needs_no_base(tmp_path):
    assert attribution.main(["requires-base", "--head-log", _log(tmp_path / "h", 700.0, "PASS")]) == attribution.EXIT_WITHIN_REFERENCE


def test_over_reference_requires_base(tmp_path):
    assert attribution.main(["requires-base", "--head-log", _log(tmp_path / "h", 1300.0)]) == attribution.EXIT_ATTRIBUTION_REQUIRED


@pytest.mark.parametrize("head, base, expected", [
    (1300.0, 1250.0, attribution.EXIT_WITHIN_REFERENCE),  # runner lento para os dois: drift
    (1374.9, 1250.0, attribution.EXIT_WITHIN_REFERENCE),  # abaixo de 10%
    (1375.1, 1250.0, attribution.EXIT_INVALID),           # regressao material do candidato
    (1300.0, 900.0, attribution.EXIT_INVALID),
])
def test_only_material_candidate_delta_blocks(tmp_path, capsys, head, base, expected):
    code = attribution.main(["decide", "--head-log", _log(tmp_path / "h", head), "--base-log", _log(tmp_path / "b", base, "FAIL", target=60.0), "--base-sha", SHA])
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
    base = _log(tmp_path / "b", 1000.0)
    assert attribution.main(["decide", "--head-log", _log(tmp_path / "h", 1300.0), "--base-log", base, "--base-sha", "main"]) == attribution.EXIT_INVALID
    assert attribution.main(["decide", "--head-log", _log(tmp_path / "h2", 900.0, "PASS"), "--base-log", base, "--base-sha", SHA]) == attribution.EXIT_INVALID
    assert attribution.main(["decide", "--head-log", _log(tmp_path / "h3", 1300.0), "--base-log", _log(tmp_path / "b2", 0.0), "--base-sha", SHA]) == attribution.EXIT_INVALID


def test_workflow_makes_attribution_mandatory_and_identical_for_pr_and_main():
    workflow = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")
    assert "pull_request:" in workflow and "branches: [main]" in workflow
    blocks = workflow.split("\n      - ")
    step = next(block for block in blocks if block.startswith("name: Timing attribution BASE vs HEAD"))
    assert "continue-on-error" not in step and "\n        if:" not in step
    assert "github.event.pull_request.base.sha || github.event.before" in step
    assert "timing_attribution requires-base" in step and "timing_attribution decide" in step
    assert "if ($LASTEXITCODE -ne 3) { exit 1 }" in step and step.rstrip().endswith("exit $LASTEXITCODE")
    verify = next(block for block in blocks if block.startswith("name: Verify frozen Core V1"))
    assert "Tee-Object" in verify and "exit $LASTEXITCODE" in verify
    assert "continue-on-error" not in workflow


def test_attribution_module_does_not_acquire_process_capability():
    source = (ROOT / "scripts/quality/timing_attribution.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "popen", "multiprocessing", "importlib", "eval(", "exec("):
        assert forbidden not in source
