"""The product's default report template and the oracle measurements it needs (#239, Phase C).

The default template honours the editorial profile -- a 1.25 cm first-line
indent, heading spacing, running header and page numbering.  Rendered by
Microsoft Word 16 it was refused by three measurement defects of the fidelity
oracle, each repaired here and pinned by a RED test:

* an indented first line: continuation lines return to the paragraph edge;
* a short glyph (hyphen) whose box top sits below its line's top;
* a paragraph whose last lines belong to a later run of different style.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from scripts.backend_contract import delivery_renderer as dr
from scripts.backend_contract.delivery_renderer import render_word_candidate, validate_final_artifact
from scripts.backend_contract.report_default_template import (
    DEFAULT_TEMPLATE_ID,
    TOC_CONTROL_TAG,
    default_report_template,
    default_template_manifest,
)
from scripts.backend_contract.report_foundation import (
    EDITORIAL_CUSTOM_ID,
    EditorialTypography,
    editorial_profile_from_mapping,
    editorial_profile_to_mapping,
    report_snapshot_from_mapping,
)

FIXTURES = Path(__file__).parent / "fixtures"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _report():
    return report_snapshot_from_mapping(json.loads((FIXTURES / "report-snapshot-v1.json").read_text(encoding="utf-8")))


def _text(page, text, x, top, *, size=11.0, right=None):
    return dr._PositionedText(page, text, x, top - size, size, right if right is not None else x + len(text) * size * 0.5, top - size, top, page_width=595.0, page_height=842.0, strict_text=text)


# --- the template -----------------------------------------------------------


def test_the_default_template_is_deterministic_and_carries_the_editorial_profile() -> None:
    profile = _report().editorial_profile
    first = default_report_template(profile)
    assert first == default_report_template(profile)
    with ZipFile(BytesIO(first)) as package:
        styles = ElementTree.fromstring(package.read("word/styles.xml"))
        document = package.read("word/document.xml").decode("utf-8")
        custom = package.read("docProps/custom.xml").decode("utf-8")
    normal = next(item for item in styles.iter(f"{W}style") if item.attrib.get(f"{W}styleId") == "Normal")
    assert normal.find(f"{W}pPr/{W}ind").attrib[f"{W}firstLine"] == str(round(1.25 * 567))
    assert normal.find(f"{W}pPr/{W}jc").attrib[f"{W}val"] == "both"
    assert normal.find(f"{W}rPr/{W}sz").attrib[f"{W}val"] == "22"
    assert any(item.find(f"{W}name").attrib[f"{W}val"] == "heading 1" for item in styles.iter(f"{W}style"))
    assert f'<w:tag w:val="{TOC_CONTROL_TAG}"/>' in document and '<w:tag w:val="CANONICAL_REPORT"/>' in document
    assert DEFAULT_TEMPLATE_ID in custom
    for placeholder in ("[[PROCESS_NUMBER]]", "[[COURT]]", "[[EXPERT_FULL_NAME]]", "[[EXPERT_TITLE]]", "[[EXPERT_REGISTRATION]]"):
        assert document.count(placeholder) == 1
    assert "[[REPORT_ID]]" not in document


def test_a_custom_profile_changes_the_template_and_the_preset_cannot_be_redefined() -> None:
    preset = _report().editorial_profile
    custom = editorial_profile_from_mapping({**editorial_profile_to_mapping(preset), "profile_id": EDITORIAL_CUSTOM_ID, "font_family": "Calibri", "body_font_pt": 12, "first_line_indent_cm": 0})
    assert default_report_template(custom) != default_report_template(preset)
    with pytest.raises(ValueError, match="preset values cannot change"):
        editorial_profile_from_mapping({**editorial_profile_to_mapping(preset), "body_font_pt": 12})
    with pytest.raises(ValueError):
        editorial_profile_from_mapping({**editorial_profile_to_mapping(preset), "profile_id": EDITORIAL_CUSTOM_ID, "font_family": "Comic Sans MS"})
    with pytest.raises(ValueError):
        editorial_profile_from_mapping({**editorial_profile_to_mapping(preset), "profile_id": EDITORIAL_CUSTOM_ID, "margin_left_cm": 0.5})
    with pytest.raises(ValueError, match="hierarchy"):
        EditorialTypography(12, 14, 11, True, 12, 6, 6)


def test_the_default_template_binds_the_approved_report_without_internal_identities() -> None:
    report = _report()
    word = render_word_candidate(template_bytes=default_report_template(report.editorial_profile), report=report, manifest=default_template_manifest()).output_bytes
    validate_final_artifact(word, "DOCX")
    with ZipFile(BytesIO(word)) as package:
        document = package.read("word/document.xml").decode("utf-8")
    process = next(item.note for item in report.context_matrix if item.field == "PROCESS_NUMBER")
    assert process in document and report.expert_profile.full_name in document
    assert report.report_id not in document


# --- oracle measurement repairs ---------------------------------------------


def _resolver(styles: str, paragraph: str):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    root = ElementTree.fromstring(f"<w:styles {ns}>{styles}</w:styles>") if styles else None
    return dr._first_line_offset_resolver(root)(ElementTree.fromstring(f"<w:p {ns}>{paragraph}</w:p>"))


@pytest.mark.parametrize(
    ("styles", "paragraph", "expected"),
    [
        ('<w:docDefaults><w:pPrDefault><w:pPr><w:ind w:firstLine="709"/></w:pPr></w:pPrDefault></w:docDefaults>', "", 35.45),
        ('<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:pPr><w:ind w:firstLine="709"/></w:pPr></w:style>', "", 35.45),
        ('<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:pPr><w:ind w:firstLine="709"/></w:pPr></w:style>'
         '<w:style w:type="paragraph" w:styleId="H"><w:basedOn w:val="Normal"/><w:pPr><w:ind w:firstLine="0"/></w:pPr></w:style>', '<w:pPr><w:pStyle w:val="H"/></w:pPr>', 0.0),
        ('<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:pPr><w:ind w:firstLine="709"/></w:pPr></w:style>', '<w:pPr><w:ind w:hanging="360"/></w:pPr>', -18.0),
        ("", '<w:pPr><w:ind w:firstLineChars="200"/></w:pPr>', 0.0),
    ],
    ids=["doc-defaults", "default-style", "style-chain-override", "direct-hanging", "chars-unmodelled"],
)
def test_the_first_line_offset_is_resolved_like_word(styles, paragraph, expected) -> None:
    assert _resolver(styles, paragraph) == pytest.approx(expected)


def test_an_indented_first_line_wraps_back_to_the_paragraph_edge() -> None:
    """RED_THIS_REPAIR: the continuation of an indented paragraph was refused."""
    fragments = [_text(0, "Primeira linha recuada do", 120.0, 700.0), _text(0, "paragrafo pericial.", 85.0, 682.0)]
    expected = "Primeira linha recuada do paragrafo pericial."
    assert dr._fragment_sequence_end(expected, fragments, 0, [], allow_line_wrap=True, alignment="both", first_line_offset=35.0) == 2
    # Controls: without the offset it stays refused, and the offset never
    # licenses a line starting anywhere else.
    assert dr._fragment_sequence_end(expected, fragments, 0, [], allow_line_wrap=True, alignment="both") is None
    elsewhere = [fragments[0], _text(0, "paragrafo pericial.", 420.0, 682.0)]
    assert dr._fragment_sequence_end(expected, elsewhere, 0, [], allow_line_wrap=True, alignment="both", first_line_offset=35.0) is None


def test_only_the_first_wrap_uses_the_first_line_offset() -> None:
    fragments = [
        _text(0, "Primeira linha recuada do", 120.0, 700.0),
        _text(0, "paragrafo pericial que", 85.0, 682.0),
        _text(0, "continua aqui.", 50.0, 664.0),
    ]
    assert dr._fragment_sequence_end("Primeira linha recuada do paragrafo pericial que continua aqui.", fragments, 0, [], allow_line_wrap=True, alignment="both", first_line_offset=35.0) is None


def test_a_short_glyph_does_not_define_the_line_top() -> None:
    """RED_THIS_REPAIR: a hyphen's box top was taken as its line's top."""
    line = [_text(0, "Observou", 121.0, 530.1), dr._PositionedText(0, "-", 168.6, 524.4, 11.0, 172.0, 524.4, 525.4, page_width=595.0, page_height=842.0, strict_text="-"), _text(0, "se a condicao.", 172.0, 530.1)]
    assert dr._last_line_top(line) == pytest.approx(530.1)
    two_lines = [_text(0, "primeira", 85.0, 700.0), _text(0, "ultima", 85.0, 686.0)]
    assert dr._last_line_top(two_lines) == pytest.approx(686.0)


def test_a_lead_run_paragraph_keeps_its_edge_after_every_wrap() -> None:
    """RED_THIS_REPAIR: a three-line answer after a bold lead was refused on its second wrap."""
    lead = _text(0, "Resposta:", 121.0, 700.0, right=168.0)
    continuation = [
        _text(0, "Sim. Existem fissuras na parede", 177.0, 700.0),
        _text(0, "leste da sala conforme o registro", 85.0, 683.0),
        _text(0, "fotografico.", 85.0, 666.0),
    ]
    anchor = dr._ParagraphWrapAnchor(0, lead.x, lead.right, lead.bottom, lead.top, 36.0)
    text = "Sim. Existem fissuras na parede leste da sala conforme o registro fotografico."
    assert dr._fragment_sequence_end(text, continuation, 0, [], allow_line_wrap=True, alignment="both", wrap_anchor=anchor) == 3
    # The edge stays bound: a third line starting elsewhere is still refused.
    elsewhere = [*continuation[:2], _text(0, "fotografico.", 300.0, 666.0)]
    assert dr._fragment_sequence_end(text, elsewhere, 0, [], allow_line_wrap=True, alignment="both", wrap_anchor=anchor) is None


# --- Microsoft Word 16 ------------------------------------------------------


def _native():
    from tests.test_office_word_native_matrix_v1 import _word_available

    return _word_available()


@pytest.mark.skipif("not __import__('tests.test_default_report_template_v1', fromlist=['_native'])._native()", reason="Microsoft Word 16 unavailable")
def test_word_16_renders_the_default_template_faithfully_and_changed_text_is_still_refused() -> None:
    from scripts.backend_contract.infrastructure.office_pdf import LocalOfficePdfConverter

    report = _report()
    template = default_report_template(report.editorial_profile)
    word = render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest()).output_bytes
    pdf = dr.render_final_pdf_candidate(word_content=word, word_format="DOCX", converter=LocalOfficePdfConverter())
    dr.validate_final_artifact(pdf, "PDF")
    changed = replace(report, claims=(replace(report.claims[0], text="Texto material deliberadamente alterado."), *report.claims[1:]))
    other = render_word_candidate(template_bytes=template, report=changed, manifest=default_template_manifest()).output_bytes
    copy, fmt = dr.safe_pdf_conversion_copy(other, "DOCX")
    with pytest.raises(ValueError, match="faithfully"):
        dr._validate_pdf_fidelity(copy, pdf)


def _toc_pages_in_word(word: bytes) -> tuple[int, ...]:
    """The page numbers the delivered Word's table of contents states."""
    root = ElementTree.fromstring(ZipFile(BytesIO(word)).read("word/document.xml"))
    control = next(
        item for item in root.iter(f"{W}sdt")
        if any(tag.attrib.get(f"{W}val") == TOC_CONTROL_TAG for tag in item.findall(f"./{W}sdtPr/{W}tag"))
    )
    texts = ["".join(node.text or "" for node in paragraph.iter(f"{W}t")) for paragraph in control.iter(f"{W}p")]
    return tuple(int(value) for value in texts[1::2])


