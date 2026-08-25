from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from scripts.quality.timing_gate import FULL_GATE_CHECKS, evaluate_timing_evidence


BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
ROOT = Path(__file__).resolve().parents[1]


def _output(duration: float, *, semantic_failure: bool = False) -> str:
    checks = []
    for name in FULL_GATE_CHECKS:
        passed = not semantic_failure or name != "regression"
        checks.append(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if semantic_failure:
        finding = "FAIL_CLOSED | CORE | regression | 1 failed | P0"
        result = "FAIL"
    elif duration > 60.0:
        checks[-1] = "[FAIL] quality non-regression"
        finding = (
            "QUALITY_NON_REGRESSION | QUALITY_GATE | FULL_GATE_DURATION_REGRESSION | "
            f"{{'expected': 60.0, 'actual': {duration}}} | P1"
        )
        result = "FAIL"
    else:
        finding = ""
        result = "PASS"
    return "\n".join([
        "CORE SAFETY GATE",
        *checks,
        f"RESULT: {result}",
        finding,
        f"DURATION_SECONDS: {duration:.3f}",
    ])


def _evidence(base: tuple[float, float], head: tuple[float, float]) -> dict:
    values = (("BASE", 1, BASE_SHA, base[0]), ("HEAD", 1, HEAD_SHA, head[0]),
              ("HEAD", 2, HEAD_SHA, head[1]), ("BASE", 2, BASE_SHA, base[1]))
    return {
        "schemaVersion": "1.0.0",
        "samples": [
            {
                "role": role,
                "sequence": sequence,
                "commitSha": sha,
                "exitCode": 0 if duration <= 60.0 else 1,
                "output": _output(duration),
            }
            for role, sequence, sha, duration in values
        ],
    }


def test_equivalently_slow_base_and_head_are_environmental_variance():
    decision = evaluate_timing_evidence(
        _evidence((70.0, 73.0), (71.0, 72.0)),
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        limit_seconds=60.0,
    )

    assert decision.allowed is True
    assert decision.code == "ENVIRONMENTAL_EXECUTION_VARIANCE"
    assert decision.base_median == 71.5
    assert decision.head_median == 71.5


def test_materially_slower_head_is_candidate_attributable_and_blocks():
    decision = evaluate_timing_evidence(
        _evidence((54.0, 57.0), (65.0, 66.0)),
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        limit_seconds=60.0,
    )

    assert decision.allowed is False
    assert decision.code == "CANDIDATE_ATTRIBUTABLE_DURATION_REGRESSION"


def test_one_sided_noise_does_not_claim_candidate_attribution():
    decision = evaluate_timing_evidence(
        _evidence((58.0, 76.0), (72.0, 70.0)),
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        limit_seconds=60.0,
    )

    assert decision.allowed is True
    assert decision.code == "ENVIRONMENTAL_EXECUTION_VARIANCE"


def test_semantic_failure_always_blocks_even_when_timing_is_fast():
    evidence = _evidence((54.0, 55.0), (56.0, 57.0))
    evidence["samples"][1]["exitCode"] = 1
    evidence["samples"][1]["output"] = _output(56.0, semantic_failure=True)

    decision = evaluate_timing_evidence(
        evidence,
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        limit_seconds=60.0,
    )

    assert decision.allowed is False
    assert decision.code == "SEMANTIC_GATE_FAILURE"


def test_missing_or_invalid_evidence_fails_closed():
    missing = _evidence((54.0, 55.0), (56.0, 57.0))
    missing["samples"].pop()
    invalid_identity = _evidence((54.0, 55.0), (56.0, 57.0))
    invalid_identity["samples"][0]["commitSha"] = HEAD_SHA

    for evidence in (missing, invalid_identity):
        decision = evaluate_timing_evidence(
            evidence,
            expected_base_sha=BASE_SHA,
            expected_head_sha=HEAD_SHA,
            limit_seconds=60.0,
        )
        assert decision.allowed is False
        assert decision.code == "TIMING_EVIDENCE_INVALID"


def test_silent_disappearance_of_a_heavy_check_fails_closed():
    evidence = _evidence((54.0, 55.0), (56.0, 57.0))
    evidence["samples"][2]["output"] = evidence["samples"][2]["output"].replace(
        "[PASS] historical critical mutation suite\n", ""
    )

    decision = evaluate_timing_evidence(
        evidence,
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        limit_seconds=60.0,
    )

    assert decision.allowed is False
    assert decision.code == "TIMING_EVIDENCE_INVALID"


def test_unknown_output_or_duplicate_check_fails_closed():
    evidence = _evidence((54.0, 55.0), (56.0, 57.0))
    evidence["samples"][3]["output"] += "\n[PASS] regression"

    decision = evaluate_timing_evidence(
        evidence,
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        limit_seconds=60.0,
    )

    assert decision.allowed is False
    assert decision.code == "TIMING_EVIDENCE_INVALID"


def _write_fake_gate(root: Path, *, duration: float) -> None:
    package = root / "scripts/quality"
    package.mkdir(parents=True)
    (root / "scripts/__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    output = _output(duration)
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "marker = Path.cwd().name\n"
        "with Path(os.environ['ORDER_LOG']).open('a', encoding='utf-8') as stream:\n"
        "    stream.write(marker + '\\n')\n"
        f"print({output!r})\n"
        f"raise SystemExit({1 if duration > 60.0 else 0})\n"
    )
    (package / "verify_core.py").write_text(source, encoding="utf-8")


def _commit_fake_gate(root: Path, *, duration: float) -> str:
    _write_fake_gate(root, duration=duration)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Timing Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "timing@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_paired_runner_executes_base_head_base_head_and_emits_exact_evidence(tmp_path):
    base = tmp_path / "base"
    head = tmp_path / "head"
    base_sha = _commit_fake_gate(base, duration=71.0)
    head_sha = _commit_fake_gate(head, duration=70.0)
    (head / "scripts/quality/timing_gate.py").write_text(
        (ROOT / "scripts/quality/timing_gate.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    evidence_path = tmp_path / "evidence.json"
    order_log = tmp_path / "order.log"

    completed = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / ".github/scripts/run-paired-core-safety.ps1"),
            "-BaseRoot", str(base), "-HeadRoot", str(head),
            "-BaseSha", base_sha, "-HeadSha", head_sha,
            "-EvidencePath", str(evidence_path), "-PythonExecutable", "python",
        ],
        cwd=ROOT,
        env={**os.environ, "ORDER_LOG": str(order_log)},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert order_log.read_text(encoding="utf-8").splitlines() == ["base", "head", "head", "base"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert [(row["role"], row["sequence"], row["commitSha"]) for row in evidence["samples"]] == [
        ("BASE", 1, base_sha), ("HEAD", 1, head_sha),
        ("HEAD", 2, head_sha), ("BASE", 2, base_sha),
    ]


def test_paired_runner_rejects_checkout_identity_mismatch(tmp_path):
    base = tmp_path / "base"
    head = tmp_path / "head"
    base_sha = _commit_fake_gate(base, duration=55.0)
    head_sha = _commit_fake_gate(head, duration=56.0)

    completed = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(ROOT / ".github/scripts/run-paired-core-safety.ps1"),
            "-BaseRoot", str(base), "-HeadRoot", str(head),
            "-BaseSha", "3" * 40, "-HeadSha", head_sha,
            "-EvidencePath", str(tmp_path / "evidence.json"), "-PythonExecutable", "python",
        ],
        cwd=ROOT,
        env={**os.environ, "ORDER_LOG": str(tmp_path / "order.log")},
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "checkout identity mismatch" in (completed.stdout + completed.stderr)
    assert base_sha != "3" * 40


def test_core_safety_workflow_uses_exact_event_shas_and_paired_runner():
    workflow = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")

    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "github.event.before" in workflow
    assert "github.sha" in workflow
    assert "run-paired-core-safety.ps1" in workflow
    assert "continue-on-error" not in workflow
