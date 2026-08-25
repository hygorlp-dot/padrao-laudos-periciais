from __future__ import annotations

import json
from pathlib import Path
import subprocess
import types

import pytest


ROOT = Path(__file__).parents[1]
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
BASE_TREE = "3" * 40
HEAD_TREE = "4" * 40
TEST_A = "100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\ttests/test_a.py"


def _embedded_module() -> types.SimpleNamespace:
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(encoding="utf-8")
    start_marker = "# TIMING_GATE_PYTHON_START\n"
    end_marker = "\n          # TIMING_GATE_PYTHON_END"
    assert workflow.count(start_marker) == 1
    assert workflow.count(end_marker) == 1
    source = workflow.split(start_marker, 1)[1].split(end_marker, 1)[0]
    lines = source.splitlines()
    assert lines[0].strip() == "@'"
    assert lines[-1].strip() == "'@ | Set-Content -LiteralPath $timingJudge -Encoding utf8"
    python_source = "\n".join(line[10:] if line.startswith("          ") else line for line in lines[1:-1])
    namespace: dict[str, object] = {"__name__": "base_owned_timing_test"}
    exec(compile(python_source, "<base-owned-timing-gate>", "exec"), namespace)
    return types.SimpleNamespace(**namespace)


def _sample(role: str, sequence: int, duration: float, *, semantic: bool = True, tests=None):
    base = role == "BASE"
    return {
        "role": role,
        "sequence": sequence,
        "commitSha": BASE_SHA if base else HEAD_SHA,
        "treeSha": BASE_TREE if base else HEAD_TREE,
        "testInventory": list(tests or (TEST_A,)),
        "dependencyIdentity": (
            "100644 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trequirements-dev.txt"
            if base
            else "100644 blob cccccccccccccccccccccccccccccccccccccccc\trequirements-dev.txt"
        ),
        "durationSeconds": duration,
        "semanticPassed": semantic,
    }


def _evaluate(base, head, *, base_tests=None, head_tests=None):
    module = _embedded_module()
    samples = [
        _sample("BASE", 1, base[0], tests=base_tests),
        _sample("HEAD", 1, head[0], tests=head_tests),
        _sample("HEAD", 2, head[1], tests=head_tests),
        _sample("BASE", 2, base[1], tests=base_tests),
    ]
    return module.evaluate(samples, BASE_SHA, HEAD_SHA, BASE_TREE, HEAD_TREE, 60.0)


def test_clean_60_second_crossing_blocks_without_fixed_forgiveness():
    decision = _evaluate((55.0, 55.0), (61.0, 61.0))

    assert decision == {"allowed": False, "code": "ABSOLUTE_TARGET_CROSSING"}


def test_over_limit_overlapping_ranges_are_environmental_without_numeric_tolerance():
    decision = _evaluate((70.0, 73.0), (71.0, 72.0))

    assert decision == {"allowed": True, "code": "ENVIRONMENTAL_EXECUTION_VARIANCE"}


def test_over_limit_strict_head_dominance_blocks_as_candidate_attributable():
    decision = _evaluate((70.0, 73.0), (74.0, 75.0))

    assert decision == {"allowed": False, "code": "CANDIDATE_ATTRIBUTABLE_DURATION_REGRESSION"}


def test_semantic_failure_always_blocks():
    module = _embedded_module()
    samples = [
        _sample("BASE", 1, 70.0),
        _sample("HEAD", 1, 71.0, semantic=False),
        _sample("HEAD", 2, 72.0),
        _sample("BASE", 2, 73.0),
    ]

    assert module.evaluate(samples, BASE_SHA, HEAD_SHA, BASE_TREE, HEAD_TREE, 60.0) == {
        "allowed": False,
        "code": "SEMANTIC_GATE_FAILURE",
    }


def test_removed_test_path_fails_closed():
    base_tests = (
        TEST_A,
        "100644 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\ttests/test_b.py",
    )
    head_tests = (
        "100644 blob cccccccccccccccccccccccccccccccccccccccc\ttests/test_a.py",
    )

    assert _evaluate((70.0, 70.0), (65.0, 65.0), base_tests=base_tests, head_tests=head_tests) == {
        "allowed": False,
        "code": "TEST_INVENTORY_REGRESSION",
    }


def _init_repo(root: Path) -> str:
    (root / "tests").mkdir(parents=True)
    (root / "tests/test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")
    (root / "requirements-dev.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Timing Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "timing@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_identity_capture_rejects_tracked_byte_mutation(tmp_path):
    module = _embedded_module()
    commit = _init_repo(tmp_path)
    identity = module.capture_identity(tmp_path, commit)
    (tmp_path / "tests/test_a.py").write_text("def test_a(): assert False\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tracked bytes"):
        module.capture_identity(tmp_path, commit)

    assert identity["commitSha"] == commit


def test_workflow_uses_protected_base_judge_and_separate_dependency_environments():
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(encoding="utf-8")

    assert "pull_request_target" in workflow
    assert "working-directory: trusted" in workflow
    assert "timing-base-venv" in workflow
    assert "timing-head-venv" in workflow
    assert "candidate/.github" not in workflow
    assert "continue-on-error" not in workflow


def test_stage_a_keeps_candidate_core_safety_duration_dispositive():
    workflow = (ROOT / ".github/workflows/core-safety.yml").read_text(encoding="utf-8")

    assert "python -m scripts.quality.verify_core --full" in workflow
    assert "continue-on-error" not in workflow
    assert "defer-duration" not in workflow


def test_embedded_policy_emits_closed_json_verdicts_only():
    verdict = _evaluate((70.0, 73.0), (71.0, 72.0))

    assert json.loads(json.dumps(verdict, sort_keys=True)) == verdict
    assert set(verdict) == {"allowed", "code"}


def test_parser_accepts_only_the_exact_timing_failure_shape():
    module = _embedded_module()
    checks = [f"[PASS] {name}" for name in module.FULL_CHECKS]
    checks[-1] = "[FAIL] quality non-regression"
    output = "\n".join([
        "CORE SAFETY GATE",
        *checks,
        "RESULT: FAIL",
        "QUALITY_NON_REGRESSION | QUALITY_GATE | FULL_GATE_DURATION_REGRESSION | detail | P1",
        "DURATION_SECONDS: 71.250",
    ])

    assert module.parse_gate_output(output, 1) == (71.25, True)

    with pytest.raises(ValueError, match="incomplete"):
        module.parse_gate_output(output.replace("[PASS] regression\n", ""), 1)


def test_parser_never_relabels_semantic_failure_as_timing_only():
    module = _embedded_module()
    checks = [f"[PASS] {name}" for name in module.FULL_CHECKS]
    checks[3] = "[FAIL] property tests"
    output = "\n".join([
        "CORE SAFETY GATE",
        *checks,
        "RESULT: FAIL",
        "FAIL_CLOSED | CORE | property tests | failure | P0",
        "DURATION_SECONDS: 71.250",
    ])

    assert module.parse_gate_output(output, 1) == (71.25, False)
