"""Fail-closed exact baseline exception matching for capability findings."""
from __future__ import annotations

import hashlib
import json
import subprocess
import ast
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import jsonschema

from scripts.quality.ast_inventory import module_name


WORD_RENDER_OPERATION = "RENDER_BOUND_AUTHORITATIVE_WORD_TO_DERIVED_PDF"
WORD_PARENT_PATH = "scripts/backend_contract/infrastructure/office_pdf.py"
WORD_WORKER_PATH = "scripts/backend_contract/infrastructure/office_word_worker.py"
_WORD_PRODUCT_PATHS = {WORD_PARENT_PATH, WORD_WORKER_PATH}
_WORD_PRODUCT_SHA256 = {
    WORD_PARENT_PATH: "0752949efd38fe08220d54828f73573223109f791ed4cd63772da95695f8058d",
    WORD_WORKER_PATH: "891c8811e84461dec50ac85a5649e49919093b36070404b6ae69ac9d0e6b4efa",
}
_FORBIDDEN_WORD_IMPORTS = {"_winapi", "ctypes", "multiprocessing", "subprocess"}
_FORBIDDEN_WORD_FUNCTIONS = {
    "execute",
    "execute_command",
    "invoke",
    "invoke_com",
    "run",
    "run_command",
}


def _chain(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return tuple(reversed(parts))


def _same_expression(node: ast.AST, source: str) -> bool:
    expected = ast.parse(source, mode="eval").body
    return ast.dump(node, include_attributes=False) == ast.dump(
        expected, include_attributes=False
    )


def _named_assignments(tree: ast.AST, name: str) -> list[ast.AST]:
    values: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name for target in targets):
                values.append(node.value)
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                values.append(node.value)
    return values


def _single_function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _calls(tree: ast.AST, final_name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (chain := _chain(node.func)) is not None
        and chain[-1] == final_name
    ]


def _keyword_map(call: ast.Call) -> dict[str, ast.AST] | None:
    if any(keyword.arg is None for keyword in call.keywords):
        return None
    values = {keyword.arg: keyword.value for keyword in call.keywords}
    return values if len(values) == len(call.keywords) else None


def _constant(node: ast.AST, value: object) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) is type(value) and node.value == value


def _fixed_keyword_contract(
    call: ast.Call,
    expected: Mapping[str, object],
    *,
    dynamic: set[str],
) -> bool:
    keywords = _keyword_map(call)
    if keywords is None or set(keywords) != set(expected) | dynamic:
        return False
    return all(_constant(keywords[name], value) for name, value in expected.items())


def _imports_are_closed(trees: Mapping[str, ast.AST]) -> bool:
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in _FORBIDDEN_WORD_IMPORTS:
                        return False
                    if alias.name.startswith(("win32", "pythoncom")) and alias.asname is not None:
                        return False
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".", 1)[0] in _FORBIDDEN_WORD_IMPORTS:
                    return False
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.casefold() in _FORBIDDEN_WORD_FUNCTIONS:
                    return False
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"compile", "eval", "exec", "__import__"}:
                    return False
                if (
                    node.func.id == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and str(node.args[1].value).casefold()
                    in {"createprocess", "dispatch", "dispatchex", "ensuredispatch"}
                ):
                    return False
    return True


