from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
from random import Random
from types import SimpleNamespace
from io import BytesIO
import zlib
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from jsonschema import Draft202012Validator
from PIL import Image, ImageFilter

from scripts.backend_contract import delivery_renderer

from scripts.backend_contract.delivery_foundation import (
    DeliveryAction,
    DeliveryArtifact,
    DeliveryBinding,
    DeliveryDecision,
    DeliveryFormat,
    DeliveryPackage,
    DeliveryRole,
    DeliverySnapshot,
    DeliveryState,
    delivery_snapshot_from_mapping,
    delivery_snapshot_to_mapping,
)
from scripts.backend_contract.delivery_renderer import (
    render_pdf_candidate,
    render_word_candidate,
    safe_pdf_conversion_copy,
    validate_supporting_artifact,
    validate_final_artifact,
    verify_reopened_artifact,
)
from scripts.backend_contract.report_template import template_binding_manifest_from_mapping
from scripts.backend_contract.application.delivery_foundation import (
    GetDeliverySnapshot,
    RenderDeliveryPackage,
    ReviewDeliverySnapshot,
    build_delivery_binding,
    mark_delivery_authority_unavailable,
    reconcile_delivery,
)
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.construction_defect_analysis import freeze_json_payload
from scripts.backend_contract.pericial_planning import pericial_planning_from_mapping
from scripts.backend_contract.report_foundation import report_snapshot_from_mapping, report_snapshot_to_mapping
from scripts.backend_contract.technical_findings import technical_snapshot_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping


SHA_A = "a" * 64
SHA_B = "b" * 64


def test_phase_c_word_worker_is_bounded_and_not_yet_product_composed() -> None:
    root = Path(__file__).parents[1]
    office_source = (
        root / "scripts/backend_contract/infrastructure/office_pdf.py"
    ).read_text(encoding="utf-8")
    worker_source = (
        root / "scripts/backend_contract/infrastructure/office_word_worker.py"
    ).read_text(encoding="utf-8")
    combined = office_source + worker_source
    assert "RENDER_BOUND_AUTHORITATIVE_WORD_TO_DERIVED_PDF" in combined
    assert r"SOFTWARE\Classes\Word.Application\CLSID" in worker_source
    assert "winreg.HKEY_LOCAL_MACHINE" in worker_source
    assert "DispatchEx" not in combined
    assert "WScript.Shell" not in combined
    assert "subprocess" not in combined
    assert "multiprocessing" not in combined
    assert "taskkill" not in combined.casefold()
    assert "pdf_converter" not in {item.name for item in fields(RenderDeliveryPackage)}
    composition = (root / "scripts/backend_contract/local_api/composition.py").read_text(encoding="utf-8")
    assert "LocalOfficePdfConverter" not in composition


def _parseable_text_pdf(text: str) -> bytes:
    encoded_lines = [line.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") for line in text.splitlines()]
    stream = b"BT /F1 10 Tf 50 780 Td 12 TL " + b" Tj T* ".join(b"(" + line + b")" for line in encoded_lines) + b" Tj ET"
    objects = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Page /Parent 4 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 1 0 R >> >> /Contents 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Catalog /Pages 4 0 R >>",
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets))
    output.extend(f"trailer << /Size 6 /Root 5 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return bytes(output)


def _positioned_text_pdf(
    pages: list[list[tuple[str, float, float, float, int]]],
) -> bytes:
    objects: list[bytes] = []

    def add(value: bytes) -> int:
        objects.append(value)
        return len(objects)

    font_id = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    content_ids: list[int] = []
    for fragments in pages:
        commands: list[bytes] = [b"BT"]
        for value, x, y, size, render_mode in fragments:
            encoded = (
                value.encode("cp1252")
                .replace(b"\\", b"\\\\")
                .replace(b"(", b"\\(")
                .replace(b")", b"\\)")
            )
            commands.append(
                f"/F1 {size:g} Tf {render_mode} Tr 1 0 0 1 {x:g} {y:g} Tm ".encode(
                    "ascii"
                )
                + b"("
                + b") Tj ("
                + encoded
                + b") Tj"
            )
        commands.append(b"ET")
        stream = b"\n".join(commands)
        content_ids.append(
            add(
                b"<< /Length "
                + str(len(stream)).encode("ascii")
                + b" >>\nstream\n"
                + stream
                + b"\nendstream"
            )
        )
    pages_id = len(objects) + len(pages) + 1
    page_ids = [
        add(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>".encode(
                "ascii"
            )
        )
        for content_id in content_ids
    ]
    kids = " ".join(f"{item} 0 R" for item in page_ids)
    add(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("ascii"))
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(
        f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    )
    output.extend(
        b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    )
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF".encode("ascii")
    )
    return bytes(output)


def _custom_content_pdf(stream: bytes, *, extra_resources: bytes = b"") -> bytes:
    objects = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Page /Parent 4 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 1 0 R >> "
        + extra_resources
        + b" >> /Contents 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Catalog /Pages 4 0 R >>",
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 6\n0000000000 65535 f \n")
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets))
    output.extend(f"trailer << /Size 6 /Root 5 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return bytes(output)


def _word_table_rows(rows: tuple[tuple[str, ...], ...]) -> bytes:
    output = BytesIO()
    table = "".join(
        "<w:tr>"
        + "".join(
            f"<w:tc><w:p><w:r><w:t>{cell}</w:t></w:r></w:p></w:tc>"
            for cell in cells
        )
        + "</w:tr>"
        for cells in rows
    )
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:tbl>{table}</w:tbl></w:body></w:document>"
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        package.writestr("word/document.xml", document)
    return output.getvalue()


def _word_table(cells: tuple[str, ...]) -> bytes:
    return _word_table_rows((cells,))


def _word_text(text: str) -> bytes:
    output = BytesIO()
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
    return output.getvalue()


def _word_runs(parts: tuple[tuple[str, int | None], ...]) -> bytes:
    runs = "".join(
        "<w:r>"
        + (
            ""
            if half_points is None
            else f'<w:rPr><w:sz w:val="{half_points}"/></w:rPr>'
        )
        + f"<w:t>{text}</w:t></w:r>"
        for text, half_points in parts
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p>{runs}</w:p></w:body></w:document>",
        )
    return output.getvalue()


def _word_with_default_paragraph_style(
    text: str,
    half_points: int,
    *,
    character_style: bool = False,
    ambiguous_default: bool = False,
) -> bytes:
    output = BytesIO()
    run_properties = (
        '<w:rPr><w:rStyle w:val="Emphasis"/></w:rPr>'
        if character_style
        else ""
    )
    character_style_xml = (
        '<w:style w:type="character" w:styleId="Emphasis"/>'
        if character_style
        else ""
    )
    foreign_namespace = ' xmlns:f="urn:synthetic:foreign"' if ambiguous_default else ""
    default_attributes = (
        'f:default="0" w:default="1"'
        if ambiguous_default
        else 'w:default="1"'
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r>{run_properties}<w:t>{text}</w:t></w:r></w:p>"
            "</w:body></w:document>",
        )
        package.writestr(
            "word/styles.xml",
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            f"{foreign_namespace}>"
            '<w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="22"/></w:rPr>'
            "</w:rPrDefault></w:docDefaults>"
            f'<w:style w:type="paragraph" {default_attributes} w:styleId="Normal">'
            f'<w:rPr><w:sz w:val="{half_points}"/></w:rPr>'
            f"</w:style>{character_style_xml}</w:styles>",
        )
    return output.getvalue()


def _word_with_strict_header(body_text: str, header_text: str) -> bytes:
    output = BytesIO()
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{body_text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    header = (
        '<w:hdr xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main">'
        f"<w:p><w:r><w:t>{header_text}</w:t></w:r></w:p></w:hdr>"
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
        package.writestr("word/header1.xml", header)
    return output.getvalue()


def _word_with_image_and_text(
    text: str,
    image_bytes: bytes,
    *,
    following_text: str | None = None,
    image_width: float = 40,
    image_height: float = 40,
    anchor_x: float | None = None,
    anchor_y: float | None = None,
    text_runs: tuple[str, ...] | None = None,
) -> bytes:
    output = BytesIO()
    width_emu = round(image_width * 12_700)
    height_emu = round(image_height * 12_700)
    if (anchor_x is None) != (anchor_y is None):
        raise ValueError("anchor coordinates must be provided together")
    if anchor_x is None:
        drawing = (
            "<wp:inline>"
            f'<wp:extent cx="{width_emu}" cy="{height_emu}"/>'
            '<a:graphic><a:graphicData><a:blip r:embed="rId1"/>'
            "</a:graphicData></a:graphic></wp:inline>"
        )
    else:
        drawing = (
            "<wp:anchor>"
            '<wp:positionH relativeFrom="page">'
            f"<wp:posOffset>{round(anchor_x * 12_700)}</wp:posOffset></wp:positionH>"
            '<wp:positionV relativeFrom="page">'
            f"<wp:posOffset>{round(anchor_y * 12_700)}</wp:posOffset></wp:positionV>"
            f'<wp:extent cx="{width_emu}" cy="{height_emu}"/>'
            '<a:graphic><a:graphicData><a:blip r:embed="rId1"/>'
            "</a:graphicData></a:graphic></wp:anchor>"
        )
    following = (
        f"<w:p><w:r><w:t>{following_text}</w:t></w:r></w:p>"
        if following_text is not None
        else ""
    )
    preceding_runs = "".join(
        f"<w:r><w:t>{item}</w:t></w:r>" for item in (text_runs or (text,))
    )
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body><w:p>{preceding_runs}</w:p>"
        f"<w:p><w:r><w:drawing>{drawing}</w:drawing></w:r></w:p>"
        f"{following}"
        "</w:body></w:document>"
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="media/image1.jpg"/>'
        "</Relationships>"
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
        package.writestr("word/_rels/document.xml.rels", relationships)
        package.writestr("word/media/image1.jpg", image_bytes)
    return output.getvalue()


def _word_with_repeated_image_flow(image_bytes: bytes) -> bytes:
    width_emu = 40 * 12_700
    drawing = (
        "<wp:inline>"
        f'<wp:extent cx="{width_emu}" cy="{width_emu}"/>'
        '<a:graphic><a:graphicData><a:blip r:embed="rId1"/>'
        "</a:graphicData></a:graphic></wp:inline>"
    )
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:body>"
        "<w:p><w:r><w:t>Before-223</w:t></w:r></w:p>"
        f"<w:p><w:r><w:drawing>{drawing}</w:drawing></w:r></w:p>"
        "<w:p><w:r><w:t>After-223</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Before-223</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>After-223</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="media/image1.jpg"/>'
        "</Relationships>"
    )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
        package.writestr("word/_rels/document.xml.rels", relationships)
        package.writestr("word/media/image1.jpg", image_bytes)
    return output.getvalue()


def _image_pdf(
    text: str,
    image_bytes: bytes,
    *,
    image_x: float,
    image_y: float = 600,
    text_y: float = 650,
    following_text: str | None = None,
    following_text_y: float = 600,
    image_width: float = 40,
    image_height: float = 40,
    image_after_text: bool = True,
    alpha: float = 1,
    matrix: tuple[float, float, float, float, float, float] | None = None,
    clip: tuple[float, float, float, float] | None = None,
    clip_commands: str | None = None,
    image_dictionary_extra: bytes = b"",
    leading_commands: bytes = b"",
    trailing_commands: bytes = b"",
    blend_mode: bytes | None = None,
) -> bytes:
    encoded = text.encode("ascii")
    transform = matrix or (image_width, 0, 0, image_height, image_x, image_y)
    if clip is not None and clip_commands is not None:
        raise ValueError("clip and clip_commands are mutually exclusive")
    clip_command = clip_commands or (
        ""
        if clip is None
        else f"{clip[0]:g} {clip[1]:g} {clip[2]:g} {clip[3]:g} re W n "
    )
    image_command = (
        f"q /GS0 gs {clip_command}"
        f"{' '.join(f'{value:g}' for value in transform)} cm /Im1 Do Q "
    ).encode("ascii")
    text_command = (
        f"BT /F1 10 Tf 1 0 0 1 50 {text_y:g} Tm (".encode("ascii")
        + encoded
        + b") Tj ET"
    )
    following_command = (
        b""
        if following_text is None
        else (
            f" BT /F1 10 Tf 1 0 0 1 50 {following_text_y:g} Tm (".encode(
                "ascii"
            )
            + following_text.encode("ascii")
            + b") Tj ET"
        )
    )
    stream = leading_commands + (
        text_command + b" " + image_command + following_command
        if image_after_text
        else image_command + text_command + following_command
    ) + trailing_commands
    objects = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Filter /DCTDecode "
        + image_dictionary_extra
        + b" /Length "
        + str(len(image_bytes)).encode("ascii")
        + b" >>\nstream\n"
        + image_bytes
        + b"\nendstream",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Page /Parent 5 0 R /MediaBox [0 0 595 842] /Resources "
        b"<< /Font << /F1 1 0 R >> /XObject << /Im1 2 0 R >> "
        + f"/ExtGState << /GS0 << /Type /ExtGState /ca {alpha:g} /CA {alpha:g} ".encode("ascii")
        + (b"" if blend_mode is None else b"/BM " + blend_mode + b" ")
        + b">> >> "
        + b">> /Contents 3 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [4 0 R] >>",
        b"<< /Type /Catalog /Pages 5 0 R >>",
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 7\n0000000000 65535 f \n")
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets))
    output.extend(f"trailer << /Size 7 /Root 6 0 R >>\nstartxref\n{xref}\n%%EOF".encode("ascii"))
    return bytes(output)


