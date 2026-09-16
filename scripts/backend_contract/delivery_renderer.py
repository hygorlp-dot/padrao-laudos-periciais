"""Protected delivery rendering and final-byte integrity checks."""

from __future__ import annotations

from collections import Counter
import ctypes
from dataclasses import dataclass, replace
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

from PIL import Image, ImageChops, ImageFilter, ImageStat, UnidentifiedImageError
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
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_MIN_OBSERVABLE_TEXT_POINTS = 4.0
ElementTree.register_namespace("w", "http://schemas.openxmlformats.org/wordprocessingml/2006/main")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter_named(root: ElementTree.Element, name: str):
    return (item for item in root.iter() if _local_name(item.tag) == name)


def _children_named(root: ElementTree.Element, name: str):
    return (item for item in root if _local_name(item.tag) == name)


def _first_named(root: ElementTree.Element | None, name: str):
    if root is None:
        return None
    return next(_iter_named(root, name), None)


def _attribute_named(root: ElementTree.Element, name: str) -> str | None:
    values = [
        value for key, value in root.attrib.items() if _local_name(key) == name
    ]
    if len(values) > 1:
        raise ValueError("ambiguous Word XML attribute")
    return values[0] if values else None


def _word_part_priority(name: str) -> tuple[int, str]:
    return (
        0 if "/header" in name else 1 if name == "word/document.xml" else 2,
        name,
    )


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


def _image_signature(
    image: Image.Image, *, premultiplied_alpha: bool = False
) -> tuple:
    rgba = image.convert("RGBA")
    if premultiplied_alpha:
        straight = Image.new("RGBA", rgba.size)
        straight.putdata(
            [
                (
                    min(255, round(red * 255 / alpha)),
                    min(255, round(green * 255 / alpha)),
                    min(255, round(blue * 255 / alpha)),
                    alpha,
                )
                if alpha
                else (0, 0, 0, 0)
                for red, green, blue, alpha in rgba.get_flattened_data()
            ]
        )
        rgba = straight
    rgb = Image.new("RGB", rgba.size)
    rgb.putdata(
        [
            (
                round(red * alpha / 255),
                round(green * alpha / 255),
                round(blue * alpha / 255),
            )
            for red, green, blue, alpha in rgba.get_flattened_data()
        ]
    )
    alpha = rgba.getchannel("A").resize((16, 16))
    alpha_pixels = tuple(alpha.get_flattened_data())
    alpha_mean = sum(alpha_pixels) / len(alpha_pixels)

    def visual_signature(candidate: Image.Image) -> tuple:
        resized = candidate.resize((32, 32))
        statistics = ImageStat.Stat(resized)
        gray = resized.convert("L").resize((16, 16))
        pixels = tuple(gray.get_flattened_data())
        mean = sum(pixels) / len(pixels)
        color_grid = tuple(resized.get_flattened_data())

        return (
            tuple(round(value, 1) for value in statistics.mean),
            tuple(round(value, 1) for value in statistics.stddev),
            tuple(value >= mean for value in pixels),
            color_grid,
        )

    raw_signature = visual_signature(rgb)
    return (
        round(image.width / max(image.height, 1), 2),
        *raw_signature,
        round(alpha_mean, 1),
        round(ImageStat.Stat(alpha).stddev[0], 1),
        tuple(value >= alpha_mean for value in alpha_pixels),
    )


def _ordered_image_signatures_match(sources: list[tuple], candidates: list[tuple]) -> bool:
    def visual_matches(first: tuple, second: tuple) -> bool:
        def correlation(
            source_values: list[int], candidate_values: list[int]
        ) -> float | None:
            source_mean = sum(source_values) / len(source_values)
            candidate_mean = sum(candidate_values) / len(candidate_values)
            source_energy = sum(
                (value - source_mean) ** 2 for value in source_values
            )
            candidate_energy = sum(
                (value - candidate_mean) ** 2 for value in candidate_values
            )
            source_stddev = math.sqrt(source_energy / len(source_values))
            candidate_stddev = math.sqrt(candidate_energy / len(candidate_values))
            if max(source_stddev, candidate_stddev) < 2:
                return None
            if not source_energy or not candidate_energy:
                return -1
            covariance = sum(
                (source - source_mean) * (candidate - candidate_mean)
                for source, candidate in zip(source_values, candidate_values)
            )
            return covariance / math.sqrt(source_energy * candidate_energy)

        correlations = [
            correlation(
                [pixel[channel] for pixel in first[3]],
                [pixel[channel] for pixel in second[3]],
            )
            for channel in range(3)
        ]
        local_correlations: list[float | None] = []
        for block_y in range(0, 32, 8):
            for block_x in range(0, 32, 8):
                indices = [
                    y * 32 + x
                    for y in range(block_y, block_y + 8)
                    for x in range(block_x, block_x + 8)
                ]
                for channel in range(3):
                    local_correlations.append(
                        correlation(
                            [first[3][index][channel] for index in indices],
                            [second[3][index][channel] for index in indices],
                        )
                    )
        source_image = Image.new("RGB", (32, 32))
        source_image.putdata(first[3])
        candidate_image = Image.new("RGB", (32, 32))
        candidate_image.putdata(second[3])
        # Preserve near-exact low-contrast Word resampling without relying on
        # unstable correlation over channels whose dynamic range is tiny.
        raw_color_deltas = [
            max(abs(source[channel] - candidate[channel]) for channel in range(3))
            for source, candidate in zip(first[3], second[3])
        ]
        raw_color_delta = max(raw_color_deltas)
        raw_mean_delta = sum(raw_color_deltas) / len(raw_color_deltas)
        blurred_source = source_image.filter(ImageFilter.GaussianBlur(1.5))
        blurred_candidate = candidate_image.filter(ImageFilter.GaussianBlur(1.5))
        # Low-pass residuals separate codec/resampling noise from spatially
        # moved visible regions, including edits that straddle the 8x8 blocks.
        blurred_color_deltas = [
            max(abs(source[channel] - candidate[channel]) for channel in range(3))
            for source, candidate in zip(
                blurred_source.get_flattened_data(),
                blurred_candidate.get_flattened_data(),
            )
        ]
        blurred_color_delta = max(blurred_color_deltas)
        blurred_mean_delta = sum(blurred_color_deltas) / len(
            blurred_color_deltas
        )

        def detail_energy(image: Image.Image) -> tuple[float, float, float]:
            low_pass = image.filter(ImageFilter.GaussianBlur(1))
            pixels = tuple(image.get_flattened_data())
            low_pass_pixels = tuple(low_pass.get_flattened_data())
            return tuple(
                math.sqrt(
                    sum(
                        (pixel[channel] - smooth[channel]) ** 2
                        for pixel, smooth in zip(pixels, low_pass_pixels)
                    )
                    / len(pixels)
                )
                for channel in range(3)
            )

        source_detail = detail_energy(source_image)
        candidate_detail = detail_energy(candidate_image)
        transformed_residuals: list[tuple[float, int]] = []
        candidate_pixels = tuple(candidate_image.get_flattened_data())
        for radius in (0.0, 0.5, 1.0, 1.5):
            transformed_source = (
                source_image
                if radius == 0
                else source_image.filter(ImageFilter.GaussianBlur(radius))
            )
            deltas = [
                max(abs(source[channel] - candidate[channel]) for channel in range(3))
                for source, candidate in zip(
                    transformed_source.get_flattened_data(), candidate_pixels
                )
            ]
            transformed_residuals.append((sum(deltas) / len(deltas), max(deltas)))
        transformed_mean_delta, transformed_max_delta = min(
            transformed_residuals, key=lambda residual: residual[0]
        )
        spatial_structure_matches = (
            sum(a != b for a, b in zip(first[2], second[2])) <= 16
            and all(value is None or value >= 0.85 for value in correlations)
            and all(value is None or value >= 0.25 for value in local_correlations)
        )
        return (
            all(abs(a - b) <= 4 for a, b in zip(first[0], second[0]))
            and all(abs(a - b) <= 12 for a, b in zip(first[1], second[1]))
            and raw_mean_delta <= 24
            and raw_color_delta <= 192
            and blurred_mean_delta <= 12
            and blurred_color_delta <= 50
            and all(
                candidate <= source * 1.1 + 2
                for source, candidate in zip(source_detail, candidate_detail)
            )
            and raw_color_delta <= max(16, raw_mean_delta * 9)
            and blurred_color_delta <= max(12, blurred_mean_delta * 9)
            # The best source-derived transform is an independent reference.
            # Keep both budgets fixed so candidate-wide padding cannot inflate
            # the admissible maximum and conceal a localized alteration.
            and transformed_mean_delta <= 12
            # Microsoft Word preserves the embedded image payload in the
            # supported native conversion path.  A small fixed residual keeps
            # ordinary lossy encoding/resampling admissible without giving a
            # candidate enough localized budget to exchange visible markers.
            and transformed_max_delta <= 12
            and (raw_color_delta <= 12 or spatial_structure_matches)
        )

    def matches(source: tuple, candidate: tuple) -> bool:
        return (
            abs(source[0] - candidate[0]) <= 0.05
            and abs(source[5] - candidate[5]) <= 8
            and abs(source[6] - candidate[6]) <= 8
            and sum(a != b for a, b in zip(source[7], candidate[7])) <= 16
            and visual_matches(source[1:5], candidate[1:5])
        )

    return len(sources) == len(candidates) and all(
        matches(source, candidate) for source, candidate in zip(sources, candidates)
    )


