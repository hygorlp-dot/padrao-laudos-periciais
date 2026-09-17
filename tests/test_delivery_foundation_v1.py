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
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NullObject,
    NumberObject,
)

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


def _word_with_repeatable_text(
    body_fragments: tuple[str, ...], header_text: str, footer_text: str
) -> bytes:
    def paragraph(text: str, *, page_break_before: bool = False) -> str:
        properties = "<w:pPr><w:pageBreakBefore/></w:pPr>" if page_break_before else ""
        return (
            f'<w:p>{properties}<w:r><w:rPr><w:sz w:val="22"/></w:rPr>'
            f"<w:t>{text}</w:t></w:r></w:p>"
        )

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            + "".join(
                paragraph(fragment, page_break_before=index > 0)
                for index, fragment in enumerate(body_fragments)
            )
            + "</w:body></w:document>",
        )
        package.writestr(
            "word/header1.xml",
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            + paragraph(header_text)
            + "</w:hdr>",
        )
        package.writestr(
            "word/footer1.xml",
            '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            + paragraph(footer_text)
            + "</w:ftr>",
        )
    return output.getvalue()


def _word_with_emphasized_text(text: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:rPr><w:b/><w:i/><w:u w:val="single"/></w:rPr>'
            f"<w:t>{text}</w:t></w:r></w:p></w:body></w:document>",
        )
    return output.getvalue()


def _word_with_header_image(body_text: str, image_bytes: bytes) -> bytes:
    output = BytesIO()
    width_emu = round(172.8 * 12_700)
    height_emu = round(51.84 * 12_700)
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{body_text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    header = (
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<w:p><w:r><w:drawing><wp:inline>"
        f'<wp:extent cx="{width_emu}" cy="{height_emu}"/>'
        '<a:graphic><a:graphicData><a:blip r:embed="rId1"/>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
        "</w:hdr>"
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="media/header.png"/>'
        "</Relationships>"
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
        package.writestr("word/header1.xml", header)
        package.writestr("word/_rels/header1.xml.rels", relationships)
        package.writestr("word/media/header.png", image_bytes)
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
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>'
            "</Types>",
        )
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
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        package.writestr("word/document.xml", "<document/>")
    with pytest.raises(ValueError, match="macro identity"):
        validate_final_artifact(output.getvalue(), "DOCM")
    with pytest.raises(ValueError, match="PDF"):
        validate_final_artifact(b"%PDF-1.7\nno page or eof", "PDF")
    with pytest.raises(ValueError, match="PDF"):
        validate_final_artifact(b"%PDF-1.7\n1 0 obj <</Type /Page>> endobj\n%%EOF", "PDF")


def test_macro_enabled_word_container_does_not_require_a_vba_project() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>'
            "</Types>",
        )
        package.writestr("word/document.xml", "<document/>")

    _digest, _size, media = validate_final_artifact(output.getvalue(), "DOCM")

    assert media == "application/vnd.ms-word.document.macroEnabled.12"


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


def test_conversion_copy_preserves_docm_authority_and_rejects_external_relationships() -> None:
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
    # The authoritative DOCM reaches the renderer byte-exact.  Macros are
    # neutralised by the worker's forced AutomationSecurity, not by amputating
    # parts out of the authority.
    assert kind == "DOCM"
    assert converted == clean.getvalue()
    with ZipFile(BytesIO(converted)) as package:
        assert "word/vbaProject.bin" in package.namelist()


def test_word_validation_rejects_noncanonical_external_target_mode() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document.main+xml"/></Types>',
        )
        package.writestr("word/document.xml", "<document/>")
        package.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Id="rId1" Type="template" '
            'Target="synthetic-private.png" TargetMode=" External "/>'
            "</Relationships>",
        )

    with pytest.raises(ValueError, match="external relationships"):
        validate_final_artifact(output.getvalue(), "DOCX")


def test_conversion_copy_preserves_macro_parts_verbatim() -> None:
    source = BytesIO()
    with ZipFile(source, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>'
            '<Override PartName="/word/VBAProject.bin" '
            'ContentType="application/vnd.ms-office.vbaProject"/></Types>',
        )
        package.writestr("word/document.xml", "<document/>")
        package.writestr("word/VBAProject.bin", b"synthetic macro payload")
        package.writestr(
            "word/_rels/document.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdMacro" '
            'Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" '
            'Target="VBAProject.bin"/></Relationships>',
        )

    converted, kind = safe_pdf_conversion_copy(source.getvalue(), "DOCM")

    assert kind == "DOCM"
    assert converted == source.getvalue()
    with ZipFile(BytesIO(converted)) as package:
        assert "word/VBAProject.bin" in package.namelist()
        relationships = package.read("word/_rels/document.xml.rels").decode()
        assert "vbaproject" in relationships.casefold()


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
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/>'
            "</Types>",
        )
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


def test_fidelity_accepts_native_ordered_header_image() -> None:
    image = BytesIO()
    Image.new("RGB", (240, 72), (22, 74, 140)).save(image, "PNG")
    word = _word_with_header_image("Synthetic", image.getvalue())

    delivery_renderer._validate_pdf_fidelity(
        word,
        _image_pdf(
            "Synthetic",
            image.getvalue(),
            image_x=90,
            image_y=740,
            image_width=172.8,
            image_height=51.84,
            image_after_text=True,
        ),
    )


def test_repeatable_header_images_are_bound_once_per_page() -> None:
    first = delivery_renderer._image_signature(Image.new("RGB", (32, 16), "blue"))
    second = delivery_renderer._image_signature(Image.new("RGB", (32, 16), "red"))
    source_layouts = [
        delivery_renderer._WordImageLayout(
            120, 30, "inline", "left", None, None
        ),
        delivery_renderer._WordImageLayout(
            120, 30, "inline", "left", None, None
        ),
    ]
    candidates = [
        delivery_renderer._PdfImageLayout(
            page, 50, bottom, 170, bottom + 30, 595, 842
        )
        for page in range(3)
        for bottom in (760, 720)
    ]
    signatures = [first, second] * 3

    def matches(
        candidate_signatures: list[tuple],
        candidate_layouts: list[delivery_renderer._PdfImageLayout],
    ) -> bool:
        return delivery_renderer._repeatable_word_images_match(
            document_signatures=[],
            document_layouts=[],
            header_signatures=[first, second],
            header_layouts=source_layouts,
            footer_signatures=[],
            footer_layouts=[],
            candidate_signatures=candidate_signatures,
            candidate_layouts=candidate_layouts,
            positioned_text=[],
            page_count=3,
        )

    assert matches(signatures, candidates)
    assert not matches(signatures[:-1], candidates[:-1])
    assert not matches(signatures + [first], candidates + [candidates[-1]])
    relocated = [*candidates]
    relocated[2] = replace(relocated[2], bottom=300, top=330)
    assert not matches(signatures, relocated)
    reordered = [*signatures]
    reordered[2:4] = [second, first]
    assert not matches(reordered, candidates)


def test_header_image_variants_are_selected_per_effective_page() -> None:
    first = delivery_renderer._image_signature(Image.new("RGB", (32, 16), "blue"))
    default = delivery_renderer._image_signature(Image.new("RGB", (32, 16), "red"))
    layout = delivery_renderer._WordImageLayout(
        120, 30, "inline", "left", None, None
    )
    candidates = [
        delivery_renderer._PdfImageLayout(
            page, 50, 760, 170, 790, 595, 842
        )
        for page in range(2)
    ]

    def matches(signatures: list[tuple]) -> bool:
        return delivery_renderer._repeatable_word_images_match(
            document_signatures=[],
            document_layouts=[],
            header_signatures=[],
            header_layouts=[],
            footer_signatures=[],
            footer_layouts=[],
            candidate_signatures=signatures,
            candidate_layouts=candidates,
            positioned_text=[],
            page_count=2,
            header_signatures_by_page=[[first], [default]],
            header_layouts_by_page=[[layout], [layout]],
            footer_signatures_by_page=[[], []],
            footer_layouts_by_page=[[], []],
        )

    assert matches([first, default])
    assert not matches([default, first])


def test_repeatable_header_image_cannot_move_into_document_body() -> None:
    image = BytesIO()
    Image.new("RGB", (240, 72), (22, 74, 140)).save(image, "PNG")
    word = _word_with_header_image("Synthetic", image.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf(
                "Synthetic",
                image.getvalue(),
                image_x=90,
                image_y=430,
                image_width=172.8,
                image_height=51.84,
                image_after_text=True,
            ),
        )
def test_repeatable_header_and_footer_text_are_required_on_every_page() -> None:
    word = _word_with_repeatable_text(
        ("Body One 223", "Body Two 223", "Body Three 223"),
        "Header 223",
        "Footer 223",
    )
    complete = _positioned_text_pdf(
        [
            [
                ("Header 223", 50, 800, 11, 0),
                (f"Body {name} 223", 50, 700, 11, 0),
                ("Footer 223", 50, 40, 11, 0),
            ]
            for name in ("One", "Two", "Three")
        ]
    )
    missing = _positioned_text_pdf(
        [
            [
                ("Header 223", 50, 800, 11, 0),
                ("Body One 223", 50, 700, 11, 0),
            ],
            [("Body Two 223", 50, 700, 11, 0)],
            [
                ("Body Three 223", 50, 700, 11, 0),
                ("Footer 223", 50, 40, 11, 0),
            ],
        ]
    )

    delivery_renderer._validate_pdf_fidelity(word, complete)
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, missing)


def test_repeatable_header_text_cannot_move_into_document_body_band() -> None:
    positioned = [
        delivery_renderer._PositionedText(
            0, "header 223", 50, 493, 11, 160, 493, 501
        )
    ]

    assert not delivery_renderer._repeatable_text_matches(
        header_fragments_by_page=[["Header 223"]],
        footer_fragments_by_page=[[]],
        positioned=positioned,
        page_heights=[792],
    )


def test_page_field_uses_effective_page_number_instead_of_cached_word_result() -> None:
    paragraph = delivery_renderer.ElementTree.fromstring(
        '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:r><w:t>Page </w:t></w:r>'
        '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>'
        "</w:p>"
    )

    assert delivery_renderer._dynamic_paragraph_text(
        paragraph, page_number=3
    ) == "Page 3"


def test_internal_word_hyperlink_is_bound_to_named_bookmark_text() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:body><w:p><w:bookmarkStart w:id="1" w:name="Target"/>'
        '<w:r><w:t>Target text</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>'
        '<w:p><w:hyperlink w:anchor="Target"><w:r><w:t>Go to target</w:t></w:r>'
        "</w:hyperlink></w:p></w:body></w:document>"
    )

    assert delivery_renderer._word_internal_link_expectations(document) == [
        delivery_renderer._WordInternalLinkExpectation(
            "go to target", "target text"
        )
    ]

    external = next(delivery_renderer._iter_named(document, "hyperlink"))
    external.set(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
        "rIdExternal",
    )
    with pytest.raises(ValueError, match="external Word hyperlink"):
        delivery_renderer._word_internal_link_expectations(document)


def test_internal_word_hyperlink_preserves_duplicate_target_occurrence() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Repeated target</w:t></w:r></w:p>"
        '<w:p><w:bookmarkStart w:id="1" w:name="Target"/>'
        '<w:r><w:t>Repeated target</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>'
        '<w:p><w:hyperlink w:anchor="Target"><w:r><w:t>Go there</w:t></w:r>'
        "</w:hyperlink></w:p></w:body></w:document>"
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_occurrence == 1


