"""Capability-free custody verifier executed from a protected base commit."""

import json
import subprocess
from pathlib import Path, PurePosixPath


REGISTRY_PATH = "config/capability-protected-artifacts-v1.json"
TRANSITION_PATH = "config/capability-protected-transition-v1.json"
_IDENTITY_KEYS = {"path", "state", "mode", "objectType", "blobSha"}


def _finding(code: str, message: str) -> dict:
    return {
        "analyzer": "CAPABILITY_TRUST_ANCHOR_V1",
        "severity": "P1",
        "code": code,
        "path": TRANSITION_PATH,
        "message": message,
    }


def _canonical_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return value if path.as_posix() == value else None


def _git(root: Path, *args: str, text: bool = True):
    return subprocess.check_output(["git", *args], cwd=root, text=text)


def _tree_identities(root: Path, commit: str, paths: list[str]) -> dict[str, dict] | None:
    output = _git(root, "ls-tree", commit, "--", *paths)
    identities = {path: {"path": path, "state": "ABSENT"} for path in paths}
    try:
        for line in output.splitlines():
            metadata, actual_path = line.split("\t", 1)
            mode, object_type, blob_sha = metadata.split()
            if actual_path not in identities or identities[actual_path]["state"] != "ABSENT" or object_type != "blob":
                return None
            identities[actual_path] = {
                "path": actual_path,
                "state": "PRESENT",
                "mode": mode,
                "objectType": object_type,
                "blobSha": blob_sha,
            }
    except (TypeError, ValueError):
        return None
    return identities


def _valid_identity(value: object, path: str) -> bool:
    if not isinstance(value, dict) or value.get("path") != path:
        return False
    if value.get("state") == "ABSENT":
        return set(value) == {"path", "state"}
    return (
        set(value) == _IDENTITY_KEYS
        and value.get("state") == "PRESENT"
        and value.get("mode") in {"100644", "100755"}
        and value.get("objectType") == "blob"
        and isinstance(value.get("blobSha"), str)
        and len(value["blobSha"]) == 40
    )


def _load_registry(root: Path, protected_base: str) -> list[dict] | None:
    value = json.loads(_git(root, "show", f"{protected_base}:{REGISTRY_PATH}"))
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "registryId", "artifacts"}:
        return None
    if value.get("schemaVersion") != "1.0.0" or value.get("registryId") != "CAPABILITY_PROTECTED_ARTIFACTS_V1":
        return None
    rows = value.get("artifacts")
    if not isinstance(rows, list) or not rows:
        return None
    paths = [row.get("path") for row in rows if isinstance(row, dict)]
    if len(paths) != len(rows) or paths != sorted(paths) or len(set(paths)) != len(paths):
        return None
    if any(_canonical_path(path) is None or not _valid_identity(row, path) for path, row in zip(paths, rows)):
        return None
    return rows


def _ancestry_error(returncode: int) -> str | None:
    if returncode == 0:
        return None
    return "CAPABILITY_PROTECTED_BASE_INVALID" if returncode == 1 else "CAPABILITY_TRUST_ANCHOR_FAILURE"


def _identity_changes(
    registry: list[dict] | None,
    base_identities: dict[str, dict] | None,
    candidate_identities: dict[str, dict] | None,
) -> tuple[str | None, dict[str, tuple[dict, dict]]]:
    if registry is None:
        return "CAPABILITY_PROTECTED_REGISTRY_INVALID", {}
    if base_identities is None or candidate_identities is None:
        return "CAPABILITY_PROTECTED_IDENTITY_INVALID", {}
    changed = {}
    for expected in registry:
        path = expected["path"]
        base_identity = base_identities.get(path)
        candidate_identity = candidate_identities.get(path)
        if base_identity != expected or candidate_identity is None:
            return "CAPABILITY_PROTECTED_IDENTITY_INVALID", {}
        if candidate_identity != base_identity:
            changed[path] = (base_identity, candidate_identity)
    return None, changed


def _transition_document_valid(
    value: object,
    protected_base: str,
    changed: dict[str, tuple[dict, dict]],
    changed_paths: set[str],
) -> bool:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "transitionId", "protectedBaseSha", "artifacts"}:
        return False
    if value.get("schemaVersion") != "1.0.0" or value.get("transitionId") != "CAPABILITY_TRUST_ANCHOR_ROTATION_V1":
        return False
    if value.get("protectedBaseSha") != protected_base:
        return False
    rows = value.get("artifacts")
    if not isinstance(rows, list) or len(rows) != len(changed):
        return False
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "base", "candidate"}:
            return False
        path = row.get("path")
        if path in seen or path not in changed:
            return False
        seen.add(path)
        base_identity, candidate_identity = changed[path]
        if not _valid_identity(row.get("base"), path) or not _valid_identity(row.get("candidate"), path):
            return False
        if base_identity.get("state") == "PRESENT" and candidate_identity.get("state") == "ABSENT":
            return False
        if row.get("base") != base_identity or row.get("candidate") != candidate_identity:
            return False
    allowed = set(changed) | {TRANSITION_PATH}
    return changed_paths <= allowed | {path for path in changed_paths if path.startswith("tests/") or path.startswith("docs/arquitetura/")}


def _transition_valid(
    root: Path,
    protected_base: str,
    candidate: str,
    changed: dict[str, tuple[dict, dict]],
) -> bool:
    try:
        value = json.loads(_git(root, "show", f"{candidate}:{TRANSITION_PATH}"))
        changed_paths = {
            item.decode("utf-8")
            for item in _git(root, "diff", "--name-only", "-z", protected_base, candidate, text=False).split(b"\0")
            if item
        }
    except (UnicodeError, json.JSONDecodeError, subprocess.CalledProcessError):
        return False
    return _transition_document_valid(value, protected_base, changed, changed_paths)


def validate_inert_trust_anchor(root: Path, protected_base: str, candidate: str) -> list[dict]:
    """Validate custody only and return no capability-analysis findings."""
    try:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", protected_base, candidate],
            cwd=root,
            capture_output=True,
        )
        ancestry_error = _ancestry_error(ancestor.returncode)
        if ancestry_error:
            return [_finding(ancestry_error, "protected ancestry could not be established")]
        registry = _load_registry(root, protected_base)
        if registry is None:
            return [_finding("CAPABILITY_PROTECTED_REGISTRY_INVALID", "protected registry is unavailable or invalid")]
        paths = [expected["path"] for expected in registry]
        base_identities = _tree_identities(root, protected_base, paths)
        candidate_identities = _tree_identities(root, candidate, paths)
        identity_error, changed = _identity_changes(registry, base_identities, candidate_identities)
        if identity_error:
            return [_finding(identity_error, "protected identity mismatch")]
        if not changed:
            return []
        if _transition_valid(root, protected_base, candidate, changed):
            return []
        return [_finding("CAPABILITY_PROTECTED_TRANSITION_INVALID", "protected change lacks an exact transition")]
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, subprocess.CalledProcessError):
        return [_finding("CAPABILITY_TRUST_ANCHOR_FAILURE", "Git or protected artifact read failed")]
