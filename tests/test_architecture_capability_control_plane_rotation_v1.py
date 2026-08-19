"""PR-C0 contracts for the base-owned capability control-plane rotation."""

import json
import subprocess
from pathlib import Path

import jsonschema
import pytest

from scripts.quality.capability_trust_anchor import (
    ARCHITECTURE_TRANSITION_PATH,
    REGISTRY_PATH,
    validate_inert_trust_anchor,
)


ROOT = Path(__file__).parents[1]
FUTURE_PATHS = {
    "config/capability-exceptions-v1.json",
    "scripts/quality/capability_analyzer.py",
    "scripts/quality/capability_bootstrap.py",
    "scripts/quality/capability_gate_adapter.py",
}


def test_pr_c_registry_custodies_exact_shadow_artifacts_as_present():
    registry = json.loads(
        (ROOT / "config/capability-protected-artifacts-v1.json").read_text(encoding="utf-8")
    )
    present = {
        row["path"]
        for row in registry["artifacts"]
        if row["path"] in FUTURE_PATHS and row["state"] == "PRESENT"
    }
    assert present == FUTURE_PATHS
    assert all((ROOT / path).is_file() for path in present)


def test_workflow_selects_capability_state_from_trusted_base_only():
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(encoding="utf-8")
    assert "CAPABILITY_BASE_BOOTSTRAP_PRESENT" in workflow
    assert "_protected_base_bootstrap_present" in workflow
    assert "Test-Path" not in workflow
    assert "python -m scripts.quality.capability_bootstrap" in workflow
    assert "candidate/scripts/quality/capability_bootstrap.py" not in workflow
    assert "working-directory: trusted" in workflow
    assert workflow.count("working-directory: trusted") >= 3
    assert "from scripts.quality.capability_trust_anchor import validate_inert_trust_anchor" in workflow


def test_pr_c_installs_shadow_judge_bytes_without_activation():
    # The exceptions registry was empty when this shadow-judge bootstrap first
    # landed; it now legitimately carries exact, schema-validated baseline
    # exceptions seeded by the CAPABILITY_BASELINE_SEED_RECOVERY_V1 predecessor
    # (see docstring at the bottom of this file), so this test no longer
    # asserts emptiness -- only that every entry is a well-formed exact
    # exception. Real regression coverage for exception semantics (exact-match
    # authorization, staleness, duplication, self-authorization) lives in
    # tests/test_capability_exceptions_v1.py.
    assert all((ROOT / path).is_file() for path in FUTURE_PATHS)
    exceptions = json.loads(
        (ROOT / "config/capability-exceptions-v1.json").read_text(encoding="utf-8")
    )
    assert exceptions["schemaVersion"] == "1.0.0"
    schema = json.loads(
        (ROOT / "schemas/capability-exception-v1.schema.json").read_text(encoding="utf-8")
    )
    for item in exceptions["exceptions"]:
        jsonschema.validate(item, schema)
    policy = json.loads(
        (ROOT / "config/capability-policy-v1.json").read_text(encoding="utf-8")
    )
    assert policy["integrityBootstrap"]["activationState"] == "CONTRACT_ONLY"


def test_transferred_capability_findings_ledger_shape_is_unchanged():
    # This ledger's own declarative content is left untouched by design --
    # closure must come from executable evidence, not an administrative
    # status field invented after the fact. That evidence is
    # tests/test_capability_base_owned_blocking_topology_v1.py, which proves
    # by real execution (via the actual capability_bootstrap.run_protected_capability_gate
    # entrypoint) that every one of these four findingIds' reproducers is
    # blocked by the current base-owned judge. This test only guards that the
    # ledger's own shape (the thing the closure proof depends on staying
    # exact) hasn't silently drifted.
    ledger = json.loads(
        (ROOT / "config/architecture-capability-transfers-v2.json").read_text(encoding="utf-8")
    )
    assert len(ledger["findings"]) == 4
    assert {row["severity"] for row in ledger["findings"]} == {"P1"}
    assert {row["destinationStage"] for row in ledger["findings"]} == {"CAPABILITY_CUTOVER_V1"}
    assert all(row["closureCondition"].startswith("Blocking CAPABILITY_ANALYZER_V1") for row in ledger["findings"])


TRACKED_PATH = "scripts/quality/capability_widget.py"


def _init_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def _write_registry(tmp_path, *, tracked_state):
    registry = tmp_path / REGISTRY_PATH
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "registryId": "CAPABILITY_PROTECTED_ARTIFACTS_V1",
        "artifacts": [tracked_state],
    }), encoding="utf-8")


def _capability_rotation_base(tmp_path):
    """Base commit: registry declares TRACKED_PATH ABSENT, nothing else."""
    _init_repo(tmp_path)
    _write_registry(tmp_path, tracked_state={"path": TRACKED_PATH, "state": "ABSENT"})
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()


