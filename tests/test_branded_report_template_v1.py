"""#271 — modelo padrao V2 com a identidade visual da pericia.

Tudo sintetico: imagens geradas aqui, perfil e laudo das fixtures. O que so o
Microsoft Word 16 prova (paginacao real, PDF derivado fiel) fica no teste nativo,
pulado onde o Word nao existe; o restante e conferido no pacote OOXML.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
import pytest

from scripts.backend_contract import delivery_renderer as dr
from scripts.backend_contract.delivery_renderer import professional_report_blocks, render_word_candidate, validate_final_artifact
from scripts.backend_contract.installation_settings import (
    DEFAULT_BRANDING,
    DEFAULT_PRESENTATION,
    BackgroundKind,
    WatermarkKind,
)
from scripts.backend_contract.report_default_template import (
    BRANDED_TEMPLATE_ID,
    TemplateBranding,
    TemplateImage,
    branded_report_template,
    branded_template_manifest,
    default_report_template,
    page_raster,
)
from tests.test_default_report_template_v1 import _report

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def _png(size=(320, 120), color=(31, 58, 77), mode="RGB") -> TemplateImage:
    output = BytesIO()
    Image.new(mode, size, color).save(output, "PNG")
    return TemplateImage(output.getvalue(), "image/png", *size)


def _branding(report, **changes) -> TemplateBranding:
    presentation = replace(
        DEFAULT_PRESENTATION,
        watermark=replace(DEFAULT_PRESENTATION.watermark, enabled=True, kind=WatermarkKind.SYMBOL, opacity=0.08),
    )
    values = dict(
        presentation=presentation, branding=DEFAULT_BRANDING, expert=report.expert_profile,
        logo=_png(), symbol=_png((200, 200), (31, 58, 77, 255), "RGBA"), signature=_png((300, 90), (20, 20, 20)),
        seal=_png((160, 160), (90, 20, 20)), city_year="Recife, 2026",
    )
    values.update(changes)
    return TemplateBranding(**values)


def _parts(content: bytes) -> dict[str, bytes]:
    with ZipFile(BytesIO(content)) as package:
        return {name: package.read(name) for name in package.namelist()}


def test_v1_stays_byte_identical_without_branding():
    # Hash do V1 gerado pelo codigo anterior a #271 para o perfil da fixture.
    assert sha256(default_report_template(_report().editorial_profile)).hexdigest() == "91a2add913f2cb8bfd7e0f9fa87ed7a53441373e5ab50e4db281efe38e6aa3a6"


def test_branded_template_is_deterministic_and_binds_the_approved_report():
    report = _report()
    branding = _branding(report)
    template = branded_report_template(report.editorial_profile, branding)
    assert template == branded_report_template(report.editorial_profile, branding)
    validate_final_artifact(template, "DOCX")
    word = render_word_candidate(template_bytes=template, report=report, manifest=branded_template_manifest()).output_bytes
    validate_final_artifact(word, "DOCX")
    parts = _parts(word)
    document = parts["word/document.xml"].decode("utf-8")
    assert "[[" not in document and report.expert_profile.full_name in document
    # Capa: identificacao sempre presente; polos pelo resumo (aqui, o texto legado ou "—").
    assert "Processo nº " in document and "Polo ativo: " in document and "Polo passivo: " in document
    assert BRANDED_TEMPLATE_ID in parts["docProps/custom.xml"].decode("utf-8")


def test_cover_header_footer_and_page_geometry():
    report = _report()
    parts = _parts(branded_report_template(report.editorial_profile, _branding(report)))
    document = ElementTree.fromstring(parts["word/document.xml"])
    section = document.find(f"{W}body/{W}sectPr")
    assert section.find(f"{W}titlePg") is not None
    references = {(item.tag.rsplit("}", 1)[1], item.attrib[f"{W}type"]) for item in section if item.tag.endswith("Reference")}
    assert references == {("headerReference", "default"), ("headerReference", "first"), ("footerReference", "default"), ("footerReference", "first")}
    margins = section.find(f"{W}pgMar").attrib
    layout = report.editorial_profile.effective_layout
    assert margins[f"{W}header"] == str(round(layout.header_distance_cm * 567))
    assert margins[f"{W}footer"] == str(round(layout.footer_distance_cm * 567))
    body_header = parts["word/header1.xml"].decode("utf-8")
    # Imagem de pagina ancorada atras do texto, na origem da pagina, e logotipo em linha.
    assert 'behindDoc="1"' in body_header and 'relativeFrom="page"' in body_header and "<wp:inline" in body_header
    assert report.expert_profile.full_name in body_header
    footer = parts["word/footer1.xml"].decode("utf-8")
    assert "Página " in footer and " PAGE " in footer and " NUMPAGES " in footer
    # Capa sem numeracao nem cabecalho de identidade.
    assert "PAGE" not in parts["word/footer2.xml"].decode("utf-8")
    assert report.expert_profile.full_name not in parts["word/header2.xml"].decode("utf-8")
    assert any(name.startswith("word/media/") for name in parts)


def test_profile_presentation_decides_what_identity_the_header_exposes():
    report = _report()
    profile = report.expert_profile
    hidden = branded_report_template(report.editorial_profile, _branding(report))
    assert profile.registration not in _parts(hidden)["word/header1.xml"].decode("utf-8") or (profile.presentation is None)
    from scripts.backend_contract.report_foundation import DEFAULT_PROFILE_PRESENTATION
    shown = replace(profile, presentation=replace(DEFAULT_PROFILE_PRESENTATION, show_registration_header=True))
    report_shown = replace(report, expert_profile=shown)
    header = _parts(branded_report_template(report.editorial_profile, _branding(report_shown, expert=shown)))["word/header1.xml"].decode("utf-8")
    assert profile.registration in header


def test_a_template_generated_for_another_expert_profile_is_refused():
    report = _report()
    other = replace(report.expert_profile, full_name="OUTRO PERITO SINTETICO")
    template = branded_report_template(report.editorial_profile, _branding(report, expert=other))
    with pytest.raises(ValueError, match="another expert profile"):
        render_word_candidate(template_bytes=template, report=report, manifest=branded_template_manifest())


def test_branded_styles_carry_heading_color_and_long_quote():
    report = _report()
    styles = ElementTree.fromstring(_parts(branded_report_template(report.editorial_profile, _branding(report)))["word/styles.xml"])
    by_id = {item.attrib[f"{W}styleId"]: item for item in styles.iter(f"{W}style")}
    assert by_id["Heading1"].find(f"{W}rPr/{W}color").attrib[f"{W}val"] == DEFAULT_BRANDING.heading_color.lstrip("#")
    quote = by_id["Quote"]
    layout = report.editorial_profile.effective_layout
    assert quote.find(f"{W}pPr/{W}ind").attrib[f"{W}left"] == str(round(layout.long_quote_indent_cm * 567))
    expected = (report.editorial_profile.body_font_pt - layout.long_quote_font_pt_delta) * 2
    assert quote.find(f"{W}rPr/{W}sz").attrib[f"{W}val"] == str(expected)


def test_long_quote_paragraph_uses_the_quote_style_without_the_marker():
    report = _report()
    claim = replace(report.claims[0], text="Conforme a norma:\n\n> Texto citado sintético, longo o bastante para ser uma citação recuada.")
    quoted = replace(report, claims=(claim, *report.claims[1:]))
    blocks = [block for block in professional_report_blocks(quoted) if block.kind == "QUOTE"]
    assert [block.text for block in blocks] == ["Texto citado sintético, longo o bastante para ser uma citação recuada."]


def test_page_raster_is_opaque_and_keeps_the_watermark_light():
    watermark = replace(DEFAULT_PRESENTATION.watermark, enabled=True, kind=WatermarkKind.SYMBOL, opacity=0.08, scale=0.5)
    content = page_raster(
        page_width_pt=595.3, page_height_pt=841.9, background=None, background_image=None,
        watermark=watermark, watermark_image=_png((200, 200), (0, 0, 0, 255), "RGBA"), rule=None,
    )
    image = Image.open(BytesIO(content))
    assert image.mode == "RGB"
    darkest = min(image.convert("L").getdata())
    # Preto a 8%: o pixel mais escuro continua claro (texto preto segue legivel).
    assert darkest >= 230
    assert page_raster(page_width_pt=595.3, page_height_pt=841.9, background=None, background_image=None, watermark=None, watermark_image=None, rule=None) is None


def test_solid_background_and_separator_rule_are_painted():
    background = replace(DEFAULT_PRESENTATION.background, kind=BackgroundKind.SOLID, color="#F4F6F8", apply_body=True)
    content = page_raster(
        page_width_pt=595.3, page_height_pt=841.9, background=background, background_image=None,
        watermark=None, watermark_image=None, rule=(2.0, "#9AAAB8", 0.75),
    )
    image = Image.open(BytesIO(content)).convert("RGB")
    assert image.getpixel((5, 5)) == (0xF4, 0xF6, 0xF8)
    y = round(2.0 / 2.54 * 150)
    assert image.getpixel((image.width // 2, y)) == (0x9A, 0xAA, 0xB8)


def _word_with_page_anchor(image_bytes: bytes) -> bytes:
    output = BytesIO()
    document = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic</w:t></w:r></w:p></w:body></w:document>'
    header = (
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:p><w:r><w:drawing><wp:anchor behindDoc="1">'
        '<wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{595 * 12700}" cy="{842 * 12700}"/>'
        '<a:graphic><a:graphicData><a:blip r:embed="rId1"/></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p></w:hdr>'
    )
    relationships = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="media/page.jpg"/></Relationships>'
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
        package.writestr("word/header1.xml", header)
        package.writestr("word/_rels/header1.xml.rels", relationships)
        package.writestr("word/media/page.jpg", image_bytes)
    return output.getvalue()


@pytest.mark.parametrize(("color", "x", "behind", "accepted"), [
    ((235, 238, 242), 0, True, True),     # fundo claro atras do texto
    ((235, 238, 242), 0, False, False),   # opaco por cima do texto: oculta conteudo
    ((0, 0, 0), 0, True, False),          # escuro atras: texto deixa de ser visivel
    ((235, 238, 242), 30, True, False),   # fora da posicao ancorada
])
def test_fidelity_binds_a_page_background_anchored_in_the_header(color, x, behind, accepted):
    from tests.test_delivery_foundation_v1 import _image_pdf
    image = BytesIO()
    Image.new("RGB", (8, 8), color).save(image, "JPEG")
    word = _word_with_page_anchor(image.getvalue())
    pdf = _image_pdf("Synthetic", image.getvalue(), image_x=x, image_y=0, image_width=595, image_height=842, image_after_text=not behind)
    if accepted:
        dr._validate_pdf_fidelity(word, pdf)
    else:
        with pytest.raises(ValueError, match="faithfully represent"):
            dr._validate_pdf_fidelity(word, pdf)


_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _jpeg(color) -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), color).save(output, "JPEG")
    return output.getvalue()


def _word_with_figure_and_header_anchor(*, behind: bool, x: int, y: int, size: int) -> bytes:
    inline = ('<wp:inline><wp:extent cx="508000" cy="508000"/><a:graphic><a:graphicData><a:blip r:embed="rId1"/>'
              '</a:graphicData></a:graphic></wp:inline>')
    document = (f'<w:document {_NS}><w:body><w:p><w:r><w:t>Synthetic</w:t></w:r></w:p>'
                f'<w:p><w:r><w:drawing>{inline}</w:drawing></w:r></w:p></w:body></w:document>')
    header = (f'<w:hdr {_NS}><w:p><w:r><w:drawing><wp:anchor behindDoc="{1 if behind else 0}">'
              f'<wp:positionH relativeFrom="page"><wp:posOffset>{x * 12700}</wp:posOffset></wp:positionH>'
              f'<wp:positionV relativeFrom="page"><wp:posOffset>{y * 12700}</wp:posOffset></wp:positionV>'
              f'<wp:extent cx="{size * 12700}" cy="{size * 12700}"/>'
              '<a:graphic><a:graphicData><a:blip r:embed="rId1"/></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p></w:hdr>')
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", document)
        package.writestr("word/_rels/document.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="media/figure.jpg"/></Relationships>')
        package.writestr("word/media/figure.jpg", _jpeg("red"))
        package.writestr("word/header1.xml", header)
        package.writestr("word/_rels/header1.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="media/logo.jpg"/></Relationships>')
        package.writestr("word/media/logo.jpg", _jpeg((235, 238, 242)))
    return output.getvalue()


def _pdf_in_order(order: list[str], *, anchor: tuple[int, int, int]) -> bytes:
    x, y, size = anchor
    commands = {
        "text": b"BT /F1 10 Tf 1 0 0 1 50 650 Tm (Synthetic) Tj ET",
        "figure": b"q 40 0 0 40 100 600 cm /Im1 Do Q",
        "anchor": f"q {size} 0 0 {size} {x} {842 - y - size} cm /Im2 Do Q".encode(),
    }
    stream = b" ".join(commands[item] for item in order)

    def image(data: bytes) -> bytes:
        return (b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length "
                + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream")
    objects = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        image(_jpeg("red")), image(_jpeg((235, 238, 242))),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Page /Parent 6 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 1 0 R >> /XObject << /Im1 2 0 R /Im2 3 0 R >> >> /Contents 4 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [5 0 R] >>",
        b"<< /Type /Catalog /Pages 6 0 R >>",
    )
    output = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    output.extend(b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets))
    output.extend(f"trailer << /Size {len(objects) + 1} /Root {len(objects)} 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)


@pytest.mark.parametrize(("behind", "anchor", "order", "accepted"), [
    (True, (100, 202, 40), ["anchor", "text", "figure"], True),    # atrás e desenhada antes da foto
    (True, (100, 202, 40), ["text", "figure", "anchor"], False),   # "atrás", mas pintada por cima da foto
    (True, (300, 20, 40), ["text", "figure", "anchor"], True),     # não cruza a foto: a ordem é livre
    (False, (100, 202, 40), ["anchor", "text", "figure"], False),  # na frente, fora da faixa do cabeçalho
    (False, (300, 20, 40), ["text", "figure", "anchor"], True),    # na frente, dentro da faixa
])
def test_fidelity_never_lets_a_header_anchor_hide_a_body_picture(behind, anchor, order, accepted):
    # Revisão do 2º conjunto, P1-1: a âncora deixou de ficar presa à faixa e
    # nada a impedia de cobrir uma foto do corpo no PDF derivado.
    word = _word_with_figure_and_header_anchor(behind=behind, x=anchor[0], y=anchor[1], size=anchor[2])
    pdf = _pdf_in_order(order, anchor=anchor)
    if accepted:
        dr._validate_pdf_fidelity(word, pdf)
    else:
        with pytest.raises(ValueError, match="faithfully represent"):
            dr._validate_pdf_fidelity(word, pdf)


def _native():
    from tests.test_office_word_native_matrix_v1 import _word_available

    return _word_available()


@pytest.mark.skipif("not __import__('tests.test_branded_report_template_v1', fromlist=['_native'])._native()", reason="Microsoft Word 16 unavailable")
def test_word_16_renders_the_branded_template_faithfully():
    from scripts.backend_contract.infrastructure.office_pdf import LocalOfficePdfConverter

    report = _report()
    template = branded_report_template(report.editorial_profile, _branding(report))
    word = render_word_candidate(template_bytes=template, report=report, manifest=branded_template_manifest()).output_bytes
    pdf = dr.render_final_pdf_candidate(word_content=word, word_format="DOCX", converter=LocalOfficePdfConverter())
    dr.validate_final_artifact(pdf, "PDF")
