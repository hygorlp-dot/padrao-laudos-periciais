from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace

import pytest

import conftest as suite_conftest
from tests import test_local_api_v1 as local_api_tests


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


def test_timeout_diagnostic_identifies_safe_local_api_operation(
    monkeypatch,
    capsys,
) -> None:
    """A timeout must identify the bounded operation without private data."""
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SEQUENCE", 0)
    nodeid = "tests/test_recovery_transaction_v1.py::test_probe[SECRET-parameter]"

    suite_conftest._record_local_api_timeout(
        nodeid=nodeid,
        method="POST",
        target=(
            "/v1/recovery/00000000-0000-4000-8000-000000000001/discard"
            "?token=PRIVATE"
        ),
        client_phase="CLIENT_GETRESPONSE",
        elapsed_seconds=5.2,
    )
    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid=nodeid,
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path="C:/outside/private.py",
                    lineno=723,
                    message="TimeoutError: private response body",
                )
            ),
        ),
        "TimeoutError",
    )

    suite_conftest._emit_failure_diagnostics()
    diagnostic = capsys.readouterr().err.splitlines()[-1]

    assert '"request_seq":"1"' in diagnostic
    assert '"method":"POST"' in diagnostic
    assert '"route_family":"RECOVERY_DISCARD"' in diagnostic
    assert '"client_phase":"CLIENT_GETRESPONSE"' in diagnostic
    assert '"elapsed_bucket":">5s"' in diagnostic
    assert '"timeout_boundary":"CLIENT_TRANSPORT_DEADLINE"' in diagnostic
    assert "00000000-0000-4000-8000-000000000001" not in diagnostic
    assert "PRIVATE" not in diagnostic
    assert "private response body" not in diagnostic


def test_timeout_diagnostic_identifies_last_observable_server_phase(
    monkeypatch,
    capsys,
) -> None:
    """A client timeout must expose the last safe server phase when known."""
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SERVER_PHASES", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SEQUENCE", 0)
    nodeid = "tests/test_recovery_transaction_v1.py::test_server_phase_probe"

    suite_conftest._record_local_api_timeout(
        nodeid=nodeid,
        method="POST",
        target="/v1/workspaces/00000000-0000-4000-8000-000000000001/materials",
        client_phase="CLIENT_GETRESPONSE",
        elapsed_seconds=5.2,
    )
    suite_conftest._record_server_phase(
        request_seq="1",
        phase="LOCAL_API_HANDLE_STARTED",
    )
    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid=nodeid,
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path="C:/outside/private.py",
                    lineno=723,
                    message="TimeoutError: hidden",
                )
            ),
        ),
        "TimeoutError",
    )
    suite_conftest._emit_failure_diagnostics()
    diagnostic = capsys.readouterr().err.splitlines()[-1]

    assert '"server_last_phase":"LOCAL_API_HANDLE_STARTED"' in diagnostic
    assert '"route_family":"WORKSPACE_MATERIALS"' in diagnostic


def test_timeout_diagnostic_identifies_last_observable_internal_phase(
    monkeypatch,
    capsys,
) -> None:
    """A handler timeout must expose its last bounded internal phase."""
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SERVER_PHASES", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_INTERNAL_PHASES", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SEQUENCE", 0)
    nodeid = "tests/test_recovery_transaction_v1.py::test_internal_phase_probe"

    suite_conftest._record_local_api_timeout(
        nodeid=nodeid,
        method="POST",
        target="/v1/recovery/staging",
        client_phase="CLIENT_GETRESPONSE",
        elapsed_seconds=5.2,
    )
    suite_conftest._record_internal_phase(
        request_seq="1",
        phase="APPLICATION_COMMAND_STARTED",
    )
    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid=nodeid,
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path="C:/outside/private.py",
                    lineno=723,
                    message="TimeoutError: hidden",
                )
            ),
        ),
        "TimeoutError",
    )
    suite_conftest._emit_failure_diagnostics()
    diagnostic = capsys.readouterr().err.splitlines()[-1]

    assert '"internal_last_phase":"APPLICATION_COMMAND_STARTED"' in diagnostic
    assert '"route_family":"RECOVERY_STAGE"' in diagnostic


