"""Exact contracts for ARCHITECTURE_CAPABILITY_EXCEPTION_REBIND_V1."""

from __future__ import annotations

import hashlib
import json
import shutil
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
ARCHITECTURE_TRANSITION_PATH = "config/architecture-protected-transition-v1.json"
PROTECTED_BASE = "1f3f5dc479433dde0ce75600c7f16f84816e2637"
SOURCE_ANCHOR = "c2cbb55f1dcb0732ca8b215df28ef6148fc91566"
E1A_PROTECTED_WORKFLOWS = {
    ".github/workflows/architecture-protected.yml",
    ".github/workflows/capability-protected.yml",
}
ROTATED_PROTECTED_ARTIFACTS = {
    "scripts/quality/architecture_analyzer.py",
    "scripts/quality/capability_trust_anchor.py",
    CAPABILITY_REGISTRY_PATH,
}
SUPPORT_ARTIFACTS = {
    EXCEPTIONS_PATH,
    CAPABILITY_TRANSITION_PATH,
    "tests/test_repository_safety_gate.py",
}
ROTATED_EXCEPTION_PATHS = {
    "scripts/quality/architecture_analyzer.py",
    "scripts/quality/capability_trust_anchor.py",
}


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _identity_from_commit(commit: str, path: str) -> tuple[str, str, str]:
    metadata, listed_path = _git("ls-tree", commit, "--", path).split("\t", 1)
    assert listed_path == path
    mode, object_type, blob_sha = metadata.split()
    return mode, object_type, blob_sha


def _identity_from_worktree(path: str) -> tuple[str, str, str]:
    mode, object_type, _ = _identity_from_commit("HEAD", path)
    return mode, object_type, _git("hash-object", path)


def _transition_identity(row: dict, side: str) -> tuple[str, str, str]:
    identity = row[side]
    return identity["mode"], identity["objectType"], identity["blobSha"]


def _architecture_transition_identity(row: dict, side: str) -> tuple[str, str, str]:
    prefix = "base" if side == "base" else "candidate"
    return row[f"{prefix}Mode"], row[f"{prefix}ObjectType"], row[f"{prefix}BlobSha"]


def test_transition_manifests_introduce_no_wildcard_or_package_wide_authority():
    capability_paths = {
        row["path"] for row in _json(CAPABILITY_TRANSITION_PATH)["artifacts"]
    }
    architecture_paths = {
        row["path"] for row in _json(ARCHITECTURE_TRANSITION_PATH)["artifacts"]
    }
    support_paths = {
        row["path"] for row in _json(ARCHITECTURE_TRANSITION_PATH)["supportArtifacts"]
    }
    paths = capability_paths | architecture_paths | support_paths

    assert all("*" not in path and not path.endswith("/") for path in paths)
    assert capability_paths == {EXCEPTIONS_PATH}
    assert architecture_paths == ROTATED_PROTECTED_ARTIFACTS
    assert support_paths == SUPPORT_ARTIFACTS


def test_rebind_rotates_only_exact_judge_exception_identities():
    base_rows = _git("show", f"{PROTECTED_BASE}:{EXCEPTIONS_PATH}")
    base = json.loads(base_rows)
    candidate = _json(EXCEPTIONS_PATH)

    assert len(candidate["exceptions"]) == len(base["exceptions"])
    changed_paths = set()
    for before, after in zip(base["exceptions"], candidate["exceptions"], strict=True):
        changed = {key for key in before if before[key] != after[key]}
        if not changed:
            continue
        changed_paths.add(after["canonicalPath"])
        assert changed == {"baselineCommit", "reviewEvidence", "wholeFileSha256"}
        assert after["baselineCommit"] == SOURCE_ANCHOR
        assert after["reviewEvidence"] == "C1B_ONE_TIME_TRUST_BOOTSTRAP_PREDECESSOR_C2CBB55"
        assert after["wholeFileSha256"] == hashlib.sha256(
            (ROOT / after["canonicalPath"]).read_bytes()
        ).hexdigest()
    assert changed_paths == ROTATED_EXCEPTION_PATHS