def _ordered_word_image_signatures(package: ZipFile, xml_roots: dict[str, ElementTree.Element]) -> list[tuple]:
    ordered: list[tuple] = []
    for name in sorted(xml_roots, key=_word_part_priority):
        base = posixpath.dirname(name)
        relationships_name = f"{base}/_rels/{posixpath.basename(name)}.rels"
        if relationships_name not in package.namelist():
            continue
        relationships = ElementTree.fromstring(package.read(relationships_name))
        targets = {
            _attribute_named(item, "Id"): posixpath.normpath(
                posixpath.join(base, _attribute_named(item, "Target") or "")
            )
            for item in _iter_named(relationships, "Relationship")
            if (_attribute_named(item, "TargetMode") or "").lower() != "external"
        }
        for image_node in xml_roots[name].iter():
            if _local_name(image_node.tag) == "blip":
                relationship_id = _attribute_named(image_node, "embed")
            elif _local_name(image_node.tag) == "imagedata":
                relationship_id = _attribute_named(image_node, "id")
            else:
                continue
            target = targets.get(relationship_id)
            if target and target in package.namelist():
                with Image.open(BytesIO(package.read(target))) as image:
                    ordered.append(_image_signature(image))
    return ordered


@dataclass(frozen=True, slots=True)
class _WordImageLayout:
    width: float
    height: float
    kind: str
    alignment: str | None
    x_offset: float | None
    y_offset: float | None
    preceding_text: str | None = None
    following_text: str | None = None
    preceding_occurrence: int | None = None
    following_occurrence: int | None = None


@dataclass(frozen=True, slots=True)
class _PdfImageLayout:
    page: int
    left: float
    bottom: float
    right: float
    top: float
    page_width: float
    page_height: float


@dataclass(frozen=True, slots=True)
class _PaintedPath:
    page: int
    left: float
    bottom: float
    right: float
    top: float


@dataclass(frozen=True, slots=True)
class _WordTableExpectation:
    rows: tuple[tuple[str, ...], ...]
    width: float | None
    column_count: int
    painted_path_count: int


def _ordered_word_image_layouts(
    xml_roots: dict[str, ElementTree.Element],
) -> list[_WordImageLayout | None]:
    ordered: list[_WordImageLayout | None] = []

    for name in sorted(xml_roots, key=_word_part_priority):
        root = xml_roots[name]
        layouts_by_image: dict[int, _WordImageLayout | None] = {}
        for paragraph in _iter_named(root, "p"):
            paragraph_properties = next(_children_named(paragraph, "pPr"), None)
            alignment_node = _first_named(paragraph_properties, "jc")
            alignment = (
                (_attribute_named(alignment_node, "val") or "left").casefold()
                if alignment_node is not None
                else "left"
            )
            for drawing in _iter_named(paragraph, "drawing"):
                extent = _first_named(drawing, "extent")
                layout: _WordImageLayout | None = None
                if extent is not None:
                    try:
                        width = float(_attribute_named(extent, "cx") or "") / 12_700
                        height = float(_attribute_named(extent, "cy") or "") / 12_700
                        container = next(
                            (
                                node
                                for node in drawing
                                if _local_name(node.tag) in {"inline", "anchor"}
                            ),
                            None,
                        )
                        if not all(
                            math.isfinite(value) and value > 0
                            for value in (width, height)
                        ) or container is None:
                            raise ValueError("invalid Word image layout")
                        if _local_name(container.tag) == "inline":
                            layout = _WordImageLayout(
                                width, height, "inline", alignment, None, None
                            )
                        else:
                            horizontal = next(_children_named(container, "positionH"), None)
                            vertical = next(_children_named(container, "positionV"), None)
                            horizontal_offset = (
                                _first_named(horizontal, "posOffset")
                                if horizontal is not None
                                else None
                            )
                            vertical_offset = (
                                _first_named(vertical, "posOffset")
                                if vertical is not None
                                else None
                            )
                            if (
                                horizontal is None
                                or vertical is None
                                or _attribute_named(horizontal, "relativeFrom") != "page"
                                or _attribute_named(vertical, "relativeFrom") != "page"
                                or horizontal_offset is None
                                or vertical_offset is None
                            ):
                                raise ValueError("unsupported Word image anchor")
                            x_offset = float(horizontal_offset.text or "") / 12_700
                            y_offset = float(vertical_offset.text or "") / 12_700
                            if not all(
                                math.isfinite(value) and value >= 0
                                for value in (x_offset, y_offset)
                            ):
                                raise ValueError("invalid Word image anchor")
                            layout = _WordImageLayout(
                                width,
                                height,
                                "anchor",
                                None,
                                x_offset,
                                y_offset,
                            )
                    except (KeyError, StopIteration, TypeError, ValueError):
                        layout = None
                for image_node in _iter_named(drawing, "blip"):
                    layouts_by_image[id(image_node)] = layout
        flow: list[tuple[str, str | ElementTree.Element]] = []
        for paragraph in _iter_named(root, "p"):
            text_buffer: list[str] = []
            for item in paragraph.iter():
                local_name = _local_name(item.tag)
                if local_name == "t" and item.text:
                    text_buffer.append(item.text)
                elif local_name in {"blip", "imagedata"}:
                    text = "".join(text_buffer)
                    if text.strip():
                        flow.append(("text", text))
                    text_buffer = []
                    flow.append(("image", item))
            text = "".join(text_buffer)
            if text.strip():
                flow.append(("text", text))

        for index, (kind, value) in enumerate(flow):
            if kind != "image" or not isinstance(value, ElementTree.Element):
                continue
            image_node = value
            preceding_index = next(
                (
                    candidate_index
                    for candidate_index in range(index - 1, -1, -1)
                    if flow[candidate_index][0] == "text"
                ),
                None,
            )
            following_index = next(
                (
                    candidate_index
                    for candidate_index in range(index + 1, len(flow))
                    if flow[candidate_index][0] == "text"
                ),
                None,
            )
            preceding_entry = flow[preceding_index] if preceding_index is not None else None
            following_entry = flow[following_index] if following_index is not None else None
            preceding = str(preceding_entry[1]).strip() if preceding_entry else None
            following = str(following_entry[1]).strip() if following_entry else None

            def occurrence(node_index: int | None) -> int | None:
                if node_index is None:
                    return None
                expected = str(flow[node_index][1])
                normalized = _normalized_visible_text(expected)
                return sum(
                    1
                    for item in flow[: node_index + 1]
                    if item[0] == "text"
                    and _normalized_visible_text(str(item[1])) == normalized
                ) - 1

            if _local_name(image_node.tag) == "blip":
                layout = layouts_by_image.get(id(image_node))
                ordered.append(
                    replace(
                        layout,
                        preceding_text=preceding,
                        following_text=following,
                        preceding_occurrence=occurrence(preceding_index),
                        following_occurrence=occurrence(following_index),
                    )
                    if layout is not None
                    else None
                )
            else:
                ordered.append(None)
    return ordered


