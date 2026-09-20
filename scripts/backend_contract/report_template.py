"""Deterministic, whitelisted binding for protected DOCX/DOCM packages."""

from dataclasses import dataclass, fields
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import re
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .report_foundation import ReportSnapshot, ReportState


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_FIELD_NAMES = {"TOC", "PAGE", "NUMPAGES", "SEQ", "REF", "PAGEREF"}
_ACQUIRING_TEMPLATE_FIELDS = re.compile(
    r"\b(?:INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|DDE)\b", re.IGNORECASE
)
# The same expression both validators use.  This reader took the token up to the
# first whitespace, and Word ends a field NAME at whitespace OR at a double
# quote: PAGEREF"Marca" binds as wdFieldPageRef in Word 16 and both validators
# accept it, while this statement refused it -- so a template they certify could
# never be bound.
_TEMPLATE_FIELD_CODE = re.compile(r"\s*([A-Z]+)\b", re.IGNORECASE)
# A binding value is text the product accepts upstream, and it has to survive
# being written into XML.  The canonical block normalises the line-break family
# and refuses what XML cannot carry; this site only escaped the three
# metacharacters, so an expert whose name held Word's manual line break made
# every render of an approved report fail, blaming the template.
_TEMPLATE_LINE_BREAKS = (
    chr(13) + chr(10),
    chr(13),
    chr(11),
    chr(12),
    chr(0x85),
    chr(0x2028),
    chr(0x2029),
)
_TEMPLATE_FORBIDDEN_CHARACTERS = re.compile(
    "["
    + chr(0) + "-" + chr(8)
    + chr(14) + "-" + chr(31)
    + chr(0xD800) + "-" + chr(0xDFFF)
    + chr(0xFFFE) + chr(0xFFFF)
    + "]"
)


def _template_text(value: str) -> str:
    """One binding value, in the only form XML can carry unchanged."""
    for control in _TEMPLATE_LINE_BREAKS:
        value = value.replace(control, chr(10))
    found = _TEMPLATE_FORBIDDEN_CHARACTERS.search(value)
    if found is not None:
        raise ValueError(
            "template binding value carries a character XML cannot represent: "
            "U+{:04X}".format(ord(found.group()))
        )
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
_FIELD_VALUES = {
    "EXPERT_FULL_NAME": lambda report: report.expert_profile.full_name,
    "EXPERT_REGISTRATION": lambda report: report.expert_profile.registration,
    "REPORT_ID": lambda report: report.report_id,
}
# The same bound the two validators state.  The binder's own numbers were
# stricter, so a photo-heavy template both validators certify -- and that the
# backup gate has already accepted -- failed every render in _safe_parts.
_MAX_PARTS = 4096
_MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
# The ratio guard applies only above 1 MiB on both other sides: a small, highly
# compressible part is ordinary, not an attack.
_COMPRESSION_RATIO_FLOOR = 1024 * 1024


# The third statement of the field policy.  report_template cannot import the
# delivery boundary -- that module imports this one -- so the segmentation is
# duplicated here exactly as it is duplicated between the two validators, and the
# parity catalogue now asks all three for a verdict rather than two.
#
# A field's instruction is the TEXT OF THE REGION between w:fldChar "begin" and
# "separate".  Judging each w:instrText node alone refused an instruction Word 16
# itself writes: editing a protected field under track changes splits it, so
# " PAGEREF Marca " and " \h" arrive as two nodes and the second one's leading
# token is a switch.  Because _FIELD_NAMES requires all six protected codes to be
# present, one reviewed field made every render of that template fail for good.
_FIELD_INSTRUCTION_ELEMENTS = frozenset({"instrText", "delInstrText"})
_FIELD_TEXT_ELEMENTS = _FIELD_INSTRUCTION_ELEMENTS | {"t", "delText"}
_FIELD_SEPARATOR_ELEMENTS = {"tab": chr(9), "br": chr(10), "cr": chr(10)}


def _local_name(tag: object) -> str:
    value = str(tag)
    return value.rsplit("}", 1)[-1] if "}" in value else value


