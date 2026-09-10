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
from contextvars import ContextVar
from threading import Lock

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
_REQUEST_TIMEOUT_OBSERVATIONS: dict[str, list[dict[str, str]]] = {}
_REQUEST_TIMEOUT_NODE_LIMIT = 128
_REQUEST_SERVER_PHASES: dict[str, list[str]] = {}
_REQUEST_SERVER_PHASE_LIMIT = 128
_REQUEST_INTERNAL_PHASES: dict[str, list[str]] = {}
_REQUEST_INTERNAL_PHASE_LIMIT = 128
_ACTIVE_REQUEST_SEQUENCES: set[str] = set()
_ACTIVE_REQUEST_SEQUENCE_LIMIT = 128
_REQUEST_SEQUENCE = 0
_REQUEST_TRACE_LOCK = Lock()
_ACTIVE_REQUEST_SEQUENCE: ContextVar[str | None] = ContextVar(
    "first_party_active_request_sequence", default=None
)
_CURRENT_NODEID: ContextVar[str | None] = ContextVar(
    "current_pytest_nodeid", default=None,
)
_ACTIVE_NODEID: str | None = None
_SAFE_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_SAFE_CLIENT_PHASES = {
    "CLIENT_CONNECT",
    "CLIENT_SEND",
    "CLIENT_GETRESPONSE",
    "CLIENT_READ",
}
_SAFE_SERVER_PHASES = {
    "LOCAL_API_HANDLE_STARTED",
    "LOCAL_API_HANDLE_COMPLETED",
    "RESPONSE_HEADERS_STARTED",
    "RESPONSE_COMPLETED",
}
_SAFE_INTERNAL_PHASES = {
    "ROUTE_DISPATCH_STARTED",
    "APPLICATION_COMMAND_STARTED",
    "APPLICATION_COMMAND_COMPLETED",
    "ROUTE_HANDLER_COMPLETED",
}
_SAFE_REQUEST_SEQUENCE = re.compile(r"^[1-9][0-9]{0,7}$")


def _safe_method(raw_method: object) -> str:
    method = raw_method.upper() if isinstance(raw_method, str) else ""
    return method if method in _SAFE_METHODS else "OTHER"


def _safe_route_family(raw_method: object, raw_target: object) -> str:
    method = _safe_method(raw_method)
    if not isinstance(raw_target, str):
        return "LOCAL_API_OTHER"
    path = raw_target.split("?", 1)[0].split("#", 1)[0]
    parts = tuple(part for part in path.split("/") if part)
    if not parts or parts[0] != "v1":
        return "LOCAL_API_OTHER"
    if parts == ("v1", "recovery") and method == "GET":
        return "RECOVERY_LIST"
    if parts == ("v1", "recovery", "staging") and method == "POST":
        return "RECOVERY_STAGE"
    if parts == ("v1", "recovery", "verify") and method == "POST":
        return "RECOVERY_VERIFY"
    if len(parts) == 4 and parts[:2] == ("v1", "recovery") and method == "POST":
        return {
            "promote": "RECOVERY_PROMOTE",
            "discard": "RECOVERY_DISCARD",
            "abandon": "RECOVERY_ABANDON",
        }.get(parts[3], "RECOVERY_OTHER")
    if parts == ("v1", "workspaces"):
        return "WORKSPACE_LIST" if method == "GET" else "WORKSPACE_CREATE" if method == "POST" else "WORKSPACE_OTHER"
    if len(parts) == 3 and parts[:2] == ("v1", "workspaces"):
        return "WORKSPACE_REOPEN" if method == "GET" else "WORKSPACE_OTHER"
    if len(parts) == 4 and parts[:2] == ("v1", "workspaces"):
        return {
            "materials": "WORKSPACE_MATERIALS",
            "backup": "BACKUP_CREATE",
        }.get(parts[3], "WORKSPACE_OTHER")
    return "LOCAL_API_OTHER"