def _rgba_image_pdf(
    rgb: tuple[int, int, int],
    alpha: int,
    *,
    matte: tuple[float, float, float] | None = None,
) -> bytes:
    rgb_data = zlib.compress(bytes(rgb) * 64)
    alpha_data = zlib.compress(bytes((alpha,)) * 64)
    stream = (
        b"BT /F1 10 Tf 1 0 0 1 50 650 Tm (Synthetic) Tj ET "
        b"q 40 0 0 40 100 600 cm /Im1 Do Q"
    )
    objects = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Filter /FlateDecode "
        + (
            b""
            if matte is None
            else (
                "/Matte [" + " ".join(f"{value:g}" for value in matte) + "] "
            ).encode("ascii")
        )
        + b"/Length "
        + str(len(alpha_data)).encode("ascii")
        + b" >>\nstream\n"
        + alpha_data
        + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Filter /FlateDecode /SMask 2 0 R /Length "
        + str(len(rgb_data)).encode("ascii")
        + b" >>\nstream\n"
        + rgb_data
        + b"\nendstream",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Page /Parent 6 0 R /MediaBox [0 0 595 842] /Resources "
        b"<< /Font << /F1 1 0 R >> /XObject << /Im1 3 0 R >> >> /Contents 4 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [5 0 R] >>",
        b"<< /Type /Catalog /Pages 6 0 R >>",
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 8\n0000000000 65535 f \n")
    output.extend(
        b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets)
    )
    output.extend(
        f"trailer << /Size 8 /Root 7 0 R >>\nstartxref\n{xref}\n%%EOF".encode(
            "ascii"
        )
    )
    return bytes(output)


def binding() -> DeliveryBinding:
    return DeliveryBinding(
        workspace_id="workspace-1",
        source_snapshot_id="SOURCE-1", source_revision=1, source_digest=SHA_A,
        case_analysis_snapshot_id="CASE-1", case_analysis_revision=2, case_analysis_digest=SHA_A,
        planning_snapshot_id="PLAN-1", planning_revision=3, planning_digest=SHA_A,
        inspection_snapshot_id="INSPECTION-1", inspection_revision=4, inspection_digest=SHA_A,
        technical_snapshot_id="TECHNICAL-1", technical_revision=5, technical_digest=SHA_A,
        report_snapshot_id="REPORT-1", report_revision=6, report_digest=SHA_A,
        report_approval_id="REPORT-APPROVAL-1", report_approval_digest=SHA_A,
        professional_id="EXPERT-1",
    )


def artifact() -> DeliveryArtifact:
    return DeliveryArtifact(
        artifact_id="ARTIFACT-1", role=DeliveryRole.MAIN_REPORT,
        format=DeliveryFormat.DOCX, filename="laudo-r1.docx",
        content_id="11111111-1111-4111-8111-111111111111",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        byte_size=123, checksum_sha256=SHA_B,
    )


def snapshot(*, decisions: tuple[DeliveryDecision, ...] = (), artifacts: tuple[DeliveryArtifact, ...] = (), state: DeliveryState = DeliveryState.DRAFT) -> DeliverySnapshot:
    return DeliverySnapshot(
        schema_version="1.0.0", delivery_id="DELIVERY-1", revision=1,
        workspace_id="workspace-1", binding=binding(),
        template_id="TEMPLATE-1", template_content_id="22222222-2222-4222-8222-222222222222",
        template_format=DeliveryFormat.DOCX, template_revision=1, template_digest=SHA_A,
        rendering_version="delivery-renderer/1.2.0", artifacts=artifacts,
        package=DeliveryPackage(manifest_version="1.0.0", artifact_ids=tuple(item.artifact_id for item in artifacts)),
        decisions=decisions, state=state, stale_reasons=(), stale_origin_state=None, supersedes_delivery_id=None,
    )


def decision(action: DeliveryAction, *, index: int, previous: str | None) -> DeliveryDecision:
    return DeliveryDecision(
        decision_id=f"DECISION-{index}", action=action, professional_id="EXPERT-1",
        reason="Decisão profissional explícita.", timestamp=f"2026-08-31T12:0{index}:00+00:00",
        supersedes_decision_id=previous,
    )


def test_delivery_snapshot_round_trip_is_strict_and_exactly_bound() -> None:
    value = snapshot()
    assert delivery_snapshot_from_mapping(delivery_snapshot_to_mapping(value)) == value
    assert value.binding.planning_snapshot_id == "PLAN-1"
    payload = delivery_snapshot_to_mapping(value)
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="fields"):
        delivery_snapshot_from_mapping(payload)


