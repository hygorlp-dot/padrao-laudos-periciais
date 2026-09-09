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
    monkeypatch.setattr(suite_conftest, "_FAILED_NODEIDS", set())

    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(failed=True, nodeid="tests/test_z.py::test_line[bad\nvalue]")
    )
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(failed=False, nodeid="tests/test_ignored.py::test_pass")
    )
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(failed=True, nodeid="tests/test_a.py::test_first")
    )
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(failed=True, nodeid="tests/test_a.py::test_first")
    )

    suite_conftest.pytest_unconfigure(None)

    assert capsys.readouterr().err.splitlines()[-1] == (
        'PYTEST_FAILED_NODEIDS=["tests/test_a.py::test_first",'
        '"tests/test_z.py::test_line[bad\\nvalue]"]'
    )


def test_clean_session_emits_no_failure_diagnostic(monkeypatch, capsys) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILED_NODEIDS", set())

    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(failed=False, nodeid="tests/test_ok.py::test_ok")
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
    assert completed.stderr.splitlines()[-1] == (
        'PYTEST_FAILED_NODEIDS=["test_failure_probe.py::test_probe"]'
    )
