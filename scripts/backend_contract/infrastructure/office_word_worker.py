"""Purpose-specific, Job-contained Microsoft Word COM worker.

The worker itself is created by :mod:`office_pdf` inside a product-owned Job.
It launches the exact machine-scoped Microsoft Word executable as its child,
so Windows places Word in that Job atomically at process creation.  A synthetic
macro-free bootstrap DOCX yields an exact ROT moniker for that process; no
ProgID activation, arbitrary executable, command, or COM method is accepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Callable
import winreg
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


RENDER_OPERATION = "RENDER_BOUND_AUTHORITATIVE_WORD_TO_DERIVED_PDF"
_SCHEMA_VERSION = "1.0.0"
_WORD_CLSID = "{000209FF-0000-0000-C000-000000000046}"
_STATUS_PHASES = (
    "COM_INIT",
    "WORD_PROCESS_START",
    "WORD_COM_BIND",
    "DOCUMENT_OPEN",
    "EXPORT_AS_FIXED_FORMAT",
    "DOCUMENT_CLOSE",
    "WORD_QUIT",
    "WORKER_EXIT",
)
_STATUS_INDEX = {phase: index for index, phase in enumerate(_STATUS_PHASES, 1)}
_MAX_PACKAGE_PARTS = 4_096
_MAX_PACKAGE_BYTES = 256 * 1024 * 1024
_MAX_PART_BYTES = 64 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_SAFE_WORD_FIELD_CODES = frozenset({"NUMPAGES", "PAGE", "PAGEREF", "REF", "SEQ", "TOC"})
_ACQUIRING_WORD_FIELD_CODES = re.compile(
    r"\b(?:DATABASE|DDE|DDEAUTO|HYPERLINK|INCLUDEPICTURE|INCLUDETEXT|LINK)\b",
    re.IGNORECASE,
)
_ACQUIRING_RELATIONSHIP_TYPES = frozenset(
    {
        "afchunk",
        "attachedtemplate",
        "control",
        "controlproperty",
        "externallink",
        "oleobject",
        "package",
        "subdocument",
    }
)
_ACQUIRING_WORD_ELEMENTS = frozenset({"altChunk", "control", "object", "subDoc"})
_OPAQUE_ACTIVE_PART_PREFIXES = ("word/activex/", "word/embeddings/")
_IMPORTABLE_PART_SUFFIXES = (".htm", ".html", ".mht", ".mhtml", ".rtf")


def _xml_local_name(value: object) -> str:
    return value.rsplit("}", 1)[-1] if isinstance(value, str) else ""


def _xml_attribute(node: ElementTree.Element, name: str) -> str | None:
    values = [
        value
        for key, value in node.attrib.items()
        if _xml_local_name(key) == name
    ]
    return values[0] if len(values) == 1 else None


@dataclass(slots=True)
class _OwnedWordProcess:
    handle: object
    job: object
    pid: int
    creation_identity: str
    image_path: str

    def Close(self) -> None:
        try:
            self.handle.Close()
        finally:
            self.job.Close()


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def _status(root: Path, phase: str) -> None:
    """Publish an immutable marker whose validated name is the parent protocol."""
    index = _STATUS_INDEX.get(phase)
    if index is None:
        raise ValueError("invalid Word worker phase")
    path = root / f"status-{index:02d}-{phase}.json"
    if path.exists() or path.with_suffix(path.suffix + ".tmp").exists():
        raise RuntimeError("Word worker phase was already published")
    _atomic_json(
        path,
        {"schemaVersion": _SCHEMA_VERSION, "state": "RUNNING", "phase": phase},
    )


def _load_request(root: Path) -> dict:
    try:
        request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Word render request") from exc
    if (
        not isinstance(request, dict)
        or set(request) != {"schemaVersion", "operation", "sourceFormat"}
        or request.get("schemaVersion") != _SCHEMA_VERSION
        or request.get("operation") != RENDER_OPERATION
        or request.get("sourceFormat") not in {"DOCX", "DOCM"}
    ):
        raise ValueError("invalid Word render request")
    return request


def _quote_windows_argument(value: str) -> str:
    if not value or any(character in value for character in ("\x00", "\r", "\n")):
        raise RuntimeError("invalid owned Word argument")
    escaped: list[str] = ['"']
    backslashes = 0
    for character in value:
        if character == "\\":
            backslashes += 1
        elif character == '"':
            escaped.append("\\" * (backslashes * 2 + 1))
            escaped.append(character)
            backslashes = 0
        else:
            escaped.append("\\" * backslashes)
            escaped.append(character)
            backslashes = 0
    escaped.append("\\" * (backslashes * 2))
    escaped.append('"')
    return "".join(escaped)


def _owned_job_name() -> str:
    job_name = os.environ.get("PLP_WORD_JOB_NAME", "")
    if not re.fullmatch(r"Local\\PLP-Word-[0-9a-f]{32}", job_name):
        raise RuntimeError("invalid Word process ownership context")
    return job_name


def _registered_server_path(command: object) -> Path:
    if not isinstance(command, str) or not command or "%" in command:
        raise RuntimeError("invalid machine Word registration")
    value = command.strip()
    if value.startswith('"'):
        end = value.find('"', 1)
        if end < 2:
            raise RuntimeError("invalid machine Word registration")
        executable_text = value[1:end]
        remainder = value[end + 1 :].strip()
    else:
        marker = value.casefold().find(".exe")
        if marker < 1:
            raise RuntimeError("invalid machine Word registration")
        executable_text = value[: marker + 4].strip()
        remainder = value[marker + 4 :].strip()
    if remainder.casefold() not in {"", "/automation"}:
        raise RuntimeError("invalid machine Word registration arguments")
    if executable_text.startswith("\\\\") or not Path(executable_text).is_absolute():
        raise RuntimeError("machine Word executable must be a local absolute path")
    executable = Path(executable_text).resolve(strict=True)
    if (
        not executable.is_file()
        or executable.is_symlink()
        or executable.name.casefold() != "winword.exe"
    ):
        raise RuntimeError("unexpected Word executable")
    return executable


def _machine_word_executable() -> Path:
    import win32api

    access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Classes\Word.Application\CLSID",
        0,
        access,
    ) as key:
        clsid, clsid_type = winreg.QueryValueEx(key, None)
    if clsid_type != winreg.REG_SZ or str(clsid).upper() != _WORD_CLSID:
        raise RuntimeError("unexpected machine Word CLSID")
    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        rf"SOFTWARE\Classes\CLSID\{_WORD_CLSID}\LocalServer32",
        0,
        access,
    ) as key:
        command, command_type = winreg.QueryValueEx(key, None)
    if command_type not in {winreg.REG_SZ, winreg.REG_EXPAND_SZ}:
        raise RuntimeError("invalid machine Word server registration")
    executable = _registered_server_path(command)
    if executable.name.casefold() != "winword.exe":
        raise RuntimeError("unexpected Word executable")
    translations = win32api.GetFileVersionInfo(str(executable), r"\VarFileInfo\Translation")
    if not isinstance(translations, tuple) or len(translations) != 1:
        raise RuntimeError("ambiguous Word executable identity")
    language, codepage = translations[0]
    prefix = rf"\StringFileInfo\{language:04x}{codepage:04x}"
    company = win32api.GetFileVersionInfo(str(executable), prefix + r"\CompanyName")
    description = win32api.GetFileVersionInfo(str(executable), prefix + r"\FileDescription")
    version = win32api.GetFileVersionInfo(str(executable), "\\")
    if (
        company != "Microsoft Corporation"
        or description != "Microsoft Word"
        or not isinstance(version, dict)
        or int(version.get("FileVersionMS", 0)) >> 16 != 16
    ):
        raise RuntimeError("machine Word executable identity mismatch")
    return executable


def _write_bootstrap_document(root: Path) -> Path:
    path = root / "bootstrap.docx"
    if path.exists() or path.is_symlink():
        raise RuntimeError("invalid bootstrap document state")
    with ZipFile(path, "x", ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        package.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>",
        )
        package.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p/><w:sectPr/></w:body></w:document>",
        )
    return path.resolve(strict=True)


def _start_owned_word_process(root: Path):
    import win32api
    import win32con
    import win32job
    import win32process

    word_executable = str(_machine_word_executable())
    bootstrap = _write_bootstrap_document(root)
    command_line = " ".join(
        (
            _quote_windows_argument(word_executable),
            "/x",
            "/q",
            _quote_windows_argument(str(bootstrap)),
        )
    )
    job = win32job.OpenJobObject(win32job.JOB_OBJECT_QUERY, False, _owned_job_name())
    if not win32job.IsProcessInJob(win32api.GetCurrentProcess(), job):
        job.Close()
        raise RuntimeError("Word worker is not in its owned job")
    startup = win32process.STARTUPINFO()
    process = thread = None
    try:
        process, thread, pid, _thread_id = win32process.CreateProcess(
            word_executable,
            command_line,
            None,
            None,
            False,
            win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW,
            None,
            str(root),
            startup,
        )
        if not win32job.IsProcessInJob(process, job):
            raise RuntimeError("Word did not inherit the owned job")
        times = win32process.GetProcessTimes(process)
        image = win32process.GetModuleFileNameEx(process, 0)
        if (
            pid != win32process.GetProcessId(process)
            or not str(times.get("CreationTime", ""))
            or Path(image).resolve(strict=True) != Path(word_executable)
        ):
            raise RuntimeError("owned Word process identity mismatch")
        win32process.ResumeThread(thread)
        thread.Close()
        thread = None
        owned = _OwnedWordProcess(
            handle=process,
            job=job,
            pid=pid,
            creation_identity=str(times["CreationTime"]),
            image_path=str(Path(image).resolve(strict=True)),
        )
        process = None
        job = None
        return owned, bootstrap
    finally:
        if thread is not None:
            thread.Close()
        if process is not None:
            win32process.TerminateProcess(process, 126)
            process.Close()
        if job is not None:
            job.Close()


def _exact_bootstrap_moniker(running_object_table: object, process: object, bootstrap: Path):
    import pythoncom
    import win32event

    context = pythoncom.CreateBindCtx(0)
    expected = os.path.normcase(str(bootstrap.resolve(strict=True)))
    while True:
        enumeration = running_object_table.EnumRunning()
        matches = []
        while True:
            batch = enumeration.Next(1)
            if not batch:
                break
            moniker = batch[0]
            try:
                display_name = moniker.GetDisplayName(context, None)
            except pythoncom.com_error:
                continue
            if os.path.normcase(os.path.abspath(display_name)) == expected:
                matches.append(moniker)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RuntimeError("bootstrap Word moniker is ambiguous")
        if win32event.WaitForSingleObject(process, 50) == win32event.WAIT_OBJECT_0:
            raise RuntimeError("owned Word exited before COM binding")


def _bind_owned_word_com_object(process: object, bootstrap: Path) -> tuple[object, object]:
    import pythoncom
    import win32event
    import win32job
    import win32com.client
    import win32process

    if not isinstance(process, _OwnedWordProcess):
        raise RuntimeError("ROT Word process identity mismatch")
    handle = process.handle
    running_object_table = pythoncom.GetRunningObjectTable()
    moniker = _exact_bootstrap_moniker(running_object_table, handle, bootstrap)
    unknown = running_object_table.GetObject(moniker)
    bootstrap_document = win32com.client.Dispatch(
        unknown.QueryInterface(pythoncom.IID_IDispatch)
    )
    app = bootstrap_document.Application
    hwnd = int(bootstrap_document.ActiveWindow.Hwnd)
    _thread_id, observed_pid = win32process.GetWindowThreadProcessId(hwnd)
    times = win32process.GetProcessTimes(handle)
    image = win32process.GetModuleFileNameEx(handle, 0)
    if (
        observed_pid != process.pid
        or win32process.GetProcessId(handle) != process.pid
        or str(times.get("CreationTime", "")) != process.creation_identity
        or os.path.normcase(os.path.abspath(image))
        != os.path.normcase(os.path.abspath(process.image_path))
        or not win32job.IsProcessInJob(handle, process.job)
        or win32event.WaitForSingleObject(handle, 0) != win32event.WAIT_TIMEOUT
    ):
        raise RuntimeError("ROT Word process identity mismatch")
    return app, bootstrap_document


def _source_path(root: Path, source_format: str) -> Path:
    name = "source.docm" if source_format == "DOCM" else "source.docx"
    source = root / name
    if source.is_symlink() or not source.is_file() or source.resolve().parent != root:
        raise ValueError("invalid Word render source")
    return source


def _validate_word_source(source: Path, source_format: str) -> None:
    """Reject package content that could make privileged Word acquire egress."""
    try:
        with ZipFile(source) as package:
            infos = package.infolist()
            if not infos or len(infos) > _MAX_PACKAGE_PARTS:
                raise ValueError("invalid Word package size")
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise ValueError("duplicate Word package part")
            total_size = 0
            for item in infos:
                path = PurePosixPath(item.filename)
                normalized_name = item.filename.casefold()
                if normalized_name.startswith(
                    _OPAQUE_ACTIVE_PART_PREFIXES
                ) or normalized_name.endswith(_IMPORTABLE_PART_SUFFIXES):
                    raise ValueError("unsupported active Word content")
                if (
                    item.filename.startswith(("/", "\\"))
                    or "\\" in item.filename
                    or ".." in path.parts
                    or item.file_size > _MAX_PART_BYTES
                    or (
                        item.file_size > 1024 * 1024
                        and item.file_size
                        > max(item.compress_size, 1) * _MAX_COMPRESSION_RATIO
                    )
                ):
                    raise ValueError("unsafe Word package part")
                total_size += item.file_size
            if total_size > _MAX_PACKAGE_BYTES:
                raise ValueError("invalid Word package size")
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required <= set(names):
                raise ValueError("incomplete Word package")

            content_types = ElementTree.fromstring(package.read("[Content_Types].xml"))
            main_types = {
                _xml_attribute(item, "ContentType")
                for item in content_types.iter()
                if _xml_local_name(item.tag) == "Override"
                and _xml_attribute(item, "PartName") == "/word/document.xml"
            }
            expected_type = (
                "application/vnd.ms-word.document.macroEnabled.main+xml"
                if source_format == "DOCM"
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            )
            if main_types != {expected_type}:
                raise ValueError("Word package format identity mismatch")

            for name in names:
                if name.endswith(".rels"):
                    relationships = ElementTree.fromstring(package.read(name))
                    for relationship in relationships.iter():
                        if _xml_local_name(relationship.tag) != "Relationship":
                            continue
                        target_value = _xml_attribute(relationship, "Target")
                        type_value = _xml_attribute(relationship, "Type")
                        mode_value = _xml_attribute(relationship, "TargetMode")
                        if target_value is None or type_value is None:
                            raise ValueError("invalid Word relationship")
                        target = target_value.strip()
                        relationship_type = type_value.rsplit("/", 1)[-1].casefold()
                        if relationship_type in _ACQUIRING_RELATIONSHIP_TYPES:
                            raise ValueError("unsupported active Word content")
                        if (
                            (mode_value or "").casefold() == "external"
                            or target.startswith(("\\\\", "//"))
                            or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE)
                        ):
                            raise ValueError("external Word relationship is forbidden")
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                root = ElementTree.fromstring(package.read(name))
                if any(
                    _xml_local_name(node.tag) in _ACQUIRING_WORD_ELEMENTS
                    for node in root.iter()
                ):
                    raise ValueError("unsupported active Word content")
                instructions = [
                    _xml_attribute(node, "instr") or ""
                    for node in root.iter()
                    if _xml_local_name(node.tag) == "fldSimple"
                ]
                for paragraph in (
                    node for node in root.iter() if _xml_local_name(node.tag) == "p"
                ):
                    instructions.append(
                        "".join(
                            node.text or ""
                            for node in paragraph.iter()
                            if _xml_local_name(node.tag) == "instrText"
                        )
                    )
                for value in instructions:
                    if not value.strip():
                        continue
                    code = re.match(r"\s*([A-Z]+)\b", value, re.IGNORECASE)
                    if (
                        _ACQUIRING_WORD_FIELD_CODES.search(value)
                        or re.search(r"(?:\\\\|//|[A-Z][A-Z0-9+.-]*:)", value, re.IGNORECASE)
                        or code is None
                        or code.group(1).upper() not in _SAFE_WORD_FIELD_CODES
                    ):
                        raise ValueError("unsupported active Word field")
    except (BadZipFile, OSError, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("invalid Word render source") from exc


def _render_job(
    root: Path,
    *,
    word_launcher: Callable[[Path], tuple[object, Path]] = _start_owned_word_process,
    com_binder: Callable[[object, Path], tuple[object, object]] = _bind_owned_word_com_object,
) -> dict:
    request = _load_request(root)
    source = _source_path(root, request["sourceFormat"])
    _validate_word_source(source, request["sourceFormat"])
    output = root / "output.partial.pdf"
    if output.exists() or output.is_symlink():
        raise ValueError("invalid Word render output state")
    source_digest = sha256(source.read_bytes()).hexdigest()
    process = None
    app = None
    bootstrap_document = None
    document = None
    com_initialized = False
    failure: Exception | None = None
    renderer_version = "UNKNOWN"
    try:
        _status(root, "COM_INIT")
        try:
            import pythoncom
        except ModuleNotFoundError:
            pythoncom = None
        if pythoncom is not None:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            com_initialized = True
        _status(root, "WORD_PROCESS_START")
        process, bootstrap = word_launcher(root)
        _status(root, "WORD_COM_BIND")
        app, bootstrap_document = com_binder(process, bootstrap)
        app.AutomationSecurity = 3
        if int(app.AutomationSecurity) != 3:
            raise RuntimeError("Word macro automation security did not fail closed")
        app.Options.UpdateLinksAtOpen = False
        app.Options.UpdateFieldsAtPrint = False
        if bool(app.Options.UpdateLinksAtOpen) or bool(app.Options.UpdateFieldsAtPrint):
            raise RuntimeError("Word automatic external updates did not fail closed")
        renderer_version_value = getattr(app, "Version", None)
        if (
            not isinstance(renderer_version_value, str)
            or re.fullmatch(r"16\.\d+(?:\.\d+)*", renderer_version_value) is None
        ):
            raise RuntimeError("Microsoft Word renderer version is invalid")
        renderer_version = renderer_version_value
        app.Visible = False
        app.DisplayAlerts = 0
        bootstrap_document.Close(SaveChanges=0)
        bootstrap_document = None
        _status(root, "DOCUMENT_OPEN")
        document = app.Documents.Open(
            FileName=str(source),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            OpenAndRepair=False,
            NoEncodingDialog=True,
        )
        _status(root, "EXPORT_AS_FIXED_FORMAT")
        document.ExportAsFixedFormat(
            OutputFileName=str(output),
            ExportFormat=17,
            OpenAfterExport=False,
            OptimizeFor=0,
            Range=0,
            Item=0,
            IncludeDocProps=True,
            CreateBookmarks=0,
            DocStructureTags=True,
            BitmapMissingFonts=True,
            UseISO19005_1=False,
        )
    except Exception as exc:  # COM providers use platform-specific exception classes.
        failure = exc
    finally:
        if document is not None:
            _status(root, "DOCUMENT_CLOSE")
            try:
                document.Close(SaveChanges=0)
            except Exception as exc:
                failure = failure or exc
            finally:
                document = None
        if bootstrap_document is not None:
            try:
                bootstrap_document.Close(SaveChanges=0)
            except Exception as exc:
                failure = failure or exc
            finally:
                bootstrap_document = None
        if app is not None:
            _status(root, "WORD_QUIT")
            try:
                app.Quit(SaveChanges=0)
            except Exception as exc:
                failure = failure or exc
        if process is not None:
            process.Close()
        if com_initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception as exc:
                failure = failure or exc

    _status(root, "WORKER_EXIT")
    if failure is not None:
        raise RuntimeError("Microsoft Word render failed") from failure
    if sha256(source.read_bytes()).hexdigest() != source_digest:
        raise RuntimeError("authoritative Word copy changed during render")
    pdf_bytes = output.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-") or not pdf_bytes.rstrip().endswith(b"%%EOF"):
        raise RuntimeError("Microsoft Word returned invalid PDF bytes")
    result = {
        "schemaVersion": _SCHEMA_VERSION,
        "status": "SUCCESS",
        "operation": RENDER_OPERATION,
        "rendererType": "MICROSOFT_WORD_DESKTOP_COM",
        "rendererVersion": renderer_version,
        "wordSha256": source_digest,
        "pdfSha256": sha256(pdf_bytes).hexdigest(),
    }
    _atomic_json(root / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        return 2
    try:
        root = Path(arguments[0]).resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            return 2
        _render_job(root)
    except (OSError, RuntimeError, ValueError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
