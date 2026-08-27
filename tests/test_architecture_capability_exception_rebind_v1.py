"""Exact contracts for ARCHITECTURE_CAPABILITY_EXCEPTION_REBIND_V1."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.quality.architecture_analyzer import run_architecture_gate
from scripts.quality.capability_bootstrap import run_protected_capability_gate


ROOT = Path(__file__).resolve().parents[1]
ANALYZER_PATH = "scripts/quality/architecture_analyzer.py"
EXCEPTIONS_PATH = "config/capability-exceptions-v1.json"
CAPABILITY_REGISTRY_PATH = "config/capability-protected-artifacts-v1.json"
CAPABILITY_TRANSITION_PATH = "config/capability-protected-transition-v1.json"


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_rebind_introduces_no_wildcard_or_package_wide_authority():
    paths = []
    for document in (
        _json(CAPABILITY_TRANSITION_PATH),
        _json("config/architecture-protected-transition-v1.json"),
    ):
        paths.extend(row["path"] for row in document["artifacts"])
        paths.extend(row["path"] for row in document.get("supportArtifacts", []))

    assert all("*" not in path and not path.endswith("/") for path in paths)
    assert set(paths) == {
        ANALYZER_PATH,
        EXCEPTIONS_PATH,
        CAPABILITY_REGISTRY_PATH,
        CAPABILITY_TRANSITION_PATH,
    }


def _future_base_clone(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "future-base"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(repo)],
        check=True,
    )
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return repo, base


def _child_commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def test_future_base_rejects_one_byte_analyzer_drift(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    analyzer = repo / ANALYZER_PATH
    analyzer.write_text(analyzer.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    child = _child_commit(repo, "one-byte-class analyzer drift")

    findings = run_protected_capability_gate(repo, base, child)
    assert "PROCESS_NAMESPACE_ACQUISITION" in {row["code"] for row in findings}


def test_future_base_rejects_analyzer_ast_identity_drift(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    analyzer = repo / ANALYZER_PATH
    source = analyzer.read_text(encoding="utf-8")
    assert "import subprocess\n" in source
    analyzer.write_text(
        source.replace("import subprocess\n", "import subprocess as child_process\n", 1),
        encoding="utf-8",
    )
    child = _child_commit(repo, "analyzer acquisition AST drift")

    findings = run_protected_capability_gate(repo, base, child)
    assert "PROCESS_NAMESPACE_ACQUISITION" in {row["code"] for row in findings}


@pytest.mark.parametrize("drift", ["content", "mode", "type"])
def test_future_base_architecture_blocks_initializer_identity_drift(tmp_path, monkeypatch, drift):
    repo, base = _future_base_clone(tmp_path)
    initializer = repo / "scripts/quality/__init__.py"
    if drift == "content":
        initializer.write_text(initializer.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    elif drift == "mode":
        subprocess.run(
            ["git", "update-index", "--chmod=+x", "scripts/quality/__init__.py"],
            cwd=repo,
            check=True,
        )
    else:
        initializer.unlink()
        initializer.mkdir()
        (initializer / "nested.py").write_text("# tree drift\n", encoding="utf-8")
    child = _child_commit(repo, f"initializer {drift} drift")
    monkeypatch.setenv("ARCHITECTURE_PROTECTED_BASE_SHA", base)
    monkeypatch.setenv("ARCHITECTURE_EXPECTED_HEAD_SHA", child)

    findings = run_architecture_gate(repo, child)
    assert "ARCHITECTURE_PROTECTED_ARTIFACT_MISMATCH" in {
        row["code"] for row in findings
    }


def test_future_base_capability_custody_blocks_exception_registry_drift(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    registry = repo / EXCEPTIONS_PATH
    registry.write_text(registry.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    child = _child_commit(repo, "exception registry drift")

    findings = run_protected_capability_gate(repo, base, child)
    assert findings
    assert {row["code"] for row in findings} <= {
        "CAPABILITY_PROTECTED_REGISTRY_ADVANCEMENT_INVALID",
        "CAPABILITY_PROTECTED_TRANSITION_INVALID",
    }


def test_future_base_blocks_new_unauthorized_capability(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    source = repo / "scripts/quality/unauthorized_process.py"
    source.write_text("import subprocess\n", encoding="utf-8")
    child = _child_commit(repo, "unauthorized process acquisition")

    findings = run_protected_capability_gate(repo, base, child)
    assert "PROCESS_NAMESPACE_ACQUISITION" in {row["code"] for row in findings}