def test_internal_word_hyperlink_binds_bookmarked_run_not_whole_paragraph() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Target A </w:t></w:r>'
        '<w:bookmarkStart w:id="2" w:name="TargetB"/>'
        '<w:r><w:t>Target B</w:t></w:r><w:bookmarkEnd w:id="2"/></w:p>'
        '<w:p><w:hyperlink w:anchor="TargetB"><w:r><w:t>Go B</w:t></w:r>'
        "</w:hyperlink></w:p></w:body></w:document>"
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_text == "target b"
    assert expectation.target_occurrence == 0


def test_bookmark_target_locations_distinguish_runs_on_same_line() -> None:
    positioned = [
        delivery_renderer._PositionedText(
            0,
            "Target A Target B",
            90,
            700,
            11,
            190,
            700,
            712,
        )
    ]

    [location] = delivery_renderer._positioned_target_locations(
        "target b", positioned, []
    )

    assert location[0] == 0
    assert location[1] > 135
    assert location[2] == 712


def test_internal_link_destination_distinguishes_same_line_bookmarks() -> None:
    word = BytesIO()
    with ZipFile(word, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p>'
            '<w:bookmarkStart w:id="1" w:name="A"/><w:r><w:t>Target A</w:t></w:r>'
            '<w:bookmarkEnd w:id="1"/><w:r><w:t> </w:t></w:r>'
            '<w:bookmarkStart w:id="2" w:name="B"/><w:r><w:t>Target B</w:t></w:r>'
            '<w:bookmarkEnd w:id="2"/></w:p><w:p>'
            '<w:hyperlink w:anchor="B"><w:r><w:t>Go B</w:t></w:r></w:hyperlink>'
            "</w:p></w:body></w:document>",
        )
    source_pdf = _positioned_text_pdf(
        [[
            ("Target A", 50, 700, 11, 0),
            ("Target B", 120, 700, 11, 0),
            ("Go B", 50, 685, 11, 0),
        ]]
    )

    def candidate(destination_x: float) -> bytes:
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(BytesIO(source_pdf), strict=True))
        page = writer.pages[0]
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(48), FloatObject(680), FloatObject(85), FloatObject(700)]
                ),
                NameObject("/Dest"): ArrayObject(
                    [
                        page.indirect_reference,
                        NameObject("/XYZ"),
                        FloatObject(destination_x),
                        FloatObject(710),
                        NullObject(),
                    ]
                ),
            }
        )
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    correct = candidate(120)
    reader = PdfReader(BytesIO(correct), strict=True)
    positioned, barriers, *_ = delivery_renderer._pdfium_visible_layout(correct)
    with ZipFile(BytesIO(word.getvalue())) as package:
        expectations = delivery_renderer._word_internal_link_expectations(
            delivery_renderer.ElementTree.fromstring(
                package.read("word/document.xml")
            )
        )
    assert delivery_renderer._annotations_match_internal_links(
        reader,
        expectations,
        delivery_renderer._positioned_reading_order(positioned),
        barriers,
    )
    delivery_renderer._validate_pdf_fidelity(word.getvalue(), correct)
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word.getvalue(), candidate(50))


def test_text_style_expectations_ignore_inactive_header_variants() -> None:
    roots = {
        "word/document.xml": delivery_renderer.ElementTree.fromstring(
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Body</w:t></w:r></w:p></w:body></w:document>"
        ),
        "word/header1.xml": delivery_renderer.ElementTree.fromstring(
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:p><w:r><w:t>Active first</w:t></w:r></w:p></w:hdr>"
        ),
        "word/header2.xml": delivery_renderer.ElementTree.fromstring(
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:p><w:r><w:t>Unused default</w:t></w:r></w:p></w:hdr>"
        ),
    }

    expectations = delivery_renderer._word_text_expectations(
        roots,
        active_content_names={"word/document.xml", "word/header1.xml"},
    )

    assert {item.text for item in expectations} == {"body", "active first"}


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


def test_borderless_table_row_accepts_wrapped_text_within_its_own_cell() -> None:
    positioned = [
        delivery_renderer._PositionedText(
            0, "left cell", 90, 700, 11, 145, 700, 710
        ),
        delivery_renderer._PositionedText(
            0, "right cell alpha", 190, 700, 11, 300, 700, 710
        ),
        delivery_renderer._PositionedText(
            0, "beta", 190, 685, 11, 225, 685, 695
        ),
    ]

    assert delivery_renderer._table_rows_match(
        [("left cell", "right cell alpha beta")], positioned, []
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
            [[("First", 50, 700, 11, 0), ("Second", 50, 685, 11, 0)]]
        ),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _positioned_text_pdf(
                [[("First", 50, 500, 11, 0), ("Second", 50, 700, 11, 0)]]
            ),
        )


def test_fidelity_rejects_right_aligned_paragraph_crossing_columns() -> None:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r>'
            '<w:t>Right column left column</w:t></w:r></w:p></w:body></w:document>',
        )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            output.getvalue(),
            _positioned_text_pdf(
                [[
                    ("Right column", 450, 700, 11, 0),
                    ("left column", 50, 685, 11, 0),
                ]]
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


def test_fidelity_rejects_unbound_visible_filled_path() -> None:
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
                trailing_commands=b" q 1 0 0 rg 420 40 120 90 re f Q",
            ),
        )


def test_fidelity_rejects_unbound_visible_stroked_path() -> None:
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
                trailing_commands=b" q 1 0 0 RG 4 w 420 40 120 90 re S Q",
            ),
        )


def test_table_grid_path_binding_supports_page_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fragment(page: int, text: str, x: float) -> delivery_renderer._PositionedText:
        return delivery_renderer._PositionedText(
            page, text, x, 700, 11, x + 30, 690, 710
        )

    matched_rows = [
        [fragment(0, "A", 100), fragment(0, "B", 200)],
        [fragment(1, "C", 100), fragment(1, "D", 200)],
    ]
    monkeypatch.setattr(
        delivery_renderer,
        "_matched_table_row_fragments",
        lambda _rows, _positioned, _barriers: matched_rows,
    )

    def segment_paths(page: int) -> list[delivery_renderer._PaintedPath]:
        paths = [
            delivery_renderer._PaintedPath(page, x - 0.25, 690, x + 0.25, 710)
            for x in (100, 200, 300)
        ] + [
            delivery_renderer._PaintedPath(page, 100, y - 0.25, 300, y + 0.25)
            for y in (690, 710)
        ]
        while len(paths) < 17:
            paths.append(paths[len(paths) % 5])
        return paths

    paths = segment_paths(0) + segment_paths(1)
    table = delivery_renderer._WordTableExpectation(
        (("A", "B"), ("C", "D")),
        (0, 100, 200),
        (2, 2),
        (0, 0),
        ((), ()),
        ((1,), (1,)),
        (),
        True,
    )
    assert delivery_renderer._painted_paths_are_bound_to_tables(
        paths, [table], [], []
    )
    assert not delivery_renderer._painted_paths_are_bound_to_tables(
        paths + [delivery_renderer._PaintedPath(1, 110, 695, 111, 705)],
        [table],
        [],
        [],
    )
    red_paths = [replace(path, fill_color=(255, 0, 0, 255)) for path in paths]
    assert not delivery_renderer._painted_paths_are_bound_to_tables(
        red_paths, [table], [], []
    )


def test_fidelity_rejects_loss_of_text_emphasis_underline_and_alignment() -> None:
    word = _word_with_emphasized_text("MATERIAL SAFETY WARNING 223")
    regular_left_aligned = _positioned_text_pdf(
        [[("MATERIAL SAFETY WARNING 223", 50, 700, 11, 0)]]
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, regular_left_aligned)


