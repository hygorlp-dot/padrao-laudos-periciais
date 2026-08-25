"""Future base-owned blocking capability judge; candidate code is never executed."""
from __future__ import annotations

import os
import subprocess
from datetime import date
from pathlib import Path

from scripts.quality.capability_analyzer import analyze_capabilities
from scripts.quality.capability_gate_adapter import apply_exact_exceptions
from scripts.quality.capability_trust_anchor import validate_inert_trust_anchor


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


def main() -> int:
    findings = run_protected_capability_gate(
        Path(os.environ["CAPABILITY_CANDIDATE_ROOT"]),
        os.environ["CAPABILITY_PROTECTED_BASE_SHA"],
        os.environ["CAPABILITY_EXPECTED_HEAD_SHA"],
    )
    print(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