def _ordered_pdf_image_signatures(page: object, reader: PdfReader) -> list[tuple]:
    images = {str(name): page.images[name].image for name in page.images.keys()}
    try:
        xobjects = page["/Resources"].get_object().get("/XObject", {}).get_object()
        matted_images = set()
        for name in images:
            soft_mask = xobjects[name].get_object().get("/SMask")
            if soft_mask is None:
                continue
            matte = soft_mask.get_object().get("/Matte")
            if matte is not None and tuple(float(value) for value in matte) == (
                0.0,
                0.0,
                0.0,
            ):
                matted_images.add(str(name))
    except (AttributeError, KeyError, TypeError, ValueError):
        matted_images = set()
    ordered: list[tuple] = []
    for operands, operator in ContentStream(page.get_contents(), reader).operations:
        if operator != b"Do" or not operands:
            continue
        image = images.get(str(operands[0]))
        if image is not None:
            ordered.append(
                _image_signature(
                    image,
                    premultiplied_alpha=str(operands[0]) in matted_images,
                )
            )
    return ordered


def _ordered_image_layouts_match(
    sources: list[_WordImageLayout | None],
    candidates: list[_PdfImageLayout],
    positioned_text: list[_PositionedText],
) -> bool:
    def matching_regions(
        expected: str | None,
    ) -> list[tuple[int, float, float, int, int]]:
        if not expected:
            return []
        regions: list[tuple[int, float, float, int, int]] = []
        for start in range(len(positioned_text)):
            end = _fragment_sequence_end(expected, positioned_text, start, [])
            if end is None:
                continue
            fragments = positioned_text[start:end]
            if fragments and len({fragment.page for fragment in fragments}) == 1:
                regions.append(
                    (
                        fragments[0].page,
                        min(fragment.bottom for fragment in fragments),
                        max(fragment.top for fragment in fragments),
                        start,
                        end,
                    )
                )
        return regions

    if len(sources) != len(candidates) or any(source is None for source in sources):
        return False
    previous_inline: _PdfImageLayout | None = None
    for source, candidate in zip(sources, candidates):
        if source is None:
            return False
        observed_width = candidate.right - candidate.left
        observed_height = candidate.top - candidate.bottom
        if not all(
            abs(observed - expected) <= max(1.0, expected * 0.05)
            for expected, observed in (
                (source.width, observed_width),
                (source.height, observed_height),
            )
        ):
            return False
        if source.kind == "anchor":
            observed_y_offset = candidate.page_height - candidate.top
            if (
                source.x_offset is None
                or source.y_offset is None
                or abs(candidate.left - source.x_offset) > 2.0
                or abs(observed_y_offset - source.y_offset) > 2.0
            ):
                return False
        elif source.alignment in {"left", "start"}:
            if candidate.left > candidate.page_width * 0.45:
                return False
        elif source.alignment in {"right", "end"}:
            if candidate.right < candidate.page_width * 0.55:
                return False
        elif source.alignment == "center":
            center = (candidate.left + candidate.right) / 2
            if abs(center - candidate.page_width / 2) > candidate.page_width * 0.15:
                return False
        else:
            return False
        if source.kind == "inline":
            if previous_inline is not None and (
                candidate.page < previous_inline.page
                or (
                    candidate.page == previous_inline.page
                    and candidate.top > previous_inline.top + 2.0
                )
            ):
                return False
            preceding_regions = matching_regions(source.preceding_text)
            following_regions = matching_regions(source.following_text)
            if source.preceding_occurrence is not None:
                preceding_regions = preceding_regions[
                    source.preceding_occurrence : source.preceding_occurrence + 1
                ]
            if source.following_occurrence is not None:
                following_regions = following_regions[
                    source.following_occurrence : source.following_occurrence + 1
                ]
            if source.preceding_text and not preceding_regions:
                return False
            if source.following_text and not following_regions:
                return False
            if not source.preceding_text and not source.following_text:
                return False
            if preceding_regions and not any(
                page == candidate.page
                and candidate.top <= bottom + 2.0
                and bottom - candidate.top <= 72.0
                for page, bottom, _top, _start, _end in preceding_regions
            ):
                return False
            if following_regions and not any(
                page == candidate.page
                and candidate.bottom >= top - 2.0
                and candidate.bottom - top <= 72.0
                for page, _bottom, top, _start, _end in following_regions
            ):
                return False
            previous_inline = candidate
    return True


def _repeatable_word_images_match(
    *,
    document_signatures: list[tuple],
    document_layouts: list[_WordImageLayout | None],
    header_signatures: list[tuple],
    header_layouts: list[_WordImageLayout | None],
    footer_signatures: list[tuple],
    footer_layouts: list[_WordImageLayout | None],
    candidate_signatures: list[tuple],
    candidate_layouts: list[_PdfImageLayout],
    positioned_text: list[_PositionedText],
    page_count: int,
) -> bool:
    if (
        len(candidate_signatures) != len(candidate_layouts)
        or len(document_signatures) != len(document_layouts)
        or len(header_signatures) != len(header_layouts)
        or len(footer_signatures) != len(footer_layouts)
        or page_count < 1
    ):
        return False

    def repeatable_layout_matches(
        source: _WordImageLayout | None,
        candidate: _PdfImageLayout,
        *,
        region: str,
    ) -> bool:
        if source is None:
            return False
        observed_width = candidate.right - candidate.left
        observed_height = candidate.top - candidate.bottom
        if not all(
            abs(observed - expected) <= max(1.0, expected * 0.05)
            for expected, observed in (
                (source.width, observed_width),
                (source.height, observed_height),
            )
        ):
            return False
        if region == "header" and candidate.bottom < candidate.page_height * 0.75:
            return False
        if region == "footer" and candidate.top > candidate.page_height * 0.25:
            return False
        if source.kind == "anchor":
            observed_y_offset = candidate.page_height - candidate.top
            return (
                source.x_offset is not None
                and source.y_offset is not None
                and abs(candidate.left - source.x_offset) <= 2.0
                and abs(observed_y_offset - source.y_offset) <= 2.0
            )
        if source.kind != "inline":
            return False
        if source.alignment in {"left", "start"}:
            return candidate.left <= candidate.page_width * 0.45
        if source.alignment in {"right", "end"}:
            return candidate.right >= candidate.page_width * 0.55
        if source.alignment == "center":
            center = (candidate.left + candidate.right) / 2
            return abs(center - candidate.page_width / 2) <= candidate.page_width * 0.15
        return False

    used: set[int] = set()

    def consume_repeated(
        signatures: list[tuple],
        layouts: list[_WordImageLayout | None],
        *,
        region: str,
    ) -> bool:
        if not signatures:
            return True
        for page in range(page_count):
            search_start = 0
            for signature, layout in zip(signatures, layouts):
                selected = next(
                    (
                        index
                        for index in range(search_start, len(candidate_signatures))
                        if index not in used
                        and candidate_layouts[index].page == page
                        and repeatable_layout_matches(
                            layout, candidate_layouts[index], region=region
                        )
                        and _ordered_image_signatures_match(
                            [signature], [candidate_signatures[index]]
                        )
                    ),
                    None,
                )
                if selected is None:
                    return False
                used.add(selected)
                search_start = selected + 1
        return True

    if not consume_repeated(
        header_signatures, header_layouts, region="header"
    ) or not consume_repeated(footer_signatures, footer_layouts, region="footer"):
        return False
    remaining_signatures = [
        signature
        for index, signature in enumerate(candidate_signatures)
        if index not in used
    ]
    remaining_layouts = [
        layout for index, layout in enumerate(candidate_layouts) if index not in used
    ]
    return _ordered_image_signatures_match(
        document_signatures, remaining_signatures
    ) and _ordered_image_layouts_match(
        document_layouts, remaining_layouts, positioned_text
    )


