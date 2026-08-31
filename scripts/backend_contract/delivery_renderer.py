"""Protected delivery rendering and final-byte integrity checks."""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import re
import textwrap
import unicodedata
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .report_foundation import ReportSnapshot
from .report_foundation import report_snapshot_to_mapping
from .report_template import (
    DocumentBindingResult,
    TemplateBindingManifest,
    bind_report_template,
)


_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DOCM_MEDIA = "application/vnd.ms-word.document.macroEnabled.12"
_PDF_MEDIA = "application/pdf"
DELIVERY_RENDERING_VERSION = "delivery-renderer/2.0.0"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
ElementTree.register_namespace("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main")


def render_word_candidate(
    *, template_bytes: bytes, report: ReportSnapshot, manifest: TemplateBindingManifest,
) -> DocumentBindingResult:
    result = bind_report_template(template_bytes, report, manifest)
    output = _inject_canonical_report(result.output_bytes, report)
    validate_final_artifact(output, manifest.output_kind)
    return DocumentBindingResult(output, result.integrity)


def _paragraph(text: str):
    paragraph = ElementTree.Element(f"{_W}p")
    run = ElementTree.SubElement(paragraph, f"{_W}r")
    node = ElementTree.SubElement(run, f"{_W}t")
    node.text = text
    return paragraph


