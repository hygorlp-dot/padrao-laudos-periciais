"""Protected delivery rendering and final-byte integrity checks."""

from __future__ import annotations

from collections import Counter
import ctypes
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import math
import posixpath
import json
import re
import textwrap
import unicodedata
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError
import pypdfium2 as pdfium
from pypdf import PdfReader
from pypdf.generic import BooleanObject
from pypdf.errors import PdfReadError
from pypdf.generic import ContentStream

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
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_V = "{urn:schemas-microsoft-com:vml}"
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
    return tuple(re.findall(r"\w+|[^\w\s]", _normalized_visible_text(value), flags=re.UNICODE))


def _image_signature(image: Image.Image) -> tuple[float, tuple[float, ...], tuple[float, ...], tuple[bool, ...]]:
    rgb = image.convert("RGB").resize((32, 32))
    statistics = ImageStat.Stat(rgb)
    gray = rgb.convert("L").resize((16, 16))
    pixels = tuple(gray.get_flattened_data())
    mean = sum(pixels) / len(pixels)
    return (
        round(image.width / max(image.height, 1), 2),
        tuple(round(value, 1) for value in statistics.mean),
        tuple(round(value, 1) for value in statistics.stddev),
        tuple(value >= mean for value in pixels),
    )


def _ordered_image_signatures_match(sources: list[tuple], candidates: list[tuple]) -> bool:
    def matches(source: tuple, candidate: tuple) -> bool:
        return (
            abs(source[0] - candidate[0]) <= 0.05
            and all(abs(a - b) <= 12 for a, b in zip(source[1], candidate[1]))
            and all(abs(a - b) <= 12 for a, b in zip(source[2], candidate[2]))
            and sum(a != b for a, b in zip(source[3], candidate[3])) <= 16
        )

    return len(sources) == len(candidates) and all(
        matches(source, candidate) for source, candidate in zip(sources, candidates)
    )


def _ordered_word_image_signatures(package: ZipFile, xml_roots: dict[str, ElementTree.Element]) -> list[tuple]:
    ordered: list[tuple] = []
    def priority(name: str) -> tuple[int, str]:
        return (0 if "/header" in name else 1 if name == "word/document.xml" else 2, name)
    for name in sorted(xml_roots, key=priority):
        base = posixpath.dirname(name)
        relationships_name = f"{base}/_rels/{posixpath.basename(name)}.rels"
        if relationships_name not in package.namelist():
            continue
        relationships = ElementTree.fromstring(package.read(relationships_name))
        targets = {
            item.attrib.get("Id"): posixpath.normpath(posixpath.join(base, item.attrib.get("Target", "")))
            for item in relationships.iter(f"{_REL}Relationship")
            if item.attrib.get("TargetMode", "").lower() != "external"
        }
        for image_node in xml_roots[name].iter():
            if image_node.tag == f"{_A}blip":
                relationship_id = image_node.attrib.get(f"{_R}embed")
            elif image_node.tag == f"{_V}imagedata":
                relationship_id = image_node.attrib.get(f"{_R}id")
            else:
                continue
            target = targets.get(relationship_id)
            if target and target in package.namelist():
                with Image.open(BytesIO(package.read(target))) as image:
                    ordered.append(_image_signature(image))
    return ordered


def _ordered_pdf_image_signatures(page: object, reader: PdfReader) -> list[tuple]:
    images = {str(name): page.images[name].image for name in page.images.keys()}
    ordered: list[tuple] = []
    for operands, operator in ContentStream(page.get_contents(), reader).operations:
        if operator != b"Do" or not operands:
            continue
        image = images.get(str(operands[0]))
        if image is not None:
            ordered.append(_image_signature(image))
    return ordered


@dataclass(frozen=True, slots=True)
class _PositionedText:
    page: int
    text: str
    x: float
    y: float
    font_size: float
    right: float
    bottom: float
    top: float


@dataclass(frozen=True, slots=True)
class _VerticalBarrier:
    page: int
    left: float
    right: float
    bottom: float
    top: float


def _has_nonvisible_text(page: object, reader: PdfReader) -> bool:
    render_mode = 0
    fill_alpha = 1.0
    stroke_alpha = 1.0
    stack: list[tuple[int, float, float]] = []
    try:
        resources = page["/Resources"].get_object()
        ext_states = resources.get("/ExtGState", {}).get_object()
    except (AttributeError, KeyError, TypeError):
        ext_states = {}
    text_operators = {b"Tj", b"TJ", b"'", b'"'}
    for operands, operator in ContentStream(page.get_contents(), reader).operations:
        if operator == b"q":
            stack.append((render_mode, fill_alpha, stroke_alpha))
        elif operator == b"Q":
            render_mode, fill_alpha, stroke_alpha = stack.pop() if stack else (0, 1.0, 1.0)
        elif operator == b"Tr" and operands:
            render_mode = int(operands[0])
        elif operator == b"gs" and operands:
            try:
                state = ext_states[str(operands[0])].get_object()
                fill_alpha = float(state.get("/ca", fill_alpha))
                stroke_alpha = float(state.get("/CA", stroke_alpha))
            except (AttributeError, KeyError, TypeError, ValueError):
                return True
        elif operator in text_operators and _text_show_has_content(operator, operands):
            if render_mode in {3, 7}:
                return True
            visible_alpha = (
                fill_alpha
                if render_mode in {0, 4}
                else stroke_alpha
                if render_mode in {1, 5}
                else max(fill_alpha, stroke_alpha)
            )
            if visible_alpha <= 0.01:
                return True
    return False