def _content_kinds_are_ordered_subsequence(
    expected: tuple[str, ...], observed: tuple[str, ...]
) -> bool:
    iterator = iter(observed)
    return all(any(candidate == value for candidate in iterator) for value in expected)


def _repeatable_text_matches(
    *,
    header_fragments: list[str],
    footer_fragments: list[str],
    positioned: list[_PositionedText],
    page_heights: list[float],
) -> bool:
    def region_matches(
        expected_fragments: list[str], *, page: int, header: bool
    ) -> bool:
        if not expected_fragments:
            return True
        height = page_heights[page]
        region = [
            fragment
            for fragment in positioned
            if fragment.page == page
            and (
                fragment.bottom >= height * 0.5
                if header
                else fragment.top <= height * 0.5
            )
        ]
        cursor = 0
        for expected in expected_fragments:
            matches = [
                (start, end)
                for start in range(len(region))
                if (end := _fragment_sequence_end(expected, region, start, []))
                is not None
            ]
            if len(matches) != 1 or matches[0][0] < cursor:
                return False
            cursor = matches[0][1]
        return True

    return len(page_heights) > 0 and all(
        region_matches(header_fragments, page=page, header=True)
        and region_matches(footer_fragments, page=page, header=False)
        for page in range(len(page_heights))
    )


def _collapse_content_kinds(values: list[str]) -> tuple[str, ...]:
    return tuple(value for index, value in enumerate(values) if not index or value != values[index - 1])


def _word_content_kinds(xml_roots: dict[str, ElementTree.Element]) -> tuple[str, ...]:
    values: list[str] = []
    for name in sorted(xml_roots, key=_word_part_priority):
        for node in xml_roots[name].iter():
            local_name = _local_name(node.tag)
            if local_name == "t" and node.text and node.text.strip():
                values.append("TEXT")
            elif local_name in {"blip", "imagedata"}:
                values.append("IMAGE")
    return _collapse_content_kinds(values)


def _pdf_content_kinds(reader: PdfReader) -> tuple[str, ...]:
    values: list[str] = []
    for page in reader.pages:
        images = {str(name) for name in page.images.keys()}
        for operands, operator in ContentStream(page.get_contents(), reader).operations:
            if operator in {b"Tj", b"TJ", b"'", b'"'} and _text_show_has_content(
                operator, operands
            ):
                values.append("TEXT")
            elif operator == b"Do" and operands and str(operands[0]) in images:
                values.append("IMAGE")
    return _collapse_content_kinds(values)


def _has_annotations(page: object) -> bool:
    try:
        annotations = page.get("/Annots")
        return annotations is not None and bool(annotations.get_object())
    except (AttributeError, KeyError, TypeError, ValueError):
        return True


def _has_unsafe_image_drawing(page: object, reader: PdfReader) -> bool:
    fill_alpha = 1.0
    stroke_alpha = 1.0
    soft_mask_active = False
    clip_bounds: tuple[float, float, float, float] | None = None
    clip_is_complex = False
    path_rectangles: tuple[tuple[float, float, float, float], ...] = ()
    path_is_complex = False
    clip_pending = False
    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    transform_seen = False
    stack: list[
        tuple[
            float,
            float,
            bool,
            tuple[float, float, float, float] | None,
            bool,
            tuple[float, float, float, float, float, float],
            bool,
        ]
    ] = []
    try:
        resources = page["/Resources"].get_object()
        ext_states = resources.get("/ExtGState", {}).get_object()
    except (AttributeError, KeyError, TypeError):
        ext_states = {}
    try:
        images = {str(name) for name in page.images.keys()}
    except (AttributeError, KeyError, TypeError, ValueError):
        return True
    if not images:
        return False
    try:
        xobjects = resources.get("/XObject", {}).get_object()
        intrinsically_masked = set()
        for name in images:
            image_object = xobjects[name].get_object()
            soft_mask = image_object.get("/SMask")
            matte = (
                soft_mask.get_object().get("/Matte")
                if soft_mask is not None
                else None
            )
            if (
                bool(image_object.get("/ImageMask", False))
                or image_object.get("/Mask") not in (None, "/None")
                or (
                    matte is not None
                    and tuple(float(value) for value in matte)
                    != (0.0, 0.0, 0.0)
                )
            ):
                intrinsically_masked.add(name)
    except (AttributeError, KeyError, TypeError, ValueError):
        return True

    def apply_pending_clip() -> None:
        nonlocal clip_bounds, clip_is_complex, clip_pending
        if not clip_pending:
            return
        if path_is_complex or len(path_rectangles) != 1:
            clip_is_complex = True
        else:
            rectangle = path_rectangles[0]
            if clip_bounds is None:
                clip_bounds = rectangle
            else:
                clip_bounds = (
                    max(clip_bounds[0], rectangle[0]),
                    max(clip_bounds[1], rectangle[1]),
                    min(clip_bounds[2], rectangle[2]),
                    min(clip_bounds[3], rectangle[3]),
                )
                if clip_bounds[2] <= clip_bounds[0] or clip_bounds[3] <= clip_bounds[1]:
                    clip_is_complex = True
        clip_pending = False

    def concatenate(
        current: tuple[float, float, float, float, float, float],
        value: tuple[float, float, float, float, float, float],
    ) -> tuple[float, float, float, float, float, float]:
        a, b, c, d, e, f = current
        g, h, i, j, k, line = value
        return (
            a * g + c * h,
            b * g + d * h,
            a * i + c * j,
            b * i + d * j,
            a * k + c * line + e,
            b * k + d * line + f,
        )

    def transformed_bounds(
        left: float,
        bottom: float,
        right: float,
        top: float,
    ) -> tuple[float, float, float, float]:
        a, b, c, d, e, f = ctm
        corners = tuple(
            (a * x + c * y + e, b * x + d * y + f)
            for x, y in (
                (left, bottom),
                (right, bottom),
                (left, top),
                (right, top),
            )
        )
        return (
            min(point[0] for point in corners),
            min(point[1] for point in corners),
            max(point[0] for point in corners),
            max(point[1] for point in corners),
        )

    for operands, operator in ContentStream(page.get_contents(), reader).operations:
        if operator == b"q":
            stack.append(
                (
                    fill_alpha,
                    stroke_alpha,
                    soft_mask_active,
                    clip_bounds,
                    clip_is_complex,
                    ctm,
                    transform_seen,
                )
            )
        elif operator == b"Q":
            (
                fill_alpha,
                stroke_alpha,
                soft_mask_active,
                clip_bounds,
                clip_is_complex,
                ctm,
                transform_seen,
            ) = (
                stack.pop()
                if stack
                else (
                    1.0,
                    1.0,
                    False,
                    None,
                    False,
                    (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
                    False,
                )
            )
            path_rectangles = ()
            path_is_complex = False
            clip_pending = False
        elif operator == b"gs" and operands:
            try:
                state = ext_states[str(operands[0])].get_object()
                fill_alpha = float(state.get("/ca", fill_alpha))
                stroke_alpha = float(state.get("/CA", stroke_alpha))
                blend_mode = state.get("/BM", "/Normal")
                if blend_mode not in (None, "/Normal"):
                    return True
                if "/SMask" in state:
                    soft_mask_active = state.get("/SMask") not in (None, "/None")
            except (AttributeError, KeyError, TypeError, ValueError):
                return True
        elif operator in {b"W", b"W*"}:
            clip_pending = True
        elif operator == b"re" and len(operands) == 4:
            try:
                x, y, width, height = (float(value) for value in operands)
                path_rectangles += (
                    transformed_bounds(
                        min(x, x + width),
                        min(y, y + height),
                        max(x, x + width),
                        max(y, y + height),
                    ),
                )
                if abs(ctm[1]) > 1e-9 or abs(ctm[2]) > 1e-9:
                    path_is_complex = True
            except (TypeError, ValueError):
                return True
        elif operator in {b"m", b"l", b"c", b"v", b"y", b"h"}:
            path_is_complex = True
        elif operator in {b"n", b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}:
            apply_pending_clip()
            path_rectangles = ()
            path_is_complex = False
        elif operator == b"cm" and len(operands) == 6:
            try:
                value = tuple(float(item) for item in operands)
                if len(value) != 6 or not all(math.isfinite(item) for item in value):
                    return True
                ctm = concatenate(ctm, value)
                transform_seen = True
            except (TypeError, ValueError):
                return True
        elif operator == b"Do" and operands and str(operands[0]) in images:
            image_name = str(operands[0])
            if (
                min(fill_alpha, stroke_alpha) < 0.99
                or soft_mask_active
                or clip_pending
                or clip_is_complex
                or not transform_seen
                or image_name in intrinsically_masked
            ):
                return True
            image_bounds = transformed_bounds(0.0, 0.0, 1.0, 1.0)
            if clip_bounds is not None and not (
                clip_bounds[0] <= image_bounds[0] + 0.5
                and clip_bounds[1] <= image_bounds[1] + 0.5
                and clip_bounds[2] >= image_bounds[2] - 0.5
                and clip_bounds[3] >= image_bounds[3] - 0.5
            ):
                return True
    return False


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
    color: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True, slots=True)
