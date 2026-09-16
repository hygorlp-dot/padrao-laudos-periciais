"""Protected delivery rendering and final-byte integrity checks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
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
_DOCX_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_DOCM_MAIN_CONTENT_TYPE = "application/vnd.ms-word.document.macroEnabled.main+xml"
_PDF_MEDIA = "application/pdf"
DELIVERY_RENDERING_VERSION = "delivery-renderer/2.0.0"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_V = "{urn:schemas-microsoft-com:vml}"
_RELATIONSHIP_NAMESPACES = frozenset(
    {
        "http://schemas.openxmlformats.org/package/2006/relationships",
        "http://purl.oclc.org/ooxml/package/relationships",
    }
)
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


def _xml_namespace(tag: object) -> str:
    if not isinstance(tag, str) or not tag.startswith("{"):
        return ""
    return tag[1:].split("}", 1)[0]


def _relationship_nodes(data: bytes) -> list[ElementTree.Element]:
    """Parse a relationship part under the same closed policy as the Word worker.

    Namespace-exact iteration silently skipped Strict-namespace parts, which made
    the external-relationship ban unenforceable for them.  Element and attribute
    identity are read by local name; the namespace itself is allow-listed.
    """
    root = ElementTree.fromstring(data)
    if (
        _local_name(root.tag) != "Relationships"
        or _xml_namespace(root.tag) not in _RELATIONSHIP_NAMESPACES
    ):
        raise ValueError("unsupported Word relationship namespace")
    nodes: list[ElementTree.Element] = []
    for node in root.iter():
        if node is root:
            continue
        if (
            _local_name(node.tag) != "Relationship"
            or _xml_namespace(node.tag) not in _RELATIONSHIP_NAMESPACES
        ):
            raise ValueError("unsupported Word relationship element")
        nodes.append(node)
    return nodes


def _is_internal_relationship(node: ElementTree.Element) -> bool:
    """TargetMode is a closed enumeration: absent or exactly ``Internal``."""
    mode = _attribute_named(node, "TargetMode")
    return mode is None or mode == "Internal"


def _cell_property(cell: ElementTree.Element, name: str):
    """Read a table-cell property from its own ``tcPr``.

    A recursive descendant search reached into nested tables, so an inner cell's
    ``gridSpan``/``vMerge`` could govern the outer cell's column geometry.
    """
    return _first_named(next(_children_named(cell, "tcPr"), None), name)


_WORD_TEXT_SEPARATORS = frozenset({"br", "cr", "tab"})
_LATIN_THEME_ALIASES = {
    "majorascii": "major",
    "majorhansi": "major",
    "minorascii": "minor",
    "minorhansi": "minor",
}
_UNSUPPORTED_THEME_ALIASES = frozenset(
    {"majorbidi", "majoreastasia", "minorbidi", "minoreastasia"}
)


def _latin_theme_family(value: str | None) -> str | None:
    """Resolve an ST_Theme alias to the Latin family it names.

    Returns None only when the reference is genuinely absent.  A reference this
    oracle cannot model -- the East Asian and complex-script slots, which select
    <a:ea>/<a:cs> rather than <a:latin>, or any unknown value -- fails closed.
    """
    alias = (value or "").strip().casefold()
    if not alias:
        return None
    if alias in _LATIN_THEME_ALIASES:
        return _LATIN_THEME_ALIASES[alias]
    if alias in _UNSUPPORTED_THEME_ALIASES:
        raise ValueError("unsupported Word non-Latin font theme slot")
    raise ValueError("unsupported Word font theme reference")


def _on_off_value(properties: ElementTree.Element | None, name: str) -> bool | None:
    node = _first_named(properties, name)
    if node is None:
        return None
    return (_attribute_named(node, "val") or "true").casefold() not in {
        "0",
        "false",
        "off",
        "none",
    }


def _hidden_run_resolver(styles_root: ElementTree.Element | None):
    """Resolve w:vanish through docDefaults, the style chain and direct run properties.

    Hidden runs carry no visible authority: Word does not render them, so the
    oracle must not demand them from the PDF -- and must reject a PDF that shows
    them, which the token multiset already does once they stop being expected.
    """
    style_hidden: dict[str, bool | None] = {}
    style_bases: dict[str, str | None] = {}
    default_hidden = False
    if styles_root is not None:
        defaults = _first_named(styles_root, "docDefaults")
        default_hidden = bool(_on_off_value(defaults, "vanish"))
        for style in _iter_named(styles_root, "style"):
            style_id = _attribute_named(style, "styleId")
            if not style_id:
                continue
            style_hidden[style_id] = _on_off_value(
                next(_children_named(style, "rPr"), None), "vanish"
            )
            based_on = _first_named(style, "basedOn")
            style_bases[style_id] = (
                _attribute_named(based_on, "val") if based_on is not None else None
            )

    def resolve_style(style_id: str | None) -> bool | None:
        visited: set[str] = set()
        while style_id and style_id not in visited:
            visited.add(style_id)
            value = style_hidden.get(style_id)
            if value is not None:
                return value
            style_id = style_bases.get(style_id)
        return None

    def is_hidden(run: ElementTree.Element, paragraph_style_id: str | None) -> bool:
        properties = next(_children_named(run, "rPr"), None)
        direct = _on_off_value(properties, "vanish")
        if direct is not None:
            return direct
        run_style = _first_named(properties, "rStyle")
        if run_style is not None:
            inherited = resolve_style(_attribute_named(run_style, "val"))
            if inherited is not None:
                return inherited
        inherited = resolve_style(paragraph_style_id)
        return default_hidden if inherited is None else inherited

    return is_hidden


def _paragraph_style_id(paragraph: ElementTree.Element) -> str | None:
    properties = next(_children_named(paragraph, "pPr"), None)
    style_node = _first_named(properties, "pStyle")
    return _attribute_named(style_node, "val") if style_node is not None else None


def _visible_paragraph_text(paragraph: ElementTree.Element, is_hidden) -> str:
    style_id = _paragraph_style_id(paragraph)
    return "".join(
        "".join(item.text or "" for item in _iter_named(run, "t"))
        for run in _iter_named(paragraph, "r")
        if not is_hidden(run, style_id)
    )


_TABLE_LOOK_FLAGS = {
    "firstRow": 0x0020,
    "lastRow": 0x0040,
    "firstColumn": 0x0080,
    "lastColumn": 0x0100,
    "noHBand": 0x0200,
    "noVBand": 0x0400,
}


def _table_look_flag(
    look: ElementTree.Element | None, name: str, *, default: bool = False
) -> bool:
    """Read one tblLook flag from either the named attributes or the legacy mask.

    Word writes both forms.  When both are present and disagree the table's
    conditional formatting is ambiguous, so this fails closed rather than
    silently preferring one encoding.
    """
    flag = _TABLE_LOOK_FLAGS.get(name)
    if flag is None:
        raise ValueError("unsupported Word table-look flag")
    if look is None:
        return default
    named = _attribute_named(look, name)
    named_value = named.casefold() in {"1", "true", "on"} if named is not None else None
    raw_mask = _attribute_named(look, "val")
    mask_value: bool | None = None
    if raw_mask is not None:
        try:
            mask_value = bool(int(raw_mask, 16) & flag)
        except ValueError as exc:
            raise ValueError("invalid Word table-look mask") from exc
    if named_value is not None and mask_value is not None and named_value != mask_value:
        raise ValueError("conflicting Word table-look declarations")
    if named_value is not None:
        return named_value
    return default if mask_value is None else mask_value


def _table_look(table: ElementTree.Element):
    """Read a table's ``tblLook`` from its own ``tblPr``, never from a nested table."""
    properties = next(_children_named(table, "tblPr"), None)
    return next(_children_named(properties, "tblLook"), None) if properties is not None else None


def _table_style_id(table: ElementTree.Element) -> str | None:
    """Read a table's style from its own ``tblPr``, never from a nested table."""
    style_node = _first_named(next(_children_named(table, "tblPr"), None), "tblStyle")
    return _attribute_named(style_node, "val") if style_node is not None else None


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
            if _is_internal_relationship(item)
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
    fill_color: tuple[int, int, int, int] | None = (0, 0, 0, 255)
    stroke_color: tuple[int, int, int, int] | None = None
    fill_mode: int = 1
    stroke: bool = False


@dataclass(frozen=True, slots=True)
class _WordTableCellExpectation:
    row_start: int
    row_end: int
    column_start: int
    column_end: int
    paragraphs: tuple[str, ...]
    fill_color: tuple[int, int, int, int] | None = None


@dataclass(frozen=True, slots=True)
class _WordTableExpectation:
    rows: tuple[tuple[str, ...], ...]
    column_offsets: tuple[float, ...]
    row_cell_counts: tuple[int, ...]
    row_vertical_merge_continuations: tuple[int, ...]
    row_vertical_merge_ranges: tuple[tuple[tuple[int, int], ...], ...]
    row_boundaries: tuple[tuple[int, ...], ...]
    cells: tuple[_WordTableCellExpectation, ...]
    painted_grid: bool
    horizontal_borders: tuple[tuple[int, tuple[int, int, int, int]], ...] = ()


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
    header_signatures_by_page: list[list[tuple]] | None = None,
    header_layouts_by_page: list[list[_WordImageLayout | None]] | None = None,
    footer_signatures_by_page: list[list[tuple]] | None = None,
    footer_layouts_by_page: list[list[_WordImageLayout | None]] | None = None,
) -> bool:
    if (
        len(candidate_signatures) != len(candidate_layouts)
        or len(document_signatures) != len(document_layouts)
        or len(header_signatures) != len(header_layouts)
        or len(footer_signatures) != len(footer_layouts)
        or page_count < 1
    ):
        return False
    header_signature_pages = header_signatures_by_page or [
        header_signatures for _ in range(page_count)
    ]
    header_layout_pages = header_layouts_by_page or [
        header_layouts for _ in range(page_count)
    ]
    footer_signature_pages = footer_signatures_by_page or [
        footer_signatures for _ in range(page_count)
    ]
    footer_layout_pages = footer_layouts_by_page or [
        footer_layouts for _ in range(page_count)
    ]
    if any(
        len(collection) != page_count
        for collection in (
            header_signature_pages,
            header_layout_pages,
            footer_signature_pages,
            footer_layout_pages,
        )
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
        signatures_by_page: list[list[tuple]],
        layouts_by_page: list[list[_WordImageLayout | None]],
        *,
        region: str,
    ) -> bool:
        for page in range(page_count):
            signatures = signatures_by_page[page]
            layouts = layouts_by_page[page]
            if len(signatures) != len(layouts):
                return False
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
        header_signature_pages, header_layout_pages, region="header"
    ) or not consume_repeated(
        footer_signature_pages, footer_layout_pages, region="footer"
    ):
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


def _dynamic_paragraph_text(
    paragraph: ElementTree.Element, *, page_number: int
) -> str:
    def events(node: ElementTree.Element):
        for child in node:
            if _local_name(child.tag) == "fldSimple":
                yield ("field", (_attribute_named(child, "instr") or "").strip())
                continue
            yield ("node", child)
            yield from events(child)

    values: list[str] = []
    field_instruction: list[str] | None = None
    skip_field_result = False
    for kind, value in events(paragraph):
        if kind == "field":
            if str(value).casefold() != "page":
                raise ValueError("unsupported dynamic Word field")
            values.append(str(page_number))
            continue
        item = value
        assert isinstance(item, ElementTree.Element)
        name = _local_name(item.tag)
        if name == "fldChar":
            field_type = (_attribute_named(item, "fldCharType") or "").casefold()
            if field_type == "begin":
                field_instruction = []
                skip_field_result = False
            elif field_type == "separate" and field_instruction is not None:
                instruction = "".join(field_instruction).strip().casefold()
                if instruction != "page":
                    raise ValueError("unsupported dynamic Word field")
                values.append(str(page_number))
                skip_field_result = True
            elif field_type == "end":
                field_instruction = None
                skip_field_result = False
        elif name == "instrText" and field_instruction is not None:
            field_instruction.append(item.text or "")
        elif name == "t" and not skip_field_result and field_instruction is None:
            values.append(item.text or "")
    return "".join(values)


def _header_footer_profile(
    package: ZipFile,
    xml_roots: dict[str, ElementTree.Element],
) -> dict[str, str | bool | None] | None:
    document = xml_roots.get("word/document.xml")
    if document is None:
        return None
    sections = list(_iter_named(document, "sectPr"))
    references = [
        item
        for section in sections
        for item in section
        if _local_name(item.tag) in {"headerReference", "footerReference"}
    ]
    if not references:
        return None
    if len(sections) != 1:
        raise ValueError("multiple Word sections are not supported for final PDF")
    relationships_name = "word/_rels/document.xml.rels"
    if relationships_name not in package.namelist():
        raise ValueError("Word header/footer relationships are missing")
    relationships = ElementTree.fromstring(package.read(relationships_name))
    targets = {
        _attribute_named(item, "Id"): posixpath.normpath(
            posixpath.join("word", _attribute_named(item, "Target") or "")
        )
        for item in _iter_named(relationships, "Relationship")
        if _is_internal_relationship(item)
    }
    profile: dict[str, str | bool | None] = {
        "different_first": _first_named(sections[0], "titlePg") is not None,
        "even_and_odd": False,
    }
    settings = xml_roots.get("word/settings.xml")
    if settings is not None:
        profile["even_and_odd"] = (
            _first_named(settings, "evenAndOddHeaders") is not None
        )
    for reference in references:
        kind = "header" if _local_name(reference.tag) == "headerReference" else "footer"
        variant = (_attribute_named(reference, "type") or "default").casefold()
        if variant not in {"default", "first", "even"}:
            raise ValueError("unsupported Word header/footer variant")
        target = targets.get(_attribute_named(reference, "id"))
        if target not in xml_roots:
            raise ValueError("Word header/footer target is missing")
        profile[f"{kind}_{variant}"] = target
    return profile