def test_fidelity_rejects_bold_loss_inside_a_table_cell() -> None:
    output = BytesIO()
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:tbl><w:tr>"
        "<w:tc><w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold cell 223</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Control cell 223</w:t></w:r></w:p></w:tc>"
        "</w:tr></w:tbl></w:body></w:document>"
    )
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
    regular = _positioned_text_pdf(
        [[
            ("Bold cell 223", 50, 700, 11, 0),
            ("Control cell 223", 250, 700, 11, 0),
        ]]
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(output.getvalue(), regular)


def test_word_text_expectations_include_table_cell_emphasis() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:rPr><w:b/></w:rPr>"
        "<w:t>Bold cell 223</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:body></w:document>"
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert [(item.text, item.bold, item.in_table) for item in expectations] == [
        ("bold cell 223", True, True)
    ]
    assert expectations[0].enforce_visible_run_style is True


def test_word_text_expectations_include_inherited_table_typography() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:tbl><w:tr><w:tc><w:p><w:r>"
        "<w:t>Cell 223</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:body></w:document>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert expectation.text == "cell 223"
    assert expectation.font_size == 11
    assert expectation.in_table is True
    assert expectation.enforce_visible_run_style is False


def test_word_text_expectations_keep_style_enforcement_per_table_run() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tr><w:tc><w:p>'
        '<w:r><w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr>'
        '<w:t>Styled 223</w:t></w:r>'
        '<w:r><w:t> Plain 223</w:t></w:r>'
        '</w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert [item.text for item in expectations] == ["styled 223", "plain 223"]
    assert expectations[0].bold is True
    assert expectations[0].color == (255, 0, 0)
    assert expectations[0].enforce_visible_run_style is True
    assert expectations[1].enforce_visible_run_style is False


def test_word_text_expectations_resolve_conditional_table_typography() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="SyntheticTable"/>'
        '<w:tblLook w:firstRow="1"/></w:tblPr><w:tr><w:tc><w:p><w:r>'
        '<w:t>Styled cell 223</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:rPr><w:sz w:val="22"/><w:rFonts w:ascii="Calibri" '
        'w:hAnsi="Calibri"/></w:rPr></w:style>'
        '<w:style w:type="table" w:styleId="SyntheticTable">'
        '<w:tblStylePr w:type="firstRow"><w:rPr><w:b/><w:sz w:val="40"/>'
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/></w:rPr>'
        '</w:tblStylePr></w:style></w:styles>'
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert expectation.font_size == 20
    assert expectation.font_family == "Arial"
    assert expectation.bold is True
    assert expectation.enforce_visible_run_style is True


def test_word_text_expectations_resolve_sibling_table_conditions_and_base_style() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="DerivedTable"/>'
        '<w:tblLook w:firstRow="1" w:lastRow="1" w:firstColumn="1"/>'
        '</w:tblPr><w:tr><w:tc><w:p><w:r><w:t>A1</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>B1</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>A2</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>B2</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="table" w:styleId="BaseTable"><w:rPr>'
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/></w:rPr></w:style>'
        '<w:style w:type="table" w:styleId="DerivedTable">'
        '<w:basedOn w:val="BaseTable"/>'
        '<w:tblStylePr w:type="firstRow"><w:rPr><w:sz w:val="40"/></w:rPr>'
        '</w:tblStylePr><w:tblStylePr w:type="lastRow"><w:rPr>'
        '<w:sz w:val="30"/></w:rPr></w:tblStylePr>'
        '<w:tblStylePr w:type="firstCol"><w:rPr><w:b/></w:rPr>'
        '</w:tblStylePr></w:style></w:styles>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert [item.text for item in expectations] == ["a1", "b1", "a2", "b2"]
    assert [item.font_size for item in expectations] == [20, 20, 15, 15]
    assert [item.bold for item in expectations] == [True, False, True, False]
    assert {item.font_family for item in expectations} == {"Arial"}


def test_word_text_expectations_apply_base_condition_after_derived_whole_table() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="Derived"/>'
        '<w:tblLook w:firstRow="1"/></w:tblPr><w:tr><w:tc><w:p><w:r>'
        '<w:t>Authority</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body>'
        '</w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="table" w:styleId="Base"><w:tblStylePr w:type="firstRow">'
        '<w:rPr><w:sz w:val="40"/><w:color w:val="FF0000"/></w:rPr>'
        '</w:tblStylePr></w:style><w:style w:type="table" w:styleId="Derived">'
        '<w:basedOn w:val="Base"/><w:rPr><w:sz w:val="16"/>'
        '<w:color w:val="0000FF"/></w:rPr></w:style></w:styles>'
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert expectation.font_size == 20
    assert expectation.color == (255, 0, 0)


def test_word_text_expectations_honor_table_look_mask_and_column_precedence() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="Masked"/>'
        '<w:tblLook w:val="0040"/></w:tblPr>'
        '<w:tr><w:tc><w:p><w:r><w:t>First</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>Last</w:t></w:r></w:p></w:tc></w:tr>'
        '</w:tbl><w:tbl><w:tblPr><w:tblStyle w:val="Columns"/>'
        '<w:tblLook w:firstRow="0" w:firstColumn="1" w:lastColumn="1"/>'
        '</w:tblPr><w:tr><w:tc><w:p><w:r><w:t>Overlap</w:t></w:r>'
        '</w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="table" w:styleId="Masked">'
        '<w:tblStylePr w:type="firstRow"><w:rPr><w:sz w:val="30"/>'
        '</w:rPr></w:tblStylePr><w:tblStylePr w:type="lastRow"><w:rPr>'
        '<w:sz w:val="40"/></w:rPr></w:tblStylePr></w:style>'
        '<w:style w:type="table" w:styleId="Columns">'
        '<w:tblStylePr w:type="lastCol"><w:rPr><w:sz w:val="28"/>'
        '</w:rPr></w:tblStylePr><w:tblStylePr w:type="firstCol"><w:rPr>'
        '<w:sz w:val="40"/></w:rPr></w:tblStylePr></w:style></w:styles>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert [item.font_size for item in expectations] == [11, 20, 20]


def test_word_text_expectations_honor_table_row_band_size_for_typography() -> None:
    rows = "".join(
        f'<w:tr><w:tc><w:p><w:r><w:t>Row {index}</w:t></w:r></w:p></w:tc></w:tr>'
        for index in range(4)
    )
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="Bands"/>'
        '<w:tblLook w:firstRow="0" w:lastRow="0" w:firstColumn="0" '
        'w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
        f'{rows}</w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="table" w:styleId="Bands"><w:tblPr>'
        '<w:tblStyleRowBandSize w:val="2"/></w:tblPr>'
        '<w:tblStylePr w:type="band1Horz"><w:rPr><w:sz w:val="40"/>'
        '</w:rPr></w:tblStylePr><w:tblStylePr w:type="band2Horz"><w:rPr>'
        '<w:sz w:val="16"/></w:rPr></w:tblStylePr></w:style></w:styles>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert [item.font_size for item in expectations] == [20, 20, 8, 8]


def test_word_table_banding_starts_after_enabled_first_row() -> None:
    rows = "".join(
        f'<w:tr><w:tc><w:p><w:r><w:t>Row {index}</w:t></w:r></w:p></w:tc></w:tr>'
        for index in range(3)
    )
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="Bands"/>'
        '<w:tblLook w:firstRow="1" w:firstColumn="0" w:lastColumn="0" '
        'w:noHBand="0" w:noVBand="1"/></w:tblPr>'
        f'{rows}</w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="table" w:styleId="Bands">'
        '<w:tblStylePr w:type="firstRow"><w:rPr><w:sz w:val="36"/>'
        '</w:rPr></w:tblStylePr><w:tblStylePr w:type="band1Horz"><w:rPr>'
        '<w:sz w:val="28"/></w:rPr></w:tblStylePr><w:tblStylePr '
        'w:type="band2Horz"><w:rPr><w:sz w:val="20"/></w:rPr>'
        '</w:tblStylePr></w:style></w:styles>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert [item.font_size for item in expectations] == [18, 10, 14]


def test_empty_first_row_condition_keeps_applicable_horizontal_band_typography() -> None:
    rows = "".join(
        f'<w:tr><w:tc><w:p><w:r><w:t>Row {index}</w:t></w:r></w:p></w:tc></w:tr>'
        for index in range(2)
    )
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="Bands"/>'
        '<w:tblLook w:firstRow="1" w:firstColumn="0" w:lastColumn="0" '
        'w:noHBand="0" w:noVBand="1"/></w:tblPr>'
        f'{rows}</w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="table" w:styleId="Bands">'
        '<w:tblStylePr w:type="firstRow"><w:rPr/></w:tblStylePr>'
        '<w:tblStylePr w:type="band1Horz"><w:rPr><w:sz w:val="40"/>'
        '</w:rPr></w:tblStylePr></w:style></w:styles>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert [item.font_size for item in expectations] == [20, 11]


def test_first_column_region_suppresses_horizontal_band_typography() -> None:
    rows = "".join(
        f'<w:tr><w:tc><w:p><w:r><w:t>Row {index}</w:t></w:r></w:p></w:tc></w:tr>'
        for index in range(2)
    )
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tblPr><w:tblStyle w:val="Bands"/>'
        '<w:tblLook w:firstRow="0" w:firstColumn="1" w:lastColumn="0" '
        'w:noHBand="0" w:noVBand="1"/></w:tblPr>'
        f'{rows}</w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="table" w:styleId="Bands">'
        '<w:tblStylePr w:type="band1Horz"><w:rPr><w:sz w:val="40"/>'
        '</w:rPr></w:tblStylePr><w:tblStylePr w:type="band2Horz"><w:rPr>'
        '<w:sz w:val="16"/></w:rPr></w:tblStylePr></w:style></w:styles>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert [item.font_size for item in expectations] == [11, 11]


def test_default_paragraph_emphasis_is_enforced_inside_table() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Inherited</w:t>'
        '</w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:rPr><w:b/><w:color w:val="FF0000"/></w:rPr>'
        '</w:style></w:styles>'
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert expectation.bold is True
    assert expectation.color == (255, 0, 0)
    assert expectation.enforce_visible_run_style is True


def test_word_text_expectations_preserve_whitespace_only_run() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Target A</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        "<w:r><w:t>Target B</w:t></w:r></w:p></w:body></w:document>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert expectation.text == "target a target b"


def test_word_text_expectation_binds_explicit_font_family() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:rPr><w:rFonts w:ascii="Times New Roman" '
        'w:hAnsi="Times New Roman"/></w:rPr><w:t>Authoritative font</w:t>'
        "</w:r></w:p></w:body></w:document>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert expectation.font_family == "Times New Roman"


def test_text_style_matching_rejects_font_family_substitution() -> None:
    expectation = delivery_renderer._WordTextExpectation(
        "authoritative font", 11, (0, 0, 0), False, False, False, "left",
        font_family="Times New Roman",
    )
    candidate = delivery_renderer._PositionedText(
        0, "authoritative font", 50, 700, 11, 160, 700, 710,
        font_family="Arial",
    )

    assert not delivery_renderer._text_sizes_match([expectation], [candidate], [])


def test_text_style_matching_binds_repeatable_style_to_each_page() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "repeated header", 11, (0, 0, 0), True, False, False, "left",
            expected_page=page,
        )
        for page in (0, 1)
    ]
    candidates = [
        delivery_renderer._PositionedText(
            page, "repeated header", 50, 745, 11, 170, 745, 753,
            font_weight=700 if page == 0 else 400,
        )
        for page in (0, 1)
    ]

    assert not delivery_renderer._text_sizes_match(
        expectations, candidates, []
    )


def test_text_style_matching_rejects_first_body_vertical_relocation() -> None:
    expectation = delivery_renderer._WordTextExpectation(
        "authoritative body", 11, (0, 0, 0), False, False, False, "left",
        expected_top_offset=72,
    )
    authoritative = delivery_renderer._PositionedText(
        0, "authoritative body", 90, 709, 11, 220, 709, 717,
        page_height=792,
    )
    relocated = replace(authoritative, bottom=529, top=537)

    assert delivery_renderer._text_sizes_match(
        [expectation], [authoritative], []
    )
    assert not delivery_renderer._text_sizes_match(
        [expectation], [relocated], []
    )


def test_text_style_matching_rejects_later_body_paragraph_relocation() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "first body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True,
        ),
        delivery_renderer._WordTextExpectation(
            "second body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True,
            expected_previous_top_gap=25,
        ),
    ]
    first = delivery_renderer._PositionedText(
        0, "first body", 90, 709, 11, 180, 709, 717
    )
    normal_second = delivery_renderer._PositionedText(
        0, "second body", 90, 684, 11, 190, 684, 692
    )
    relocated_second = replace(normal_second, bottom=514, top=522)

    assert delivery_renderer._text_sizes_match(
        expectations, [first, normal_second], []
    )
    assert not delivery_renderer._text_sizes_match(
        expectations, [first, relocated_second], []
    )


def test_text_style_matching_preserves_wrapped_paragraph_flow() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "wrapped body across two lines", 11, (0, 0, 0), False, False, False,
            "left", body_flow_anchor=True,
        ),
        delivery_renderer._WordTextExpectation(
            "second body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True, expected_previous_top_gap=25,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "wrapped body across", 90, 709, 11, 500, 709, 717
        ),
        delivery_renderer._PositionedText(
            0, "two lines", 90, 694, 11, 180, 694, 702
        ),
        delivery_renderer._PositionedText(
            0, "second body", 90, 669, 11, 180, 669, 677
        ),
    ]

    assert delivery_renderer._ordered_text_blocks_match(
        ["wrapped body across two lines", "second body"], positioned, []
    )
    assert delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_text_style_matching_rejects_collapsed_blank_paragraph_flow() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "first body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True,
        ),
        delivery_renderer._WordTextExpectation(
            "second body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True, expected_previous_top_gap=62.8,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "first body", 90, 709, 11, 180, 709, 717
        ),
        delivery_renderer._PositionedText(
            0, "second body", 90, 689, 11, 180, 689, 697
        ),
    ]

    assert not delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_text_style_matching_rejects_single_collapsed_blank_paragraph() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "first body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True,
        ),
        delivery_renderer._WordTextExpectation(
            "second body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True, expected_previous_top_gap=26.4,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "first body", 90, 709, 11, 180, 709, 717
        ),
        delivery_renderer._PositionedText(
            0, "second body", 90, 695.8, 11, 180, 695.8, 703.8
        ),
    ]

    assert not delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_text_style_matching_rejects_added_blank_paragraph_flow() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "first body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True,
        ),
        delivery_renderer._WordTextExpectation(
            "second body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True, expected_previous_top_gap=13.2,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "first body", 90, 709, 11, 180, 709, 717
        ),
        delivery_renderer._PositionedText(
            0, "second body", 90, 665, 11, 180, 665, 673
        ),
    ]

    assert not delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_word_text_expectations_bind_inherited_line_spacing() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:pPr><w:pStyle w:val="Double"/></w:pPr>'
        '<w:r><w:rPr><w:sz w:val="40"/></w:rPr><w:t>First</w:t></w:r>'
        '</w:p><w:p><w:r><w:t>Second</w:t>'
        '</w:r></w:p></w:body></w:document>'
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"/>'
        '<w:style w:type="paragraph" w:styleId="Double"><w:basedOn w:val="Normal"/>'
        '<w:pPr><w:spacing w:line="480" w:lineRule="auto"/></w:pPr>'
        '</w:style></w:styles>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert expectations[0].line_height == pytest.approx(48)
    assert expectations[1].expected_previous_top_gap == pytest.approx(48)


