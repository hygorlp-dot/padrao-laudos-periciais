"""Fail-closed isolated worktree bootstrap and ephemeral UOW manifest."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import stat
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import jsonschema


class BootstrapError(RuntimeError):
    """Raised before unsafe or ambiguous bootstrap state is accepted."""


_REF_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _resolve_git_executable() -> str:
    located = shutil.which("git")
    if not located:
        raise RuntimeError("trusted Git executable is unavailable")
    executable = Path(located).resolve(strict=True)
    attributes = getattr(executable.stat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not executable.is_file() or executable.is_symlink() or attributes & reparse_flag:
        raise RuntimeError("trusted Git executable must be a real file")
    return str(executable)


_GIT_EXECUTABLE = _resolve_git_executable()


def _controlled_git_environment() -> dict[str, str]:
    blocked = {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
        "GIT_EXEC_PATH", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_SSH", "GIT_SSH_COMMAND",
    }
    environment = {
        key: value for key, value in os.environ.items()
        if key not in blocked and not key.startswith("GIT_CONFIG_")
    }
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _git_execution_policy(hooks: Path) -> list[str]:
    return [
        "-c", f"core.hooksPath={hooks}",
        "-c", f"core.attributesFile={os.devnull}",
        "-c", "core.fsmonitor=false",
        "-c", "credential.helper=",
        "-c", "core.askPass=",
        "-c", "protocol.allow=never",
        "-c", "protocol.file.allow=always",
        "-c", "protocol.https.allow=always",
    ]


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        [_GIT_EXECUTABLE, *args], cwd=repository, text=True, capture_output=True,
        env=_controlled_git_environment(),
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
    if ".." in destination.parts:
        raise BootstrapError("parent traversal in target is prohibited")
    if any(private[index:index + 2] == ["referencias", "privadas"] for index in range(len(private) - 1)):
        raise BootstrapError("private target is prohibited")
    try:
        resolved_parent = destination.parent.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError("target parent must already exist and be resolvable") from exc
    resolved = resolved_parent / destination.name
    resolved_parts = [part.casefold() for part in resolved.parts]
    if any(
        resolved_parts[index:index + 2] == ["referencias", "privadas"]
        for index in range(len(resolved_parts) - 1)
    ):
        raise BootstrapError("private resolved target is prohibited")
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
        [_GIT_EXECUTABLE, "grep", "-n", "filter=", commit, "--", ".gitattributes", "**/.gitattributes"],
        cwd=root,
        text=True,
        capture_output=True,
        env=_controlled_git_environment(),
    )
    if result.returncode == 0 and result.stdout.strip():
        raise BootstrapError("versioned Git filter attributes are prohibited")
    if result.returncode not in {0, 1}:
        raise BootstrapError("unable to inspect Git filter attributes")


def _reject_external_attributes(root: Path, common: Path) -> None:
    info_attributes = common / "info" / "attributes"
    if info_attributes.exists() and info_attributes.read_text(encoding="utf-8").strip():
        raise BootstrapError("Git info attributes are prohibited")
    configured = subprocess.run(
        [_GIT_EXECUTABLE, "config", "--show-origin", "--get-all", "core.attributesFile"],
        cwd=root, text=True, capture_output=True, env=_controlled_git_environment(),
    )
    if configured.returncode == 0 and configured.stdout.strip():
        raise BootstrapError("global/system Git attributes are prohibited")
    if configured.returncode not in {0, 1}:
        raise BootstrapError("unable to inspect Git attributes configuration")


def _reject_fsmonitor(root: Path) -> None:
    configured = subprocess.run(
        [_GIT_EXECUTABLE, "config", "--show-origin", "--get-all", "core.fsmonitor"],
        cwd=root, text=True, capture_output=True, env=_controlled_git_environment(),
    )
    if configured.returncode == 0 and configured.stdout.strip():
        raise BootstrapError("Git fsmonitor configuration is prohibited")
    if configured.returncode not in {0, 1}:
        raise BootstrapError("unable to inspect Git fsmonitor configuration")


def _reject_special_tree_entries(root: Path, commit: str) -> None:
    result = subprocess.run(
        [_GIT_EXECUTABLE, "ls-tree", "-rz", commit], cwd=root, capture_output=True,
        env=_controlled_git_environment(),
    )
    if result.returncode:
        raise BootstrapError("unable to inspect candidate tree modes")
    for record in (value for value in result.stdout.split(b"\0") if value):
        metadata = record.split(b"\t", 1)[0]
        if metadata.startswith(b"160000 commit "):
            raise BootstrapError("submodule gitlinks are prohibited")
        if metadata.startswith(b"120000 blob "):
            raise BootstrapError("tracked symlinks are prohibited")


def _reject_private_tree(root: Path, commit: str) -> None:
    result = subprocess.run(
        [_GIT_EXECUTABLE, "ls-tree", "-rz", "--name-only", commit], cwd=root, capture_output=True,
        env=_controlled_git_environment(),
    )
    if result.returncode:
        raise BootstrapError("unable to inventory candidate tree paths")
    try:
        paths = [value.decode("utf-8", errors="strict") for value in result.stdout.split(b"\0") if value]
    except UnicodeDecodeError as exc:
        raise BootstrapError("candidate tree contains a non-UTF-8 path") from exc
    for path in paths:
        normalized = path.replace("\\", "/").casefold()
        if normalized == "referencias/privadas" or normalized.startswith("referencias/privadas/"):
            raise BootstrapError("candidate tree contains a private tracked path")


def _validated_fetch_url(root: Path, remote: str) -> str:
    result = subprocess.run(
        [_GIT_EXECUTABLE, "config", "--get-all", f"remote.{remote}.url"],
        cwd=root, text=True, capture_output=True, env=_controlled_git_environment(),
    )
    if result.returncode not in {0, 1}:
        raise BootstrapError("named remote is not configured")
    urls = [value for value in result.stdout.splitlines() if value]
    if not urls:
        raise BootstrapError("named remote is not configured")
    if len(urls) != 1:
        raise BootstrapError("named remote must resolve to exactly one fetch URL")
    url = urls[0]
    standard = url.startswith(("https://", "file://"))
    if not standard and not Path(url).is_absolute():
        raise BootstrapError("remote transport/helper is not approved")
    if "::" in url or any(character in url for character in "\r\n"):
        raise BootstrapError("remote transport/helper is not approved")
    if url.startswith("file://") or Path(url).is_absolute():
        _validate_local_remote(url)
    return url


def _validate_local_remote(url: str) -> None:
    if url.startswith("file://"):
        parsed = urlparse(url)
        if parsed.netloc not in {"", "localhost"} or parsed.query or parsed.fragment or parsed.username:
            raise BootstrapError("non-local file remote is prohibited")
        decoded_path = unquote(parsed.path)
        if decoded_path.replace("\\", "/").startswith("//"):
            raise BootstrapError("UNC/device remote is prohibited")
        raw = Path(url2pathname(decoded_path))
    else:
        raw = Path(url)
    raw_text = str(raw).replace("/", "\\")
    if raw_text.startswith(("\\\\", "\\\\?\\", "\\\\.\\")):
        raise BootstrapError("UNC/device remote is prohibited")
    if os.name == "nt":
        raw = _canonical_windows_local_path(raw)
    try:
        absolute = raw.absolute()
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise BootstrapError("local remote must exist and resolve safely") from exc
    resolved_parts = [part.casefold() for part in resolved.parts]
    if any(
        resolved_parts[index:index + 2] == ["referencias", "privadas"]
        for index in range(len(resolved_parts) - 1)
    ):
        raise BootstrapError("private local remote is prohibited")
    for ancestor in [absolute, *absolute.parents]:
        if not ancestor.exists():
            continue
        attributes = getattr(ancestor.stat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if ancestor.is_symlink() or attributes & reparse_flag:
            raise BootstrapError("symlinked/reparse local remote is prohibited")


def _canonical_windows_local_path(raw: Path) -> Path:
    """Resolve a path through the Win32 volume namespace, rejecting aliases."""
    if not raw.drive or raw.drive.startswith("\\"):
        raise BootstrapError("Windows local remote requires a local drive")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = [ctypes.c_wchar_p]
    get_drive_type.restype = ctypes.c_uint
    drive_root = f"{raw.drive}\\"
    if get_drive_type(drive_root) != 3:  # DRIVE_FIXED
        raise BootstrapError("Windows local remote must use a fixed local drive")

    query_device = kernel32.QueryDosDeviceW
    query_device.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    query_device.restype = ctypes.c_uint
    device_buffer = ctypes.create_unicode_buffer(32768)
    if not query_device(raw.drive, device_buffer, len(device_buffer)):
        raise BootstrapError("Windows drive identity could not be proven")
    if device_buffer.value.casefold().replace("\\", "/").startswith("/??/"):
        raise BootstrapError("Windows DOS/SUBST drive aliases are prohibited")

    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
        ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p,
    ]
    create_file.restype = ctypes.c_void_p
    handle = create_file(
        str(raw.absolute()), 0, 0x7, None, 3, 0x02000000, None
    )  # shared read/write/delete; OPEN_EXISTING; FILE_FLAG_BACKUP_SEMANTICS
    if handle == ctypes.c_void_p(-1).value:
        raise BootstrapError("Windows local remote final path could not be opened")
    try:
        final_path = kernel32.GetFinalPathNameByHandleW
        final_path.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint]
        final_path.restype = ctypes.c_uint
        final_buffer = ctypes.create_unicode_buffer(32768)
        length = final_path(handle, final_buffer, len(final_buffer), 0)
        if not length or length >= len(final_buffer):
            raise BootstrapError("Windows local remote final path could not be proven")
    finally:
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [ctypes.c_void_p]
        close_handle.restype = ctypes.c_int
        close_handle(handle)
    canonical_text = final_buffer.value
    canonical_slashes = canonical_text.casefold().replace("\\", "/")
    if canonical_slashes.startswith("//?/unc/"):
        raise BootstrapError("UNC/device remote is prohibited")
    if canonical_slashes.startswith("//?/"):
        canonical_text = canonical_text[4:]
    canonical = Path(canonical_text)
    if not canonical.drive or get_drive_type(f"{canonical.drive}\\") != 3:
        raise BootstrapError("Windows final remote path is not on a fixed local drive")
    return canonical


def _reject_fetch_execution_config(root: Path, remote: str) -> None:
    result = subprocess.run(
        [_GIT_EXECUTABLE, "config", "--show-origin", "--get-regexp", r"^(url\.|remote\.|credential\.|core\.askpass$)"],
        cwd=root, text=True, capture_output=True, env=_controlled_git_environment(),
    )
    if result.returncode not in {0, 1}:
        raise BootstrapError("unable to inspect fetch execution configuration")
    forbidden_remote = {f"remote.{remote}.uploadpack", f"remote.{remote}.vcs"}
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) < 2:
            raise BootstrapError("ambiguous fetch execution configuration")
        key = fields[1].casefold()
        if key.endswith(".insteadof") or key.endswith(".pushinsteadof") or key in forbidden_remote:
            raise BootstrapError("fetch rewrite/helper configuration is prohibited")
        if key == "core.askpass" or key.startswith("credential.") and key.endswith(".helper"):
            raise BootstrapError("credential/askpass execution configuration is prohibited")


@contextmanager
def _exclusive_lock(common: Path):
    state_dir = common / "codex-uow"
    try:
        state_dir.mkdir(mode=0o700, exist_ok=True)
        attributes = getattr(state_dir.stat(), "st_file_attributes", 0)
    except OSError as exc:
        raise BootstrapError("invalid UOW state directory") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not state_dir.is_dir() or state_dir.is_symlink() or attributes & reparse_flag:
        raise BootstrapError("UOW state directory must be a real directory")
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


def _manifest_directory(state_dir: Path) -> Path:
    manifests = state_dir / "manifests"
    try:
        manifests.mkdir(mode=0o700, exist_ok=True)
        attributes = getattr(manifests.stat(), "st_file_attributes", 0)
    except OSError as exc:
        raise BootstrapError("invalid manifests directory") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if not manifests.is_dir() or manifests.is_symlink() or attributes & reparse_flag:
        raise BootstrapError("manifests directory must be a real non-reparse directory")
    return manifests


def _canonical_manifest(state_dir: Path, local_branch: str, manifest: dict[str, Any]) -> Path:
    manifests = _manifest_directory(state_dir)
    path = _manifest_path(manifests, local_branch, manifest)
    encoded = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        with path.open("xb") as stream:
            stream.write(encoded)
    except FileExistsError as exc:
        raise BootstrapError(f"manifest already exists: {path}") from exc
    return path


def _manifest_path(manifests: Path, local_branch: str, manifest: dict[str, Any]) -> Path:
    branch_id = hashlib.sha256(local_branch.encode("utf-8")).hexdigest()
    return manifests / f"issue-{manifest['issue']}-{branch_id}-{manifest['base_head']}.json"


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
    if mutation_owner not in lanes:
        raise BootstrapError("mutation owner must be one of the declared lanes")
    for label, values in (
        ("lanes", lanes), ("dependencies", dependencies),
        ("skills", skills), ("policies", policies),
    ):
        if len(values) != len(set(values)):
            raise BootstrapError(f"duplicate {label} are prohibited")
    root, common, destination = _validated_paths(repository, target)
    fetch_url = _validated_fetch_url(root, remote)
    _reject_fetch_execution_config(root, remote)
    _reject_external_attributes(root, common)
    _reject_fsmonitor(root)
    for label, value in (("remote branch", remote_branch), ("local branch", local_branch)):
        if subprocess.run(
            [_GIT_EXECUTABLE, "check-ref-format", "--branch", value], cwd=root, capture_output=True,
            env=_controlled_git_environment(),
        ).returncode:
            raise BootstrapError(f"invalid {label}: {value!r}")
    if subprocess.run(
        [_GIT_EXECUTABLE, "show-ref", "--verify", "--quiet", f"refs/heads/{local_branch}"], cwd=root,
        env=_controlled_git_environment(),
    ).returncode == 0:
        raise BootstrapError(f"local branch already exists: {local_branch}")

    with _exclusive_lock(common) as state_dir:
        _manifest_directory(state_dir)
        hooks = Path(tempfile.mkdtemp(prefix="empty-hooks-", dir=state_dir))
        hook_attributes = getattr(hooks.stat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if hooks.is_symlink() or hook_attributes & reparse_flag or any(hooks.iterdir()):
            raise BootstrapError("unable to establish an empty real hooks directory")
        remote_ref = f"refs/remotes/{remote}/{remote_branch}"
        fetch_environment = _controlled_git_environment()
        fetch = subprocess.run(
            [_GIT_EXECUTABLE, *_git_execution_policy(hooks), "fetch", "--no-tags", fetch_url,
             f"refs/heads/{remote_branch}:{remote_ref}"],
            cwd=root, text=True, capture_output=True, env=fetch_environment,
        )
        if fetch.returncode:
            raise BootstrapError(fetch.stderr.strip() or "git fetch failed")
        base_head = _git(root, "rev-parse", f"{remote_ref}^{{commit}}")
        base_tree = _git(root, "rev-parse", f"{base_head}^{{tree}}")
        if not _SHA.fullmatch(base_head) or not _SHA.fullmatch(base_tree):
            raise BootstrapError("remote did not resolve to exact commit/tree SHAs")
        _reject_tree_filters(root, base_head)
        _reject_special_tree_entries(root, base_head)
        _reject_private_tree(root, base_head)
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
            "repository_id_sha256": hashlib.sha256(str(common).casefold().encode("utf-8")).hexdigest(),
            "fetch_url_sha256": hashlib.sha256(fetch_url.encode("utf-8")).hexdigest(),
            "git_common_dir": str(common),
            "worktree_git_dir": "PENDING_POSTCONDITION",
            "target_path": str(destination),
            "remote": remote,
            "remote_branch": remote_branch,
            "local_branch": local_branch,
            "postconditions": {
                "clean": True, "head": base_head, "tree": base_tree,
                "upstream_head": base_head,
            },
            "lanes": list(lanes),
            "dependencies": list(dependencies),
            "declaration_authority": "UNTRUSTED_CALLER_INPUT",
            "mutation_owner": mutation_owner,
            "open_findings": [],
            "terminal_state": "OPEN",
            "skills": list(skills),
            "policies": list(policies),
        }
        _validate_manifest(manifest)
        manifest_destination = _manifest_path(_manifest_directory(state_dir), local_branch, manifest)
        if manifest_destination.exists() or manifest_destination.is_symlink():
            raise BootstrapError(f"manifest already exists: {manifest_destination}")
        environment = _controlled_git_environment()
        environment["GIT_ATTR_NOSYSTEM"] = "1"
        result = subprocess.run(
            [_GIT_EXECUTABLE, *_git_execution_policy(hooks), "worktree", "add", "--no-track",
             "-b", local_branch, str(destination), base_head],
            cwd=root, text=True, capture_output=True, env=environment,
        )
        if result.returncode:
            raise BootstrapError(result.stderr.strip() or "git worktree add failed")
        _git(root, "branch", f"--set-upstream-to={remote}/{remote_branch}", local_branch)
        if _git(destination, "rev-parse", "HEAD") != base_head:
            raise BootstrapError("created worktree HEAD mismatch")
        if _git(destination, "rev-parse", "HEAD^{tree}") != base_tree:
            raise BootstrapError("created worktree tree mismatch")
        if _git(destination, "-c", "core.fsmonitor=false", "status", "--porcelain=v1"):
            raise BootstrapError("created worktree is not clean")
        if _git(destination, "rev-parse", "@{upstream}") != base_head:
            raise BootstrapError("created worktree upstream mismatch")

        git_dir_raw = Path(_git(destination, "rev-parse", "--git-dir"))
        git_dir = (destination / git_dir_raw).resolve() if not git_dir_raw.is_absolute() else git_dir_raw.resolve()
        manifest["worktree_git_dir"] = str(git_dir)
        _validate_manifest(manifest)

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
