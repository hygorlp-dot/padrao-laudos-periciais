"""Single executable gate for the frozen Core V1."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .config import validate_configuration
from .architecture_gate import load_and_validate as validate_architecture
from .fixture_registry import validate_fixture_registry
from .metrics import analyze_complexity, parse_coverage_totals, validate_quality_baseline

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GateResult:
    result: str
    exit_code: int
    checks: tuple[tuple[str, bool], ...]
    findings: tuple[dict, ...]
    duration_seconds: float
    component_durations: tuple[tuple[str, float], ...] = ()


def _finding(invariant: str, boundary: str, test: str, reason: str, severity: str = "P1") -> dict:
    return {"invariant": invariant, "boundary": boundary, "teste": test, "motivo": reason, "severidade": severity}


def check_private_tracking(tracked_files: list[str]) -> list[dict]:
    private = [path for path in tracked_files if path.replace("\\", "/").startswith("referencias/privadas/")]
    return [_finding("PII_DENY_BY_DEFAULT", "REPOSITORY", path, "referência privada rastreada", "P0") for path in private]


def _run(runner, command: list[str], root: Path):
    return runner(command, cwd=root, capture_output=True, text=True)


def run_gate(mode: str, root: Path = ROOT, *, runner=subprocess.run, tracked_files: list[str] | None = None) -> GateResult:
    started = time.perf_counter(); findings: list[dict] = []; checks: list[tuple[str, bool]] = []; durations: dict[str, float] = {}
    architecture_started = time.perf_counter()
    architecture_errors = [
        _finding("ARCHITECTURE_DIRECTION", "QUALITY_GATE", item.get("code", "ARCHITECTURE_INVALID"), str(item), "P1")
        for item in validate_architecture(root)
    ]
    durations["architecture"] = time.perf_counter() - architecture_started
    direct = (("invariants", validate_configuration(root)), ("fixtures", validate_fixture_registry(root)),
              ("architecture", architecture_errors))
    for name, errors in direct:
        checks.append((name, not errors)); findings.extend(errors)
    if tracked_files is None:
        git = _run(runner, ["git", "ls-files"], root)
        tracked_files = git.stdout.splitlines() if git.returncode == 0 else []
        if git.returncode != 0:
            findings.append(_finding("FAIL_CLOSED", "REPOSITORY", "git ls-files", git.stderr or "git indisponível", "P1"))
    privacy = check_private_tracking(tracked_files); checks.append(("privacy", not privacy)); findings.extend(privacy)
    commands = [
        ("property tests", [sys.executable, "-m", "pytest", "-q", "tests/test_core_properties.py"], "SEMANTIC_MONOTONICITY", "CORE"),
        ("gate tests", [sys.executable, "-m", "pytest", "-q", "tests/test_repository_safety_gate.py"], "FAIL_CLOSED", "REPOSITORY"),
        ("compileall", [sys.executable, "-m", "compileall", "-q", "scripts", "tests"], "FAIL_CLOSED", "REPOSITORY"),
    ]
    if mode == "full":
        commands.extend([
            ("historical critical mutation suite", [sys.executable, "-m", "pytest", "-q", "tests/test_historical_mutations.py::test_historical_critical_mutants_are_all_killed"], "NO_SILENT_LOSS", "QUALITY_GATE"),
            ("quality V2", [sys.executable, "-m", "pytest", "-q", "tests/test_core_properties_v2.py", "tests/test_fault_injection.py", "tests/test_schema_versions.py", "tests/test_quality_metrics.py", "tests/test_quality_hardening_v2.py", "tests/test_historical_mutations.py", "-k", "not historical_critical_mutants"], "SCHEMA_VERSION_FIDELITY", "QUALITY_GATE"),
            ("schemas", [sys.executable, "scripts/validar_schemas.py"], "SOURCE_TRUTH", "REPOSITORY"),
            ("regression", [sys.executable, "-m", "coverage", "run", "--branch", "--data-file=coverage-quality-v2.data", "--source=scripts/extracao_pje,scripts/planejamento_pericial,scripts/conhecimento_privado,scripts/redacao_pericial", "-m", "pytest", "tests", "-q", "--ignore=tests/test_historical_mutations.py", "--ignore=tests/test_core_properties_v2.py", "--ignore=tests/test_fault_injection.py", "--ignore=tests/test_schema_versions.py", "--ignore=tests/test_quality_metrics.py", "--ignore=tests/test_quality_hardening_v2.py"], "FAIL_CLOSED", "CORE"),
            ("coverage report", [sys.executable, "-m", "coverage", "json", "--data-file=coverage-quality-v2.data", "-o", "coverage-quality-v2.json"], "QUALITY_NON_REGRESSION", "QUALITY_GATE"),
            ("E2E positive", [sys.executable, "-m", "pytest", "-q", "tests/test_final_closure_r7.py", "-k", "e2e_positivo"], "SOURCE_TRUTH", "MOTOR"),
            ("E2E negative", [sys.executable, "-m", "pytest", "-q", "tests/test_aceitacao_final_motor_v1.py", "-k", "e2e_final_03"], "ESSENTIAL_INPUT_REMOVAL_DEGRADES_RESULT", "MOTOR"),
        ])
    if (root / ".git").exists():
        commands.append(("diff check", ["git", "diff", "--check"], "NO_SILENT_OVERWRITE", "REPOSITORY"))
    for name, command, invariant, boundary in commands:
        component_started = time.perf_counter(); completed = _run(runner, command, root)
        durations[name] = time.perf_counter() - component_started
        passed = completed.returncode == 0; checks.append((name, passed))
        if not passed:
            reason = (completed.stderr or completed.stdout or f"exit {completed.returncode}").strip().splitlines()[-1]
            findings.append(_finding(invariant, boundary, name, reason, "P0" if name in {"regression", "E2E negative", "privacy"} else "P1"))
    if mode == "full":
        quality_findings: list[dict] = []
        try:
            baseline = json.loads((root / "config/quality-baseline.json").read_text(encoding="utf-8"))
            report = json.loads((root / "coverage-quality-v2.json").read_text(encoding="utf-8"))
            paths = [root / item["path"] for item in baseline.get("hotspots", [])]
            complexity = analyze_complexity(paths, base=root)
            elapsed = time.perf_counter() - started
            quality_findings = validate_quality_baseline(
                baseline, parse_coverage_totals(report), complexity, duration_seconds=elapsed,
                component_durations=durations,
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            quality_findings = [{"code": "QUALITY_MEASUREMENT_INVALID", "detail": str(exc)}]
        checks.append(("quality non-regression", not quality_findings))
        for item in quality_findings:
            findings.append(_finding("QUALITY_NON_REGRESSION", "QUALITY_GATE", item["code"], str(item), "P1"))
    passed = not findings and all(ok for _, ok in checks)
    return GateResult("PASS" if passed else "FAIL", 0 if passed else 1, tuple(checks), tuple(findings),
                      round(time.perf_counter() - started, 3),
                      tuple((name, round(value, 3)) for name, value in sorted(durations.items())))


def _print(result: GateResult) -> None:
    print("CORE SAFETY GATE\n")
    for name, passed in result.checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    print(f"\nRESULT: {result.result}")
    if result.findings:
        for item in result.findings:
            print(" | ".join(str(item[key]) for key in ("invariant", "boundary", "teste", "motivo", "severidade")))
    for name, duration in result.component_durations:
        print(f"COMPONENT_DURATION_SECONDS: {name}={duration:.3f}")
    print(f"DURATION_SECONDS: {result.duration_seconds:.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); group = parser.add_mutually_exclusive_group()
    group.add_argument("--fast", action="store_true"); group.add_argument("--full", action="store_true")
    args = parser.parse_args(argv); result = run_gate("fast" if args.fast else "full"); _print(result); return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