def test_wrapped_text_accepts_bound_cross_page_word_fragmentation() -> None:
    positioned = [
        delivery_renderer._PositionedText(
            0, "alpha synthetic00", 90, 90, 11, 210, 90, 100
        ),
        delivery_renderer._PositionedText(
            1, "35 omega", 90, 700, 11, 160, 700, 710
        ),
    ]

    assert delivery_renderer._ordered_text_blocks_match(
        ["alpha synthetic0035 omega"], positioned, []
    )

    relocated = [
        positioned[0],
        delivery_renderer._PositionedText(
            1, "35 omega", 130, 700, 11, 200, 700, 710
        ),
    ]
    assert not delivery_renderer._ordered_text_blocks_match(
        ["alpha synthetic0035 omega"], relocated, []
    )


def test_centered_wrapped_paragraph_keeps_anchor_across_styled_segments() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "prefix", 11, (0, 0, 0), True, False, False, "center",
        ),
        delivery_renderer._WordTextExpectation(
            "alpha beta", 11, (0, 0, 0), False, False, False, "center",
            paragraph_continuation=True,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "prefix", 200, 700, 11, 250, 700, 710, font_weight=700
        ),
        delivery_renderer._PositionedText(
            0, "alpha", 250, 700, 11, 400, 700, 710
        ),
        delivery_renderer._PositionedText(
            0, "beta", 220, 685, 11, 380, 685, 695
        ),
    ]

    assert delivery_renderer._text_sizes_match(expectations, positioned, [])


@pytest.mark.parametrize("alignment", ("left", "both"))
def test_styled_wrap_anchor_excludes_unrelated_same_line_text(
    alignment: str,
) -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "side authority", 11, (0, 0, 0), False, False, False, "left",
        ),
        delivery_renderer._WordTextExpectation(
            "prefix", 11, (0, 0, 0), True, False, False, alignment,
        ),
        delivery_renderer._WordTextExpectation(
            "alpha beta", 11, (0, 0, 0), False, False, False, alignment,
            paragraph_continuation=True,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "side authority", 30, 702, 11, 80, 702, 710
        ),
        delivery_renderer._PositionedText(
            0, "prefix", 90, 702, 11, 140, 702, 710, font_weight=700
        ),
        delivery_renderer._PositionedText(
            0, "alpha", 90, 687, 11, 150, 687, 695
        ),
        delivery_renderer._PositionedText(
            0, "beta", 30, 672, 11, 75, 672, 680
        ),
    ]

    assert not delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_right_styled_wrap_anchor_excludes_unrelated_same_line_text() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "prefix", 11, (0, 0, 0), True, False, False, "right",
        ),
        delivery_renderer._WordTextExpectation(
            "alpha beta", 11, (0, 0, 0), False, False, False, "right",
            paragraph_continuation=True,
        ),
        delivery_renderer._WordTextExpectation(
            "side authority", 11, (0, 0, 0), False, False, False, "right",
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "prefix", 400, 702, 11, 500, 702, 710, font_weight=700
        ),
        delivery_renderer._PositionedText(
            0, "side authority", 520, 702, 11, 580, 702, 710
        ),
        delivery_renderer._PositionedText(
            0, "alpha", 440, 687, 11, 500, 687, 695
        ),
        delivery_renderer._PositionedText(
            0, "beta", 530, 672, 11, 580, 672, 680
        ),
    ]

    assert not delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_centered_table_wrap_anchor_excludes_unrelated_same_line_text() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "prefix", 11, (0, 0, 0), True, False, False, "center",
            in_table=True,
        ),
        delivery_renderer._WordTextExpectation(
            "alpha beta", 11, (0, 0, 0), False, False, False, "center",
            in_table=True,
            paragraph_continuation=True,
        ),
        delivery_renderer._WordTextExpectation(
            "side authority", 11, (0, 0, 0), False, False, False, "center",
            in_table=True,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "prefix", 250, 702, 11, 350, 702, 710, font_weight=700
        ),
        delivery_renderer._PositionedText(
            0, "side authority", 500, 702, 11, 560, 702, 710
        ),
        delivery_renderer._PositionedText(
            0, "alpha", 250, 687, 11, 362, 687, 695
        ),
        delivery_renderer._PositionedText(
            0, "beta", 350, 672, 11, 460, 672, 680
        ),
    ]

    assert not delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_body_flow_rejects_arbitrary_page_break_away_from_page_boundary() -> None:
    expectations = [
        delivery_renderer._WordTextExpectation(
            "first body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True,
        ),
        delivery_renderer._WordTextExpectation(
            "second body", 11, (0, 0, 0), False, False, False, "left",
            body_flow_anchor=True,
            expected_previous_top_gap=13.2,
        ),
    ]
    positioned = [
        delivery_renderer._PositionedText(
            0, "first body", 90, 390, 11, 180, 390, 400
        ),
        delivery_renderer._PositionedText(
            1, "second body", 90, 700, 11, 180, 700, 710
        ),
    ]

    assert not delivery_renderer._text_sizes_match(expectations, positioned, [])


def test_wrapped_text_rejects_cross_column_and_reverse_barrier_paths() -> None:
    positioned = [
        delivery_renderer._PositionedText(
            0, "right column", 350, 702, 11, 445, 702, 710
        ),
        delivery_renderer._PositionedText(
            0, "left column", 50, 687, 11, 135, 687, 695
        ),
    ]
    barrier = delivery_renderer._VerticalBarrier(0, 290, 310, 680, 725)

    assert not delivery_renderer._ordered_text_blocks_match(
        ["right column left column"], positioned, []
    )
    assert not delivery_renderer._ordered_text_blocks_match(
        ["right column left column"], positioned, [barrier]
    )


def test_wrapped_text_rejects_material_first_line_indent_relocation() -> None:
    positioned = [
        delivery_renderer._PositionedText(
            0, "alpha 223", 150, 709, 11, 197, 709, 717
        ),
        delivery_renderer._PositionedText(
            0, "beta 223", 90, 694, 11, 131, 694, 702
        ),
    ]

    assert not delivery_renderer._ordered_text_blocks_match(
        ["alpha 223 beta 223"], positioned, []
    )


def test_first_visible_body_anchor_survives_preceding_empty_paragraph() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p/><w:p><w:r><w:t>Anchored body</w:t></w:r></w:p>'
        '<w:sectPr><w:pgMar w:top="1440"/></w:sectPr>'
        "</w:body></w:document>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert expectation.expected_top_offset is not None
    assert expectation.expected_top_offset > 72


def test_first_visible_body_anchor_accounts_for_multiple_empty_paragraphs() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p/><w:p/><w:p/><w:p><w:r><w:t>Anchored body</w:t>'
        '</w:r></w:p><w:sectPr><w:pgMar w:top="1440"/></w:sectPr>'
        "</w:body></w:document>"
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:pPr><w:spacing w:after="160"/></w:pPr><w:rPr><w:sz w:val="22"/>'
        "</w:rPr></w:style></w:styles>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert expectation.expected_top_offset == pytest.approx(135.6)


def test_word_text_expectation_resolves_minor_theme_font() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Theme font</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:asciiTheme="minorHAnsi" '
        'w:hAnsiTheme="minorHAnsi"/></w:rPr></w:rPrDefault></w:docDefaults>'
        "</w:styles>"
    )
    theme = delivery_renderer.ElementTree.fromstring(
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:themeElements><a:fontScheme><a:majorFont><a:latin typeface="Cambria"/>'
        '</a:majorFont><a:minorFont><a:latin typeface="Calibri"/></a:minorFont>'
        "</a:fontScheme></a:themeElements></a:theme>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {
            "word/document.xml": document,
            "word/styles.xml": styles,
            "word/theme/theme1.xml": theme,
        }
    )

    assert expectation.font_family == "Calibri"


def test_word_text_expectation_resolves_nondefault_theme_part_name() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Theme font</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:asciiTheme="minorHAnsi"/>'
        "</w:rPr></w:rPrDefault></w:docDefaults></w:styles>"
    )
    theme = delivery_renderer.ElementTree.fromstring(
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:themeElements><a:fontScheme><a:minorFont>'
        '<a:latin typeface="Times New Roman"/></a:minorFont>'
        "</a:fontScheme></a:themeElements></a:theme>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {
            "word/document.xml": document,
            "word/styles.xml": styles,
            "word/theme/custom.xml": theme,
        }
    )

    assert expectation.font_family == "Times New Roman"


def test_word_text_expectation_resolves_minor_ascii_theme_font() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>Theme font</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    styles = delivery_renderer.ElementTree.fromstring(
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:asciiTheme="minorAscii"/>'
        "</w:rPr></w:rPrDefault></w:docDefaults></w:styles>"
    )
    theme = delivery_renderer.ElementTree.fromstring(
        '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:themeElements><a:fontScheme><a:minorFont>'
        '<a:latin typeface="Calibri"/></a:minorFont>'
        "</a:fontScheme></a:themeElements></a:theme>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {
            "word/document.xml": document,
            "word/styles.xml": styles,
            "word/theme/custom.xml": theme,
        }
    )

    assert expectation.font_family == "Calibri"


def test_word_page_geometry_preserves_size_and_orientation() -> None:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>Page geometry</w:t></w:r></w:p>'
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
        "</w:body></w:document>"
    )

    geometry = delivery_renderer._word_page_geometry(document)

    assert geometry == (612.0, 792.0)
    assert delivery_renderer._page_geometry_matches(
        geometry, [(612.0, 792.0)]
    )
    assert not delivery_renderer._page_geometry_matches(
        geometry, [(792.0, 612.0)]
    )


def test_pdf_page_coverage_rejects_unbound_blank_page() -> None:
    positioned = [
        delivery_renderer._PositionedText(
            0, "bound content", 50, 700, 11, 150, 700, 710
        )
    ]

    assert not delivery_renderer._pdf_pages_have_visible_content(
        2, positioned, [], []
    )


def test_pdf_page_coverage_rejects_page_with_only_repeatable_text() -> None:
    assert not delivery_renderer._pdf_pages_have_document_content(
        extracted_pages=["Header 223\nBody 223", "Header 223"],
        header_fragments_by_page=[["Header 223"], ["Header 223"]],
        footer_fragments_by_page=[[], []],
        image_layouts=[],
        painted_paths=[],
        page_heights=[792, 792],
    )


def test_fidelity_rejects_body_text_relocated_away_from_word_alignment() -> None:
    word = _word_text("Authoritative heading 223")
    relocated = _positioned_text_pdf(
        [[("Authoritative heading 223", 300, 700, 11, 0)]]
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, relocated)


def test_fidelity_rejects_unbound_pdf_annotation() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())
    source_pdf = _image_pdf("Synthetic", image.getvalue(), image_x=100)
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(BytesIO(source_pdf), strict=True))
    writer.add_annotation(
        0,
        FreeText(
            text="UNBOUND FINAL CLAIM",
            rect=(360, 40, 560, 110),
            font_size="18pt",
            font_color="ff0000",
            border_color="ff0000",
            background_color="ffff00",
        ),
    )
    altered = BytesIO()
    writer.write(altered)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, altered.getvalue())