def _repeatable_text_matches(
    *,
    header_fragments_by_page: list[list[str]],
    footer_fragments_by_page: list[list[str]],
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
                fragment.bottom >= height * 0.75
                if header
                else fragment.top <= height * 0.25
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

    return (
        len(page_heights) > 0
        and len(header_fragments_by_page) == len(page_heights)
        and len(footer_fragments_by_page) == len(page_heights)
        and all(
        region_matches(header_fragments_by_page[page], page=page, header=True)
        and region_matches(footer_fragments_by_page[page], page=page, header=False)
        for page in range(len(page_heights))
        )
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


def _positioned_target_locations(
    target: str,
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> list[tuple[int, float, float]]:
    """Enumerate visible occurrences of a target in reading order.

    This used to mix two enumerations -- a substring search inside one fragment
    and a multi-fragment sequence match -- and then deduplicate them by their
    geometry.  One visible occurrence could contribute two entries, or two could
    collapse into one, so the ordinal handed in from the Word side addressed the
    wrong destination.  Occurrences are now non-overlapping windows of the same
    lexical token sequence the Word side counts.
    """
    needle = _lexical_tokens(target)
    if not needle:
        return []
    stream: list[tuple[str, int, int, int]] = []
    for index, fragment in enumerate(positioned):
        tokens = _lexical_tokens(fragment.text)
        for order, token in enumerate(tokens):
            stream.append((token, index, order, len(tokens)))
    locations: list[tuple[int, float, float]] = []
    cursor = 0
    while cursor + len(needle) <= len(stream):
        window = stream[cursor : cursor + len(needle)]
        if tuple(token for token, _index, _order, _count in window) != needle:
            cursor += 1
            continue
        first_index, last_index = window[0][1], window[-1][1]
        matched = positioned[first_index : last_index + 1]
        first = matched[0]
        crosses_barrier = any(
            barrier.page == first.page
            and barrier.left >= first.x - 0.5
            and barrier.right <= matched[-1].right + 0.5
            for barrier in barriers
        )
        if all(item.page == first.page for item in matched) and not crosses_barrier:
            width = max(0.0, first.right - first.x)
            offset = window[0][2] / max(window[0][3], 1)
            locations.append(
                (
                    first.page,
                    first.x + width * offset,
                    max(item.top for item in matched),
                )
            )
        cursor += len(needle)
    return locations


def _annotations_match_internal_links(
    reader: PdfReader,
    expectations: list[_WordInternalLinkExpectation],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    page_references = {
        (
            page.indirect_reference.idnum,
            page.indirect_reference.generation,
        ): index
        for index, page in enumerate(reader.pages)
        if page.indirect_reference is not None
    }
    observed: list[tuple[int, object]] = []
    try:
        for page_index, page in enumerate(reader.pages):
            annotations = page.get("/Annots")
            if annotations is None:
                continue
            observed.extend(
                (page_index, annotation.get_object())
                for annotation in annotations.get_object()
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    if len(observed) != len(expectations):
        return False

    used_expectations: set[int] = set()
    for page_index, annotation in observed:
        try:
            if str(annotation.get("/Subtype")) != "/Link" or any(
                key in annotation
                for key in ("/A", "/AA", "/JS", "/URI", "/Launch")
            ):
                return False
            rectangle = [float(value) for value in annotation["/Rect"]]
            if len(rectangle) != 4 or not all(map(math.isfinite, rectangle)):
                return False
            left, bottom, right, top = rectangle
            page = reader.pages[page_index]
            if (
                left >= right
                or bottom >= top
                or left < float(page.mediabox.left)
                or bottom < float(page.mediabox.bottom)
                or right > float(page.mediabox.right)
                or top > float(page.mediabox.top)
            ):
                return False
            destination = annotation["/Dest"].get_object()
            if len(destination) < 4 or str(destination[1]) != "/XYZ":
                return False
            destination_reference = destination[0]
            destination_page = page_references.get(
                (
                    destination_reference.idnum,
                    destination_reference.generation,
                )
            )
            destination_x = float(destination[2])
            destination_y = float(destination[3])
            if destination_page is None or not all(
                map(math.isfinite, (destination_x, destination_y))
            ):
                return False
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            return False

        link_fragments = _positioned_reading_order(
            [
                fragment
                for fragment in positioned
                if fragment.page == page_index
                and fragment.x >= left - 2.0
                and fragment.right <= right + 2.0
                and fragment.bottom >= bottom - 2.0
                and fragment.top <= top + 2.0
            ]
        )
        link_text = _normalized_visible_text(
            " ".join(fragment.text for fragment in link_fragments)
        )
        candidate = next(
            (
                (index, expectation)
                for index, expectation in enumerate(expectations)
                if index not in used_expectations and expectation.text == link_text
            ),
            None,
        )
        if candidate is None:
            return False
        expectation_index, expectation = candidate
        target_matches = _positioned_target_locations(
            expectation.target_text, positioned, barriers
        )
        if expectation.target_occurrence >= len(target_matches):
            return False
        authoritative_target = target_matches[expectation.target_occurrence]
        if (
            authoritative_target[0] != destination_page
            or abs(destination_x - authoritative_target[1]) > 18.0
            or abs(destination_y - authoritative_target[2]) > 12.0
        ):
            return False
        used_expectations.add(expectation_index)
    return len(used_expectations) == len(expectations)


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
    font_weight: int = 400
    italic_angle: int = 0
    page_width: float = 612.0
    font_family: str | None = None
    page_height: float = 792.0


@dataclass(frozen=True, slots=True)
class _VerticalBarrier:
    page: int
    left: float
    right: float
    bottom: float
    top: float


@dataclass(frozen=True, slots=True)
class _ParagraphWrapAnchor:
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
    bold: bool
    italic: bool
    underline: bool
    alignment: str
    in_table: bool = False
    font_family: str | None = None
    expected_top_offset: float | None = None
    expected_page: int | None = None
    body_flow_anchor: bool = False
    expected_previous_top_gap: float | None = None
    enforce_visible_run_style: bool = True
    line_height: float | None = None
    paragraph_continuation: bool = False
    page_break_before: bool = False


def _word_page_geometry(
    document: ElementTree.Element | None,
) -> tuple[float, float] | None:
    if document is None:
        return None
    dimensions: set[tuple[float, float]] = set()
    for section in _iter_named(document, "sectPr"):
        page_size = _first_named(section, "pgSz")
        if page_size is None:
            continue
        try:
            width = float(_attribute_named(page_size, "w") or "") / 20.0
            height = float(_attribute_named(page_size, "h") or "") / 20.0
        except ValueError as exc:
            raise ValueError("invalid Word page geometry") from exc
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            raise ValueError("invalid Word page geometry")
        dimensions.add((width, height))
    if not dimensions:
        return None
    if len(dimensions) != 1:
        raise ValueError("multiple Word page geometries are not supported")
    return next(iter(dimensions))


def _page_geometry_matches(
    expected: tuple[float, float] | None,
    observed: list[tuple[float, float]],
) -> bool:
    if expected is None:
        return True
    return bool(observed) and all(
        abs(width - expected[0]) <= 2.0 and abs(height - expected[1]) <= 2.0
        for width, height in observed
    )


def _pdf_pages_have_visible_content(
    page_count: int,
    positioned: list[_PositionedText],
    images: list[_PdfImageLayout],
    paths: list[_PaintedPath],
) -> bool:
    observed_pages = {
        *(item.page for item in positioned),
        *(item.page for item in images),
        *(item.page for item in paths),
    }
    return page_count > 0 and observed_pages == set(range(page_count))


def _pdf_pages_have_document_content(
    *,
    extracted_pages: list[str],
    header_fragments_by_page: list[list[str]],
    footer_fragments_by_page: list[list[str]],
    image_layouts: list[_PdfImageLayout],
    painted_paths: list[_PaintedPath],
    page_heights: list[float],
) -> bool:
    page_count = len(extracted_pages)
    if page_count == 0 or any(
        len(values) != page_count
        for values in (
            header_fragments_by_page,
            footer_fragments_by_page,
            page_heights,
        )
    ):
        return False
    for page, extracted in enumerate(extracted_pages):
        page_counts = Counter(_lexical_tokens(extracted))
        repeatable_counts = Counter(
            _lexical_tokens(
                " ".join(
                    header_fragments_by_page[page]
                    + footer_fragments_by_page[page]
                )
            )
        )
        if page_counts - repeatable_counts:
            continue
        page_height = page_heights[page]
        if not math.isfinite(page_height) or page_height <= 0:
            return False
        body_bottom = page_height * 0.25
        body_top = page_height * 0.75
        if any(
            item.page == page
            and item.top > body_bottom
            and item.bottom < body_top
            for item in (*image_layouts, *painted_paths)
        ):
            continue
        return False
    return True


def _normalized_font_family(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold().split("+")[-1])
    for suffix in ("bolditalic", "boldoblique", "italic", "oblique", "bold", "regular"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    for suffix in ("psmt", "mt"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


@dataclass(frozen=True, slots=True)
class _WordInternalLinkExpectation:
    text: str
    target_text: str
    target_occurrence: int = 0


def _token_occurrences(haystack: tuple[str, ...], needle: tuple[str, ...]) -> int:
    """Count non-overlapping occurrences of a token window, as the PDF side does."""
    if not needle:
        return 0
    count = 0
    index = 0
    while index + len(needle) <= len(haystack):
        if haystack[index : index + len(needle)] == needle:
            count += 1
            index += len(needle)
        else:
            index += 1
    return count


def _word_internal_link_expectations(
    document: ElementTree.Element | None,
) -> list[_WordInternalLinkExpectation]:
    """Bind internal hyperlinks to the visible occurrence their bookmark covers.

    The occurrence ordinal used to be ``prefix.count(target_text)``, a substring
    count over normalised text.  The PDF side counts positioned occurrences, so
    the two ordinals measured different things and a one-character or repeated
    target resolved to the wrong destination.  Both sides now count the same
    thing: non-overlapping windows of the same lexical token sequence.
    """
    if document is None:
        return []
    buffer: list[str] = []
    length = 0
    active: dict[str, tuple[str, int]] = {}
    spans: dict[str, tuple[int, int]] = {}

    def append(value: str) -> None:
        nonlocal length
        if value:
            buffer.append(value)
            length += len(value)

    def walk(node: ElementTree.Element) -> None:
        # One depth-first pass visits each node exactly once.  Iterating
        # paragraphs and then descending into each of them counted the content
        # of nested paragraphs -- a text box inside a paragraph -- twice.
        for child in node:
            local_name = _local_name(child.tag)
            if local_name == "bookmarkStart":
                bookmark_id = _attribute_named(child, "id")
                name = _attribute_named(child, "name")
                if not bookmark_id or not name or bookmark_id in active:
                    raise ValueError("Word bookmark target is invalid")
                active[bookmark_id] = (name, length)
                continue
            if local_name == "bookmarkEnd":
                bookmark_id = _attribute_named(child, "id")
                entry = active.pop(bookmark_id or "", None)
                if entry is None:
                    raise ValueError("Word bookmark target is invalid")
                name, start = entry
                if name in spans:
                    raise ValueError("Word bookmark target is invalid")
                spans[name] = (start, length)
                continue
            if local_name == "t":
                append(child.text or "")
                continue
            if local_name in _WORD_TEXT_SEPARATORS:
                # A tab or break separates tokens even though it carries no text.
                append(" ")
                continue
            if local_name == "p":
                # Paragraph boundaries separate tokens on both sides, so a nested
                # paragraph cannot fuse with the text that precedes it.
                append(chr(10))
                walk(child)
                append(chr(10))
                continue
            walk(child)

    walk(document)
    if active:
        raise ValueError("Word bookmark target is incomplete")

    text = "".join(buffer)
    bookmark_targets: dict[str, tuple[str, int]] = {}
    for name, (start, end) in spans.items():
        target_text = _normalized_visible_text(text[start:end])
        target_tokens = _lexical_tokens(text[start:end])
        if not target_text or not target_tokens:
            raise ValueError("Word bookmark target is invalid")
        bookmark_targets[name] = (
            target_text,
            _token_occurrences(_lexical_tokens(text[:start]), target_tokens),
        )

    expectations: list[_WordInternalLinkExpectation] = []
    for hyperlink in _iter_named(document, "hyperlink"):
        if _attribute_named(hyperlink, "id"):
            raise ValueError("external Word hyperlink is not allowed")
        anchor = _attribute_named(hyperlink, "anchor")
        link_text = _normalized_visible_text(
            "".join(item.text or "" for item in _iter_named(hyperlink, "t"))
        )
        target = bookmark_targets.get(anchor or "")
        if not anchor or not link_text or target is None:
            raise ValueError("Word internal hyperlink target is invalid")
        target_text, target_occurrence = target
        expectations.append(
            _WordInternalLinkExpectation(link_text, target_text, target_occurrence)
        )
    return expectations

def _word_text_expectations(
    xml_roots: dict[str, ElementTree.Element],
    *,
    active_content_names: set[str] | None = None,
) -> list[_WordTextExpectation]:
    styles_root = xml_roots.get("word/styles.xml")
    is_hidden_run = _hidden_run_resolver(styles_root)
    theme_parts = [
        root
        for name, root in xml_roots.items()
        if name.startswith("word/theme/") and name.endswith(".xml")
    ]
    if len(theme_parts) > 1:
        raise ValueError("multiple Word theme parts are not supported")
    theme_root = theme_parts[0] if theme_parts else None
    theme_fonts: dict[str, str] = {}
    if theme_root is not None:
        for prefix, element_name in (
            ("major", "majorFont"),
            ("minor", "minorFont"),
        ):
            family = _first_named(_first_named(theme_root, element_name), "latin")
            typeface = (
                (_attribute_named(family, "typeface") or "").strip()
                if family is not None
                else ""
            )
            if typeface:
                theme_fonts[prefix] = typeface

    def size_from_properties(properties: ElementTree.Element | None) -> float | None:
        size_node = _first_named(properties, "sz")
        if size_node is None:
            return None
        try:
            value = float(_attribute_named(size_node, "val") or "") / 2.0
        except ValueError:
            return None
        return value if math.isfinite(value) and value > 0 else None

    def font_from_properties(properties: ElementTree.Element | None) -> str | None:
        fonts = _first_named(properties, "rFonts")
        if fonts is None:
            return None
        ascii_font = (_attribute_named(fonts, "ascii") or "").strip()
        ansi_font = (_attribute_named(fonts, "hAnsi") or "").strip()
        selected = ascii_font or ansi_font
        if ascii_font and ansi_font and (
            _normalized_font_family(ascii_font)
            != _normalized_font_family(ansi_font)
        ):
            raise ValueError("conflicting Word Latin font families")
        if selected:
            return selected
        # ST_Theme aliases are resolved to the family they name, so that
        # minorAscii and minorHAnsi -- two spellings of one Latin slot -- are not
        # mistaken for a conflict.  A slot this oracle does not model resolves to
        # UNSUPPORTED, never to None: None here means ABSENT, which switches the
        # font check off entirely.
        ascii_family = _latin_theme_family(_attribute_named(fonts, "asciiTheme"))
        ansi_family = _latin_theme_family(_attribute_named(fonts, "hAnsiTheme"))
        if ascii_family and ansi_family and ascii_family != ansi_family:
            raise ValueError("conflicting Word Latin font themes")
        family = ascii_family or ansi_family
        if family is None:
            return None
        resolved = theme_fonts.get(family)
        if not resolved:
            raise ValueError("unresolved Word Latin font theme")
        return resolved

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

    def on_off_from_properties(
        properties: ElementTree.Element | None, name: str
    ) -> bool | None:
        node = _first_named(properties, name)
        if node is None:
            return None
        value = (_attribute_named(node, "val") or "true").casefold()
        return value not in {"0", "false", "off", "none"}

    def underline_from_properties(
        properties: ElementTree.Element | None,
    ) -> bool | None:
        node = _first_named(properties, "u")
        if node is None:
            return None
        value = (_attribute_named(node, "val") or "single").casefold()
        if value in {"0", "false", "off", "none"}:
            return False
        if value != "single":
            raise ValueError("unsupported Word underline style")
        return True

    def alignment_from_properties(
        properties: ElementTree.Element | None,
    ) -> str | None:
        node = _first_named(properties, "jc")
        if node is None:
            return None
        value = (_attribute_named(node, "val") or "").casefold()
        aliases = {"start": "left", "end": "right"}
        value = aliases.get(value, value)
        if value not in {"left", "center", "right", "both"}:
            raise ValueError("unsupported Word paragraph alignment")
        return value

    def spacing_before_from_properties(
        properties: ElementTree.Element | None,
    ) -> float | None:
        spacing = _first_named(properties, "spacing")
        if spacing is None:
            return None
        raw = _attribute_named(spacing, "before")
        if raw is None:
            return None
        try:
            value = float(raw) / 20.0
        except ValueError as exc:
            raise ValueError("invalid Word paragraph spacing") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid Word paragraph spacing")
        return value

    def spacing_after_from_properties(
        properties: ElementTree.Element | None,
    ) -> float | None:
        spacing = _first_named(properties, "spacing")
        if spacing is None:
            return None
        raw = _attribute_named(spacing, "after")
        if raw is None:
            return None
        try:
            value = float(raw) / 20.0
        except ValueError as exc:
            raise ValueError("invalid Word paragraph spacing") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError("invalid Word paragraph spacing")
        return value

    def line_spacing_from_properties(
        properties: ElementTree.Element | None,
    ) -> tuple[str, float] | None:
        spacing = _first_named(properties, "spacing")
        if spacing is None:
            return None
        raw = _attribute_named(spacing, "line")
        if raw is None:
            return None
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("invalid Word line spacing") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError("invalid Word line spacing")
        rule = (_attribute_named(spacing, "lineRule") or "auto").casefold()
        if rule not in {"auto", "exact", "atleast"}:
            raise ValueError("unsupported Word line spacing")
        return rule, value

    def resolved_line_height(
        spec: tuple[str, float] | None, font_size: float
    ) -> float:
        if spec is None:
            return font_size * 1.2
        rule, value = spec
        if rule == "auto":
            return font_size * 1.2 * value / 240.0
        points = value / 20.0
        return points if rule == "exact" else max(font_size * 1.2, points)

    default_size = 11.0
    default_font: str | None = None
    default_color = (0, 0, 0)
    default_bold = False
    default_italic = False
    default_underline = False
    default_alignment = "left"
    default_spacing_before = 0.0
    default_spacing_after = 0.0
    default_line_spacing: tuple[str, float] | None = None
    default_paragraph_style: str | None = None
    style_sizes: dict[str, float | None] = {}
    style_fonts: dict[str, str | None] = {}
    style_colors: dict[str, tuple[int, int, int] | None] = {}
    style_bold: dict[str, bool | None] = {}
    style_italic: dict[str, bool | None] = {}
    style_underline: dict[str, bool | None] = {}
    style_alignment: dict[str, str | None] = {}
    style_spacing_before: dict[str, float | None] = {}
    style_spacing_after: dict[str, float | None] = {}
    style_line_spacing: dict[str, tuple[str, float] | None] = {}
    style_bases: dict[str, str | None] = {}
    style_nodes: dict[str, ElementTree.Element] = {}
    if styles_root is not None:
        defaults = _first_named(styles_root, "docDefaults")
        default_size = size_from_properties(defaults) or default_size
        default_font = font_from_properties(defaults)
        default_color = color_from_properties(defaults) or default_color
        default_bold = on_off_from_properties(defaults, "b") or False
        default_italic = on_off_from_properties(defaults, "i") or False
        default_underline = underline_from_properties(defaults) or False
        default_alignment = alignment_from_properties(defaults) or default_alignment
        default_spacing_before = (
            spacing_before_from_properties(defaults) or default_spacing_before
        )
        default_spacing_after = (
            spacing_after_from_properties(defaults) or default_spacing_after
        )
        default_line_spacing = line_spacing_from_properties(defaults)
        for style in _iter_named(styles_root, "style"):
            style_id = _attribute_named(style, "styleId")
            if not style_id:
                continue
            style_nodes[style_id] = style
            if (
                (_attribute_named(style, "type") or "").casefold() == "paragraph"
                and (_attribute_named(style, "default") or "").casefold()
                in {"1", "true", "on"}
            ):
                default_paragraph_style = style_id
            properties = next(_children_named(style, "rPr"), None)
            paragraph_properties = next(_children_named(style, "pPr"), None)
            based_on = _first_named(style, "basedOn")
            style_sizes[style_id] = size_from_properties(properties)
            style_fonts[style_id] = font_from_properties(properties)
            style_colors[style_id] = color_from_properties(properties)
            style_bold[style_id] = on_off_from_properties(properties, "b")
            style_italic[style_id] = on_off_from_properties(properties, "i")
            style_underline[style_id] = underline_from_properties(properties)
            style_alignment[style_id] = alignment_from_properties(
                paragraph_properties
            )
            style_spacing_before[style_id] = spacing_before_from_properties(
                paragraph_properties
            )
            style_spacing_after[style_id] = spacing_after_from_properties(
                paragraph_properties
            )
            style_line_spacing[style_id] = line_spacing_from_properties(
                paragraph_properties
            )
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

    def resolve_style_font(
        style_id: str | None,
        fallback: str | None = default_font,
    ) -> str | None:
        visited: set[str] = set()
        while style_id and style_id not in visited:
            visited.add(style_id)
            font = style_fonts.get(style_id)
            if font is not None:
                return font
            style_id = style_bases.get(style_id)
        return fallback

    def resolve_style_value(
        style_id: str | None,
        values: dict[str, object | None],
        fallback: object,
    ) -> object:
        visited: set[str] = set()
        while style_id and style_id not in visited:
            visited.add(style_id)
            value = values.get(style_id)
            if value is not None:
                return value
            style_id = style_bases.get(style_id)
        return fallback

    def table_run_properties(
        root: ElementTree.Element,
    ) -> dict[int, tuple[ElementTree.Element, ...]]:
        properties_by_paragraph: dict[int, tuple[ElementTree.Element, ...]] = {}

        enabled = _table_look_flag

        def style_chain(style_id: str | None) -> list[ElementTree.Element]:
            chain: list[ElementTree.Element] = []
            visited: set[str] = set()
            while style_id and style_id not in visited:
                visited.add(style_id)
                style = style_nodes.get(style_id)
                if style is None:
                    break
                chain.append(style)
                based_on = _first_named(style, "basedOn")
                style_id = (
                    _attribute_named(based_on, "val")
                    if based_on is not None
                    else None
                )
            chain.reverse()
            return chain

        conditional_order = (
            "band2vert",
            "band1vert",
            "band2horz",
            "band1horz",
            "lastcol",
            "firstcol",
            "lastrow",
            "firstrow",
            "secell",
            "swcell",
            "necell",
            "nwcell",
        )
        for table in _iter_named(root, "tbl"):
            table_properties = next(_children_named(table, "tblPr"), None)
            style_id = _table_style_id(table)
            chain = style_chain(style_id)
            look = next(_children_named(table_properties, "tblLook"), None) if table_properties is not None else None
            row_band_size = 1
            column_band_size = 1
            for style in chain:
                style_table_properties = next(
                    _children_named(style, "tblPr"), None
                )
                for name, target in (
                    ("tblStyleRowBandSize", "row"),
                    ("tblStyleColBandSize", "column"),
                ):
                    size_node = _first_named(style_table_properties, name)
                    if size_node is None:
                        continue
                    try:
                        size = int(_attribute_named(size_node, "val") or "")
                    except ValueError as exc:
                        raise ValueError("invalid Word table band size") from exc
                    if size < 1:
                        raise ValueError("invalid Word table band size")
                    if target == "row":
                        row_band_size = size
                    else:
                        column_band_size = size
            first_row_enabled = enabled(look, "firstRow", default=True)
            last_row_enabled = enabled(look, "lastRow")
            first_column_enabled = enabled(look, "firstColumn")
            last_column_enabled = enabled(look, "lastColumn")
            rows = list(_children_named(table, "tr"))
            for row_index, row in enumerate(rows):
                cells = list(_children_named(row, "tc"))
                for cell_index, cell in enumerate(cells):
                    active: set[str] = set()
                    first_row = row_index == 0 and first_row_enabled
                    last_row = row_index == len(rows) - 1 and last_row_enabled
                    first_column = cell_index == 0 and first_column_enabled
                    last_column = (
                        cell_index == len(cells) - 1 and last_column_enabled
                    )
                    if first_row:
                        active.add("firstrow")
                    if last_row:
                        active.add("lastrow")
                    if first_column:
                        active.add("firstcol")
                    if last_column:
                        active.add("lastcol")
                    if first_row and first_column:
                        active.add("nwcell")
                    if first_row and last_column:
                        active.add("necell")
                    if last_row and first_column:
                        active.add("swcell")
                    if last_row and last_column:
                        active.add("secell")
                    if (
                        not first_column
                        and not last_column
                        and not enabled(look, "noHBand")
                    ):
                        band_row = row_index
                        active.add(
                            "band1horz"
                            if (band_row // row_band_size) % 2 == 0
                            else "band2horz"
                        )
                    if (
                        not first_row
                        and not last_row
                        and not enabled(look, "noVBand", default=True)
                    ):
                        band_column = cell_index
                        active.add(
                            "band1vert"
                            if (band_column // column_band_size) % 2 == 0
                            else "band2vert"
                        )

                    layers: list[ElementTree.Element] = []
                    for style in chain:
                        whole_table = next(_children_named(style, "rPr"), None)
                        if whole_table is not None:
                            layers.append(whole_table)
                    conditionals = [
                        {
                            (_attribute_named(item, "type") or "").casefold(): item
                            for item in _children_named(style, "tblStylePr")
                        }
                        for style in chain
                    ]
                    for kind in conditional_order:
                        for conditional in conditionals:
                            item = conditional.get(kind)
                            run_properties = _first_named(item, "rPr")
                            if kind in active and run_properties is not None:
                                layers.append(run_properties)
                    for paragraph in _iter_named(cell, "p"):
                        properties_by_paragraph[id(paragraph)] = tuple(layers)
        return properties_by_paragraph

    def layered_value(
        layers: tuple[ElementTree.Element, ...],
        extractor: Callable[[ElementTree.Element | None], object | None],
        fallback: object,
    ) -> object:
        value = fallback
        for layer in layers:
            candidate = extractor(layer)
            if candidate is not None:
                value = candidate
        return value

    anchor_paragraph_id: int | None = None
    anchor_top_margin: float | None = None
    anchor_preceding_blank_height = 0.0
    document = xml_roots.get("word/document.xml")
    body = _first_named(document, "body")
    if body is not None:
        for child in body:
            if _local_name(child.tag) == "sectPr":
                continue
            paragraphs = (
                [child]
                if _local_name(child.tag) == "p"
                else list(_iter_named(child, "p"))
            )
            if len(paragraphs) == 1:
                paragraph = paragraphs[0]
                text = "".join(
                    item.text or "" for item in _iter_named(paragraph, "t")
                )
                if text.strip() and _first_named(paragraph, "drawing") is None:
                    anchor_paragraph_id = id(paragraph)
                    break
                if not text.strip() and _first_named(paragraph, "drawing") is None:
                    paragraph_properties = next(
                        _children_named(paragraph, "pPr"), None
                    )
                    style_node = _first_named(paragraph_properties, "pStyle")
                    style_id = (
                        _attribute_named(style_node, "val")
                        if style_node is not None
                        else default_paragraph_style
                    )
                    paragraph_mark_properties = next(
                        _children_named(paragraph_properties, "rPr"), None
                    ) if paragraph_properties is not None else None
                    blank_size = (
                        size_from_properties(paragraph_mark_properties)
                        or resolve_style(style_id)
                    )
                    blank_before = spacing_before_from_properties(
                        paragraph_properties
                    )
                    if blank_before is None:
                        blank_before = float(
                            resolve_style_value(
                                style_id,
                                style_spacing_before,
                                default_spacing_before,
                            )
                        )
                    blank_after = spacing_after_from_properties(
                        paragraph_properties
                    )
                    if blank_after is None:
                        blank_after = float(
                            resolve_style_value(
                                style_id,
                                style_spacing_after,
                                default_spacing_after,
                            )
                        )
                    blank_line_spacing = line_spacing_from_properties(
                        paragraph_properties
                    )
                    if blank_line_spacing is None:
                        blank_line_spacing = resolve_style_value(
                            style_id,
                            style_line_spacing,
                            default_line_spacing,
                        )
                    anchor_preceding_blank_height += (
                        blank_before
                        + resolved_line_height(blank_line_spacing, blank_size)
                        + blank_after
                    )
                    continue
            break
        sections = list(_iter_named(document, "sectPr")) if document is not None else []
        if sections:
            page_margin = _first_named(sections[0], "pgMar")
            raw_top = (
                _attribute_named(page_margin, "top")
                if page_margin is not None
                else None
            )
            if raw_top is not None:
                try:
                    anchor_top_margin = float(raw_top) / 20.0
                except ValueError as exc:
                    raise ValueError("invalid Word page margin") from exc
                if not math.isfinite(anchor_top_margin) or anchor_top_margin < 0:
                    raise ValueError("invalid Word page margin")

    expectations: list[_WordTextExpectation] = []
    content_names = [
        name
        for name in sorted(xml_roots, key=_word_part_priority)
        if name == "word/document.xml"
        or name.startswith(("word/header", "word/footer"))
        if active_content_names is None or name in active_content_names
    ]
    for name in content_names:
        previous_body_line_height: float | None = None
        previous_body_after = 0.0
        pending_blank_height = 0.0
        table_properties_by_paragraph = table_run_properties(xml_roots[name])
        table_paragraph_ids = {
            id(paragraph)
            for table in _iter_named(xml_roots[name], "tbl")
            for paragraph in _iter_named(table, "p")
        }
        for paragraph in _iter_named(xml_roots[name], "p"):
            in_table = id(paragraph) in table_paragraph_ids
            paragraph_has_drawing = _first_named(paragraph, "drawing") is not None
            paragraph_properties = next(_children_named(paragraph, "pPr"), None)
            paragraph_style_node = _first_named(paragraph_properties, "pStyle")
            paragraph_style = (
                _attribute_named(paragraph_style_node, "val")
                if paragraph_style_node is not None
                else None
            )
            table_layers = table_properties_by_paragraph.get(id(paragraph), ())
            paragraph_size = float(
                layered_value(
                    table_layers,
                    size_from_properties,
                    resolve_style(default_paragraph_style),
                )
            )
            paragraph_font = layered_value(
                table_layers,
                font_from_properties,
                resolve_style_font(default_paragraph_style),
            )
            paragraph_color = layered_value(
                table_layers,
                color_from_properties,
                resolve_style_color(default_paragraph_style),
            )
            paragraph_bold = bool(
                layered_value(
                    table_layers,
                    lambda value: on_off_from_properties(value, "b"),
                    resolve_style_value(
                        default_paragraph_style, style_bold, default_bold
                    ),
                )
            )
            paragraph_italic = bool(
                layered_value(
                    table_layers,
                    lambda value: on_off_from_properties(value, "i"),
                    resolve_style_value(
                        default_paragraph_style, style_italic, default_italic
                    ),
                )
            )
            paragraph_underline = bool(
                layered_value(
                    table_layers,
                    underline_from_properties,
                    resolve_style_value(
                        default_paragraph_style,
                        style_underline,
                        default_underline,
                    ),
                )
            )
            if paragraph_style is not None:
                paragraph_size = resolve_style(paragraph_style, paragraph_size)
                paragraph_font = resolve_style_font(paragraph_style, paragraph_font)
                paragraph_color = resolve_style_color(paragraph_style, paragraph_color)
                paragraph_bold = bool(
                    resolve_style_value(paragraph_style, style_bold, paragraph_bold)
                )
                paragraph_italic = bool(
                    resolve_style_value(
                        paragraph_style, style_italic, paragraph_italic
                    )
                )
                paragraph_underline = bool(
                    resolve_style_value(
                        paragraph_style, style_underline, paragraph_underline
                    )
                )
            paragraph_alignment = str(
                alignment_from_properties(paragraph_properties)
                or resolve_style_value(
                    paragraph_style or default_paragraph_style,
                    style_alignment,
                    default_alignment,
                )
            )
            paragraph_spacing_before = float(
                spacing_before_from_properties(paragraph_properties)
                if spacing_before_from_properties(paragraph_properties) is not None
                else resolve_style_value(
                    paragraph_style or default_paragraph_style,
                    style_spacing_before,
                    default_spacing_before,
                )
            )
            paragraph_spacing_after = float(
                spacing_after_from_properties(paragraph_properties)
                if spacing_after_from_properties(paragraph_properties) is not None
                else resolve_style_value(
                    paragraph_style or default_paragraph_style,
                    style_spacing_after,
                    default_spacing_after,
                )
            )
            paragraph_line_spacing = line_spacing_from_properties(
                paragraph_properties
            )
            if paragraph_line_spacing is None:
                paragraph_line_spacing = resolve_style_value(
                    paragraph_style or default_paragraph_style,
                    style_line_spacing,
                    default_line_spacing,
                )
            page_break_node = _first_named(
                paragraph_properties, "pageBreakBefore"
            )
            paragraph_page_break_before = (
                page_break_node is not None
                and (_attribute_named(page_break_node, "val") or "true").casefold()
                not in {"0", "false", "off"}
            )
            segments: list[
                tuple[
                    str,
                    float,
                    tuple[int, int, int],
                    bool,
                    bool,
                    bool,
                    str | None,
                    bool,
                ]
            ] = []
            dynamic_result_runs = {
                id(run)
                for field in _iter_named(paragraph, "fldSimple")
                for run in _iter_named(field, "r")
            }
            in_complex_field_result = False
            for run in _iter_named(paragraph, "r"):
                field_markers = [
                    (_attribute_named(marker, "fldCharType") or "").casefold()
                    for marker in _iter_named(run, "fldChar")
                ]
                if "separate" in field_markers:
                    in_complex_field_result = True
                    continue
                if "end" in field_markers:
                    in_complex_field_result = False
                    continue
                if id(run) in dynamic_result_runs or in_complex_field_result:
                    continue
                if is_hidden_run(run, paragraph_style):
                    # Word does not render hidden runs, so they carry no visible
                    # authority and must not become a fidelity expectation.
                    continue
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
                font_family = (
                    font_from_properties(run_properties)
                    or resolve_style_font(run_style, paragraph_font)
                    if run_style
                    else font_from_properties(run_properties)
                    or paragraph_font
                )
                color = (
                    color_from_properties(run_properties)
                    or resolve_style_color(run_style, paragraph_color)
                    if run_style
                    else color_from_properties(run_properties)
                    or paragraph_color
                )
                bold = (
                    on_off_from_properties(run_properties, "b")
                    if on_off_from_properties(run_properties, "b") is not None
                    else bool(
                        resolve_style_value(run_style, style_bold, paragraph_bold)
                    )
                )
                italic = (
                    on_off_from_properties(run_properties, "i")
                    if on_off_from_properties(run_properties, "i") is not None
                    else bool(
                        resolve_style_value(
                            run_style, style_italic, paragraph_italic
                        )
                    )
                )
                underline_value = underline_from_properties(run_properties)
                underline = (
                    underline_value
                    if underline_value is not None
                    else bool(
                        resolve_style_value(
                            run_style, style_underline, paragraph_underline
                        )
                    )
                )
                enforce_visible_run_style = bool(
                    not in_table
                    or run_properties is not None
                    or run_style
                    or paragraph_style
                    or default_paragraph_style
                    or table_layers
                )
                raw_text = "".join(
                    item.text or ""
                    for item in _iter_named(run, "t")
                    if item.text
                )
                if raw_text and not raw_text.strip() and segments:
                    previous = segments[-1]
                    segments[-1] = (previous[0] + raw_text, *previous[1:])
                    continue
                if not raw_text.strip():
                    continue
                if (
                    segments
                    and abs(segments[-1][1] - size) <= 0.01
                    and segments[-1][2] == color
                    and segments[-1][3:] == (
                        bold,
                        italic,
                        underline,
                        font_family,
                        enforce_visible_run_style,
                    )
                ):
                    previous_text, previous_size, previous_color, *_ = segments[-1]
                    segments[-1] = (
                        previous_text + raw_text,
                        previous_size,
                        previous_color,
                        bold,
                        italic,
                        underline,
                        font_family,
                        enforce_visible_run_style,
                    )
                else:
                    segments.append(
                        (
                            raw_text,
                            size,
                            color,
                            bold,
                            italic,
                            underline,
                            font_family,
                            enforce_visible_run_style,
                        )
                    )
            paragraph_line_height = resolved_line_height(
                paragraph_line_spacing,
                max((segment[1] for segment in segments), default=paragraph_size),
            )
            for segment_index, (
                text,
                size,
                color,
                bold,
                italic,
                underline,
                font_family,
                enforce_visible_run_style,
            ) in enumerate(segments):
                normalized = _normalized_visible_text(text)
                if not normalized:
                    continue
                expected_top_offset = (
                    anchor_top_margin
                    + anchor_preceding_blank_height
                    + paragraph_spacing_before
                    if name == "word/document.xml"
                    and id(paragraph) == anchor_paragraph_id
                    and segment_index == 0
                    and anchor_top_margin is not None
                    else None
                )
                body_flow_anchor = (
                    name == "word/document.xml"
                    and not in_table
                    and not paragraph_has_drawing
                    and segment_index == 0
                )
                expected_previous_top_gap = (
                    previous_body_line_height
                    + previous_body_after
                    + pending_blank_height
                    + paragraph_spacing_before
                    if body_flow_anchor and previous_body_line_height is not None
                    else None
                )
                expectations.append(
                    _WordTextExpectation(
                        normalized,
                        size,
                        color,
                        bold,
                        italic,
                        underline,
                        paragraph_alignment,
                        in_table,
                        font_family,
                        expected_top_offset,
                        None,
                        body_flow_anchor,
                        expected_previous_top_gap,
                        enforce_visible_run_style,
                        paragraph_line_height,
                        segment_index > 0,
                        paragraph_page_break_before and segment_index == 0,
                    )
                )
            if name == "word/document.xml":
                if in_table or paragraph_has_drawing:
                    previous_body_line_height = None
                    previous_body_after = 0.0
                    pending_blank_height = 0.0
                elif segments:
                    previous_body_line_height = paragraph_line_height
                    previous_body_after = paragraph_spacing_after
                    pending_blank_height = 0.0
                else:
                    pending_blank_height += (
                        paragraph_spacing_before
                        + paragraph_line_height
                        + paragraph_spacing_after
                    )
    return expectations


def _text_sizes_match(
    expectations: list[_WordTextExpectation],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    if not expectations:
        return True
    used_fragments: set[int] = set()
    previous_body_fragments: list[_PositionedText] | None = None
    paragraph_wrap_anchor: _ParagraphWrapAnchor | None = None
    for expectation in expectations:
        match: tuple[int, int] | None = None
        for start in range(len(positioned)):
            if (
                expectation.expected_page is not None
                and positioned[start].page != expectation.expected_page
            ):
                continue
            end = _fragment_sequence_end(
                expectation.text,
                positioned,
                start,
                barriers,
                allow_line_wrap=True,
                alignment=expectation.alignment,
                expected_line_height=expectation.line_height,
                wrap_anchor=(
                    paragraph_wrap_anchor
                    if expectation.paragraph_continuation
                    else None
                ),
            )
            if end is None:
                continue
            if any(index in used_fragments for index in range(start, end)):
                continue
            tolerance = max(1.5, expectation.font_size * 0.12)
            matched_fragments = positioned[start:end]
            style_matches = all(
                abs(fragment.font_size - expectation.font_size) <= tolerance
                and (
                    not expectation.enforce_visible_run_style
                    or (
                        all(
                            abs(observed - expected) <= 8
                            for observed, expected in zip(
                                fragment.color, expectation.color
                            )
                        )
                        and (fragment.font_weight >= 600) == expectation.bold
                        and (abs(fragment.italic_angle) >= 2) == expectation.italic
                    )
                )
                and (
                    expectation.font_family is None
                    or fragment.font_family is not None
                    and _normalized_font_family(fragment.font_family)
                    == _normalized_font_family(expectation.font_family)
                )
                for fragment in matched_fragments
            )
            page = matched_fragments[0].page
            line_tolerance = max(
                3.0,
                0.35 * max(fragment.font_size for fragment in matched_fragments),
            )

            def fragment_line_matches(anchor: _PositionedText) -> bool:
                line = [
                    fragment
                    for fragment in positioned
                    if fragment.page == anchor.page
                    and max(fragment.bottom, anchor.bottom)
                    - min(fragment.top, anchor.top)
                    <= line_tolerance
                ]
                line_left = min(fragment.x for fragment in line)
                line_right = max(fragment.right for fragment in line)
                page_width = anchor.page_width
                if expectation.alignment in {"left", "both"}:
                    return line_left <= page_width * 0.25
                if expectation.alignment == "right":
                    return line_right >= page_width * 0.75
                return abs((line_left + line_right) / 2 - page_width / 2) <= max(
                    4.0, page_width * 0.03
                )

            alignment_matches = expectation.in_table or all(
                fragment_line_matches(fragment) for fragment in matched_fragments
            )
            vertical_matches = expectation.expected_top_offset is None or (
                page == 0
                and abs(
                    matched_fragments[0].page_height
                    - max(fragment.top for fragment in matched_fragments)
                    - expectation.expected_top_offset
                )
                <= max(18.0, expectation.font_size * 1.75)
            )
            flow_matches = True
            if (
                expectation.body_flow_anchor
                and expectation.expected_previous_top_gap is not None
            ):
                if previous_body_fragments is None:
                    flow_matches = False
                else:
                    previous_page = previous_body_fragments[-1].page
                    if page == previous_page:
                        previous_page_fragments = [
                            fragment
                            for fragment in previous_body_fragments
                            if fragment.page == previous_page
                        ]
                        observed_gap = min(
                            fragment.top for fragment in previous_page_fragments
                        ) - max(fragment.top for fragment in matched_fragments)
                        missing_flow_tolerance = max(
                            6.0, expectation.font_size * 0.75
                        )
                        additional_flow_tolerance = max(
                            6.0, expectation.font_size * 0.75
                        )
                        flow_matches = (
                            observed_gap >= 0
                            and observed_gap
                            >= expectation.expected_previous_top_gap
                            - missing_flow_tolerance
                            and observed_gap
                            <= expectation.expected_previous_top_gap
                            + additional_flow_tolerance
                        )
                    else:
                        previous_fragment = previous_body_fragments[-1]
                        current_fragment = matched_fragments[0]
                        flow_matches = (
                            page == previous_page + 1
                            and current_fragment.top
                            >= current_fragment.page_height * 0.70
                            and (
                                expectation.page_break_before
                                or previous_fragment.top
                                <= previous_fragment.page_height * 0.30
                            )
                        )
            if (
                style_matches
                and alignment_matches
                and vertical_matches
                and flow_matches
            ):
                match = (start, end)
                break
        if match is None:
            return False
        used_fragments.update(range(*match))
        if not expectation.paragraph_continuation:
            paragraph_fragments = positioned[match[0] : match[1]]
            first_fragment = paragraph_fragments[0]
            anchor_tolerance = max(3.0, first_fragment.font_size * 0.35)
            first_line = [
                fragment
                for fragment in paragraph_fragments
                if fragment.page == first_fragment.page
                and max(fragment.bottom, first_fragment.bottom)
                - min(fragment.top, first_fragment.top)
                <= anchor_tolerance
            ]
            paragraph_wrap_anchor = _ParagraphWrapAnchor(
                first_fragment.page,
                min(fragment.x for fragment in first_line),
                max(fragment.right for fragment in first_line),
                min(fragment.bottom for fragment in first_line),
                max(fragment.top for fragment in first_line),
            )
        elif paragraph_wrap_anchor is not None:
            first_fragment = positioned[match[0]]
            line_tolerance = max(3.0, first_fragment.font_size * 0.35)
            horizontal_tolerance = max(18.0, 1.5 * first_fragment.font_size)
            same_anchor_line = (
                first_fragment.page == paragraph_wrap_anchor.page
                and max(first_fragment.bottom, paragraph_wrap_anchor.bottom)
                - min(first_fragment.top, paragraph_wrap_anchor.top)
                <= line_tolerance
                and first_fragment.x
                <= paragraph_wrap_anchor.right + horizontal_tolerance
                and first_fragment.right
                >= paragraph_wrap_anchor.left - horizontal_tolerance
            )
            if same_anchor_line:
                paragraph_wrap_anchor = _ParagraphWrapAnchor(
                    paragraph_wrap_anchor.page,
                    min(paragraph_wrap_anchor.left, first_fragment.x),
                    max(paragraph_wrap_anchor.right, first_fragment.right),
                    min(paragraph_wrap_anchor.bottom, first_fragment.bottom),
                    max(paragraph_wrap_anchor.top, first_fragment.top),
                )
        if expectation.body_flow_anchor:
            previous_body_fragments = positioned[match[0] : match[1]]
    return True


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
        # Coverage is measured against the glyph's own extent, not the cropped
        # box.  The box is padded by 1pt per side to tolerate rasterisation
        # offsets; that padding carries no ink, so using it as the denominator
        # put the threshold out of reach for any glyph narrower than roughly
        # 2pt -- "I", "l", "i" and the Roman numerals that fill judicial
        # reports would read as non-visible in a faithful render.
        glyph_columns = min(
            float(difference.width), max(1.0, (right - left) * scale)
        )
        glyph_rows = min(
            float(difference.height), max(1.0, (top - bottom) * scale)
        )
        return (
            active_columns >= max(1, math.ceil(glyph_columns * minimum_axis_coverage))
            and active_rows >= max(1, math.ceil(glyph_rows * minimum_axis_coverage))
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


def _page_object_stroke_rgba(item: object) -> tuple[int, int, int, int] | None:
    values = tuple(ctypes.c_uint() for _ in range(4))
    if not pdfium.raw.FPDFPageObj_GetStrokeColor(
        item.raw,
        ctypes.byref(values[0]),
        ctypes.byref(values[1]),
        ctypes.byref(values[2]),
        ctypes.byref(values[3]),
    ):
        return None
    return tuple(int(value.value) for value in values)


def _path_paint_properties(
    item: object,
) -> tuple[int, bool, tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
    fill_mode = ctypes.c_int()
    stroke = ctypes.c_int()
    if not pdfium.raw.FPDFPath_GetDrawMode(
        item.raw, ctypes.byref(fill_mode), ctypes.byref(stroke)
    ):
        return -1, True, None, None
    return (
        fill_mode.value,
        bool(stroke.value),
        _page_object_fill_rgba(item) if fill_mode.value else None,
        _page_object_stroke_rgba(item) if stroke.value else None,
    )


def _path_has_visible_paint(item: object) -> bool:
    fill_mode, stroke, fill_color, stroke_color = _path_paint_properties(item)
    if fill_mode < 0:
        return True
    if fill_mode:
        if fill_color is None or fill_color[3] > 0:
            return True
    if not stroke:
        return False
    return stroke_color is None or stroke_color[3] > 0


def _text_free_background(pdf_content: bytes, page_number: int, scale: float):
    """Render one page with its direct text removed, on an independent copy.

    The occlusion check needs a text-free raster of the same page.  Producing it
    by removing objects from the document the layout was just read from mutates
    the analysis subject and transfers ownership of objects that are closed
    afterwards.  This builds the temporary analytical representation the
    fidelity contract allows: a separate load of the same bytes, discarded here.
    The delivered PDF is never touched.
    """
    document = pdfium.PdfDocument(pdf_content)
    page = None
    bitmap = None
    removed: list[object] = []
    try:
        page = document[page_number]
        for item in page.get_objects(max_depth=15):
            if item.type == pdfium.raw.FPDF_PAGEOBJ_TEXT and item.container is None:
                removed.append(item)
            else:
                item.close()
        for item in removed:
            page.remove_obj(item)
        if removed:
            page.gen_content()
        bitmap = page.render(scale=scale)
        return bitmap.to_pil()
    finally:
        if bitmap is not None:
            bitmap.close()
        for item in removed:
            item.close()
        if page is not None:
            page.close()
        document.close()


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
                        if item.container is not None:
                            unsafe = True
                        fill_color = _page_object_fill_rgba(item)
                        if fill_color is None or fill_color[3] < 252:
                            unsafe = True
                            text_color = (0, 0, 0)
                        else:
                            text_color = fill_color[:3]
                        try:
                            font = item.get_font()
                            font_weight = int(font.get_weight())
                            font_family = str(
                                font.get_family_name() or font.get_base_name()
                            ).strip()
                            if not font_family:
                                raise ValueError("PDF font family is unavailable")
                            italic_value = ctypes.c_int()
                            if not pdfium.raw.FPDFFont_GetItalicAngle(
                                font.raw, ctypes.byref(italic_value)
                            ):
                                raise ValueError("PDF font italic angle is unavailable")
                            italic_angle = int(italic_value.value)
                        except (AttributeError, RuntimeError, TypeError, ValueError):
                            unsafe = True
                            font_weight = 400
                            font_family = None
                            italic_angle = 0
                        positioned.append(
                            _PositionedText(
                                page=page_number,
                                text=text,
                                x=left,
                                y=bottom,
                                font_size=float(item.get_font_size()),
                                right=right,
                                bottom=bottom,
                                top=top,
                                color=text_color,
                                font_weight=font_weight,
                                italic_angle=italic_angle,
                                page_width=width,
                                font_family=font_family,
                                page_height=height,
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
                        fill_mode, stroke, fill_color, stroke_color = (
                            _path_paint_properties(item)
                        )
                        painted_paths.append(
                            _PaintedPath(
                                page_number,
                                left,
                                bottom,
                                right,
                                top,
                                fill_color,
                                stroke_color,
                                fill_mode,
                                stroke,
                            )
                        )
                    elif item.type not in {
                        pdfium.raw.FPDF_PAGEOBJ_TEXT,
                        pdfium.raw.FPDF_PAGEOBJ_IMAGE,
                        pdfium.raw.FPDF_PAGEOBJ_PATH,
                    }:
                        # Shadings and opaque container objects have no
                        # source-side Word authority in the supported model.
                        unsafe = True
                background = _text_free_background(pdf_content, page_number, scale)
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
    *,
    allow_line_wrap: bool = False,
    alignment: str | None = None,
    expected_line_height: float | None = None,
    wrap_anchor: _ParagraphWrapAnchor | None = None,
) -> int | None:
    normalized_target = _normalized_visible_text(expected)
    text_candidates = {""}
    previous: _PositionedText | None = None
    line_start: _PositionedText | None = None
    active_wrap_anchor = wrap_anchor
    for index in range(start, len(fragments)):
        fragment = fragments[index]
        if line_start is None:
            line_start = fragment
            if active_wrap_anchor is not None:
                line_tolerance = max(3.0, 0.35 * fragment.font_size)
                horizontal_tolerance = max(18.0, 1.5 * fragment.font_size)
                same_anchor_line = (
                    fragment.page == active_wrap_anchor.page
                    and max(fragment.bottom, active_wrap_anchor.bottom)
                    - min(fragment.top, active_wrap_anchor.top)
                    <= line_tolerance
                    and fragment.x
                    <= active_wrap_anchor.right + horizontal_tolerance
                    and fragment.right
                    >= active_wrap_anchor.left - horizontal_tolerance
                )
                if same_anchor_line:
                    active_wrap_anchor = _ParagraphWrapAnchor(
                        active_wrap_anchor.page,
                        min(active_wrap_anchor.left, fragment.x),
                        max(active_wrap_anchor.right, fragment.right),
                        min(active_wrap_anchor.bottom, fragment.bottom),
                        max(active_wrap_anchor.top, fragment.top),
                    )
        if previous is not None:
            line_tolerance = max(3.0, 0.35 * max(previous.font_size, fragment.font_size))
            vertical_gap = max(previous.bottom, fragment.bottom) - min(
                previous.top, fragment.top
            )
            estimated_end = previous.x + len(previous.text) * previous.font_size * 0.6
            horizontal_tolerance = max(18.0, 1.5 * max(previous.font_size, fragment.font_size))
            same_line = (
                vertical_gap <= line_tolerance
                and fragment.x >= previous.x
                and fragment.x <= estimated_end + horizontal_tolerance
            )
            line_step = previous.top - fragment.top
            wrap_alignment = alignment
            if wrap_alignment is None and line_start is not None:
                prior_center = (line_start.x + previous.right) / 2
                if line_start.x <= previous.page_width * 0.25:
                    wrap_alignment = "left"
                elif previous.right >= previous.page_width * 0.75:
                    wrap_alignment = "right"
                elif abs(prior_center - previous.page_width / 2) <= max(
                    4.0, previous.page_width * 0.08
                ):
                    wrap_alignment = "center"
            maximum_line_step = max(
                24.0,
                expected_line_height or 0.0,
                2.25 * max(previous.font_size, fragment.font_size),
            )
            if wrap_alignment in {"left", "both"}:
                wrap_anchor_matches = (
                    line_start is not None
                    and abs(
                        fragment.x
                        - (
                            active_wrap_anchor.left
                            if active_wrap_anchor is not None
                            else line_start.x
                        )
                    )
                    <= horizontal_tolerance
                )
            elif wrap_alignment == "right":
                wrap_anchor_matches = (
                    abs(
                        fragment.right
                        - (
                            active_wrap_anchor.right
                            if active_wrap_anchor is not None
                            else previous.right
                        )
                    )
                    <= horizontal_tolerance
                )
            elif wrap_alignment == "center" and line_start is not None:
                prior_center = (
                    (active_wrap_anchor.left + active_wrap_anchor.right) / 2
                    if active_wrap_anchor is not None
                    else (line_start.x + previous.right) / 2
                )
                wrap_anchor_matches = abs(
                    (fragment.x + fragment.right) / 2
                    - prior_center
                ) <= horizontal_tolerance
            else:
                wrap_anchor_matches = False
            wrapped_line = (
                allow_line_wrap
                and 0 < line_step <= maximum_line_step
                and wrap_anchor_matches
            )
            wrapped_page = (
                allow_line_wrap
                and fragment.page == previous.page + 1
                and previous.top <= previous.page_height * 0.30
                and fragment.top >= fragment.page_height * 0.70
                and wrap_anchor_matches
            )
            left_fragment, right_fragment = sorted(
                (previous, fragment), key=lambda value: value.x
            )
            crosses_barrier = any(
                barrier.page == fragment.page
                and left_fragment.right <= right_fragment.x
                and barrier.left >= left_fragment.right - 0.5
                and barrier.right <= right_fragment.x + 0.5
                and barrier.bottom <= max(previous.top, fragment.top)
                and barrier.top >= min(previous.bottom, fragment.bottom)
                for barrier in barriers
            )
            same_page_continuation = (
                fragment.page == previous.page and (same_line or wrapped_line)
            )
            if not (same_page_continuation or wrapped_page) or crosses_barrier:
                return None
            if wrapped_line or wrapped_page:
                line_start = fragment
        fragment_text = _normalized_visible_text(fragment.text)
        next_candidates = {
            candidate
            for observed in text_candidates
            for candidate in (
                _normalized_visible_text(observed + fragment_text),
                _normalized_visible_text(observed + " " + fragment_text),
            )
            if normalized_target.startswith(candidate)
        }
        if normalized_target in next_candidates:
            return index + 1
        if not next_candidates:
            return None
        text_candidates = next_candidates
        previous = fragment
    return None


def _ordered_text_blocks_match(
    blocks: list[str],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
) -> bool:
    if not blocks:
        return True
    cursor = 0
    for block in blocks:
        match = next(
            (
                (start, end)
                for start in range(cursor, len(positioned))
                if (
                    end := _fragment_sequence_end(
                        block,
                        positioned,
                        start,
                        barriers,
                        allow_line_wrap=True,
                    )
                )
                is not None
            ),
            None,
        )
        if match is None:
            return False
        cursor = match[1]
    return True


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
    ordered = _positioned_reading_order(positioned)
    previous_position: tuple[int, float] | None = None
    selected_rows: list[list[_PositionedText]] = []
    for row in rows:
        matching_positions: dict[tuple[int, float], list[_PositionedText]] = {}
        for anchor in ordered:
            line_tolerance = max(3.0, 0.35 * anchor.font_size)
            line_starts = [
                index
                for index, fragment in enumerate(ordered)
                if fragment.page == anchor.page
                and abs(fragment.y - anchor.y) <= line_tolerance
            ]
            cursor = 0
            matched = True
            matched_fragments: list[_PositionedText] = []
            for cell in row:
                end = None
                for start in line_starts:
                    if start < cursor:
                        continue
                    end = next(
                        (
                            candidate
                            for alignment in ("left", "right", "center")
                            if (
                                candidate := _fragment_sequence_end(
                                    cell,
                                    ordered,
                                    start,
                                    barriers,
                                    allow_line_wrap=True,
                                    alignment=alignment,
                                )
                            )
                            is not None
                        ),
                        None,
                    )
                    if end is not None:
                        break
                if end is None:
                    matched = False
                    break
                matched_fragments.extend(ordered[start:end])
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


def _table_cell_fill_matches(
    *,
    cell: _WordTableCellExpectation,
    paths: list[_PaintedPath],
    used: set[int],
    page: int,
    bounds: tuple[float, float, float, float],
    color_matches: Callable[
        [tuple[int, int, int, int] | None, tuple[int, int, int, int]], bool
    ],
) -> bool:
    if cell.fill_color is None:
        return True
    left, bottom, right, top = bounds
    candidates = [
        index
        for index, path in enumerate(paths)
        if index not in used
        and path.page == page
        and path.fill_mode > 0
        and not path.stroke
        and color_matches(path.fill_color, cell.fill_color)
        and path.left >= left - 2.0
        and path.right <= right + 2.0
        and path.bottom >= bottom - 2.0
        and path.top <= top + 2.0
    ]
    cell_area = max((right - left) * (top - bottom), 1.0)
    if not candidates or not any(
        (paths[index].right - paths[index].left)
        * (paths[index].top - paths[index].bottom)
        >= cell_area * 0.2
        for index in candidates
    ):
        return False
    used.update(candidates)
    return True


def _table_cell_and_fill_match(
    *,
    cell: _WordTableCellExpectation,
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
    paths: list[_PaintedPath],
    used: set[int],
    page: int,
    bounds: tuple[float, float, float, float],
    color_matches: Callable[
        [tuple[int, int, int, int] | None, tuple[int, int, int, int]], bool
    ],
) -> bool:
    left, bottom, right, top = bounds
    cell_fragments = _positioned_reading_order(
        [
            fragment
            for fragment in positioned
            if fragment.page == page
            and fragment.x >= left - 2.0
            and fragment.right <= right + 2.0
            and fragment.bottom >= bottom - 2.0
            and fragment.top <= top + 2.0
        ]
    )
    paragraph_cursor = 0
    for paragraph in cell.paragraphs:
        end = _fragment_sequence_end(
            paragraph, cell_fragments, paragraph_cursor, barriers
        )
        if end is None:
            return False
        paragraph_cursor = end
    return _table_cell_fill_matches(
        cell=cell,
        paths=paths,
        used=used,
        page=page,
        bounds=bounds,
        color_matches=color_matches,
    )


def _painted_paths_are_bound_to_tables(
    paths: list[_PaintedPath],
    tables: list[_WordTableExpectation],
    positioned: list[_PositionedText],
    barriers: list[_VerticalBarrier],
    text_expectations: list[_WordTextExpectation] | None = None,
) -> bool:
    def native_black_fill(path: _PaintedPath) -> bool:
        return (
            path.fill_mode > 0
            and not path.stroke
            and path.fill_color is not None
            and path.fill_color[3] >= 252
            and max(path.fill_color[:3]) <= 8
        )

    def color_matches(
        observed: tuple[int, int, int, int] | None,
        expected: tuple[int, int, int, int],
    ) -> bool:
        return observed is not None and all(
            abs(left - right) <= 2 for left, right in zip(observed, expected)
        )

    used: set[int] = set()
    used_text_fragments: set[int] = set()
    for expectation in text_expectations or []:
        if not expectation.underline:
            continue
        match = next(
            (
                (start, end)
                for start in range(len(positioned))
                if (
                    end := _fragment_sequence_end(
                        expectation.text, positioned, start, barriers
                    )
                )
                is not None
                and not any(
                    index in used_text_fragments for index in range(start, end)
                )
            ),
            None,
        )
        if match is None:
            return False
        used_text_fragments.update(range(*match))
        fragments = positioned[match[0] : match[1]]
        pages = {fragment.page for fragment in fragments}
        if len(pages) != 1:
            return False
        page = next(iter(pages))
        left = min(fragment.x for fragment in fragments)
        right = max(fragment.right for fragment in fragments)
        bottom = min(fragment.bottom for fragment in fragments)
        candidates = [
            index
            for index, path in enumerate(paths)
            if index not in used
            and path.page == page
            and native_black_fill(path)
            and path.right - path.left > 4 * (path.top - path.bottom)
            and abs(path.left - left) <= 2.0
            and abs(path.right - right) <= 2.0
            and path.top <= bottom + 1.0
            and bottom - path.top <= 3.0
        ]
        if len(candidates) != 1:
            return False
        used.add(candidates[0])

    rows = [row for table in tables for row in table.rows]
    matched_rows = _matched_table_row_fragments(rows, positioned, barriers)
    if matched_rows is None:
        return False
    cursor = 0
    for table in tables:
        table_rows = matched_rows[cursor : cursor + len(table.rows)]
        cursor += len(table.rows)
        has_cell_fills = any(cell.fill_color is not None for cell in table.cells)
        if not table.painted_grid and not table.horizontal_borders and not has_cell_fills:
            continue
        if len(table.column_offsets) < 2:
            return False

        page_segments: list[list[tuple[int, list[_PositionedText]]]] = []
        for row_index, row in enumerate(table_rows):
            row_pages = {fragment.page for fragment in row}
            if len(row_pages) != 1:
                return False
            page = next(iter(row_pages))
            if not page_segments or page_segments[-1][0][1][0].page != page:
                page_segments.append([])
            page_segments[-1].append((row_index, row))

        def clusters(values: list[float]) -> list[list[float]]:
            grouped: list[list[float]] = []
            for value in sorted(values):
                if not grouped or abs(value - sum(grouped[-1]) / len(grouped[-1])) > 1.0:
                    grouped.append([value])
                else:
                    grouped[-1].append(value)
            return grouped

        for segment in page_segments:
            row_indices = [row_index for row_index, _row in segment]
            fragments = [
                fragment for _row_index, row in segment for fragment in row
            ]
            page = fragments[0].page
            left = min(fragment.x for fragment in fragments) - 12.0
            table_width = table.column_offsets[-1]
            right = min(fragment.x for fragment in fragments) + table_width + 12.0
            bottom = min(fragment.bottom for fragment in fragments) - 12.0
            top = max(fragment.top for fragment in fragments) + 12.0
            if not table.painted_grid:
                if len(page_segments) != 1 or not table.horizontal_borders:
                    return False
                border_colors = {
                    color for _boundary, color in table.horizontal_borders
                }
                border_candidates = [
                    index
                    for index, path in enumerate(paths)
                    if index not in used
                    and path.page == page
                    and path.left >= left
                    and path.right <= right
                    and path.bottom >= bottom
                    and path.top <= top
                    and min(
                        path.right - path.left, path.top - path.bottom
                    ) <= 1.5
                    and any(
                        color_matches(path.fill_color, color)
                        for color in border_colors
                    )
                ]
                border_paths = [paths[index] for index in border_candidates]
                y_clusters = clusters(
                    [(path.bottom + path.top) / 2 for path in border_paths]
                )
                expected_boundaries = sorted(
                    boundary for boundary, _color in table.horizontal_borders
                )
                if len(y_clusters) != len(expected_boundaries):
                    return False
                y_centers_by_boundary = {
                    boundary: sum(group) / len(group)
                    for boundary, group in zip(expected_boundaries, y_clusters)
                }
                table_left = min(path.left for path in border_paths)
                table_right = table_left + table_width
                if abs(max(path.right for path in border_paths) - table_right) > max(
                    2.0, table_width * 0.03
                ):
                    return False
                x_centers = [
                    table_left + offset for offset in table.column_offsets
                ]
                y_centers = [
                    y_centers_by_boundary[index]
                    for index in range(len(table.rows) + 1)
                    if index in y_centers_by_boundary
                ]
                if len(y_centers) != len(table.rows) + 1:
                    return False
                for boundary, expected_color in table.horizontal_borders:
                    center = y_centers_by_boundary[boundary]
                    members = [
                        path
                        for path in border_paths
                        if color_matches(path.fill_color, expected_color)
                        and abs((path.bottom + path.top) / 2 - center) <= 1.0
                    ]
                    if (
                        not members
                        or min(path.left for path in members) > table_left + 2.0
                        or max(path.right for path in members) < table_right - 2.0
                    ):
                        return False
                row_positions = {
                    row_index: position
                    for position, row_index in enumerate(row_indices)
                }
                used.update(border_candidates)
                for cell in table.cells:
                    if cell.row_start not in row_positions or cell.row_end not in row_positions:
                        return False
                    start_position = row_positions[cell.row_start]
                    end_position = row_positions[cell.row_end]
                    cell_left = x_centers[cell.column_start]
                    cell_right = x_centers[cell.column_end]
                    cell_top = y_centers[-1 - start_position]
                    cell_bottom = y_centers[-2 - end_position]
                    if not _table_cell_and_fill_match(
                        cell=cell,
                        positioned=positioned,
                        barriers=barriers,
                        paths=paths,
                        used=used,
                        page=page,
                        bounds=(cell_left, cell_bottom, cell_right, cell_top),
                        color_matches=color_matches,
                    ):
                        return False
                continue
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
                and native_black_fill(path)
            ]
            if not candidates:
                return False
            table_paths = [paths[index] for index in candidates]
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
            active_boundaries = sorted(
                {0, len(table.column_offsets) - 1}.union(
                    *(set(table.row_boundaries[index]) for index in row_indices)
                )
            )
            if len(x_clusters) != len(active_boundaries) or len(y_clusters) != len(segment) + 1:
                return False
            x_centers = [sum(group) / len(group) for group in x_clusters]
            expected_x_offsets = [table.column_offsets[index] for index in active_boundaries]
            observed_x_offsets = [value - x_centers[0] for value in x_centers]
            if any(
                abs(observed - expected) > max(2.0, table_width * 0.03)
                for observed, expected in zip(observed_x_offsets, expected_x_offsets)
            ):
                return False
            y_centers = [sum(group) / len(group) for group in y_clusters]
            if any(
                not (
                    any(
                        abs((path.left + path.right) / 2 - center) <= 1.0
                        for center in x_centers
                    )
                    or any(
                        abs((path.bottom + path.top) / 2 - center) <= 1.0
                        for center in y_centers
                    )
                )
                for path in table_paths
            ):
                return False
            row_positions = {
                row_index: position
                for position, row_index in enumerate(row_indices)
            }
            for cell in table.cells:
                if cell.row_start not in row_positions:
                    continue
                if cell.row_end not in row_positions:
                    return False
                start_position = row_positions[cell.row_start]
                end_position = row_positions[cell.row_end]
                if end_position < start_position:
                    return False
                cell_left = x_centers[0] + table.column_offsets[cell.column_start]
                cell_right = x_centers[0] + table.column_offsets[cell.column_end]
                cell_top = y_centers[-1 - start_position]
                cell_bottom = y_centers[-2 - end_position]
                cell_fragments = _positioned_reading_order(
                    [
                        fragment
                        for fragment in positioned
                        if fragment.page == page
                        and fragment.x >= cell_left - 2.0
                        and fragment.right <= cell_right + 2.0
                        and fragment.bottom >= cell_bottom - 2.0
                        and fragment.top <= cell_top + 2.0
                    ]
                )
                paragraph_cursor = 0
                for paragraph in cell.paragraphs:
                    end = _fragment_sequence_end(
                        paragraph, cell_fragments, paragraph_cursor, barriers
                    )
                    if end is None:
                        return False
                    paragraph_cursor = end
                if not _table_cell_fill_matches(
                    cell=cell,
                    paths=paths,
                    used=used,
                    page=page,
                    bounds=(cell_left, cell_bottom, cell_right, cell_top),
                    color_matches=color_matches,
                ):
                    return False
            for cluster_index, group in enumerate(y_clusters):
                center = sum(group) / len(group)
                members = [
                    path
                    for path in horizontal_paths
                    if abs((path.bottom + path.top) / 2 - center) <= 1.0
                ]
                source_boundary = len(segment) - cluster_index
                if source_boundary in {0, len(segment)}:
                    active_ranges = [(0, len(table.column_offsets) - 1)]
                else:
                    lower_row_index = row_indices[source_boundary]
                    inactive = set()
                    for start, end in table.row_vertical_merge_ranges[
                        lower_row_index
                    ]:
                        inactive.update(range(start, end))
                    active_ranges = []
                    range_start: int | None = None
                    for column in range(len(table.column_offsets) - 1):
                        if column not in inactive and range_start is None:
                            range_start = column
                        if column in inactive and range_start is not None:
                            active_ranges.append((range_start, column))
                            range_start = None
                    if range_start is not None:
                        active_ranges.append(
                            (range_start, len(table.column_offsets) - 1)
                        )
                for start, end in active_ranges:
                    expected_left = x_centers[0] + table.column_offsets[start]
                    expected_right = x_centers[0] + table.column_offsets[end]
                    overlapping = [
                        path
                        for path in members
                        if path.right >= expected_left - 2.0
                        and path.left <= expected_right + 2.0
                    ]
                    if (
                        not overlapping
                        or min(path.left for path in overlapping)
                        > expected_left + 2.0
                        or max(path.right for path in overlapping)
                        < expected_right - 2.0
                    ):
                        return False
            for boundary, group in zip(active_boundaries, x_clusters):
                center = sum(group) / len(group)
                members = [
                    path
                    for path in vertical_paths
                    if abs((path.left + path.right) / 2 - center) <= 1.0
                ]
                for position, row_index in enumerate(row_indices):
                    row_boundaries = {
                        0,
                        len(table.column_offsets) - 1,
                        *table.row_boundaries[row_index],
                    }
                    if boundary not in row_boundaries:
                        continue
                    row_top = y_centers[-1 - position]
                    row_bottom = y_centers[-2 - position]
                    if not any(
                        path.bottom <= row_bottom + 2.0
                        and path.top >= row_top - 2.0
                        for path in members
                    ):
                        return False
            used.update(candidates)
    return len(used) == len(paths)


def _validate_pdf_fidelity(word_content: bytes, pdf_content: bytes) -> None:
    """Reject converter output that is not observably derived from the bound Word."""
    try:
        with ZipFile(BytesIO(word_content)) as package:
            styles_root = (
                ElementTree.fromstring(package.read("word/styles.xml"))
                if "word/styles.xml" in package.namelist()
                else None
            )
            table_styles = {
                _attribute_named(style, "styleId"): style
                for style in (_iter_named(styles_root, "style") if styles_root is not None else ())
                if (_attribute_named(style, "type") or "").casefold() == "table"
                and _attribute_named(style, "styleId")
            }

            def table_color(node: ElementTree.Element | None) -> tuple[int, int, int, int] | None:
                if node is None:
                    return None
                value = (_attribute_named(node, "fill") or _attribute_named(node, "color") or "").strip()
                if value.casefold() in {"", "auto", "none"}:
                    return None
                if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
                    raise ValueError("unsupported Word table color")
                return (*tuple(int(value[index : index + 2], 16) for index in (0, 2, 4)), 255)

            is_hidden_run = _hidden_run_resolver(styles_root)

            body_fragments: list[str] = []
            document_fragments: list[str] = []
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
                table_nodes = list(_iter_named(root, "tbl"))
                table_paragraph_ids = {
                    id(paragraph)
                    for table_node in table_nodes
                    for paragraph in _iter_named(table_node, "p")
                }
                paragraph_fragments = [
                    (paragraph, _visible_paragraph_text(paragraph, is_hidden_run))
                    for paragraph in _iter_named(root, "p")
                ]
                paragraph_fragments = [
                    (paragraph, fragment)
                    for paragraph, fragment in paragraph_fragments
                    if fragment.strip()
                ]
                fragments = [fragment for _paragraph, fragment in paragraph_fragments]
                if name == "word/document.xml":
                    body_fragments.extend(fragments)
                    document_fragments.extend(
                        fragment
                        for paragraph, fragment in paragraph_fragments
                        if id(paragraph) not in table_paragraph_ids
                    )
                elif name.startswith("word/header"):
                    header_fragments.extend(fragments)
                elif name.startswith("word/footer"):
                    footer_fragments.extend(fragments)
                for table in table_nodes:
                    grid = next(_children_named(table, "tblGrid"), None)
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
                    valid_grid = bool(grid_widths) and all(
                        math.isfinite(value) and value > 0 for value in grid_widths
                    )
                    column_offsets = [0.0]
                    if valid_grid:
                        for value in grid_widths:
                            column_offsets.append(column_offsets[-1] + value)

                    raw_rows: list[
                        list[
                            tuple[
                                int,
                                int,
                                str | None,
                                tuple[str, ...],
                                tuple[int, int, int, int] | None,
                            ]
                        ]
                    ] = []
                    inferred_column_count: int | None = None
                    for row in _children_named(table, "tr"):
                        cell_nodes = list(_children_named(row, "tc"))
                        position = 0
                        raw_cells: list[
                            tuple[
                                int,
                                int,
                                str | None,
                                tuple[str, ...],
                                tuple[int, int, int, int] | None,
                            ]
                        ] = []
                        valid_row = True
                        for cell in cell_nodes:
                            start = position
                            grid_span = _cell_property(cell, "gridSpan")
                            try:
                                span = int(
                                    (
                                        _attribute_named(grid_span, "val")
                                        if grid_span is not None
                                        else None
                                    )
                                    or "1"
                                )
                            except ValueError:
                                valid_row = False
                                break
                            if span < 1:
                                valid_row = False
                                break
                            position += span
                            vertical_merge = _cell_property(cell, "vMerge")
                            merge_state = (
                                (
                                    _attribute_named(vertical_merge, "val")
                                    or "continue"
                                ).casefold()
                                if vertical_merge is not None
                                else None
                            )
                            cell_paragraphs = tuple(
                                value
                                for paragraph in _iter_named(cell, "p")
                                if (
                                    value := _normalized_visible_text(
                                        _visible_paragraph_text(
                                            paragraph, is_hidden_run
                                        )
                                    )
                                )
                            )
                            cell_properties = next(_children_named(cell, "tcPr"), None)
                            direct_fill = table_color(
                                _first_named(cell_properties, "shd")
                            )
                            raw_cells.append(
                                (
                                    start,
                                    position,
                                    merge_state,
                                    cell_paragraphs,
                                    direct_fill,
                                )
                            )
                        if grid_columns:
                            column_count_matches = position == len(grid_columns)
                        else:
                            if inferred_column_count is None:
                                inferred_column_count = position
                            column_count_matches = position == inferred_column_count
                        if not valid_row or not column_count_matches:
                            raise ValueError("unsupported Word table structure")
                        raw_rows.append(raw_cells)
                    if not raw_rows:
                        raise ValueError("unsupported Word table structure")
                    rows: list[tuple[str, ...]] = []
                    row_cell_counts: list[int] = []
                    row_vertical_merge_continuations: list[int] = []
                    row_vertical_merge_ranges: list[tuple[tuple[int, int], ...]] = []
                    row_boundaries: list[tuple[int, ...]] = []
                    cells: list[_WordTableCellExpectation] = []
                    for row_index, raw_cells in enumerate(raw_rows):
                        anchors = tuple(
                            paragraphs[0]
                            for _start, _end, merge_state, paragraphs, _fill in raw_cells
                            if merge_state != "continue" and paragraphs
                        )
                        if not anchors:
                            raise ValueError("unsupported Word table structure")
                        rows.append(anchors)
                        row_cell_counts.append(len(raw_cells))
                        row_vertical_merge_continuations.append(
                            sum(
                                merge_state == "continue"
                                for _start, _end, merge_state, _paragraphs, _fill in raw_cells
                            )
                        )
                        row_vertical_merge_ranges.append(
                            tuple(
                                (start, end)
                                for start, end, merge_state, _paragraphs, _fill in raw_cells
                                if merge_state == "continue"
                            )
                        )
                        row_boundaries.append(
                            tuple(
                                end
                                for _start, end, _merge_state, _paragraphs, _fill in raw_cells
                                if end < len(grid_columns)
                            )
                        )
                        for start, end, merge_state, paragraphs, direct_fill in raw_cells:
                            if merge_state == "continue" or not paragraphs:
                                continue
                            row_end = row_index
                            if merge_state == "restart":
                                for candidate_index in range(
                                    row_index + 1, len(raw_rows)
                                ):
                                    continuation = next(
                                        (
                                                candidate
                                                for candidate in raw_rows[candidate_index]
                                                if candidate[0] == start
                                            and candidate[1] == end
                                        ),
                                        None,
                                    )
                                    if continuation is None or continuation[2] != "continue":
                                        break
                                    row_end = candidate_index
                            cells.append(
                                _WordTableCellExpectation(
                                    row_index,
                                    row_end,
                                    start,
                                    end,
                                    paragraphs,
                                    direct_fill,
                                )
                            )
                    style_id = _table_style_id(table)
                    style = (
                        (style_id or "")
                        .casefold()
                        .replace(" ", "")
                    )
                    horizontal_borders: dict[
                        int, tuple[int, int, int, int]
                    ] = {}
                    table_style = table_styles.get(style_id)
                    if table_style is not None:
                        table_look = _table_look(table)

                        def look_enabled(name: str, default: bool = False) -> bool:
                            return _table_look_flag(table_look, name, default=default)

                        first_row = look_enabled("firstRow", True)
                        last_row = look_enabled("lastRow")
                        no_horizontal_banding = look_enabled("noHBand")

                        def add_style_borders(
                            properties: ElementTree.Element | None,
                            *,
                            top_boundary: int,
                            bottom_boundary: int,
                        ) -> None:
                            borders = _first_named(properties, "tblBorders")
                            if borders is None:
                                borders = _first_named(properties, "tcBorders")
                            if borders is None:
                                return
                            for name, boundary in (
                                ("top", top_boundary),
                                ("bottom", bottom_boundary),
                            ):
                                border = _first_named(borders, name)
                                if border is None or (
                                    _attribute_named(border, "val") or ""
                                ).casefold() in {"nil", "none"}:
                                    continue
                                color = table_color(border)
                                if color is None:
                                    continue
                                existing = horizontal_borders.get(boundary)
                                if existing is not None and existing != color:
                                    raise ValueError("conflicting Word table border colors")
                                horizontal_borders[boundary] = color

                        add_style_borders(
                            next(_children_named(table_style, "tblPr"), None),
                            top_boundary=len(rows),
                            bottom_boundary=0,
                        )
                        conditional_styles = {
                            (_attribute_named(item, "type") or "").casefold(): item
                            for item in _children_named(table_style, "tblStylePr")
                        }
                        if first_row and rows:
                            first_properties = conditional_styles.get("firstrow")
                            add_style_borders(
                                _first_named(first_properties, "tcPr"),
                                top_boundary=len(rows),
                                bottom_boundary=len(rows) - 1,
                            )
                        if last_row and rows:
                            last_properties = conditional_styles.get("lastrow")
                            add_style_borders(
                                _first_named(last_properties, "tcPr"),
                                top_boundary=1,
                                bottom_boundary=0,
                            )
                        band_style = conditional_styles.get("band1horz")
                        band_fill = table_color(
                            _first_named(
                                _first_named(band_style, "tcPr"), "shd"
                            )
                        )
                        if band_fill is not None and not no_horizontal_banding:
                            style_properties = next(
                                _children_named(table_style, "tblPr"), None
                            )
                            band_size_node = _first_named(
                                style_properties, "tblStyleRowBandSize"
                            )
                            try:
                                band_size = int(
                                    _attribute_named(band_size_node, "val") or "1"
                                )
                            except ValueError as exc:
                                raise ValueError(
                                    "invalid Word table row band size"
                                ) from exc
                            if band_size < 1:
                                raise ValueError(
                                    "invalid Word table row band size"
                                )
                            start = 1 if first_row else 0
                            stop = len(rows) - (1 if last_row else 0)
                            band_rows = {
                                index
                                for index in range(start, stop)
                                if ((index - start) // band_size) % 2 == 0
                            }
                            cells = [
                                replace(
                                    cell,
                                    fill_color=(
                                        cell.fill_color
                                        if cell.fill_color is not None
                                        else band_fill
                                    ),
                                )
                                if cell.row_start in band_rows
                                else cell
                                for cell in cells
                            ]
                    column_count = len(grid_columns)
                    painted_grid = style == "tablegrid" and column_count > 0
                    table_rows.extend(rows)
                    tables.append(
                        _WordTableExpectation(
                            tuple(rows),
                            tuple(column_offsets) if valid_grid else (),
                            tuple(row_cell_counts),
                            tuple(row_vertical_merge_continuations),
                            tuple(row_vertical_merge_ranges),
                            tuple(row_boundaries),
                            tuple(cells),
                            painted_grid,
                            tuple(sorted(horizontal_borders.items())),
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
            header_footer_profile = _header_footer_profile(package, xml_roots)
            document_images = _ordered_word_image_signatures(package, document_roots)
            document_image_layouts = _ordered_word_image_layouts(document_roots)
            header_images = _ordered_word_image_signatures(package, header_roots)
            header_image_layouts = _ordered_word_image_layouts(header_roots)
            footer_images = _ordered_word_image_signatures(package, footer_roots)
            footer_image_layouts = _ordered_word_image_layouts(footer_roots)
            header_images_by_part = {
                name: _ordered_word_image_signatures(package, {name: root})
                for name, root in header_roots.items()
            }
            header_layouts_by_part = {
                name: _ordered_word_image_layouts({name: root})
                for name, root in header_roots.items()
            }
            footer_images_by_part = {
                name: _ordered_word_image_signatures(package, {name: root})
                for name, root in footer_roots.items()
            }
            footer_layouts_by_part = {
                name: _ordered_word_image_layouts({name: root})
                for name, root in footer_roots.items()
            }
            word_content_kinds = _word_content_kinds(document_roots)
            word_internal_links = _word_internal_link_expectations(
                xml_roots.get("word/document.xml")
            )
            word_page_geometry = _word_page_geometry(
                xml_roots.get("word/document.xml")
            )
        reader = PdfReader(BytesIO(pdf_content), strict=True)
        extracted_pages: list[str] = []
        unsafe_text = False
        pdf_images: list[tuple] = []
        page_heights: list[float] = []
        page_dimensions: list[tuple[float, float]] = []
        for page_number, page in enumerate(reader.pages):
            if (
                _has_nonvisible_text(page, reader)
                or _has_unsafe_image_drawing(page, reader)
            ):
                unsafe_text = True
            page_heights.append(float(page.mediabox.height))
            page_dimensions.append(
                (float(page.mediabox.width), float(page.mediabox.height))
            )
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
        annotations_match = _annotations_match_internal_links(
            reader, word_internal_links, reading_positioned, barriers
        )
        unsafe_text = unsafe_text or pdfium_unsafe
    except (BadZipFile, KeyError, ElementTree.ParseError, PdfReadError, OSError, RuntimeError, ValueError) as exc:
        raise ValueError("final PDF fidelity cannot be verified") from exc
    page_count = len(reader.pages)

    def selected_part(kind: str, page: int) -> str | None:
        if header_footer_profile is None:
            return None
        if page == 0 and bool(header_footer_profile.get("different_first")):
            value = header_footer_profile.get(f"{kind}_first")
        elif (page + 1) % 2 == 0 and bool(
            header_footer_profile.get("even_and_odd")
        ):
            value = header_footer_profile.get(f"{kind}_even")
        else:
            value = header_footer_profile.get(f"{kind}_default")
        return value if isinstance(value, str) else None

    def part_fragments(name: str | None, page: int) -> list[str]:
        if name is None:
            return []
        try:
            return [
                fragment
                for paragraph in _iter_named(xml_roots[name], "p")
                if (
                    fragment := _dynamic_paragraph_text(
                        paragraph, page_number=page + 1
                    )
                ).strip()
            ]
        except (KeyError, ValueError) as exc:
            raise ValueError("final PDF fidelity cannot be verified") from exc

    if header_footer_profile is None:
        header_fragments_by_page = [list(header_fragments) for _ in range(page_count)]
        footer_fragments_by_page = [list(footer_fragments) for _ in range(page_count)]
        repeatable_content_names_by_page = [
            {*header_roots, *footer_roots} for _ in range(page_count)
        ]
        header_image_signatures_by_page = [
            list(header_images) for _ in range(page_count)
        ]
        header_image_layouts_by_page = [
            list(header_image_layouts) for _ in range(page_count)
        ]
        footer_image_signatures_by_page = [
            list(footer_images) for _ in range(page_count)
        ]
        footer_image_layouts_by_page = [
            list(footer_image_layouts) for _ in range(page_count)
        ]
    else:
        selected_header_parts = [
            selected_part("header", page) for page in range(page_count)
        ]
        selected_footer_parts = [
            selected_part("footer", page) for page in range(page_count)
        ]
        header_fragments_by_page = [
            part_fragments(name, page)
            for page, name in enumerate(selected_header_parts)
        ]
        footer_fragments_by_page = [
            part_fragments(name, page)
            for page, name in enumerate(selected_footer_parts)
        ]
        repeatable_content_names_by_page = [
            {
                name
                for name in (header_name, footer_name)
                if name is not None
            }
            for header_name, footer_name in zip(
                selected_header_parts, selected_footer_parts
            )
        ]
        header_image_signatures_by_page = [
            list(header_images_by_part.get(name, []))
            for name in selected_header_parts
        ]
        header_image_layouts_by_page = [
            list(header_layouts_by_part.get(name, []))
            for name in selected_header_parts
        ]
        footer_image_signatures_by_page = [
            list(footer_images_by_part.get(name, []))
            for name in selected_footer_parts
        ]
        footer_image_layouts_by_page = [
            list(footer_layouts_by_part.get(name, []))
            for name in selected_footer_parts
        ]
    try:
        word_text_expectations = _word_text_expectations(
            xml_roots, active_content_names={"word/document.xml"}
        )
        for page, content_names in enumerate(repeatable_content_names_by_page):
            word_text_expectations.extend(
                replace(expectation, expected_page=page)
                for expectation in _word_text_expectations(
                    xml_roots, active_content_names=content_names
                )
            )
    except ValueError as exc:
        raise ValueError("final PDF fidelity cannot be verified") from exc

    source_tokens = _lexical_tokens(" ".join(body_fragments))
    pdf_tokens = _lexical_tokens(pdf_text)
    source_counts = Counter(source_tokens)
    pdf_counts = Counter(pdf_tokens)
    expected_repeatable_counts = Counter(
        _lexical_tokens(
            " ".join(
                fragment
                for page_fragments in (
                    header_fragments_by_page + footer_fragments_by_page
                )
                for fragment in page_fragments
            )
        )
    )
    token_counts_match = pdf_counts == source_counts + expected_repeatable_counts
    document_order_matches = _ordered_text_blocks_match(
        document_fragments, reading_positioned, barriers
    )
    repeatable_text_matches = _repeatable_text_matches(
        header_fragments_by_page=header_fragments_by_page,
        footer_fragments_by_page=footer_fragments_by_page,
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
        header_signatures_by_page=header_image_signatures_by_page,
        header_layouts_by_page=header_image_layouts_by_page,
        footer_signatures_by_page=footer_image_signatures_by_page,
        footer_layouts_by_page=footer_image_layouts_by_page,
    )
    tables_match = _table_rows_match(table_rows, reading_positioned, barriers)
    painted_paths_match = _painted_paths_are_bound_to_tables(
        painted_paths,
        tables,
        reading_positioned,
        barriers,
        word_text_expectations,
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
        or not annotations_match
        or not _page_geometry_matches(word_page_geometry, page_dimensions)
        or not _pdf_pages_have_visible_content(
            page_count, reading_positioned, pdf_image_layouts, painted_paths
        )
        or not _pdf_pages_have_document_content(
            extracted_pages=extracted_pages,
            header_fragments_by_page=header_fragments_by_page,
            footer_fragments_by_page=footer_fragments_by_page,
            image_layouts=pdf_image_layouts,
            painted_paths=painted_paths,
            page_heights=page_heights,
        )
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
                has_macro = any(
                    name.casefold()
                    in {"word/vbaproject.bin", "word/vbadata.xml"}
                    for name in names
                )
                content_types = ElementTree.fromstring(
                    package.read("[Content_Types].xml")
                )
                main_content_types = {
                    item.attrib.get("ContentType")
                    for item in content_types.iter(f"{_CT}Override")
                    if item.attrib.get("PartName") == "/word/document.xml"
                }
                for name in names:
                    if name.endswith(".rels"):
                        if any(
                            not _is_internal_relationship(item)
                            for item in _relationship_nodes(package.read(name))
                        ):
                            raise ValueError("external relationships are forbidden in delivery artifacts")
        except (BadZipFile, ElementTree.ParseError, OSError) as exc:
            raise ValueError("final Word artifact is invalid") from exc
        expected_main_type = (
            _DOCM_MAIN_CONTENT_TYPE
            if output_format == "DOCM"
            else _DOCX_MAIN_CONTENT_TYPE
        )
        if main_content_types != {expected_main_type} or (
            output_format == "DOCX" and has_macro
        ):
            raise ValueError("final Word artifact macro identity changed")
        media_type = _DOCM_MEDIA if output_format == "DOCM" else _DOCX_MEDIA
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
    """Admit the authoritative Word bytes to the local renderer without rewriting them.

    This deliberately no longer fabricates a substitute artifact.  Stripping the
    VBA parts out of a DOCM changed the bytes the renderer saw, broke
    ``WORD/DOCM = AUTHORITATIVE`` and left the fidelity oracle comparing the
    derived PDF against a product-made copy rather than against the authority.
    Macros are neutralised where the privilege actually lives: the Word worker
    forces ``AutomationSecurity`` to disable them and opens every document
    ``ReadOnly``, with automatic link and field updates off.
    """
    validate_final_artifact(content, output_format)
    if output_format not in {"DOCX", "DOCM"}:
        raise ValueError("unsupported final artifact format")
    return content, output_format


def verify_reopened_artifact(
    *, content: bytes, output_format: str, expected_size: int, expected_sha256: str,
) -> None:
    digest, size, _ = validate_delivery_artifact(content, output_format)
    if size != expected_size or digest != expected_sha256:
        raise ValueError("reopened artifact bytes diverge from finalized manifest")