def _raster_region_is_observably_painted(
    rendered: Image.Image,
    background: Image.Image,
    bounds: tuple[float, float, float, float],
    *,
    page_height: float,
    scale: float,
) -> bool:
    left, bottom, right, top = bounds
    box = (
        max(0, math.floor((left - 1.0) * scale)),
        max(0, math.floor((page_height - top - 1.0) * scale)),
        min(rendered.width, math.ceil((right + 1.0) * scale)),
        min(rendered.height, math.ceil((page_height - bottom + 1.0) * scale)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return False
    actual = rendered.crop(box).convert("RGB")
    without_text = background.crop(box).convert("RGB")
    difference = ImageChops.difference(actual, without_text).convert("L")
    try:
        pixels = tuple(difference.get_flattened_data())
        if not pixels or max(pixels) - min(pixels) <= 8:
            return False
        active_columns = 0
        for x in range(difference.width):
            column = [difference.getpixel((x, y)) for y in range(difference.height)]
            active_columns += max(column) - min(column) > 8
        active_rows = 0
        for y in range(difference.height):
            row = [difference.getpixel((x, y)) for x in range(difference.width)]
            active_rows += max(row) - min(row) > 8
        return (
            active_columns >= max(1, math.ceil(difference.width * 0.12))
            and active_rows >= max(1, math.ceil(difference.height * 0.12))
        )
    finally:
        difference.close()
        without_text.close()
        actual.close()


def _path_is_opaque_fill(item: object) -> bool:
    fill_mode = ctypes.c_int()
    stroke = ctypes.c_int()
    if not pdfium.raw.FPDFPath_GetDrawMode(
        item.raw, ctypes.byref(fill_mode), ctypes.byref(stroke)
    ):
        return True
    if fill_mode.value == 0:
        return False
    red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))
    if not pdfium.raw.FPDFPageObj_GetFillColor(
        item.raw,
        ctypes.byref(red),
        ctypes.byref(green),
        ctypes.byref(blue),
        ctypes.byref(alpha),
    ):
        return True
    return alpha.value >= 250


def _regions_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return (
        min(first[2], second[2]) - max(first[0], second[0]) > 0.25
        and min(first[3], second[3]) - max(first[1], second[1]) > 0.25
    )


