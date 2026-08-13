import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.quality.core_baseline import build_baseline, canonical_bytes, semantic_bytes, verify_baseline


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _synthetic_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "baseline@example.invalid")
    _git(repo, "config", "user.name", "Baseline Test")
    files = {
        "config/core-invariants.json": {
            "schema_version": "1.0.0",
            "invariants": [{"id": "FAIL_CLOSED", "boundaries": ["MOTOR"], "testes": ["tests/test_motor.py"], "severidade": "P0", "global": True, "bloqueante": True, "descricao": "x"}],
        },
        "config/core-boundaries.json": {
            "schema_version": "1.0.0",
            "boundaries": [{"id": "MOTOR", "paths": ["scripts/motor/", "docs/padroes/protocolo-"], "invariants": ["FAIL_CLOSED"], "schemas": ["schemas/motor.schema.json"], "tests": ["tests/test_motor.py"], "consumers": []}],
        },
        "tests/fixtures/core-fixtures.json": {
            "schema_version": "1.0.0",
            "fixtures": [{"arquivo": "tests/fixtures/motor.json", "dominio": "MOTOR", "schema": "motor.schema.json", "consumer": "tests/test_motor.py::test_motor", "expected": "VALID", "finalidade": "x"}],
        },
        "config/quality-baseline.json": {"schema_version": "1.0.0", "hotspots": [{"path": "scripts/motor/core.py", "function": "executar", "complexity": 2}]},
        "config/core-registry-lock.json": {"schema_version": "1.0.0"},
        "config/schema-versions.json": {"schema_version": "1.0.0"},
        "scripts/motor/core.py": "import json\n\ndef executar(value, *, flag=False):\n    if flag:\n        return json.dumps(value)\n    return value\n",
        "scripts/motor/__init__.py": "from .core import executar\n__all__ = ['executar']\n",
        "schemas/motor.schema.json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
        "tests/test_motor.py": "def test_motor():\n    assert True\n",
        "tests/fixtures/motor.json": {"ok": True},
        "requirements.txt": "jsonschema==4.0.0\n",
        "docs/padroes/protocolo-one.md": "# Protocol one\n",
        "docs/padroes/protocolo-two.md": "# Protocol two\n",
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict):
            path.write_text(json.dumps(content), encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", *files)
    _git(repo, "commit", "-m", "fixture")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_baseline_is_exact_sha_reproducible_and_ignores_worktree_bytes(tmp_path):
    repo, sha = _synthetic_repo(tmp_path)

    first = build_baseline(repo, sha, baseline_version="V1")
    (repo / "scripts/motor/core.py").write_text("PRIVATE DIRTY BYTES", encoding="utf-8")
    (repo / "untracked.txt").write_text("UNTRACKED", encoding="utf-8")
    second = build_baseline(repo, sha, baseline_version="V1")

    assert canonical_bytes(first) == canonical_bytes(second)
    assert first["coreBaseSha"] == sha
    assert all(not item["path"].startswith("referencias/privadas/") for item in first["coreManifest"])
    core = next(item for item in first["coreManifest"] if item["path"] == "scripts/motor/core.py")
    committed = subprocess.run(
        ["git", "show", f"{sha}:scripts/motor/core.py"], cwd=repo, check=True, capture_output=True
    ).stdout
    assert core["sizeBytes"] == len(committed)
    assert core["sha256"] == hashlib.sha256(committed).hexdigest()


def test_baseline_inventory_and_fingerprint_are_canonical(tmp_path):
    repo, sha = _synthetic_repo(tmp_path)
    baseline = build_baseline(repo, sha, baseline_version="V1")

    assert baseline["baselineVersion"] == "V1"
    assert [item["path"] for item in baseline["coreManifest"]] == sorted(item["path"] for item in baseline["coreManifest"])
    assert baseline["moduleInventory"][0]["path"] == "scripts/motor/__init__.py"
    assert {item["path"] for item in baseline["coreManifest"]} >= {
        "docs/padroes/protocolo-one.md", "docs/padroes/protocolo-two.md"
    }
    assert {tuple(edge.values()) for edge in baseline["dependencyEdges"]} >= {
        ("scripts.motor", "scripts.motor.core")
    }
    assert any(symbol["name"] == "executar" for symbol in baseline["symbolInventory"])
    assert baseline["invariantInventory"][0]["id"] == "FAIL_CLOSED"
    assert baseline["boundaryInventory"][0]["id"] == "MOTOR"
    assert baseline["fixtureBaseline"]["registeredCount"] == 1
    assert baseline["analyzerVersion"] == "1.0.0"
    assert baseline["behavioralBaseline"]["status"] == "NOT_YET_PROVEN"
    with pytest.raises(ValueError, match="evidence SHA mismatch"):
        build_baseline(repo, sha, baseline_version="V1", evidence={"coreBaseSha": "0" * 40})
    assert baseline["riskRegister"]
    assert {item["area"] for item in baseline["gapMatrix"]} >= {"Architecture Gate", "Replay", "Fault Injection"}
    fingerprint = hashlib.sha256(semantic_bytes(baseline)).hexdigest()
    assert baseline["semanticFingerprint"] == fingerprint
    assert verify_baseline(baseline, fingerprint) == []
    assert verify_baseline(baseline, "0" * 64) == ["BASELINE_FINGERPRINT_MISMATCH"]
    assert canonical_bytes(build_baseline(repo, sha, baseline_version="V1")) == canonical_bytes(baseline)


def test_baseline_rejects_unknown_or_private_tracked_boundary_paths(tmp_path):
    repo, sha = _synthetic_repo(tmp_path)
    boundaries_path = repo / "config/core-boundaries.json"
    doc = json.loads(_git(repo, "show", f"{sha}:config/core-boundaries.json"))
    doc["boundaries"][0]["paths"] = ["referencias/privadas/"]
    boundaries_path.write_text(json.dumps(doc), encoding="utf-8")
    _git(repo, "add", "--", "config/core-boundaries.json")
    _git(repo, "commit", "-m", "private boundary")
    private_sha = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="private path"):
        build_baseline(repo, private_sha, baseline_version="V1")


def test_baseline_rejects_registered_prefix_without_tracked_match(tmp_path):
    repo, sha = _synthetic_repo(tmp_path)
    path = repo / "config/core-boundaries.json"
    doc = json.loads(_git(repo, "show", f"{sha}:config/core-boundaries.json"))
    doc["boundaries"][0]["paths"] = ["scripts/does-not-exist-"]
    path.write_text(json.dumps(doc), encoding="utf-8")
    _git(repo, "add", "--", "config/core-boundaries.json")
    _git(repo, "commit", "-m", "unknown boundary")

    with pytest.raises(ValueError, match="matches no tracked content"):
        build_baseline(repo, _git(repo, "rev-parse", "HEAD"), baseline_version="V1")
