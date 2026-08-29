"""Sanitized current-tree and reachable-history publication privacy scans."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Runner(Protocol):
    def __call__(self, command: list[str], **kwargs): ...


_PRIVATE_ROOT = "referencias/privadas/"
_FIXTURE_ROOT = "tests/fixtures/"
_FORBIDDEN_FIXTURE_MARKERS = (
    b"real_case_derived",
    b"caso_real_derivado",
    b'"provenance":"real_case"',
    b'"provenance": "real_case"',
)


def _finding(rule: str, path: str, *, commit: str | None = None) -> dict:
    finding = {
        "invariant": "PII_DENY_BY_DEFAULT",
        "boundary": "REPOSITORY",
        "severidade": "P0",
        "rule": rule,
        "path": path,
        "teste": path,
        "motivo": rule,
    }
    if commit is not None:
        finding["commit"] = commit
    return finding


def _git(root: Path, *args: str, runner: Runner):
    return runner(
        ["git", *args], cwd=root, capture_output=True, check=False, timeout=120
    )


def _normalized(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").casefold()


def _is_private(path: str) -> bool:
    return _normalized(path).startswith(_PRIVATE_ROOT)


def _is_fixture(path: str) -> bool:
    normalized = _normalized(path)
    return normalized.startswith(_FIXTURE_ROOT) and normalized != (
        _FIXTURE_ROOT + "core-fixtures.json"
    )


def _has_forbidden_fixture_marker(blob: bytes) -> bool:
    lowered = blob.lower().replace(b"\r", b"")
    return any(marker in lowered for marker in _FORBIDDEN_FIXTURE_MARKERS)


def _git_failure(command: str) -> list[dict]:
    return [_finding("GIT_SCAN_UNAVAILABLE", command)]


def scan_current_tree(root: Path, *, runner: Runner) -> list[dict]:
    """Scan the exact tracked index without opening private working-tree paths."""
    listed = _git(root, "ls-files", "-z", runner=runner)
    if listed.returncode != 0:
        return _git_failure("git ls-files")
    findings: list[dict] = []
    for raw_path in listed.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if _is_private(path):
            findings.append(_finding("PRIVATE_PATH_TRACKED", path))
            continue
        if not _is_fixture(path):
            continue
        blob = _git(root, "show", f":{path}", runner=runner)
        if blob.returncode != 0:
            findings.extend(_git_failure(f"git show :{path}"))
        elif _has_forbidden_fixture_marker(blob.stdout):
            findings.append(_finding("REAL_CASE_FIXTURE_DERIVATION", path))
    return findings


def scan_reachable_history(root: Path, *, runner: Runner) -> list[dict]:
    """Scan every commit reachable from local refs and return redacted metadata."""
    history = _git(root, "log", "--all", "--diff-filter=AMCR", "--format=%x1e%H", "--name-only", "-z", runner=runner)
    if history.returncode != 0:
        return _git_failure("git log --all")
    findings: list[dict] = []
    commit: str | None = None
    for record in history.stdout.split(b"\0"):
        record = record.lstrip(b"\r\n")
        if not record:
            continue
        if record.startswith(b"\x1e"):
            commit = record[1:].strip().decode("ascii", errors="strict")
            continue
        if commit is None:
            return _git_failure("git log record without commit")
        path = record.decode("utf-8", errors="surrogateescape")
        if _is_private(path):
            findings.append(_finding("PRIVATE_PATH_TRACKED", path, commit=commit))
            continue
        if not _is_fixture(path):
            continue
        blob = _git(root, "show", f"{commit}:{path}", runner=runner)
        if blob.returncode != 0:
            findings.extend(_git_failure(f"git show {commit}:{path}"))
        elif _has_forbidden_fixture_marker(blob.stdout):
            findings.append(_finding("REAL_CASE_FIXTURE_DERIVATION", path, commit=commit))
    return findings
