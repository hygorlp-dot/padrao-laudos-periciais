"""PR-C0 contracts for the base-owned capability control-plane rotation."""

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
FUTURE_PATHS = {
    "config/capability-exceptions-v1.json",
    "scripts/quality/capability_analyzer.py",
    "scripts/quality/capability_bootstrap.py",
    "scripts/quality/capability_gate_adapter.py",
}


def test_registry_predeclares_only_contractual_future_artifacts_as_absent():
    registry = json.loads(
        (ROOT / "config/capability-protected-artifacts-v1.json").read_text(encoding="utf-8")
    )
    absent = {
        row["path"]
        for row in registry["artifacts"]
        if row["state"] == "ABSENT"
    }
    assert absent == FUTURE_PATHS
    assert all(not (ROOT / path).exists() for path in absent)


def test_workflow_selects_capability_state_from_trusted_base_only():
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(encoding="utf-8")
    assert "CAPABILITY_BASE_BOOTSTRAP_PRESENT" in workflow
    assert 'Test-Path -LiteralPath "scripts/quality/capability_bootstrap.py"' in workflow
    assert "python -m scripts.quality.capability_bootstrap" in workflow
    assert "candidate/scripts/quality/capability_bootstrap.py" not in workflow
    assert "working-directory: trusted" in workflow
    assert workflow.count("working-directory: trusted") >= 3
    assert "from scripts.quality.capability_trust_anchor import validate_inert_trust_anchor" in workflow


def test_pr_c0_contains_no_capability_judge_or_exception_registry():
    assert all(not (ROOT / path).exists() for path in FUTURE_PATHS)


def test_transferred_capability_findings_remain_exactly_open():
    ledger = json.loads(
        (ROOT / "config/architecture-capability-transfers-v2.json").read_text(encoding="utf-8")
    )
    assert len(ledger["findings"]) == 4
    assert {row["severity"] for row in ledger["findings"]} == {"P1"}
    assert {row["destinationStage"] for row in ledger["findings"]} == {"CAPABILITY_CUTOVER_V1"}
    assert all(row["closureCondition"].startswith("Blocking CAPABILITY_ANALYZER_V1") for row in ledger["findings"])
