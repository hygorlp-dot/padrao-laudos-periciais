"""Figures in the report and the three oracle repairs they needed (#239, Phase E).

PHOTO_ORIGINAL != REPORT_PRESENTATION_DERIVATIVE: the document shows an
upright, bounded, metadata-free derivative of the original the figure is bound
to by SHA-256.  Figures are numbered in document order and prose cites them by
marker, resolved at presentation -- no Word field.

Word 16 rendered a faithful report with figures that the fidelity oracle
refused for three measurement defects, each repaired and pinned RED here:

* its content stream draws a page's pictures after all of the page's text;
* a caption kept with its picture (and the heading kept with the caption)
  moves to the next page with a picture that does not fit;
* so the text after a picture may open the following page.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from PIL import Image, ImageDraw
import pytest

from scripts.backend_contract import delivery_renderer as dr
from scripts.backend_contract.application.report_foundation import AmendReportDraft
from scripts.backend_contract.photo_library import PhotoEntry, PhotoLibrary
from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
from scripts.backend_contract.report_figures import figure_numbers, figure_presentation_image, resolve_references
from scripts.backend_contract.report_foundation import ReportFigure, report_snapshot_from_mapping, report_snapshot_to_mapping
from tests.test_report_authoring_v1 import _Record, _draft_bound_to, _upstream

FIXTURES = Path(__file__).parent / "fixtures"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def photo(seed: int, size=(1200, 900), *, orientation: int | None = None) -> bytes:
    image = Image.new("RGB", size, (40 + seed * 30, 90, 160 - seed * 20))
    draw = ImageDraw.Draw(image)
    for step in range(0, size[0], 60):
        draw.line([(step, 0), (size[0] - step, size[1])], fill=(230, 200 - seed * 25, 40 + seed * 40), width=9)
    draw.ellipse([200 + seed * 80, 150, 600 + seed * 80, 550], outline=(255, 255, 255), width=14)
    output = BytesIO()
    options = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        exif.get_ifd(0x8825)[1] = "S"
        options["exif"] = exif.tobytes()
    image.save(output, format="JPEG", quality=92, **options)
    return output.getvalue()


def _figure_id(index: int) -> str:
    return f"PHOTO-00000000-0000-4000-8000-{index:012d}"


def _report_with_figures(sections=("INSPECTION", "INSPECTION", "TECHNICAL_FINDINGS", "ATTACHMENTS")):
    report = report_snapshot_from_mapping(json.loads((FIXTURES / "report-snapshot-v1.json").read_text(encoding="utf-8")))
    originals, figures = {}, []
    for index, section in enumerate(sections, 1):
        content = photo(index, (1200, 900) if index != 3 else (900, 1200))
        originals[_figure_id(index)] = content
        figures.append(ReportFigure(_figure_id(index), f"0000000{index}-0000-4000-8000-000000000000", hashlib.sha256(content).hexdigest(), f"Registro fotográfico sintético número {index}", section, *Image.open(BytesIO(content)).size))
    claims = list(report.claims)
    claims[4] = replace(claims[4], text=claims[4].text + f" Ver [[FIGURA:{_figure_id(3)}]] e [[FIGURA:{_figure_id(1)}]].")
    return replace(report, figures=tuple(figures), claims=tuple(claims)), originals


# --- domain and presentation ----------------------------------------------------


def test_a_marker_names_a_presented_figure_or_table_and_resolves_to_its_number() -> None:
    report, _ = _report_with_figures()
    assert report_snapshot_from_mapping(report_snapshot_to_mapping(report)) == report
    numbers = figure_numbers(report)
    assert [numbers[_figure_id(index)] for index in (1, 2, 3, 4)] == [1, 2, 3, 4]
    assert resolve_references(f"Ver [[FIGURA:{_figure_id(3)}]].", numbers) == "Ver Figura 3."
    with pytest.raises(ValueError, match="cites a figure"):
        replace(report, figures=report.figures[:2])
    with pytest.raises(ValueError, match="cites a table"):
        replace(report, claims=(replace(report.claims[0], text="Ver [[TABELA:ACHADOS]]."), *report.claims[1:]))


def test_figures_are_numbered_in_document_order_with_the_title_above() -> None:
    report, _ = _report_with_figures(("ATTACHMENTS", "INSPECTION", "TECHNICAL_FINDINGS", "INSPECTION"))
    numbers = figure_numbers(report)
    assert [numbers[_figure_id(index)] for index in (2, 4, 3, 1)] == [1, 2, 3, 4]
    blocks = dr.professional_report_blocks(report)
    captions = [(position, block.text) for position, block in enumerate(blocks) if block.kind == "CAPTION"]
    assert [text.split(" – ")[0] for _position, text in captions] == ["Figura 1", "Figura 2", "Figura 3", "Figura 4"]
    assert all(blocks[position + 1].kind == "FIGURE" for position, _text in captions)
    text = "\n".join(t for block in blocks for t in block.paragraph_texts)
    assert "Ver Figura 3 e Figura 4." in text and "[[FIGURA" not in text and "PHOTO-" not in text


def test_the_derivative_is_upright_bounded_metadata_free_and_deterministic() -> None:
    original = photo(1, (3000, 2000), orientation=6)
    derivative = figure_presentation_image(original)
    assert derivative == figure_presentation_image(original)
    with Image.open(BytesIO(derivative)) as image:
        assert image.format == "JPEG" and image.size == (1067, 1600) and not image.getexif()
    with pytest.raises(ValueError, match="corrupt"):
        figure_presentation_image(original[:200])


def test_figures_are_captured_from_the_library_selection() -> None:
    case, technical, _ = _upstream()
    report = _draft_bound_to(case, technical)
    entry = PhotoEntry(_figure_id(1), "00000001-0000-4000-8000-000000000000", "a" * 64, "foto.jpg", "image/jpeg", 1200, 900, None, None, False, "2026-09-26T13:00:00+00:00", "Fissura na parede", (), "INSPECTION", 1)
    library = PhotoLibrary("1.0.0", "11111111-1111-4111-8111-111111111111", (entry,))
    service = AmendReportDraft(
        get_snapshot=SimpleNamespace(execute=lambda _w: (_Record(revision=7), report)),
        save_snapshot=SimpleNamespace(execute=lambda _w, snapshot, expected: _Record(revision=8)),
        ids=SimpleNamespace(new_uuid=lambda: "00000000-0000-4000-8000-000000000123"),
        get_photo_library=SimpleNamespace(execute=lambda _w: (_Record(revision=3), library)),
    )
    _, figured = service.execute("w", expected_revision=7, action="SET_FIGURES", values={})
    assert figured.figures == (ReportFigure(_figure_id(1), entry.content_id, "a" * 64, "Fissura na parede", "INSPECTION", 1200, 900),)
    empty = SimpleNamespace(execute=lambda _w: (_Record(revision=3), PhotoLibrary("1.0.0", library.workspace_id, (replace(entry, report_section=None, report_order=None),))))
    with pytest.raises(ValueError, match="selected photos"):
        replace(service, get_photo_library=empty).execute("w", expected_revision=7, action="SET_FIGURES", values={})


def test_the_word_package_carries_each_derivative_related_from_its_drawing() -> None:
    report, originals = _report_with_figures()
    images = {key: figure_presentation_image(value) for key, value in originals.items()}
    template = default_report_template(report.editorial_profile)
    word = dr.render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest(), figure_images=images).output_bytes
    package = ZipFile(BytesIO(word))
    assert package.read("word/media/plp-figure-003.jpeg") == images[_figure_id(3)]
    rels = package.read("word/_rels/document.xml.rels")
    assert rels.count(b"rIdPLPFig") == 4 and b'Extension="jpeg"' in package.read("[Content_Types].xml")
    document = package.read("word/document.xml").decode("utf-8")
    assert document.count("<wp:inline") == 4 and 'descr="Registro fotográfico sintético número 2"' in document
    with pytest.raises(ValueError, match="require their images"):
        dr.render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest(), figure_images={_figure_id(1): images[_figure_id(1)]})


# --- oracle repairs ---------------------------------------------------------------


def test_positional_order_reads_a_page_whose_pictures_are_streamed_last() -> None:
    """RED_THIS_REPAIR: caption, picture, heading on a page streamed T, T, I."""
    text = lambda top: dr._PositionedText(0, "texto", 100.0, top - 10, 10.0, 140.0, top - 10, top, page_width=595.0, page_height=842.0, strict_text="texto")  # noqa: E731
    picture = dr._PdfImageLayout(0, 100.0, 450.0, 500.0, 760.0, 595.0, 842.0)
    kinds = dr._positional_content_kinds([text(790.0), text(430.0)], [picture])
    assert kinds == ("TEXT", "IMAGE", "TEXT")
    assert dr._content_kinds_are_ordered_subsequence(("TEXT", "IMAGE", "TEXT"), kinds)
    assert not dr._content_kinds_are_ordered_subsequence(("TEXT", "IMAGE", "TEXT"), ("TEXT", "IMAGE"))


def test_a_keep_with_picture_chain_may_open_a_page() -> None:
    """RED_THIS_REPAIR: the caption and the heading kept with a moved picture were refused."""
    document = dr.ElementTree.fromstring(
        f'<w:document xmlns:w="{W}"><w:body>'
        "<w:p><w:r><w:t>Paragrafo anterior.</w:t></w:r></w:p>"
        "<w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:t>9. ANEXOS</w:t></w:r></w:p>"
        "<w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:t>Figura 4 legenda</w:t></w:r></w:p>"
        "<w:p><w:r><w:drawing/></w:r></w:p>"
        "<w:p><w:pPr><w:keepNext/></w:pPr><w:r><w:t>Titulo sem figura</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Texto seguinte.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    expectations = {item.text: item.page_break_before for item in dr._word_text_expectations({"word/document.xml": document})}
    assert expectations["9. anexos"] and expectations["figura 4 legenda"]
    assert not expectations["paragrafo anterior."] and not expectations["titulo sem figura"]


def test_the_text_after_a_picture_may_open_the_next_page() -> None:
    """RED_THIS_REPAIR: the next figure's caption, moved with its picture, was refused."""
    fragment = lambda page, top, text: dr._PositionedText(page, text, 100.0, top - 10, 10.0, 100.0 + len(text) * 5, top - 10, top, page_width=595.0, page_height=842.0, strict_text=text)  # noqa: E731
    positioned = [fragment(0, 520.0, "Figura 1"), fragment(1, 790.0, "Figura 2")]
    source = dr._WordImageLayout(300.0, 300.0, "inline", "center", None, None, "Figura 1", "Figura 2", 0, 0)
    picture = dr._PdfImageLayout(0, 147.5, 200.0, 447.5, 500.0, 595.0, 842.0)
    assert dr._ordered_image_layouts_match([source], [picture], positioned)
    elsewhere = [fragment(0, 520.0, "Figura 1"), fragment(1, 400.0, "Figura 2")]
    assert not dr._ordered_image_layouts_match([source], [picture], elsewhere)
    two_pages_on = [fragment(0, 520.0, "Figura 1"), fragment(2, 790.0, "Figura 2")]
    assert not dr._ordered_image_layouts_match([source], [picture], two_pages_on)