def test_capability_registry_and_transition_bind_exact_exception_blob():
    registry = _json(CAPABILITY_REGISTRY_PATH)
    protected = next(row for row in registry["artifacts"] if row["path"] == EXCEPTIONS_PATH)
    assert (protected["mode"], protected["objectType"], protected["blobSha"]) == (
        *_identity_from_worktree(EXCEPTIONS_PATH)[:2],
        _identity_from_worktree(EXCEPTIONS_PATH)[2],
    )

    transition = _json(CAPABILITY_TRANSITION_PATH)
    assert transition["protectedBaseSha"] == PROTECTED_BASE
    assert len(transition["artifacts"]) == 1
    row = transition["artifacts"][0]
    assert row["path"] == EXCEPTIONS_PATH
    assert _transition_identity(row, "base") == _identity_from_commit(PROTECTED_BASE, EXCEPTIONS_PATH)
    assert _transition_identity(row, "candidate") == _identity_from_worktree(EXCEPTIONS_PATH)


def test_architecture_transition_binds_current_trust_anchor_rotation():
    transition = _json(ARCHITECTURE_TRANSITION_PATH)
    assert transition["schemaVersion"] == "3.0.0"
    assert transition["protectedBaseSha"] == PROTECTED_BASE

    artifact_rows = {row["path"]: row for row in transition["artifacts"]}
    assert set(artifact_rows) == ROTATED_PROTECTED_ARTIFACTS

    for path, row in artifact_rows.items():
        assert _architecture_transition_identity(row, "base") == _identity_from_commit(
            PROTECTED_BASE, path
        )
        assert _architecture_transition_identity(row, "candidate") == _identity_from_worktree(path)

    support_rows = {row["path"]: row for row in transition["supportArtifacts"]}
    assert transition["supportScope"] == "CAPABILITY_BOOTSTRAP_V1"
    assert set(support_rows) == SUPPORT_ARTIFACTS
    for path, row in support_rows.items():
        assert _architecture_transition_identity(row, "base") == _identity_from_commit(
            PROTECTED_BASE, path
        )
        assert _architecture_transition_identity(row, "candidate") == _identity_from_worktree(path)


def test_protected_workflows_use_trusted_locked_uv_dependencies():
    for path in E1A_PROTECTED_WORKFLOWS:
        workflow = (ROOT / path).read_text(encoding="utf-8")
        assert "uv lock --check" in workflow
        assert '$syncArgs = @("pip", "sync", "--system", "--require-hashes", "requirements-dev.txt")' in workflow
        assert "uv @syncArgs" in workflow
        assert "cache-dependency-glob: trusted/uv.lock" in workflow
        assert "pip install" not in workflow


def _future_base_clone(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "future-base"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(repo)],
        check=True,
    )
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    for path in (
        ARCHITECTURE_TRANSITION_PATH,
        EXCEPTIONS_PATH,
        CAPABILITY_REGISTRY_PATH,
        CAPABILITY_TRANSITION_PATH,
    ):
        shutil.copyfile(ROOT / path, repo / path)
    subprocess.run(["git", "add", "--", *(
        ARCHITECTURE_TRANSITION_PATH,
        EXCEPTIONS_PATH,
        CAPABILITY_REGISTRY_PATH,
        CAPABILITY_TRANSITION_PATH,
    )], cwd=repo, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode:
        subprocess.run(["git", "commit", "-qm", "candidate protected base"], cwd=repo, check=True)
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


def test_future_base_suppresses_unchanged_capabilities_and_accepts_safe_child(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    safe = repo / "scripts/quality/rebind_safe_child.py"
    safe.write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    child = _child_commit(repo, "safe child")

    assert run_protected_capability_gate(repo, base, child) == []


def test_future_base_blocks_new_unauthorized_capability(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    source = repo / "scripts/quality/unauthorized_process.py"
    source.write_text("import subprocess\n", encoding="utf-8")
    child = _child_commit(repo, "unauthorized process acquisition")

    findings = run_protected_capability_gate(repo, base, child)
    assert "PROCESS_NAMESPACE_ACQUISITION" in {row["code"] for row in findings}
