from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import types

import pytest

from scripts.backend_contract.infrastructure import office_pdf, office_word_worker
from scripts.backend_contract.infrastructure.office_pdf import (
    LocalOfficePdfConverter,
    RendererUnavailable,
)
from scripts.backend_contract.infrastructure.office_word_worker import (
    RENDER_OPERATION,
    _owned_job_name,
    _load_request,
    _render_job,
)


class _CompletedWorker:
    def __init__(self, root: Path) -> None:
        self.identity = office_pdf.OwnedProcessIdentity(101, "created", "python.exe")
        source = next(root.glob("source.doc*"))
        output = root / "output.partial.pdf"
        payload = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
        output.write_bytes(payload)
        (root / "result.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0.0",
                    "status": "SUCCESS",
                    "operation": RENDER_OPERATION,
                    "rendererType": "MICROSOFT_WORD_DESKTOP_COM",
                    "rendererVersion": "16.0",
                    "wordSha256": sha256(source.read_bytes()).hexdigest(),
                    "pdfSha256": sha256(payload).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        self.closed = False

    def wait(self, _milliseconds: int) -> bool:
        return True

    def observed_identity(self):
        return self.identity

    def terminate_job(self) -> None:
        raise AssertionError("completed worker must not be terminated")

    def wait_contained(self, _milliseconds: int) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class _FakeDocument:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def ExportAsFixedFormat(self, **kwargs) -> None:
        self.calls.append(("export", kwargs))
        Path(kwargs["OutputFileName"]).write_bytes(b"%PDF-1.7\n%%EOF")

    def Close(self, **kwargs) -> None:
        self.calls.append(("close", kwargs))


class _FakeWord:
    Version = "16.0"

    def __init__(self, calls: list[tuple]) -> None:
        object.__setattr__(self, "calls", calls)
        self.Documents = self

    def __setattr__(self, name, value) -> None:
        if name in {"AutomationSecurity", "Visible", "DisplayAlerts"}:
            self.calls.append(("set", name, value))
        object.__setattr__(self, name, value)

    def Open(self, **kwargs):
        self.calls.append(("open", kwargs))
        return _FakeDocument(self.calls)

    def Quit(self, **kwargs) -> None:
        self.calls.append(("quit", kwargs))


class _OwnershipCheckingWord(_FakeWord):
    @property
    def Version(self) -> str:
        assert any(call[0] == "word-process-owned" for call in self.calls)
        return "16.0"

    def Open(self, **kwargs):
        assert any(call[0] == "word-com-bound" for call in self.calls)
        assert ("set", "AutomationSecurity", 3) in self.calls
        return super().Open(**kwargs)


class _FakeBootstrapDocument:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls
        self.ActiveWindow = type("Window", (), {"Hwnd": 1})()

    def Close(self, **kwargs) -> None:
        self.calls.append(("bootstrap-close", kwargs))


class _FakeProcess:
    def __init__(self, calls: list[tuple]) -> None:
        self.calls = calls

    def Close(self) -> None:
        self.calls.append(("process-close",))


def _word_launcher(tmp_path: Path, calls: list[tuple]):
    bootstrap = tmp_path / "bootstrap.docx"
    bootstrap.write_bytes(b"synthetic-bootstrap")
    calls.append(("word-process-owned",))
    return _FakeProcess(calls), bootstrap


def _com_binder(calls: list[tuple]):
    def bind(_process, _bootstrap):
        calls.append(("word-com-bound",))
        return _FakeWord(calls), _FakeBootstrapDocument(calls)

    return bind


def test_converter_uses_closed_worker_protocol_and_preserves_word_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[_CompletedWorker] = []

    def start(root: Path):
        worker = _CompletedWorker(root)
        started.append(worker)
        return worker

    monkeypatch.setattr(office_pdf, "_start_owned_word_worker", start)
    source = b"synthetic-authoritative-word"
    converter = LocalOfficePdfConverter(temp_root=tmp_path)

    output = converter.convert(source, "DOCX")

    assert output.startswith(b"%PDF-1.7")
    assert source == b"synthetic-authoritative-word"
    assert converter.renderer_version == "16.0"
    assert started[0].closed is True


def test_word_worker_hard_codes_read_only_word_to_pdf_operation(tmp_path: Path) -> None:
    source = b"synthetic-worker-word"
    (tmp_path / "source.docx").write_bytes(source)
    (tmp_path / "request.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "operation": RENDER_OPERATION,
                "sourceFormat": "DOCX",
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple] = []

    result = _render_job(
        tmp_path,
        word_launcher=lambda root: _word_launcher(root, calls),
        com_binder=_com_binder(calls),
    )

    opened = next(call[1] for call in calls if call[0] == "open")
    exported = next(call[1] for call in calls if call[0] == "export")
    assert opened["ReadOnly"] is True
    assert opened["AddToRecentFiles"] is False
    assert exported["ExportFormat"] == 17
    assert result["rendererVersion"] == "16.0"
    assert result["wordSha256"] == sha256(source).hexdigest()
    assert any(call[0] == "close" for call in calls)
    assert ("set", "AutomationSecurity", 3) in calls
    assert any(call[0] == "bootstrap-close" for call in calls)
    assert any(call[0] == "quit" for call in calls)
    assert any(call[0] == "process-close" for call in calls)


def test_word_worker_binds_exact_owned_process_and_disables_macros_before_open(
    tmp_path: Path,
) -> None:
    (tmp_path / "source.docx").write_bytes(b"synthetic-worker-word")
    (tmp_path / "request.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "operation": RENDER_OPERATION,
                "sourceFormat": "DOCX",
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple] = []

    _render_job(
        tmp_path,
        word_launcher=lambda root: _word_launcher(root, calls),
        com_binder=lambda _process, _bootstrap: (
            calls.append(("word-com-bound",))
            or (_OwnershipCheckingWord(calls), _FakeBootstrapDocument(calls))
        ),
    )

    names = [call[0] for call in calls]
    assert names.index("word-process-owned") < names.index("word-com-bound")
    assert names.index("word-com-bound") < names.index("open")
    assert calls.index(("set", "AutomationSecurity", 3)) < names.index("open")


def test_worker_request_is_exact_and_rejects_arbitrary_protocol(tmp_path: Path) -> None:
    request = {
        "schemaVersion": "1.0.0",
        "operation": RENDER_OPERATION,
        "sourceFormat": "DOCM",
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    assert _load_request(tmp_path) == request

    for invalid in (
        {**request, "command": "arbitrary"},
        {**request, "operation": "RUN_COMMAND"},
        {**request, "sourceFormat": "PDF"},
    ):
        path.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(ValueError, match="request"):
            _load_request(tmp_path)


def test_word_process_ownership_context_fails_closed_before_process_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLP_WORD_JOB_NAME", raising=False)
    monkeypatch.delenv("PLP_WORD_INSTANCE_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="ownership context"):
        _owned_job_name()


def test_converter_rejects_invalid_input_and_fails_closed(tmp_path: Path) -> None:
    converter = LocalOfficePdfConverter(temp_root=tmp_path)
    with pytest.raises(ValueError, match="DOCX or DOCM"):
        converter.convert(b"bytes", "PDF")
    with pytest.raises(ValueError, match="bytes"):
        converter.convert("not-bytes", "DOCX")  # type: ignore[arg-type]


def test_missing_windows_worker_dependency_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        office_pdf,
        "_start_owned_word_worker",
        lambda _root: (_ for _ in ()).throw(RendererUnavailable("missing")),
    )
    converter = LocalOfficePdfConverter(temp_root=tmp_path)
    with pytest.raises(RendererUnavailable, match="missing"):
        converter.convert(b"synthetic", "DOCX")


def test_job_assignment_failure_terminates_exact_suspended_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class _Handle:
        def __init__(self, kind: str) -> None:
            self.kind = kind
            self.alive = kind == "process"

        def Close(self) -> None:
            events.append(f"{self.kind}-close")

    process = _Handle("process")
    thread = _Handle("thread")
    job = _Handle("job")
    win32con = types.SimpleNamespace(CREATE_SUSPENDED=4, CREATE_NO_WINDOW=8)
    win32event = types.SimpleNamespace(WAIT_OBJECT_0=0)
    win32job = types.SimpleNamespace(
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=1,
        JobObjectExtendedLimitInformation=9,
        CreateJobObject=lambda _security, _name: job,
        QueryInformationJobObject=lambda _job, _kind: {
            "BasicLimitInformation": {"LimitFlags": 0}
        },
        SetInformationJobObject=lambda _job, _kind, _value: None,
        AssignProcessToJobObject=lambda _job, _process: (_ for _ in ()).throw(
            OSError("synthetic assignment failure")
        ),
        TerminateJobObject=lambda _job, _code: events.append("job-terminate"),
    )

    class _StartupInfo:
        pass

    def _create_process(*_args):
        events.append("process-created-suspended")
        return process, thread, 4242, 4343

    def _terminate_process(handle, _code):
        handle.alive = False
        events.append("process-terminate")

    win32process = types.SimpleNamespace(
        STARTUPINFO=_StartupInfo,
        CreateProcess=_create_process,
        TerminateProcess=_terminate_process,
    )
    for name, module in {
        "win32con": win32con,
        "win32event": win32event,
        "win32job": win32job,
        "win32process": win32process,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    with pytest.raises(RendererUnavailable, match="could not start"):
        office_pdf._start_owned_word_worker(tmp_path)

    assert process.alive is False
    assert "process-terminate" in events
    assert "process-close" in events
    assert "job-close" in events


def test_rot_binding_rejects_signaled_original_process_even_if_pid_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    process_handle = object()
    job_handle = object()
    process = office_word_worker._OwnedWordProcess(
        handle=process_handle,
        job=job_handle,
        pid=4242,
        creation_identity="created-a",
        image_path="C:/Program Files/Microsoft Office/WINWORD.EXE",
    )
    bootstrap = tmp_path / "bootstrap.docx"
    bootstrap.write_bytes(b"synthetic-bootstrap")
    bootstrap_document = types.SimpleNamespace(
        Application=object(),
        ActiveWindow=types.SimpleNamespace(Hwnd=77),
    )
    unknown = types.SimpleNamespace(QueryInterface=lambda _iid: object())
    pythoncom = types.SimpleNamespace(
        IID_IDispatch=object(),
        GetRunningObjectTable=lambda: types.SimpleNamespace(
            GetObject=lambda _moniker: unknown
        ),
    )
    win32com_client = types.ModuleType("win32com.client")
    win32com_client.Dispatch = lambda _dispatch: bootstrap_document
    win32com = types.ModuleType("win32com")
    win32com.client = win32com_client
    win32event = types.SimpleNamespace(
        WAIT_OBJECT_0=0,
        WAIT_TIMEOUT=258,
        WaitForSingleObject=lambda _process, _milliseconds: 0,
    )
    win32job = types.SimpleNamespace(
        IsProcessInJob=lambda _process, _job: True,
    )
    win32process = types.SimpleNamespace(
        GetWindowThreadProcessId=lambda _hwnd: (1, 4242),
        GetProcessId=lambda _process: 4242,
        GetProcessTimes=lambda _process: {"CreationTime": "created-a"},
        GetModuleFileNameEx=lambda _process, _module: (
            "C:/Program Files/Microsoft Office/WINWORD.EXE"
        ),
    )
    for name, module in {
        "pythoncom": pythoncom,
        "win32com": win32com,
        "win32com.client": win32com_client,
        "win32event": win32event,
        "win32job": win32job,
        "win32process": win32process,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(
        office_word_worker,
        "_exact_bootstrap_moniker",
        lambda _rot, _process, _bootstrap: object(),
    )

    with pytest.raises(RuntimeError, match="identity"):
        office_word_worker._bind_owned_word_com_object(process, bootstrap)


def test_missing_word_version_cannot_produce_success_result(tmp_path: Path) -> None:
    (tmp_path / "source.docx").write_bytes(b"synthetic-worker-word")
    (tmp_path / "request.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "operation": RENDER_OPERATION,
                "sourceFormat": "DOCX",
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple] = []

    class _VersionlessWord(_FakeWord):
        @property
        def Version(self):
            raise AttributeError("synthetic missing version")

    versionless_word = _VersionlessWord(calls)

    with pytest.raises(RuntimeError, match="render"):
        _render_job(
            tmp_path,
            word_launcher=lambda root: _word_launcher(root, calls),
            com_binder=lambda _process, _bootstrap: (
                versionless_word,
                _FakeBootstrapDocument(calls),
            ),
        )

    assert not (tmp_path / "result.json").exists()


def test_parent_rejects_unknown_renderer_version(tmp_path: Path) -> None:
    output = b"%PDF-1.7\n%%EOF"
    (tmp_path / "output.partial.pdf").write_bytes(output)
    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "status": "SUCCESS",
                "operation": RENDER_OPERATION,
                "rendererType": "MICROSOFT_WORD_DESKTOP_COM",
                "rendererVersion": "UNKNOWN",
                "wordSha256": "word-digest",
                "pdfSha256": sha256(output).hexdigest(),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RendererUnavailable, match="integrity"):
        office_pdf._load_result(tmp_path, "word-digest")


def test_render_tree_cleanup_is_bounded_across_transient_office_file_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "render-root"
    root.mkdir()
    (root / "source.docx").write_bytes(b"synthetic-private-source")
    real_rmtree = shutil.rmtree
    attempts = 0
    pauses: list[float] = []

    def _transient_rmtree(path: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("synthetic transient Office diagnostics lock")
        real_rmtree(path)

    monkeypatch.setattr(office_pdf.shutil, "rmtree", _transient_rmtree)

    office_pdf._remove_render_tree(
        root,
        clock=iter((0.0, 0.1)).__next__,
        pause=pauses.append,
    )

    assert attempts == 2
    assert pauses == [0.05]
    assert not root.exists()


def test_sensitive_source_unlink_uses_the_same_bounded_cleanup_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "render-root"
    root.mkdir()
    source = root / "source.docx"
    source.write_bytes(b"synthetic-private-source")
    real_unlink = Path.unlink
    real_rmtree = shutil.rmtree
    unlink_attempts = 0
    pauses: list[float] = []

    def _transient_unlink(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal unlink_attempts
        if path == source:
            unlink_attempts += 1
            if unlink_attempts == 1:
                raise PermissionError("synthetic transient source lock")
        real_unlink(path, missing_ok=missing_ok)

    def _guarded_rmtree(path: Path) -> None:
        if source.exists():
            raise PermissionError("synthetic tree lock while source is open")
        real_rmtree(path)

    monkeypatch.setattr(Path, "unlink", _transient_unlink)
    monkeypatch.setattr(office_pdf.shutil, "rmtree", _guarded_rmtree)

    office_pdf._remove_render_tree(
        root,
        clock=iter((0.0, 0.1)).__next__,
        pause=pauses.append,
    )

    assert unlink_attempts == 2
    assert pauses == [0.05]
    assert not root.exists()


def test_production_sources_expose_no_generic_process_or_com_api() -> None:
    office_source = Path(office_pdf.__file__).read_text(encoding="utf-8")
    worker_source = Path(__file__).parents[1].joinpath(
        "scripts/backend_contract/infrastructure/office_word_worker.py"
    ).read_text(encoding="utf-8")
    combined = office_source + worker_source

    assert "taskkill" not in combined.casefold()
    assert "subprocess" not in combined
    assert "multiprocessing" not in combined
    assert "def run(command" not in combined
    assert "def execute(" not in combined
    assert "invoke_com" not in combined
    assert "DispatchEx" not in combined
    assert "WScript.Shell" not in combined
    assert combined.count('"{000209FF-0000-0000-C000-000000000046}"') == 1
    assert "winreg.HKEY_CURRENT_USER" not in combined