def _pdfium_visible_layout(
    pdf_content: bytes,
) -> tuple[list[_PositionedText], list[_VerticalBarrier], bool]:
    positioned: list[_PositionedText] = []
    barriers: list[_VerticalBarrier] = []
    unsafe = False
    document = pdfium.PdfDocument(pdf_content)
    try:
        for page_number in range(len(document)):
            page = document[page_number]
            text_page = None
            bitmap = None
            rendered = None
            background_bitmap = None
            background = None
            objects: list[object] = []
            try:
                width, height = page.get_size()
                scale = 2.0
                if (
                    not all(math.isfinite(value) and value > 0 for value in (width, height))
                    or width * scale > 8_192
                    or height * scale > 8_192
                    or width * height * scale * scale > 32_000_000
                ):
                    raise ValueError("PDF page exceeds fidelity raster limits")
                text_page = page.get_textpage()
                bitmap = page.render(scale=scale)
                rendered = bitmap.to_pil()
                prior_text_regions: list[tuple[float, float, float, float]] = []
                direct_text_objects: list[object] = []
                objects = list(page.get_objects(max_depth=15, textpage=text_page))
                glyph_regions: list[tuple[float, float, float, float]] = []
                for character_index in range(text_page.count_chars()):
                    character = text_page.get_text_range(character_index, 1)
                    if not character or character.isspace():
                        continue
                    glyph_bounds = tuple(
                        float(value) for value in text_page.get_charbox(character_index)
                    )
                    if (
                        len(glyph_bounds) != 4
                        or not all(math.isfinite(value) for value in glyph_bounds)
                        or glyph_bounds[0] < -0.5
                        or glyph_bounds[1] < -0.5
                        or glyph_bounds[2] > width + 0.5
                        or glyph_bounds[3] > height + 0.5
                        or glyph_bounds[2] <= glyph_bounds[0]
                        or glyph_bounds[3] <= glyph_bounds[1]
                    ):
                        unsafe = True
                    else:
                        glyph_regions.append(glyph_bounds)
                for item in objects:
                    bounds = tuple(float(value) for value in item.get_bounds())
                    if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
                        unsafe = True
                        continue
                    left, bottom, right, top = bounds
                    inside_page = (
                        left >= -0.5
                        and bottom >= -0.5
                        and right <= width + 0.5
                        and top <= height + 0.5
                        and right > left
                        and top > bottom
                    )
                    if item.type == pdfium.raw.FPDF_PAGEOBJ_TEXT:
                        text = _normalized_visible_text(item.extract())
                        matrix = item.get_matrix()
                        horizontal_scale = math.hypot(float(matrix.a), float(matrix.b))
                        vertical_scale = math.hypot(float(matrix.c), float(matrix.d))
                        if not text:
                            if horizontal_scale < 0.05 or vertical_scale < 0.05:
                                unsafe = True
                            continue
                        if (
                            not inside_page
                            or horizontal_scale < 0.25
                            or vertical_scale < 0.25
                        ):
                            unsafe = True
                        if item.container is None:
                            direct_text_objects.append(item)
                        else:
                            unsafe = True
                        prior_text_regions.append(bounds)
                        positioned.append(
                            _PositionedText(
                                page_number,
                                text,
                                left,
                                bottom,
                                max(float(item.get_font_size()), top - bottom),
                                right,
                                bottom,
                                top,
                            )
                        )
                    elif item.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                        if not inside_page or right - left < 0.5 or top - bottom < 0.5:
                            unsafe = True
                    elif (
                        item.type == pdfium.raw.FPDF_PAGEOBJ_PATH
                        and right - left <= 3.0
                        and top - bottom >= 3.0
                    ):
                        barriers.append(
                            _VerticalBarrier(page_number, left, right, bottom, top)
                        )
                    if (
                        item.type == pdfium.raw.FPDF_PAGEOBJ_PATH
                        and _path_is_opaque_fill(item)
                        and any(_regions_overlap(bounds, region) for region in prior_text_regions)
                    ):
                        unsafe = True
                for item in direct_text_objects:
                    page.remove_obj(item)
                if direct_text_objects:
                    page.gen_content()
                background_bitmap = page.render(scale=scale)
                background = background_bitmap.to_pil()
                if any(
                    not _raster_region_is_observably_painted(
                        rendered,
                        background,
                        bounds,
                        page_height=height,
                        scale=scale,
                    )
                    for bounds in glyph_regions
                ):
                    unsafe = True
            finally:
                if background is not None:
                    background.close()
                if background_bitmap is not None:
                    background_bitmap.close()
                if rendered is not None:
                    rendered.close()
                if bitmap is not None:
                    bitmap.close()
                for item in objects:
                    item.close()
                if text_page is not None:
                    text_page.close()
                page.close()
    finally:
        document.close()
    return positioned, barriers, unsafe


def _text_show_has_content(operator: bytes, operands: list[object]) -> bool:
    if not operands:
        return False
    values: object = operands[0]
    if operator == b'"' and len(operands) >= 3:
        values = operands[2]
    if operator == b"TJ" and isinstance(values, (list, tuple)):
        return any(
            isinstance(value, (str, bytes)) and bool(value)
            for value in values
        )
    return isinstance(values, (str, bytes)) and bool(values)


def _fragment_sequence_end(
    expected: str,
    fragments: list[_PositionedText],
    start: int,
    barriers: list[_VerticalBarrier],
) -> int | None:
    target = _lexical_tokens(expected)
    observed: list[str] = []
    previous: _PositionedText | None = None
    for index in range(start, len(fragments)):
        fragment = fragments[index]
        if previous is not None:
            line_tolerance = max(3.0, 0.35 * max(previous.font_size, fragment.font_size))
            estimated_end = previous.x + len(previous.text) * previous.font_size * 0.6
            horizontal_tolerance = max(18.0, 1.5 * max(previous.font_size, fragment.font_size))
            crosses_barrier = any(
                barrier.page == fragment.page
                and barrier.left < fragment.x
                and barrier.right > previous.right
                and barrier.bottom <= max(previous.top, fragment.top)
                and barrier.top >= min(previous.bottom, fragment.bottom)
                for barrier in barriers
            )
            if (
                fragment.page != previous.page
                or abs(fragment.y - previous.y) > line_tolerance
                or fragment.x < previous.x
                or fragment.x > estimated_end + horizontal_tolerance
                or crosses_barrier
            ):
                return None
        observed.extend(_lexical_tokens(fragment.text))
        observed_tuple = tuple(observed)
        if observed_tuple == target:
            return index + 1
        if observed_tuple != target[: len(observed_tuple)]:
            return None
        previous = fragment
    return None