@pytest.mark.parametrize(
    ("failure_point", "expected_phase"),
    (
        ("connect", "CLIENT_CONNECT"),
        ("getresponse", "CLIENT_GETRESPONSE"),
        ("read", "CLIENT_READ"),
    ),
)
def test_http_request_timeout_records_observable_client_phase(
    monkeypatch,
    capsys,
    failure_point,
    expected_phase,
) -> None:
    """The first-party HTTP helper records only the phase that timed out."""
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SEQUENCE", 0)

    class Response:
        status = 200

        def getheaders(self):
            return (("Content-Length", "0"),)

        def read(self):
            if failure_point == "read":
                raise TimeoutError("PRIVATE response body")
            return b""

    class Connection:
        def __init__(self, _host, _port, timeout):
            self.sock = None
            self.timeout = timeout

        def request(self, *_args, **_kwargs):
            if failure_point == "connect":
                raise TimeoutError("PRIVATE connect detail")
            self.sock = object()

        def getresponse(self):
            if failure_point == "getresponse":
                raise TimeoutError("PRIVATE response detail")
            return Response()

        def close(self):
            return None

    monkeypatch.setattr(local_api_tests.http.client, "HTTPConnection", Connection)
    server = SimpleNamespace(address=("127.0.0.1", 1))
    with pytest.raises(TimeoutError):
        local_api_tests.http_request(
            server,
            "POST",
            "/v1/recovery/00000000-0000-4000-8000-000000000001/promote?secret=PRIVATE",
            value={"payload": "PRIVATE"},
        )

    nodeid = suite_conftest._CURRENT_NODEID.get()
    assert nodeid is not None
    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid=nodeid,
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path="C:/outside/private.py",
                    lineno=723,
                    message="TimeoutError: PRIVATE detail",
                )
            ),
        ),
        "TimeoutError",
    )
    suite_conftest._emit_failure_diagnostics()
    diagnostic = capsys.readouterr().err.splitlines()[-1]
    assert f'"client_phase":"{expected_phase}"' in diagnostic
    assert '"server_last_phase":"UNKNOWN"' in diagnostic
    assert '"route_family":"RECOVERY_PROMOTE"' in diagnostic
    assert '"method":"POST"' in diagnostic
    assert "00000000-0000-4000-8000-000000000001" not in diagnostic
    assert "PRIVATE" not in diagnostic


