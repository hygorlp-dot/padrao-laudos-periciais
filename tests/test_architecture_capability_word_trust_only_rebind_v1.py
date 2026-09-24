"""Exact contracts for the trust-only Word hash rebind judge (MODE A) and the
exact 13-path product transition (MODE B) in capability-protected.yml.

The MODE A validator is executed exactly as the workflow embeds it, against
synthetic commits built on top of the real HEAD, so these tests exercise the
judge's own text rather than a copy of it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.quality import capability_trust_anchor as trust_anchor


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/capability-protected.yml"
ADAPTER = "scripts/quality/capability_gate_adapter.py"
EXCEPTIONS = "config/capability-exceptions-v1.json"
REGISTRY = "config/capability-protected-artifacts-v1.json"
TRANSITION = "config/capability-protected-transition-v1.json"
ARCHITECTURE_TRANSITION = "config/architecture-protected-transition-v1.json"
SUPPORT_TEST = "tests/test_architecture_capability_exception_rebind_v1.py"
WORD_PARENT = "scripts/backend_contract/infrastructure/office_pdf.py"
BASE_ADAPTER_BLOB = "14421881173fb35aab368229afc81e0c00b1c163"
SUPERSEDED = (
    "e1ebb30e5d5b1e49d747d486c8c53d9c0bb91b1d1cfff947298acfe2623245c9",
    "753828e9d112a220c231a9d47f1663e7289e3b01d2d55ca65fcb09170ee6fa1b",
)
FINAL = (
    "b7394dc88f96e9c6e815d12345cd232b0fa6172471f3699db1127b7366883080",
    "a453ca2d4a8a8b2aefb2ee786911d1b1314fea7d31f30884845e439041bbf87e",
)
REVIEW_EVIDENCE = "LOCAL_WORD_COM_CONTAINMENT_FINAL_HASH_REBIND_V2"
EXACT_PRODUCT_TRANSITION = {
    "scripts/backend_contract/infrastructure/office_pdf.py",
    "scripts/backend_contract/infrastructure/office_word_worker.py",
    "tests/test_delivery_foundation_v1.py",
    "tests/test_office_pdf_renderer_v1.py",
    "tests/test_office_word_containment_v1.py",
    "scripts/backend_contract/delivery_renderer.py",
    "scripts/backend_contract/report_template.py",
    "scripts/backend_contract/application/delivery_foundation.py",
    "artifacts/native-word-matrix-v1.json",
    "tests/opc_word_fixtures.py",
    "tests/test_office_word_authority_v1.py",
    "tests/test_office_word_native_matrix_v1.py",
    "tests/test_product_integration_oracle_v1.py",
}
_GIT_IDENTITY = ("-c", "user.name=Trust Fixture", "-c", "user.email=fixture@example.invalid")


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _mode_a_source() -> str:
    lines = _workflow().splitlines()
    begin = next(i for i, line in enumerate(lines) if line.strip() == "# WORD_TRUST_ONLY_REBIND_V2_BEGIN")
    end = next(i for i, line in enumerate(lines) if line.strip() == "# WORD_TRUST_ONLY_REBIND_V2_END")
    block = lines[begin : end + 1]
    indent = len(block[0]) - len(block[0].lstrip())
    assert all(not line.strip() or line[:indent].isspace() for line in block)
    return "\n".join(line[indent:] for line in block) + "\n"


def _git(repo: Path, *args: str, text: bool = True):
    return subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=repo, check=True, capture_output=True, text=text
    ).stdout


def _blob(repo: Path, path: str) -> str:
    return _git(repo, "hash-object", "-w", "--", path).strip()


def _identity(repo: Path, path: str) -> dict:
    if not (repo / path).exists():
        return {"path": path, "state": "ABSENT"}
    return {"path": path, "state": "PRESENT", "mode": "100644", "objectType": "blob", "blobSha": _blob(repo, path)}


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    """A throwaway clone of HEAD plus a trusted-side layout for the judge."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    base_dir = tmp_path_factory.mktemp("word-rebind")
    repo = base_dir / "candidate"
    subprocess.run(
        ["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(repo)],
        check=True, capture_output=True,
    )
    _git(repo, "checkout", "-q", "--detach", head)
    trusted = base_dir / "ws" / "trusted"
    for path in ("config/capability-policy-v1.json", "schemas/capability-exception-v1.schema.json"):
        (trusted / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, trusted / path)
    return {"repo": repo, "base": head, "workspace": base_dir / "ws"}


def _build_rebind(
    repo: Path,
    base: str,
    *,
    digests: tuple[str, str] = FINAL,
    adapter_suffix: str = "",
    extra_files: dict[str, str] | None = None,
    transition_id: str = trust_anchor.WORD_TRANSITION_ID,
    protected_base: str | None = None,
    baseline_commit: str | None = None,
    exception_drift: bool = False,
    advance_registry: bool = True,
    wildcard_row: bool = False,
) -> str:
    """Build the exact trust-only rebind shape on `base`, optionally perturbed."""
    _git(repo, "checkout", "-q", "--detach", base)
    adapter = (repo / ADAPTER).read_bytes()
    for old, new in zip(SUPERSEDED, digests):
        adapter = adapter.replace(old.encode(), new.encode())
    (repo / ADAPTER).write_bytes(adapter + adapter_suffix.encode())
    for path, content in (extra_files or {}).items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(content, encoding="utf-8", newline="\n")
    adapter_commit = _commit(repo, "rebind adapter")
    candidate_adapter = (repo / ADAPTER).read_bytes()

    exceptions = json.loads((repo / EXCEPTIONS).read_text(encoding="utf-8"))
    for row in exceptions["exceptions"]:
        if row["canonicalPath"] == ADAPTER:
            row["wholeFileSha256"] = hashlib.sha256(candidate_adapter).hexdigest()
            row["baselineCommit"] = baseline_commit or adapter_commit
            row["reviewEvidence"] = REVIEW_EVIDENCE
        elif exception_drift:
            row["reviewBy"] = "2099-01-01"
            exception_drift = False
    (repo / EXCEPTIONS).write_text(json.dumps(exceptions, indent=2) + "\n", encoding="utf-8", newline="\n")
    (repo / SUPPORT_TEST).write_text(
        (repo / SUPPORT_TEST).read_text(encoding="utf-8") + "\n", encoding="utf-8", newline="\n"
    )

    if advance_registry:
        registry = json.loads((repo / REGISTRY).read_text(encoding="utf-8"))
        registry["artifacts"] = [_identity(repo, row["path"]) for row in registry["artifacts"]]
        (repo / REGISTRY).write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8", newline="\n")
    (repo / ARCHITECTURE_TRANSITION).write_text(
        json.dumps({"schemaVersion": "2.0.0", "note": "architecture-protected owns this content"}) + "\n",
        encoding="utf-8", newline="\n",
    )

    changed = {
        item for item in _git(repo, "diff", "--name-only", "-z", base).split("\0") if item
    } | {TRANSITION}
    protected = {ADAPTER, EXCEPTIONS, REGISTRY}
    def row(path: str) -> dict:
        listed = _git(repo, "ls-tree", base, "--", path).strip()
        base_identity = (
            dict(zip(("path", "state", "mode", "objectType", "blobSha"), (
                path, "PRESENT", *listed.split("\t")[0].split()
            )))
            if listed
            else {"path": path, "state": "ABSENT"}
        )
        return {"path": path, "base": base_identity, "candidate": _identity(repo, path)}

    support = sorted(changed - protected - {TRANSITION, ARCHITECTURE_TRANSITION})
    transition = {
        "schemaVersion": "3.0.0",
        "transitionId": transition_id,
        "purpose": trust_anchor.WORD_TRANSITION_PURPOSE,
        "scope": trust_anchor.WORD_TRANSITION_SCOPE,
        "protectedBaseSha": protected_base or base,
        "protectedArtifacts": [row(path) for path in sorted(changed & protected)],
        "supportArtifacts": [row(path) for path in support],
    }
    if wildcard_row:
        transition["supportArtifacts"].append({
            "path": "scripts/backend_contract/*",
            "base": {"path": "scripts/backend_contract/*", "state": "ABSENT"},
            "candidate": {"path": "scripts/backend_contract/*", "state": "ABSENT"},
        })
    (repo / TRANSITION).write_text(json.dumps(transition, indent=2) + "\n", encoding="utf-8", newline="\n")
    return _commit(repo, "rebind manifests")


def _judge(workspace: dict, base: str, candidate: str) -> tuple[int, dict]:
    env = {
        **os.environ,
        "CAPABILITY_CANDIDATE_ROOT": str(workspace["repo"]),
        "CAPABILITY_PROTECTED_BASE_SHA": base,
        "CAPABILITY_EXPECTED_HEAD_SHA": candidate,
        "GITHUB_WORKSPACE": str(workspace["workspace"]),
    }
    completed = subprocess.run(
        [sys.executable, "-"], input=_mode_a_source(), cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=600,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    return completed.returncode, json.loads(lines[-1]) if lines else {}


def test_the_base_is_the_exact_pre_rebind_adapter(workspace):
    blob = _git(workspace["repo"], "rev-parse", f"{workspace['base']}:{ADAPTER}").strip()
    assert blob == BASE_ADAPTER_BLOB
    source = _git(workspace["repo"], "show", f"{workspace['base']}:{ADAPTER}")
    assert all(source.count(value) == 1 for value in SUPERSEDED)


def test_exact_authorized_trust_only_rebind_shape_is_accepted(workspace):
    candidate = _build_rebind(workspace["repo"], workspace["base"])
    code, result = _judge(workspace, workspace["base"], candidate)
    assert code == 0, result
    assert len(result) == 10 and all(result.values())


@pytest.mark.parametrize(
    ("case", "kwargs", "failing"),
    [
        ("trust-only PR modifying product file", {"extra_files": {WORD_PARENT: "RENDER = 1\n"}}, "paths"),
        ("unknown product path", {"extra_files": {"scripts/backend_contract/sixth_module.py": "X = 1\n"}}, "paths"),
        ("unexpected trust file", {"extra_files": {"scripts/quality/capability_trust_anchor.py": "# widened\n"}}, "paths"),
        ("unexpected workflow change", {"extra_files": {".github/workflows/capability-protected.yml": "name: x\n"}}, "paths"),
        ("wildcard product scope", {"wildcard_row": True}, "rows"),
        ("unknown transition ID", {"transition_id": "LOCAL_WORD_COM_CONTAINMENT_TRUST_TRANSITION_V9"}, "transition"),
        ("wrong protected base", {"protected_base": "0" * 40}, "transition"),
        ("superseded hashes retained", {"digests": SUPERSEDED}, "adapter"),
        ("unknown hash", {"digests": ("f" * 64, FINAL[1])}, "adapter"),
        ("generic subprocess", {"adapter_suffix": "\nimport subprocess as _process\n"}, "adapter"),
        ("generic execution", {"adapter_suffix": "\n_run = exec\n"}, "adapter"),
        ("shell authority", {"adapter_suffix": "\nimport os\n_shell = os.system\n"}, "adapter"),
        ("arbitrary COM/ProgID", {"adapter_suffix": "\nimport win32com.client\n"}, "adapter"),
        ("private egress", {"adapter_suffix": "\nimport urllib.request\n"}, "adapter"),
        ("exception registry drift", {"exception_drift": True}, "exceptions"),
        ("exception baseline outside the rebind", {"baseline_commit": "BASE"}, "exceptions"),
        ("registry not advanced", {"advance_registry": False}, "registry"),
    ],
)
def test_every_other_trust_only_shape_is_denied(workspace, case, kwargs, failing):
    if kwargs.get("baseline_commit") == "BASE":
        kwargs = {**kwargs, "baseline_commit": workspace["base"]}
    candidate = _build_rebind(workspace["repo"], workspace["base"], **kwargs)
    code, result = _judge(workspace, workspace["base"], candidate)
    assert code != 0, case
    assert "error" not in result and result.get(failing) is False, (case, result)


def test_the_rebind_is_finite_and_cannot_be_replayed_after_it_lands(workspace):
    landed = _build_rebind(workspace["repo"], workspace["base"])
    replay = _build_rebind(workspace["repo"], landed)
    code, result = _judge(workspace, landed, replay)
    assert code != 0
    assert "error" not in result and result.get("base") is False, result


def test_ordinary_product_pr_without_exact_hashes_is_denied(workspace):
    repo = workspace["repo"]
    _git(repo, "checkout", "-q", "--detach", workspace["base"])
    for path in trust_anchor._WORD_PRODUCT_PATHS:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text("RENDER = 'unreviewed'\n", encoding="utf-8", newline="\n")
    candidate = _commit(repo, "unreviewed product")
    assert trust_anchor._word_render_contract_is_closed(repo, candidate) is False
    code, _result = _judge(workspace, workspace["base"], candidate)
    assert code != 0


def _pwsh_array(name: str) -> set[str]:
    match = re.search(rf"\${name} = @\((.*?)\n\s*\)", _workflow(), re.S)
    assert match, name
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_product_transition_allowlists_are_exactly_the_thirteen_authorized_paths():
    workflow = _workflow()
    start = workflow.index("          allowed = required | {", workflow.index("if ($productOnly) {"))
    body = workflow[start : workflow.index("\n          }", start)]
    required = {
        "scripts/backend_contract/infrastructure/office_pdf.py",
        "scripts/backend_contract/infrastructure/office_word_worker.py",
    }
    assert required | set(re.findall(r"'([^']+)'", body)) == EXACT_PRODUCT_TRANSITION
    assert _pwsh_array("productOnlyAllowed") == EXACT_PRODUCT_TRANSITION
    assert _pwsh_array("productOnlyRequired") == required
    assert EXACT_PRODUCT_TRANSITION <= _pwsh_array("allowed")
    assert len(EXACT_PRODUCT_TRANSITION) == 13
    every_path = EXACT_PRODUCT_TRANSITION | _pwsh_array("allowed")
    assert not any("*" in path or path.endswith("/") for path in every_path)
    # The contract over exact product bytes is still required in MODE B.
    assert "'contract': _word_render_contract_is_closed(root, candidate) is True" in workflow
    assert "required <= changed <= allowed" in workflow


def test_mode_a_is_wired_only_behind_the_failed_product_contract():
    workflow = _workflow()
    detect = workflow.index("- name: Detect dedicated Word scope changes")
    custody = workflow.index("- name: Validate base-owned capability custody")
    assert detect < workflow.index("# WORD_TRUST_ONLY_REBIND_V2_BEGIN") < custody
    assert "CAPABILITY_WORD_TRUST_ONLY_REBIND=true" in workflow[detect:custody]
    assert (
        "if: env.CAPABILITY_BASE_BOOTSTRAP_PRESENT == 'true' && env.CAPABILITY_WORD_SCOPE_CHANGED == 'true' "
        "&& env.CAPABILITY_WORD_TRUST_ONLY_REBIND != 'true'"
    ) in workflow
    source = _mode_a_source()
    assert "trust/" not in source and "pull_request" not in source
    assert "if 'error' in result or len(result) != 10 or not all(result.values()):" in source