class _VerticalBarrier:
    page: int
    left: float
    right: float
    bottom: float
    top: float


@dataclass(frozen=True, slots=True)
class _WordTextExpectation:
    text: str
    font_size: float
    color: tuple[int, int, int]


def _word_text_expectations(
    xml_roots: dict[str, ElementTree.Element],
) -> list[_WordTextExpectation]:
    styles_root = xml_roots.get("word/styles.xml")

    def size_from_properties(properties: ElementTree.Element | None) -> float | None:
        size_node = _first_named(properties, "sz")
        if size_node is None:
            return None
        try:
            value = float(_attribute_named(size_node, "val") or "") / 2.0
        except ValueError:
            return None
        return value if math.isfinite(value) and value > 0 else None

    def color_from_properties(
        properties: ElementTree.Element | None,
    ) -> tuple[int, int, int] | None:
        color_node = _first_named(properties, "color")
        if color_node is None:
            return None
        value = (_attribute_named(color_node, "val") or "").strip()
        if value.casefold() == "auto":
            return (0, 0, 0)
        if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
            raise ValueError("unsupported Word text color")
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))

    default_size = 11.0
    default_color = (0, 0, 0)
    default_paragraph_style: str | None = None
    style_sizes: dict[str, float | None] = {}
    style_colors: dict[str, tuple[int, int, int] | None] = {}
    style_bases: dict[str, str | None] = {}
    if styles_root is not None:
        defaults = _first_named(styles_root, "docDefaults")
        default_size = size_from_properties(defaults) or default_size
        default_color = color_from_properties(defaults) or default_color
        for style in _iter_named(styles_root, "style"):
            style_id = _attribute_named(style, "styleId")
            if not style_id:
                continue
            if (
                (_attribute_named(style, "type") or "").casefold() == "paragraph"
                and (_attribute_named(style, "default") or "").casefold()
                in {"1", "true", "on"}
            ):
                default_paragraph_style = style_id
            properties = next(_children_named(style, "rPr"), None)
            based_on = _first_named(style, "basedOn")
            style_sizes[style_id] = size_from_properties(properties)
            style_colors[style_id] = color_from_properties(properties)
            style_bases[style_id] = (
                _attribute_named(based_on, "val") if based_on is not None else None
            )

    def resolve_style(style_id: str | None, fallback: float = default_size) -> float:
        visited: set[str] = set()
        while style_id and style_id not in visited:
            visited.add(style_id)
            size = style_sizes.get(style_id)
            if size is not None:
                return size
            style_id = style_bases.get(style_id)
        return fallback

    def resolve_style_color(
        style_id: str | None,
        fallback: tuple[int, int, int] = default_color,
    ) -> tuple[int, int, int]:
        visited: set[str] = set()
        while style_id and style_id not in visited:
            visited.add(style_id)
            color = style_colors.get(style_id)
            if color is not None:
                return color
            style_id = style_bases.get(style_id)
        return fallback

    expectations: list[_WordTextExpectation] = []
    content_names = [
        name
        for name in sorted(xml_roots, key=_word_part_priority)
        if name == "word/document.xml"
        or name.startswith(("word/header", "word/footer"))
    ]
    for name in content_names:
        for paragraph in _iter_named(xml_roots[name], "p"):
            paragraph_properties = next(_children_named(paragraph, "pPr"), None)
            paragraph_style_node = _first_named(paragraph_properties, "pStyle")
            paragraph_style = (
                _attribute_named(paragraph_style_node, "val")
                if paragraph_style_node is not None
                else None
            )
            paragraph_size = resolve_style(
                paragraph_style or default_paragraph_style
            )
            paragraph_color = resolve_style_color(
                paragraph_style or default_paragraph_style
            )
            segments: list[tuple[str, float, tuple[int, int, int]]] = []
            for run in _iter_named(paragraph, "r"):
                run_properties = next(_children_named(run, "rPr"), None)
                run_style_node = _first_named(run_properties, "rStyle")
                run_style = (
                    _attribute_named(run_style_node, "val")
                    if run_style_node is not None
                    else None
                )
                size = (
                    size_from_properties(run_properties)
                    or resolve_style(run_style, paragraph_size)
                    if run_style
                    else size_from_properties(run_properties)
                    or paragraph_size
                )
                color = (
                    color_from_properties(run_properties)
                    or resolve_style_color(run_style, paragraph_color)
                    if run_style
                    else color_from_properties(run_properties)
                    or paragraph_color
                )
                raw_text = "".join(
                    item.text or ""
                    for item in _iter_named(run, "t")
                    if item.text and item.text.strip()
                )
                if not raw_text.strip():
                    continue
                if (
                    segments
                    and abs(segments[-1][1] - size) <= 0.01
                    and segments[-1][2] == color
                ):
                    previous_text, previous_size, previous_color = segments[-1]
                    segments[-1] = (
                        previous_text + raw_text,
                        previous_size,
                        previous_color,
                    )
                else:
                    segments.append((raw_text, size, color))
            expectations.extend(
                _WordTextExpectation(_normalized_visible_text(text), size, color)
                for text, size, color in segments
                if _normalized_visible_text(text)
            )
    return expectations