def test_server_phase_correlation_is_bounded_and_request_scoped(monkeypatch) -> None:
    """Only bounded synthetic sequences can contribute a server phase."""
    monkeypatch.setattr(suite_conftest, "_REQUEST_SERVER_PHASES", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_INTERNAL_PHASES", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SEQUENCE", 0)
    monkeypatch.setattr(suite_conftest, "_ACTIVE_REQUEST_SEQUENCES", set())
    assert suite_conftest._begin_local_api_request() == "1"
    assert suite_conftest._begin_local_api_request() == "2"

    suite_conftest._record_server_phase(
        request_seq="not-a-sequence", phase="LOCAL_API_HANDLE_STARTED"
    )
    suite_conftest._record_server_phase(request_seq="1", phase="PRIVATE_PHASE")
    suite_conftest._record_server_phase(
        request_seq="1", phase="LOCAL_API_HANDLE_STARTED"
    )
    suite_conftest._record_server_phase(
        request_seq="1", phase="RESPONSE_HEADERS_STARTED"
    )
    suite_conftest._record_server_phase(
        request_seq="2", phase="RESPONSE_COMPLETED"
    )
    suite_conftest._record_internal_phase(
        request_seq="1", phase="ROUTE_DISPATCH_STARTED"
    )
    suite_conftest._record_internal_phase(
        request_seq="1", phase="APPLICATION_COMMAND_STARTED"
    )
    suite_conftest._record_internal_phase(
        request_seq="1", phase="APPLICATION_COMMAND_STARTED"
    )
    suite_conftest._record_internal_phase(request_seq="1", phase="PRIVATE_PHASE")

    assert suite_conftest._REQUEST_SERVER_PHASES == {
        "1": ["LOCAL_API_HANDLE_STARTED", "RESPONSE_HEADERS_STARTED"],
        "2": ["RESPONSE_COMPLETED"],
    }
    assert suite_conftest._REQUEST_INTERNAL_PHASES == {
        "1": ["ROUTE_DISPATCH_STARTED", "APPLICATION_COMMAND_STARTED"]
    }

    suite_conftest._record_local_api_timeout(
        nodeid="tests/test_pytest_harness_v1.py::test_untrusted_sequence",
        method="GET",
        target="/v1/workspaces",
        client_phase="CLIENT_GETRESPONSE",
        elapsed_seconds=5.1,
        request_seq="PRIVATE_SEQUENCE",
    )
    assert (
        suite_conftest._REQUEST_TIMEOUT_OBSERVATIONS[
            "tests/test_pytest_harness_v1.py::test_untrusted_sequence"
        ][0]["request_seq"]
        == "3"
    )

    for index in range(200):
        request_seq = suite_conftest._begin_local_api_request()
        suite_conftest._record_server_phase(
            request_seq=request_seq, phase="LOCAL_API_HANDLE_STARTED"
        )
    assert len(suite_conftest._REQUEST_SERVER_PHASES) <= 128

    for index in range(200):
        request_seq = suite_conftest._begin_local_api_request()
        suite_conftest._record_internal_phase(
            request_seq=request_seq, phase="ROUTE_DISPATCH_STARTED"
        )
    assert len(suite_conftest._REQUEST_INTERNAL_PHASES) <= 128

    suite_conftest._finish_local_api_request("2", retain=False)
    assert "2" not in suite_conftest._REQUEST_SERVER_PHASES
    assert "2" not in suite_conftest._REQUEST_INTERNAL_PHASES


def test_timeout_observability_bounds_cascade_and_rejects_untrusted_target(
    monkeypatch,
) -> None:
    """Hostile paths and cascades remain bounded and sanitized."""
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SEQUENCE", 0)
    nodeid = "tests/test_pytest_harness_v1.py::test_timeout_cascade"
    hostile_target = (
        "C:/private/secret.pdf?token=PRIVATE&payload="
        + ("x" * 100_000)
    )
    for _ in range(20):
        suite_conftest._record_local_api_timeout(
            nodeid=nodeid,
            method="TRACE PRIVATE",
            target=hostile_target,
            client_phase="not-a-phase",
            elapsed_seconds=999,
        )

    observations = suite_conftest._REQUEST_TIMEOUT_OBSERVATIONS[nodeid]
    assert len(observations) == 8
    assert all(item["method"] == "OTHER" for item in observations)
    assert all(item["route_family"] == "LOCAL_API_OTHER" for item in observations)
    assert all(item["client_phase"] == "CLIENT_UNKNOWN" for item in observations)
    assert all(item["elapsed_bucket"] == ">30s" for item in observations)
    assert all("PRIVATE" not in str(item) for item in observations)

    for index in range(200):
        suite_conftest._record_local_api_timeout(
            nodeid=f"tests/test_pytest_harness_v1.py::test_timeout_{index}",
            method="GET",
            target="/v1/recovery",
            client_phase="CLIENT_GETRESPONSE",
            elapsed_seconds=6,
        )
    assert len(suite_conftest._REQUEST_TIMEOUT_OBSERVATIONS) <= 128


