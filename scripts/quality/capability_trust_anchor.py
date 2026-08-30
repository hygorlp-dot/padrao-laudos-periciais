"""Capability-free custody verifier executed from a protected base commit."""

import json
import subprocess
from pathlib import Path, PurePosixPath


REGISTRY_PATH = "config/capability-protected-artifacts-v1.json"
TRANSITION_PATH = "config/capability-protected-transition-v1.json"
BOOTSTRAP_PATH = "scripts/quality/capability_bootstrap.py"
ARCHITECTURE_TRANSITION_PATH = "config/architecture-protected-transition-v1.json"
_IDENTITY_KEYS = {"path", "state", "mode", "objectType", "blobSha"}
_SUPPORT_SCOPES = {
    "C1B_SAFE_UOW_BOOTSTRAP_V1": {
        "docs/padroes/safe-uow-bootstrap-v1.md",
        "schemas/uow-manifest-v1.schema.json",
        "scripts/agentic/uow_bootstrap.py",
    },
}


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


def _load_registry(root: Path, commit: str) -> list[dict] | None:
    value = json.loads(_git(root, "show", f"{commit}:{REGISTRY_PATH}"))
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


def _candidate_registry_valid(
    root: Path,
    candidate: str,
    base_registry: list[dict],
    candidate_identities: dict[str, dict],
) -> bool:
    """Require the candidate registry to be the exact base-owned path set with current identities."""
    candidate_registry = _load_registry(root, candidate)
    if candidate_registry is None:
        return False
    base_paths = [row["path"] for row in base_registry]
    if [row["path"] for row in candidate_registry] != base_paths:
        return False
    expected = [candidate_identities[path] for path in base_paths]
    return candidate_registry == expected


def _protected_base_bootstrap_present(root: Path, protected_base: str) -> bool | None:
    """Select the workflow state from the exact base Git identity, never filesystem lookup."""
    try:
        registry = _load_registry(root, protected_base)
        if registry is None:
            return None
        matches = [row for row in registry if row["path"] == BOOTSTRAP_PATH]
        if len(matches) != 1:
            return None
        identities = _tree_identities(root, protected_base, [BOOTSTRAP_PATH])
        if identities is None or identities.get(BOOTSTRAP_PATH) != matches[0]:
            return None
        return matches[0]["state"] == "PRESENT"
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, subprocess.CalledProcessError):
        return None


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
    if not isinstance(value, dict):
        return False
    schema_version = value.get("schemaVersion")
    expected_keys = (
        {"schemaVersion", "transitionId", "protectedBaseSha", "artifacts", "supportScope", "supportArtifacts"}
        if schema_version == "2.0.0"
        else {"schemaVersion", "transitionId", "protectedBaseSha", "artifacts"}
    )
    if set(value) != expected_keys or schema_version not in {"1.0.0", "2.0.0"}:
        return False
    if value.get("transitionId") != "CAPABILITY_TRUST_ANCHOR_ROTATION_V1":
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
    support_paths: set[str] = set()
    if schema_version == "2.0.0":
        scope_paths = _SUPPORT_SCOPES.get(value.get("supportScope"))
        support_rows = value.get("supportArtifacts")
        if scope_paths is None or not isinstance(support_rows, list):
            return False
        for support_row in support_rows:
            if not isinstance(support_row, dict) or set(support_row) != {"path", "base", "candidate"}:
                return False
            support_path = support_row.get("path")
            base_support = support_row.get("base")
            candidate_support = support_row.get("candidate")
            if (
                support_path in support_paths
                or support_path not in scope_paths
                or not _valid_identity(base_support, support_path)
                or not _valid_identity(candidate_support, support_path)
                or candidate_support.get("state") != "PRESENT"
                or base_support == candidate_support
            ):
                return False
            support_paths.add(support_path)
        if support_paths != changed_paths & scope_paths:
            return False
    allowed = set(changed) | {REGISTRY_PATH, TRANSITION_PATH} | support_paths
    if REGISTRY_PATH in changed_paths:
        # A real capability-registry rotation legitimately requires updating the
        # architecture trust-boundary system's own transition manifest (its
        # protectedBaseSha always tracks the real base at CI time, and
        # config/capability-protected-artifacts-v1.json is itself an
        # architecture-protected artifact). architecture-protected remains the
        # sole semantic authority over that file's content; this only accounts
        # for its presence in the diff, exact path, no prefix, no wildcard.
        allowed = allowed | {ARCHITECTURE_TRANSITION_PATH}
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
    if not _transition_document_valid(value, protected_base, changed, changed_paths):
        return False
    if value.get("schemaVersion") == "2.0.0":
        for row in value["supportArtifacts"]:
            path = row["path"]
            identities = _tree_identities(root, protected_base, [path])
            candidate_identities = _tree_identities(root, candidate, [path])
            if (
                identities is None
                or candidate_identities is None
                or identities[path] != row["base"]
                or candidate_identities[path] != row["candidate"]
            ):
                return False
    return True


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
        if not _candidate_registry_valid(root, candidate, registry, candidate_identities):
            return [_finding(
                "CAPABILITY_PROTECTED_REGISTRY_ADVANCEMENT_INVALID",
                "candidate registry is not the exact base-owned path set with candidate identities",
            )]
        if not changed:
            return []
        if _transition_valid(root, protected_base, candidate, changed):
            return []
        return [_finding("CAPABILITY_PROTECTED_TRANSITION_INVALID", "protected change lacks an exact transition")]
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, subprocess.CalledProcessError):
        return [_finding("CAPABILITY_TRUST_ANCHOR_FAILURE", "Git or protected artifact read failed")]
