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
    sources: dict[str, str] = {}
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
        content = _git(root, "cat-file", "blob", blob.decode(), text=False)
        sources[path] = content.decode("utf-8", errors="strict")
    return dict(sorted(sources.items()))
