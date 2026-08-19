"""End-to-end proof that the base-owned capability judge is the authoritative,
blocking topology -- exercising the real capability_bootstrap.run_protected_capability_gate
entrypoint (the exact function capability-protected.yml invokes) against a
synthetic protected base, not just its individual components in isolation.
"""
import hashlib
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.quality.capability_analyzer import analyze_capabilities
from scripts.quality.capability_bootstrap import run_protected_capability_gate
from scripts.quality.capability_trust_anchor import BOOTSTRAP_PATH, REGISTRY_PATH

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config/capability-policy-v1.json"
EXCEPTION_SCHEMA_PATH = ROOT / "schemas/capability-exception-v1.schema.json"
LEGIT_PATH = "scripts/quality/legit_baseline_tool.py"
LEGIT_SOURCE = "import subprocess\n"


def _git(repo: Path, *args: str, check: bool = True):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=check)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=test@example.invalid", "-c", "user.name=Test", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _write_registry(repo: Path) -> None:
    bootstrap_sha = _git(repo, "hash-object", BOOTSTRAP_PATH).stdout.strip()
    registry_path = repo / REGISTRY_PATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({
        "schemaVersion": "1.0.0",
        "registryId": "CAPABILITY_PROTECTED_ARTIFACTS_V1",
        "artifacts": [
            {"path": BOOTSTRAP_PATH, "state": "PRESENT", "mode": "100644", "objectType": "blob", "blobSha": bootstrap_sha},
        ],
    }, indent=2), encoding="utf-8")


@pytest.fixture(scope="module")
def protected_base(tmp_path_factory):
    """A synthetic protected base with bootstrap PRESENT and one exact,
    unexpired exception authorizing a legitimate pre-existing acquisition --
    the same shape produced by the CAPABILITY_BASELINE_SEED_RECOVERY_V1 PR."""
    repo = tmp_path_factory.mktemp("base-owned-topology")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / "scripts/quality").mkdir(parents=True)
    (repo / BOOTSTRAP_PATH).write_text("# dummy registry marker, not executed\n", encoding="utf-8")
    (repo / LEGIT_PATH).write_text(LEGIT_SOURCE, encoding="utf-8")
    _write_registry(repo)
    (repo / "config/capability-exceptions-v1.json").write_text(
        json.dumps({"schemaVersion": "1.0.0", "exceptions": []}), encoding="utf-8"
    )
    base_sha = _commit(repo, "protected base: bootstrap present, one legit acquisition")

    tree = _git(repo, "rev-parse", f"{base_sha}^{{tree}}").stdout.strip()
    findings = analyze_capabilities(repo, base_sha, tree, policy_path=POLICY_PATH)
    assert len(findings) == 1 and findings[0]["canonicalPath"] == LEGIT_PATH
    finding = findings[0]
    # Hash the actual git blob, not the working-tree file: Windows write_text()
    # translates \n to \r\n, but git normalizes back to \n on commit, so a
    # working-tree hash would silently mismatch the committed blob.
    legit_blob = subprocess.run(
        ["git", "show", f"{base_sha}:{LEGIT_PATH}"], cwd=repo, capture_output=True, check=True
    ).stdout
    whole_sha = hashlib.sha256(legit_blob).hexdigest()
    exception = {
        "schemaVersion": "1.0.0", "policyVersion": finding["policyVersion"],
        "analyzerVersion": "1.0.0", "ruleVersion": "1.0.0",
        "findingCode": finding["code"], "capabilityClass": finding["code"],
        "canonicalPath": finding["canonicalPath"], "module": finding["module"],
        "acquisitionLocation": finding["location"],
        "normalizedAcquisitionAstSha256": finding["normalizedAstSha256"],
        "wholeFileSha256": whole_sha, "baselineCommit": base_sha,
        "acquiredCapability": "subprocess",
        "justification": "Synthetic baseline acquisition exempted for topology proof.",
        "owner": "TEST_HARNESS", "reviewEvidence": "SYNTHETIC", "disposition": "ACCEPT_BASELINE",
        "reviewBy": (date.today() + timedelta(days=365)).isoformat(),
    }
    (repo / "config/capability-exceptions-v1.json").write_text(
        json.dumps({"schemaVersion": "1.0.0", "exceptions": [exception]}, indent=2), encoding="utf-8"
    )
    base_with_exception_sha = _commit(repo, "protected base: seed exact exception for legit acquisition")
    return repo, base_with_exception_sha