def _template_field_instructions(root: ElementTree.Element) -> list[str]:
    """Every field instruction in a part, one per field, in document order."""
    instructions: list[str] = []
    open_fields: list[list] = []

    def closed(field: list) -> str:
        buffer, in_result = field
        value = "".join(buffer)
        if in_result:
            return value
        if not value.strip():
            raise ValueError("unsupported active Word field instruction")
        return value

    for node in root.iter():
        name = _local_name(node.tag)
        if name == "fldChar":
            marker = (node.attrib.get(f"{_W}fldCharType") or "").strip().casefold()
            if marker == "begin":
                open_fields.append([[], False])
            elif marker == "separate" and open_fields:
                instructions.append(closed(open_fields[-1]))
                open_fields[-1] = [[], True]
            elif marker == "end" and open_fields:
                instructions.append(closed(open_fields.pop()))
        elif name in _FIELD_TEXT_ELEMENTS:
            spelled_as_instruction = name in _FIELD_INSTRUCTION_ELEMENTS
            if open_fields:
                buffer, in_result = open_fields[-1]
                if not in_result or spelled_as_instruction:
                    buffer.append(node.text or "")
            elif spelled_as_instruction:
                instructions.append(node.text or "")
        elif name in _FIELD_SEPARATOR_ELEMENTS and open_fields:
            buffer, in_result = open_fields[-1]
            if not in_result:
                buffer.append(_FIELD_SEPARATOR_ELEMENTS[name])
    instructions.extend(closed(item) for item in open_fields)
    return instructions


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
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("unsafe template package")
                if item.filename.endswith("/"):
                    # A directory entry carries no content.  Both validators skip
                    # them and a parity test pins that they are legal, while this
                    # third statement refused them -- so the backup gate
                    # certified a template that could then never be bound.
                    #
                    # The skip belongs AFTER the traversal check, not before it:
                    # placed first it let "../escape/" and "/word/" through, and
                    # a name ending in "/" can still carry bytes, so the size and
                    # ratio guards below have to see it too.
                    if item.file_size:
                        raise ValueError("unsafe template package")
                    continue
                if (
                    item.file_size > _COMPRESSION_RATIO_FLOOR
                    and item.file_size
                    > max(item.compress_size, 1) * _MAX_COMPRESSION_RATIO
                ):
                    raise ValueError("unsafe template package")
            return infos, {item.filename: package.read(item.filename) for item in infos}
    except ValueError:
        raise
    except Exception as exc:
        # zipfile's failure vocabulary is not closed: NotImplementedError for an
        # unimplemented compression method is not an OSError, and it left this
        # boundary as itself.
        raise ValueError("unsafe template package") from exc


def _mechanics(parts: dict[str, bytes]) -> tuple[set[str], tuple[str, ...], int]:
    try:
        root = ElementTree.fromstring(parts["word/document.xml"])
    except (KeyError, ElementTree.ParseError) as exc:
        raise ValueError("template document XML is invalid") from exc
    field_names = set()
    # Complex fields may split one instruction over several instrText nodes.
    # Reconstruct each paragraph and reject every opcode outside the protected
    # set before a template can reach a local Office process.
    xml_roots = []
    for name, content in parts.items():
        if not (name.startswith("word/") and name.endswith(".xml")):
            continue
        try:
            xml_roots.append(ElementTree.fromstring(content))
        except ElementTree.ParseError as exc:
            raise ValueError("template Word XML is invalid") from exc
    for xml_root in xml_roots:
        nodes = _template_field_instructions(xml_root)
        nodes.extend(
            item.attrib.get(f"{_W}instr", "")
            for item in xml_root.iter(f"{_W}fldSimple")
            if item.attrib.get(f"{_W}instr", "").strip()
        )
        for instruction in nodes:
            # Both validators match each instruction on its own, on word
            # boundaries.  Joining every instruction of a part, stripping all
            # whitespace and asking for bare substrings read any identifier
            # containing those letters as an opcode -- a bookmark named
            # "Addendum" was refused -- and let one field's trailing characters
            # join the next field's leading ones.
            if _ACQUIRING_TEMPLATE_FIELDS.search(instruction) or "://" in instruction:
                raise ValueError("unsupported active Word field instruction")
        for instruction in nodes:
            if not instruction.strip():
                # The result region of an ordinary field contributes nothing.
                continue
            code = _TEMPLATE_FIELD_CODE.match(instruction)
            if code is None or code.group(1).upper() not in _FIELD_NAMES:
                raise ValueError("unsupported active Word field instruction")
            field_names.add(code.group(1).upper())
    bookmarks = tuple(sorted(item.attrib.get(f"{_W}name", "") for item in root.iter(f"{_W}bookmarkStart") if item.attrib.get(f"{_W}name")))
    controls = sum(1 for _ in root.iter(f"{_W}sdt"))
    for item in root.iter(f"{_WP}docPr"):
        if not item.attrib.get("descr", "").strip():
            raise ValueError("image alt description is required")
    return field_names, bookmarks, controls


