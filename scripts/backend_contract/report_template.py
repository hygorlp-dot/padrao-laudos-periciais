"""Deterministic, whitelisted binding for protected DOCX/DOCM packages."""

from dataclasses import dataclass, fields
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from .report_foundation import ReportSnapshot, ReportState


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_FIELD_NAMES = {"TOC", "PAGE", "NUMPAGES", "SEQ", "REF", "PAGEREF"}
_FIELD_VALUES = {
    "EXPERT_FULL_NAME": lambda report: report.expert_profile.full_name,
    "EXPERT_REGISTRATION": lambda report: report.expert_profile.registration,
    "REPORT_ID": lambda report: report.report_id,
}
_MAX_PARTS = 1000
_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


@dataclass(frozen=True, slots=True)
class TemplateBinding:
    field: str
    placeholder: str

    def __post_init__(self):
        if self.field not in _FIELD_VALUES or not _text(self.placeholder):
            raise ValueError("template binding is invalid")


@dataclass(frozen=True, slots=True)
class TemplateBindingManifest:
    schema_version: str
    template_id: str
    output_kind: str
    bindings: tuple[TemplateBinding, ...]

    def __post_init__(self):
        if self.schema_version != "1.0.0" or not _text(self.template_id) or self.output_kind not in {"DOCX", "DOCM"}:
            raise ValueError("template manifest is invalid")
        if type(self.bindings) is not tuple or {item.field for item in self.bindings} != set(_FIELD_VALUES) or len(self.bindings) != len(_FIELD_VALUES):
            raise ValueError("template manifest must bind every canonical field once")


@dataclass(frozen=True, slots=True)
class TemplateIntegrity:
    passed: bool
    preserved_fields: tuple[str, ...]
    bookmarks: tuple[str, ...]
    content_controls: int
    macro_preserved: bool
    styles_preserved: bool
    numbering_preserved: bool


@dataclass(frozen=True, slots=True)
class DocumentBindingResult:
    output_bytes: bytes
    integrity: TemplateIntegrity


def template_binding_manifest_from_mapping(value: object) -> TemplateBindingManifest:
    if type(value) is not dict or set(value) != {item.name for item in fields(TemplateBindingManifest)} or type(value["bindings"]) is not list:
        raise ValueError("template manifest mapping is invalid")
    bindings = []
    for item in value["bindings"]:
        if type(item) is not dict or set(item) != {field.name for field in fields(TemplateBinding)}:
            raise ValueError("template binding mapping is invalid")
        bindings.append(TemplateBinding(**item))
    return TemplateBindingManifest(value["schema_version"], value["template_id"], value["output_kind"], tuple(bindings))


def _safe_parts(template_bytes: bytes) -> tuple[list[ZipInfo], dict[str, bytes]]:
    if type(template_bytes) is not bytes or not template_bytes:
        raise ValueError("unsafe template package")
    try:
        with ZipFile(BytesIO(template_bytes)) as package:
            infos = package.infolist()
            if len(infos) > _MAX_PARTS or sum(item.file_size for item in infos) > _MAX_UNCOMPRESSED_BYTES:
                raise ValueError("unsafe template package")
            for item in infos:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or item.filename.endswith("/"):
                    raise ValueError("unsafe template package")
                if item.compress_size and item.file_size / item.compress_size > 200:
                    raise ValueError("unsafe template package")
            return infos, {item.filename: package.read(item.filename) for item in infos}
    except (BadZipFile, OSError) as exc:
        raise ValueError("unsafe template package") from exc


def _mechanics(parts: dict[str, bytes]) -> tuple[set[str], tuple[str, ...], int]:
    try:
        root = ElementTree.fromstring(parts["word/document.xml"])
    except (KeyError, ElementTree.ParseError) as exc:
        raise ValueError("template document XML is invalid") from exc
    field_names = set()
    for item in root.iter(f"{_W}instrText"):
        if item.text:
            name = item.text.strip().split(maxsplit=1)[0].upper()
            if name in _FIELD_NAMES:
                field_names.add(name)
    bookmarks = tuple(sorted(item.attrib.get(f"{_W}name", "") for item in root.iter(f"{_W}bookmarkStart") if item.attrib.get(f"{_W}name")))
    controls = sum(1 for _ in root.iter(f"{_W}sdt"))
    for item in root.iter(f"{_WP}docPr"):
        if not item.attrib.get("descr", "").strip():
            raise ValueError("image alt description is required")
    return field_names, bookmarks, controls


def _digest(parts: dict[str, bytes], name: str) -> str | None:
    return sha256(parts[name]).hexdigest() if name in parts else None


def bind_report_template(template_bytes: bytes, report: ReportSnapshot, manifest: TemplateBindingManifest) -> DocumentBindingResult:
    if type(report) is not ReportSnapshot or report.state is not ReportState.APPROVED or not report.coverage.complete or report.upstream_stale:
        raise ValueError("Word binding requires an approved report")
    if type(manifest) is not TemplateBindingManifest:
        raise ValueError("template manifest is invalid")
    infos, before = _safe_parts(template_bytes)
    before_mechanics = _mechanics(before)
    if before_mechanics[0] != _FIELD_NAMES:
        raise ValueError("protected Word fields are incomplete")
    is_macro = "word/vbaProject.bin" in before
    if (manifest.output_kind == "DOCM") != is_macro:
        raise ValueError("template kind and macro package disagree")
    document = before["word/document.xml"].decode("utf-8")
    for binding in manifest.bindings:
        if document.count(binding.placeholder) != 1:
            raise ValueError("canonical field must remain single-source")
        document = document.replace(binding.placeholder, _FIELD_VALUES[binding.field](report))
    after = dict(before)
    after["word/document.xml"] = document.encode("utf-8")
    after_mechanics = _mechanics(after)
    protected = ("[Content_Types].xml", "word/styles.xml", "word/numbering.xml", "word/vbaProject.bin")
    if before_mechanics != after_mechanics or any(_digest(before, name) != _digest(after, name) for name in protected):
        raise ValueError("Word template integrity changed")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for info in infos:
            package.writestr(info.filename, after[info.filename])
    integrity = TemplateIntegrity(
        passed=True, preserved_fields=tuple(sorted(after_mechanics[0])), bookmarks=after_mechanics[1], content_controls=after_mechanics[2],
        macro_preserved=_digest(before, "word/vbaProject.bin") == _digest(after, "word/vbaProject.bin"),
        styles_preserved=_digest(before, "word/styles.xml") == _digest(after, "word/styles.xml"),
        numbering_preserved=_digest(before, "word/numbering.xml") == _digest(after, "word/numbering.xml"),
    )
    return DocumentBindingResult(output.getvalue(), integrity)