def _long_report(extra_paragraphs: int):
    report = _report()
    filler = "\n".join(
        f"Parágrafo técnico {index} da seção de contexto, redigido para ocupar espaço suficiente e deslocar a paginação das seções seguintes do laudo."
        for index in range(1, extra_paragraphs + 1)
    )
    claims = tuple(
        replace(claim, text=f"{claim.text}\n{filler}") if index in (1, 3) else claim
        for index, claim in enumerate(report.claims)
    )
    return replace(report, claims=claims)


@pytest.mark.skipif("not __import__('tests.test_default_report_template_v1', fromlist=['_native'])._native()", reason="Microsoft Word 16 unavailable")
def test_word_16_table_of_contents_quotes_real_pages_and_follows_text_that_moves_them() -> None:
    from scripts.backend_contract.application.delivery_foundation import RenderDeliveryPackage
    from scripts.backend_contract.infrastructure.office_pdf import LocalOfficePdfConverter

    service = RenderDeliveryPackage(None, None, None, None, None, None, pdf_converter=LocalOfficePdfConverter())
    manifest = default_template_manifest()

    def delivered(report):
        word, pdf, renderer = service._paginated(default_report_template(report.editorial_profile), report, manifest)
        assert pdf is not None and renderer is not None, "the derived PDF must exist"
        stated = _toc_pages_in_word(word)
        measured = dr.locate_heading_pages(pdf, dr.report_heading_texts(report))
        assert stated == measured, (stated, measured)
        return stated

    before = delivered(_long_report(12))
    assert before[-1] > before[0], "the fixture must span several pages"
    after = delivered(_long_report(40))
    assert after[0] == before[0]
    assert after[-1] > before[-1], "added text must move later headings to later pages"
