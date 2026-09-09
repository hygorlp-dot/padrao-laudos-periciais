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
    owned_test_path = str(Path(__file__).resolve())

    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid="tests/test_pytest_harness_v1.py::test_z_line[bad\nvalue]",
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=owned_test_path,
                    lineno=17,
                    message="AssertionError: private payload must never be emitted",
                )
            ),
        ),
        "AssertionError",
    )
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=False,
            nodeid="tests/test_ignored.py::test_pass",
            when="call",
            longrepr=None,
        )
    )
    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid="tests/test_pytest_harness_v1.py::test_a_first",
            when="setup",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=owned_test_path,
                    lineno=3,
                    message=(
                        "PermissionError: [WinError 32] file busy: "
                        "'C:\\\\private\\\\case-secret.pdf'"
                    ),
                )
            ),
        ),
        "PermissionError",
    )
    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid="tests/test_pytest_harness_v1.py::test_a_first",
            when="setup",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=owned_test_path,
                    lineno=3,
                    message="PermissionError: duplicate must not be emitted",
                )
            ),
        ),
        "PermissionError",
    )

    suite_conftest._emit_failure_diagnostics()

    assert capsys.readouterr().err.splitlines()[-1] == (
        'PYTEST_FAILURE_DIAGNOSTICS_V1=[{"exception_type":"PermissionError",'
        '"location":"tests/test_pytest_harness_v1.py:3",'
        '"message":"os_error:winerror=32",'
        '"nodeid":"tests/test_pytest_harness_v1.py::test_a_first",'
        '"phase":"setup"},{"exception_type":"AssertionError",'
        '"location":"tests/test_pytest_harness_v1.py:17",'
        '"message":"assertion_failed",'
        '"nodeid":"tests/test_pytest_harness_v1.py::test_z_line[parameters-redacted]",'
        '"phase":"call","redacted_instance":"1"}]'
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
    suite_conftest._emit_failure_diagnostics()

    assert capsys.readouterr().err == ""


def test_real_pytest_process_leaves_failed_nodeids_as_last_stderr_line(tmp_path) -> None:
    probe = tmp_path / "test_failure_probe.py"
    probe.write_text("def test_probe():\n    assert False\n", encoding="utf-8")
    late_plugin = tmp_path / "late_plugin.py"
    late_plugin.write_text(
        "import sys\n"
        "import pytest\n\n"
        "@pytest.hookimpl(trylast=True)\n"
        "def pytest_unconfigure(config):\n"
        "    print('LATE_PLUGIN_UNCONFIGURE', file=sys.stderr, flush=True)\n",
        encoding="utf-8",
    )
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
            "-p",
            "late_plugin",
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
    assert "LATE_PLUGIN_UNCONFIGURE" in completed.stderr.splitlines()[:-1]
    assert '"exception_type":"AssertionError"' in diagnostic
    assert '"location":"<outside-repository>:2"' in diagnostic
    assert '"message":"assertion_failed"' in diagnostic
    assert '"nodeid":"<outside-repository>"' in diagnostic
    assert '"phase":"call"' in diagnostic


def test_failure_diagnostic_never_emits_raw_message_or_absolute_path(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    private_path = r"D:\private\PROCESS-REAL\secret-name.pdf"
    private_message = f"RuntimeError: leaked material at {private_path} with CLIENT-NAME"
    private_node_parameter = "CLIENT-NAME-PRIVATE-PARAMETER"
    repository_private_path = (
        Path(suite_conftest.__file__).resolve().parents[1]
        / "referencias"
        / "privadas"
        / "SYNTHETIC-PRIVATE-LOCATION.py"
    )

    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=True,
            nodeid=(
                "tests/test_pytest_harness_v1.py::"
                f"test_safe[{private_node_parameter}]"
            ),
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
    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=True,
            nodeid=(
                "tests/test_pytest_harness_v1.py::"
                "test_repository_private_location"
            ),
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=str(repository_private_path),
                    lineno=92,
                    message="RuntimeError: hidden",
                )
            ),
        )
    )
    suite_conftest._emit_failure_diagnostics()

    diagnostic = capsys.readouterr().err.splitlines()[-1]
    assert private_path not in diagnostic
    assert "PROCESS-REAL" not in diagnostic
    assert "CLIENT-NAME" not in diagnostic
    assert private_node_parameter not in diagnostic
    assert "referencias/privadas" not in diagnostic
    assert "SYNTHETIC-PRIVATE-LOCATION" not in diagnostic
    assert '"location":"<outside-repository>:91"' in diagnostic
    assert '"location":"<outside-repository>:92"' in diagnostic
    assert '"message":"exception_message_redacted"' in diagnostic
    assert (
        '"nodeid":"tests/test_pytest_harness_v1.py::'
        'test_safe[parameters-redacted]"' in diagnostic
    )