def test_fidelity_rejects_unbound_visible_pdf_shading() -> None:
    image = BytesIO()
    Image.new("RGB", (8, 8), "red").save(image, "JPEG")
    word = _word_with_image_and_text("Synthetic", image.getvalue())
    source_pdf = _image_pdf("Synthetic", image.getvalue(), image_x=100)
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(BytesIO(source_pdf), strict=True))
    page = writer.pages[0]
    resources = page["/Resources"].get_object()
    function = DictionaryObject(
        {
            NameObject("/FunctionType"): NumberObject(2),
            NameObject("/Domain"): ArrayObject([FloatObject(0), FloatObject(1)]),
            NameObject("/C0"): ArrayObject(
                [FloatObject(1), FloatObject(0), FloatObject(0)]
            ),
            NameObject("/C1"): ArrayObject(
                [FloatObject(1), FloatObject(1), FloatObject(0)]
            ),
            NameObject("/N"): FloatObject(1),
        }
    )
    shading = DictionaryObject(
        {
            NameObject("/ShadingType"): NumberObject(2),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/Coords"): ArrayObject(
                [FloatObject(0), FloatObject(0), FloatObject(120), FloatObject(0)]
            ),
            NameObject("/Function"): writer._add_object(function),
            NameObject("/Extend"): ArrayObject(
                [BooleanObject(True), BooleanObject(True)]
            ),
        }
    )
    resources[NameObject("/Shading")] = DictionaryObject(
        {NameObject("/ShAudit"): writer._add_object(shading)}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        page.get_contents().get_data()
        + b"\nq 420 40 120 90 re W n 1 0 0 1 420 40 cm /ShAudit sh Q\n"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    altered = BytesIO()
    writer.write(altered)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, altered.getvalue())


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


def test_fidelity_rejects_detail_budget_trading_patch_exchange() -> None:
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
    candidate_image = source_image.filter(ImageFilter.GaussianBlur(1))
    first_patch = source_image.crop((7, 23, 9, 25))
    second_patch = source_image.crop((17, 7, 19, 9))
    candidate_image.paste(second_patch, (7, 23))
    candidate_image.paste(first_patch, (17, 7))

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


def test_fidelity_rejects_balanced_padding_hiding_marker_swap() -> None:
    random = Random(0)
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (random.randrange(256), random.randrange(256), random.randrange(256))
            for _ in range(32 * 32)
        ]
    )
    first_color = (158, 98, 100)
    second_color = (98, 158, 100)
    for y in range(2):
        for x in range(2):
            source_image.putpixel((4 + x, 4 + y), first_color)
            source_image.putpixel((22 + x, 22 + y), second_color)

    candidate_image = source_image.copy()
    for y in range(32):
        for x in range(32):
            if (4 <= x < 6 and 4 <= y < 6) or (22 <= x < 24 and 22 <= y < 24):
                continue
            pixel = candidate_image.getpixel((x, y))
            delta = 20 if (x + y) % 2 == 0 else -20
            candidate_image.putpixel(
                (x, y),
                tuple(max(0, min(255, channel + delta)) for channel in pixel),
            )
    for y in range(2):
        for x in range(2):
            candidate_image.putpixel((4 + x, 4 + y), second_color)
            candidate_image.putpixel((22 + x, 22 + y), first_color)

    source = BytesIO()
    source_image.save(source, "PNG")
    candidate = BytesIO()
    candidate_image.save(candidate, "JPEG", quality=95, subsampling=0)
    word = _word_with_image_and_text("Synthetic", source.getvalue())

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _image_pdf("Synthetic", candidate.getvalue(), image_x=100),
        )


def test_fidelity_rejects_low_amplitude_padding_hiding_marker_swap() -> None:
    random = Random(19)
    source_image = Image.new("RGB", (32, 32))
    source_image.putdata(
        [
            (
                random.randrange(40, 216),
                random.randrange(40, 216),
                random.randrange(40, 216),
            )
            for _ in range(32 * 32)
        ]
    )
    first_color = (154, 106, 100)
    second_color = (106, 154, 100)
    for y in range(2):
        for x in range(2):
            source_image.putpixel((4 + x, 4 + y), first_color)
            source_image.putpixel((22 + x, 22 + y), second_color)

    candidate_image = source_image.copy()
    for y in range(32):
        for x in range(32):
            if (4 <= x < 6 and 4 <= y < 6) or (22 <= x < 24 and 22 <= y < 24):
                continue
            delta = 6 if (x + y) % 2 == 0 else -6
            candidate_image.putpixel(
                (x, y),
                tuple(channel + delta for channel in candidate_image.getpixel((x, y))),
            )
    for y in range(2):
        for x in range(2):
            candidate_image.putpixel((4 + x, 4 + y), second_color)
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


# --- Phase C F-05: table structure must fail closed, never drop expectations ---

# Adjudication note: the Claude diagnostic reported F-05 as a reproduced false
# positive (an altered PDF passing because the table was dropped).  That did not
# reproduce: with the table dropped the flattened and row-swapped PDFs are still
# rejected by the other oracles.  The code gap is real, the exploit is not
# demonstrated, so F-05 is carried as an invariant-completeness defect.  These
# tests therefore pin the *policy*: an unresolvable table must fail as a
# resolution error, not be silently excluded and rejected by accident elsewhere.


def _word_table_document(table_markup: str) -> bytes:
    output = BytesIO()
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{table_markup}</w:body></w:document>"
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


_WELL_FORMED_TABLE = (
    "<w:tbl>"
    "<w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
    "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr>"
    "<w:tr><w:tc><w:p><w:r><w:t>Cell C</w:t></w:r></w:p></w:tc>"
    "<w:tc><w:p><w:r><w:t>Cell D</w:t></w:r></w:p></w:tc></w:tr>"
    "</w:tbl>"
)
_FLATTENED_TABLE_PDF = "Cell A Cell B Cell C Cell D"


def test_well_formed_table_is_bound_and_rejects_flattened_pdf() -> None:
    """Control: a resolvable table is bound, so the mismatch is a fidelity failure."""
    with pytest.raises(ValueError, match="does not faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table_document(_WELL_FORMED_TABLE),
            _parseable_text_pdf(_FLATTENED_TABLE_PDF),
        )


@pytest.mark.parametrize(
    "table_markup",
    (
        _WELL_FORMED_TABLE.replace(
            "<w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>",
            '<w:tc><w:tcPr><w:gridSpan w:val="nao-numerico"/></w:tcPr>'
            "<w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>",
        ),
        _WELL_FORMED_TABLE.replace(
            "<w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>",
            '<w:tc><w:tcPr><w:gridSpan w:val="0"/></w:tcPr>'
            "<w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>",
        ),
        _WELL_FORMED_TABLE.replace(
            "<w:tr><w:tc><w:p><w:r><w:t>Cell C</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>Cell D</w:t></w:r></w:p></w:tc></w:tr>",
            "<w:tr><w:tc><w:p><w:r><w:t>Cell C</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>Cell D</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>Cell E</w:t></w:r></w:p></w:tc></w:tr>",
        ),
        '<w:tbl><w:tr><w:tc><w:tcPr><w:vMerge w:val="continue"/></w:tcPr>'
        "<w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
        '<w:tc><w:tcPr><w:vMerge w:val="continue"/></w:tcPr>'
        "<w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>",
    ),
    ids=(
        "invalid_grid_span",
        "zero_grid_span",
        "row_column_count_mismatch",
        "orphan_vertical_merge_continuation",
    ),
)
def test_unresolvable_table_structure_fails_closed(table_markup: str) -> None:
    """RED F-05: these shapes were dropped from the oracle instead of rejected."""
    with pytest.raises(ValueError, match="cannot be verified"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table_document(table_markup),
            _parseable_text_pdf(_FLATTENED_TABLE_PDF),
        )


def test_nested_table_cell_properties_are_not_read_from_the_inner_table() -> None:
    """RED F-05: recursive lookup let an inner cell govern the outer cell geometry."""
    markup = (
        "<w:tbl><w:tr>"
        "<w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p>"
        "<w:tbl><w:tr>"
        '<w:tc><w:tcPr><w:gridSpan w:val="3"/></w:tcPr>'
        "<w:p><w:r><w:t>Inner X</w:t></w:r></w:p></w:tc>"
        "</w:tr></w:tbl></w:tc>"
        "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc>"
        "</w:tr></w:tbl>"
    )
    # The outer row must resolve to two columns; the inner gridSpan is not its own.
    with pytest.raises(ValueError, match="does not faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table_document(markup),
            _parseable_text_pdf("Cell A Inner X Cell B"),
        )


def test_outer_table_style_is_not_inherited_from_a_nested_table() -> None:
    """RED F-05: recursive tblStyle lookup let an inner table style the outer one."""
    markup = (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p>"
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/></w:tblPr>'
        "<w:tr><w:tc><w:p><w:r><w:t>Inner X</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:tc><w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{markup}</w:body></w:document>"
    )
    outer = next(delivery_renderer._iter_named(document, "tbl"))
    inner = [item for item in delivery_renderer._iter_named(document, "tbl")][1]

    assert delivery_renderer._table_style_id(outer) is None
    assert delivery_renderer._table_style_id(inner) == "TableGrid"


# --- Phase C F-04: theme font aliases distinguish ABSENT from UNRESOLVED ---


_THEME_PART = (
    '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    "<a:themeElements><a:fontScheme>"
    '<a:majorFont><a:latin typeface="Cambria"/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Calibri"/></a:minorFont>'
    "</a:fontScheme></a:themeElements></a:theme>"
)


def _theme_roots(run_fonts: str, *, with_theme: bool = True) -> dict:
    document = delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:rPr>{run_fonts}</w:rPr>"
        "<w:t>Tema 223</w:t></w:r></w:p></w:body></w:document>"
    )
    roots = {"word/document.xml": document}
    if with_theme:
        roots["word/theme/theme1.xml"] = delivery_renderer.ElementTree.fromstring(_THEME_PART)
    return roots


def test_latin_theme_aliases_resolve_to_the_same_family() -> None:
    """RED F-04/E2: minorAscii + minorHAnsi name one family, not a conflict."""
    [expectation] = delivery_renderer._word_text_expectations(
        _theme_roots('<w:rFonts w:asciiTheme="minorAscii" w:hAnsiTheme="minorHAnsi"/>')
    )
    assert expectation.font_family == "Calibri"


@pytest.mark.parametrize(
    "alias", ("minorAscii", "minorHAnsi", "majorAscii", "majorHAnsi")
)
def test_each_latin_theme_alias_resolves(alias: str) -> None:
    [expectation] = delivery_renderer._word_text_expectations(
        _theme_roots(f'<w:rFonts w:asciiTheme="{alias}"/>')
    )
    assert expectation.font_family == ("Cambria" if alias.startswith("major") else "Calibri")


def test_genuinely_conflicting_latin_theme_families_fail_closed() -> None:
    with pytest.raises(ValueError, match="theme"):
        delivery_renderer._word_text_expectations(
            _theme_roots('<w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="majorHAnsi"/>')
        )


@pytest.mark.parametrize(
    "alias",
    ("minorEastAsia", "majorEastAsia", "minorBidi", "majorBidi"),
)
def test_non_latin_theme_slots_fail_closed(alias: str) -> None:
    """RED F-04/E3: these resolved to None, silently dropping the font check."""
    with pytest.raises(ValueError, match="theme"):
        delivery_renderer._word_text_expectations(
            _theme_roots(f'<w:rFonts w:asciiTheme="{alias}"/>')
        )


def test_unknown_theme_alias_fails_closed() -> None:
    with pytest.raises(ValueError, match="theme"):
        delivery_renderer._word_text_expectations(
            _theme_roots('<w:rFonts w:asciiTheme="sintetico"/>')
        )


def test_theme_alias_without_a_theme_part_fails_closed() -> None:
    """An alias that cannot be resolved is UNRESOLVED, never ABSENT."""
    with pytest.raises(ValueError, match="theme"):
        delivery_renderer._word_text_expectations(
            _theme_roots('<w:rFonts w:asciiTheme="minorHAnsi"/>', with_theme=False)
        )