def _parent_word_process_contract_is_closed(tree: ast.AST) -> bool:
    start = _single_function(tree, "_start_owned_word_worker")
    if start is None:
        return False
    executable = _named_assignments(start, "executable")
    worker_script = _named_assignments(start, "worker_script")
    command_line = _named_assignments(start, "command_line")
    if (
        len(executable) != 1
        or not _same_expression(executable[0], "str(Path(sys.executable).resolve(strict=True))")
        or len(worker_script) != 1
        or not _same_expression(
            worker_script[0],
            'str(Path(__file__).with_name("office_word_worker.py").resolve(strict=True))',
        )
        or len(command_line) != 1
        or not _same_expression(
            command_line[0],
            '" ".join(_quote_windows_argument(value) for value in '
            '(executable, "-I", worker_script, str(root.resolve(strict=True))))',
        )
    ):
        return False

    create_calls = _calls(tree, "CreateProcess")
    if len(create_calls) != 1:
        return False
    call = create_calls[0]
    if _chain(call.func) != ("win32process", "CreateProcess") or call.keywords or len(call.args) != 9:
        return False
    if not (
        _same_expression(call.args[0], "executable")
        and _same_expression(call.args[1], "command_line")
        and _constant(call.args[2], None)
        and _constant(call.args[3], None)
        and _constant(call.args[4], False)
        and _same_expression(
            call.args[5], "win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW"
        )
        and _same_expression(
            call.args[6],
            "_controlled_worker_environment(root, job_name=job_name, instance_token=instance_token)",
        )
        and _same_expression(call.args[7], "str(Path(__file__).resolve().parents[3])")
        and _same_expression(call.args[8], "startup")
    ):
        return False

    required = {
        ("win32job", "CreateJobObject"),
        ("win32job", "SetInformationJobObject"),
        ("win32job", "AssignProcessToJobObject"),
        ("win32process", "ResumeThread"),
    }
    positions: dict[tuple[str, ...], int] = {}
    for node in ast.walk(start):
        if isinstance(node, ast.Call) and (chain := _chain(node.func)) in required:
            if chain in positions:
                return False
            positions[chain] = node.lineno
    if set(positions) != required:
        return False
    return (
        positions[("win32job", "CreateJobObject")]
        < positions[("win32job", "SetInformationJobObject")]
        < call.lineno
        < positions[("win32job", "AssignProcessToJobObject")]
        < positions[("win32process", "ResumeThread")]
    )


