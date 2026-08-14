"""Policy-free deterministic inventory and blob reads from one exact Git tree."""
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


def _git(root, *args: str, text: bool = True):
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=text)
    if completed.returncode:
        raise RuntimeError((completed.stderr if text else completed.stderr.decode(errors="replace")) or "Git object unavailable")
    return completed.stdout


def candidate_tree(root, commitish: str, *, expected_tree: str | None = None) -> tuple[str, str]:
    commit = _git(root, "rev-parse", f"{commitish}^{{commit}}").strip()
    tree = _git(root, "rev-parse", f"{commit}^{{tree}}").strip()
    if expected_tree is not None and tree != expected_tree:
        raise ValueError("candidate commit/tree mismatch")
    if len(commit) != 40 or len(tree) != 40:
        raise ValueError("candidate identity is not SHA-1 object identity")
    return commit, tree


def tree_python_sources(root, tree: str, roots: tuple[str, ...] = ("scripts/",)) -> dict[str, str]:
    raw = _git(root, "ls-tree", "-r", "-z", tree, "--", *roots, text=False)
    entries: list[tuple[str, bytes]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, blob = metadata.split(b" ", 2)
        path = raw_path.decode("utf-8", errors="strict")
        if not path.endswith(".py"):
            continue
        if mode not in {b"100644", b"100755"} or kind != b"blob":
            raise ValueError(f"non-regular architecture source: {path}")
        path = canonical_python_path(path, roots)
        entries.append((path, blob))
    completed = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=b"".join(blob + b"\n" for _, blob in entries),
        capture_output=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode(errors="replace") or "Git objects unavailable")
    output = memoryview(completed.stdout)
    offset = 0
    sources: dict[str, str] = {}
    for path, expected_blob in entries:
        newline = completed.stdout.find(b"\n", offset)
        if newline < 0:
            raise RuntimeError("truncated Git batch header")
        header = bytes(output[offset:newline]).split()
        if len(header) != 3 or header[0] != expected_blob or header[1] != b"blob":
            raise RuntimeError("unexpected Git batch object")
        size = int(header[2])
        start = newline + 1
        end = start + size
        if end >= len(output) or output[end] != 10:
            raise RuntimeError("truncated Git batch object")
        sources[path] = bytes(output[start:end]).decode("utf-8", errors="strict")
        offset = end + 1
    if offset != len(output):
        raise RuntimeError("unexpected trailing Git batch output")
    return dict(sorted(sources.items()))