def test_absent_theme_reference_is_not_an_error() -> None:
    [expectation] = delivery_renderer._word_text_expectations(
        _theme_roots('<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/>')
    )
    assert expectation.font_family == "Arial"


# --- Phase C F-03/F-08: vertical flow and native wrap regression matrices ---
#
# Adjudication: both findings were raised against bdb6135 and are already
# repaired at 7a8486b (the blank-gap tolerance moved from max(48, size*3) to
# max(6, size*0.75), and _fragment_sequence_end grew a paragraph wrap anchor).
# Verified empirically, not by reading.  These matrices lock the repairs in.
# Real font-metric variation (Calibri/Times/Arial line pitch) is not observable
# through a synthetic Helvetica PDF and stays on the native Word matrix (N-09).


def _word_flow_document(body: str) -> bytes:
    output = BytesIO()
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
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


def _blank_paragraph_word(blanks: int, *, spacing: str = "") -> bytes:
    properties = f"<w:pPr>{spacing}</w:pPr>" if spacing else ""
    run = '<w:r><w:rPr><w:sz w:val="22"/></w:rPr>'
    return _word_flow_document(
        f"<w:p>{properties}{run}<w:t>Primeiro</w:t></w:r></w:p>"
        + f"<w:p>{properties}</w:p>" * blanks
        + f"<w:p>{properties}{run}<w:t>Segundo</w:t></w:r></w:p>"
    )


def _two_line_pdf(gap_pitches: float, *, pitch: float = 13.2) -> bytes:
    return _positioned_text_pdf(
        [
            [
                ("Primeiro", 50.0, 780.0, 11.0, 0),
                ("Segundo", 50.0, 780.0 - pitch * gap_pitches, 11.0, 0),
            ]
        ]
    )


@pytest.mark.parametrize("blanks", (1, 2, 3, 5))
def test_material_empty_paragraphs_are_quantised(blanks: int) -> None:
    word = _blank_paragraph_word(blanks)

    delivery_renderer._validate_pdf_fidelity(word, _two_line_pdf(1 + blanks))
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, _two_line_pdf(1))


@pytest.mark.parametrize("blanks", (1, 3))
def test_empty_paragraph_spacing_is_included_in_the_expected_gap(blanks: int) -> None:
    spacing = '<w:spacing w:before="120" w:after="120"/>'
    word = _blank_paragraph_word(blanks, spacing=spacing)
    # 120 twips before + after == 6pt + 6pt per paragraph, on top of the line box.
    extra = (blanks + 1) * 12.0

    delivery_renderer._validate_pdf_fidelity(
        word,
        _positioned_text_pdf(
            [
                [
                    ("Primeiro", 50.0, 780.0, 11.0, 0),
                    ("Segundo", 50.0, 780.0 - (13.2 * (1 + blanks) + extra), 11.0, 0),
                ]
            ]
        ),
    )
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word, _two_line_pdf(1))


@pytest.mark.parametrize("line_count", (2, 3, 4))
def test_native_line_wrap_is_accepted(line_count: int) -> None:
    lines = ["Alpha Beta", "Gamma Delta", "Epsilon Zeta", "Eta Theta"][:line_count]
    word = _word_flow_document(
        '<w:p><w:r><w:rPr><w:sz w:val="22"/></w:rPr>'
        f"<w:t>{' '.join(lines)}</w:t></w:r></w:p>"
    )
    fragments = [
        (line, 50.0, 780.0 - 13.2 * index, 11.0, 0) for index, line in enumerate(lines)
    ]

    delivery_renderer._validate_pdf_fidelity(word, _positioned_text_pdf([fragments]))


def test_wrapped_continuation_displaced_several_pitches_is_rejected() -> None:
    word = _word_flow_document(
        '<w:p><w:r><w:rPr><w:sz w:val="22"/></w:rPr>'
        "<w:t>Alpha Beta Gamma Delta</w:t></w:r></w:p>"
    )

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _positioned_text_pdf(
                [
                    [
                        ("Alpha Beta", 50.0, 780.0, 11.0, 0),
                        ("Gamma Delta", 50.0, 780.0 - 13.2 * 4, 11.0, 0),
                    ]
                ]
            ),
        )


# --- Phase C F-13: hidden text has no visible authority ---


def _word_with_hidden_run(hidden_markup: str, *, styles: str = "") -> bytes:
    output = BytesIO()
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p>"
        '<w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>Visivel</w:t></w:r>'
        f"{hidden_markup}"
        "</w:p></w:body></w:document>"
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
        if styles:
            package.writestr("word/styles.xml", styles)
    return output.getvalue()


_DIRECT_HIDDEN_RUN = (
    '<w:r><w:rPr><w:sz w:val="22"/><w:vanish/></w:rPr><w:t>Oculto</w:t></w:r>'
)
_STYLED_HIDDEN_RUN = (
    '<w:r><w:rPr><w:rStyle w:val="Escondido"/><w:sz w:val="22"/></w:rPr>'
    "<w:t>Oculto</w:t></w:r>"
)
_HIDDEN_CHARACTER_STYLES = (
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:style w:type="character" w:styleId="Escondido"><w:rPr><w:vanish/></w:rPr></w:style>'
    "</w:styles>"
)


@pytest.mark.parametrize(
    ("hidden_markup", "styles"),
    (
        (_DIRECT_HIDDEN_RUN, ""),
        (_STYLED_HIDDEN_RUN, _HIDDEN_CHARACTER_STYLES),
    ),
    ids=("direct_vanish", "inherited_vanish"),
)
def test_hidden_text_is_not_expected_in_the_derived_pdf(
    hidden_markup: str, styles: str
) -> None:
    """RED F-13: hidden runs were demanded from a PDF that correctly omits them."""
    word = _word_with_hidden_run(hidden_markup, styles=styles)

    delivery_renderer._validate_pdf_fidelity(
        word, _positioned_text_pdf([[("Visivel", 50.0, 780.0, 11.0, 0)]])
    )


@pytest.mark.parametrize(
    ("hidden_markup", "styles"),
    (
        (_DIRECT_HIDDEN_RUN, ""),
        (_STYLED_HIDDEN_RUN, _HIDDEN_CHARACTER_STYLES),
    ),
    ids=("direct_vanish", "inherited_vanish"),
)
def test_rendered_hidden_text_is_rejected(hidden_markup: str, styles: str) -> None:
    """A PDF that reveals hidden text is not a faithful rendering."""
    word = _word_with_hidden_run(hidden_markup, styles=styles)

    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            word,
            _positioned_text_pdf(
                [
                    [
                        ("Visivel", 50.0, 780.0, 11.0, 0),
                        ("Oculto", 100.0, 780.0, 11.0, 0),
                    ]
                ]
            ),
        )


# --- Phase C F-14: legacy tblLook mask and named attributes must agree ---


def _table_look(markup: str):
    return delivery_renderer.ElementTree.fromstring(
        '<w:tblLook xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        f"{markup}/>"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("firstRow", True),
        ("firstColumn", True),
        ("lastRow", False),
        ("noHBand", False),
        ("noVBand", True),
    ),
)
def test_legacy_table_look_mask_is_decoded(name: str, expected: bool) -> None:
    look = _table_look('w:val="04A0"')
    assert delivery_renderer._table_look_flag(look, name) is expected


def test_table_look_mask_and_named_attribute_conflict_fails_closed() -> None:
    look = _table_look('w:val="0020" w:firstRow="0"')
    with pytest.raises(ValueError, match="conflicting Word table-look"):
        delivery_renderer._table_look_flag(look, "firstRow")


def test_table_look_mask_and_named_attribute_agreement_is_accepted() -> None:
    look = _table_look('w:val="0020" w:firstRow="1"')
    assert delivery_renderer._table_look_flag(look, "firstRow") is True


def test_malformed_table_look_mask_fails_closed() -> None:
    with pytest.raises(ValueError, match="invalid Word table-look mask"):
        delivery_renderer._table_look_flag(_table_look('w:val="zz"'), "firstRow")


def test_absent_table_look_uses_the_documented_default() -> None:
    assert delivery_renderer._table_look_flag(None, "firstRow", default=True) is True
    assert delivery_renderer._table_look_flag(None, "noHBand") is False


# --- Phase C F-09: bookmark occurrence uses one tokenisation on both sides ---


def _link_document(body: str):
    return delivery_renderer.ElementTree.fromstring(
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{body}</w:body></w:document>"
    )


_GO = '<w:p><w:hyperlink w:anchor="Alvo"><w:r><w:t>Ir</w:t></w:r></w:hyperlink></w:p>'


