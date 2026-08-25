"""Base-owned capability judge and protected timing control plane."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
import re
import subprocess
import tempfile
import venv
from datetime import date
from pathlib import Path

from scripts.quality.capability_analyzer import analyze_capabilities
from scripts.quality.capability_gate_adapter import apply_exact_exceptions
from scripts.quality.capability_trust_anchor import validate_inert_trust_anchor


_SHA = re.compile(r"[0-9a-f]{40}")
_TIMING_ORDER = (("BASE", 1), ("HEAD", 1), ("HEAD", 2), ("BASE", 2))
_FULL_GATE_CHECKS = (
    "invariants",
    "fixtures",
    "privacy",
    "property tests",
    "gate tests",
    "compileall",
    "historical critical mutation suite",
    "quality V2",
    "schemas",
    "E2E positive",
    "E2E negative",
    "capability cutover tests",
    "regression",
    "coverage report",
    "diff check",
    "quality non-regression",
)


@dataclass(frozen=True)
class CheckoutIdentity:
    commit_sha: str
    tree_sha: str
    test_inventory: tuple[str, ...]
    dependency_identity: str


@dataclass(frozen=True)
class TimingSample:
    role: str
    sequence: int
    commit_sha: str
    tree_sha: str
    test_inventory: tuple[str, ...]
    dependency_identity: str
    duration_seconds: float
    semantic_passed: bool


@dataclass(frozen=True)
class TimingDecision:
    allowed: bool
    code: str
    detail: str = ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def capture_checkout_identity(root: Path, expected_sha: str) -> CheckoutIdentity:
    """Bind a sample to exact committed bytes and reject tracked mutations."""
    if _SHA.fullmatch(expected_sha) is None:
        raise ValueError("commit identity is malformed")
    head = _git(root, "rev-parse", "HEAD")
    tree = _git(root, "rev-parse", f"{expected_sha}^{{tree}}")
    dirty = _git(root, "diff", "--quiet", expected_sha, "--")
    tests = _git(root, "ls-tree", "-r", expected_sha, "--", "tests")
    dependency = _git(root, "ls-tree", expected_sha, "--", "requirements-dev.txt")
    if any(item.returncode for item in (head, tree, tests, dependency)):
        raise ValueError("Git identity is unavailable")
    if head.stdout.strip() != expected_sha or dirty.returncode:
        raise ValueError("checkout tracked bytes diverge from expected commit")
    tree_sha = tree.stdout.strip()
    if _SHA.fullmatch(tree_sha) is None:
        raise ValueError("tree identity is malformed")
    test_inventory = tuple(line for line in tests.stdout.splitlines() if line)
    if not test_inventory:
        raise ValueError("test inventory is empty")
    dependency_lines = [line for line in dependency.stdout.splitlines() if line]
    if len(dependency_lines) != 1:
        raise ValueError("dependency identity is unavailable")
    return CheckoutIdentity(expected_sha, tree_sha, test_inventory, dependency_lines[0])


def validate_isolated_python_environments(base_python: Path, head_python: Path) -> None:
    if base_python.resolve() == head_python.resolve():
        raise ValueError("BASE and HEAD require isolated Python environments")
    if not base_python.is_file() or not head_python.is_file():
        raise ValueError("isolated Python environment is unavailable")


def _inventory_paths(rows: tuple[str, ...]) -> tuple[str, ...] | None:
    paths: list[str] = []
    for row in rows:
        try:
            metadata, path = row.split("\t", 1)
            mode, object_type, object_id = metadata.split()
        except ValueError:
            return None
        if (
            mode not in {"100644", "100755"}
            or object_type != "blob"
            or _SHA.fullmatch(object_id) is None
            or not path.startswith("tests/")
            or "\\" in path
        ):
            return None
        paths.append(path)
    if tuple(sorted(paths)) != tuple(paths) or len(paths) != len(set(paths)):
        return None
    return tuple(paths)


def _dependency_identity_valid(value: str) -> bool:
    try:
        metadata, path = value.split("\t", 1)
        mode, object_type, object_id = metadata.split()
    except ValueError:
        return False
    return (
        path == "requirements-dev.txt"
        and mode in {"100644", "100755"}
        and object_type == "blob"
        and _SHA.fullmatch(object_id) is not None
    )


def evaluate_paired_timing(
    samples: tuple[TimingSample, ...],
    *,
    expected_base_sha: str,
    expected_head_sha: str,
    expected_base_tree: str,
    expected_head_tree: str,
    limit_seconds: float,
) -> TimingDecision:
    """Apply a tolerance-free paired attribution rule to exact evidence."""
    if (
        len(samples) != 4
        or any(_SHA.fullmatch(value) is None for value in (
            expected_base_sha, expected_head_sha, expected_base_tree, expected_head_tree
        ))
        or expected_base_sha == expected_head_sha
        or not isinstance(limit_seconds, (int, float))
        or isinstance(limit_seconds, bool)
        or not math.isfinite(float(limit_seconds))
        or limit_seconds <= 0
    ):
        return TimingDecision(False, "TIMING_EVIDENCE_INVALID", "top-level contract")

    by_role: dict[str, list[TimingSample]] = {"BASE": [], "HEAD": []}
    for sample, expected_order in zip(samples, _TIMING_ORDER):
        expected_role, expected_sequence = expected_order
        expected_sha = expected_base_sha if expected_role == "BASE" else expected_head_sha
        expected_tree = expected_base_tree if expected_role == "BASE" else expected_head_tree
        if (
            sample.role != expected_role
            or sample.sequence != expected_sequence
            or sample.commit_sha != expected_sha
            or sample.tree_sha != expected_tree
            or _inventory_paths(sample.test_inventory) is None
            or not _dependency_identity_valid(sample.dependency_identity)
            or not isinstance(sample.semantic_passed, bool)
            or not isinstance(sample.duration_seconds, (int, float))
            or isinstance(sample.duration_seconds, bool)
            or not math.isfinite(float(sample.duration_seconds))
            or sample.duration_seconds <= 0
        ):
            return TimingDecision(False, "TIMING_EVIDENCE_INVALID", "sample identity or shape")
        by_role[expected_role].append(sample)

    for role in ("BASE", "HEAD"):
        first, second = by_role[role]
        if (
            first.test_inventory != second.test_inventory
            or first.dependency_identity != second.dependency_identity
        ):
            return TimingDecision(False, "TIMING_EVIDENCE_INVALID", f"{role} inventory drift")
    base_paths = set(_inventory_paths(by_role["BASE"][0].test_inventory) or ())
    head_paths = set(_inventory_paths(by_role["HEAD"][0].test_inventory) or ())
    if not base_paths <= head_paths:
        return TimingDecision(False, "TEST_INVENTORY_REGRESSION", "HEAD removed tracked tests")
    if any(not sample.semantic_passed for sample in samples):
        return TimingDecision(False, "SEMANTIC_GATE_FAILURE")

    base = tuple(float(item.duration_seconds) for item in by_role["BASE"])
    head = tuple(float(item.duration_seconds) for item in by_role["HEAD"])
    detail = f"BASE={base};HEAD={head};TARGET={float(limit_seconds):.3f}"
    if max(head) <= limit_seconds:
        return TimingDecision(True, "ABSOLUTE_DURATION_WITHIN_LIMIT", detail)
    if min(base) <= limit_seconds:
        return TimingDecision(False, "ABSOLUTE_TARGET_CROSSING", detail)
    if min(head) <= limit_seconds:
        return TimingDecision(False, "TIMING_EVIDENCE_INCONSISTENT", detail)
    if min(head) > max(base):
        return TimingDecision(False, "CANDIDATE_ATTRIBUTABLE_DURATION_REGRESSION", detail)
    return TimingDecision(True, "ENVIRONMENTAL_EXECUTION_VARIANCE", detail)


def _sample_from_output(
    output: str,
    returncode: int,
    role: str,
    sequence: int,
    identity: CheckoutIdentity,
) -> TimingSample:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("gate output is malformed") from exc
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "result", "exitCode", "checks", "findings",
        "durationSeconds", "durationDeferred",
    }:
        raise ValueError("gate output schema is malformed")
    checks = value.get("checks")
    if (
        value.get("schemaVersion") != "1.0.0"
        or value.get("exitCode") != returncode
        or not isinstance(checks, list)
        or tuple(item.get("name") for item in checks if isinstance(item, dict)) != _FULL_GATE_CHECKS
        or any(set(item) != {"name", "passed"} or not isinstance(item["passed"], bool) for item in checks)
        or not isinstance(value.get("findings"), list)
        or not isinstance(value.get("durationDeferred"), bool)
        or not isinstance(value.get("durationSeconds"), (int, float))
        or isinstance(value.get("durationSeconds"), bool)
        or not math.isfinite(float(value["durationSeconds"]))
        or value["durationSeconds"] <= 0
    ):
        raise ValueError("gate output is incomplete")
    semantic_passed = (
        returncode == 0
        and value.get("result") == "PASS"
        and all(item["passed"] for item in checks)
        and not value["findings"]
    )
    return TimingSample(
        role,
        sequence,
        identity.commit_sha,
        identity.tree_sha,
        identity.test_inventory,
        identity.dependency_identity,
        float(value["durationSeconds"]),
        semantic_passed,
    )


def run_paired_timing_gate(
    base_root: Path,
    head_root: Path,
    base_sha: str,
    head_sha: str,
    base_python: Path,
    head_python: Path,
    *,
    limit_seconds: float = 60.0,
) -> TimingDecision:
    """Run BASE/HEAD in isolated environments under the base-owned judge."""
    try:
        validate_isolated_python_environments(base_python, head_python)
        initial = {
            "BASE": capture_checkout_identity(base_root, base_sha),
            "HEAD": capture_checkout_identity(head_root, head_sha),
        }
        samples: list[TimingSample] = []
        for role, sequence in _TIMING_ORDER:
            root = base_root if role == "BASE" else head_root
            python = base_python if role == "BASE" else head_python
            before = capture_checkout_identity(root, base_sha if role == "BASE" else head_sha)
            if before != initial[role]:
                raise ValueError("checkout identity drifted before sample")
            completed = subprocess.run(
                [
                    str(python), "-m", "scripts.quality.verify_core", "--full",
                    "--defer-duration-to-protected-timing", "--json",
                ],
                cwd=root,
                capture_output=True,
                text=True,
            )
            after = capture_checkout_identity(root, base_sha if role == "BASE" else head_sha)
            if after != before:
                raise ValueError("checkout identity drifted during sample")
            sample = _sample_from_output(completed.stdout, completed.returncode, role, sequence, before)
            if not sample.semantic_passed:
                return TimingDecision(False, "SEMANTIC_GATE_FAILURE", completed.stderr[-1000:])
            samples.append(sample)
        return evaluate_paired_timing(
            tuple(samples),
            expected_base_sha=base_sha,
            expected_head_sha=head_sha,
            expected_base_tree=initial["BASE"].tree_sha,
            expected_head_tree=initial["HEAD"].tree_sha,
            limit_seconds=limit_seconds,
        )
    except (OSError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        return TimingDecision(False, "TIMING_EVIDENCE_INVALID", str(exc))


def _create_isolated_environment(root: Path, destination: Path) -> Path:
    venv.EnvBuilder(with_pip=True, clear=True).create(destination)
    python = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    completed = subprocess.run(
        [
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(root / "requirements-dev.txt"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ValueError("isolated dependency installation failed")
    return python


def run_timing_from_protected_environment(
    candidate_root: Path,
    protected_base: str,
    expected_head: str,
) -> TimingDecision:
    """Create per-tree environments and execute only the protected orchestrator."""
    protected_root = Path(__file__).resolve().parents[2]
    try:
        with tempfile.TemporaryDirectory(prefix="base-owned-timing-") as temporary:
            temporary_root = Path(temporary)
            base_python = _create_isolated_environment(protected_root, temporary_root / "base")
            head_python = _create_isolated_environment(candidate_root, temporary_root / "head")
            return run_paired_timing_gate(
                protected_root,
                candidate_root,
                protected_base,
                expected_head,
                base_python,
                head_python,
            )
    except (OSError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        return TimingDecision(False, "TIMING_EVIDENCE_INVALID", str(exc))


def run_protected_capability_gate(candidate_root: Path, protected_base: str, expected_head: str) -> list[dict]:
    custody = validate_inert_trust_anchor(candidate_root, protected_base, expected_head)
    if custody:
        return custody
    tree = subprocess.check_output(
        ["git", "rev-parse", f"{expected_head}^{{tree}}"], cwd=candidate_root, text=True
    ).strip()
    findings = analyze_capabilities(
        candidate_root,
        expected_head,
        tree,
        policy_path=Path(__file__).resolve().parents[2] / "config/capability-policy-v1.json",
    )
    return apply_exact_exceptions(
        candidate_root,
        findings,
        protected_base,
        expected_head,
        registry_path="config/capability-exceptions-v1.json",
        schema_path=Path(__file__).resolve().parents[2] / "schemas/capability-exception-v1.schema.json",
        now=date.today(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timing-gate", action="store_true")
    args = parser.parse_args(argv)
    candidate_root = Path(os.environ["CAPABILITY_CANDIDATE_ROOT"])
    protected_base = os.environ["CAPABILITY_PROTECTED_BASE_SHA"]
    expected_head = os.environ["CAPABILITY_EXPECTED_HEAD_SHA"]
    if args.timing_gate:
        decision = run_timing_from_protected_environment(candidate_root, protected_base, expected_head)
        print(json.dumps({"allowed": decision.allowed, "code": decision.code, "detail": decision.detail}))
        return 0 if decision.allowed else 1
    findings = run_protected_capability_gate(
        candidate_root,
        protected_base,
        expected_head,
    )
    print(findings)
    if findings:
        return 1
    decision = run_timing_from_protected_environment(candidate_root, protected_base, expected_head)
    print(json.dumps({"allowed": decision.allowed, "code": decision.code, "detail": decision.detail}))
    return 0 if decision.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
