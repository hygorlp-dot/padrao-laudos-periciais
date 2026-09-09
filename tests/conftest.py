"""Configuração comum da suíte.

O único ajuste aqui é de HARNESS, não de produto: as propriedades Hypothesis
deste repositório são puras e em memória, então o prazo de parede padrão (200 ms
por exemplo) não mede invariante nenhuma — só mede quanta CPU o resto da suíte
está consumindo no momento. Mantê-lo transformava a suíte em fonte de falhas
intermitentes sem significado de produto. O número de exemplos permanece o
padrão: nada de cobertura é abdicado.
"""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sys

from hypothesis import HealthCheck, settings
import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_FAILURE_DIAGNOSTICS: dict[tuple[str, str, str], dict[str, str]] = {}
_FAILURE_DIAGNOSTIC_LIMIT = 128
_MAX_DIAGNOSTIC_FIELD_LENGTH = 512
_MAX_DIAGNOSTIC_LINE_NUMBER = 10_000_000
_SAFE_EXCEPTION_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,79}$")
_SAFE_NODE_SCOPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_WINDOWS_ERROR_CODE = re.compile(r"\[WinError ([0-9]{1,10})\]")
_POSIX_ERROR_CODE = re.compile(r"\[Errno ([0-9]{1,10})\]")
_DIAGNOSTIC_LIMIT_KEY = ("<diagnostic-limit-reached>", "unknown", "limit")
_DIAGNOSTIC_LIMIT_RECORD = {
    "exception_type": "DiagnosticLimit",
    "location": "<not-applicable>",
    "message": "additional_failures_redacted",
    "nodeid": "<diagnostic-limit-reached>",
    "phase": "unknown",
}


def _repository_owned_file(
    raw_path: object,
    *,
    require_tests: bool = False,
) -> Path | None:
    if not isinstance(raw_path, (str, Path)):
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = _REPOSITORY_ROOT / candidate
    try:
        relative = candidate.relative_to(_REPOSITORY_ROOT)
    except ValueError:
        return None
    normalized_parts = tuple(part.casefold() for part in relative.parts)
    if (
        not normalized_parts
        or normalized_parts[0] not in {"tests", "scripts"}
        or ".." in normalized_parts
        or any(part != part.rstrip(" .") for part in normalized_parts)
        or (require_tests and normalized_parts[0] != "tests")
    ):
        return None
    current = _REPOSITORY_ROOT
    try:
        for part in relative.parts:
            current /= part
            if current.is_symlink() or (
                hasattr(current, "is_junction") and current.is_junction()
            ):
                return None
        if not current.is_file():
            return None
    except OSError:
        return None
    return relative


def _repository_location(raw_path: object, raw_line: object) -> str:
    location = "<outside-repository>"
    relative = _repository_owned_file(raw_path)
    if relative is not None:
        location = relative.as_posix()
    if (
        type(raw_line) is int
        and 0 < raw_line <= _MAX_DIAGNOSTIC_LINE_NUMBER
    ):
        location = f"{location}:{raw_line}"
    if len(location) > _MAX_DIAGNOSTIC_FIELD_LENGTH:
        return "<repository-path-redacted>"
    return location


def _safe_exception_type(raw_type: object) -> str:
    candidate = raw_type if type(raw_type) is str else ""
    return candidate if _SAFE_EXCEPTION_TYPE.fullmatch(candidate) else "UnknownFailure"


def _sanitized_nodeid(raw_nodeid: object) -> str:
    """Keep only repository-owned test identity; parameter payload is untrusted."""

    if type(raw_nodeid) is not str or "::" not in raw_nodeid:
        return "<outside-repository>"
    raw_path, raw_scope = raw_nodeid.split("::", 1)
    normalized_path = raw_path.replace("\\", "/")
    relative = _repository_owned_file(normalized_path, require_tests=True)
    if relative is None:
        return "<outside-repository>"
    scope, has_parameters, _parameters = raw_scope.partition("[")
    scope_parts = scope.split("::")
    if not scope_parts or any(
        _SAFE_NODE_SCOPE.fullmatch(part) is None for part in scope_parts
    ):
        return "<repository-node-redacted>"
    nodeid = f"{relative.as_posix()}::{'::'.join(scope_parts)}"
    if has_parameters:
        nodeid += "[parameters-redacted]"
    if len(nodeid) > _MAX_DIAGNOSTIC_FIELD_LENGTH:
        return "<repository-node-redacted>"
    return nodeid


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
    exception_type = _safe_exception_type(raw_exception_type)
    phase = getattr(report, "when", None)
    return {
        "exception_type": exception_type,
        "location": _repository_location(
            getattr(crash, "path", None),
            getattr(crash, "lineno", None),
        ),
        "message": _sanitized_message(exception_type, message),
        "nodeid": _sanitized_nodeid(getattr(report, "nodeid", None)),
        "phase": phase if phase in {"setup", "call", "teardown"} else "unknown",
    }


def _record_failure(report: object, raw_exception_type: object = None) -> None:
    raw_nodeid = getattr(report, "nodeid", None)
    if type(raw_nodeid) is not str or not raw_nodeid:
        return
    phase = getattr(report, "when", None)
    safe_phase = phase if phase in {"setup", "call", "teardown"} else "unknown"
    diagnostic = _failure_diagnostic(report, raw_exception_type)
    fingerprint = sha256(
        raw_nodeid.encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    key = (diagnostic["nodeid"], safe_phase, fingerprint)
    if key in _FAILURE_DIAGNOSTICS:
        return
    if len(_FAILURE_DIAGNOSTICS) >= _FAILURE_DIAGNOSTIC_LIMIT:
        _FAILURE_DIAGNOSTICS.setdefault(
            _DIAGNOSTIC_LIMIT_KEY,
            dict(_DIAGNOSTIC_LIMIT_RECORD),
        )
        return
    raw_scope = raw_nodeid.split("::", 1)[1] if "::" in raw_nodeid else ""
    if "[" in raw_scope:
        diagnostic["redacted_instance"] = str(
            1
            + sum(
                stored_nodeid == diagnostic["nodeid"]
                and stored_phase == safe_phase
                for stored_nodeid, stored_phase, _stored_fingerprint in (
                    _FAILURE_DIAGNOSTICS
                )
            )
        )
    _FAILURE_DIAGNOSTICS[key] = diagnostic


def _failure_diagnostic_line(
    diagnostics: dict[tuple[str, str, str], dict[str, str]],
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


def _emit_failure_diagnostics() -> None:
    if _FAILURE_DIAGNOSTICS:
        print(
            _failure_diagnostic_line(_FAILURE_DIAGNOSTICS),
            file=sys.stderr,
            flush=True,
        )


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_unconfigure(config: object):
    """Make sanitized failure metadata the last line captured by verify_core."""

    yield
    _emit_failure_diagnostics()


settings.register_profile(
    "pericial",
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("pericial")
