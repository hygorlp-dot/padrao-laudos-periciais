"""Configuração comum da suíte.

O único ajuste aqui é de HARNESS, não de produto: as propriedades Hypothesis
deste repositório são puras e em memória, então o prazo de parede padrão (200 ms
por exemplo) não mede invariante nenhuma — só mede quanta CPU o resto da suíte
está consumindo no momento. Mantê-lo transformava a suíte em fonte de falhas
intermitentes sem significado de produto. O número de exemplos permanece o
padrão: nada de cobertura é abdicado.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

from hypothesis import HealthCheck, settings
import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FAILURE_DIAGNOSTICS: dict[tuple[str, str], dict[str, str]] = {}
_SAFE_EXCEPTION_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,79}$")
_WINDOWS_ERROR_CODE = re.compile(r"\[WinError ([0-9]{1,10})\]")
_POSIX_ERROR_CODE = re.compile(r"\[Errno ([0-9]{1,10})\]")


def _repository_location(raw_path: object, raw_line: object) -> str:
    location = "<outside-repository>"
    if isinstance(raw_path, (str, Path)):
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = _REPOSITORY_ROOT / candidate
        try:
            location = candidate.resolve(strict=False).relative_to(
                _REPOSITORY_ROOT
            ).as_posix()
        except (OSError, ValueError):
            pass
    if type(raw_line) is int and raw_line > 0:
        return f"{location}:{raw_line}"
    return location


def _safe_exception_type(raw_type: object, message: object) -> str:
    candidate = raw_type if type(raw_type) is str else ""
    if not candidate and type(message) is str:
        candidate = message.split(":", 1)[0].strip()
    return candidate if _SAFE_EXCEPTION_TYPE.fullmatch(candidate) else "UnknownFailure"


def _sanitized_message(exception_type: str, message: object) -> str:
    if type(message) is not str:
        return "failure_details_unavailable"
    windows_code = _WINDOWS_ERROR_CODE.search(message)
    if windows_code is not None:
        return f"os_error:winerror={windows_code.group(1)}"
    posix_code = _POSIX_ERROR_CODE.search(message)
    if posix_code is not None:
        return f"os_error:errno={posix_code.group(1)}"
    if exception_type == "AssertionError":
        return "assertion_failed"
    return "exception_message_redacted"


def _failure_diagnostic(
    report: object,
    raw_exception_type: object = None,
) -> dict[str, str]:
    longrepr = getattr(report, "longrepr", None)
    crash = getattr(longrepr, "reprcrash", None)
    message = getattr(crash, "message", None)
    exception_type = _safe_exception_type(raw_exception_type, message)
    phase = getattr(report, "when", None)
    return {
        "exception_type": exception_type,
        "location": _repository_location(
            getattr(crash, "path", None),
            getattr(crash, "lineno", None),
        ),
        "message": _sanitized_message(exception_type, message),
        "nodeid": str(getattr(report, "nodeid", "")),
        "phase": phase if phase in {"setup", "call", "teardown"} else "unknown",
    }


def _record_failure(report: object, raw_exception_type: object = None) -> None:
    nodeid = getattr(report, "nodeid", None)
    if type(nodeid) is not str or not nodeid:
        return
    phase = getattr(report, "when", None)
    safe_phase = phase if phase in {"setup", "call", "teardown"} else "unknown"
    _FAILURE_DIAGNOSTICS.setdefault(
        (nodeid, safe_phase),
        _failure_diagnostic(report, raw_exception_type),
    )


def _failure_diagnostic_line(
    diagnostics: dict[tuple[str, str], dict[str, str]],
) -> str:
    payload = json.dumps(
        sorted(diagnostics.values(), key=lambda item: (item["nodeid"], item["phase"])),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"PYTEST_FAILURE_DIAGNOSTICS_V1={payload}"


def pytest_runtest_logreport(report: object) -> None:
    """Retain bounded failure metadata, never raw paths or failure payloads."""

    if getattr(report, "failed", False):
        _record_failure(report)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: object, call: object):
    """Capture the exception class from pytest authority, not display text."""

    outcome = yield
    report = outcome.get_result()
    if not getattr(report, "failed", False):
        return
    excinfo = getattr(call, "excinfo", None)
    exception_class = getattr(excinfo, "type", None)
    _record_failure(report, getattr(exception_class, "__name__", None))


def pytest_unconfigure(config: object) -> None:
    """Make sanitized failure metadata the last line captured by verify_core."""

    if _FAILURE_DIAGNOSTICS:
        print(
            _failure_diagnostic_line(_FAILURE_DIAGNOSTICS),
            file=sys.stderr,
            flush=True,
        )


settings.register_profile(
    "pericial",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("pericial")