def _text_sizes_match(
    expectations: list[_WordTextExpectation],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    cursor = 0
    for expectation in expectations:
        match: tuple[int, int] | None = None
        for start in range(cursor, len(positioned)):
            end = _fragment_sequence_end(
                expectation.text, positioned, start, barriers
            )
            if end is None:
                continue
            tolerance = max(1.5, expectation.font_size * 0.12)
            if all(
                abs(fragment.font_size - expectation.font_size) <= tolerance
                and all(
                    abs(observed - expected) <= 8
                    for observed, expected in zip(fragment.color, expectation.color)
                )
                for fragment in positioned[start:end]
            ):
                match = (start, end)
                break
        if match is None:
            return False
        cursor = match[1]
    return bool(expectations)


def _has_nonvisible_text(page: object, reader: PdfReader) -> bool:
    render_mode = 0
    fill_alpha = 1.0
    stroke_alpha = 1.0
    blend_mode = "/Normal"
    stack: list[tuple[int, float, float, str]] = []
    try:
        resources = page["/Resources"].get_object()
        ext_states = resources.get("/ExtGState", {}).get_object()
    except (AttributeError, KeyError, TypeError):
        ext_states = {}
    text_operators = {b"Tj", b"TJ", b"'", b'"'}
    for operands, operator in ContentStream(page.get_contents(), reader).operations:
        if operator == b"q":
            stack.append((render_mode, fill_alpha, stroke_alpha, blend_mode))
        elif operator == b"Q":
            render_mode, fill_alpha, stroke_alpha, blend_mode = (
                stack.pop() if stack else (0, 1.0, 1.0, "/Normal")
            )
        elif operator == b"Tr" and operands:
            render_mode = int(operands[0])
        elif operator == b"gs" and operands:
            try:
                state = ext_states[str(operands[0])].get_object()
                fill_alpha = float(state.get("/ca", fill_alpha))
                stroke_alpha = float(state.get("/CA", stroke_alpha))
                blend_mode = str(state.get("/BM", blend_mode))
            except (AttributeError, KeyError, TypeError, ValueError):
                return True
        elif operator in text_operators and _text_show_has_content(operator, operands):
            if render_mode != 0 or blend_mode != "/Normal":
                return True
            visible_alpha = (
                fill_alpha
                if render_mode in {0, 4}
                else stroke_alpha
                if render_mode in {1, 5}
                else max(fill_alpha, stroke_alpha)
            )
            # Native Word text is emitted fully visible.  Treat materially
            # translucent text as unfaithful instead of allowing extraction
            # to stand in for what a professional reader can actually see.
            if visible_alpha < 0.99:
                return True
    return False


def _raster_region_is_observably_painted(
    rendered: Image.Image,
    background: Image.Image,
    bounds: tuple[float, float, float, float],
    *,
    page_height: float,
    scale: float,
    minimum_axis_coverage: float,
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
            active_columns
            >= max(1, math.ceil(difference.width * minimum_axis_coverage))
            and active_rows
            >= max(1, math.ceil(difference.height * minimum_axis_coverage))
        )
    finally:
        difference.close()
        without_text.close()
        actual.close()


def _page_object_fill_rgba(item: object) -> tuple[int, int, int, int] | None:
    values = tuple(ctypes.c_uint() for _ in range(4))
    if not pdfium.raw.FPDFPageObj_GetFillColor(
        item.raw,
        ctypes.byref(values[0]),
        ctypes.byref(values[1]),
        ctypes.byref(values[2]),
        ctypes.byref(values[3]),
    ):
        return None
    return tuple(int(value.value) for value in values)


def _path_has_visible_paint(item: object) -> bool:
    fill_mode = ctypes.c_int()
    stroke = ctypes.c_int()
    if not pdfium.raw.FPDFPath_GetDrawMode(
        item.raw, ctypes.byref(fill_mode), ctypes.byref(stroke)
    ):
        return True
    if fill_mode.value != 0:
        color = _page_object_fill_rgba(item)
        if color is None or color[3] > 0:
            return True
    if not stroke.value:
        return False
    values = tuple(ctypes.c_uint() for _ in range(4))
    if not pdfium.raw.FPDFPageObj_GetStrokeColor(
        item.raw,
        ctypes.byref(values[0]),
        ctypes.byref(values[1]),
        ctypes.byref(values[2]),
        ctypes.byref(values[3]),
    ):
        return True
    return values[3].value > 0


def _pdfium_visible_layout(
    pdf_content: bytes,
) -> tuple[
    list[_PositionedText],
    list[_VerticalBarrier],
    list[_PdfImageLayout],
    list[_PaintedPath],
    bool,
]:
    positioned: list[_PositionedText] = []
    barriers: list[_VerticalBarrier] = []
    image_layouts: list[_PdfImageLayout] = []
    painted_paths: list[_PaintedPath] = []
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
                direct_text_objects: list[object] = []
                objects = list(page.get_objects(max_depth=15, textpage=text_page))
                glyph_regions: list[
                    tuple[tuple[float, float, float, float], str]
                ] = []
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
                        glyph_regions.append((glyph_bounds, character))
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
                        scale_delta = abs(horizontal_scale - vertical_scale)
                        upright = (
                            float(matrix.a) > 0
                            and float(matrix.d) > 0
                            and abs(float(matrix.b)) <= 0.05 * float(matrix.a)
                            and abs(float(matrix.c)) <= 0.05 * float(matrix.d)
                        )
                        if not text:
                            if (
                                horizontal_scale < 0.05
                                or vertical_scale < 0.05
                                or not upright
                            ):
                                unsafe = True
                            continue
                        if (
                            not inside_page
                            or horizontal_scale < 0.25
                            or vertical_scale < 0.25
                            or scale_delta
                            > 0.05 * max(horizontal_scale, vertical_scale)
                            or not upright
                            or max(float(item.get_font_size()), top - bottom)
                            < _MIN_OBSERVABLE_TEXT_POINTS
                        ):
                            unsafe = True
                        if item.container is None:
                            direct_text_objects.append(item)
                        else:
                            unsafe = True
                        fill_color = _page_object_fill_rgba(item)
                        if fill_color is None or fill_color[3] < 252:
                            unsafe = True
                            text_color = (0, 0, 0)
                        else:
                            text_color = fill_color[:3]
                        positioned.append(
                            _PositionedText(
                                page_number,
                                text,
                                left,
                                bottom,
                                float(item.get_font_size()),
                                right,
                                bottom,
                                top,
                                text_color,
                            )
                        )
                    elif item.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE:
                        matrix = item.get_matrix()
                        upright = (
                            float(matrix.a) > 0
                            and float(matrix.d) > 0
                            and abs(float(matrix.b)) <= 0.05 * float(matrix.a)
                            and abs(float(matrix.c)) <= 0.05 * float(matrix.d)
                        )
                        if not inside_page or right - left < 0.5 or top - bottom < 0.5:
                            unsafe = True
                        if not upright:
                            unsafe = True
                        image_layouts.append(
                            _PdfImageLayout(
                                page_number,
                                left,
                                bottom,
                                right,
                                top,
                                width,
                                height,
                            )
                        )
                    elif (
                        item.type == pdfium.raw.FPDF_PAGEOBJ_PATH
                        and top - bottom >= 3.0
                    ):
                        barriers.append(
                            _VerticalBarrier(page_number, left, right, bottom, top)
                        )
                    if (
                        item.type == pdfium.raw.FPDF_PAGEOBJ_PATH
                        and _path_has_visible_paint(item)
                    ):
                        painted_paths.append(
                            _PaintedPath(page_number, left, bottom, right, top)
                        )
                    elif item.type not in {
                        pdfium.raw.FPDF_PAGEOBJ_TEXT,
                        pdfium.raw.FPDF_PAGEOBJ_IMAGE,
                        pdfium.raw.FPDF_PAGEOBJ_PATH,
                    }:
                        # Shadings and opaque container objects have no
                        # source-side Word authority in the supported model.
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
                        minimum_axis_coverage=(
                            0.50 if any(character.isalnum() for character in text) else 0.12
                        ),
                    )
                    for bounds, text in glyph_regions
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
    return positioned, barriers, image_layouts, painted_paths, unsafe


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
    observed_text: list[str] = []
    normalized_target = _normalized_visible_text(expected)
    previous: _PositionedText | None = None
    for index in range(start, len(fragments)):
        fragment = fragments[index]
        if previous is not None:
            line_tolerance = max(3.0, 0.35 * max(previous.font_size, fragment.font_size))
            vertical_gap = max(previous.bottom, fragment.bottom) - min(
                previous.top, fragment.top
            )
            estimated_end = previous.x + len(previous.text) * previous.font_size * 0.6
            horizontal_tolerance = max(18.0, 1.5 * max(previous.font_size, fragment.font_size))
            crosses_barrier = any(
                barrier.page == fragment.page
                and barrier.left >= previous.right - 0.5
                and barrier.right <= fragment.x + 0.5
                and barrier.bottom <= max(previous.top, fragment.top)
                and barrier.top >= min(previous.bottom, fragment.bottom)
                for barrier in barriers
            )
            if (
                fragment.page != previous.page
                or vertical_gap > line_tolerance
                or fragment.x < previous.x
                or fragment.x > estimated_end + horizontal_tolerance
                or crosses_barrier
            ):
                return None
        observed.extend(_lexical_tokens(fragment.text))
        observed_text.append(fragment.text)
        observed_tuple = tuple(observed)
        compact_text = _normalized_visible_text("".join(observed_text))
        spaced_text = _normalized_visible_text(" ".join(observed_text))
        if (
            observed_tuple == target
            or compact_text == normalized_target
            or spaced_text == normalized_target
        ):
            return index + 1
        if (
            observed_tuple != target[: len(observed_tuple)]
            and not normalized_target.startswith(compact_text)
            and not normalized_target.startswith(spaced_text)
        ):
            return None
        previous = fragment
    return None