def test_safe_child_of_base_owned_topology_has_no_findings(protected_base):
    repo, base = protected_base
    _git(repo, "checkout", "-q", base)
    (repo / "scripts/quality/safe_addition.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    child = _commit(repo, "safe child")
    assert run_protected_capability_gate(repo, base, child) == []


def test_candidate_registry_self_mutation_blocks_closed(protected_base):
    repo, base = protected_base
    _git(repo, "checkout", "-q", base)
    exceptions = json.loads((repo / "config/capability-exceptions-v1.json").read_text(encoding="utf-8"))
    exceptions["exceptions"].append(dict(exceptions["exceptions"][0]))
    (repo / "config/capability-exceptions-v1.json").write_text(
        json.dumps(exceptions, indent=2), encoding="utf-8"
    )
    child = _commit(repo, "candidate mutates its own exception registry")
    findings = run_protected_capability_gate(repo, base, child)
    assert findings, "registry self-mutation must not be able to authorize itself"
    assert any(item["canonicalPath"] == LEGIT_PATH for item in findings), (
        "mutating the registry must void suppression for the whole batch, "
        "including the previously-exempted acquisition"
    )


TRANSFERRED_REPRODUCERS = {
    "PR50-HIGHER-ORDER-STRING-EXECUTION-BYPASS": (
        "__builtins__['eval'](\"__import__('scripts.quality.target')\")\n",
        "DYNAMIC_EXECUTION_ACQUISITION",
    ),
    "PR50-SYS-MODULES-RETRIEVAL-BYPASS": (
        "import sys\nname = 'os'\nsys.modules.__getitem__('importlib').import_module(name)\n",
        "DYNAMIC_IMPORT_ACQUISITION",
    ),
    "PR50-IMPORT-HOOK-WRITE-BYPASS": (
        "import sys\nfinder = object()\nsys.meta_path = [finder]\n",
        "SENSITIVE_NAMESPACE_ESCAPE",
    ),
    "PR50-SYS-9A7815A-001": (
        "payload = '1 + 1'\n__builtins__['eval'](payload)\n",
        "DYNAMIC_EXECUTION_ACQUISITION",
    ),
}


@pytest.mark.parametrize("finding_id", sorted(TRANSFERRED_REPRODUCERS))
def test_each_transferred_reproducer_is_blocked_by_base_owned_topology(protected_base, finding_id):
    repo, base = protected_base
    _git(repo, "checkout", "-q", base)
    source, expected_code = TRANSFERRED_REPRODUCERS[finding_id]
    (repo / f"scripts/quality/reproducer_{finding_id.lower().replace('-', '_')}.py").write_text(
        source, encoding="utf-8"
    )
    child = _commit(repo, f"malicious child: {finding_id}")
    findings = run_protected_capability_gate(repo, base, child)
    assert expected_code in {item["code"] for item in findings}, (
        f"{finding_id} must remain blocked by the real base-owned "
        f"capability_bootstrap.run_protected_capability_gate entrypoint"
    )


def test_ledger_finding_ids_match_the_proven_reproducer_set():
    ledger = json.loads(
        (ROOT / "config/architecture-capability-transfers-v2.json").read_text(encoding="utf-8")
    )
    assert {row["findingId"] for row in ledger["findings"]} == set(TRANSFERRED_REPRODUCERS)
