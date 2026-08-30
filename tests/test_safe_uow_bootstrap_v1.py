import json
import os
import subprocess
from pathlib import Path

import pytest
import jsonschema

from scripts.agentic.uow_bootstrap import BootstrapError, bootstrap_uow, minimal_bootstrap


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, Path, str]:
    source = tmp_path / "source"
    remote = tmp_path / "remote.git"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Test")
    git(source, "config", "user.email", "test@example.invalid")
    (source / "tracked.txt").write_text("stable\n", encoding="utf-8")
    git(source, "add", "tracked.txt")
    git(source, "commit", "-m", "base")
    git(tmp_path, "init", "--bare", str(remote))
    git(source, "remote", "add", "origin", str(remote))
    git(source, "push", "-u", "origin", "main")
    return source, remote, git(source, "rev-parse", "HEAD")


def test_bootstrap_creates_exact_clean_worktree_and_canonical_manifest(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, expected = repository
    target = tmp_path / "isolated"
    dirty = source / "preexisting-untracked.txt"
    dirty.write_text("preserve\n", encoding="utf-8")

    result = bootstrap_uow(
        repository=source,
        remote="origin",
        remote_branch="main",
        local_branch="chore/42-example",
        target=target,
        issue=42,
        stage="C1",
        task="SAFE_UOW_BOOTSTRAP_V1",
        risk="MEDIUM",
        lanes=["IMPLEMENTER", "PR_REVIEWER"],
        dependencies=["C1A"],
        mutation_owner="IMPLEMENTER",
        skills=["repository-safety-gate"],
        policies=["AGENTS.md"],
    )

    assert result["base_head"] == expected
    assert result["current_head"] == expected
    assert git(target, "status", "--porcelain=v1") == ""
    assert git(target, "rev-parse", "HEAD") == expected
    assert git(target, "rev-parse", "@{upstream}") == expected
    manifest_path = Path(result["manifest_path"])
    assert manifest_path.is_file()
    assert target not in manifest_path.parents
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/uow-manifest-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(payload, schema)
    assert payload["terminal_state"] == "OPEN"
    assert payload["mutation_owner"] == "IMPLEMENTER"
    assert payload["declaration_authority"] == "UNTRUSTED_CALLER_INPUT"
    assert payload["remote"] == "origin"
    assert payload["remote_branch"] == "main"
    assert payload["local_branch"] == "chore/42-example"
    assert payload["target_path"] == str(target)
    assert payload["postconditions"] == {
        "clean": True,
        "head": expected,
        "tree": git(target, "rev-parse", "HEAD^{tree}"),
        "upstream_head": expected,
    }
    assert manifest_path.read_bytes().endswith(b"\n")
    assert dirty.read_text(encoding="utf-8") == "preserve\n"


def test_dirty_existing_worktree_is_preserved_on_target_collision(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    target = tmp_path / "occupied"
    target.mkdir()
    sentinel = target / "do-not-touch.txt"
    sentinel.write_text("dirty\n", encoding="utf-8")

    with pytest.raises(BootstrapError, match="target.*exists"):
        minimal_bootstrap(source, target, "chore/42-collision")

    assert sentinel.read_text(encoding="utf-8") == "dirty\n"


@pytest.mark.parametrize(
    "relative",
    ["referencias/privadas/uow", "nested/referencias/privadas/uow"],
)
def test_private_target_is_rejected_before_fetch(
    repository: tuple[Path, Path, str], tmp_path: Path, relative: str
):
    source, _remote, before = repository
    target = tmp_path / relative
    with pytest.raises(BootstrapError, match="private"):
        minimal_bootstrap(source, target, "chore/42-private")
    assert git(source, "rev-parse", "HEAD") == before
    assert not target.exists()


def test_branch_collision_fails_without_touching_existing_worktree(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    git(source, "branch", "chore/42-existing")
    target = tmp_path / "new-target"
    with pytest.raises(BootstrapError, match="branch.*exists"):
        minimal_bootstrap(source, target, "chore/42-existing")
    assert not target.exists()


def test_external_filter_configuration_fails_closed_before_creation(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    (source / ".gitattributes").write_text("*.txt filter=danger\n", encoding="utf-8")
    git(source, "add", ".gitattributes")
    git(source, "commit", "-m", "add external filter attribute")
    git(source, "push", "origin", "main")
    target = tmp_path / "filtered"
    with pytest.raises(BootstrapError, match="filter"):
        minimal_bootstrap(source, target, "chore/42-filter")
    assert not target.exists()


def test_repository_lock_blocks_competing_owner_before_fetch(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, before = repository
    common = Path(git(source, "rev-parse", "--git-common-dir"))
    state = source / common / "codex-uow"
    state.mkdir()
    lock = state / "bootstrap.lock"
    lock.write_text("owned\n", encoding="utf-8")
    target = tmp_path / "locked"

    with pytest.raises(BootstrapError, match="owns.*lock"):
        minimal_bootstrap(source, target, "chore/42-locked")

    assert lock.read_text(encoding="utf-8") == "owned\n"
    assert git(source, "rev-parse", "HEAD") == before
    assert not target.exists()


def test_submodule_gitlink_fails_closed_before_worktree_creation(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, expected = repository
    git(source, "update-index", "--add", "--cacheinfo", "160000", expected, "nested-module")
    git(source, "commit", "-m", "add synthetic gitlink")
    git(source, "push", "origin", "main")
    target = tmp_path / "submodule-target"

    with pytest.raises(BootstrapError, match="submodule"):
        minimal_bootstrap(source, target, "chore/42-submodule")

    assert not target.exists()


def test_preexisting_hook_directory_cannot_execute_checkout_hook(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    common = source / Path(git(source, "rev-parse", "--git-common-dir"))
    hooks = common / "codex-uow" / "empty-hooks"
    hooks.mkdir(parents=True)
    sentinel = tmp_path / "hook-executed"
    hook = hooks / "post-checkout"
    hook.write_text(f"#!/bin/sh\nprintf unsafe > '{sentinel.as_posix()}'\n", encoding="utf-8")
    hook.chmod(0o755)

    minimal_bootstrap(source, tmp_path / "safe-hooks", "chore/42-safe-hooks")

    assert not sentinel.exists()


def test_info_attributes_cannot_activate_external_filter(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    common = source / Path(git(source, "rev-parse", "--git-common-dir"))
    info = common / "info" / "attributes"
    info.write_text("*.txt filter=danger\n", encoding="utf-8")
    target = tmp_path / "info-attributes"

    with pytest.raises(BootstrapError, match="info attributes"):
        minimal_bootstrap(source, target, "chore/42-info-attributes")

    assert not target.exists()


def test_mutation_owner_must_belong_to_declared_lanes(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    with pytest.raises(BootstrapError, match="owner.*lanes"):
        bootstrap_uow(
            repository=source, remote="origin", remote_branch="main",
            local_branch="chore/42-owner", target=tmp_path / "owner",
            issue=42, stage="C1", task="SAFE_UOW_BOOTSTRAP_V1", risk="MEDIUM",
            lanes=["PR_REVIEWER"], dependencies=[], mutation_owner="IMPLEMENTER",
            skills=["repository-safety-gate"], policies=["AGENTS.md"],
        )


def test_reparse_manifest_directory_cannot_redirect_write(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    common = source / Path(git(source, "rev-parse", "--git-common-dir"))
    state = common / "codex-uow"
    state.mkdir()
    outside = tmp_path / "outside-manifests"
    outside.mkdir()
    link = state / "manifests"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"directory symlink unavailable: {exc}")
        junction = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            text=True, capture_output=True,
        )
        if junction.returncode:
            pytest.skip(f"directory reparse unavailable: {junction.stderr}")

    with pytest.raises(BootstrapError, match="manifests directory"):
        minimal_bootstrap(source, tmp_path / "redirect", "chore/42-redirect")

    assert list(outside.iterdir()) == []


def test_configured_fsmonitor_is_rejected_before_any_worktree_creation(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    sentinel = tmp_path / "fsmonitor-executed"
    monitor = tmp_path / "monitor.sh"
    monitor.write_text(f"#!/bin/sh\nprintf unsafe > '{sentinel.as_posix()}'\n", encoding="utf-8")
    monitor.chmod(0o755)
    git(source, "config", "core.fsmonitor", str(monitor))
    target = tmp_path / "fsmonitor-target"

    with pytest.raises(BootstrapError, match="fsmonitor"):
        minimal_bootstrap(source, target, "chore/42-fsmonitor")

    assert not target.exists()
    assert not sentinel.exists()


def test_parent_traversal_cannot_hide_private_target(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, before = repository
    base = tmp_path / "boundary"
    (base / "referencias" / "x").mkdir(parents=True)
    (base / "referencias" / "privadas").mkdir()
    target = base / "referencias" / "x" / ".." / "privadas" / "uow"

    with pytest.raises(BootstrapError, match="traversal|private"):
        minimal_bootstrap(source, target, "chore/42-private-traversal")

    assert git(source, "rev-parse", "HEAD") == before
    assert not (base / "referencias" / "privadas" / "uow").exists()


@pytest.mark.parametrize(
    "private_path",
    ["referencias/privadas/secret.txt", "Referencias/Privadas/mixed-case.txt"],
)
def test_private_remote_tree_is_rejected_before_checkout(
    repository: tuple[Path, Path, str], tmp_path: Path, private_path: str
):
    source, _remote, _expected = repository
    private = source / private_path
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text("synthetic secret\n", encoding="utf-8")
    git(source, "add", "--", private_path)
    git(source, "commit", "-m", "add prohibited private path")
    git(source, "push", "origin", "main")
    target = tmp_path / "private-tree"

    with pytest.raises(BootstrapError, match="private tracked path"):
        minimal_bootstrap(source, target, "chore/42-private-tree")

    assert not target.exists()


@pytest.mark.skipif(os.name == "nt", reason="Windows filenames cannot contain newline")
def test_private_remote_tree_inventory_is_nul_safe_for_newline_path(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    private = source / "referencias" / "privadas" / "line\nbreak.txt"
    private.parent.mkdir(parents=True)
    private.write_text("synthetic secret\n", encoding="utf-8")
    git(source, "add", "--", str(private.relative_to(source)))
    git(source, "commit", "-m", "add newline private path")
    git(source, "push", "origin", "main")

    with pytest.raises(BootstrapError, match="private tracked path"):
        minimal_bootstrap(source, tmp_path / "newline-tree", "chore/42-newline-tree")


def test_fetch_cannot_execute_repository_reference_transaction_hook(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, remote, _expected = repository
    other = tmp_path / "other"
    git(tmp_path, "clone", str(remote), str(other))
    git(other, "checkout", "-b", "main", "origin/main")
    git(other, "config", "user.name", "Other")
    git(other, "config", "user.email", "other@example.invalid")
    (other / "remote-change.txt").write_text("advance\n", encoding="utf-8")
    git(other, "add", "remote-change.txt")
    git(other, "commit", "-m", "advance remote")
    git(other, "push", "origin", "main")
    sentinel = tmp_path / "fetch-hook-executed"
    hook = source / ".git" / "hooks" / "reference-transaction"
    hook.write_text(f"#!/bin/sh\nprintf unsafe > '{sentinel.as_posix()}'\n", encoding="utf-8")
    hook.chmod(0o755)

    minimal_bootstrap(source, tmp_path / "safe-fetch", "chore/42-safe-fetch")

    assert not sentinel.exists()


def test_remote_helper_transport_is_rejected_before_fetch(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    git(source, "remote", "set-url", "origin", "ext::arbitrary-helper")
    target = tmp_path / "helper"
    with pytest.raises(BootstrapError, match="transport/helper"):
        minimal_bootstrap(source, target, "chore/42-helper")
    assert not target.exists()


def test_url_rewrite_cannot_turn_https_remote_into_external_helper(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    git(source, "remote", "set-url", "origin", "https://approved.example/repository.git")
    git(source, "config", "url.ext::arbitrary-helper.insteadOf", "https://approved.example/")
    target = tmp_path / "rewrite"

    with pytest.raises(BootstrapError, match="rewrite/helper"):
        minimal_bootstrap(source, target, "chore/42-rewrite")

    assert not target.exists()


def test_custom_uploadpack_is_rejected_before_fetch(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    git(source, "config", "remote.origin.uploadpack", "arbitrary-executable")
    target = tmp_path / "uploadpack"

    with pytest.raises(BootstrapError, match="rewrite/helper"):
        minimal_bootstrap(source, target, "chore/42-uploadpack")

    assert not target.exists()


def test_duplicate_manifest_declarations_fail_before_fetch_or_worktree(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, before = repository
    target = tmp_path / "duplicates"

    with pytest.raises(BootstrapError, match="duplicate lanes"):
        bootstrap_uow(
            repository=source, remote="origin", remote_branch="main",
            local_branch="chore/42-duplicates", target=target, issue=42,
            stage="C1", task="SAFE_UOW_BOOTSTRAP_V1", risk="MEDIUM",
            lanes=["IMPLEMENTER", "IMPLEMENTER"], dependencies=[],
            mutation_owner="IMPLEMENTER", skills=["repository-safety-gate"],
            policies=["AGENTS.md"],
        )

    assert git(source, "rev-parse", "HEAD") == before
    assert not target.exists()


def test_manifest_filename_is_collision_resistant_for_similar_branches(
    repository: tuple[Path, Path, str], tmp_path: Path
):
    source, _remote, _expected = repository
    first = minimal_bootstrap(source, tmp_path / "first", "a/b")
    second = minimal_bootstrap(source, tmp_path / "second", "a-b")

    assert first["manifest_path"] != second["manifest_path"]


def test_git_exec_path_cannot_substitute_https_transport_helper(
    repository: tuple[Path, Path, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source, _remote, _expected = repository
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    sentinel = tmp_path / "transport-helper-executed"
    helper = helpers / ("git-remote-https.exe" if os.name == "nt" else "git-remote-https")
    helper.write_text(f"#!/bin/sh\nprintf unsafe > '{sentinel.as_posix()}'\n", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setenv("GIT_EXEC_PATH", str(helpers))
    git(source, "remote", "set-url", "origin", "https://127.0.0.1:9/repository.git")

    with pytest.raises(BootstrapError, match="fetch failed|unable to access|Failed to connect"):
        minimal_bootstrap(source, tmp_path / "exec-path", "chore/42-exec-path")

    assert not sentinel.exists()


@pytest.mark.parametrize("key", ["credential.helper", "core.askPass"])
def test_credential_execution_config_is_rejected_before_fetch(
    repository: tuple[Path, Path, str], tmp_path: Path, key: str
):
    source, _remote, _expected = repository
    git(source, "config", key, "arbitrary-executable")
    target = tmp_path / "credential-helper"

    with pytest.raises(BootstrapError, match="credential/askpass"):
        minimal_bootstrap(source, target, "chore/42-credential-helper")

    assert not target.exists()