def _elapsed_bucket(elapsed_seconds: object) -> str:
    try:
        elapsed = float(elapsed_seconds)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if elapsed <= 1:
        return "<=1s"
    if elapsed <= 5:
        return ">1s"
    if elapsed <= 30:
        return ">5s"
    return ">30s"


def _begin_local_api_request() -> str:
    """Allocate one bounded synthetic sequence for client/server correlation."""

    global _REQUEST_SEQUENCE
    with _REQUEST_TRACE_LOCK:
        _REQUEST_SEQUENCE += 1
        request_seq = str(_REQUEST_SEQUENCE)
        _activate_request_sequence(request_seq)
        return request_seq


def _activate_request_sequence(request_seq: str) -> None:
    if request_seq not in _ACTIVE_REQUEST_SEQUENCES:
        if len(_ACTIVE_REQUEST_SEQUENCES) >= _ACTIVE_REQUEST_SEQUENCE_LIMIT:
            _ACTIVE_REQUEST_SEQUENCES.pop()
        _ACTIVE_REQUEST_SEQUENCES.add(request_seq)


def _record_server_phase(*, request_seq: object, phase: object) -> None:
    if not isinstance(request_seq, str) or _SAFE_REQUEST_SEQUENCE.fullmatch(request_seq) is None:
        return
    if phase not in _SAFE_SERVER_PHASES:
        return
    with _REQUEST_TRACE_LOCK:
        if request_seq not in _ACTIVE_REQUEST_SEQUENCES:
            return
        if (
            request_seq not in _REQUEST_SERVER_PHASES
            and len(_REQUEST_SERVER_PHASES) >= _REQUEST_SERVER_PHASE_LIMIT
        ):
            return
        phases = _REQUEST_SERVER_PHASES.setdefault(request_seq, [])
        if len(phases) < len(_SAFE_SERVER_PHASES):
            phases.append(phase)


def _finish_local_api_request(request_seq: object, *, retain: bool) -> None:
    if retain or not isinstance(request_seq, str):
        return
    with _REQUEST_TRACE_LOCK:
        _REQUEST_SERVER_PHASES.pop(request_seq, None)
        _REQUEST_INTERNAL_PHASES.pop(request_seq, None)
        if not retain:
            _ACTIVE_REQUEST_SEQUENCES.discard(request_seq)


def _record_internal_phase(*, request_seq: object, phase: object) -> None:
    if not isinstance(request_seq, str) or _SAFE_REQUEST_SEQUENCE.fullmatch(request_seq) is None:
        return
    if phase not in _SAFE_INTERNAL_PHASES:
        return
    with _REQUEST_TRACE_LOCK:
        if request_seq not in _ACTIVE_REQUEST_SEQUENCES:
            return
        if (
            request_seq not in _REQUEST_INTERNAL_PHASES
            and len(_REQUEST_INTERNAL_PHASES) >= _REQUEST_INTERNAL_PHASE_LIMIT
        ):
            return
        phases = _REQUEST_INTERNAL_PHASES.setdefault(request_seq, [])
        if phase not in phases and len(phases) < len(_SAFE_INTERNAL_PHASES):
            phases.append(phase)


