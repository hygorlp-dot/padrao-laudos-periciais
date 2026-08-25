"""Fail-closed evaluation of paired BASE/HEAD full-gate timing evidence."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from statistics import median


FULL_GATE_CHECKS = (
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

_EXPECTED_SAMPLE_IDENTITIES = (("BASE", 1), ("HEAD", 1), ("HEAD", 2), ("BASE", 2))
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class TimingDecision:
    allowed: bool
    code: str
    base_samples: tuple[float, ...] = ()
    head_samples: tuple[float, ...] = ()
    base_median: float | None = None
    head_median: float | None = None
    detail: str = ""


@dataclass(frozen=True)
class _ParsedSample:
    duration: float
    semantic_passed: bool


def _invalid(detail: str) -> TimingDecision:
    return TimingDecision(False, "TIMING_EVIDENCE_INVALID", detail=detail)


def _parse_sample_output(output: str, exit_code: int, limit_seconds: float) -> _ParsedSample | None:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    minimum = 1 + len(FULL_GATE_CHECKS) + 2
    if len(lines) < minimum or lines[0] != "CORE SAFETY GATE":
        return None

    statuses: list[bool] = []
    for index, name in enumerate(FULL_GATE_CHECKS, start=1):
        match = re.fullmatch(r"\[(PASS|FAIL)\] (.+)", lines[index])
        if match is None or match.group(2) != name:
            return None
        statuses.append(match.group(1) == "PASS")

    result_index = 1 + len(FULL_GATE_CHECKS)
    result_match = re.fullmatch(r"RESULT: (PASS|FAIL)", lines[result_index])
    duration_match = re.fullmatch(r"DURATION_SECONDS: ([0-9]+(?:\.[0-9]+)?)", lines[-1])
    if result_match is None or duration_match is None:
        return None
    duration = float(duration_match.group(1))
    if not math.isfinite(duration) or duration < 0:
        return None

    finding_lines = lines[result_index + 1:-1]
    findings: list[tuple[str, str, str, str, str]] = []
    for line in finding_lines:
        fields = tuple(part.strip() for part in line.split(" | ", 4))
        if len(fields) != 5 or not all(fields) or fields[-1] not in {"P0", "P1", "P2"}:
            return None
        findings.append(fields)  # type: ignore[arg-type]

    reported_pass = result_match.group(1) == "PASS"
    if reported_pass:
        if exit_code != 0 or not all(statuses) or findings or duration > limit_seconds:
            return None
        return _ParsedSample(duration, True)

    if exit_code == 0 or all(statuses) or not findings:
        return None
    timing_only = (
        statuses == [True] * (len(FULL_GATE_CHECKS) - 1) + [False]
        and len(findings) == 1
        and findings[0][0:3] == (
            "QUALITY_NON_REGRESSION",
            "QUALITY_GATE",
            "FULL_GATE_DURATION_REGRESSION",
        )
        and findings[0][4] == "P1"
        and duration > limit_seconds
    )
    return _ParsedSample(duration, timing_only)


def evaluate_timing_evidence(
    evidence: object,
    *,
    expected_base_sha: str,
    expected_head_sha: str,
    limit_seconds: float,
) -> TimingDecision:
    """Evaluate two interleaved samples per exact commit without masking semantics."""
    if (
        not isinstance(evidence, dict)
        or set(evidence) != {"schemaVersion", "samples"}
        or evidence.get("schemaVersion") != "1.0.0"
        or not isinstance(limit_seconds, (int, float))
        or isinstance(limit_seconds, bool)
        or not math.isfinite(float(limit_seconds))
        or limit_seconds <= 0
        or _SHA_PATTERN.fullmatch(expected_base_sha) is None
        or _SHA_PATTERN.fullmatch(expected_head_sha) is None
        or expected_base_sha == expected_head_sha
    ):
        return _invalid("invalid top-level contract")

    samples = evidence.get("samples")
    if not isinstance(samples, list) or len(samples) != len(_EXPECTED_SAMPLE_IDENTITIES):
        return _invalid("exactly four interleaved samples are required")

    parsed: list[tuple[str, _ParsedSample]] = []
    for row, (expected_role, expected_sequence) in zip(samples, _EXPECTED_SAMPLE_IDENTITIES):
        if not isinstance(row, dict) or set(row) != {"role", "sequence", "commitSha", "exitCode", "output"}:
            return _invalid("sample schema is malformed")
        expected_sha = expected_base_sha if expected_role == "BASE" else expected_head_sha
        if (
            row.get("role") != expected_role
            or row.get("sequence") != expected_sequence
            or row.get("commitSha") != expected_sha
            or not isinstance(row.get("exitCode"), int)
            or isinstance(row.get("exitCode"), bool)
            or not isinstance(row.get("output"), str)
        ):
            return _invalid("sample identity or type mismatch")
        sample = _parse_sample_output(row["output"], row["exitCode"], float(limit_seconds))
        if sample is None:
            return _invalid("sample output is incomplete or inconsistent")
        parsed.append((expected_role, sample))

    if any(not sample.semantic_passed for _, sample in parsed):
        return TimingDecision(False, "SEMANTIC_GATE_FAILURE", detail="at least one full gate had a non-timing failure")

    base = tuple(sample.duration for role, sample in parsed if role == "BASE")
    head = tuple(sample.duration for role, sample in parsed if role == "HEAD")
    base_median = float(median(base))
    head_median = float(median(head))
    common = {
        "base_samples": base,
        "head_samples": head,
        "base_median": base_median,
        "head_median": head_median,
    }
    if max(head) <= float(limit_seconds):
        return TimingDecision(True, "ABSOLUTE_DURATION_WITHIN_LIMIT", **common)
    expected_head_one = (2 * base[0] + base[1]) / 3
    expected_head_two = (base[0] + 2 * base[1]) / 3
    residuals = (head[0] - expected_head_one, head[1] - expected_head_two)
    detail = "HEAD_RESIDUALS_SECONDS=" + ",".join(f"{value:.3f}" for value in residuals)
    if all(value > 0 for value in residuals):
        return TimingDecision(
            False, "CANDIDATE_ATTRIBUTABLE_DURATION_REGRESSION", detail=detail, **common
        )
    return TimingDecision(True, "ENVIRONMENTAL_EXECUTION_VARIANCE", detail=detail, **common)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-base-sha", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--limit-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        decision = evaluate_timing_evidence(
            evidence,
            expected_base_sha=args.expected_base_sha,
            expected_head_sha=args.expected_head_sha,
            limit_seconds=args.limit_seconds,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        decision = _invalid(str(exc))

    print(f"TIMING_GATE_RESULT={'PASS' if decision.allowed else 'FAIL'}")
    print(f"TIMING_GATE_CODE={decision.code}")
    if decision.base_samples:
        print("BASE_SAMPLES_SECONDS=" + ",".join(f"{value:.3f}" for value in decision.base_samples))
        print("HEAD_SAMPLES_SECONDS=" + ",".join(f"{value:.3f}" for value in decision.head_samples))
        print(f"BASE_MEDIAN_SECONDS={decision.base_median:.3f}")
        print(f"HEAD_MEDIAN_SECONDS={decision.head_median:.3f}")
    if decision.detail:
        print(f"DETAIL={decision.detail}")
    return 0 if decision.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
