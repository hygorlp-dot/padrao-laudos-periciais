from __future__ import annotations

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
