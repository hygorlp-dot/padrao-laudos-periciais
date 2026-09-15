"""Exact contracts for ARCHITECTURE_CAPABILITY_EXCEPTION_REBIND_V1."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.quality.architecture_analyzer import _support_path_in_scope, run_architecture_gate
from scripts.quality.capability_bootstrap import run_protected_capability_gate
from scripts.quality.capability_gate_adapter import (
    _WORD_PRODUCT_SHA256,
    _word_render_digests_are_closed,
    word_render_sources_are_closed,
)
from scripts.quality import capability_trust_anchor as trust_anchor
from scripts.quality import capability_gate_adapter as gate_adapter


ROOT = Path(__file__).resolve().parents[1]
ANALYZER_PATH = "scripts/quality/architecture_analyzer.py"
EXCEPTIONS_PATH = "config/capability-exceptions-v1.json"
CAPABILITY_REGISTRY_PATH = "config/capability-protected-artifacts-v1.json"
CAPABILITY_TRANSITION_PATH = "config/capability-protected-transition-v1.json"
ARCHITECTURE_TRANSITION_PATH = "config/architecture-protected-transition-v1.json"
CAPABILITY_GATE_ADAPTER_PATH = "scripts/quality/capability_gate_adapter.py"
WORD_PARENT_PATH = "scripts/backend_contract/infrastructure/office_pdf.py"
WORD_WORKER_PATH = "scripts/backend_contract/infrastructure/office_word_worker.py"
PROTECTED_BASE = "382e82d2e380f3ee80e8c97e2cc514f0dd37e315"
ARCHITECTURE_PROTECTED_BASE = "382e82d2e380f3ee80e8c97e2cc514f0dd37e315"
SOURCE_ANCHORS = {
    "scripts/quality/architecture_analyzer.py": "f2f745e8791906ae91049ed0474df710b911613d",
    "scripts/quality/capability_gate_adapter.py": "a14375bb6f6d40593ca06edae67dee2a9d256071",
    "scripts/quality/capability_trust_anchor.py": "f2f745e8791906ae91049ed0474df710b911613d",
}
REVIEW_EVIDENCE = {
    "scripts/quality/architecture_analyzer.py": "ISSUE_224_WORD_CONTRACT_PREDECESSOR_ARCHITECTURE",
    "scripts/quality/capability_gate_adapter.py": "ISSUE_224_EXACT_WORD_CONTRACT_VALIDATOR",
    "scripts/quality/capability_trust_anchor.py": "ISSUE_224_WORD_CONTRACT_PREDECESSOR_CUSTODY",
}
E1A_PROTECTED_WORKFLOWS = {
    ".github/workflows/architecture-protected.yml",
    ".github/workflows/capability-protected.yml",
}
ROTATED_PROTECTED_ARTIFACTS = {
    ".github/workflows/capability-protected.yml",
    "scripts/quality/architecture_analyzer.py",
    "scripts/quality/capability_gate_adapter.py",
    "scripts/quality/capability_trust_anchor.py",
    CAPABILITY_REGISTRY_PATH,
    EXCEPTIONS_PATH,
}
SUPPORT_ARTIFACTS = {
    "tests/test_architecture_capability_exception_rebind_v1.py",
    "tests/test_repository_safety_gate.py",
}
ROTATED_EXCEPTION_PATHS = {
    "scripts/quality/architecture_analyzer.py",
    "scripts/quality/capability_gate_adapter.py",
    "scripts/quality/capability_trust_anchor.py",
}


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _identity_from_commit(commit: str, path: str) -> tuple[str, str, str]:
    metadata, listed_path = _git("ls-tree", commit, "--", path).split("\t", 1)
    assert listed_path == path
    mode, object_type, blob_sha = metadata.split()
    return mode, object_type, blob_sha


def _identity_from_worktree(path: str) -> tuple[str, str, str]:
    mode, object_type, _ = _identity_from_commit("HEAD", path)
    return mode, object_type, _git("hash-object", path)


def _transition_identity(row: dict, side: str) -> tuple[str, str, str]:
    identity = row[side]
    return identity["mode"], identity["objectType"], identity["blobSha"]


def _architecture_transition_identity(row: dict, side: str) -> tuple[str, str, str]:
    prefix = "base" if side == "base" else "candidate"
    return row[f"{prefix}Mode"], row[f"{prefix}ObjectType"], row[f"{prefix}BlobSha"]


def test_transition_manifests_introduce_no_wildcard_or_package_wide_authority():
    capability_paths = {
        row["path"] for row in _json(CAPABILITY_TRANSITION_PATH)["protectedArtifacts"]
    }
    architecture_paths = {
        row["path"] for row in _json(ARCHITECTURE_TRANSITION_PATH)["artifacts"]
    }
    support_paths = {
        row["path"] for row in _json(ARCHITECTURE_TRANSITION_PATH)["supportArtifacts"]
    }
    paths = capability_paths | architecture_paths | support_paths

    assert all("*" not in path and not path.endswith("/") for path in paths)
    assert capability_paths == {
        ".github/workflows/capability-protected.yml",
        CAPABILITY_REGISTRY_PATH,
        EXCEPTIONS_PATH,
        "scripts/quality/architecture_analyzer.py",
        CAPABILITY_GATE_ADAPTER_PATH,
        "scripts/quality/capability_trust_anchor.py",
    }
    assert architecture_paths == capability_paths - {
        EXCEPTIONS_PATH,
        CAPABILITY_GATE_ADAPTER_PATH,
    }
    assert support_paths == {
        EXCEPTIONS_PATH,
        CAPABILITY_TRANSITION_PATH,
        CAPABILITY_GATE_ADAPTER_PATH,
        "tests/test_repository_safety_gate.py",
    }


def test_capability_workflow_python_scope_admits_exception_transition_path():
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(
        encoding="utf-8"
    )
    protected_start = workflow.index("allowed_protected = {")
    protected_end = workflow.index("\n          }", protected_start)
    assert EXCEPTIONS_PATH in workflow[protected_start:protected_end]
    assert CAPABILITY_GATE_ADAPTER_PATH in workflow[protected_start:protected_end]
    start = workflow.index("allowed_paths = {")
    end = workflow.index("\n          }", start)
    assert EXCEPTIONS_PATH in workflow[start:end]
    assert CAPABILITY_GATE_ADAPTER_PATH in workflow[start:end]
    for path in trust_anchor._SUPPORT_SCOPES["LOCAL_WORD_COM_CONTAINMENT_V1"]:
        assert path in workflow[start:end]

    assert (
        "if: env.CAPABILITY_BASE_BOOTSTRAP_PRESENT != 'true' || "
        "env.CAPABILITY_WORD_SCOPE_CHANGED != 'true'"
    ) in workflow


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (EXCEPTIONS_PATH, False),
        (CAPABILITY_TRANSITION_PATH, None),
        ("scripts/backend_contract/infrastructure/office_pdf.py", True),
        ("tests/test_delivery_foundation_v1.py", True),
        ("tests/test_office_pdf_renderer_v1.py", True),
        (CAPABILITY_GATE_ADAPTER_PATH, True),
        ("scripts/backend_contract/delivery_foundation.py", False),
        ("frontend/src/workspaces/DeliveryFoundationView.tsx", False),
        (".github/workflows/architecture-protected.yml", False),
        (".github/workflows/arbitrary.yml", False),
    ],
)
def test_word_transition_routing_uses_exact_registered_scope(tmp_path, path, expected):
    route = getattr(trust_anchor, "_word_transition_scope_changed", None)
    assert callable(route)
    repo, base = _future_base_clone(tmp_path)
    changed = repo / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    original = changed.read_text(encoding="utf-8") if changed.exists() else ""
    changed.write_text(original + "\n# routing fixture\n", encoding="utf-8")
    candidate = _child_commit(repo, f"routing fixture {path}")

    assert route(repo, base, candidate) is expected


@pytest.mark.parametrize(
    ("field", "value", "remove"),
    [
        ("scope", "UNKNOWN_SCOPE", False),
        ("schemaVersion", "2.0.0", False),
        ("protectedArtifacts", "INVALID", False),
        ("protectedBaseSha", None, True),
    ],
)
def test_word_transition_routing_fails_closed_for_invalid_manifest(
    tmp_path, field, value, remove
):
    route = getattr(trust_anchor, "_word_transition_scope_changed", None)
    assert callable(route)
    repo, base = _future_base_clone(tmp_path)
    transition = repo / CAPABILITY_TRANSITION_PATH
    manifest = json.loads(transition.read_text(encoding="utf-8"))
    if remove:
        manifest.pop(field)
    else:
        manifest[field] = value
    transition.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    candidate = _child_commit(repo, "invalid routing manifest")

    assert route(repo, base, candidate) is None


def test_word_transition_routing_fails_closed_for_transition_only_mutation(tmp_path):
    route = getattr(trust_anchor, "_word_transition_scope_changed", None)
    assert callable(route)
    repo, base = _future_base_clone(tmp_path)
    transition = repo / CAPABILITY_TRANSITION_PATH
    manifest = json.loads(transition.read_text(encoding="utf-8"))
    manifest["protectedBaseSha"] = "0" * 40
    transition.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    candidate = _child_commit(repo, "transition-only mutation")

    assert route(repo, base, candidate) is None


def test_word_transition_routing_accepts_current_transition_with_word_change(tmp_path):
    route = getattr(trust_anchor, "_word_transition_scope_changed", None)
    assert callable(route)
    repo, base = _future_base_clone(tmp_path)
    changed = repo / "scripts/backend_contract/infrastructure/office_pdf.py"
    changed.parent.mkdir(parents=True, exist_ok=True)
    original = changed.read_text(encoding="utf-8") if changed.exists() else ""
    changed.write_text(
        original + "\n# Word fixture\n", encoding="utf-8"
    )
    transition = repo / CAPABILITY_TRANSITION_PATH
    manifest = json.loads(transition.read_text(encoding="utf-8"))
    manifest["protectedBaseSha"] = base
    transition.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    candidate = _child_commit(repo, "current Word transition")

    assert route(repo, base, candidate) is True


def test_rebind_rotates_only_exact_judge_exception_identities():
    base_rows = _git("show", f"{PROTECTED_BASE}:{EXCEPTIONS_PATH}")
    base = json.loads(base_rows)
    candidate = _json(EXCEPTIONS_PATH)

    assert len(candidate["exceptions"]) == len(base["exceptions"])
    changed_paths = set()
    for before, after in zip(base["exceptions"], candidate["exceptions"], strict=True):
        changed = {key for key in before if before[key] != after[key]}
        if not changed:
            continue
        changed_paths.add(after["canonicalPath"])
        assert changed == {"baselineCommit", "reviewEvidence", "wholeFileSha256"}
        assert after["baselineCommit"] == SOURCE_ANCHORS[after["canonicalPath"]]
        assert after["reviewEvidence"] == REVIEW_EVIDENCE[after["canonicalPath"]]
        assert after["wholeFileSha256"] == hashlib.sha256(
            (ROOT / after["canonicalPath"]).read_bytes()
        ).hexdigest()
    assert changed_paths == ROTATED_EXCEPTION_PATHS


def test_capability_registry_and_transition_bind_exact_exception_blob():
    registry = _json(CAPABILITY_REGISTRY_PATH)
    protected = next(row for row in registry["artifacts"] if row["path"] == EXCEPTIONS_PATH)
    assert (protected["mode"], protected["objectType"], protected["blobSha"]) == (
        *_identity_from_worktree(EXCEPTIONS_PATH)[:2],
        _identity_from_worktree(EXCEPTIONS_PATH)[2],
    )

    transition = _json(CAPABILITY_TRANSITION_PATH)
    assert transition["schemaVersion"] == "3.0.0"
    assert transition["transitionId"] == "LOCAL_WORD_COM_CONTAINMENT_TRUST_TRANSITION_V1"
    assert transition["purpose"] == "BOUND_MICROSOFT_WORD_COM_EXECUTION_FOR_AUTHORITATIVE_WORD_TO_PDF"
    assert transition["scope"] == "LOCAL_WORD_COM_CONTAINMENT_V1"
    assert transition["protectedBaseSha"] == PROTECTED_BASE
    assert {row["path"] for row in transition["protectedArtifacts"]} == {
        ".github/workflows/capability-protected.yml",
        CAPABILITY_REGISTRY_PATH,
        EXCEPTIONS_PATH,
        "scripts/quality/architecture_analyzer.py",
        CAPABILITY_GATE_ADAPTER_PATH,
        "scripts/quality/capability_trust_anchor.py",
    }
    assert {row["path"] for row in transition["supportArtifacts"]} == {
        "tests/test_architecture_capability_exception_rebind_v1.py",
        "tests/test_repository_safety_gate.py",
    }


def test_architecture_transition_binds_current_trust_anchor_rotation():
    transition = _json(ARCHITECTURE_TRANSITION_PATH)
    assert transition["schemaVersion"] == "3.0.0"
    assert transition["protectedBaseSha"] == ARCHITECTURE_PROTECTED_BASE

    artifact_rows = {row["path"]: row for row in transition["artifacts"]}
    assert set(artifact_rows) == {
        ".github/workflows/capability-protected.yml",
        CAPABILITY_REGISTRY_PATH,
        "scripts/quality/architecture_analyzer.py",
        "scripts/quality/capability_trust_anchor.py",
    }

    for path, row in artifact_rows.items():
        assert _architecture_transition_identity(row, "base") == _identity_from_commit(
            ARCHITECTURE_PROTECTED_BASE, path
        )
        assert _architecture_transition_identity(row, "candidate") == _identity_from_worktree(path)

    support_rows = {row["path"]: row for row in transition["supportArtifacts"]}
    assert transition["supportScope"] == "CAPABILITY_BOOTSTRAP_V1"
    assert set(support_rows) == {
        CAPABILITY_TRANSITION_PATH,
        EXCEPTIONS_PATH,
        CAPABILITY_GATE_ADAPTER_PATH,
        "tests/test_repository_safety_gate.py",
    }
    for path, row in support_rows.items():
        assert _architecture_transition_identity(row, "base") == _identity_from_commit(
            PROTECTED_BASE, path
        )
        assert _architecture_transition_identity(row, "candidate") == _identity_from_worktree(path)


def test_protected_workflows_use_trusted_locked_uv_dependencies():
    for path in E1A_PROTECTED_WORKFLOWS:
        workflow = (ROOT / path).read_text(encoding="utf-8")
        assert "uv lock --check" in workflow
        assert '$syncArgs = @("pip", "sync", "--system", "--require-hashes", "requirements-dev.txt")' in workflow
        assert "uv @syncArgs" in workflow
        assert "cache-dependency-glob: trusted/uv.lock" in workflow
        assert "pip install" not in workflow


def _future_base_clone(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "future-base"
    subprocess.run(
        ["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(repo)],
        check=True,
    )
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    for path in (
        ARCHITECTURE_TRANSITION_PATH,
        EXCEPTIONS_PATH,
        CAPABILITY_REGISTRY_PATH,
        CAPABILITY_TRANSITION_PATH,
    ):
        shutil.copyfile(ROOT / path, repo / path)
    subprocess.run(["git", "add", "--", *(
        ARCHITECTURE_TRANSITION_PATH,
        EXCEPTIONS_PATH,
        CAPABILITY_REGISTRY_PATH,
        CAPABILITY_TRANSITION_PATH,
    )], cwd=repo, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode:
        subprocess.run(["git", "commit", "-qm", "candidate protected base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return repo, base


def _child_commit(repo: Path, message: str) -> str:
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def test_future_base_rejects_one_byte_analyzer_drift(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    analyzer = repo / ANALYZER_PATH
    analyzer.write_text(analyzer.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    child = _child_commit(repo, "one-byte-class analyzer drift")

    findings = run_protected_capability_gate(repo, base, child)
    assert "PROCESS_NAMESPACE_ACQUISITION" in {row["code"] for row in findings}


def test_future_base_rejects_analyzer_ast_identity_drift(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    analyzer = repo / ANALYZER_PATH
    source = analyzer.read_text(encoding="utf-8")
    assert "import subprocess\n" in source
    analyzer.write_text(
        source.replace("import subprocess\n", "import subprocess as child_process\n", 1),
        encoding="utf-8",
    )
    child = _child_commit(repo, "analyzer acquisition AST drift")

    findings = run_protected_capability_gate(repo, base, child)
    assert "PROCESS_NAMESPACE_ACQUISITION" in {row["code"] for row in findings}


@pytest.mark.parametrize("drift", ["content", "mode", "type"])
def test_future_base_architecture_blocks_initializer_identity_drift(tmp_path, monkeypatch, drift):
    repo, base = _future_base_clone(tmp_path)
    initializer = repo / "scripts/quality/__init__.py"
    if drift == "content":
        initializer.write_text(initializer.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
    elif drift == "mode":
        subprocess.run(
            ["git", "update-index", "--chmod=+x", "scripts/quality/__init__.py"],
            cwd=repo,
            check=True,
        )
    else:
        initializer.unlink()
        initializer.mkdir()
        (initializer / "nested.py").write_text("# tree drift\n", encoding="utf-8")
    child = _child_commit(repo, f"initializer {drift} drift")
    monkeypatch.setenv("ARCHITECTURE_PROTECTED_BASE_SHA", base)
    monkeypatch.setenv("ARCHITECTURE_EXPECTED_HEAD_SHA", child)

    findings = run_architecture_gate(repo, child)
    assert "ARCHITECTURE_PROTECTED_ARTIFACT_MISMATCH" in {
        row["code"] for row in findings
    }


def test_future_base_capability_custody_blocks_exception_registry_drift(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    registry = repo / EXCEPTIONS_PATH
    registry.write_text(registry.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    child = _child_commit(repo, "exception registry drift")

    findings = run_protected_capability_gate(repo, base, child)
    assert findings
    assert {row["code"] for row in findings} <= {
        "CAPABILITY_PROTECTED_REGISTRY_ADVANCEMENT_INVALID",
        "CAPABILITY_PROTECTED_TRANSITION_INVALID",
    }


def test_future_base_suppresses_unchanged_capabilities_and_accepts_safe_child(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    safe = repo / "scripts/quality/rebind_safe_child.py"
    safe.write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    child = _child_commit(repo, "safe child")

    assert run_protected_capability_gate(repo, base, child) == []


def test_future_base_blocks_new_unauthorized_capability(tmp_path):
    repo, base = _future_base_clone(tmp_path)
    source = repo / "scripts/quality/unauthorized_process.py"
    source.write_text("import subprocess\n", encoding="utf-8")
    child = _child_commit(repo, "unauthorized process acquisition")

    findings = run_protected_capability_gate(repo, base, child)
    assert "PROCESS_NAMESPACE_ACQUISITION" in {row["code"] for row in findings}


def test_word_com_containment_scope_is_registered_with_exact_paths():
    scope = trust_anchor._SUPPORT_SCOPES["LOCAL_WORD_COM_CONTAINMENT_V1"]
    assert scope == {
        CAPABILITY_GATE_ADAPTER_PATH,
        "tests/test_delivery_foundation_v1.py",
        "scripts/backend_contract/infrastructure/office_pdf.py",
        "scripts/backend_contract/infrastructure/office_word_worker.py",
        "tests/test_office_pdf_renderer_v1.py",
        "tests/test_office_word_containment_v1.py",
    }


@pytest.mark.parametrize(
    "path",
    [
        EXCEPTIONS_PATH,
        CAPABILITY_TRANSITION_PATH,
        CAPABILITY_GATE_ADAPTER_PATH,
        "tests/test_delivery_foundation_v1.py",
        "scripts/backend_contract/infrastructure/office_pdf.py",
        "scripts/backend_contract/infrastructure/office_word_worker.py",
        "tests/test_office_pdf_renderer_v1.py",
        "tests/test_office_word_containment_v1.py",
    ],
)
def test_word_com_containment_scope_accepts_only_registered_paths(path):
    assert _support_path_in_scope("LOCAL_WORD_COM_CONTAINMENT_V1", path)


@pytest.mark.parametrize(
    "path",
    [
        "scripts/backend_contract/infrastructure/office.py",
        "scripts/backend_contract/infrastructure/office_pdf.py/child.py",
        "scripts/backend_contract/infrastructure/subprocess_runner.py",
        "scripts/backend_contract/infrastructure/office_word_worker.py.bak",
        "scripts/backend_contract/infrastructure/*.py",
        "scripts/quality/capability_gate_adapter.py.bak",
        "scripts/quality/capability_gate_adapter.py/child.py",
        "scripts/quality/*.py",
        "tests/test_office_word_containment_v1.py/extra",
    ],
)
def test_word_com_containment_scope_rejects_siblings_wildcards_and_prefixes(path):
    assert not _support_path_in_scope("LOCAL_WORD_COM_CONTAINMENT_V1", path)


def test_word_com_containment_scope_does_not_authorize_process_or_shell_namespaces():
    scope = trust_anchor._SUPPORT_SCOPES["LOCAL_WORD_COM_CONTAINMENT_V1"]
    assert not any("subprocess" in path or "shell" in path for path in scope)
    assert "scripts/backend_contract/infrastructure/office_pdf.py" in scope
    assert "scripts/backend_contract/infrastructure/office_word_worker.py" in scope


def test_dedicated_word_workflow_admits_exact_absent_to_present_identities():
    workflow = (ROOT / ".github/workflows/capability-protected.yml").read_text(
        encoding="utf-8"
    )

    assert "if not output:" in workflow
    assert "return {'path': path, 'state': 'ABSENT'}" in workflow
    assert "tests/test_delivery_foundation_v1.py" in workflow
    assert "_word_render_contract_is_closed" in workflow
    assert "$productOnlyRequired" in workflow
    assert "required <= changed <= allowed" in workflow
    assert "protected Word transition predecessor is closed on this base" in workflow


def _closed_word_render_sources() -> dict[str, str]:
    return {
        WORD_PARENT_PATH: '''
from pathlib import Path
import sys
from uuid import uuid4

from .office_word_worker import RENDER_OPERATION

def _controlled_worker_environment(root, *, job_name, instance_token):
    return {"PLP_WORD_JOB_NAME": job_name, "PLP_WORD_INSTANCE_TOKEN": instance_token}

def _quote_windows_argument(value):
    return value

def _start_owned_word_worker(root):
    import win32con
    import win32job
    import win32process
    executable = str(Path(sys.executable).resolve(strict=True))
    worker_script = str(Path(__file__).with_name("office_word_worker.py").resolve(strict=True))
    command_line = " ".join(
        _quote_windows_argument(value)
        for value in (executable, "-I", worker_script, str(root.resolve(strict=True)))
    )
    nonce = uuid4().hex
    job_name = f"Local\\\\PLP-Word-{nonce}"
    instance_token = f"PLP-Word-{nonce}"
    job = win32job.CreateJobObject(None, job_name)
    information = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    information["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, information)
    startup = win32process.STARTUPINFO()
    process, thread, pid, thread_id = win32process.CreateProcess(
        executable,
        command_line,
        None,
        None,
        False,
        win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW,
        _controlled_worker_environment(root, job_name=job_name, instance_token=instance_token),
        str(Path(__file__).resolve().parents[3]),
        startup,
    )
    win32job.AssignProcessToJobObject(job, process)
    win32process.ResumeThread(thread)
    return process
''',
        WORD_WORKER_PATH: '''
from pathlib import Path
import sys
import winreg

RENDER_OPERATION = "RENDER_BOUND_AUTHORITATIVE_WORD_TO_DERIVED_PDF"
_WORD_CLSID = "{000209FF-0000-0000-C000-000000000046}"

def _machine_word_executable():
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\\\Classes\\\\Word.Application\\\\CLSID") as key:
        clsid = winreg.QueryValueEx(key, None)[0]
    if clsid != _WORD_CLSID:
        raise RuntimeError("unexpected Word registration")
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"SOFTWARE\\\\Classes\\\\CLSID\\\\{_WORD_CLSID}\\\\LocalServer32") as key:
        command = winreg.QueryValueEx(key, None)[0]
    executable = Path(command.split(" /Automation", 1)[0].strip('"')).resolve(strict=True)
    if executable.name.casefold() != "winword.exe":
        raise RuntimeError("unexpected Word executable")
    return executable

def _start_owned_word_process(root):
    import win32api
    import win32con
    import win32job
    import win32process
    word_executable = str(_machine_word_executable())
    bootstrap = _write_bootstrap_document(root)
    command_line = " ".join((_quote_windows_argument(word_executable), "/x", "/q", _quote_windows_argument(str(bootstrap))))
    job = win32job.OpenJobObject(win32job.JOB_OBJECT_QUERY, False, "fixed-by-parent")
    if not win32job.IsProcessInJob(win32api.GetCurrentProcess(), job):
        raise RuntimeError("worker is not in owned job")
    startup = win32process.STARTUPINFO()
    process, thread, pid, thread_id = win32process.CreateProcess(
        word_executable,
        command_line,
        None,
        None,
        False,
        win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW,
        None,
        str(root),
        startup,
    )
    if not win32job.IsProcessInJob(process, job):
        raise RuntimeError("Word did not inherit owned job")
    win32process.ResumeThread(thread)
    return process, bootstrap

def _bind_owned_word_com_object(process, bootstrap):
    import pythoncom
    import win32com.client
    running_object_table = pythoncom.GetRunningObjectTable()
    moniker = _exact_bootstrap_moniker(running_object_table, bootstrap)
    unknown = running_object_table.GetObject(moniker)
    document = win32com.client.Dispatch(unknown.QueryInterface(pythoncom.IID_IDispatch))
    return document.Application, document

def _render_job(root, *, word_launcher=_start_owned_word_process, com_binder=_bind_owned_word_com_object):
    process, bootstrap = word_launcher(root)
    app, bootstrap_document = com_binder(process, bootstrap)
    app.AutomationSecurity = 3
    app.Visible = False
    app.DisplayAlerts = 0
    document = app.Documents.Open(
        FileName="fixed-source",
        ConfirmConversions=False,
        ReadOnly=True,
        AddToRecentFiles=False,
        OpenAndRepair=False,
        NoEncodingDialog=True,
    )
    document.ExportAsFixedFormat(
        OutputFileName="fixed-output",
        ExportFormat=17,
        OpenAfterExport=False,
        OptimizeFor=0,
        Range=0,
        Item=0,
        IncludeDocProps=True,
        CreateBookmarks=0,
        DocStructureTags=True,
        BitmapMissingFonts=True,
        UseISO19005_1=False,
    )
    document.Close(SaveChanges=0)
    app.Quit(SaveChanges=0)
''',
    }


def test_word_render_contract_accepts_only_the_pre_reviewed_exact_digests():
    assert _word_render_digests_are_closed(dict(_WORD_PRODUCT_SHA256))
    assert _WORD_PRODUCT_SHA256 == {
        WORD_PARENT_PATH: "0752949efd38fe08220d54828f73573223109f791ed4cd63772da95695f8058d",
        WORD_WORKER_PATH: "891c8811e84461dec50ac85a5649e49919093b36070404b6ae69ac9d0e6b4efa",
    }


@pytest.mark.parametrize(
    ("path", "old", "new"),
    [
        (WORD_PARENT_PATH, "        executable,\n        command_line,", "        attacker_executable,\n        attacker_command_line,"),
        (WORD_WORKER_PATH, '"winword.exe"', '"attacker.exe"'),
        (WORD_WORKER_PATH, "ReadOnly=True", "ReadOnly=False"),
        (WORD_WORKER_PATH, "app.AutomationSecurity = 3", "app.AutomationSecurity = 1"),
        (WORD_PARENT_PATH, "import sys", "import sys\nimport subprocess"),
    ],
)
def test_word_render_contract_rejects_semantic_bypasses(
    monkeypatch: pytest.MonkeyPatch, path: str, old: str, new: str
):
    sources = _closed_word_render_sources()
    monkeypatch.setattr(
        gate_adapter,
        "_WORD_PRODUCT_SHA256",
        {name: hashlib.sha256(value.encode("utf-8")).hexdigest() for name, value in sources.items()},
    )
    assert word_render_sources_are_closed(sources)
    assert old in sources[path]
    sources[path] = sources[path].replace(old, new, 1)

    assert not word_render_sources_are_closed(sources)


def test_word_render_digest_contract_rejects_any_path_or_digest_drift():
    for path in (WORD_PARENT_PATH, WORD_WORKER_PATH):
        changed = dict(_WORD_PRODUCT_SHA256)
        changed[path] = "0" * 64
        assert not _word_render_digests_are_closed(changed)
    assert not _word_render_digests_are_closed(
        {**_WORD_PRODUCT_SHA256, "scripts/unrelated.py": "0" * 64}
    )
    assert not _word_render_digests_are_closed(
        {WORD_PARENT_PATH: _WORD_PRODUCT_SHA256[WORD_PARENT_PATH]}
    )


def test_word_render_contract_rejects_generic_public_execution_api(
    monkeypatch: pytest.MonkeyPatch,
):
    sources = _closed_word_render_sources()
    monkeypatch.setattr(
        gate_adapter,
        "_WORD_PRODUCT_SHA256",
        {name: hashlib.sha256(value.encode("utf-8")).hexdigest() for name, value in sources.items()},
    )
    assert word_render_sources_are_closed(sources)
    sources[WORD_PARENT_PATH] += "\ndef run(executable, command_line):\n    return executable, command_line\n"

    assert not word_render_sources_are_closed(sources)


def test_word_render_contract_rejects_a_second_hidden_process_surface(
    monkeypatch: pytest.MonkeyPatch,
):
    sources = _closed_word_render_sources()
    monkeypatch.setattr(
        gate_adapter,
        "_WORD_PRODUCT_SHA256",
        {name: hashlib.sha256(value.encode("utf-8")).hexdigest() for name, value in sources.items()},
    )
    assert word_render_sources_are_closed(sources)
    sources[WORD_WORKER_PATH] += '''
def _alternate_process(executable, command_line, startup):
    return win32process.CreateProcess(
        executable, command_line, None, None, False, 0, None, None, startup
    )
'''

    assert not word_render_sources_are_closed(sources)