def test_failure_diagnostic_bounds_hostile_parameterized_nodeid(monkeypatch) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    hostile_parameter = "SYNTHETIC-PRIVATE-" + ("x" * 200_000)

    suite_conftest.pytest_runtest_logreport(
        SimpleNamespace(
            failed=True,
            nodeid=f"tests/test_pytest_harness_v1.py::test_probe[{hostile_parameter}]",
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=str(Path(__file__).resolve()),
                    lineno=1,
                    message="AssertionError: hidden",
                )
            ),
        )
    )

    diagnostic = suite_conftest._failure_diagnostic_line(
        suite_conftest._FAILURE_DIAGNOSTICS
    )
    assert hostile_parameter not in diagnostic
    assert len(diagnostic.encode("utf-8")) < 2_048
    assert suite_conftest._repository_location(
        str(Path(__file__).resolve()),
        10**5_000,
    ) == "tests/test_pytest_harness_v1.py"


def test_failure_diagnostic_preserves_redacted_parameter_cardinality(monkeypatch) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    secret_parameters = ("SYNTHETIC-SECRET-ALPHA", "SYNTHETIC-SECRET-BETA")

    for parameter in secret_parameters:
        report = SimpleNamespace(
            failed=True,
            nodeid=(
                "tests/test_pytest_harness_v1.py::"
                f"test_parameter_case[{parameter}]"
            ),
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path=str(Path(__file__).resolve()),
                    lineno=1,
                    message="AssertionError: hidden",
                )
            ),
        )
        suite_conftest.pytest_runtest_logreport(report)
        suite_conftest.pytest_runtest_logreport(report)

    diagnostic = suite_conftest._failure_diagnostic_line(
        suite_conftest._FAILURE_DIAGNOSTICS
    )
    assert len(suite_conftest._FAILURE_DIAGNOSTICS) == 2
    assert diagnostic.count("test_parameter_case[parameters-redacted]") == 2
    assert '"redacted_instance":"1"' in diagnostic
    assert '"redacted_instance":"2"' in diagnostic
    assert all(parameter not in diagnostic for parameter in secret_parameters)


def test_failure_diagnostic_caps_failure_cascade(monkeypatch) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})

    for index in range(140):
        suite_conftest.pytest_runtest_logreport(
            SimpleNamespace(
                failed=True,
                nodeid=(
                    "tests/test_pytest_harness_v1.py::"
                    f"test_synthetic_failure_{index}"
                ),
                when="call",
                longrepr=SimpleNamespace(
                    reprcrash=SimpleNamespace(
                        path=str(Path(__file__).resolve()),
                        lineno=1,
                        message="AssertionError: hidden",
                    )
                ),
            )
        )

    diagnostic = suite_conftest._failure_diagnostic_line(
        suite_conftest._FAILURE_DIAGNOSTICS
    )
    assert len(suite_conftest._FAILURE_DIAGNOSTICS) == 129
    assert '"nodeid":"<diagnostic-limit-reached>"' in diagnostic