def test_canonical_synthetic_fixture_matches_strict_schema() -> None:
    root = Path(__file__).parents[1]
    payload = json.loads((root / "tests/fixtures/delivery-snapshot-v1.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "schemas/delivery-snapshot-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)
    assert delivery_snapshot_to_mapping(delivery_snapshot_from_mapping(payload)) == payload


def test_lifecycle_requires_linear_explicit_professional_decisions() -> None:
    ready = decision(DeliveryAction.MARK_READY_FOR_REVIEW, index=1, previous=None)
    approved = decision(DeliveryAction.APPROVE, index=2, previous=ready.decision_id)
    finalized = decision(DeliveryAction.FINALIZE, index=3, previous=approved.decision_id)
    delivered = decision(DeliveryAction.DELIVER, index=4, previous=finalized.decision_id)
    value = snapshot(decisions=(ready, approved, finalized, delivered), artifacts=(artifact(),), state=DeliveryState.DELIVERED)
    assert value.state is DeliveryState.DELIVERED
    with pytest.raises(ValueError, match="transition"):
        snapshot(decisions=(delivered,), artifacts=(artifact(),), state=DeliveryState.DELIVERED)


def test_finalization_requires_hashed_main_artifact_and_exact_manifest() -> None:
    ready = decision(DeliveryAction.MARK_READY_FOR_REVIEW, index=1, previous=None)
    approved = decision(DeliveryAction.APPROVE, index=2, previous=ready.decision_id)
    finalized = decision(DeliveryAction.FINALIZE, index=3, previous=approved.decision_id)
    with pytest.raises(ValueError, match="artifact"):
        snapshot(decisions=(ready, approved, finalized), state=DeliveryState.FINALIZED)
    with pytest.raises(ValueError, match="manifest"):
        replace(
            snapshot(decisions=(ready, approved, finalized), artifacts=(artifact(),), state=DeliveryState.FINALIZED),
            package=DeliveryPackage("1.0.0", ()),
        )


def test_review_cannot_approve_metadata_without_rendered_bytes() -> None:
    ready = decision(DeliveryAction.MARK_READY_FOR_REVIEW, index=1, previous=None)
    with pytest.raises(ValueError, match="rendered main artifact"):
        snapshot(decisions=(ready,), state=DeliveryState.READY_FOR_REVIEW)


def test_reviewable_delivery_rejects_pdf_as_the_professional_main_artifact() -> None:
    ready = decision(DeliveryAction.MARK_READY_FOR_REVIEW, index=1, previous=None)
    pdf = replace(
        artifact(), format=DeliveryFormat.PDF, filename="laudo-r1.pdf", media_type="application/pdf",
    )
    with pytest.raises(ValueError, match="Word main artifact"):
        snapshot(decisions=(ready,), artifacts=(pdf,), state=DeliveryState.READY_FOR_REVIEW)


def test_stale_overrides_final_state_and_cannot_be_silently_cleared() -> None:
    value = replace(snapshot(), state=DeliveryState.STALE, stale_reasons=("REPORT_DIGEST_CHANGED",), stale_origin_state=DeliveryState.DRAFT)
    assert value.state is DeliveryState.STALE
    with pytest.raises(ValueError, match="stale"):
        replace(value, state=DeliveryState.DRAFT)


def test_unavailable_current_authority_reopens_as_stale_instead_of_hiding_delivery() -> None:
    delivered = snapshot(
        decisions=(
            decision(DeliveryAction.MARK_READY_FOR_REVIEW, index=1, previous=None),
            decision(DeliveryAction.APPROVE, index=2, previous="DECISION-1"),
            decision(DeliveryAction.FINALIZE, index=3, previous="DECISION-2"),
            decision(DeliveryAction.DELIVER, index=4, previous="DECISION-3"),
        ), artifacts=(artifact(),), state=DeliveryState.DELIVERED,
    )
    stale = mark_delivery_authority_unavailable(delivered)
    assert stale.state is DeliveryState.STALE
    assert stale.stale_origin_state is DeliveryState.DELIVERED
    assert stale.stale_reasons == ("UPSTREAM_AUTHORITY_UNAVAILABLE",)


def test_changed_pathology_authority_propagates_through_report_to_delivery_stale() -> None:
    current = snapshot()
    stored = SimpleNamespace(
        revision=7,
        payload=freeze_json_payload(delivery_snapshot_to_mapping(current)),
    )
    inert = SimpleNamespace(execute=lambda _workspace: (None, None))
    changed_report = SimpleNamespace(
        execute=lambda _workspace: (_ for _ in ()).throw(
            ValueError("report pathology snapshot revision changed")
        )
    )
    service = GetDeliverySnapshot(
        SimpleNamespace(execute=lambda *_args: stored),
        inert,
        inert,
        inert,
        inert,
        changed_report,
    )

    _, reopened = service.execute(current.workspace_id)

    assert reopened.state is DeliveryState.STALE
    assert reopened.stale_reasons == ("UPSTREAM_AUTHORITY_UNAVAILABLE",)


def test_artifact_filename_and_content_identity_are_unique() -> None:
    duplicate = replace(artifact(), artifact_id="ARTIFACT-2")
    with pytest.raises(ValueError, match="unique"):
        snapshot(artifacts=(artifact(), duplicate))


def test_application_binding_consumes_current_approved_authorities_and_reconciles_change() -> None:
    root = Path(__file__).parents[1] / "tests/fixtures"
    def load(name: str) -> dict:
        return json.loads((root / name).read_text(encoding="utf-8"))

    def record(revision: int) -> SimpleNamespace:
        return SimpleNamespace(revision=revision)

    report = report_snapshot_from_mapping(load("report-snapshot-v1.json"))
    case = replace(
        case_analysis_from_mapping(load("case-analysis-snapshot-v1.json")),
        snapshot_id=report.source_snapshot.case_analysis_snapshot_id,
        workspace_id=report.workspace_id,
        judicial_context_workspace_id=report.workspace_id,
    )
    planning = replace(pericial_planning_from_mapping(load("pericial-planning-snapshot-v1.json")), workspace_id=report.workspace_id)
    inspection = replace(inspection_session_from_mapping(load("inspection-session-v1.json")), workspace_id=report.workspace_id)
    technical = replace(technical_snapshot_from_mapping(load("technical-snapshot-v1.json")), workspace_id=report.workspace_id)
    current = build_delivery_binding(
        workspace_id=report.workspace_id,
        case_record=record(report.source_snapshot.case_analysis_revision), case=case,
        planning_record=record(3), planning=planning,
        inspection_record=record(report.source_snapshot.inspection_session_revision), inspection=inspection,
        technical_record=record(report.source_snapshot.technical_snapshot_revision), technical=technical,
        report_record=record(6), report=report,
    )
    bound = replace(snapshot(), workspace_id=report.workspace_id, binding=current)
    assert reconcile_delivery(bound, current) == bound
    changed = replace(current, report_digest=SHA_B)
    stale = reconcile_delivery(bound, changed)
    assert stale.state is DeliveryState.STALE
    assert stale.stale_reasons == ("REPORT_DIGEST_CHANGED",)


def test_delivery_review_rejects_professional_identity_outside_bound_authority() -> None:
    class Getter:
        def execute(self, _workspace_id):
            return SimpleNamespace(revision=1), snapshot()

    service = ReviewDeliverySnapshot(Getter(), object(), object(), object())
    with pytest.raises(ValueError, match="professional authority"):
        service.execute(
            "workspace-1", action="MARK_READY_FOR_REVIEW", professional_id="OTHER-EXPERT",
            reason="Tentativa inválida.", expected_revision=1,
        )


def test_final_word_reopens_while_diagnostic_pdf_remains_non_delivery() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
        package.writestr("word/vbaProject.bin", b"synthetic macro")
    word = output.getvalue()
    digest, size, media = validate_final_artifact(word, "DOCM")
    assert media == "application/vnd.ms-word.document.macroEnabled.12"
    verify_reopened_artifact(content=word, output_format="DOCM", expected_size=size, expected_sha256=digest)
    report = report_snapshot_from_mapping(json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8")))
    pdf = render_pdf_candidate(report)
    pdf_digest, pdf_size, pdf_media = validate_final_artifact(pdf, "PDF")
    assert pdf_media == "application/pdf"
    with pytest.raises(ValueError, match="diagnostic PDF cannot be a Delivery artifact"):
        verify_reopened_artifact(content=pdf, output_format="PDF", expected_size=pdf_size, expected_sha256=pdf_digest)
    with pytest.raises(ValueError, match="diagnostic PDF cannot be a Delivery artifact"):
        verify_reopened_artifact(content=pdf, output_format="PDF", expected_size=pdf_size, expected_sha256=SHA_A)


def test_artifact_validation_rejects_macro_identity_change_and_malformed_pdf() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", "<document/>")
    with pytest.raises(ValueError, match="macro identity"):
        validate_final_artifact(output.getvalue(), "DOCM")
    with pytest.raises(ValueError, match="PDF"):
        validate_final_artifact(b"%PDF-1.7\nno page or eof", "PDF")
    with pytest.raises(ValueError, match="PDF"):
        validate_final_artifact(b"%PDF-1.7\n1 0 obj <</Type /Page>> endobj\n%%EOF", "PDF")


def test_supporting_image_bytes_are_verified_by_declared_media_type() -> None:
    def image_bytes(kind: str) -> bytes:
        output = BytesIO()
        Image.new("RGB", (2, 2), "white").save(output, format=kind)
        return output.getvalue()

    jpeg = image_bytes("JPEG")
    png = image_bytes("PNG")
    assert validate_supporting_artifact(jpeg, "image/jpeg")[2] == "image/jpeg"
    assert validate_supporting_artifact(png, "image/png")[2] == "image/png"
    with pytest.raises(ValueError, match="JPEG"):
        validate_supporting_artifact(png, "image/jpeg")
    with pytest.raises(ValueError, match="unsupported"):
        validate_supporting_artifact(b"opaque", "application/octet-stream")
    with pytest.raises(ValueError, match="PNG"):
        validate_supporting_artifact(b"\x89PNG\r\n\x1a\n", "image/png")
    with pytest.raises(ValueError, match="JPEG"):
        validate_supporting_artifact(b"\xff\xd8\xff\xff\xd9", "image/jpeg")


def test_conversion_copy_strips_macros_and_external_relationships_are_rejected() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/><Override PartName="/word/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
        package.writestr("word/document.xml", "<document/>")
        package.writestr("word/vbaProject.bin", b"macro")
        package.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="template" Target="https://example.invalid/private" TargetMode="External"/></Relationships>')
    with pytest.raises(ValueError, match="external relationships"):
        validate_final_artifact(output.getvalue(), "DOCM")
    clean = BytesIO()
    with ZipFile(clean, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/><Override PartName="/word/vbaProject.bin" ContentType="application/vnd.ms-office.vbaProject"/></Types>')
        package.writestr("word/document.xml", "<document/>")
        package.writestr("word/vbaProject.bin", b"macro")
    converted, kind = safe_pdf_conversion_copy(clean.getvalue(), "DOCM")
    assert kind == "DOCX"
    with ZipFile(BytesIO(converted)) as package:
        assert "word/vbaProject.bin" not in package.namelist()


def test_rendered_word_bytes_contain_and_change_with_entire_approved_report_body() -> None:
    root = Path(__file__).parents[1] / "tests/fixtures"
    report = report_snapshot_from_mapping(json.loads((root / "report-snapshot-v1.json").read_text(encoding="utf-8")))
    document = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>[[EXPERT_FULL_NAME]]</w:t></w:r></w:p><w:p><w:r><w:t>[[EXPERT_REGISTRATION]]</w:t></w:r></w:p><w:p><w:r><w:t>[[REPORT_ID]]</w:t></w:r></w:p>
      <w:sdt><w:sdtPr><w:tag w:val="CANONICAL_REPORT"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>empty</w:t></w:r></w:p></w:sdtContent></w:sdt>
      <w:p><w:bookmarkStart w:id="1" w:name="B"/><w:r><w:instrText>TOC</w:instrText><w:instrText>PAGE</w:instrText><w:instrText>NUMPAGES</w:instrText><w:instrText>SEQ Figure</w:instrText><w:instrText>REF B</w:instrText><w:instrText>PAGEREF B</w:instrText></w:r><w:bookmarkEnd w:id="1"/></w:p>
    </w:body></w:document>'''
    package_bytes = BytesIO()
    with ZipFile(package_bytes, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", document)
        package.writestr("word/styles.xml", "<styles/>")
        package.writestr("word/numbering.xml", "<numbering/>")
        package.writestr("word/vbaProject.bin", b"macro")
        package.writestr("docProps/custom.xml", '<Properties><property name="TEMPLATE_ID"><value>TEMPLATE-1</value></property></Properties>')
    manifest = template_binding_manifest_from_mapping({"schema_version": "1.0.0", "template_id": "TEMPLATE-1", "output_kind": "DOCM", "bindings": [{"field": "EXPERT_FULL_NAME", "placeholder": "[[EXPERT_FULL_NAME]]"}, {"field": "EXPERT_REGISTRATION", "placeholder": "[[EXPERT_REGISTRATION]]"}, {"field": "REPORT_ID", "placeholder": "[[REPORT_ID]]"}]})
    first = render_word_candidate(template_bytes=package_bytes.getvalue(), report=report, manifest=manifest).output_bytes
    changed = replace(report, claims=(replace(report.claims[0], text="Texto material deliberadamente alterado."), *report.claims[1:]))
    second = render_word_candidate(template_bytes=package_bytes.getvalue(), report=changed, manifest=manifest).output_bytes
    with ZipFile(BytesIO(first)) as package:
        rendered = package.read("word/document.xml").decode("utf-8")
    assert report.claims[0].text in rendered
    assert report.answers[0].text in rendered
    assert "REPORT_SNAPSHOT_SHA256" in rendered
    assert first != second


@pytest.mark.parametrize(
    ("instruction", "part", "representation"),
    (
        ('INCLUDETEXT "https://example.invalid/private"', "document", "complex"),
        ('includepicture "https://example.invalid/private.png"', "document", "complex"),
        ('DDEAUTO cmd "test"', "document", "complex"),
        ('DDE cmd "test"', "document", "complex"),
        ('INCLUDETEXT "https://example.invalid/header"', "header", "complex"),
        ('INCLUDETEXT "https://example.invalid/simple"', "document", "simple"),
    ),
)
def test_active_external_or_execution_word_fields_are_rejected_before_binding(instruction: str, part: str, representation: str) -> None:
    root = Path(__file__).parents[1] / "tests/fixtures"
    report = report_snapshot_from_mapping(json.loads((root / "report-snapshot-v1.json").read_text(encoding="utf-8")))
    split = len(instruction) // 2
    active_field = (
        f'<w:p><w:fldSimple w:instr="{instruction.replace(chr(34), "&quot;")}"/></w:p>'
        if representation == "simple"
        else f"<w:p><w:r><w:instrText>{instruction[:split]}</w:instrText><w:instrText>{instruction[split:]}</w:instrText></w:r></w:p>"
    )
    document = f'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>[[EXPERT_FULL_NAME]]</w:t><w:t>[[EXPERT_REGISTRATION]]</w:t><w:t>[[REPORT_ID]]</w:t></w:r></w:p>
      <w:sdt><w:sdtPr><w:tag w:val="CANONICAL_REPORT"/></w:sdtPr><w:sdtContent/></w:sdt>
      <w:p><w:bookmarkStart w:id="1" w:name="B"/><w:r><w:instrText>TOC</w:instrText><w:instrText>PAGE</w:instrText><w:instrText>NUMPAGES</w:instrText><w:instrText>SEQ Figure</w:instrText><w:instrText>REF B</w:instrText><w:instrText>PAGEREF B</w:instrText></w:r></w:p>
      {active_field if part == "document" else ""}
    </w:body></w:document>'''
    package_bytes = BytesIO()
    with ZipFile(package_bytes, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("word/document.xml", document)
        package.writestr("word/styles.xml", "<styles/>")
        package.writestr("word/numbering.xml", "<numbering/>")
        if part == "header":
            package.writestr("word/header1.xml", f'<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{active_field}</w:hdr>')
        package.writestr("docProps/custom.xml", '<Properties><property name="TEMPLATE_ID"><value>TEMPLATE-1</value></property></Properties>')
    manifest = template_binding_manifest_from_mapping({"schema_version": "1.0.0", "template_id": "TEMPLATE-1", "output_kind": "DOCX", "bindings": [{"field": "EXPERT_FULL_NAME", "placeholder": "[[EXPERT_FULL_NAME]]"}, {"field": "EXPERT_REGISTRATION", "placeholder": "[[EXPERT_REGISTRATION]]"}, {"field": "REPORT_ID", "placeholder": "[[REPORT_ID]]"}]})
    with pytest.raises(ValueError, match="unsupported active Word field"):
        render_word_candidate(template_bytes=package_bytes.getvalue(), report=report, manifest=manifest)


def test_rendered_pdf_contains_same_canonical_report_digest_and_changes_with_report() -> None:
    root = Path(__file__).parents[1] / "tests/fixtures"
    report = report_snapshot_from_mapping(json.loads((root / "report-snapshot-v1.json").read_text(encoding="utf-8")))
    first = render_pdf_candidate(report)
    validate_final_artifact(first, "PDF")
    mapping = report_snapshot_to_mapping(report)
    digest = __import__("hashlib").sha256(json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert digest.encode("ascii") in first
    assert render_pdf_candidate(replace(report, report_id=f"{report.report_id}-REV")) != first


def test_pdf_renderer_wraps_long_lines_and_rejects_lossy_unicode() -> None:
    root = Path(__file__).parents[1] / "tests/fixtures"
    report = report_snapshot_from_mapping(json.loads((root / "report-snapshot-v1.json").read_text(encoding="utf-8")))
    long_text = "Trecho " + "muito longo " * 80 + "MARCADOR-FINAL"
    wrapped = render_pdf_candidate(replace(report, claims=(replace(report.claims[0], text=long_text), *report.claims[1:])))
    assert b"MARCADOR-FINAL" in wrapped
    assert wrapped.count(b") Tj T*") > len(report.claims)
    widest = render_pdf_candidate(replace(report, claims=(replace(report.claims[0], text="W" * 176), *report.claims[1:])))
    assert b"W" * 56 in widest
    assert b"W" * 57 not in widest
    with pytest.raises(ValueError, match="unsupported"):
        render_pdf_candidate(replace(report, claims=(replace(report.claims[0], text="Hipotese tecnica \u0394"), *report.claims[1:])))


def test_final_pdf_is_converted_from_the_exact_bound_word_bytes() -> None:
    report = report_snapshot_from_mapping(json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8")))
    word = BytesIO()
    document = f"""<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>{report.report_id}</w:t></w:r></w:p>
    </w:body></w:document>"""
    with ZipFile(word, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("word/document.xml", document)

    class Converter:
        def __init__(self) -> None:
            self.received = None

        def convert(self, content: bytes, source_format: str) -> bytes:
            self.received = (content, source_format)
            return _parseable_text_pdf(report.report_id)

    converter = Converter()
    pdf = delivery_renderer.render_final_pdf_candidate(
        word_content=word.getvalue(), word_format="DOCX", converter=converter,
    )

    assert converter.received == (word.getvalue(), "DOCX")
    assert pdf.startswith(b"%PDF-")

    unrelated = replace(report, report_id="RELATORIO-ERRADO")

    class WrongConverter:
        def convert(self, _content: bytes, _source_format: str) -> bytes:
            return _parseable_text_pdf(unrelated.report_id)

    with pytest.raises(ValueError, match="does not faithfully represent"):
        delivery_renderer.render_final_pdf_candidate(
            word_content=word.getvalue(), word_format="DOCX", converter=WrongConverter(),
        )

    class AdditiveForgeryConverter:
        def convert(self, _content: bytes, _source_format: str) -> bytes:
            return _parseable_text_pdf(f"{report.report_id} {report.report_id}")

    with pytest.raises(ValueError, match="does not faithfully represent"):
        delivery_renderer.render_final_pdf_candidate(
            word_content=word.getvalue(), word_format="DOCX", converter=AdditiveForgeryConverter(),
        )


def test_final_pdf_rejects_a_table_flattened_into_unrelated_lines() -> None:
    word = BytesIO()
    document = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
    </w:body></w:document>'''
    with ZipFile(word, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("word/document.xml", document)

    class FlatteningConverter:
        def convert(self, _content: bytes, _source_format: str) -> bytes:
            return _parseable_text_pdf("Cell A Cell B")

    with pytest.raises(ValueError, match="does not faithfully represent"):
        delivery_renderer.render_final_pdf_candidate(
            word_content=word.getvalue(), word_format="DOCX", converter=FlatteningConverter(),
        )


def test_fidelity_includes_authoritative_strict_namespace_header_text() -> None:
    word = _word_with_strict_header("Body-223", "Header-223")

    delivery_renderer._validate_pdf_fidelity(
        word,
        _parseable_text_pdf("Header-223\nBody-223"),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _parseable_text_pdf("Body-223"),
        )


@pytest.mark.parametrize(
    "first_cell_fragments",
    (
        ("Cell-A-223",),
        ("Cell-A-", "223"),
        ("Cell", "-", "A", "-", "223"),
        ("Cell", " ", "A", "-", "223"),
    ),
)
def test_fidelity_accepts_bounded_visible_table_cell_fragmentation(
    first_cell_fragments: tuple[str, ...],
) -> None:
    source_cell = "Cell A-223" if " " in first_cell_fragments else "Cell-A-223"
    x = 50.0
    positioned = []
    for fragment in first_cell_fragments:
        positioned.append((fragment, x, 700.0, 10.0, 0))
        x += max(len(fragment), 1) * 5.5
    positioned.append(("Cell-B-223", 250.0, 701.5, 10.0, 0))

    delivery_renderer._validate_pdf_fidelity(
        _word_table((source_cell, "Cell-B-223")),
        _positioned_text_pdf([positioned]),
    )


@pytest.mark.parametrize(
    "pages",
    (
        [[("Cell", 50, 700, 10, 0), ("-A-223", 80, 680, 10, 0), ("Cell-B-223", 250, 700, 10, 0)]],
        [[("Cell", 50, 700, 10, 0), ("-A-223", 180, 700, 10, 0), ("Cell-B-223", 250, 700, 10, 0)]],
        [[("Cell-A-223", 250, 700, 10, 0), ("Cell-B-223", 50, 700, 10, 0)]],
        [[("Cell-A-223", -40, 700, 10, 0), ("Cell-B-223", 250, 700, 10, 0)]],
        [[("Cell-A-223", 50, 700, 10, 3), ("Cell-B-223", 250, 700, 10, 0)]],
        [[("Cell-A-223", 50, 700, 0.1, 0), ("Cell-B-223", 250, 700, 10, 0)]],
    ),
    ids=("cross-line", "disconnected", "inverted", "out-of-bounds", "hidden", "near-zero"),
)
def test_fidelity_rejects_spatial_or_invisible_table_token_injection(
    pages: list[list[tuple[str, float, float, float, int]]],
) -> None:
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table(("Cell-A-223", "Cell-B-223")),
            _positioned_text_pdf(pages),
        )


def test_fidelity_never_composes_one_table_cell_across_pages() -> None:
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table(("Cell-A-223", "Cell-B-223")),
            _positioned_text_pdf(
                [
                    [("Cell", 50, 700, 10, 0)],
                    [("-A-223", 80, 700, 10, 0), ("Cell-B-223", 250, 700, 10, 0)],
                ]
            ),
        )


@pytest.mark.parametrize(
    ("stream", "resources"),
    (
        (
            b"BT /F1 10 Tf 1 0 0 1 50 700 Tm (Cell-A-223) Tj ET "
            b"q 1 1 1 rg 0 650 595 100 re f Q",
            b"",
        ),
        (
            b"BT /F1 10 Tf 0 0 0 1 50 700 Tm (Cell-A-223) Tj ET",
            b"",
        ),
        (
            b"BT /F1 10 Tf 0.2 0 0 1 50 700 Tm (Cell-A-223) Tj ET",
            b"",
        ),
        (
            b"BT /F1 10 Tf 1 0 0 1 50 700 Tm (Cell-A-223) Tj ET "
            b"q 1 1 1 rg 55 650 540 100 re f Q",
            b"",
        ),
        (
            b"BT /F1 10 Tf 1 0 0 1 50 700 Tm (Cell-A-223) Tj ET "
            b"q 1 1 1 rg 90 650 505 100 re f Q",
            b"",
        ),
        (
            b"BT /F1 10 Tf 1 0 0 1 590 700 Tm (Cell-A-223) Tj ET",
            b"",
        ),
        (
            b"q /GS0 gs BT /F1 10 Tf 1 0 0 1 50 700 Tm (Cell-A-223) Tj ET Q",
            b"/ExtGState << /GS0 << /Type /ExtGState /ca 0 /CA 0 >> >>",
        ),
        (
            b"q /GS0 gs BT /F1 10 Tf 1 0 0 1 50 700 Tm (Cell-A-223) Tj ET Q",
            b"/ExtGState << /GS0 << /Type /ExtGState /ca 0.05 /CA 0.05 >> >>",
        ),
        (
            b"BT /F1 10 Tf 1 0 0 1 50 700 Tm (Cell-A-223) Tj ET "
            b"q /GS0 gs 1 1 1 rg 0 650 595 100 re f Q",
            b"/ExtGState << /GS0 << /Type /ExtGState /ca 0.95 /CA 0.95 >> >>",
        ),
    ),
    ids=(
        "opaque-overpaint",
        "zero-width",
        "near-zero-width",
        "hidden-strip",
        "hidden-tail",
        "partial-off-page",
        "zero-alpha",
        "low-alpha",
        "near-opaque-overpaint",
    ),
)
def test_fidelity_rejects_nonvisible_or_cross_region_table_fragments(
    stream: bytes, resources: bytes
) -> None:
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_text("Cell-A-223"),
            _custom_content_pdf(stream, extra_resources=resources),
        )


def test_fidelity_never_composes_fragments_across_a_visible_cell_rule() -> None:
    stream = (
        b"BT\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 50 700 Tm () Tj (Cell-) Tj\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 82 700 Tm () Tj (A-223) Tj\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 250 700 Tm () Tj (Cell-B-223) Tj\n"
        b"ET\n0 0 0 RG 1 w 80 650 m 80 750 l S"
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table(("Cell-A-223", "Cell-B-223")),
            _custom_content_pdf(stream),
        )


def test_fidelity_never_composes_fragments_across_a_wide_filled_cell_rule() -> None:
    stream = (
        b"BT\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 50 700 Tm (Cell-) Tj\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 84 700 Tm (A-223) Tj\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 250 700 Tm (Cell-B-223) Tj\n"
        b"ET\n0 0 0 rg 80 650 4 100 re f"
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table(("Cell-A-223", "Cell-B-223")),
            _custom_content_pdf(stream),
        )


def test_fidelity_never_composes_fragments_across_any_path_contained_in_gap() -> None:
    stream = (
        b"BT\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 50 700 Tm (Cell-) Tj\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 98 700 Tm (A-223) Tj\n"
        b"/F1 10 Tf 0 Tr 1 0 0 1 250 700 Tm (Cell-B-223) Tj\n"
        b"ET\n0 0 0 rg 72 650 26 100 re f"
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table(("Cell-A-223", "Cell-B-223")),
            _custom_content_pdf(stream),
        )


@pytest.mark.parametrize(
    "clip_rectangle",
    (
        b"50 700 100 1.5",
        b"50 704 100 4",
        b"50 690 1.5 30",
        b"50 690 25 30",
    ),
    ids=(
        "thin-horizontal-band",
        "four-point-horizontal-band",
        "thin-vertical-band",
        "partial-vertical-band",
    ),
)
def test_fidelity_rejects_text_materially_removed_by_an_active_clip(
    clip_rectangle: bytes,
) -> None:
    stream = (
        b"q "
        + clip_rectangle
        + b" re W n BT /F1 10 Tf 1 0 0 1 50 700 Tm (Synthetic) Tj ET Q"
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_text("Synthetic"),
            _custom_content_pdf(stream),
        )


@pytest.mark.parametrize("font_size", (4, 48, 72, 120))
def test_fidelity_rejects_text_scale_not_bound_to_word_source(
    font_size: float,
) -> None:
    stream = (
        f"BT /F1 {font_size:g} Tf 1 0 0 1 50 650 Tm (Synthetic) Tj ET"
    ).encode("ascii")
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_text("Synthetic"),
            _custom_content_pdf(stream),
        )


@pytest.mark.parametrize("character_style", (False, True))
def test_fidelity_applies_default_paragraph_style_font_size(
    character_style: bool,
) -> None:
    word = _word_with_default_paragraph_style(
        "Default-Style-223", 96, character_style=character_style
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _custom_content_pdf(
                b"BT /F1 11 Tf 1 0 0 1 50 650 Tm (Default-Style-223) Tj ET"
            ),
        )
    delivery_renderer._validate_pdf_fidelity(
        word,
        _custom_content_pdf(
            b"BT /F1 48 Tf 1 0 0 1 50 650 Tm (Default-Style-223) Tj ET"
        ),
    )


def test_fidelity_rejects_ambiguous_local_name_style_attributes() -> None:
    word = _word_with_default_paragraph_style(
        "Default-Style-223", 96, ambiguous_default=True
    )

    with pytest.raises(ValueError, match="fidelity cannot be verified"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _custom_content_pdf(
                b"BT /F1 11 Tf 1 0 0 1 50 650 Tm (Default-Style-223) Tj ET"
            ),
        )


def test_fidelity_rejects_anisotropic_text_scale_as_font_size_equivalence() -> None:
    word = _word_with_default_paragraph_style("Default-Style-223", 96)
    stretched = _custom_content_pdf(
        b"BT /F1 11 Tf 1 0 0 4.36 50 600 Tm (Default-Style-223) Tj ET"
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, stretched)


def test_fidelity_binds_authoritative_word_text_color() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:rPr><w:sz w:val="20"/>'
            '<w:color w:val="FF0000"/></w:rPr><w:t>Synthetic</w:t>'
            "</w:r></w:p></w:body></w:document>",
        )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            output.getvalue(),
            _positioned_text_pdf([[("Synthetic", 50, 700, 10, 0)]]),
        )


def test_fidelity_rejects_non_normal_text_blend_mode() -> None:
    pdf = _custom_content_pdf(
        b"/GS1 gs BT /F1 11 Tf 1 0 0 1 50 650 Tm (Synthetic) Tj ET",
        extra_resources=(
            b"/ExtGState << /GS1 << /Type /ExtGState /BM /Difference >> >>"
        ),
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(_word_text("Synthetic"), pdf)


def test_fidelity_binds_body_paragraphs_to_visual_reading_order() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>First</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>Second</w:t></w:r></w:p></w:body></w:document>",
        )
    word = output.getvalue()
    delivery_renderer._validate_pdf_fidelity(
        word,
        _positioned_text_pdf(
            [[("First", 50, 700, 11, 0), ("Second", 50, 650, 11, 0)]]
        ),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _positioned_text_pdf(
                [[("First", 50, 500, 11, 0), ("Second", 50, 700, 11, 0)]]
            ),
        )


@pytest.mark.parametrize(
    ("parts", "stream"),
    (
        (
            (("Syn", None), ("thetic", None)),
            b"BT /F1 11 Tf 1 0 0 1 50 650 Tm (Synthetic) Tj ET",
        ),
        (
            (("Syn", 22), ("thetic", 24)),
            b"BT /F1 11 Tf 1 0 0 1 50 650 Tm (Syn) Tj /F1 12 Tf (thetic) Tj ET",
        ),
    ),
    ids=("same-size", "mixed-size"),
)
def test_fidelity_preserves_contiguous_text_across_word_runs(
    parts: tuple[tuple[str, int | None], ...], stream: bytes
) -> None:
    delivery_renderer._validate_pdf_fidelity(
        _word_runs(parts),
        _custom_content_pdf(stream),
    )


def test_fidelity_binds_table_rows_to_document_vertical_order() -> None:
    word = _word_table_rows(
        (("Row-1-A", "Row-1-B"), ("Row-2-A", "Row-2-B"))
    )
    delivery_renderer._validate_pdf_fidelity(
        word,
        _positioned_text_pdf(
            [[
                ("Row-1-A", 50, 700, 10, 0),
                ("Row-1-B", 250, 700, 10, 0),
                ("Row-2-A", 50, 600, 10, 0),
                ("Row-2-B", 250, 600, 10, 0),
            ]]
        ),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _positioned_text_pdf(
                [[
                    ("Row-1-A", 50, 600, 10, 0),
                    ("Row-1-B", 250, 600, 10, 0),
                    ("Row-2-A", 50, 700, 10, 0),
                    ("Row-2-B", 250, 700, 10, 0),
                ]]
            ),
        )


@pytest.mark.parametrize(
    "matrix",
    ("0 1 -1 0", "-1 0 0 1", "1 0.8 0 1", "-1 0 0 -1"),
    ids=("rotated", "mirrored", "skewed", "upside-down"),
)
def test_fidelity_rejects_unbound_affine_text_orientation(matrix: str) -> None:
    stream = f"BT /F1 10 Tf {matrix} 100 700 Tm (Cell-A-223) Tj ET".encode(
        "ascii"
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_text("Cell-A-223"),
            _custom_content_pdf(stream),
        )


@pytest.mark.parametrize("font_size", (1, 0.6, 0.25))
def test_fidelity_rejects_near_invisible_text_size(font_size: float) -> None:
    stream = (
        f"BT /F1 {font_size:g} Tf 1 0 0 1 100 700 Tm (Cell-A-223) Tj ET"
    ).encode("ascii")
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_text("Cell-A-223"),
            _custom_content_pdf(stream),
        )


def test_fidelity_rejects_matching_image_rendered_outside_the_page() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    delivery_renderer._validate_pdf_fidelity(
        word,
        _image_pdf("Synthetic", image.getvalue(), image_x=100),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", image.getvalue(), image_x=700),
        )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=45,
                image_y=640,
                image_width=100,
                image_height=30,
                image_after_text=True,
            ),
        )


@pytest.mark.parametrize(
    ("image_width", "image_height"),
    ((0.6, 0.6), (1, 1), (40, 0.6), (400, 100)),
    ids=("sub-point", "one-point", "flattened", "distorted"),
)
def test_fidelity_rejects_image_geometry_not_bound_to_word_layout(
    image_width: float, image_height: float
) -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=100,
                image_width=image_width,
                image_height=image_height,
            ),
        )


def test_fidelity_binds_image_to_declared_word_extent_not_intrinsic_ratio() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text(
        "Synthetic",
        image.getvalue(),
        image_width=40,
        image_height=20,
    )

    delivery_renderer._validate_pdf_fidelity(
        word,
        _image_pdf(
            "Synthetic",
            image.getvalue(),
            image_x=100,
            image_width=40,
            image_height=20,
        ),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=100,
                image_width=40,
                image_height=40,
            ),
        )


@pytest.mark.parametrize(
    "pdf",
    (
        {"alpha": 0},
        {"matrix": (0, 40, -40, 0, 140, 700)},
        {"matrix": (-40, 0, 0, 40, 140, 700)},
        {"clip": (100, 700, 20, 40)},
        {"image_x": 500},
        {"image_after_text": False},
    ),
    ids=("transparent", "rotated", "mirrored", "cropped", "relocated", "reordered"),
)
def test_fidelity_rejects_unbound_image_presentation(pdf: dict[str, object]) -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())
    options: dict[str, object] = {"image_x": 100}
    options.update(pdf)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", image.getvalue(), **options),
        )


@pytest.mark.parametrize(
    "clip_commands",
    (
        "100 700 20 40 re W n 100 700 40 40 re W n ",
        "110 710 20 20 re 100 700 40 40 re W* n ",
    ),
    ids=("cumulative-intersection", "even-odd-hole"),
)
def test_fidelity_rejects_images_materially_removed_by_composed_clips(
    clip_commands: str,
) -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=100,
                clip_commands=clip_commands,
            ),
        )


def test_fidelity_composes_ctm_before_evaluating_image_clip() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())
    pdf = _image_pdf(
        "Synthetic",
        image.getvalue(),
        image_x=100,
        matrix=(1, 0, 0, 1, 0, 0),
        clip_commands="40 0 0 40 100 600 cm 0 0 0.6 1 re W n ",
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, pdf)


def _transparent_smask_image_pdf(image_bytes: bytes) -> bytes:
    stream = (
        b"BT /F1 10 Tf 1 0 0 1 50 650 Tm (Synthetic) Tj ET "
        b"q /GS0 gs 40 0 0 40 100 700 cm /Im1 Do Q"
    )
    transparent_mask = bytes(64)
    objects = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceGray "
        b"/BitsPerComponent 8 /Length 64 >>\nstream\n"
        + transparent_mask
        + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Filter /DCTDecode /SMask 2 0 R /Length "
        + str(len(image_bytes)).encode("ascii")
        + b" >>\nstream\n"
        + image_bytes
        + b"\nendstream",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
        b"<< /Type /Page /Parent 6 0 R /MediaBox [0 0 595 842] /Resources "
        b"<< /Font << /F1 1 0 R >> /XObject << /Im1 3 0 R >> "
        b"/ExtGState << /GS0 << /Type /ExtGState /ca 1 /CA 1 >> >> >> /Contents 4 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [5 0 R] >>",
        b"<< /Type /Catalog /Pages 6 0 R >>",
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 8\n0000000000 65535 f \n")
    output.extend(
        b"".join(
            f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets
        )
    )
    output.extend(
        f"trailer << /Size 8 /Root 7 0 R >>\nstartxref\n{xref}\n%%EOF".encode(
            "ascii"
        )
    )
    return bytes(output)


def _extgstate_softmask_image_pdf(image_bytes: bytes) -> bytes:
    mask_stream = b"0 g 0 0 1 1 re f"
    page_stream = (
        b"BT /F1 10 Tf 1 0 0 1 50 650 Tm (Synthetic) Tj ET "
        b"q /GS0 gs 40 0 0 40 100 600 cm /Im1 Do Q"
    )
    objects = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /XObject /Subtype /Form /FormType 1 /BBox [0 0 1 1] "
        b"/Group << /S /Transparency /CS /DeviceGray /I true >> /Resources << >> /Length "
        + str(len(mask_stream)).encode("ascii")
        + b" >>\nstream\n"
        + mask_stream
        + b"\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Filter /DCTDecode /Length "
        + str(len(image_bytes)).encode("ascii")
        + b" >>\nstream\n"
        + image_bytes
        + b"\nendstream",
        b"<< /Type /ExtGState /SMask << /S /Luminosity /G 2 0 R /BC [0] >> >>",
        b"<< /Length "
        + str(len(page_stream)).encode("ascii")
        + b" >>\nstream\n"
        + page_stream
        + b"\nendstream",
        b"<< /Type /Page /Parent 7 0 R /MediaBox [0 0 595 842] /Resources "
        b"<< /Font << /F1 1 0 R >> /XObject << /Im1 3 0 R >> "
        b"/ExtGState << /GS0 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [6 0 R] >>",
        b"<< /Type /Catalog /Pages 7 0 R >>",
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(output)
    output.extend(b"xref\n0 9\n0000000000 65535 f \n")
    output.extend(
        b"".join(
            f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets
        )
    )
    output.extend(
        f"trailer << /Size 9 /Root 8 0 R >>\nstartxref\n{xref}\n%%EOF".encode(
            "ascii"
        )
    )
    return bytes(output)


def test_fidelity_rejects_image_hidden_by_an_intrinsic_soft_mask() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _transparent_smask_image_pdf(image.getvalue()),
        )


def test_fidelity_rejects_image_hidden_by_a_graphics_state_soft_mask() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _extgstate_softmask_image_pdf(image.getvalue()),
        )


@pytest.mark.parametrize("image_y", (400, 100, 1))
def test_fidelity_rejects_gross_inline_image_vertical_relocation(
    image_y: float,
) -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic", image.getvalue(), image_x=100, image_y=image_y
            ),
        )


@pytest.mark.parametrize(
    "image_y",
    (650, 720, 540),
    ids=("between", "above-preceding", "below-following"),
)
def test_fidelity_binds_inline_image_to_surrounding_source_flow(
    image_y: float,
) -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text(
        "Before-223",
        image.getvalue(),
        following_text="After-223",
    )
    pdf = _image_pdf(
        "Before-223",
        image.getvalue(),
        image_x=100,
        image_y=image_y,
        text_y=700,
        following_text="After-223",
        following_text_y=600,
    )

    if image_y == 650:
        delivery_renderer._validate_pdf_fidelity(word, pdf)
    else:
        with pytest.raises(ValueError, match="faithfully represent"):
            delivery_renderer._validate_pdf_fidelity(word, pdf)


def test_fidelity_binds_inline_image_to_the_exact_repeated_flow_occurrence() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_repeated_image_flow(image.getvalue())
    relocated = _image_pdf(
        "Before-223",
        image.getvalue(),
        image_x=100,
        image_y=350,
        text_y=400,
        following_text="After-223",
        following_text_y=300,
        leading_commands=(
            b"BT /F1 10 Tf 1 0 0 1 50 700 Tm (Before-223) Tj ET "
            b"BT /F1 10 Tf 1 0 0 1 50 650 Tm (After-223) Tj ET "
        ),
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, relocated)


def test_fidelity_requires_every_available_inline_flow_context() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text(
        "Before",
        image.getvalue(),
        following_text="After",
        text_runs=("Be", "fore"),
    )
    moved_above_preceding = _image_pdf(
        "Before",
        image.getvalue(),
        image_x=100,
        image_y=720,
        text_y=700,
        following_text="After",
        following_text_y=650,
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, moved_above_preceding)


def test_fidelity_rejects_distinct_inline_images_swapped_between_duplicate_flows() -> None:
    sources = [
        delivery_renderer._WordImageLayout(
            40,
            40,
            "inline",
            "left",
            None,
            None,
            "Before-223",
            "After-223",
            occurrence,
            occurrence,
        )
        for occurrence in (0, 1)
    ]
    candidates = [
        delivery_renderer._PdfImageLayout(0, 100, 430, 140, 470, 595, 842),
        delivery_renderer._PdfImageLayout(0, 100, 630, 140, 670, 595, 842),
    ]
    positioned = [
        delivery_renderer._PositionedText(0, "before-223", 50, 500, 10, 110, 500, 510),
        delivery_renderer._PositionedText(0, "after-223", 50, 400, 10, 100, 400, 410),
        delivery_renderer._PositionedText(0, "before-223", 50, 700, 10, 110, 700, 710),
        delivery_renderer._PositionedText(0, "after-223", 50, 600, 10, 100, 600, 610),
    ]

    assert not delivery_renderer._ordered_image_layouts_match(
        sources, candidates, positioned
    )


def test_word_image_flow_occurrences_preserve_equal_tuple_identity() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        """<w:document
        xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
        xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
        <w:body>
          <w:p><w:r><w:t>Before-223</w:t></w:r></w:p>
          <w:p><w:r><w:drawing><wp:inline>
            <wp:extent cx="508000" cy="508000"/>
            <a:graphic><a:graphicData><a:blip/></a:graphicData></a:graphic>
          </wp:inline></w:drawing></w:r></w:p>
          <w:p><w:r><w:t>After-223</w:t></w:r></w:p>
          <w:p><w:r><w:t>Before-223</w:t></w:r></w:p>
          <w:p><w:r><w:drawing><wp:inline>
            <wp:extent cx="508000" cy="508000"/>
            <a:graphic><a:graphicData><a:blip/></a:graphicData></a:graphic>
          </wp:inline></w:drawing></w:r></w:p>
          <w:p><w:r><w:t>After-223</w:t></w:r></w:p>
        </w:body>
        </w:document>"""
    )

    layouts = delivery_renderer._ordered_word_image_layouts(
        {"word/document.xml": document}
    )

    assert [
        (layout.preceding_occurrence, layout.following_occurrence)
        for layout in layouts
        if layout is not None
    ] == [(0, 0), (1, 1)]


def test_fidelity_rejects_image_hidden_by_intrinsic_color_key_mask() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=100,
                image_dictionary_extra=b"/Mask [0 255 0 255 0 255]",
            ),
        )


def test_fidelity_rejects_image_fully_occluded_by_a_later_opaque_path() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=100,
                trailing_commands=b" 1 1 1 rg 100 600 40 40 re f",
            ),
        )


def test_fidelity_rejects_double_premultiplied_transparent_image() -> None:
    source = BytesIO()
    Image.new("RGBA", (8, 8), (220, 20, 20, 128)).save(source, "PNG")
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _rgba_image_pdf((110, 10, 10), 128),
        )


def test_fidelity_rejects_nonblack_soft_mask_matte() -> None:
    source = BytesIO()
    Image.new("RGBA", (8, 8), (220, 20, 20, 64)).save(source, "PNG")
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _rgba_image_pdf((220, 20, 20), 64, matte=(1, 1, 1)),
        )


def test_fidelity_rejects_non_normal_image_blend_mode() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=100,
                leading_commands=b"1 0 0 rg 100 600 40 40 re f ",
                blend_mode=b"/Difference",
            ),
        )


def test_fidelity_binds_page_anchored_image_position() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text(
        "Synthetic",
        image.getvalue(),
        anchor_x=50,
        anchor_y=100,
    )

    delivery_renderer._validate_pdf_fidelity(
        word,
        _image_pdf("Synthetic", image.getvalue(), image_x=50, image_y=702),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", image.getvalue(), image_x=500, image_y=702),
        )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", image.getvalue(), image_x=50, image_y=100),
        )


def test_image_fidelity_signature_distinguishes_uniform_opposites() -> None:
    black = Image.new("RGB", (64, 64), "black")
    white = Image.new("RGB", (64, 64), "white")
    black_signature = delivery_renderer._image_signature(black)
    white_signature = delivery_renderer._image_signature(white)
    assert black_signature != white_signature
    assert delivery_renderer._ordered_image_signatures_match(
        [black_signature, white_signature], [white_signature, black_signature],
    ) is False
    red_signature = delivery_renderer._image_signature(Image.new("RGB", (64, 64), "red"))
    assert delivery_renderer._ordered_image_signatures_match([black_signature], [red_signature, black_signature]) is False
    assert delivery_renderer._ordered_image_signatures_match([black_signature], [black_signature, red_signature]) is False

    black_bytes = BytesIO(); white_bytes = BytesIO()
    black.save(black_bytes, "PNG"); white.save(white_bytes, "PNG")
    package_bytes = BytesIO()
    document = '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body><w:p><w:r><w:drawing><a:blip r:embed="rId2"/></w:drawing></w:r></w:p><w:p><w:r><w:pict><v:imagedata r:id="rId1"/></w:pict></w:r></w:p></w:body></w:document>'''
    relationships = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="media/image1.png"/><Relationship Id="rId2" Target="media/image2.png"/></Relationships>'''
    with ZipFile(package_bytes, "w", ZIP_DEFLATED) as package:
        package.writestr("word/media/image1.png", black_bytes.getvalue())
        package.writestr("word/media/image2.png", white_bytes.getvalue())
        package.writestr("word/document.xml", document)
        package.writestr("word/_rels/document.xml.rels", relationships)
    with ZipFile(BytesIO(package_bytes.getvalue())) as package:
        root = delivery_renderer.ElementTree.fromstring(package.read("word/document.xml"))
        assert delivery_renderer._ordered_word_image_signatures(package, {"word/document.xml": root}) == [
            white_signature, black_signature,
        ]


def test_fidelity_rejects_spatially_rearranged_isoluminant_colors() -> None:
    red = (255, 0, 0)
    isoluminant_green = (0, 130, 0)

    def image_bytes(*, swapped: bool, output_format: str) -> bytes:
        image = Image.new("RGB", (32, 32))
        for x in range(32):
            for y in range(32):
                if swapped:
                    color = isoluminant_green if x < 16 else red
                else:
                    color = red if x < 16 else isoluminant_green
                image.putpixel((x, y), color)
        output = BytesIO()
        if output_format == "JPEG":
            image.save(output, output_format, quality=100, subsampling=0)
        else:
            image.save(output, output_format)
        return output.getvalue()

    source = image_bytes(swapped=False, output_format="PNG")
    rearranged = image_bytes(swapped=True, output_format="JPEG")
    word = _word_with_image_and_text("Synthetic", source)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", rearranged, image_x=100),
        )


def test_fidelity_rejects_spatial_color_swap_below_quantized_delta_limit() -> None:
    gray = (128, 128, 128)
    isoluminant_magenta = (174, 96, 175)

    def image_bytes(*, swapped: bool) -> bytes:
        image = Image.new("RGB", (32, 32))
        for grid_y in range(8):
            for grid_x in range(8):
                use_magenta = (grid_x + grid_y) % 2 == int(swapped)
                color = isoluminant_magenta if use_magenta else gray
                for y in range(grid_y * 4, (grid_y + 1) * 4):
                    for x in range(grid_x * 4, (grid_x + 1) * 4):
                        image.putpixel((x, y), color)
        output = BytesIO()
        image.save(output, "JPEG", quality=100, subsampling=0)
        return output.getvalue()

    source = image_bytes(swapped=False)
    rearranged = image_bytes(swapped=True)
    word = _word_with_image_and_text("Synthetic", source)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", rearranged, image_x=100),
        )


def test_fidelity_rejects_color_pattern_hidden_by_coarse_spatial_grid() -> None:
    red = (255, 0, 0)
    isoluminant_green = (0, 130, 0)

    def image_bytes(*, inverted: bool, output_format: str) -> bytes:
        image = Image.new("RGB", (32, 32))
        for x in range(32):
            for y in range(32):
                bit = ((x // 3) + (y // 3)) % 2
                if inverted:
                    bit = 1 - bit
                image.putpixel((x, y), red if bit == 0 else isoluminant_green)
        output = BytesIO()
        if output_format == "JPEG":
            image.save(output, output_format, quality=100, subsampling=0)
        else:
            image.save(output, output_format)
        return output.getvalue()

    source = image_bytes(inverted=False, output_format="PNG")
    rearranged = image_bytes(inverted=True, output_format="JPEG")
    word = _word_with_image_and_text("Synthetic", source)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", rearranged, image_x=100),
        )


def test_fidelity_rejects_localized_isoluminant_patch_exchange() -> None:
    red = (255, 0, 0)
    isoluminant_green = (0, 130, 0)
    source_image = Image.new("RGB", (32, 32), red)
    for x in range(16, 32):
        for y in range(32):
            source_image.putpixel((x, y), isoluminant_green)

    rearranged_image = source_image.copy()
    for x in range(5, 11):
        for y in range(13, 19):
            rearranged_image.putpixel((x, y), isoluminant_green)
    for x in range(21, 27):
        for y in range(13, 19):
            rearranged_image.putpixel((x, y), red)

    source = BytesIO()
    source_image.save(source, "PNG")
    rearranged = BytesIO()
    rearranged_image.save(rearranged, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", rearranged.getvalue(), image_x=100),
        )


def test_fidelity_rejects_small_localized_dct_pixel_exchange() -> None:
    red = (255, 0, 0)
    isoluminant_green = (0, 130, 0)
    source_image = Image.new("RGB", (8, 8), red)
    for x in range(4, 8):
        for y in range(8):
            source_image.putpixel((x, y), isoluminant_green)

    rearranged_image = source_image.copy()
    rearranged_image.putpixel((1, 3), isoluminant_green)
    rearranged_image.putpixel((6, 3), red)

    source = BytesIO()
    source_image.save(source, "PNG")
    rearranged = BytesIO()
    rearranged_image.save(rearranged, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", rearranged.getvalue(), image_x=100),
        )


def test_fidelity_rejects_localized_marker_swap_over_texture() -> None:
    random = Random(0)
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(32 * 32)
        ]
    )
    candidate_image = source_image.copy()
    for y in range(3):
        for x in range(3):
            source_image.putpixel((6 + x, 6 + y), (255, 0, 0))
            source_image.putpixel((22 + x, 22 + y), (0, 255, 0))
            candidate_image.putpixel((6 + x, 6 + y), (0, 255, 0))
            candidate_image.putpixel((22 + x, 22 + y), (255, 0, 0))

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_fidelity_rejects_single_pixel_marker_swap_over_texture() -> None:
    random = Random(0)
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(32 * 32)
        ]
    )
    candidate_image = source_image.copy()
    source_image.putpixel((6, 6), (255, 0, 0))
    source_image.putpixel((22, 22), (0, 255, 0))
    candidate_image.putpixel((6, 6), (0, 255, 0))
    candidate_image.putpixel((22, 22), (255, 0, 0))

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_fidelity_rejects_moderate_marker_swap_over_texture() -> None:
    random = Random(0)
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(32 * 32)
        ]
    )
    candidate_image = source_image.copy()
    first_color = (200, 40, 40)
    second_color = (40, 200, 40)
    for y in range(2):
        for x in range(2):
            source_image.putpixel((6 + x, 6 + y), first_color)
            source_image.putpixel((22 + x, 22 + y), second_color)
            candidate_image.putpixel((6 + x, 6 + y), second_color)
            candidate_image.putpixel((22 + x, 22 + y), first_color)

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_fidelity_rejects_diffuse_residual_padding_around_marker_swap() -> None:
    random = Random(0)
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(32 * 32)
        ]
    )
    candidate_image = source_image.copy()
    for y in range(32):
        for x in range(32):
            red, green, blue = candidate_image.getpixel((x, y))
            direction = 1 if x < 16 else -1
            candidate_image.putpixel(
                (x, y),
                (
                    max(0, min(255, red + direction * 26)),
                    max(0, min(255, green - direction * 13)),
                    blue,
                ),
            )
    for y in range(3):
        for x in range(3):
            source_image.putpixel((6 + x, 6 + y), (255, 0, 0))
            source_image.putpixel((22 + x, 22 + y), (0, 130, 0))
            candidate_image.putpixel((6 + x, 6 + y), (0, 130, 0))
            candidate_image.putpixel((22 + x, 22 + y), (255, 0, 0))

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_fidelity_rejects_distributed_chromatic_adulteration() -> None:
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (
                (x * 7 + y * 3) % 256,
                (x * 5 + y * 11) % 256,
                (x * 13 + y * 2) % 256,
            )
            for y in range(32)
            for x in range(32)
        ]
    )
    candidate_image = source_image.copy()
    for y in range(0, 32, 2):
        for x in range(0, 32, 2):
            red, green, blue = candidate_image.getpixel((x, y))
            candidate_image.putpixel(
                (x, y),
                (min(255, red + 48), max(0, green - 48), blue),
            )

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_fidelity_rejects_balanced_distributed_chromatic_adulteration() -> None:
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (
                80 + (x * 7 + y * 3) % 96,
                80 + (x * 5 + y * 11) % 96,
                80 + (x * 13 + y * 2) % 96,
            )
            for y in range(32)
            for x in range(32)
        ]
    )
    candidate_image = source_image.copy()
    for y in range(0, 32, 2):
        for x in range(0, 32, 2):
            red, green, blue = candidate_image.getpixel((x, y))
            direction = 1 if (x // 2 + y // 2) % 2 == 0 else -1
            candidate_image.putpixel(
                (x, y),
                (red + direction * 32, green - direction * 32, blue),
            )

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_fidelity_rejects_patch_exchange_across_spatial_boundaries() -> None:
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (
                (x * 7 + y * 3) % 256,
                (x * 5 + y * 11) % 256,
                (x * 13 + y * 2) % 256,
            )
            for y in range(32)
            for x in range(32)
        ]
    )
    candidate_image = source_image.copy()
    first_patch = source_image.crop((7, 23, 13, 29))
    second_patch = source_image.crop((9, 17, 15, 23))
    candidate_image.paste(second_patch, (7, 23))
    candidate_image.paste(first_patch, (9, 17))

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=100, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_image_fidelity_signature_preserves_legitimate_alpha_semantics() -> None:
    source = Image.new("RGBA", (32, 32), (220, 20, 20, 128))
    word_style = delivery_renderer._image_signature(source)
    pdf_premultiplied_style = delivery_renderer._image_signature(
        Image.new("RGBA", (32, 32), (110, 10, 10, 128)),
        premultiplied_alpha=True,
    )
    invisible_forgery = delivery_renderer._image_signature(
        Image.new("RGBA", (32, 32), (110, 10, 10, 0))
    )

    assert delivery_renderer._ordered_image_signatures_match(
        [word_style], [pdf_premultiplied_style]
    )
    assert not delivery_renderer._ordered_image_signatures_match(
        [word_style], [invisible_forgery]
    )


def test_image_fidelity_ignores_rgb_hidden_beneath_zero_alpha() -> None:
    source = Image.new("RGBA", (32, 32), (255, 0, 0, 0))
    normalized = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for image in (source, normalized):
        for x in range(8, 24):
            for y in range(8, 24):
                image.putpixel((x, y), (0, 0, 255, 255))

    assert delivery_renderer._ordered_image_signatures_match(
        [delivery_renderer._image_signature(source)],
        [delivery_renderer._image_signature(normalized)],
    )


def test_image_fidelity_preserves_legitimate_lossy_color_encoding() -> None:
    source = Image.new("RGB", (64, 64))
    for x in range(64):
        for y in range(64):
            source.putpixel((x, y), (x * 4, y * 4, (x + y) * 2))
    encoded = BytesIO()
    source.save(encoded, "JPEG", quality=85, subsampling=0)

    with Image.open(BytesIO(encoded.getvalue())) as candidate:
        assert delivery_renderer._ordered_image_signatures_match(
            [delivery_renderer._image_signature(source)],
            [delivery_renderer._image_signature(candidate)],
        )


def test_image_fidelity_preserves_legitimate_continuous_rgb_resampling() -> None:
    source = Image.new("RGB", (32, 32))
    source.putdata(
        [
            (
                (x * 7 + y * 3) % 256,
                (x * 5 + y * 11) % 256,
                (x * 13 + y * 2) % 256,
            )
            for y in range(32)
            for x in range(32)
        ]
    )
    resampled = source.filter(ImageFilter.GaussianBlur(1))

    assert delivery_renderer._ordered_image_signatures_match(
        [delivery_renderer._image_signature(source)],
        [delivery_renderer._image_signature(resampled)],
    )


def test_image_fidelity_preserves_low_contrast_resampling() -> None:
    source = Image.new("RGB", (80, 48))
    source.putdata(
        [
            (
                110 + (x * 17 + y * 5) % 35,
                115 + (x * 3 + y * 19) % 31,
                120 + (x * 11 + y * 7) % 29,
            )
            for y in range(48)
            for x in range(80)
        ]
    )
    resampled = source.filter(ImageFilter.GaussianBlur(1))

    assert delivery_renderer._ordered_image_signatures_match(
        [delivery_renderer._image_signature(source)],
        [delivery_renderer._image_signature(resampled)],
    )


def test_final_pdf_conversion_fails_closed_without_a_local_converter() -> None:
    class Unavailable:
        def convert(self, _content: bytes, _source_format: str) -> bytes:
            raise RuntimeError("local Office PDF converter is unavailable")

    word = BytesIO()
    with ZipFile(word, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("word/document.xml", "<document/>")
    with pytest.raises(ValueError, match="local Office PDF conversion unavailable"):
        delivery_renderer.render_final_pdf_candidate(
            word_content=word.getvalue(), word_format="DOCX", converter=Unavailable(),
        )


def test_text_only_diagnostic_pdf_can_never_become_a_final_professional_pdf() -> None:
    report = report_snapshot_from_mapping(json.loads((Path(__file__).parent / "fixtures/report-snapshot-v1.json").read_text(encoding="utf-8")))
    diagnostic = render_pdf_candidate(report)
    word = BytesIO()
    with ZipFile(word, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("word/document.xml", "<document/>")

    class DiagnosticConverter:
        def convert(self, _content: bytes, _source_format: str) -> bytes:
            return diagnostic

    with pytest.raises(ValueError, match="diagnostic PDF cannot be finalized"):
        delivery_renderer.render_final_pdf_candidate(
            word_content=word.getvalue(), word_format="DOCX", converter=DiagnosticConverter(),
        )
    digest, size, _ = validate_final_artifact(diagnostic, "PDF")
    with pytest.raises(ValueError, match="diagnostic PDF cannot be a Delivery artifact"):
        verify_reopened_artifact(
            content=diagnostic, output_format="PDF", expected_size=size, expected_sha256=digest,
        )
    alternate_whitespace = diagnostic.replace(b"/DiagnosticOnly true", b"/DiagnosticOnly\ntrue")
    assert b"/DiagnosticOnly true" not in alternate_whitespace
    with pytest.raises(ValueError, match="diagnostic PDF cannot be a Delivery artifact"):
        delivery_renderer.validate_delivery_artifact(alternate_whitespace, "PDF")
