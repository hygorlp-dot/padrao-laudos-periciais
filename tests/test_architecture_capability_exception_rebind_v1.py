"""Exact contracts for ARCHITECTURE_CAPABILITY_EXCEPTION_REBIND_V1."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.quality.architecture_analyzer import _support_path_in_scope, run_architecture_gate
from scripts.quality.capability_bootstrap import run_protected_capability_gate
from scripts.quality import capability_trust_anchor as trust_anchor


ROOT = Path(__file__).resolve().parents[1]
ANALYZER_PATH = "scripts/quality/architecture_analyzer.py"
EXCEPTIONS_PATH = "config/capability-exceptions-v1.json"
CAPABILITY_REGISTRY_PATH = "config/capability-protected-artifacts-v1.json"
CAPABILITY_TRANSITION_PATH = "config/capability-protected-transition-v1.json"
ARCHITECTURE_TRANSITION_PATH = "config/architecture-protected-transition-v1.json"
PROTECTED_BASE = "0897a03b67114c6995f209233f88c7d39c3c2557"
ARCHITECTURE_PROTECTED_BASE = "0897a03b67114c6995f209233f88c7d39c3c2557"
SOURCE_ANCHORS = {
    "scripts/quality/architecture_analyzer.py": "bd9c1aab2d069c71f7b2a7ceedfa8bc45e5d4ba7",
    "scripts/quality/capability_trust_anchor.py": "bd9c1aab2d069c71f7b2a7ceedfa8bc45e5d4ba7",
}
REVIEW_EVIDENCE = {
    "scripts/quality/architecture_analyzer.py": "PHASE_B_WORD_TRUST_SCOPE_BD9C1AA",
    "scripts/quality/capability_trust_anchor.py": "PHASE_B_WORD_TRUST_SCOPE_BD9C1AA",
}
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
        row["path"] for row in _json(CAPABILITY_TRANSITION_PATH)["protectedArtifacts"]
    }
    architecture_paths = {
        row["path"] for row in _json(ARCHITECTURE_TRANSITION_PATH)["artifacts"]
    }
    support_paths = {
        row["path"] for row in _json(ARCHITECTURE_TRANSITION_PATH)["supportArtifacts"]
    }
    paths = capability_paths | architecture_paths | support_paths

    assert all("*" not in path and not path.endswith("/") for path in paths)
    assert capability_paths == {
        ".github/workflows/capability-protected.yml",
        CAPABILITY_REGISTRY_PATH,
        "scripts/quality/architecture_analyzer.py",
        "scripts/quality/capability_trust_anchor.py",
    }
    assert architecture_paths == capability_paths
    assert support_paths == {EXCEPTIONS_PATH, CAPABILITY_TRANSITION_PATH, "tests/test_repository_safety_gate.py"}


def test_capability_workflow_python_scope_admits_exception_transition_path():
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(
        encoding="utf-8"
    )
    start = workflow.index("allowed_paths = {")
    end = workflow.index("\n          }", start)
    assert EXCEPTIONS_PATH in workflow[start:end]


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
        assert after["baselineCommit"] == SOURCE_ANCHORS[after["canonicalPath"]]
        assert after["reviewEvidence"] == REVIEW_EVIDENCE[after["canonicalPath"]]
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
    assert transition["schemaVersion"] == "3.0.0"
    assert transition["transitionId"] == "LOCAL_WORD_COM_CONTAINMENT_TRUST_TRANSITION_V1"
    assert transition["purpose"] == "BOUND_MICROSOFT_WORD_COM_EXECUTION_FOR_AUTHORITATIVE_WORD_TO_PDF"
    assert transition["scope"] == "LOCAL_WORD_COM_CONTAINMENT_V1"
    assert transition["protectedBaseSha"] == PROTECTED_BASE
    assert {row["path"] for row in transition["protectedArtifacts"]} == {
        ".github/workflows/capability-protected.yml",
        CAPABILITY_REGISTRY_PATH,
        "scripts/quality/architecture_analyzer.py",
        "scripts/quality/capability_trust_anchor.py",
    }
    assert {row["path"] for row in transition["supportArtifacts"]} == {
        EXCEPTIONS_PATH,
        "tests/test_architecture_capability_exception_rebind_v1.py",
        "tests/test_repository_safety_gate.py",
    }


def test_architecture_transition_binds_current_trust_anchor_rotation():
    transition = _json(ARCHITECTURE_TRANSITION_PATH)
    assert transition["schemaVersion"] == "3.0.0"
    assert transition["protectedBaseSha"] == ARCHITECTURE_PROTECTED_BASE

    artifact_rows = {row["path"]: row for row in transition["artifacts"]}
    assert set(artifact_rows) == {
        ".github/workflows/capability-protected.yml",
        CAPABILITY_REGISTRY_PATH,
        "scripts/quality/architecture_analyzer.py",
        "scripts/quality/capability_trust_anchor.py",
    }

    for path, row in artifact_rows.items():
        assert _architecture_transition_identity(row, "base") == _identity_from_commit(
            ARCHITECTURE_PROTECTED_BASE, path
        )
        assert _architecture_transition_identity(row, "candidate") == _identity_from_worktree(path)

    support_rows = {row["path"]: row for row in transition["supportArtifacts"]}
    assert transition["supportScope"] == "CAPABILITY_BOOTSTRAP_V1"
    assert set(support_rows) == {CAPABILITY_TRANSITION_PATH, EXCEPTIONS_PATH, "tests/test_repository_safety_gate.py"}
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


def test_word_com_containment_scope_is_registered_with_exact_paths():
    scope = trust_anchor._SUPPORT_SCOPES["LOCAL_WORD_COM_CONTAINMENT_V1"]
    assert scope == {
        "scripts/backend_contract/infrastructure/office_pdf.py",
        "scripts/backend_contract/infrastructure/office_word_worker.py",
        "tests/test_office_pdf_renderer_v1.py",
        "tests/test_office_word_containment_v1.py",
    }


@pytest.mark.parametrize(
    "path",
    [
        "scripts/backend_contract/infrastructure/office_pdf.py",
        "scripts/backend_contract/infrastructure/office_word_worker.py",
        "tests/test_office_pdf_renderer_v1.py",
        "tests/test_office_word_containment_v1.py",
    ],
)
def test_word_com_containment_scope_accepts_only_registered_paths(path):
    assert _support_path_in_scope("LOCAL_WORD_COM_CONTAINMENT_V1", path)


@pytest.mark.parametrize(
    "path",
    [
        "scripts/backend_contract/infrastructure/office.py",
        "scripts/backend_contract/infrastructure/office_pdf.py/child.py",
        "scripts/backend_contract/infrastructure/subprocess_runner.py",
        "scripts/backend_contract/infrastructure/office_word_worker.py.bak",
        "scripts/backend_contract/infrastructure/*.py",
        "tests/test_office_word_containment_v1.py/extra",
    ],
)
def test_word_com_containment_scope_rejects_siblings_wildcards_and_prefixes(path):
    assert not _support_path_in_scope("LOCAL_WORD_COM_CONTAINMENT_V1", path)


def test_word_com_containment_scope_does_not_authorize_process_or_shell_namespaces():
    scope = trust_anchor._SUPPORT_SCOPES["LOCAL_WORD_COM_CONTAINMENT_V1"]
    assert not any("subprocess" in path or "shell" in path for path in scope)
    assert "scripts/backend_contract/infrastructure/office_pdf.py" in scope
    assert "scripts/backend_contract/infrastructure/office_word_worker.py" in scope