def _record_local_api_timeout(
    *,
    nodeid: str | None = None,
    method: object,
    target: object,
    client_phase: object,
    elapsed_seconds: object,
    request_seq: str | None = None,
) -> None:
    """Retain bounded, sanitized metadata for one local API timeout."""

    raw_nodeid = nodeid or _CURRENT_NODEID.get() or _ACTIVE_NODEID or "<unknown>"
    phase = client_phase if client_phase in _SAFE_CLIENT_PHASES else "CLIENT_UNKNOWN"
    with _REQUEST_TRACE_LOCK:
        if (
            not isinstance(request_seq, str)
            or _SAFE_REQUEST_SEQUENCE.fullmatch(request_seq) is None
        ):
            global _REQUEST_SEQUENCE
            _REQUEST_SEQUENCE += 1
            request_seq = str(_REQUEST_SEQUENCE)
        _activate_request_sequence(request_seq)
        observation = {
            "request_seq": request_seq,
            "method": _safe_method(method),
            "route_family": _safe_route_family(method, target),
            "client_phase": phase,
            "elapsed_bucket": _elapsed_bucket(elapsed_seconds),
            "timeout_boundary": "CLIENT_TRANSPORT_DEADLINE",
            "server_last_phase_at_timeout": (
                _REQUEST_SERVER_PHASES.get(request_seq, [])[-1]
                if _REQUEST_SERVER_PHASES.get(request_seq)
                else "UNKNOWN"
            ),
            "internal_last_phase_at_timeout": (
                _REQUEST_INTERNAL_PHASES.get(request_seq, [])[-1]
                if _REQUEST_INTERNAL_PHASES.get(request_seq)
                else "UNKNOWN"
            ),
        }
        if (
            raw_nodeid not in _REQUEST_TIMEOUT_OBSERVATIONS
            and len(_REQUEST_TIMEOUT_OBSERVATIONS) >= _REQUEST_TIMEOUT_NODE_LIMIT
        ):
            return
        observations = _REQUEST_TIMEOUT_OBSERVATIONS.setdefault(raw_nodeid, [])
        if len(observations) >= 8:
            observations.pop(0)
        observations.append(observation)


def _request_timeout_observation(nodeid: object) -> dict[str, str] | None:
    if not isinstance(nodeid, str):
        return None
    observations = _REQUEST_TIMEOUT_OBSERVATIONS.get(nodeid)
    if not observations:
        return None
    observation = dict(observations[-1])
    phases = _REQUEST_SERVER_PHASES.get(observation["request_seq"], [])
    observation["server_last_phase_observed_later"] = (
        phases[-1] if phases else "UNKNOWN"
    )
    observation["server_last_phase"] = observation["server_last_phase_observed_later"]
    internal_phases = _REQUEST_INTERNAL_PHASES.get(observation["request_seq"], [])
    observation["internal_last_phase_observed_later"] = (
        internal_phases[-1] if internal_phases else "UNKNOWN"
    )
    observation["internal_last_phase"] = observation[
        "internal_last_phase_observed_later"
    ]
    return observation


def _headers_request_sequence(headers: object) -> str | None:
    raw_sequence = (
        headers.get("X-First-Party-Test-Request-Seq")
        if hasattr(headers, "get")
        else None
    )
    if (
        not isinstance(raw_sequence, str)
        or _SAFE_REQUEST_SEQUENCE.fullmatch(raw_sequence) is None
    ):
        return None
    return raw_sequence


def _server_request_sequence(handler: object) -> str | None:
    return _headers_request_sequence(getattr(handler, "headers", None))


def _record_handler_phase(handler: object, phase: str) -> None:
    request_seq = _server_request_sequence(handler)
    if request_seq is not None:
        _record_server_phase(request_seq=request_seq, phase=phase)


def _install_server_phase_observer() -> None:
    """Wrap only test-created Local API handlers; production code is untouched."""

    try:
        from scripts.backend_contract.local_api import server as local_api_server
    except ModuleNotFoundError:
        # Isolated subprocess probes load this plugin with only the test
        # directory on PYTHONPATH. Client diagnostics remain useful there;
        # server-phase observation is optional when production modules are not
        # importable.
        return

    original_factory = local_api_server._handler_for
    if getattr(original_factory, "_first_party_phase_observer", False):
        return

    def observed_factory(*args: object, **kwargs: object):
        base_handler = original_factory(*args, **kwargs)
        api = args[0] if args else None
        if api is not None:
            _install_internal_phase_observer(api)

        class ObservedHandler(base_handler):
            def _handle_request(self):
                _record_handler_phase(self, "LOCAL_API_HANDLE_STARTED")
                response = super()._handle_request()
                _record_handler_phase(self, "LOCAL_API_HANDLE_COMPLETED")
                return response

            def send_response_only(self, *response_args, **response_kwargs):
                result = super().send_response_only(*response_args, **response_kwargs)
                _record_handler_phase(self, "RESPONSE_HEADERS_STARTED")
                return result

            def _write_response(self, response):
                result = super()._write_response(response)
                _record_handler_phase(self, "RESPONSE_COMPLETED")
                return result

        for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            setattr(ObservedHandler, f"do_{method}", ObservedHandler._dispatch)
        return ObservedHandler

    observed_factory._first_party_phase_observer = True
    local_api_server._handler_for = observed_factory


