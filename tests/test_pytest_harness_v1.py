from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import conftest as suite_conftest


def test_failed_nodeids_are_sanitized_deduplicated_and_emitted_last(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})

    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=True,
            nodeid="tests/test_z.py::test_line[bad\nvalue]",
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=str(Path(suite_conftest.__file__).resolve().parent / "test_z.py"),
                    lineno=17,
                    message="AssertionError: private payload must never be emitted",
                )
            ),
        )
    )
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=False,
            nodeid="tests/test_ignored.py::test_pass",
            when="call",
            longrepr=None,
        )
    )
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=True,
            nodeid="tests/test_a.py::test_first",
            when="setup",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=str(Path(suite_conftest.__file__).resolve().parent / "test_a.py"),
                    lineno=3,
                    message=(
                        "PermissionError: [WinError 32] file busy: "
                        "'C:\\\\private\\\\case-secret.pdf'"
                    ),
                )
            ),
        )
    )
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=True,
            nodeid="tests/test_a.py::test_first",
            when="setup",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=str(Path(suite_conftest.__file__).resolve().parent / "test_a.py"),
                    lineno=3,
                    message="PermissionError: duplicate must not be emitted",
                )
            ),
        )
    )

    suite_conftest.pytest_unconfigure(None)

    assert capsys.readouterr().err.splitlines()[-1] == (
        'PYTEST_FAILURE_DIAGNOSTICS_V1=[{"exception_type":"PermissionError",'
        '"location":"tests/test_a.py:3","message":"os_error:winerror=32",'
        '"nodeid":"tests/test_a.py::test_first","phase":"setup"},'
        '{"exception_type":"AssertionError","location":"tests/test_z.py:17",'
        '"message":"assertion_failed","nodeid":"tests/test_z.py::test_line[bad\\nvalue]",'
        '"phase":"call"}]'
    )


def test_clean_session_emits_no_failure_diagnostic(monkeypatch, capsys) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})

    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=False,
            nodeid="tests/test_ok.py::test_ok",
            when="call",
            longrepr=None,
        )
    )
    suite_conftest.pytest_unconfigure(None)

    assert capsys.readouterr().err == ""


def test_real_pytest_process_leaves_failed_nodeids_as_last_stderr_line(tmp_path) -> None:
    probe = tmp_path / "test_failure_probe.py"
    probe.write_text("def test_probe():\n    assert False\n", encoding="utf-8")
    tests_dir = Path(suite_conftest.__file__).resolve().parent
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        item
        for item in (str(tests_dir), environment.get("PYTHONPATH"))
        if item
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "conftest",
            probe.name,
            "-p",
            "no:cacheprovider",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    diagnostic = completed.stderr.splitlines()[-1]
    assert diagnostic.startswith("PYTEST_FAILURE_DIAGNOSTICS_V1=")
    assert '"exception_type":"AssertionError"' in diagnostic
    assert '"location":"<outside-repository>:2"' in diagnostic
    assert '"message":"assertion_failed"' in diagnostic
    assert '"nodeid":"test_failure_probe.py::test_probe"' in diagnostic
    assert '"phase":"call"' in diagnostic


def test_failure_diagnostic_never_emits_raw_message_or_absolute_path(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    private_path = r"D:\private\PROCESS-REAL\secret-name.pdf"
    private_message = f"RuntimeError: leaked material at {private_path} with CLIENT-NAME"

    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=True,
            nodeid="tests/test_safe.py::test_safe",
            when="teardown",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=private_path,
                    lineno=91,
                    message=private_message,
                )
            ),
        )
    )
    suite_conftest.pytest_unconfigure(None)

    diagnostic = capsys.readouterr().err.splitlines()[-1]
    assert private_path not in diagnostic
    assert "PROCESS-REAL" not in diagnostic
    assert "CLIENT-NAME" not in diagnostic
    assert '"location":"<outside-repository>:91"' in diagnostic
    assert '"message":"exception_message_redacted"' in diagnostic
