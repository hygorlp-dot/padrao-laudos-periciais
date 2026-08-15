import copy
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from scripts.quality.capability_gate_adapter import apply_exact_exceptions


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/capability-exception-v1.schema.json"
REGISTRY = "config/capability-exceptions-v1.json"
SOURCE = b"import subprocess\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def _fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "scripts/quality").mkdir(parents=True)
    (repo / "config").mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "config", "user.name", "Capability Tests"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "capability@example.invalid"], cwd=repo, check=True)
    (repo / "scripts/quality/example.py").write_bytes(SOURCE)
    finding = {
        "schemaVersion": "1.0.0", "analyzer": "CAPABILITY_ANALYZER_V1", "policyVersion": "1.0.0",
        "code": "PROCESS_NAMESPACE_ACQUISITION", "severity": "P1",
        "canonicalPath": "scripts/quality/example.py", "module": "scripts.quality.example",
        "location": {"line": 1, "column": 0}, "normalizedAstSha256": "a" * 64,
    }
    exception = {
        "schemaVersion": "1.0.0", "policyVersion": "1.0.0", "analyzerVersion": "1.0.0", "ruleVersion": "1.0.0",
        "findingCode": finding["code"], "capabilityClass": finding["code"],
        "canonicalPath": finding["canonicalPath"], "module": finding["module"],
        "acquisitionLocation": finding["location"], "normalizedAcquisitionAstSha256": finding["normalizedAstSha256"],
        "wholeFileSha256": hashlib.sha256(SOURCE).hexdigest(), "baselineCommit": "0" * 40,
        "acquiredCapability": "subprocess", "justification": "Reviewed quality subprocess acquisition only.",
        "owner": "QUALITY_GOVERNANCE", "reviewEvidence": "REVIEW-1", "disposition": "REMOVE_BY_EXPIRY",
        "reviewBy": "2099-01-01",
    }
    (repo / REGISTRY).write_text(json.dumps({"schemaVersion": "1.0.0", "exceptions": []}), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=repo, check=True)
    seed = _git(repo, "rev-parse", "HEAD")
    exception["baselineCommit"] = seed
    (repo / REGISTRY).write_text(json.dumps({"schemaVersion": "1.0.0", "exceptions": [exception]}), encoding="utf-8")
    subprocess.run(["git", "add", REGISTRY], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline registry"], cwd=repo, check=True)
    baseline = _git(repo, "rev-parse", "HEAD")
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "candidate"], cwd=repo, check=True)
    candidate = _git(repo, "rev-parse", "HEAD")
    return repo, baseline, candidate, finding, exception


def _apply(repo, baseline, candidate, finding, **kwargs):
    return apply_exact_exceptions(repo, [finding], baseline, candidate, registry_path=REGISTRY, schema_path=SCHEMA,
                                  now=date(2026, 8, 14), **kwargs)


def test_exact_preexisting_unexpired_exception_authorizes_only_matching_finding(tmp_path):
    repo, baseline, candidate, finding, _ = _fixture(tmp_path)
    assert _apply(repo, baseline, candidate, finding) == []


@pytest.mark.parametrize("field,value", [
    ("findingCode", "DYNAMIC_EXECUTION_ACQUISITION"), ("canonicalPath", "scripts/quality/other.py"),
    ("module", "scripts.quality.other"), ("normalizedAcquisitionAstSha256", "b" * 64),
    ("policyVersion", "2.0.0"), ("analyzerVersion", "2.0.0"), ("ruleVersion", "2.0.0"),
    ("wholeFileSha256", "b" * 64), ("reviewBy", "2020-01-01"),
])
def test_mismatch_or_expiry_blocks_closed(tmp_path, field, value):
    repo, baseline, candidate, finding, exception = _fixture(tmp_path)
    registry = {"schemaVersion": "1.0.0", "exceptions": [dict(exception, **{field: value})]}
    (repo / REGISTRY).write_text(json.dumps(registry), encoding="utf-8")
    subprocess.run(["git", "add", REGISTRY], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "mismatch"], cwd=repo, check=True)
    candidate = _git(repo, "rev-parse", "HEAD")
    assert _apply(repo, baseline, candidate, finding) == [finding]


def test_duplicate_or_candidate_only_registry_blocks_closed(tmp_path):
    repo, baseline, candidate, finding, exception = _fixture(tmp_path)
    for rows in ([exception, copy.deepcopy(exception)], []):
        (repo / REGISTRY).write_text(json.dumps({"schemaVersion": "1.0.0", "exceptions": rows}), encoding="utf-8")
        subprocess.run(["git", "add", REGISTRY], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "candidate registry"], cwd=repo, check=True)
        candidate = _git(repo, "rev-parse", "HEAD")
        assert _apply(repo, baseline, candidate, finding) == [finding]


def test_nonancestor_baseline_and_git_read_failure_block_closed(tmp_path):
    repo, baseline, candidate, finding, _ = _fixture(tmp_path)
    subprocess.run(["git", "checkout", "-q", "--orphan", "other"], cwd=repo, check=True)
    (repo / "unrelated").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "unrelated"], cwd=repo, check=True)
    unrelated = _git(repo, "rev-parse", "HEAD")
    assert _apply(repo, unrelated, candidate, finding) == [finding]
    assert _apply(repo, baseline, "f" * 40, finding) == [finding]
