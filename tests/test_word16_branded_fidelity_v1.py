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
