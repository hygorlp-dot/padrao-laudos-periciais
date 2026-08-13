"""Policy-free deterministic inventory of candidate Git-tree Python sources."""
from __future__ import annotations

import subprocess
from pathlib import PurePosixPath, PureWindowsPath


def canonical_python_path(path: str, roots: tuple[str, ...]) -> str:
    if not isinstance(path, str) or not path or "\\" in path or PureWindowsPath(path).drive:
        raise ValueError(f"noncanonical Python path: {path!r}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or candidate.as_posix() != path or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError(f"noncanonical Python path: {path!r}")
    if not path.endswith(".py") or not any(path.startswith(root) for root in roots):
        raise ValueError(f"Python path outside production roots: {path!r}")
    return path


def tracked_python_inventory(root, roots: tuple[str, ...] = ("scripts/",)) -> tuple[str, ...]:
    completed = subprocess.run(["git", "ls-files", "-s", "-z", "--", *roots], cwd=root, capture_output=True)
    if completed.returncode:
        raise RuntimeError("tracked Python inventory unavailable")
    paths: list[str] = []
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        if metadata.split(b" ", 1)[0] not in {b"100644", b"100755"}:
            raise ValueError(f"non-regular architecture source: {raw_path!r}")
        path = raw_path.decode("utf-8", errors="strict")
        if path.endswith(".py"):
            paths.append(canonical_python_path(path, roots))
    return tuple(sorted(paths))