def test_non_timeout_and_success_do_not_add_request_timeout_fields(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(suite_conftest, "_FAILURE_DIAGNOSTICS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    nodeid = "tests/test_pytest_harness_v1.py::test_non_timeout"
    suite_conftest._record_failure(
        SimpleNamespace(
            failed=True,
            nodeid=nodeid,
            when="call",
            longrepr=SimpleNamespace(
                reprcrash=SimpleNamespace(
                    path="C:/outside/private.py",
                    lineno=1,
                    message="RuntimeError: private detail",
                )
            ),
        ),
        "RuntimeError",
    )
    suite_conftest._emit_failure_diagnostics()
    diagnostic = capsys.readouterr().err.splitlines()[-1]
    assert "request_seq" not in diagnostic
    assert suite_conftest._REQUEST_TIMEOUT_OBSERVATIONS == {}


def test_worker_thread_timeout_uses_active_test_node(monkeypatch) -> None:
    monkeypatch.setattr(suite_conftest, "_REQUEST_TIMEOUT_OBSERVATIONS", {})
    monkeypatch.setattr(suite_conftest, "_REQUEST_SEQUENCE", 0)
    nodeid = "tests/test_pytest_harness_v1.py::test_worker_timeout"
    monkeypatch.setattr(suite_conftest, "_ACTIVE_NODEID", nodeid)

    worker = Thread(
        target=suite_conftest._record_local_api_timeout,
        kwargs={
            "method": "GET",
            "target": "/v1/recovery",
            "client_phase": "CLIENT_READ",
            "elapsed_seconds": 5.5,
        },
    )
    worker.start()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert suite_conftest._REQUEST_TIMEOUT_OBSERVATIONS[nodeid][0]["route_family"] == (
        "RECOVERY_LIST"
    )


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


@pytest.mark.parametrize("alias", ("referencias./privadas", "referencias/privadas."))
def test_private_windows_alias_is_redacted_before_filesystem_access(
    monkeypatch, tmp_path, alias,
) -> None:
    # Entirely synthetic root: never access the repository's private directory.
    private = tmp_path / "referencias" / "privadas"
    private.mkdir(parents=True)
    (private / "SYNTHETIC.py").write_text("# synthetic\n", encoding="utf-8")
    monkeypatch.setattr(suite_conftest, "_REPOSITORY_ROOT", tmp_path)

    assert suite_conftest._repository_location(
        f"{alias}/SYNTHETIC.py", 1,
    ) == "<outside-repository>:1"


def test_diagnostic_path_gate_does_not_probe_non_source_roots(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(suite_conftest, "_REPOSITORY_ROOT", tmp_path)

    def forbidden_probe(_path):
        raise AssertionError("non-source path must be rejected before filesystem access")

    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(Path, "is_symlink", forbidden_probe)
        for path in (
            "referencias/privadas/SYNTHETIC.py",
            "REFER~1/PRIVAD~1/SYNTHETIC.py",
            "referencias./privadas/SYNTHETIC.py",
            ".git/SYNTHETIC.py",
        ):
            assert suite_conftest._repository_location(path, 1) == "<outside-repository>:1"


def test_diagnostic_field_bounds_include_path_fallback_and_line_suffix(monkeypatch):
    with monkeypatch.context() as scoped_patch:
        scoped_patch.setattr(
            suite_conftest, "_repository_owned_file",
            lambda *_args, **_kwargs: Path("tests/" + "a" * 510 + ".py"),
        )
        assert len(suite_conftest._sanitized_nodeid("tests/test.py::test_probe")) <= 512
        scoped_patch.setattr(
            suite_conftest, "_repository_owned_file",
            lambda *_args, **_kwargs: Path("tests/" + "a" * 500 + ".py"),
        )
        assert len(suite_conftest._repository_location("unused", 10_000_000)) <= 512


def test_diagnostic_path_gate_preserves_source_locations_and_rejects_aliases():
    assert suite_conftest._repository_location(
        "scripts/quality/verify_core.py", 1,
    ) == "scripts/quality/verify_core.py:1"
    assert suite_conftest._repository_location(
        "scripts./quality/verify_core.py", 1,
    ) == "<outside-repository>:1"
