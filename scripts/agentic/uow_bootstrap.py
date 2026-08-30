"""Fail-closed isolated worktree bootstrap and ephemeral UOW manifest."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import stat
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import jsonschema


class BootstrapError(RuntimeError):
    """Raised before unsafe or ambiguous bootstrap state is accepted."""


_REF_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, text=True, capture_output=True
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "git failed"
        raise BootstrapError(detail)
    return result.stdout.strip()


def _validate_name(label: str, value: str) -> None:
    if not _REF_COMPONENT.fullmatch(value) or ".." in value or value.endswith("/"):
        raise BootstrapError(f"invalid {label}: {value!r}")


def _validated_paths(repository: Path, target: Path) -> tuple[Path, Path, Path]:
    root = Path(_git(repository, "rev-parse", "--show-toplevel")).resolve()
    common_raw = Path(_git(root, "rev-parse", "--git-common-dir"))
    common = (root / common_raw).resolve() if not common_raw.is_absolute() else common_raw.resolve()
    destination = target.absolute()
    if destination.exists() or destination.is_symlink():
        raise BootstrapError(f"target already exists: {destination}")
    private = [part.casefold() for part in destination.parts]
    if any(private[index:index + 2] == ["referencias", "privadas"] for index in range(len(private) - 1)):
        raise BootstrapError("private target is prohibited")
    try:
        resolved_parent = destination.parent.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError("target parent must already exist and be resolvable") from exc
    resolved = resolved_parent / destination.name
    if resolved == Path.home().resolve() or resolved == Path(resolved.anchor):
        raise BootstrapError("home or drive-root target is prohibited")
    try:
        resolved.relative_to(root)
    except ValueError:
        pass
    else:
        raise BootstrapError("target must be outside the source worktree")
    for ancestor in [resolved_parent, *resolved_parent.parents]:
        attributes = getattr(ancestor.stat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if ancestor.is_symlink() or attributes & reparse_flag:
            raise BootstrapError("symlinked/reparse target ancestry is prohibited")
    return root, common, resolved


def _reject_tree_filters(root: Path, commit: str) -> None:
    result = subprocess.run(
        ["git", "grep", "-n", "filter=", commit, "--", ".gitattributes", "**/.gitattributes"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        raise BootstrapError("versioned Git filter attributes are prohibited")
    if result.returncode not in {0, 1}:
        raise BootstrapError("unable to inspect Git filter attributes")


@contextmanager
def _exclusive_lock(common: Path):
    state_dir = common / "codex-uow"
    state_dir.mkdir(mode=0o700, exist_ok=True)
    lock = state_dir / "bootstrap.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise BootstrapError("another UOW bootstrap owns the repository lock") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.close(descriptor)
        yield state_dir
    finally:
        lock.unlink(missing_ok=True)


def _canonical_manifest(state_dir: Path, local_branch: str, manifest: dict[str, Any]) -> Path:
    manifests = state_dir / "manifests"
    manifests.mkdir(mode=0o700, exist_ok=True)
    safe_branch = re.sub(r"[^A-Za-z0-9._-]+", "-", local_branch)
    path = manifests / f"issue-{manifest['issue']}-{safe_branch}-{manifest['base_head']}.json"
    encoded = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError as exc:
        raise BootstrapError(f"manifest already exists: {path}") from exc
    return path


def _validate_manifest(manifest: dict[str, Any]) -> None:
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "uow-manifest-v1.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(manifest)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise BootstrapError(f"invalid UOW manifest: {exc}") from exc


def bootstrap_uow(
    *,
    repository: Path,
    remote: str,
    remote_branch: str,
    local_branch: str,
    target: Path,
    issue: int,
    stage: str,
    task: str,
    risk: str,
    lanes: Sequence[str],
    dependencies: Sequence[str],
    mutation_owner: str,
    skills: Sequence[str],
    policies: Sequence[str],
    pull_request: int | None = None,
) -> dict[str, Any]:
    for label, value in (("remote", remote), ("remote branch", remote_branch), ("local branch", local_branch)):
        _validate_name(label, value)
    if issue < 1 or pull_request is not None and pull_request < 1:
        raise BootstrapError("Issue/PR identifiers must be positive")
    if risk not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise BootstrapError("invalid risk")
    if not all((stage, task, mutation_owner, *lanes, *skills, *policies)):
        raise BootstrapError("manifest identity fields must be nonempty")
    root, common, destination = _validated_paths(repository, target)
    for label, value in (("remote branch", remote_branch), ("local branch", local_branch)):
        if subprocess.run(
            ["git", "check-ref-format", "--branch", value], cwd=root, capture_output=True
        ).returncode:
            raise BootstrapError(f"invalid {label}: {value!r}")
    if subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{local_branch}"], cwd=root
    ).returncode == 0:
        raise BootstrapError(f"local branch already exists: {local_branch}")

    with _exclusive_lock(common) as state_dir:
        hooks = state_dir / "empty-hooks"
        hooks.mkdir(mode=0o700, exist_ok=True)
        remote_ref = f"refs/remotes/{remote}/{remote_branch}"
        _git(root, "fetch", "--no-tags", remote, f"refs/heads/{remote_branch}:{remote_ref}")
        base_head = _git(root, "rev-parse", f"{remote_ref}^{{commit}}")
        base_tree = _git(root, "rev-parse", f"{base_head}^{{tree}}")
        if not _SHA.fullmatch(base_head) or not _SHA.fullmatch(base_tree):
            raise BootstrapError("remote did not resolve to exact commit/tree SHAs")
        _reject_tree_filters(root, base_head)
        manifest = {
            "schema_version": "1.0.0",
            "issue": issue,
            "pull_request": pull_request,
            "stage": stage,
            "task": task,
            "risk": risk,
            "base_head": base_head,
            "base_tree": base_tree,
            "current_head": base_head,
            "lanes": list(lanes),
            "dependencies": list(dependencies),
            "mutation_owner": mutation_owner,
            "open_findings": [],
            "terminal_state": "OPEN",
            "skills": list(skills),
            "policies": list(policies),
        }
        _validate_manifest(manifest)
        _git(
            root,
            "-c", f"core.hooksPath={hooks}",
            "worktree", "add", "--no-track", "-b", local_branch,
            str(destination), base_head,
        )
        _git(root, "branch", f"--set-upstream-to={remote}/{remote_branch}", local_branch)
        if _git(destination, "rev-parse", "HEAD") != base_head:
            raise BootstrapError("created worktree HEAD mismatch")
        if _git(destination, "rev-parse", "HEAD^{tree}") != base_tree:
            raise BootstrapError("created worktree tree mismatch")
        if _git(destination, "status", "--porcelain=v1"):
            raise BootstrapError("created worktree is not clean")
        if _git(destination, "rev-parse", "@{upstream}") != base_head:
            raise BootstrapError("created worktree upstream mismatch")

        manifest_path = _canonical_manifest(state_dir, local_branch, manifest)
        return {**manifest, "manifest_path": str(manifest_path)}


def minimal_bootstrap(repository: Path, target: Path, local_branch: str) -> dict[str, Any]:
    return bootstrap_uow(
        repository=repository,
        remote="origin",
        remote_branch="main",
        local_branch=local_branch,
        target=target,
        issue=1,
        stage="TEST",
        task="SAFE_UOW_BOOTSTRAP_V1",
        risk="LOW",
        lanes=["IMPLEMENTER"],
        dependencies=[],
        mutation_owner="IMPLEMENTER",
        skills=["repository-safety-gate"],
        policies=["AGENTS.md"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--remote-branch", required=True)
    parser.add_argument("--local-branch", required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--risk", choices=["LOW", "MEDIUM", "HIGH", "CRITICAL"], required=True)
    parser.add_argument("--lanes", nargs="+", required=True)
    parser.add_argument("--dependency", action="append", default=[])
    parser.add_argument("--mutation-owner", required=True)
    parser.add_argument("--skill", action="append", required=True)
    parser.add_argument("--policy", action="append", required=True)
    args = parser.parse_args()
    result = bootstrap_uow(
        repository=args.repository, remote=args.remote, remote_branch=args.remote_branch,
        local_branch=args.local_branch, target=args.target, issue=args.issue,
        stage=args.stage, task=args.task, risk=args.risk, lanes=args.lanes,
        dependencies=args.dependency, mutation_owner=args.mutation_owner,
        skills=args.skill, policies=args.policy,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