def _digest(parts: dict[str, bytes], name: str) -> str | None:
    return sha256(parts[name]).hexdigest() if name in parts else None


_MAIN_PART_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml": "DOCX",
    "application/vnd.ms-word.document.macroenabled.main+xml": "DOCM",
}


def _declared_output_kind(parts: dict) -> str:
    """DOCX or DOCM as the package itself declares it, not as its parts hint.

    The kind used to be inferred from the PRESENCE of word/vbaProject.bin, while
    the delivery boundary decided the same axis from the main part's declared
    content type.  Native Word 16 writes a .docm carrying no VBA part at all
    when the document has no macros (probe, 2026-09-19), so for every such
    template the two rules were mutually unsatisfiable: binding refused it as
    DOCM for want of a macro part, and the boundary refused it as DOCX for its
    declared content type.  Both now read the same signal.
    """
    try:
        root = ElementTree.fromstring(parts["[Content_Types].xml"])
    except (KeyError, ElementTree.ParseError) as exc:
        raise ValueError("template content types are unreadable") from exc
    declared = {
        (item.attrib.get("ContentType") or "").casefold()
        for item in root.iter()
        if item.tag.rsplit("}", 1)[-1] == "Override"
        and (item.attrib.get("PartName") or "").casefold() == "/word/document.xml"
    }
    kinds = {
        _MAIN_PART_CONTENT_TYPES[value]
        for value in declared
        if value in _MAIN_PART_CONTENT_TYPES
    }
    if len(kinds) != 1:
        raise ValueError("template main part content type is not uniquely declared")
    return kinds.pop()


def bind_report_template(template_bytes: bytes, report: ReportSnapshot, manifest: TemplateBindingManifest) -> DocumentBindingResult:
    if type(report) is not ReportSnapshot or report.state is not ReportState.APPROVED or not report.coverage.complete or report.upstream_stale:
        raise ValueError("Word binding requires an approved report")
    if type(manifest) is not TemplateBindingManifest:
        raise ValueError("template manifest is invalid")
    infos, before = _safe_parts(template_bytes)
    try:
        custom_root = ElementTree.fromstring(before["docProps/custom.xml"])
    except (KeyError, ElementTree.ParseError) as exc:
        raise ValueError("template identity is missing") from exc
    identity_properties = [item for item in custom_root.iter() if item.attrib.get("name") == "TEMPLATE_ID"]
    identity_values = [text.strip() for item in identity_properties for text in item.itertext() if text.strip()]
    if identity_values != [manifest.template_id]:
        raise ValueError("template identity does not match manifest")
    before_mechanics = _mechanics(before)
    if before_mechanics[0] != _FIELD_NAMES:
        raise ValueError("protected Word fields are incomplete")
    if _declared_output_kind(before) != manifest.output_kind:
        raise ValueError("template kind and package content type disagree")
    document = before["word/document.xml"].decode("utf-8")
    declared_placeholders = {item.placeholder for item in manifest.bindings}
    if set(re.findall(r"\[\[[A-Z][A-Z0-9_]*\]\]", document)) != declared_placeholders:
        raise ValueError("undeclared canonical template field")
    for binding in manifest.bindings:
        if document.count(binding.placeholder) != 1:
            raise ValueError("canonical field must remain single-source")
        document = document.replace(
            binding.placeholder, _template_text(_FIELD_VALUES[binding.field](report))
        )
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
