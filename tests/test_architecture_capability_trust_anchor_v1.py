"""Architecture-custody tests for the inert capability trust anchor."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.quality.capability_trust_anchor import (
    _ancestry_error,
    _identity_changes,
    _transition_document_valid,
    validate_inert_trust_anchor,
)


PROTECTED_PATHS = (
    "scripts/quality/capability_analyzer.py",
    "config/capability-policy-v1.json",
)
ROOT = Path(__file__).parents[1]


def _git(root: Path, *args: str, input_text: str | None = None) -> str:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    })
    return subprocess.check_output(
        ["git", *args], cwd=root, env=env, input=input_text, text=True,
    ).strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _identity(root: Path, commit: str, path: str) -> dict:
    line = _git(root, "ls-tree", commit, "--", path)
    mode, object_type, blob_sha = line.split("\t", 1)[0].split()
    return {
        "path": path,
        "state": "PRESENT",
        "mode": mode,
        "objectType": object_type,
        "blobSha": blob_sha,
    }


@pytest.fixture(scope="module")
def _shared_inert_repo(tmp_path_factory) -> tuple[Path, str]:
    root = tmp_path_factory.mktemp("capability-anchor") / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    for path in PROTECTED_PATHS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"base:{path}\n", encoding="utf-8")
    base_without_registry = _commit(root, "base artifacts")
    registry = {
        "schemaVersion": "1.0.0",
        "registryId": "CAPABILITY_PROTECTED_ARTIFACTS_V1",
        "artifacts": [_identity(root, base_without_registry, path) for path in sorted(PROTECTED_PATHS)],
    }
    registry_path = root / "config/capability-protected-artifacts-v1.json"
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    base = _commit(root, "install inert registry")
    return root, base


@pytest.fixture
def inert_repo(_shared_inert_repo) -> tuple[Path, str]:
    root, base = _shared_inert_repo
    top_level = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if top_level != root.resolve():
        raise RuntimeError("shared capability fixture root mismatch")
    _git(root, "reset", "--hard", "-q", base)
    _git(root, "clean", "-fdx", "-q")
    yield root, base
    _git(root, "reset", "--hard", "-q", base)
    _git(root, "clean", "-fdx", "-q")


def test_unchanged_protected_artifacts_pass_inertly():
    identity = {"path": PROTECTED_PATHS[0], "state": "PRESENT", "mode": "100644", "objectType": "blob", "blobSha": "b" * 40}
    error, changed = _identity_changes([identity], {identity["path"]: identity}, {identity["path"]: identity})
    assert error is None
    assert changed == {}


def test_unmanifested_protected_mutation_blocks():
    path = PROTECTED_PATHS[0]
    base_identity = {"path": path, "state": "PRESENT", "mode": "100644", "objectType": "blob", "blobSha": "b" * 40}
    candidate_identity = {**base_identity, "blobSha": "c" * 40}
    assert not _transition_document_valid(None, "a" * 40, {path: (base_identity, candidate_identity)}, {path})


def test_exact_manifested_transition_passes(inert_repo):
    root, base = inert_repo
    path = PROTECTED_PATHS[0]
    base_identity = _identity(root, base, path)
    (root / path).write_text("candidate\n", encoding="utf-8")
    staged = _commit(root, "stage candidate bytes")
    candidate_identity = _identity(root, staged, path)
    transition = {
        "schemaVersion": "1.0.0",
        "transitionId": "CAPABILITY_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": base,
        "artifacts": [{"path": path, "base": base_identity, "candidate": candidate_identity}],
    }
    transition_path = root / "config/capability-protected-transition-v1.json"
    transition_path.write_text(json.dumps(transition, indent=2) + "\n", encoding="utf-8")
    candidate = _commit(root, "authorize exact transition")
    assert validate_inert_trust_anchor(root, base, candidate) == []


def test_present_to_absent_transition_remains_blocked():
    base = "a" * 40
    path = PROTECTED_PATHS[0]
    base_identity = {"path": path, "state": "PRESENT", "mode": "100644", "objectType": "blob", "blobSha": "b" * 40}
    candidate_identity = {"path": path, "state": "ABSENT"}
    transition = {
        "schemaVersion": "1.0.0",
        "transitionId": "CAPABILITY_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": base,
        "artifacts": [{
            "path": path,
            "base": base_identity,
            "candidate": candidate_identity,
        }],
    }
    changed = {path: (base_identity, candidate_identity)}
    assert not _transition_document_valid(transition, base, changed, {path, "config/capability-protected-transition-v1.json"})


def test_mixed_unprotected_production_change_blocks_exact_transition():
    base = "a" * 40
    path = PROTECTED_PATHS[0]
    base_identity = {"path": path, "state": "PRESENT", "mode": "100644", "objectType": "blob", "blobSha": "b" * 40}
    candidate_identity = {**base_identity, "blobSha": "c" * 40}
    transition = {
        "schemaVersion": "1.0.0",
        "transitionId": "CAPABILITY_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": base,
        "artifacts": [{"path": path, "base": base_identity, "candidate": candidate_identity}],
    }
    changed = {path: (base_identity, candidate_identity)}
    changed_paths = {path, "config/capability-protected-transition-v1.json", "scripts/product.py"}
    assert not _transition_document_valid(transition, base, changed, changed_paths)


@pytest.mark.parametrize("mutation", ["duplicate", "omitted", "unknown-key", "wrong-base"])
def test_malformed_or_inexact_manifest_blocks(mutation):
    base = "a" * 40
    path = PROTECTED_PATHS[0]
    base_identity = {"path": path, "state": "PRESENT", "mode": "100644", "objectType": "blob", "blobSha": "b" * 40}
    candidate_identity = {**base_identity, "blobSha": "c" * 40}
    row = {"path": path, "base": base_identity, "candidate": candidate_identity}
    transition = {
        "schemaVersion": "1.0.0",
        "transitionId": "CAPABILITY_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": base,
        "artifacts": [row],
    }
    if mutation == "duplicate":
        transition["artifacts"].append(row)
    elif mutation == "omitted":
        transition["artifacts"] = []
    elif mutation == "unknown-key":
        transition["candidateMayAuthorize"] = True
    else:
        transition["protectedBaseSha"] = "0" * 40
    changed = {path: (base_identity, candidate_identity)}
    assert not _transition_document_valid(
        transition, base, changed, {path, "config/capability-protected-transition-v1.json"},
    )


def test_non_ancestor_and_git_read_failure_block():
    assert _ancestry_error(1) == "CAPABILITY_PROTECTED_BASE_INVALID"
    assert _ancestry_error(128) == "CAPABILITY_TRUST_ANCHOR_FAILURE"


def test_protected_workflow_runs_only_inert_base_owned_verifier():
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(encoding="utf-8")
    assert "pull_request_target" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "persist-credentials: false" in workflow
    assert "validate_inert_trust_anchor" in workflow
    assert "capability_analyzer" not in workflow
    assert "secrets." not in workflow


def test_dynamic_capability_transfers_remain_open_and_denied_by_default():
    ledger = json.loads((ROOT / "config/architecture-capability-transfers-v2.json").read_text(encoding="utf-8"))
    assert ledger["defaultPolicy"] == "DENY"
    assert ledger["wildcardExceptionsAllowed"] is False
    assert len(ledger["findings"]) == 4
    assert {item["severity"] for item in ledger["findings"]} == {"P1"}