def _worker_com_contract_is_closed(tree: ast.AST) -> bool:
    clsids = _named_assignments(tree, "_WORD_CLSID")
    operations = _named_assignments(tree, "RENDER_OPERATION")
    if (
        len(clsids) != 1
        or not _constant(clsids[0], "{000209FF-0000-0000-C000-000000000046}")
        or len(operations) != 1
        or not _constant(operations[0], WORD_RENDER_OPERATION)
    ):
        return False

    machine_path = _single_function(tree, "_machine_word_executable")
    launch = _single_function(tree, "_start_owned_word_process")
    binder = _single_function(tree, "_bind_owned_word_com_object")
    if machine_path is None or launch is None or binder is None:
        return False
    machine_source = ast.unparse(machine_path)
    if (
        "winreg.HKEY_LOCAL_MACHINE" not in machine_source
        or "Word.Application" not in machine_source
        or "LocalServer32" not in machine_source
        or "winword.exe" not in machine_source.casefold()
        or "HKEY_CURRENT_USER" in machine_source
    ):
        return False

    word_executable = _named_assignments(launch, "word_executable")
    command_line = _named_assignments(launch, "command_line")
    if (
        len(word_executable) != 1
        or not _same_expression(word_executable[0], "str(_machine_word_executable())")
        or len(command_line) != 1
        or not _same_expression(
            command_line[0],
            '" ".join((_quote_windows_argument(word_executable), "/x", "/q", '
            "_quote_windows_argument(str(bootstrap))))",
        )
    ):
        return False
    create_calls = _calls(launch, "CreateProcess")
    all_worker_create_calls = _calls(tree, "CreateProcess")
    if len(create_calls) != 1 or all_worker_create_calls != create_calls:
        return False
    create = create_calls[0]
    if (
        _chain(create.func) != ("win32process", "CreateProcess")
        or create.keywords
        or len(create.args) != 9
        or not _same_expression(create.args[0], "word_executable")
        or not _same_expression(create.args[1], "command_line")
        or not _constant(create.args[2], None)
        or not _constant(create.args[3], None)
        or not _constant(create.args[4], False)
        or not _same_expression(
            create.args[5], "win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW"
        )
        or not _constant(create.args[6], None)
        or not _same_expression(create.args[7], "str(root)")
        or not _same_expression(create.args[8], "startup")
    ):
        return False
    resume = _calls(launch, "ResumeThread")
    membership = _calls(launch, "IsProcessInJob")
    if (
        len(resume) != 1
        or _chain(resume[0].func) != ("win32process", "ResumeThread")
        or len(membership) != 2
        or not any(
            call.lineno < create.lineno
            and _same_expression(call.args[0], "win32api.GetCurrentProcess()")
            for call in membership
            if len(call.args) == 2
        )
        or not any(
            create.lineno < call.lineno < resume[0].lineno
            and _same_expression(call.args[0], "process")
            for call in membership
            if len(call.args) == 2
        )
    ):
        return False

    dispatch_calls = _calls(tree, "Dispatch")
    if (
        len(dispatch_calls) != 1
        or _chain(dispatch_calls[0].func) != ("win32com", "client", "Dispatch")
        or dispatch_calls[0].keywords
        or len(dispatch_calls[0].args) != 1
        or not _same_expression(
            dispatch_calls[0].args[0],
            "unknown.QueryInterface(pythoncom.IID_IDispatch)",
        )
        or _calls(tree, "DispatchEx")
        or _calls(tree, "EnsureDispatch")
        or len(_calls(binder, "GetRunningObjectTable")) != 1
        or len(_calls(binder, "GetObject")) != 1
    ):
        return False

    render = _single_function(tree, "_render_job")
    if render is None:
        return False
    bindings = [
        node
        for node in ast.walk(render)
        if isinstance(node, ast.Call) and _chain(node.func) == ("com_binder",)
    ]
    opens = [
        node
        for node in ast.walk(render)
        if isinstance(node, ast.Call) and _chain(node.func) == ("app", "Documents", "Open")
    ]
    exports = [
        node
        for node in ast.walk(render)
        if isinstance(node, ast.Call) and _chain(node.func) == ("document", "ExportAsFixedFormat")
    ]
    closes = [
        node
        for node in ast.walk(render)
        if isinstance(node, ast.Call) and _chain(node.func) == ("document", "Close")
    ]
    quits = [
        node
        for node in ast.walk(render)
        if isinstance(node, ast.Call) and _chain(node.func) == ("app", "Quit")
    ]
    launchers = [
        node
        for node in ast.walk(render)
        if isinstance(node, ast.Call) and _chain(node.func) == ("word_launcher",)
    ]
    automation = [
        node
        for node in ast.walk(render)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            _chain(target) == ("app", "AutomationSecurity")
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        )
    ]
    if not all(len(nodes) == 1 for nodes in (bindings, opens, exports, launchers, automation)):
        return False
    if not closes or not quits or not _constant(automation[0].value, 3):
        return False
    if not (
        launchers[0].lineno
        < bindings[0].lineno
        < automation[0].lineno
        < opens[0].lineno
        < exports[0].lineno
    ):
        return False
    if not _fixed_keyword_contract(
        opens[0],
        {
            "ConfirmConversions": False,
            "ReadOnly": True,
            "AddToRecentFiles": False,
            "OpenAndRepair": False,
            "NoEncodingDialog": True,
        },
        dynamic={"FileName"},
    ):
        return False
    if not _fixed_keyword_contract(
        exports[0],
        {
            "ExportFormat": 17,
            "OpenAfterExport": False,
            "OptimizeFor": 0,
            "Range": 0,
            "Item": 0,
            "IncludeDocProps": True,
            "CreateBookmarks": 0,
            "DocStructureTags": True,
            "BitmapMissingFonts": True,
            "UseISO19005_1": False,
        },
        dynamic={"OutputFileName"},
    ):
        return False
    if any(
        not _fixed_keyword_contract(call, {"SaveChanges": 0}, dynamic=set())
        for call in (*closes, *quits)
    ):
        return False

    return True


def _word_render_digests_are_closed(digests: Mapping[str, str]) -> bool:
    return (
        set(digests) == _WORD_PRODUCT_PATHS
        and all(type(value) is str for value in digests.values())
        and dict(digests) == _WORD_PRODUCT_SHA256
    )