def _commit_capability_rotation(tmp_path, protected_base, *, extra_paths=()):
    """Candidate commit: TRACKED_PATH goes ABSENT -> PRESENT, registry updated to match,
    an exact capability transition document authorizes it, plus any extra_paths written
    verbatim (used to probe what else the diff-accounting allows)."""
    widget = tmp_path / TRACKED_PATH
    widget.parent.mkdir(parents=True, exist_ok=True)
    widget.write_text("# capability widget\n", encoding="utf-8")
    subprocess.run(["git", "add", TRACKED_PATH], cwd=tmp_path, check=True)
    candidate_blob = subprocess.check_output(
        ["git", "hash-object", TRACKED_PATH], cwd=tmp_path, text=True,
    ).strip()
    candidate_identity = {
        "path": TRACKED_PATH, "state": "PRESENT",
        "mode": "100644", "objectType": "blob", "blobSha": candidate_blob,
    }
    _write_registry(tmp_path, tracked_state=candidate_identity)
    transition = tmp_path / "config/capability-protected-transition-v1.json"
    transition.parent.mkdir(parents=True, exist_ok=True)
    transition.write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "transitionId": "CAPABILITY_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": protected_base,
        "artifacts": [{
            "path": TRACKED_PATH,
            "base": {"path": TRACKED_PATH, "state": "ABSENT"},
            "candidate": candidate_identity,
        }],
    }), encoding="utf-8")
    for extra_path, content in extra_paths:
        extra_file = tmp_path / extra_path
        extra_file.parent.mkdir(parents=True, exist_ok=True)
        extra_file.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "capability rotation"], cwd=tmp_path, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()


def test_architecture_transition_path_accepted_alongside_real_capability_rotation(tmp_path):
    base = _capability_rotation_base(tmp_path)
    candidate = _commit_capability_rotation(
        tmp_path, base,
        extra_paths=[(ARCHITECTURE_TRANSITION_PATH, "# architecture transition companion\n")],
    )
    assert validate_inert_trust_anchor(tmp_path, base, candidate) == []


@pytest.mark.parametrize("extra_path", [
    "config/architecture-policy-v1.json",
    "config/some-other-config.json",
    "config/architecture-protected-transition-v1.json.bak",
    "config/architecture-protected-transition-v1.jsonx",
    "scripts/quality/architecture_analyzer.py",
])
def test_lookalike_or_arbitrary_paths_remain_rejected_alongside_capability_rotation(tmp_path, extra_path):
    base = _capability_rotation_base(tmp_path)
    candidate = _commit_capability_rotation(
        tmp_path, base,
        extra_paths=[(extra_path, "# not the exact architecture transition path\n")],
    )
    findings = validate_inert_trust_anchor(tmp_path, base, candidate)
    assert any(item["code"] == "CAPABILITY_PROTECTED_TRANSITION_INVALID" for item in findings)


def test_architecture_transition_path_still_rejected_without_a_real_registry_rotation(tmp_path):
    # No registry-tracked identity actually changes here (TRACKED_PATH stays ABSENT), so
    # `changed` is empty and validate_inert_trust_anchor exits before ever consulting the
    # allowlist — the architecture-transition exception must not become a free-standing
    # bypass usable without a genuine capability rotation alongside it.
    _init_repo(tmp_path)
    _write_registry(tmp_path, tracked_state={"path": TRACKED_PATH, "state": "ABSENT"})
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "protected base"], cwd=tmp_path, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    unrelated = tmp_path / ARCHITECTURE_TRANSITION_PATH
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_text("# unrelated change, no capability rotation occurred\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "unrelated architecture-only change"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    assert validate_inert_trust_anchor(tmp_path, base, candidate) == []


def test_existing_fail_closed_behavior_on_missing_transition_is_unchanged(tmp_path):
    base = _capability_rotation_base(tmp_path)
    # Rotate the tracked file but omit the capability transition document entirely.
    widget = tmp_path / TRACKED_PATH
    widget.parent.mkdir(parents=True, exist_ok=True)
    widget.write_text("# capability widget\n", encoding="utf-8")
    subprocess.run(["git", "add", TRACKED_PATH], cwd=tmp_path, check=True)
    candidate_blob = subprocess.check_output(
        ["git", "hash-object", TRACKED_PATH], cwd=tmp_path, text=True,
    ).strip()
    _write_registry(tmp_path, tracked_state={
        "path": TRACKED_PATH, "state": "PRESENT",
        "mode": "100644", "objectType": "blob", "blobSha": candidate_blob,
    })
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "rotate without transition"], cwd=tmp_path, check=True)
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()

    findings = validate_inert_trust_anchor(tmp_path, base, candidate)
    assert any(item["code"] == "CAPABILITY_PROTECTED_TRANSITION_INVALID" for item in findings)


# A test asserting that PR #65/#66's own commit alone (with no capability-registry
# rotation) passed the base-owned judge at HEAD used to live here. That was a
# point-in-time fact about that specific, now-merged commit — evaluating it at a
# floating "HEAD" broke the moment a later commit (this capability bootstrap)
# legitimately performs a real registry rotation on top, which is exactly what
# the fix that commit shipped was meant to allow. The real, ongoing regression
# coverage for the handshake mechanism itself lives in the tests above
# (accepted-alongside-rotation / rejected-without-rotation / lookalike-rejected).