def _ordered_text_blocks_match(
    blocks: list[str],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    cursor = 0
    for block in blocks:
        match = next(
            (
                (start, end)
                for start in range(cursor, len(positioned))
                if (end := _fragment_sequence_end(block, positioned, start, barriers))
                is not None
            ),
            None,
        )
        if match is None:
            return False
        cursor = match[1]
    return bool(blocks)


def _positioned_reading_order(
    fragments: list[_PositionedText],
) -> list[_PositionedText]:
    lines: list[list[_PositionedText]] = []
    for fragment in sorted(
        fragments, key=lambda item: (item.page, -item.top, item.x)
    ):
        matching_line = next(
            (
                line
                for line in lines
                if line[0].page == fragment.page
                and max(
                    max(item.bottom for item in line), fragment.bottom
                )
                - min(min(item.top for item in line), fragment.top)
                <= max(
                    3.0,
                    0.35
                    * max(
                        fragment.font_size,
                        *(item.font_size for item in line),
                    ),
                )
            ),
            None,
        )
        if matching_line is None:
            lines.append([fragment])
        else:
            matching_line.append(fragment)
    ordered_lines = sorted(
        lines,
        key=lambda line: (line[0].page, -max(item.top for item in line)),
    )
    return [
        fragment
        for line in ordered_lines
        for fragment in sorted(line, key=lambda item: item.x)
    ]


def _matched_table_row_fragments(
    rows: list[tuple[str, ...]],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> list[list[_PositionedText]] | None:
    previous_position: tuple[int, float] | None = None
    selected_rows: list[list[_PositionedText]] = []
    for row in rows:
        matching_positions: dict[tuple[int, float], list[_PositionedText]] = {}
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
            matched_fragments: list[_PositionedText] = []
            for cell in row:
                end = None
                for start in range(cursor, len(line)):
                    end = _fragment_sequence_end(cell, line, start, barriers)
                    if end is not None:
                        break
                if end is None:
                    matched = False
                    break
                matched_fragments.extend(line[start:end])
                cursor = end
            if matched:
                matching_positions[(anchor.page, anchor.y)] = matched_fragments
        ordered_positions = sorted(
            matching_positions,
            key=lambda value: (value[0], -value[1]),
        )
        selected = next(
            (
                position
                for position in ordered_positions
                if previous_position is None
                or position[0] > previous_position[0]
                or (
                    position[0] == previous_position[0]
                    and position[1] < previous_position[1] - 0.5
                )
            ),
            None,
        )
        if selected is None:
            return None
        selected_rows.append(matching_positions[selected])
        previous_position = selected
    return selected_rows


def _table_rows_match(
    rows: list[tuple[str, ...]],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    return _matched_table_row_fragments(rows, positioned, barriers) is not None


def _painted_paths_are_bound_to_tables(
    paths: list[_PaintedPath],
    tables: list[_WordTableExpectation],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    expected_count = sum(table.painted_path_count for table in tables)
    if len(paths) != expected_count:
        return False
    rows = [row for table in tables for row in table.rows]
    matched_rows = _matched_table_row_fragments(rows, positioned, barriers)
    if matched_rows is None:
        return False
    cursor = 0
    used: set[int] = set()
    for table in tables:
        table_rows = matched_rows[cursor : cursor + len(table.rows)]
        cursor += len(table.rows)
        if not table.painted_path_count:
            continue
        fragments = [fragment for row in table_rows for fragment in row]
        pages = {fragment.page for fragment in fragments}
        if table.width is None or len(pages) != 1 or not fragments:
            return False
        page = next(iter(pages))
        left = min(fragment.x for fragment in fragments) - 12.0
        right = min(fragment.x for fragment in fragments) + table.width + 12.0
        bottom = min(fragment.bottom for fragment in fragments) - 12.0
        top = max(fragment.top for fragment in fragments) + 12.0
        candidates = [
            index
            for index, path in enumerate(paths)
            if index not in used
            and path.page == page
            and path.left >= left
            and path.right <= right
            and path.bottom >= bottom
            and path.top <= top
            and min(path.right - path.left, path.top - path.bottom) <= 1.5
        ]
        if len(candidates) != table.painted_path_count:
            return False
        table_paths = [paths[index] for index in candidates]

        def clusters(values: list[float]) -> list[list[float]]:
            grouped: list[list[float]] = []
            for value in sorted(values):
                if not grouped or abs(value - sum(grouped[-1]) / len(grouped[-1])) > 1.0:
                    grouped.append([value])
                else:
                    grouped[-1].append(value)
            return grouped

        vertical_paths = [
            path
            for path in table_paths
            if path.top - path.bottom > 2 * (path.right - path.left)
        ]
        horizontal_paths = [
            path
            for path in table_paths
            if path.right - path.left > 2 * (path.top - path.bottom)
        ]
        x_clusters = clusters(
            [(path.left + path.right) / 2 for path in vertical_paths]
        )
        y_clusters = clusters(
            [(path.bottom + path.top) / 2 for path in horizontal_paths]
        )
        if (
            len(x_clusters) != table.column_count + 1
            or len(y_clusters) != len(table.rows) + 1
        ):
            return False
        x_centers = [sum(group) / len(group) for group in x_clusters]
        expected_width = table.width
        if abs((max(x_centers) - min(x_centers)) - expected_width) > max(
            2.0, expected_width * 0.03
        ):
            return False
        for group in y_clusters:
            center = sum(group) / len(group)
            members = [
                path
                for path in horizontal_paths
                if abs((path.bottom + path.top) / 2 - center) <= 1.0
            ]
            if (
                min(path.left for path in members) > min(x_centers) + 2.0
                or max(path.right for path in members) < max(x_centers) - 2.0
            ):
                return False
        for group in x_clusters:
            center = sum(group) / len(group)
            members = [
                path
                for path in vertical_paths
                if abs((path.left + path.right) / 2 - center) <= 1.0
            ]
            if (
                min(path.bottom for path in members)
                > min(fragment.bottom for fragment in fragments) + 2.0
                or max(path.top for path in members)
                < max(fragment.top for fragment in fragments) - 2.0
            ):
                return False
        used.update(candidates)
    return len(used) == len(paths)


def _validate_pdf_fidelity(word_content: bytes, pdf_content: bytes) -> None:
    """Reject converter output that is not observably derived from the bound Word."""
    try:
        with ZipFile(BytesIO(word_content)) as package:
            word_fragments: list[str] = []
            document_fragments: list[str] = []
            repeatable_fragments: list[str] = []
            header_fragments: list[str] = []
            footer_fragments: list[str] = []
            xml_roots: dict[str, ElementTree.Element] = {}
            table_rows: list[tuple[str, ...]] = []
            tables: list[_WordTableExpectation] = []
            for name in sorted(package.namelist(), key=_word_part_priority):
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                root = ElementTree.fromstring(package.read(name))
                xml_roots[name] = root
                fragments = [
                    "".join(item.text or "" for item in _iter_named(paragraph, "t"))
                    for paragraph in _iter_named(root, "p")
                ]
                fragments = [fragment for fragment in fragments if fragment.strip()]
                word_fragments.extend(fragments)
                if name == "word/document.xml":
                    document_fragments.extend(fragments)
                elif name.startswith("word/header"):
                    header_fragments.extend(fragments)
                    repeatable_fragments.extend(fragments)
                elif name.startswith("word/footer"):
                    footer_fragments.extend(fragments)
                    repeatable_fragments.extend(fragments)
                for table in _iter_named(root, "tbl"):
                    rows: list[tuple[str, ...]] = []
                    for row in _children_named(table, "tr"):
                        cells = tuple(
                            _normalized_visible_text(
                                " ".join(
                                    "".join(
                                        item.text or ""
                                        for item in _iter_named(paragraph, "t")
                                    )
                                    for paragraph in _iter_named(cell, "p")
                                )
                            )
                            for cell in _children_named(row, "tc")
                        )
                        if len(cells) > 1 and all(cells):
                            rows.append(cells)
                    if not rows:
                        continue
                    grid = _first_named(table, "tblGrid")
                    grid_columns = (
                        list(_children_named(grid, "gridCol"))
                        if grid is not None
                        else []
                    )
                    try:
                        grid_widths = [
                            float(_attribute_named(column, "w") or "") / 20
                            for column in grid_columns
                        ]
                    except (TypeError, ValueError):
                        grid_widths = []
                    width = (
                        sum(grid_widths)
                        if grid_widths
                        and all(math.isfinite(value) and value > 0 for value in grid_widths)
                        else None
                    )
                    style_node = _first_named(table, "tblStyle")
                    style = (
                        (_attribute_named(style_node, "val") or "")
                        .casefold()
                        .replace(" ", "")
                        if style_node is not None
                        else ""
                    )
                    row_count = len(rows)
                    column_count = len(grid_columns)
                    painted_path_count = (
                        3 * row_count * column_count
                        + 2 * row_count
                        + 2 * column_count
                        + 5
                        if style == "tablegrid" and column_count > 0
                        else 0
                    )
                    table_rows.extend(rows)
                    tables.append(
                        _WordTableExpectation(
                            tuple(rows), width, column_count, painted_path_count
                        )
                    )
            document_roots = {
                name: root
                for name, root in xml_roots.items()
                if name == "word/document.xml"
            }
            header_roots = {
                name: root
                for name, root in xml_roots.items()
                if name.startswith("word/header")
            }
            footer_roots = {
                name: root
                for name, root in xml_roots.items()
                if name.startswith("word/footer")
            }
            document_images = _ordered_word_image_signatures(package, document_roots)
            document_image_layouts = _ordered_word_image_layouts(document_roots)
            header_images = _ordered_word_image_signatures(package, header_roots)
            header_image_layouts = _ordered_word_image_layouts(header_roots)
            footer_images = _ordered_word_image_signatures(package, footer_roots)
            footer_image_layouts = _ordered_word_image_layouts(footer_roots)
            word_content_kinds = _word_content_kinds(document_roots)
            word_text_expectations = _word_text_expectations(xml_roots)
        reader = PdfReader(BytesIO(pdf_content), strict=True)
        extracted_pages: list[str] = []
        unsafe_text = False
        pdf_images: list[tuple] = []
        page_heights: list[float] = []
        for page_number, page in enumerate(reader.pages):
            if (
                _has_annotations(page)
                or _has_nonvisible_text(page, reader)
                or _has_unsafe_image_drawing(page, reader)
            ):
                unsafe_text = True
            page_heights.append(float(page.mediabox.height))
            extracted_pages.append(page.extract_text() or "")
            pdf_images.extend(_ordered_pdf_image_signatures(page, reader))
        pdf_text = _normalized_visible_text("\n".join(extracted_pages))
        (
            positioned,
            barriers,
            pdf_image_layouts,
            painted_paths,
            pdfium_unsafe,
        ) = _pdfium_visible_layout(pdf_content)
        reading_positioned = _positioned_reading_order(positioned)
        pdf_content_kinds = _pdf_content_kinds(reader)
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
    document_order_matches = _ordered_text_blocks_match(
        document_fragments, reading_positioned, barriers
    )
    repeatable_text_matches = _repeatable_text_matches(
        header_fragments=header_fragments,
        footer_fragments=footer_fragments,
        positioned=reading_positioned,
        page_heights=page_heights,
    )

    images_match = _repeatable_word_images_match(
        document_signatures=document_images,
        document_layouts=document_image_layouts,
        header_signatures=header_images,
        header_layouts=header_image_layouts,
        footer_signatures=footer_images,
        footer_layouts=footer_image_layouts,
        candidate_signatures=pdf_images,
        candidate_layouts=pdf_image_layouts,
        positioned_text=reading_positioned,
        page_count=len(reader.pages),
    )
    tables_match = _table_rows_match(table_rows, reading_positioned, barriers)
    painted_paths_match = _painted_paths_are_bound_to_tables(
        painted_paths, tables, reading_positioned, barriers
    )
    text_sizes_match = _text_sizes_match(
        word_text_expectations, reading_positioned, barriers
    )
    content_order_matches = _content_kinds_are_ordered_subsequence(
        word_content_kinds, pdf_content_kinds
    )
    if (
        not source_tokens
        or unsafe_text
        or not token_counts_match
        or not document_order_matches
        or not repeatable_text_matches
        or not images_match
        or not content_order_matches
        or not tables_match
        or not painted_paths_match
        or not text_sizes_match
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