def _install_internal_phase_observer(api: object) -> None:
    """Observe stable dispatch/command boundaries on test-created API objects."""

    if getattr(api, "_first_party_internal_phase_observer", False):
        return
    original_handle = getattr(api, "handle", None)
    services = getattr(api, "_services", None)
    if not callable(original_handle) or services is None:
        return

    def observed_handle(method, target, headers, body):
        request_seq = _headers_request_sequence(headers)
        token = _ACTIVE_REQUEST_SEQUENCE.set(request_seq)
        if request_seq is not None:
            _record_internal_phase(
                request_seq=request_seq,
                phase="ROUTE_DISPATCH_STARTED",
            )
        try:
            response = original_handle(method, target, headers, body)
            if request_seq is not None:
                _record_internal_phase(
                    request_seq=request_seq,
                    phase="ROUTE_HANDLER_COMPLETED",
                )
            return response
        finally:
            _ACTIVE_REQUEST_SEQUENCE.reset(token)

    try:
        setattr(api, "handle", observed_handle)
        setattr(api, "_first_party_internal_phase_observer", True)
    except (AttributeError, TypeError):
        return

    for field_name in getattr(services, "__dataclass_fields__", {}):
        service = getattr(services, field_name, None)
        service_type = type(service) if service is not None else None
        type_execute = getattr(service_type, "execute", None)
        if not callable(type_execute) or getattr(
            service_type, "_first_party_phase_observer", False
        ):
            continue

        def observed_execute(self, *args, _execute=type_execute, **kwargs):
            request_seq = _ACTIVE_REQUEST_SEQUENCE.get()
            should_record = request_seq is not None and not (
                request_seq in _REQUEST_INTERNAL_PHASES
                and "APPLICATION_COMMAND_STARTED" in _REQUEST_INTERNAL_PHASES[request_seq]
            )
            if should_record:
                _record_internal_phase(
                    request_seq=request_seq,
                    phase="APPLICATION_COMMAND_STARTED",
                )
            result = _execute(self, *args, **kwargs)
            if should_record:
                _record_internal_phase(
                    request_seq=request_seq,
                    phase="APPLICATION_COMMAND_COMPLETED",
                )
            return result

        try:
            setattr(service_type, "execute", observed_execute)
            setattr(service_type, "_first_party_phase_observer", True)
        except (AttributeError, TypeError):
            continue


_install_server_phase_observer()


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
    timeout_observation = _request_timeout_observation(raw_nodeid)
    if timeout_observation is not None and diagnostic["exception_type"] == "TimeoutError":
        diagnostic.update(timeout_observation)
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


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: object, nextitem: object):
    """Associate local API observations with the running test node."""

    global _ACTIVE_NODEID
    current_nodeid = getattr(item, "nodeid", None)
    token = _CURRENT_NODEID.set(current_nodeid)
    with _REQUEST_TRACE_LOCK:
        previous_nodeid = _ACTIVE_NODEID
        _ACTIVE_NODEID = current_nodeid
    try:
        yield
    finally:
        with _REQUEST_TRACE_LOCK:
            _ACTIVE_NODEID = previous_nodeid
        _CURRENT_NODEID.reset(token)


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
