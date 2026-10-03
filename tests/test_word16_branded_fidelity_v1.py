"""Real Microsoft Word 16 renders of the branded templates (#281).

The DOCX/PDF pairs under tests/fixtures/word16-*.{docx,pdf} were captured on
Windows 11 10.0.26200 with Word 16.0.20430.20118 (Click-to-Run, x64) from main
42de7be: the DOCX is the exact conversion copy handed to Word and the PDF is
what Word exported.  They are synthetic.  The fidelity oracle refused the two
branded renders although Word drew what the DOCX declares; each case below is
one predicate that mis-modelled Word, and each adversarial proves that the
repaired predicate still refuses the PDF when it no longer represents the DOCX.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, FloatObject

from scripts.backend_contract import delivery_renderer as dr

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# SHA-256 of the bytes captured on the Word 16 machine (diag-w16, #281).
_CAPTURED = {
    "word16-branded-simple.docx": "cebb7c76bd3e450765d6e9ad3da66c24e874277856c62a8042257a354fe7baaa",
    "word16-branded-simple.pdf": "68bbeddf6f34d8da722971962069dad820589638831733adba1710e754c6e8f0",
    "word16-branded-v2.docx": "50ff2fa2dbf2e749dd9485d93c3411e763ae2a71e90d9250a9e5bd5d7114b611",
    "word16-branded-v2.pdf": "6d48afe6ea59a2ac43ed4632a65c00af94cd3f25be85eed993744b506c6e7eb9",
    "word16-custom-template.docx": "cc910151e7d475fac4a9c4fe64ddbc2fde5212ca5f82c182dd5ce4ffd9676e56",
    "word16-custom-template.pdf": "554d4f870ea995820a938085fb38d998484eb6653416588ac4fb5d0de611f0e2",
}


def _fixture(name: str) -> bytes:
    data = (_FIXTURES / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == _CAPTURED[name], name
    return data


def _pair(stem: str) -> tuple[bytes, bytes]:
    return _fixture(f"{stem}.docx"), _fixture(f"{stem}.pdf")


def _docx_with(word: bytes, part: str, old: str, new: str, *, count: int = 1) -> bytes:
    """The same package with one exact textual edit in one part."""
    source = ZipFile(BytesIO(word))
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == part:
                text = data.decode("utf-8")
                assert text.count(old) == count, (part, old, text.count(old))
                data = text.replace(old, new).encode("utf-8")
            target.writestr(item, data)
    return output.getvalue()


def _docx_with_media(word: bytes, part: str, replacement: bytes) -> bytes:
    source = ZipFile(BytesIO(word))
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = replacement if item.filename == part else source.read(item.filename)
            target.writestr(item, data)
    return output.getvalue()


def _pdf_with_page_operations(pdf: bytes, page_index: int, edit) -> bytes:
    """The same PDF with one page's content operations rewritten by ``edit``."""
    reader = PdfReader(BytesIO(pdf))
    writer = PdfWriter(clone_from=reader)
    page = writer.pages[page_index]
    content = ContentStream(page.get_contents(), writer)
    content.operations = edit(list(content.operations))
    page.replace_contents(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _drawing_block(operations: list, predicate) -> tuple[int, int]:
    """[start, end) of the first q ... Q block whose operations satisfy predicate."""
    depth = 0
    start = None
    for index, (operands, operator) in enumerate(operations):
        if operator == b"q":
            if depth == 0:
                start = index
            depth += 1
        elif operator == b"Q":
            depth -= 1
            if depth == 0 and start is not None and predicate(operations[start : index + 1]):
                return start, index + 1
    raise AssertionError("drawing block not found")


def _shows_text(fragment: str):
    def predicate(block: list) -> bool:
        shown = "".join(
            part if isinstance(part, str) else ""
            for operands, operator in block
            if operator == b"TJ"
            for part in operands[0]
        )
        return fragment in shown

    return predicate


def _draws_image(block: list) -> bool:
    return any(operator == b"Do" for _operands, operator in block)


def _assert_refused(word: bytes, pdf: bytes) -> None:
    with pytest.raises(ValueError, match="does not faithfully represent"):
        dr._validate_pdf_fidelity(word, pdf)


# --- GREEN: the real Word 16 renders are faithful -------------------------------------


@pytest.mark.parametrize(
    "stem", ["word16-branded-simple", "word16-branded-v2", "word16-custom-template"]
)
def test_real_word_16_renders_of_the_product_templates_are_faithful(stem):
    word, pdf = _pair(stem)
    dr._validate_pdf_fidelity(word, pdf)


# --- the Word behaviours each repaired predicate now models ----------------------------


def test_word_joins_paragraph_spacing_with_the_larger_value_unless_the_document_opts_out():
    settings = (
        '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "{}</w:settings>"
    )
    from xml.etree import ElementTree

    collapsed = dr._word_paragraph_spacing_combiner(ElementTree.fromstring(settings.format("")))
    additive = dr._word_paragraph_spacing_combiner(
        ElementTree.fromstring(
            settings.format("<w:compat><w:doNotUseHTMLParagraphAutoSpacing/></w:compat>")
        )
    )
    switched_off = dr._word_paragraph_spacing_combiner(
        ElementTree.fromstring(
            settings.format(
                '<w:compat><w:doNotUseHTMLParagraphAutoSpacing w:val="0"/></w:compat>'
            )
        )
    )
    assert collapsed(12.0, 60.0) == 60.0
    assert additive(12.0, 60.0) == 72.0
    assert switched_off(12.0, 60.0) == 60.0


def test_the_spacing_model_is_bound_to_the_document_not_loosened():
    """Opting the same DOCX out of Word's HTML auto spacing makes it declare
    the summed gaps; Word's collapsed render no longer represents it."""
    word, pdf = _pair("word16-branded-simple")
    additive = _docx_with(
        word,
        "word/settings.xml",
        "<w:defaultTabStop",
        "<w:compat><w:doNotUseHTMLParagraphAutoSpacing/></w:compat><w:defaultTabStop",
    )
    _assert_refused(additive, pdf)


def test_a_footer_field_between_two_runs_keeps_them_two_expectations():
    word, _pdf = _pair("word16-branded-simple")
    from xml.etree import ElementTree

    with ZipFile(BytesIO(word)) as package:
        roots = {
            name: ElementTree.fromstring(package.read(name))
            for name in ("word/styles.xml", "word/footer1.xml", "word/settings.xml")
        }
    footer = [
        expectation.text
        for expectation in dr._word_text_expectations(
            roots, active_content_names={"word/footer1.xml"}
        )
    ]
    assert footer == ["página", "de"]


# --- ADVERSARIAL: the real render against a DOCX it does not represent -----------------


@pytest.mark.parametrize(
    ("part", "old", "new"),
    [
        # header text replaced
        ("word/header1.xml", "Profissional Sintético", "Profissional Trocado"),
        # PAGE/NUMPAGES: "Página 2 de 3" is no longer what the footer declares
        ("word/footer1.xml", " NUMPAGES ", " PAGE "),
        # title font size materially different
        ("word/styles.xml", '<w:sz w:val="40"/><w:szCs w:val="40"/>', '<w:sz w:val="28"/><w:szCs w:val="28"/>'),
        # cover logo displaced: the title no longer declares 120 pt above it
        ("word/styles.xml", 'w:before="2400"', 'w:before="200"'),
        # body text substituted
        ("word/document.xml", "A parte sintética alegou uma ocorrência.", "A parte sintética negou uma ocorrência."),
    ],
    ids=["header-text", "page-numpages", "title-size", "logo-displaced", "text-substituted"],
)
def test_the_branded_render_is_refused_for_a_docx_it_does_not_represent(part, old, new):
    word, pdf = _pair("word16-branded-simple")
    _assert_refused(_docx_with(word, part, old, new), pdf)


def test_body_order_altered_is_refused():
    word, pdf = _pair("word16-branded-simple")
    first = "A parte sintética alegou uma ocorrência."
    second = "A decisão sintética delimitou o objeto pericial."
    swapped = _docx_with(word, "word/document.xml", first, "\u0000")
    swapped = _docx_with(swapped, "word/document.xml", second, first)
    swapped = _docx_with(swapped, "word/document.xml", "\u0000", second)
    _assert_refused(swapped, pdf)


def test_the_first_page_header_profile_is_bound():
    """Dropping titlePg makes the cover carry the running header it never had."""
    word, pdf = _pair("word16-branded-simple")
    with ZipFile(BytesIO(word)) as package:
        document = package.read("word/document.xml").decode("utf-8")
    title_page = next(
        marker for marker in ("<w:titlePg/>", '<w:titlePg w:val="1"/>', "<w:titlePg w:val=\"true\"/>")
        if marker in document
    )
    _assert_refused(_docx_with(word, "word/document.xml", title_page, ""), pdf)


def test_the_long_quote_indent_is_bound_both_ways():
    word, pdf = _pair("word16-branded-v2")
    indent = '<w:ind w:left="2268" w:firstLine="0"/>'
    # Not indented: the 4 cm recuo Word drew is no longer the document's.
    _assert_refused(_docx_with(word, "word/styles.xml", indent, '<w:ind w:left="0" w:firstLine="0"/>'), pdf)
    # Indented further than Word drew it: a line cannot start left of its indent.
    _assert_refused(_docx_with(word, "word/styles.xml", indent, '<w:ind w:left="4000" w:firstLine="0"/>'), pdf)


def test_a_missing_or_swapped_picture_is_refused():
    word, pdf = _pair("word16-branded-simple")
    with ZipFile(BytesIO(word)) as package:
        media = sorted(name for name in package.namelist() if name.startswith("word/media/"))
        images = {name: package.read(name) for name in media}
    assert len(media) >= 3
    # Every picture swapped for another one of the package: logo, signature, seal.
    for target in media:
        donor = next(name for name in media if images[name] != images[target])
        _assert_refused(_docx_with_media(word, target, images[donor]), pdf)
    # The seal no longer exists in the DOCX: the PDF paints a picture the
    # document does not have.
    with ZipFile(BytesIO(word)) as package:
        document = package.read("word/document.xml").decode("utf-8")
    seal_start = document.rindex("<w:drawing>")
    seal_end = document.index("</w:drawing>", seal_start) + len("</w:drawing>")
    _assert_refused(
        _docx_with(word, "word/document.xml", document[seal_start:seal_end], ""), pdf
    )


# --- ADVERSARIAL: a derived PDF that is not Word's render ------------------------------


def test_background_painted_over_the_page_is_refused():
    word, pdf = _pair("word16-branded-simple")

    def paint_background_last(operations: list) -> list:
        start, end = _drawing_block(operations, _draws_image)
        return operations[:start] + operations[end:] + operations[start:end]

    _assert_refused(word, _pdf_with_page_operations(pdf, 1, paint_background_last))


def test_a_doubled_running_header_is_refused():
    """The header is located as the topmost copy in its band; a second copy is
    still refused by the exact token multiset."""
    word, pdf = _pair("word16-branded-v2")

    def double_header(operations: list) -> list:
        start, end = _drawing_block(operations, _shows_text("Prof"))
        copy = []
        for operands, operator in operations[start:end]:
            if operator == b"Tm":
                operands = [*operands[:5], FloatObject(float(operands[5]) - 30)]
            copy.append((operands, operator))
        return operations[:end] + copy + operations[end:]

    _assert_refused(word, _pdf_with_page_operations(pdf, 3, double_header))


def test_a_missing_running_header_is_refused_even_when_body_text_repeats_it():
    """Page 4 opens with the signature block, whose name repeats the header."""
    word, pdf = _pair("word16-branded-v2")

    def drop_header_name(operations: list) -> list:
        start, end = _drawing_block(operations, _shows_text("Prof"))
        return operations[:start] + operations[end:]

    _assert_refused(word, _pdf_with_page_operations(pdf, 3, drop_header_name))


def test_a_dropped_page_is_refused():
    word, pdf = _pair("word16-branded-v2")
    reader = PdfReader(BytesIO(pdf))
    writer = PdfWriter()
    for page in reader.pages[:-1]:
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    _assert_refused(word, output.getvalue())


# --- independent review (#281): geometry the repaired predicates must keep ----------


def _move_picture(name: str, dx: float, dy: float):
    """Translate one painted picture (its clip rectangle and its matrix)."""

    def edit(operations: list) -> list:
        moved = []
        for index, (operands, operator) in enumerate(operations):
            following = operations[index + 1 : index + 5]
            draws_it = any(
                op == b"Do" and str(args[0]) == name for args, op in following
            )
            if operator == b"cm" and operations[index + 1][1] == b"Do" and draws_it:
                operands = [
                    *operands[:4],
                    FloatObject(float(operands[4]) + dx),
                    FloatObject(float(operands[5]) + dy),
                ]
            elif operator == b"re" and draws_it:
                operands = [
                    FloatObject(float(operands[0]) + dx),
                    FloatObject(float(operands[1]) + dy),
                    *operands[2:],
                ]
            moved.append((operands, operator))
        return moved

    return edit


@pytest.mark.parametrize(
    ("page", "picture", "dx", "dy"),
    [
        (0, "/Image12", 0.0, -115.0),  # cover logo onto the title, 120 pt declared
        (0, "/Image12", 0.0, -60.0),
        (0, "/Image12", 0.0, 60.0),
        (3, "/Image21", 85.05 - 226.8, 0.0),  # centred signature to the margin
        (3, "/Image22", 85.05 - 262.23, 0.0),  # centred seal to the margin
        (3, "/Image22", 0.0, -60.0),
    ],
    ids=["logo-down-115", "logo-down-60", "logo-up-60", "signature-left", "seal-left", "seal-down-60"],
)
def test_a_picture_moved_from_where_the_document_puts_it_is_refused(page, picture, dx, dy):
    word, pdf = _pair("word16-branded-v2")
    _assert_refused(word, _pdf_with_page_operations(pdf, page, _move_picture(picture, dx, dy)))


def _move_text_line(y_from: float, y_to: float, *, before: int):
    def edit(operations: list) -> list:
        moved = []
        for index, (operands, operator) in enumerate(operations):
            if operator == b"Tm" and index < before and abs(float(operands[5]) - y_from) < 0.05:
                operands = [*operands[:5], FloatObject(y_to)]
            moved.append((operands, operator))
        return moved

    return edit


def test_a_running_header_moved_into_the_body_is_refused_even_beside_its_repetition():
    """Page 4 opens with the signature block repeating the header's name."""
    word, pdf = _pair("word16-branded-v2")

    def lower_the_header(operations: list) -> list:
        operations = _move_text_line(769.77, 650.0, before=60)(operations)
        return _move_text_line(757.97, 638.0, before=120)(operations)

    _assert_refused(word, _pdf_with_page_operations(pdf, 3, lower_the_header))


def test_a_header_missing_where_body_text_repeats_it_is_refused():
    """One-line header; page 4 loses it while its text moves to mid page."""
    word, pdf = _pair("word16-branded-v2")
    line_two = (
        '<w:p><w:pPr><w:pStyle w:val="Header"/><w:jc w:val="left"/></w:pPr><w:r>'
        '<w:t xml:space="preserve">Perito Judicial · REG-SYNTHETIC-001</w:t></w:r></w:p>'
    )
    one_line = _docx_with(word, "word/header1.xml", line_two, "")

    def drop_line_two(operations: list) -> list:
        start, end = _drawing_block(operations, _shows_text("Perit"))
        return operations[:start] + operations[end:]

    stripped = pdf
    for page in (1, 2, 3):
        stripped = _pdf_with_page_operations(stripped, page, drop_line_two)

    def header_to_mid_page(operations: list) -> list:
        start, end = _drawing_block(operations, _shows_text("Prof"))
        block = [
            ([*operands[:5], FloatObject(400.0)] if operator == b"Tm" else operands, operator)
            for operands, operator in operations[start:end]
        ]
        return operations[:start] + operations[end:] + block

    _assert_refused(one_line, _pdf_with_page_operations(stripped, 3, header_to_mid_page))


def test_the_custom_template_header_cannot_sit_over_the_body():
    word, pdf = _pair("word16-custom-template")
    reader = PdfReader(BytesIO(pdf))
    operations = ContentStream(reader.pages[2].get_contents(), reader).operations
    header_y = max(
        float(operands[5]) for operands, operator in operations if operator == b"Tm"
    )
    _assert_refused(
        word, _pdf_with_page_operations(pdf, 2, _move_text_line(header_y, 640.0, before=len(operations)))
    )


def test_a_picture_opens_the_next_page_only_when_it_does_not_fit():
    def text(page: int, value: str, baseline: float) -> dr._PositionedText:
        return dr._PositionedText(
            page=page, text=value, x=85.0, y=baseline, font_size=11.0,
            right=85.0 + 5.5 * len(value), bottom=baseline - 2.5, top=baseline + 8.5,
            page_width=595.3, page_height=841.9, strict_text=value,
        )

    source = dr._WordImageLayout(
        170.0, 51.0, "inline", "center", None, None,
        "Texto anterior.", "Texto seguinte.", 0, 0,
    )
    picture = dr._PdfImageLayout(
        page=1, left=212.6, bottom=705.0, right=382.6, top=756.0,
        page_width=595.3, page_height=841.9,
    )
    following = text(1, "Texto seguinte.", 690.0)
    # 160 pt free above a 72 pt bottom margin: the picture fitted there.
    assert not dr._ordered_image_layouts_match(
        [source], [picture], [text(0, "Texto anterior.", 240.0), following], 72.0
    )
    # 18 pt free: it did not fit and Word moves it to the next page.
    assert dr._ordered_image_layouts_match(
        [source], [picture], [text(0, "Texto anterior.", 92.5), following], 72.0
    )


def test_a_hanging_paragraph_of_several_runs_keeps_its_first_line_bound():
    from xml.etree import ElementTree

    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = ElementTree.fromstring(
        f"<w:document {namespace}><w:body>"
        '<w:p><w:pPr><w:ind w:left="720" w:hanging="720"/></w:pPr>'
        "<w:r><w:rPr><w:b/></w:rPr><w:t>AUTOR, Fulano.</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> Titulo sintetico.</w:t></w:r></w:p>'
        '<w:sectPr><w:pgMar w:top="1701" w:right="1134" w:bottom="1134" w:left="1701"/></w:sectPr>'
        "</w:body></w:document>"
    )
    expectations = dr._word_text_expectations(
        {"word/document.xml": document}, active_content_names={"word/document.xml"}
    )
    assert [expectation.paragraph_hanging for expectation in expectations] == [-36.0, -36.0]

    def fragment(value: str, x: float, width: float, weight: int) -> dr._PositionedText:
        return dr._PositionedText(
            page=0, text=value, x=x, y=748.0, font_size=11.0, right=x + width,
            bottom=745.5, top=756.85, font_weight=weight, page_width=595.3,
            page_height=841.9, strict_text=value, font_family=expectations[0].font_family,
        )

    # Word: the first line starts at the margin, 36 pt left of the indent.
    at_margin = [fragment("AUTOR, Fulano.", 85.05, 80.0, 700), fragment(" Titulo sintetico.", 165.05, 90.0, 400)]
    assert dr._text_sizes_match(expectations, at_margin, [])
    # Further left than margin + indent - hanging is still refused.
    too_far = [fragment("AUTOR, Fulano.", 40.0, 80.0, 700), fragment(" Titulo sintetico.", 120.0, 90.0, 400)]
    assert not dr._text_sizes_match(expectations, too_far, [])


def _quote_expectation(**changes) -> dr._WordTextExpectation:
    from dataclasses import replace

    base = dr._WordTextExpectation(
        "citacao", 10.0, (0, 0, 0), False, False, False, "both",
        line_height=12.0, left_indent=113.4, left_margin=85.05,
    )
    return replace(base, **changes)


def _quote_line(page: int, x: float) -> dr._PositionedText:
    return dr._PositionedText(
        page=page, text="citacao", x=x, y=500.0, font_size=10.0, right=x + 40.0,
        bottom=497.5, top=507.0, page_width=595.3, page_height=841.9,
        strict_text="citacao", font_family=None,
    )


def test_mirrored_margins_bind_the_indent_by_page_parity():
    from xml.etree import ElementTree

    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = ElementTree.fromstring(
        f"<w:document {namespace}><w:body><w:p><w:r><w:t>Texto.</w:t></w:r></w:p>"
        '<w:sectPr><w:pgMar w:top="1701" w:right="1134" w:bottom="1134" w:left="1701"/></w:sectPr>'
        "</w:body></w:document>"
    )
    settings = ElementTree.fromstring(f"<w:settings {namespace}><w:mirrorMargins/></w:settings>")
    plain = dr._word_text_expectations(
        {"word/document.xml": document}, active_content_names={"word/document.xml"}
    )
    mirrored = dr._word_text_expectations(
        {"word/document.xml": document, "word/settings.xml": settings},
        active_content_names={"word/document.xml"},
    )
    assert (plain[0].left_margin, plain[0].even_left_margin) == (85.05, None)
    assert (mirrored[0].left_margin, mirrored[0].even_left_margin) == (85.05, 56.7)

    quote = _quote_expectation(even_left_margin=56.7)
    # Page 1 (odd): 3 cm margin + 4 cm; page 2 (even): mirrored 2 cm + 4 cm.
    assert dr._text_sizes_match([quote], [_quote_line(0, 198.45)], [])
    assert dr._text_sizes_match([quote], [_quote_line(1, 170.1)], [])
    # The parity swapped: an odd page laid out with the even page's margin.
    assert not dr._text_sizes_match([quote], [_quote_line(0, 170.1)], [])
    # Without mirrored margins the even page keeps the 3 cm margin.
    assert not dr._text_sizes_match([_quote_expectation()], [_quote_line(1, 170.1)], [])


def test_a_picture_kept_on_a_page_it_does_not_fit_is_refused():
    def text(value: str, baseline: float) -> dr._PositionedText:
        return dr._PositionedText(
            page=0, text=value, x=85.0, y=baseline, font_size=11.0,
            right=85.0 + 5.5 * len(value), bottom=baseline - 2.5, top=baseline + 8.5,
            page_width=595.3, page_height=841.9, strict_text=value,
        )

    source = dr._WordImageLayout(
        170.0, 51.0, "inline", "center", None, None, "Texto anterior.", None, 0, None,
    )
    # 18 pt above a 72 pt bottom margin: drawn there it crosses the margin.
    crossing = dr._PdfImageLayout(
        page=0, left=212.6, bottom=38.0, right=382.6, top=89.0,
        page_width=595.3, page_height=841.9,
    )
    assert not dr._ordered_image_layouts_match(
        [source], [crossing], [text("Texto anterior.", 92.5)], 72.0
    )
    inside = dr._PdfImageLayout(
        page=0, left=212.6, bottom=310.0, right=382.6, top=361.0,
        page_width=595.3, page_height=841.9,
    )
    assert dr._ordered_image_layouts_match(
        [source], [inside], [text("Texto anterior.", 366.0)], 72.0
    )


def test_a_numbered_paragraph_cannot_be_verified_without_its_list_label():
    """Word draws the label from numbering.xml; the oracle does not model it,
    so a PDF that drops it must not be accepted."""
    word, pdf = _pair("word16-branded-simple")
    paragraph = '<w:p><w:r><w:t xml:space="preserve">A parte sintética alegou uma ocorrência.</w:t></w:r></w:p>'
    numbered = paragraph.replace(
        "<w:p>",
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>',
        1,
    )
    with pytest.raises(ValueError):
        dr._validate_pdf_fidelity(_docx_with(word, "word/document.xml", paragraph, numbered), pdf)
    # Numbering inherited from the paragraph's style is the same.
    style_numbered = _docx_with(
        word,
        "word/styles.xml",
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr>',
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>'
        '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr>'
        '<w:numPr><w:numId w:val="3"/></w:numPr>',
    )
    with pytest.raises(ValueError):
        dr._validate_pdf_fidelity(style_numbered, pdf)


def test_a_missing_running_footer_is_refused():
    word, pdf = _pair("word16-branded-simple")

    def drop_footer(operations: list) -> list:
        start, end = _drawing_block(operations, _shows_text("gina"))
        return operations[:start] + operations[end:]

    _assert_refused(word, _pdf_with_page_operations(pdf, 2, drop_footer))


def test_a_declared_alignment_the_render_does_not_have_is_refused():
    word, pdf = _pair("word16-branded-simple")
    # The centred title declared right-aligned.
    title = '<w:spacing w:before="2400" w:after="480"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>'
    _assert_refused(
        _docx_with(word, "word/styles.xml", title, title.replace("center", "right")), pdf
    )


def test_a_picture_missing_from_the_pdf_is_refused():
    word, pdf = _pair("word16-branded-v2")

    def drop_seal(operations: list) -> list:
        start, end = _drawing_block(
            operations,
            lambda block: any(
                operator == b"Do" and str(operands[0]) == "/Image22"
                for operands, operator in block
            ),
        )
        return operations[:start] + operations[end:]

    _assert_refused(word, _pdf_with_page_operations(pdf, 3, drop_seal))


@pytest.mark.parametrize("page", [0, 2])
def test_the_watermarked_background_painted_over_the_body_is_refused(page):
    """The V2 watermark is composed into the page background picture."""
    word, pdf = _pair("word16-branded-v2")

    def paint_background_last(operations: list) -> list:
        start, end = _drawing_block(operations, _draws_image)
        return operations[:start] + operations[end:] + operations[start:end]

    _assert_refused(word, _pdf_with_page_operations(pdf, page, paint_background_last))