def test_single_character_bookmark_target_counts_occurrences_not_letters() -> None:
    """RED F-09: prefix.count() counted every letter "i", not every occurrence."""
    document = _link_document(
        "<w:p><w:r><w:t>Minhas linhas iniciais</w:t></w:r></w:p>"
        '<w:p><w:bookmarkStart w:id="1" w:name="Alvo"/>'
        "<w:r><w:t>I</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>' + _GO
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_text == "i"
    assert expectation.target_occurrence == 0


def test_bookmark_spanning_two_paragraphs_is_supported() -> None:
    """RED F-09: a bookmark crossing a paragraph boundary rejected the document."""
    document = _link_document(
        '<w:p><w:bookmarkStart w:id="1" w:name="Alvo"/>'
        "<w:r><w:t>Primeira parte</w:t></w:r></w:p>"
        '<w:p><w:r><w:t>segunda parte</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>' + _GO
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_text == "primeira parte segunda parte"


def test_bookmark_target_separated_by_a_tab_keeps_its_tokens_apart() -> None:
    """RED F-09: w:tab contributed nothing, fusing "Anexo" and "I" into "anexoi"."""
    document = _link_document(
        '<w:p><w:bookmarkStart w:id="1" w:name="Alvo"/>'
        "<w:r><w:t>Anexo</w:t><w:tab/><w:t>I</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>' + _GO
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_text == "anexo i"


def test_bookmark_target_separated_by_a_break_keeps_its_tokens_apart() -> None:
    document = _link_document(
        '<w:p><w:bookmarkStart w:id="1" w:name="Alvo"/>'
        "<w:r><w:t>Anexo</w:t><w:br/><w:t>II</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>' + _GO
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_text == "anexo ii"


def test_text_inside_a_textbox_is_not_counted_twice() -> None:
    """RED F-09: nested paragraphs were visited by the outer walk and again alone."""
    document = _link_document(
        "<w:p><w:r><w:t>Anexo</w:t></w:r>"
        "<w:r><w:pict><w:txbxContent><w:p><w:r><w:t>Anexo</w:t></w:r></w:p>"
        "</w:txbxContent></w:pict></w:r></w:p>"
        '<w:p><w:bookmarkStart w:id="1" w:name="Alvo"/>'
        "<w:r><w:t>Anexo</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>' + _GO
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_text == "anexo"
    assert expectation.target_occurrence == 2


def test_whitespace_run_before_the_bookmark_does_not_shift_the_occurrence() -> None:
    document = _link_document(
        "<w:p><w:r><w:t>Anexo</w:t></w:r></w:p>"
        '<w:p><w:r><w:t xml:space="preserve">   </w:t></w:r>'
        '<w:bookmarkStart w:id="1" w:name="Alvo"/>'
        "<w:r><w:t>Anexo</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>' + _GO
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_text == "anexo"
    assert expectation.target_occurrence == 1


def test_internal_link_resolves_the_second_of_two_identical_targets() -> None:
    """The ordinal must select the bookmarked occurrence, not the first lexical one."""
    word = BytesIO()
    with ZipFile(word, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p>'
            "<w:r><w:t>Anexo I</w:t></w:r>"
            '<w:r><w:t xml:space="preserve">   </w:t></w:r>'
            '<w:bookmarkStart w:id="1" w:name="Segundo"/>'
            "<w:r><w:t>Anexo I</w:t></w:r>"
            '<w:bookmarkEnd w:id="1"/></w:p><w:p>'
            '<w:hyperlink w:anchor="Segundo"><w:r><w:t>Ir</w:t></w:r></w:hyperlink>'
            "</w:p></w:body></w:document>",
        )
    source_pdf = _positioned_text_pdf(
        [[
            ("Anexo I", 50, 700, 11, 0),
            ("Anexo I", 100, 700, 11, 0),
            ("Ir", 50, 685, 11, 0),
        ]]
    )

    def candidate(destination_x: float) -> bytes:
        writer = PdfWriter()
        writer.clone_document_from_reader(PdfReader(BytesIO(source_pdf), strict=True))
        page = writer.pages[0]
        annotation = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject(
                    [FloatObject(48), FloatObject(680), FloatObject(70), FloatObject(700)]
                ),
                NameObject("/Dest"): ArrayObject(
                    [
                        page.indirect_reference,
                        NameObject("/XYZ"),
                        FloatObject(destination_x),
                        FloatObject(710),
                        NullObject(),
                    ]
                ),
            }
        )
        page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    delivery_renderer._validate_pdf_fidelity(word.getvalue(), candidate(100))
    with pytest.raises(ValueError, match="faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(word.getvalue(), candidate(50))


# --- Phase C F-21: narrow glyphs are observable ---
#
# Found while building the F-09 duplicate-target fixture, not reported by the
# diagnostic review.  _raster_region_is_observably_painted pads the crop box by
# 1pt per side to tolerate rasterisation offsets, then measures the required
# axis coverage against that padded width.  The padding does not add ink, so for
# a glyph narrower than about 2pt of ink the 0.50 threshold is unreachable in
# any font.  Roman numerals make this ordinary in judicial reports.


@pytest.mark.parametrize(
    "text",
    ("Anexo I", "Inciso I", "Anexo II", "Item l", "Peca i", "Anexo I - Planta"),
)
def test_narrow_glyphs_do_not_read_as_nonvisible(text: str) -> None:
    pdf = _positioned_text_pdf([[(text, 50.0, 700.0, 11.0, 0)]])

    *_, unsafe = delivery_renderer._pdfium_visible_layout(pdf)

    assert unsafe is False


def test_genuinely_invisible_text_is_still_detected() -> None:
    """Control: render mode 3 (invisible) must keep failing."""
    pdf = _positioned_text_pdf([[("Anexo I", 50.0, 700.0, 11.0, 3)]])

    *_, unsafe = delivery_renderer._pdfium_visible_layout(pdf)

    assert unsafe is True


# --- Phase C F-09b: hyperlinked cross-reference fields produce link annotations ---
#
# Reproduced on Word 16.0.20326 first, as section 18 requires: a PAGEREF field
# with the r"\h" switch makes Word emit a /Link annotation while the package
# carries no w:hyperlink element at all, so the annotation count never matched
# and a faithful document was rejected.  TOC entries need no new handling: Word
# writes them as w:hyperlink inside the field result, which was already read.


def _cross_reference_document(switch: str = r" \h "):
    run = '<w:r><w:rPr><w:sz w:val="24"/></w:rPr>'
    return _link_document(
        '<w:p><w:bookmarkStart w:id="1" w:name="Secao1"/>'
        + run
        + "<w:t>Secao Um</w:t></w:r>"
        + '<w:bookmarkEnd w:id="1"/></w:p><w:p>'
        + run
        + '<w:fldChar w:fldCharType="begin"/></w:r>'
        + run
        + '<w:instrText xml:space="preserve"> PAGEREF Secao1'
        + switch
        + "</w:instrText></w:r>"
        + run
        + '<w:fldChar w:fldCharType="separate"/></w:r>'
        + run
        + "<w:t>7</w:t></w:r>"
        + run
        + '<w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )


def test_hyperlinked_cross_reference_field_becomes_a_link_expectation() -> None:
    [expectation] = delivery_renderer._word_internal_link_expectations(
        _cross_reference_document()
    )

    assert expectation.text == "7"
    assert expectation.target_text == "secao um"
    assert expectation.target_occurrence == 0


def test_cross_reference_without_the_hyperlink_switch_creates_no_expectation() -> None:
    assert delivery_renderer._word_internal_link_expectations(
        _cross_reference_document(switch=" ")
    ) == []


def test_simple_field_cross_reference_becomes_a_link_expectation() -> None:
    document = _link_document(
        '<w:p><w:bookmarkStart w:id="1" w:name="Secao1"/>'
        '<w:r><w:t>Secao Um</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>'
        r'<w:p><w:fldSimple w:instr=" REF Secao1 \h ">'
        "<w:r><w:t>Secao Um</w:t></w:r></w:fldSimple></w:p>"
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.text == "secao um"
    assert expectation.target_text == "secao um"


# --- Phase C F-22: canonical injection must preserve package markup ---
#
# Reproduced on Word 16.0.20326 during the OPC adjudication: a template authored
# in real Word binds and renders, but the candidate produced from it cannot be
# opened by Word at all.  _inject_canonical_report re-serialised the whole
# word/document.xml with ElementTree, which drops namespace prefixes nothing in
# the tree happens to use, while mc:Ignorable keeps naming them.  A Markup
# Compatibility attribute referring to an undeclared prefix makes the part
# invalid.  Pre-existing; found by driving the real product template path.


_WORD_SHAPED_DOCUMENT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document '
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" '
    'mc:Ignorable="w14 w15">'
    "<w:body>"
    '<w:p w14:paraId="5C0E038D"><w:r><w:t>Cabecalho</w:t></w:r></w:p>'
    "<w:sdt><w:sdtPr>"
    '<w:tag w:val="CANONICAL_REPORT"/>'
    "</w:sdtPr><w:sdtContent>"
    "<w:p><w:r><w:t>substituir</w:t></w:r></w:p>"
    "</w:sdtContent></w:sdt>"
    "<w:sectPr/></w:body></w:document>"
)


def _word_shaped_bound_artifact() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        package.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/'
            '2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        package.writestr("word/document.xml", _WORD_SHAPED_DOCUMENT)
    return output.getvalue()


def _injected_document(report: object) -> str:
    injected = delivery_renderer._inject_canonical_report(
        _word_shaped_bound_artifact(), report
    )
    with ZipFile(BytesIO(injected)) as package:
        return package.read("word/document.xml").decode("utf-8")


def _approved_report():
    root = Path(__file__).parents[1] / "tests/fixtures"
    return report_snapshot_from_mapping(
        json.loads((root / "report-snapshot-v1.json").read_text(encoding="utf-8"))
    )


def test_canonical_injection_keeps_every_ignorable_prefix_declared() -> None:
    """RED F-22: mc:Ignorable named prefixes the serialiser had dropped."""
    document = _injected_document(_approved_report())

    ignorable = delivery_renderer.re.search(r'mc:Ignorable="([^"]*)"', document)
    assert ignorable is not None
    for prefix in ignorable.group(1).split():
        assert f'xmlns:{prefix}="' in document, f"{prefix} is named but not declared"


def test_canonical_injection_preserves_namespaced_attributes() -> None:
    document = _injected_document(_approved_report())

    assert 'w14:paraId="5C0E038D"' in document
    assert "ns0:" not in document


def test_canonical_injection_still_replaces_the_control_content() -> None:
    document = _injected_document(_approved_report())

    assert "substituir" not in document
    assert "REPORT_SNAPSHOT_SHA256" in document
    assert document.count("CANONICAL_REPORT") >= 1


def test_blank_table_row_is_resolvable() -> None:
    """A spacer row carries no text anchor but its geometry is fully known."""
    markup = _WELL_FORMED_TABLE.replace(
        "</w:tbl>",
        "<w:tr><w:tc><w:p/></w:tc><w:tc><w:p/></w:tc></w:tr></w:tbl>",
    )
    with pytest.raises(ValueError, match="does not faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table_document(markup),
            _parseable_text_pdf(_FLATTENED_TABLE_PDF),
        )


def test_row_with_grid_before_is_resolvable() -> None:
    """Word writes gridBefore whenever a row does not start at column one."""
    markup = (
        "<w:tbl><w:tblGrid><w:gridCol w:w=\"2000\"/><w:gridCol w:w=\"2000\"/></w:tblGrid>"
        "<w:tr><w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>Cell B</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:trPr><w:gridBefore w:val=\"1\"/></w:trPr>"
        "<w:tc><w:p><w:r><w:t>Cell C</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    )
    with pytest.raises(ValueError, match="does not faithfully represent"):
        delivery_renderer._validate_pdf_fidelity(
            _word_table_document(markup), _parseable_text_pdf("Cell A Cell B Cell C")
        )


# --- Phase C §27 internal review: reviewer and auditor findings ---

_MAIN_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _doc(body: str):
    return delivery_renderer.ElementTree.fromstring(
        f"<w:document {_MAIN_NS}><w:body>{body}</w:body></w:document>"
    )


def _frag(text: str, x: float, right: float, top: float = 100.0, page: int = 0):
    return delivery_renderer._PositionedText(
        page, text, x, top, 10.0, right, top - 8.0, top
    )


def test_superseded_tracked_formatting_is_not_read_as_current() -> None:
    """P0: w:rPrChange records the formatting a change replaced; Word ignores it.

    A recursive property lookup found the superseded w:vanish and read a visible
    run as hidden, and hidden runs carry no expectation at all, so deleting that
    text from the PDF became undetectable.
    """
    paragraph = next(
        delivery_renderer._iter_named(
            _doc(
                "<w:p><w:r><w:rPr>"
                '<w:rPrChange w:id="1" w:author="a" w:date="d">'
                "<w:rPr><w:vanish/></w:rPr></w:rPrChange>"
                "</w:rPr><w:t>TEXTO VISIVEL</w:t></w:r></w:p>"
            ),
            "p",
        )
    )

    text = delivery_renderer._visible_paragraph_text(
        paragraph, delivery_renderer._hidden_run_resolver(None)
    )

    assert text == "TEXTO VISIVEL"


def test_current_formatting_still_hides_a_genuinely_hidden_run() -> None:
    paragraph = next(
        delivery_renderer._iter_named(
            _doc("<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>OCULTO</w:t></w:r></w:p>"),
            "p",
        )
    )

    assert (
        delivery_renderer._visible_paragraph_text(
            paragraph, delivery_renderer._hidden_run_resolver(None)
        )
        == ""
    )


def test_text_box_content_is_counted_once() -> None:
    """A text box lives in a run of its container, and is a paragraph of its own."""
    document = _doc(
        "<w:p><w:r><w:t>OUTER</w:t></w:r>"
        "<w:r><w:pict><w:txbxContent><w:p><w:r><w:t>BOXED</w:t></w:r></w:p>"
        "</w:txbxContent></w:pict></w:r></w:p>"
    )
    hidden = delivery_renderer._hidden_run_resolver(None)

    fragments = [
        delivery_renderer._visible_paragraph_text(paragraph, hidden)
        for paragraph in delivery_renderer._iter_named(document, "p")
    ]

    assert fragments == ["OUTER", "BOXED"]


def test_word_toc_entry_produces_one_link_expectation() -> None:
    """Word wraps the PAGEREF field of a TOC entry in the hyperlink itself."""
    document = _doc(
        '<w:p><w:bookmarkStart w:id="1" w:name="_Toc1"/>'
        "<w:r><w:t>Introducao</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>'
        '<w:p><w:hyperlink w:anchor="_Toc1">'
        "<w:r><w:t>Introducao</w:t></w:r><w:r><w:tab/></w:r>"
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGEREF _Toc1 \\h </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>3</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        "</w:hyperlink></w:p>"
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    # The tab separates the title from the page number, as it does in the PDF.
    assert expectation.text == "introducao 3"


def test_hidden_run_does_not_shift_the_link_occurrence_ordinal() -> None:
    document = _doc(
        "<w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>Anexo A</w:t></w:r></w:p>"
        '<w:p><w:bookmarkStart w:id="1" w:name="B1"/>'
        "<w:r><w:t>Anexo A</w:t></w:r>"
        '<w:bookmarkEnd w:id="1"/></w:p>'
        '<w:p><w:hyperlink w:anchor="B1"><w:r><w:t>Ir</w:t></w:r></w:hyperlink></w:p>'
    )

    [expectation] = delivery_renderer._word_internal_link_expectations(document)

    assert expectation.target_occurrence == 0


def test_target_split_across_text_objects_is_still_one_occurrence() -> None:
    """Word emits a new text object at every run boundary, mid-word included."""
    split = [_frag("An", 0.0, 20.0), _frag("exo A", 20.0, 60.0)]

    assert delivery_renderer._positioned_target_locations("Anexo A", split, []) == [
        (0, 0.0, 100.0)
    ]


def test_adjacent_occurrences_are_not_fused_into_one_token() -> None:
    separated = [_frag("Anexo A", 0.0, 60.0), _frag("Anexo A", 100.0, 160.0)]

    assert len(
        delivery_renderer._positioned_target_locations("Anexo A", separated, [])
    ) == 2


def test_a_distant_rule_does_not_remove_an_occurrence() -> None:
    """Dropping an occurrence silently renumbers every later ordinal."""
    fragments = [_frag("Anexo A", 0.0, 60.0)]
    distant_rule = [delivery_renderer._VerticalBarrier(0, 10.0, 12.0, 10.0, 20.0)]

    assert delivery_renderer._positioned_target_locations(
        "Anexo A", fragments, distant_rule
    ) == [(0, 0.0, 100.0)]


def test_repeatable_matching_reports_the_fragments_it_consumed() -> None:
    """Header exclusion is by provenance, not by a geometric slab of the page.

    A 25% band also swallows ordinary body text near the top margin, which
    renumbered internal-link occurrences and rejected faithful documents.
    """
    header = _frag("Cabecalho", 50.0, 140.0, top=760.0)
    body_near_margin = _frag("Texto do corpo", 50.0, 200.0, top=700.0)
    consumed: set[int] = set()

    matched = delivery_renderer._repeatable_text_matches(
        header_fragments_by_page=[["Cabecalho"]],
        footer_fragments_by_page=[[]],
        positioned=[header, body_near_margin],
        page_heights=[792.0],
        consumed=consumed,
    )

    assert matched is True
    assert id(header) in consumed
    assert id(body_near_margin) not in consumed


def test_body_field_result_carries_a_typography_expectation() -> None:
    """Its text is already required verbatim, so its style must be checked too."""
    document = _doc(
        '<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>PLAIN </w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> REF _Ref1 \\h </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>CROSSREF</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert "crossref" in " ".join(item.text for item in expectations)


# --- Phase C deferred hypothesis: BODY_TABLE_RELATIVE_ORDER_NOT_BOUND ---


@pytest.mark.skip(
    reason=(
        "HYPOTHESIS_REQUIRING_REPRODUCTION - BODY_TABLE_RELATIVE_ORDER_NOT_BOUND. "
        "Raised by SYSTEMIC_AUDITOR at 1a5b71c; not promoted to a defect because no "
        "discriminating fixture exists yet. "
        "CAUSAL ARGUMENT: _validate_pdf_fidelity checks two order invariants against "
        "two independent cursors. document_fragments deliberately excludes paragraphs "
        "that belong to a w:tbl, and _ordered_text_blocks_match advances its cursor "
        "over those non-table paragraphs only; _table_rows_match advances a separate "
        "cursor over table rows only. token_counts_match is a multiset and is "
        "order-blind, _content_kinds_are_ordered_subsequence collapses everything to "
        "TEXT/IMAGE and is only a subsequence test, and _text_sizes_match restarts its "
        "search from index 0 for every expectation. Nothing therefore constrains how "
        "the two sequences interleave, so a derived PDF that relocates a whole table "
        "relative to the body text could satisfy every check. "
        "REPRODUCTION ATTEMPT: a Word body of paragraph/table/paragraph was validated "
        "against two synthetic PDFs, one in document order and one with the table "
        "moved above the first paragraph. Both were REJECTED, so the fixture does not "
        "discriminate and proves nothing either way. "
        "REPRODUCER LIMITATION: _parseable_text_pdf cannot produce a PDF that the "
        "table oracle accepts at all - even the faithful ordering is rejected - "
        "because it emits one text object per line with no cell geometry, so "
        "_matched_table_row_fragments never binds a row. Any fixture built on it "
        "cannot isolate ordering from table binding. "
        "REOPENING CRITERIA: reopen when a PDF that the table oracle ACCEPTS can be "
        "produced - most directly by rendering a real table through Microsoft Word in "
        "the native matrix, capturing that PDF, and then reordering its page content "
        "streams while leaving the table itself intact. If the reordered PDF is "
        "accepted, this becomes a CONFIRMED P1 false positive and the minimum repair "
        "is a single ordered stream of body blocks - paragraph fragments and table row "
        "anchors in document order - advanced by one shared cursor. "
        "Until then the oracle must not be weakened or refactored on this argument."
    )
)
def test_body_and_table_relative_order_is_bound() -> None:
    raise AssertionError("unreachable: see skip reason")


# --- Phase C §27 round 2: reviewer and auditor findings ---


@pytest.mark.parametrize(
    ("authoritative", "altered"),
    (
        ("area util 78,50 m²", "area util 78,50 m2"),
        ("PARECER REJEITADO", "Parecer Rejeitado"),
        ("1º andar", "1o andar"),
        ("AB", "ＡＢ"),
    ),
)
def test_strict_tokens_distinguish_material_substitutions(
    authoritative: str, altered: str
) -> None:
    """P0: NFKC+casefold folded away exactly what a judicial report depends on."""
    assert delivery_renderer._strict_tokens(authoritative) != delivery_renderer._strict_tokens(
        altered
    )
    # The matching stream stays folded, so wrap and fragment matching still work.
    assert delivery_renderer._lexical_tokens(authoritative) == delivery_renderer._lexical_tokens(
        altered
    )


@pytest.mark.parametrize(
    ("authoritative", "rendered"),
    (
        ("a b", "a b"),
        ("ﬁm", "fim"),
        ("co­operacao", "cooperacao"),
        ("a‑b", "a-b"),
    ),
)
def test_strict_tokens_tolerate_what_word_actually_varies(
    authoritative: str, rendered: str
) -> None:
    assert delivery_renderer._strict_tokens(authoritative) == delivery_renderer._strict_tokens(
        rendered
    )


def test_superseded_run_formatting_never_becomes_the_expectation() -> None:
    """P0: w:rPrChange holds the formatting a change REPLACED."""
    styles = delivery_renderer.ElementTree.fromstring(
        f"<w:styles {_MAIN_NS}>"
        '<w:style w:type="paragraph" w:styleId="Titulo"><w:rPr><w:sz w:val="32"/></w:rPr></w:style>'
        "</w:styles>"
    )
    document = _doc(
        '<w:p><w:pPr><w:pStyle w:val="Titulo"/></w:pPr>'
        '<w:r><w:rPr><w:rPrChange w:id="1" w:author="a" w:date="d"><w:rPr>'
        '<w:sz w:val="16"/><w:b/><w:color w:val="808080"/>'
        '<w:rFonts w:ascii="Comic Sans MS"/>'
        "</w:rPr></w:rPrChange></w:rPr>"
        "<w:t>TEXTO</w:t></w:r></w:p>"
    )

    [expectation] = delivery_renderer._word_text_expectations(
        {"word/document.xml": document, "word/styles.xml": styles}
    )

    assert expectation.font_size == 16.0
    assert expectation.bold is False
    assert expectation.color == (0, 0, 0)
    assert expectation.font_family is None


def test_superseded_paragraph_style_does_not_hide_visible_text() -> None:
    styles = delivery_renderer.ElementTree.fromstring(
        f"<w:styles {_MAIN_NS}>"
        '<w:style w:type="paragraph" w:styleId="Oculto"><w:rPr><w:vanish/></w:rPr></w:style>'
        "</w:styles>"
    )
    paragraph = next(
        delivery_renderer._iter_named(
            _doc(
                '<w:p><w:pPr><w:pPrChange w:id="2" w:author="a" w:date="d">'
                '<w:pPr><w:pStyle w:val="Oculto"/></w:pPr></w:pPrChange></w:pPr>'
                "<w:r><w:t>PARAGRAFO</w:t></w:r></w:p>"
            ),
            "p",
        )
    )

    text = delivery_renderer._visible_paragraph_text(
        paragraph, delivery_renderer._hidden_run_resolver(styles)
    )

    assert text == "PARAGRAFO"


def test_tab_separates_tokens_on_the_body_side_too() -> None:
    """A TOC line is "Introducao<tab>3"; fusing it matches no faithful PDF."""
    paragraph = next(
        delivery_renderer._iter_named(
            _doc("<w:p><w:r><w:t>Introducao</w:t><w:tab/><w:t>3</w:t></w:r></w:p>"), "p"
        )
    )

    text = delivery_renderer._visible_paragraph_text(
        paragraph, delivery_renderer._hidden_run_resolver(None)
    )

    assert delivery_renderer._lexical_tokens(text) == ("introducao", "3")


def test_text_box_is_counted_once_by_the_expectation_builder() -> None:
    document = _doc(
        "<w:p><w:r><w:t>ANTES</w:t></w:r>"
        "<w:r><w:pict><w:txbxContent><w:p><w:r><w:t>DENTRO</w:t></w:r></w:p>"
        "</w:txbxContent></w:pict></w:r></w:p>"
    )

    expectations = delivery_renderer._word_text_expectations(
        {"word/document.xml": document}
    )

    assert [item.text for item in expectations] == ["antes", "dentro"]


def test_blank_spacer_row_does_not_consume_the_next_row_line() -> None:
    fragments = [
        _frag("Cabecalho A", 50.0, 110.0, top=700.0),
        _frag("Cabecalho B", 200.0, 260.0, top=700.0),
        _frag("Dado A", 50.0, 110.0, top=640.0),
        _frag("Dado B", 200.0, 260.0, top=640.0),
    ]
    ordered = delivery_renderer._positioned_reading_order(fragments)
    header = ("Cabecalho A", "Cabecalho B")
    data = ("Dado A", "Dado B")

    assert delivery_renderer._table_rows_match([header, (), data], ordered, []) is True
    # Order is still bound: a swapped table must not pass.
    assert delivery_renderer._table_rows_match([data, (), header], ordered, []) is False


def test_profiled_header_text_excludes_hidden_runs() -> None:
    paragraph = next(
        delivery_renderer._iter_named(
            _doc(
                "<w:p><w:r><w:t>Visivel</w:t></w:r>"
                "<w:r><w:rPr><w:vanish/></w:rPr><w:t>Oculto</w:t></w:r></w:p>"
            ),
            "p",
        )
    )

    text = delivery_renderer._dynamic_paragraph_text(
        paragraph,
        page_number=1,
        is_hidden_run=delivery_renderer._hidden_run_resolver(None),
    )

    assert text == "Visivel"