# --- Microsoft Word 16 ------------------------------------------------------------


def _native():
    from tests.test_office_word_native_matrix_v1 import _word_available

    return _word_available()


@pytest.mark.skipif("not __import__('tests.test_report_figures_v1', fromlist=['_native'])._native()", reason="Microsoft Word 16 unavailable")
def test_word_16_renders_figures_faithfully_and_a_swapped_picture_is_refused() -> None:
    from scripts.backend_contract.infrastructure.office_pdf import LocalOfficePdfConverter

    report, originals = _report_with_figures()
    images = {key: figure_presentation_image(value) for key, value in originals.items()}
    template = default_report_template(report.editorial_profile)
    word = dr.render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest(), figure_images=images).output_bytes
    pdf = dr.render_final_pdf_candidate(word_content=word, word_format="DOCX", converter=LocalOfficePdfConverter())
    dr.validate_final_artifact(pdf, "PDF")
    swapped = {**images, _figure_id(2): figure_presentation_image(photo(7))}
    other = dr.render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest(), figure_images=swapped).output_bytes
    copy, _format = dr.safe_pdf_conversion_copy(other, "DOCX")
    with pytest.raises(ValueError, match="faithfully"):
        dr._validate_pdf_fidelity(copy, pdf)


def test_the_delivery_derives_each_figure_from_its_bound_original_or_refuses() -> None:
    from scripts.backend_contract.application.delivery_foundation import RenderDeliveryPackage

    report, originals = _report_with_figures()
    by_content = {figure.content_id: originals[figure.figure_id] for figure in report.figures}
    private = SimpleNamespace(execute=lambda _w, content_id: SimpleNamespace(content=by_content[str(content_id)], metadata=SimpleNamespace(checksum_sha256=hashlib.sha256(by_content[str(content_id)]).hexdigest())))
    service = RenderDeliveryPackage(None, None, private, None, None, None)
    images = service._figure_images("w", report)
    assert images == {key: figure_presentation_image(value) for key, value in originals.items()}
    by_content[report.figures[0].content_id] = photo(9)
    with pytest.raises(ValueError, match="diverges from its bound bytes"):
        service._figure_images("w", report)
    assert service._figure_images("w", report_snapshot_from_mapping(json.loads((FIXTURES / "report-snapshot-v1.json").read_text(encoding="utf-8")))) is None
