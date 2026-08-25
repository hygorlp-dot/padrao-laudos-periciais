"""Exact contracts for ARCHITECTURE_CAPABILITY_EXCEPTION_REBIND_V1."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.quality.architecture_analyzer import run_architecture_gate
from scripts.quality.capability_bootstrap import run_protected_capability_gate


ROOT = Path(__file__).resolve().parents[1]
PROTECTED_BASE = "dd2d74cc4a0baec555c47677f1c8fc67ce46ec3b"
COMMIT_A = "f00bb46f60431376f8fe7bc5bba497aaf09670d9"
ANALYZER_PATH = "scripts/quality/architecture_analyzer.py"
EXCEPTIONS_PATH = "config/capability-exceptions-v1.json"
CAPABILITY_REGISTRY_PATH = "config/capability-protected-artifacts-v1.json"
CAPABILITY_TRANSITION_PATH = "config/capability-protected-transition-v1.json"


def _git(*args: str, text: bool = True) -> str | bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=text)


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _commit_json(commit: str, path: str) -> dict:
    return json.loads(_git("show", f"{commit}:{path}"))


def _identity_from_commit(commit: str, path: str) -> tuple[str, str, str]:
    line = _git("ls-tree", commit, "--", path).strip()
    metadata, listed_path = line.split("\t", 1)
    assert listed_path == path
    mode, object_type, oid = metadata.split()
    return mode, object_type, oid


def _identity_from_worktree(path: str) -> tuple[str, str, str]:
    return "100644", "blob", _git("hash-object", path).strip()


def _exception(payload: dict) -> dict:
    matches = [
        row
        for row in payload["exceptions"]
        if row.get("canonicalPath") == ANALYZER_PATH
        and row.get("findingCode") == "PROCESS_NAMESPACE_ACQUISITION"
    ]
    assert len(matches) == 1
    return matches[0]


def test_exception_rebind_changes_only_exact_blob_and_baseline_identity():
    before = _exception(_commit_json(COMMIT_A, EXCEPTIONS_PATH))
    after = _exception(_json(EXCEPTIONS_PATH))
    changed = {key for key in before if before[key] != after[key]}

    assert changed == {"wholeFileSha256", "baselineCommit"}
    analyzer_bytes = _git("show", f"{COMMIT_A}:{ANALYZER_PATH}", text=False)
    assert after["wholeFileSha256"] == hashlib.sha256(analyzer_bytes).hexdigest()
    assert after["baselineCommit"] == COMMIT_A


def test_capability_registry_and_transition_bind_the_exact_exception_blob():
    expected_candidate = _identity_from_worktree(EXCEPTIONS_PATH)
    registry = _json(CAPABILITY_REGISTRY_PATH)
    registry_rows = {row["path"]: row for row in registry["artifacts"]}
    assert registry_rows[EXCEPTIONS_PATH] == {
        "path": EXCEPTIONS_PATH,
        "state": "PRESENT",
        "mode": expected_candidate[0],
        "objectType": expected_candidate[1],
        "blobSha": expected_candidate[2],
    }

    transition = _json(CAPABILITY_TRANSITION_PATH)
    assert transition["protectedBaseSha"] == PROTECTED_BASE
    assert [row["path"] for row in transition["artifacts"]] == [EXCEPTIONS_PATH]
    row = transition["artifacts"][0]
    expected_base = _identity_from_commit(PROTECTED_BASE, EXCEPTIONS_PATH)
    assert row["base"] == {
        "path": EXCEPTIONS_PATH,
        "state": "PRESENT",
        "mode": expected_base[0],
        "objectType": expected_base[1],
        "blobSha": expected_base[2],
    }
    assert row["candidate"] == registry_rows[EXCEPTIONS_PATH]


def test_architecture_transition_binds_both_protected_rotations_and_companions():
    transition = _json("config/architecture-protected-transition-v1.json")
    assert transition["schemaVersion"] == "3.0.0"
    assert transition["protectedBaseSha"] == PROTECTED_BASE
    assert transition["supportScope"] == "CAPABILITY_BOOTSTRAP_V1"

    artifact_rows = {row["path"]: row for row in transition["artifacts"]}
    assert set(artifact_rows) == {ANALYZER_PATH, CAPABILITY_REGISTRY_PATH}
    support_rows = {row["path"]: row for row in transition["supportArtifacts"]}
    assert set(support_rows) == {EXCEPTIONS_PATH, CAPABILITY_TRANSITION_PATH}

    for path, row in {**artifact_rows, **support_rows}.items():
        base = _identity_from_commit(PROTECTED_BASE, path)
        candidate = _identity_from_worktree(path)
        assert row == {
            "path": path,
            "baseMode": base[0],
            "baseObjectType": base[1],
            "baseBlobSha": base[2],
            "candidateMode": candidate[0],
            "candidateObjectType": candidate[1],
            "candidateBlobSha": candidate[2],
        }


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


def test_future_base_suppresses_unchanged_analyzer_and_accepts_safe_child(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    safe = repo / "scripts/quality/rebind_safe_child.py"
    safe.write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    child = _child_commit(repo, "safe child")

    assert run_protected_capability_gate(repo, base, child) == []


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