def _table_rows_match(
    rows: list[tuple[str, ...]],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    for row in rows:
        row_matches = False
        for anchor in positioned:
            line_tolerance = max(3.0, 0.35 * anchor.font_size)
            line = sorted(
                (
                    fragment
                    for fragment in positioned
                    if fragment.page == anchor.page
                    and abs(fragment.y - anchor.y) <= line_tolerance
                ),
                key=lambda fragment: fragment.x,
            )
            cursor = 0
            matched = True
            for cell in row:
                end = None
                for start in range(cursor, len(line)):
                    end = _fragment_sequence_end(cell, line, start, barriers)
                    if end is not None:
                        break
                if end is None:
                    matched = False
                    break
                cursor = end
            if matched:
                row_matches = True
                break
        if not row_matches:
            return False
    return True


def _validate_pdf_fidelity(word_content: bytes, pdf_content: bytes) -> None:
    """Reject converter output that is not observably derived from the bound Word."""
    try:
        with ZipFile(BytesIO(word_content)) as package:
            word_fragments: list[str] = []
            document_fragments: list[str] = []
            repeatable_fragments: list[str] = []
            xml_roots: dict[str, ElementTree.Element] = {}
            table_rows: list[tuple[str, ...]] = []
            for name in package.namelist():
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                root = ElementTree.fromstring(package.read(name))
                xml_roots[name] = root
                fragments = [item.text for item in root.iter(f"{_W}t") if item.text and item.text.strip()]
                word_fragments.extend(fragments)
                if name == "word/document.xml":
                    document_fragments.extend(fragments)
                elif name.startswith(("word/header", "word/footer")):
                    repeatable_fragments.extend(fragments)
                for row in root.iter(f"{_W}tr"):
                    cells = tuple(
                        _normalized_visible_text(" ".join(item.text or "" for item in cell.iter(f"{_W}t")))
                        for cell in row.findall(f"{_W}tc")
                    )
                    if len(cells) > 1 and all(cells):
                        table_rows.append(cells)
            word_images = _ordered_word_image_signatures(package, xml_roots)
        reader = PdfReader(BytesIO(pdf_content), strict=True)
        extracted_pages: list[str] = []
        unsafe_text = False
        pdf_images: list[tuple[float, tuple[float, ...], tuple[float, ...], tuple[bool, ...]]] = []
        for page_number, page in enumerate(reader.pages):
            if _has_nonvisible_text(page, reader):
                unsafe_text = True
            extracted_pages.append(page.extract_text() or "")
            pdf_images.extend(_ordered_pdf_image_signatures(page, reader))
        pdf_text = _normalized_visible_text("\n".join(extracted_pages))
        positioned, barriers, pdfium_unsafe = _pdfium_visible_layout(pdf_content)
        unsafe_text = unsafe_text or pdfium_unsafe
    except (BadZipFile, KeyError, ElementTree.ParseError, PdfReadError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError("final PDF fidelity cannot be verified") from exc
    source_tokens = _lexical_tokens(" ".join(word_fragments))
    pdf_tokens = _lexical_tokens(pdf_text)
    source_counts = Counter(source_tokens)
    pdf_counts = Counter(pdf_tokens)
    repeatable_counts = Counter(_lexical_tokens(" ".join(repeatable_fragments)))
    page_repetitions = max(len(reader.pages) - 1, 0)
    token_counts_match = all(pdf_counts[token] >= count for token, count in source_counts.items()) and all(
        count <= source_counts[token] + repeatable_counts[token] * page_repetitions
        for token, count in pdf_counts.items()
    )
    document_tokens = _lexical_tokens(" ".join(document_fragments))
    token_cursor = iter(pdf_tokens)
    document_order_matches = all(any(candidate == token for candidate in token_cursor) for token in document_tokens)

    images_match = _ordered_image_signatures_match(word_images, pdf_images)
    tables_match = _table_rows_match(table_rows, positioned, barriers)
    if (
        not source_tokens
        or unsafe_text
        or not token_counts_match
        or not document_order_matches
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


def validate_delivery_artifact(content: bytes, output_format: str) -> tuple[str, int, str]:
    """Validate bytes admitted to a professional Delivery package."""
    result = validate_final_artifact(content, output_format)
    if output_format == "PDF":
        reader = PdfReader(BytesIO(content), strict=True)
        marker = reader.trailer["/Root"].get("/DiagnosticOnly")
        if marker is not None:
            marker = marker.get_object()
        if isinstance(marker, BooleanObject) and marker.value is True:
            raise ValueError("diagnostic PDF cannot be a Delivery artifact")
    return result


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
    digest, size, _ = validate_delivery_artifact(content, output_format)
    if size != expected_size or digest != expected_sha256:
        raise ValueError("reopened artifact bytes diverge from finalized manifest")