def word_render_sources_are_closed(sources: Mapping[str, str]) -> bool:
    """Fail closed unless both product sources are the pre-reviewed exact bytes."""
    try:
        if set(sources) != _WORD_PRODUCT_PATHS or any(
            not isinstance(source, str) for source in sources.values()
        ):
            return False
        return _word_render_digests_are_closed(
            {
                path: hashlib.sha256(sources[path].encode("utf-8")).hexdigest()
                for path in _WORD_PRODUCT_PATHS
            }
        )
    except (AttributeError, TypeError, UnicodeError, ValueError):
        return False


def _git(repo: Path, *args: str, text: bool = True):
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=text)
    if completed.returncode:
        raise RuntimeError("Git object unavailable")
    return completed.stdout


def _key_from_finding(item: dict) -> tuple:
    return (
        item.get("code"), item.get("canonicalPath"), item.get("module"),
        item.get("location", {}).get("line"), item.get("location", {}).get("column"),
        item.get("normalizedAstSha256"), item.get("policyVersion"), item.get("analyzer"),
    )


def _key_from_exception(item: dict) -> tuple:
    return (
        item.get("findingCode"), item.get("canonicalPath"), item.get("module"),
        item.get("acquisitionLocation", {}).get("line"), item.get("acquisitionLocation", {}).get("column"),
        item.get("normalizedAcquisitionAstSha256"), item.get("policyVersion"),
        "CAPABILITY_ANALYZER_V1" if item.get("analyzerVersion") == "1.0.0" else None,
    )


def _validated_exception_key(item: object, finding_keys: set[tuple], schema: dict, now: date) -> tuple | None:
    """Return the exact finding key only for a valid, current exception contract."""
    try:
        if not isinstance(item, dict):
            return None
        jsonschema.validate(item, schema)
        key = _key_from_exception(item)
        if key not in finding_keys or item["ruleVersion"] != "1.0.0":
            return None
        if module_name(item["canonicalPath"]) != item["module"]:
            return None
        if date.fromisoformat(item["reviewBy"]) < now:
            return None
        return key
    except (ValueError, TypeError, KeyError, jsonschema.ValidationError, jsonschema.SchemaError):
        return None


def apply_exact_exceptions(
    repo: Path,
    findings: list[dict],
    protected_baseline: str,
    candidate: str,
    *,
    registry_path: str,
    schema_path: Path,
    now: date,
) -> list[dict]:
    """Suppress only exact findings authorized by an unchanged ancestor registry."""
    original = list(findings)
    try:
        if _git(repo, "merge-base", "--is-ancestor", protected_baseline, candidate).strip():
            return original
        baseline_raw = _git(repo, "show", f"{protected_baseline}:{registry_path}")
        candidate_raw = _git(repo, "show", f"{candidate}:{registry_path}")
        if baseline_raw != candidate_raw:
            return original
        registry = json.loads(baseline_raw)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(registry, dict) or set(registry) != {"schemaVersion", "exceptions"}:
            return original
        if registry.get("schemaVersion") != "1.0.0" or not isinstance(registry.get("exceptions"), list):
            return original
        rows = registry["exceptions"]
        keys = [_key_from_exception(row) for row in rows if isinstance(row, dict)]
        if len(keys) != len(rows) or len(keys) != len(set(keys)):
            return original
        finding_keys = {_key_from_finding(item) for item in original}
        approved: set[tuple] = set()
        for row in rows:
            key = _validated_exception_key(row, finding_keys, schema, now)
            if key is None:
                return original
            source_commit = row["baselineCommit"]
            if _git(repo, "merge-base", "--is-ancestor", source_commit, protected_baseline).strip():
                return original
            baseline_blob = _git(repo, "show", f"{source_commit}:{row['canonicalPath']}", text=False)
            candidate_blob = _git(repo, "show", f"{candidate}:{row['canonicalPath']}", text=False)
            if baseline_blob != candidate_blob or hashlib.sha256(candidate_blob).hexdigest() != row["wholeFileSha256"]:
                return original
            approved.add(key)
        return [item for item in original if _key_from_finding(item) not in approved]
    except (
        OSError, RuntimeError, UnicodeError, ValueError, TypeError, KeyError,
        json.JSONDecodeError, jsonschema.ValidationError, jsonschema.SchemaError,
    ):
        return original
