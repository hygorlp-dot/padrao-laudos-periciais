import json
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
