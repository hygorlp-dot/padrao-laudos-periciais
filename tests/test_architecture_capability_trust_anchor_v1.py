"""Architecture-custody tests for the inert capability trust anchor."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.quality import capability_trust_anchor as trust_anchor
from scripts.quality.capability_trust_anchor import (
    _ancestry_error,
    _candidate_registry_valid,
    _identity_changes,
    _transition_document_valid,
    validate_inert_trust_anchor,
)


PROTECTED_PATHS = (
    "scripts/quality/capability_analyzer.py",
    "config/capability-policy-v1.json",
)
FUTURE_PATH = "scripts/quality/capability_bootstrap.py"
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
    rows = [_identity(root, base_without_registry, path) for path in PROTECTED_PATHS]
    rows.append({"path": FUTURE_PATH, "state": "ABSENT"})
    registry = {
        "schemaVersion": "1.0.0",
        "registryId": "CAPABILITY_PROTECTED_ARTIFACTS_V1",
        "artifacts": sorted(rows, key=lambda item: item["path"]),
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
    registry_path = root / "config/capability-protected-artifacts-v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"] = [
        candidate_identity if row["path"] == path else row
        for row in registry["artifacts"]
    ]
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
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


def test_absent_to_present_requires_mechanically_advanced_candidate_registry(inert_repo):
    root, base = inert_repo
    target = root / FUTURE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("candidate bootstrap bytes\n", encoding="utf-8")
    staged = _commit(root, "stage future protected bytes")
    candidate_identity = _identity(root, staged, FUTURE_PATH)

    registry_path = root / "config/capability-protected-artifacts-v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["artifacts"] = [
        candidate_identity if row["path"] == FUTURE_PATH else row
        for row in registry["artifacts"]
    ]
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    transition = {
        "schemaVersion": "1.0.0",
        "transitionId": "CAPABILITY_TRUST_ANCHOR_ROTATION_V1",
        "protectedBaseSha": base,
        "artifacts": [{
            "path": FUTURE_PATH,
            "base": {"path": FUTURE_PATH, "state": "ABSENT"},
            "candidate": candidate_identity,
        }],
    }
    transition_path = root / "config/capability-protected-transition-v1.json"
    transition_path.write_text(json.dumps(transition, indent=2) + "\n", encoding="utf-8")
    candidate = _commit(root, "advance exact protected registry")

    assert validate_inert_trust_anchor(root, base, candidate) == []
    assert trust_anchor._protected_base_bootstrap_present(root, candidate) is True


@pytest.mark.parametrize("mutation", ["added", "removed", "reordered"])
def test_candidate_registry_cannot_change_base_owned_path_set_or_order(inert_repo, mutation):
    root, base = inert_repo
    registry_path = root / "config/capability-protected-artifacts-v1.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if mutation == "added":
        registry["artifacts"].append({"path": "scripts/quality/candidate_choice.py", "state": "ABSENT"})
    elif mutation == "removed":
        registry["artifacts"].pop()
    else:
        registry["artifacts"].reverse()
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    candidate = _commit(root, f"candidate registry {mutation}")

    findings = validate_inert_trust_anchor(root, base, candidate)
    assert {item["code"] for item in findings} == {"CAPABILITY_PROTECTED_REGISTRY_ADVANCEMENT_INVALID"}


def test_base_state_ignores_windows_casefold_alias_not_present_at_canonical_git_path(inert_repo):
    root, _base = inert_repo
    _git(root, "config", "core.ignorecase", "false")
    blob = _git(root, "hash-object", "-w", "--stdin", input_text="casefold alias\n")
    _git(
        root,
        "update-index",
        "--add",
        "--cacheinfo",
        f"100644,{blob},Scripts/quality/capability_bootstrap.py",
    )
    # Commit the index directly: ``git add -A`` would remove this intentionally
    # index-only alias because no matching worktree file exists.
    _git(root, "commit", "-q", "-m", "record noncanonical casefold alias")
    alias_base = _git(root, "rev-parse", "HEAD")

    assert _git(root, "ls-tree", alias_base, "--", "Scripts/quality/capability_bootstrap.py")
    assert not _git(root, "ls-tree", alias_base, "--", FUTURE_PATH)
    _git(root, "reset", "--hard", "-q", alias_base)
    assert (root / "Scripts/quality/capability_bootstrap.py").is_file()
    if os.name == "nt":
        # The old Test-Path selector saw this case-folded filesystem alias as
        # the canonical protected path even though the exact Git path is absent.
        assert (root / FUTURE_PATH).is_file()

    assert trust_anchor._protected_base_bootstrap_present(root, alias_base) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "100755"),
        ("objectType", "tree"),
        ("blobSha", "0" * 40),
    ],
)
def test_candidate_registry_cannot_invent_identity_dimensions(inert_repo, field, value):
    root, base = inert_repo
    registry_path = root / "config/capability-protected-artifacts-v1.json"
    base_registry = json.loads(registry_path.read_text(encoding="utf-8"))["artifacts"]
    paths = [row["path"] for row in base_registry]
    from scripts.quality.capability_trust_anchor import _tree_identities

    candidate_identities = _tree_identities(root, base, paths)
    assert candidate_identities is not None
    registry = {
        "schemaVersion": "1.0.0",
        "registryId": "CAPABILITY_PROTECTED_ARTIFACTS_V1",
        "artifacts": [dict(candidate_identities[path]) for path in paths],
    }
    row = next(item for item in registry["artifacts"] if item["state"] == "PRESENT")
    row[field] = value
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    candidate = _commit(root, f"invent candidate {field}")

    assert not _candidate_registry_valid(root, candidate, base_registry, candidate_identities)


def test_arbitrary_config_support_path_does_not_accompany_transition():
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
    assert not _transition_document_valid(
        transition,
        base,
        {path: (base_identity, candidate_identity)},
        {path, "config/capability-protected-transition-v1.json", "config/candidate-support.json"},
    )


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
