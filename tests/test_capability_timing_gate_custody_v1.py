from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from scripts.quality import capability_bootstrap
from scripts.quality.capability_bootstrap import (
    TimingSample,
    capture_checkout_identity,
    evaluate_paired_timing,
    validate_isolated_python_environments,
)


BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
BASE_TREE = "3" * 40
HEAD_TREE = "4" * 40


def _sample(
    role: str,
    sequence: int,
    duration: float,
    *,
    semantic_passed: bool = True,
    tests: tuple[str, ...] = ("100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\ttests/test_a.py",),
) -> TimingSample:
    base = role == "BASE"
    return TimingSample(
        role=role,
        sequence=sequence,
        commit_sha=BASE_SHA if base else HEAD_SHA,
        tree_sha=BASE_TREE if base else HEAD_TREE,
        test_inventory=tests,
        dependency_identity=(
            "100644 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trequirements-dev.txt"
            if base
            else "100644 blob cccccccccccccccccccccccccccccccccccccccc\trequirements-dev.txt"
        ),
        duration_seconds=duration,
        semantic_passed=semantic_passed,
    )


def _decision(
    base: tuple[float, float],
    head: tuple[float, float],
    *,
    base_tests: tuple[str, ...] | None = None,
    head_tests: tuple[str, ...] | None = None,
):
    base_inventory = base_tests or _sample("BASE", 1, 1).test_inventory
    head_inventory = head_tests or _sample("HEAD", 1, 1).test_inventory
    samples = (
        _sample("BASE", 1, base[0], tests=base_inventory),
        _sample("HEAD", 1, head[0], tests=head_inventory),
        _sample("HEAD", 2, head[1], tests=head_inventory),
        _sample("BASE", 2, base[1], tests=base_inventory),
    )
    return evaluate_paired_timing(
        samples,
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        expected_base_tree=BASE_TREE,
        expected_head_tree=HEAD_TREE,
        limit_seconds=60.0,
    )


def test_clean_target_crossing_is_blocking_without_fixed_forgiveness():
    decision = _decision((55.0, 55.0), (61.0, 61.0))

    assert decision.allowed is False
    assert decision.code == "ABSOLUTE_TARGET_CROSSING"


def test_equivalent_slow_ranges_are_environmental_without_numeric_tolerance():
    decision = _decision((70.0, 73.0), (71.0, 72.0))

    assert decision.allowed is True
    assert decision.code == "ENVIRONMENTAL_EXECUTION_VARIANCE"


def test_strictly_slower_head_range_is_candidate_attributable():
    decision = _decision((70.0, 73.0), (74.0, 75.0))

    assert decision.allowed is False
    assert decision.code == "CANDIDATE_ATTRIBUTABLE_DURATION_REGRESSION"


def test_semantic_failure_blocks_regardless_of_timing():
    samples = (
        _sample("BASE", 1, 70.0),
        _sample("HEAD", 1, 71.0, semantic_passed=False),
        _sample("HEAD", 2, 72.0),
        _sample("BASE", 2, 73.0),
    )

    decision = evaluate_paired_timing(
        samples,
        expected_base_sha=BASE_SHA,
        expected_head_sha=HEAD_SHA,
        expected_base_tree=BASE_TREE,
        expected_head_tree=HEAD_TREE,
        limit_seconds=60.0,
    )

    assert decision.allowed is False
    assert decision.code == "SEMANTIC_GATE_FAILURE"


def test_missing_base_test_path_fails_closed_instead_of_improving_timing():
    base_tests = (
        "100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\ttests/test_a.py",
        "100644 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\ttests/test_b.py",
    )
    head_tests = (
        "100644 blob cccccccccccccccccccccccccccccccccccccccc\ttests/test_a.py",
    )

    decision = _decision((70.0, 70.0), (65.0, 65.0), base_tests=base_tests, head_tests=head_tests)

    assert decision.allowed is False
    assert decision.code == "TEST_INVENTORY_REGRESSION"


def test_same_python_environment_cannot_be_used_for_base_and_head(tmp_path):
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="isolated"):
        validate_isolated_python_environments(interpreter, interpreter)


def _init_repo(root: Path) -> str:
    (root / "tests").mkdir(parents=True)
    (root / "tests/test_a.py").write_text("def test_a(): assert True\n", encoding="utf-8")
    (root / "requirements-dev.txt").write_text("pytest==9.1.1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Timing Custody Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "timing@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_checkout_identity_detects_tracked_byte_mutation(tmp_path):
    commit = _init_repo(tmp_path)
    before = capture_checkout_identity(tmp_path, commit)
    (tmp_path / "tests/test_a.py").write_text("def test_a(): assert False\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tracked bytes"):
        capture_checkout_identity(tmp_path, commit)

    assert before.commit_sha == commit


def test_stage_a_default_core_workflow_keeps_absolute_duration_dispositive():
    workflow = Path(".github/workflows/core-safety.yml").read_text(encoding="utf-8")

    assert "--defer-duration-to-protected-timing" not in workflow
    assert "python -m scripts.quality.verify_core --full" in workflow


def test_stage_a_timing_control_plane_is_base_owned_and_uses_isolated_environments():
    workflow = Path(".github/workflows/capability-protected.yml").read_text(encoding="utf-8")
    registry = json.loads(Path("config/capability-protected-artifacts-v1.json").read_text(encoding="utf-8"))
    protected_paths = {row["path"] for row in registry["artifacts"]}

    assert "scripts/quality/capability_bootstrap.py" in protected_paths
    assert "scripts/quality/verify_core.py" in protected_paths
    assert "python -m scripts.quality.capability_bootstrap" in workflow
    assert "working-directory: trusted" in workflow
    assert "candidate/scripts/quality/capability_bootstrap.py" not in workflow


def test_protected_entrypoint_runs_timing_only_after_capability_passes(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setenv("CAPABILITY_CANDIDATE_ROOT", str(tmp_path))
    monkeypatch.setenv("CAPABILITY_PROTECTED_BASE_SHA", BASE_SHA)
    monkeypatch.setenv("CAPABILITY_EXPECTED_HEAD_SHA", HEAD_SHA)
    monkeypatch.setattr(
        capability_bootstrap,
        "run_protected_capability_gate",
        lambda *_args: calls.append("capability") or [],
    )
    monkeypatch.setattr(
        capability_bootstrap,
        "run_timing_from_protected_environment",
        lambda *_args: calls.append("timing") or capability_bootstrap.TimingDecision(True, "PASS"),
        raising=False,
    )

    assert capability_bootstrap.main([]) == 0
    assert calls == ["capability", "timing"]


def test_protected_entrypoint_never_runs_timing_after_capability_failure(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setenv("CAPABILITY_CANDIDATE_ROOT", str(tmp_path))
    monkeypatch.setenv("CAPABILITY_PROTECTED_BASE_SHA", BASE_SHA)
    monkeypatch.setenv("CAPABILITY_EXPECTED_HEAD_SHA", HEAD_SHA)
    monkeypatch.setattr(
        capability_bootstrap,
        "run_protected_capability_gate",
        lambda *_args: [{"severity": "P1"}],
    )
    monkeypatch.setattr(
        capability_bootstrap,
        "run_timing_from_protected_environment",
        lambda *_args: calls.append("timing") or capability_bootstrap.TimingDecision(True, "PASS"),
        raising=False,
    )

    assert capability_bootstrap.main([]) == 1
    assert calls == []