def _canonical_report_lines(report: ReportSnapshot) -> tuple[str, ...]:
    mapping = report_snapshot_to_mapping(report)
    digest = sha256(json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    lines = [f"LAUDO CANÔNICO | {report.report_id}", f"REPORT_SNAPSHOT_SHA256 | {digest}"]
    for item in report.context_matrix:
        lines.append(f"CONTEXTO | {item.field} | {item.status.value} | {item.source_id or 'SEM_FONTE'} | {item.note}")
    claims_by_section = {section.section_id: [] for section in report.sections}
    for claim in report.claims:
        claims_by_section[claim.section_id].append(claim)
    answers_by_section = {section.section_id: [] for section in report.sections}
    for answer in report.answers:
        answers_by_section[answer.section_id].append(answer)
    for section in sorted(report.sections, key=lambda item: item.order):
        lines.append(f"SEÇÃO {section.order} | {section.title}")
        for claim in claims_by_section[section.section_id]:
            lines.append(f"AFIRMAÇÃO | {claim.claim_id} | {claim.authority.value} | {claim.text}")
            lines.extend(f"PROVENIÊNCIA | {item.source_kind} | {item.source_id} | revisão {item.source_revision}" for item in claim.provenance)
        for answer in answers_by_section[section.section_id]:
            lines.extend((
                f"QUESITO | {answer.question_id}", f"RESPOSTA | {answer.text}",
                f"ACHADO | {answer.finding_id}", f"EVIDÊNCIAS | {', '.join(answer.evidence_ids)}",
                f"MÉTODOS | {', '.join(answer.method_ids)}", f"DECISÃO | {answer.decision_id}",
            ))
    for decision in report.review_decisions:
        lines.append(f"REVISÃO PROFISSIONAL | {decision.action.value} | {decision.professional_id} | {decision.reason} | {decision.timestamp}")
    return tuple(lines)


def render_pdf_candidate(report: ReportSnapshot) -> bytes:
    """Render a text-only diagnostic PDF; never use as a final professional artifact."""
    report_digest = sha256(json.dumps(report_snapshot_to_mapping(report), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    lines = []
    for source_line in _canonical_report_lines(report):
        try:
            source_line.encode("cp1252")
        except UnicodeEncodeError as exc:
            raise ValueError("canonical report contains characters unsupported by the PDF renderer") from exc
        # 56 glyphs fits the 503pt text box even for Helvetica's widest WinAnsi glyph (W, 944/1000em) at 9pt.
        lines.extend(textwrap.wrap(source_line, width=56, replace_whitespace=False, drop_whitespace=False, break_on_hyphens=False) or [""])
    pages = [lines[index:index + 44] for index in range(0, len(lines), 44)] or [["EMPTY REPORT"]]
    objects: list[bytes] = []

    def add(value: bytes) -> int:
        objects.append(value)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    content_ids = []
    for page in pages:
        commands = [b"BT /F1 9 Tf 46 795 Td 11 TL"]
        for line in page:
            encoded = line.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
            commands.append(b"(" + encoded + b") Tj T*")
        commands.append(b"ET")
        stream = b"\n".join(commands)
        content_ids.append(add(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"))
    pages_id = len(objects) + len(pages) + 1
    page_ids = []
    for content_id in content_ids:
        page_ids.append(add(f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode("ascii")))
    kids = " ".join(f"{item} 0 R" for item in page_ids)
    add(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("ascii"))
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R /DiagnosticOnly true /ReportSnapshotSHA256 ({report_digest}) >>".encode("ascii"))
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer << /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return bytes(output)


def render_final_pdf_candidate(*, word_content: bytes, word_format: str, converter: object) -> bytes:
    """Convert the exact bound Word artifact through an explicitly local converter."""
    conversion_copy, conversion_format = safe_pdf_conversion_copy(word_content, word_format)
    try:
        output = converter.convert(conversion_copy, conversion_format)
    except (OSError, RuntimeError, TimeoutError) as exc:
        raise ValueError("local Office PDF conversion unavailable") from exc
    if b"/DiagnosticOnly true" in output:
        raise ValueError("diagnostic PDF cannot be finalized")
    validate_final_artifact(output, "PDF")
    _validate_pdf_fidelity(conversion_copy, output)
    return output


def _normalized_visible_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _lexical_tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W\d_]+", _normalized_visible_text(value), flags=re.UNICODE))


def _image_signature(image: Image.Image) -> tuple[float, tuple[bool, ...]]:
    gray = image.convert("L").resize((16, 16))
    pixels = tuple(gray.getdata())
    mean = sum(pixels) / len(pixels)
    return round(image.width / max(image.height, 1), 2), tuple(value >= mean for value in pixels)


def _validate_pdf_fidelity(word_content: bytes, pdf_content: bytes) -> None:
    """Reject converter output that is not observably derived from the bound Word."""
    try:
        with ZipFile(BytesIO(word_content)) as package:
            word_fragments: list[str] = []
            word_images: list[tuple[float, tuple[bool, ...]]] = []
            table_rows: list[tuple[str, ...]] = []
            for name in package.namelist():
                if name.startswith("word/media/") and not name.endswith("/"):
                    with Image.open(BytesIO(package.read(name))) as image:
                        word_images.append(_image_signature(image))
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                root = ElementTree.fromstring(package.read(name))
                word_fragments.extend(
                    item.text for item in root.iter(f"{_W}t") if item.text and item.text.strip()
                )
                for row in root.iter(f"{_W}tr"):
                    cells = tuple(
                        _normalized_visible_text(" ".join(item.text or "" for item in cell.iter(f"{_W}t")))
                        for cell in row.findall(f"{_W}tc")
                    )
                    if len(cells) > 1 and all(cells):
                        table_rows.append(cells)
        reader = PdfReader(BytesIO(pdf_content), strict=True)
        extracted_pages: list[str] = []
        positioned: list[tuple[int, str, float]] = []
        pdf_images: list[tuple[float, tuple[bool, ...]]] = []
        for page_number, page in enumerate(reader.pages):
            def visitor(text: str, _cm: object, tm: list[float], _font: object, _size: float) -> None:
                normalized = _normalized_visible_text(text)
                if normalized:
                    positioned.append((page_number, normalized, float(tm[5])))
            extracted_pages.append(page.extract_text(visitor_text=visitor) or "")
            pdf_images.extend(_image_signature(item.image) for item in page.images)
        pdf_text = _normalized_visible_text("\n".join(extracted_pages))
    except (BadZipFile, KeyError, ElementTree.ParseError, PdfReadError, OSError, ValueError) as exc:
        raise ValueError("final PDF fidelity cannot be verified") from exc
    required = {_normalized_visible_text(item) for item in word_fragments if _normalized_visible_text(item)}
    source_vocabulary = set(_lexical_tokens(" ".join(word_fragments)))
    pdf_vocabulary = set(_lexical_tokens(pdf_text))
    images_match = all(
        any(abs(source[0] - candidate[0]) <= 0.05 and sum(a != b for a, b in zip(source[1], candidate[1])) <= 16 for candidate in pdf_images)
        for source in word_images
    )
    tables_match = all(
        any(
            all(any(cell in text and page == anchor_page and abs(y - anchor_y) <= 3 for page, text, y in positioned) for cell in row[1:])
            for anchor_page, anchor_text, anchor_y in positioned if row[0] in anchor_text
        )
        for row in table_rows
    )
    if (
        not required
        or any(item not in pdf_text for item in required)
        or not pdf_vocabulary <= source_vocabulary
        or not images_match
        or not tables_match
    ):
        raise ValueError("final PDF does not faithfully represent the bound Word artifact")


def _inject_canonical_report(content: bytes, report: ReportSnapshot) -> bytes:
    try:
        with ZipFile(BytesIO(content)) as source:
            parts = {item.filename: source.read(item.filename) for item in source.infolist()}
        root = ElementTree.fromstring(parts["word/document.xml"])
    except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("bound Word artifact is invalid") from exc
    controls = []
    for control in root.iter(f"{_W}sdt"):
        tags = control.findall(f"./{_W}sdtPr/{_W}tag")
        if any(item.attrib.get(f"{_W}val") == "CANONICAL_REPORT" for item in tags):
            controls.append(control)
    if len(controls) != 1:
        raise ValueError("template requires exactly one CANONICAL_REPORT content control")
    target = controls[0].find(f"{_W}sdtContent")
    if target is None:
        raise ValueError("CANONICAL_REPORT content control is incomplete")
    target.clear()
    for line in _canonical_report_lines(report):
        target.append(_paragraph(line))
    parts["word/document.xml"] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    return output.getvalue()


def validate_final_artifact(content: bytes, output_format: str) -> tuple[str, int, str]:
    if type(content) is not bytes or not content:
        raise ValueError("final artifact bytes are empty")
    if output_format in {"DOCX", "DOCM"}:
        try:
            with ZipFile(BytesIO(content)) as package:
                names = set(package.namelist())
                if not {"[Content_Types].xml", "word/document.xml"} <= names:
                    raise ValueError("final Word artifact is incomplete")
                has_macro = "word/vbaProject.bin" in names
                for name in names:
                    if name.endswith(".rels"):
                        root = ElementTree.fromstring(package.read(name))
                        if any(item.attrib.get("TargetMode", "").lower() == "external" for item in root.iter(f"{_REL}Relationship")):
                            raise ValueError("external relationships are forbidden in delivery artifacts")
        except (BadZipFile, OSError) as exc:
            raise ValueError("final Word artifact is invalid") from exc
        if has_macro != (output_format == "DOCM"):
            raise ValueError("final Word artifact macro identity changed")
        media_type = _DOCM_MEDIA if has_macro else _DOCX_MEDIA
    elif output_format == "PDF":
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if not reader.pages:
                raise ValueError("final PDF artifact is invalid")
            for page in reader.pages:
                _ = page.mediabox
        except (PdfReadError, OSError, ValueError, KeyError) as exc:
            raise ValueError("final PDF artifact is invalid") from exc
        if not content.startswith(b"%PDF-") or not content.rstrip().endswith(b"%%EOF"):
            raise ValueError("final PDF artifact is invalid")
        media_type = _PDF_MEDIA
    else:
        raise ValueError("unsupported final artifact format")
    return sha256(content).hexdigest(), len(content), media_type


def validate_supporting_artifact(content: bytes, media_type: str) -> tuple[str, int, str]:
    """Verify non-Office supporting bytes without trusting filename metadata."""
    if type(content) is not bytes or not content:
        raise ValueError("supporting artifact bytes are empty")
    expected_format = {"image/jpeg": "JPEG", "image/png": "PNG"}.get(media_type)
    if expected_format is None:
        raise ValueError("unsupported supporting artifact media type")
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format != expected_format:
                raise ValueError(f"supporting {expected_format} artifact is invalid")
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"supporting {expected_format} artifact is invalid") from exc
    return sha256(content).hexdigest(), len(content), media_type


def safe_pdf_conversion_copy(content: bytes, output_format: str) -> tuple[bytes, str]:
    """Build a macro-free, external-link-free copy used only by the local PDF renderer."""
    validate_final_artifact(content, output_format)
    if output_format == "DOCX":
        return content, output_format
    with ZipFile(BytesIO(content)) as source:
        parts = {item.filename: source.read(item.filename) for item in source.infolist() if item.filename not in {"word/vbaProject.bin", "word/vbaData.xml"}}
    content_types = ElementTree.fromstring(parts["[Content_Types].xml"])
    for item in tuple(content_types):
        if item.attrib.get("PartName") in {"/word/vbaProject.bin", "/word/vbaData.xml"}:
            content_types.remove(item)
        elif "macroEnabled.main+xml" in item.attrib.get("ContentType", ""):
            item.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
    parts["[Content_Types].xml"] = ElementTree.tostring(content_types, encoding="utf-8", xml_declaration=True)
    for name in tuple(parts):
        if not name.endswith(".rels"):
            continue
        root = ElementTree.fromstring(parts[name])
        for item in tuple(root):
            if "vbaProject" in item.attrib.get("Type", "") or item.attrib.get("Target", "").endswith(("vbaProject.bin", "vbaData.xml")):
                root.remove(item)
        parts[name] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    validate_final_artifact(output.getvalue(), "DOCX")
    return output.getvalue(), "DOCX"


def verify_reopened_artifact(
    *, content: bytes, output_format: str, expected_size: int, expected_sha256: str,
) -> None:
    digest, size, _ = validate_final_artifact(content, output_format)
    if size != expected_size or digest != expected_sha256:
        raise ValueError("reopened artifact bytes diverge from finalized manifest")
