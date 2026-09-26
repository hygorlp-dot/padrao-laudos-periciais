"""The product's default professional report template, derived from the editorial profile.

The template is generated, never downloaded: a deterministic DOCX built from the
approved report's editorial profile (fonts, sizes, spacing, margins) with a
cover, a table of contents area, the canonical content area and a signature
block.  It carries no case data of its own; the case enters only through the
declared binding placeholders and the CANONICAL_REPORT content control.
"""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .report_foundation import EditorialProfile
from .report_template import TemplateBinding, TemplateBindingManifest

DEFAULT_TEMPLATE_ID = "PRODUCT-DEFAULT-REPORT-V1"
DEFAULT_TEMPLATE_FILENAME = "modelo-padrao-laudo.docx"
TOC_CONTROL_TAG = "TOC_ENTRIES"
_BINDINGS = (
    ("PROCESS_NUMBER", "[[PROCESS_NUMBER]]"),
    ("COURT", "[[COURT]]"),
    ("EXPERT_FULL_NAME", "[[EXPERT_FULL_NAME]]"),
    ("EXPERT_TITLE", "[[EXPERT_TITLE]]"),
    ("EXPERT_REGISTRATION", "[[EXPERT_REGISTRATION]]"),
)
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PAGE_WIDTH = 11906  # A4 in twentieths of a point
_PAGE_HEIGHT = 16838
# A fixed timestamp keeps the package byte-identical for one profile.
_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def default_template_manifest() -> TemplateBindingManifest:
    return TemplateBindingManifest(
        "1.0.0", DEFAULT_TEMPLATE_ID, "DOCX",
        tuple(TemplateBinding(field, placeholder) for field, placeholder in _BINDINGS),
    )


def _twips(centimetres: float) -> int:
    return round(centimetres * 567)


def _run(text: str, *, bold: bool = False, size: int | None = None) -> str:
    properties = ""
    if bold or size:
        properties = "<w:rPr>" + ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "") + "</w:rPr>"
    return f'<w:r>{properties}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _paragraph(content: str, style: str | None = None, *, page_break_before: bool = False) -> str:
    properties = ""
    if style or page_break_before:
        properties = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + ("<w:pageBreakBefore/>" if page_break_before else "") + "</w:pPr>"
    return f"<w:p>{properties}{content}</w:p>"


def _field(instruction: str, result: str) -> str:
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {escape(instruction)} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{_run(result)}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def _control(tag: str, identity: int, content: str) -> str:
    return (
        f'<w:sdt><w:sdtPr><w:alias w:val="{tag}"/><w:tag w:val="{tag}"/><w:id w:val="{identity}"/></w:sdtPr>'
        f"<w:sdtContent>{content}</w:sdtContent></w:sdt>"
    )


def _document(profile: EditorialProfile) -> str:
    margins = (
        _twips(profile.margin_top_cm), _twips(profile.margin_right_cm),
        _twips(profile.margin_bottom_cm), _twips(profile.margin_left_cm),
    )
    toc_placeholder = (
        "<w:p><w:pPr><w:pStyle w:val=\"TOC1\"/></w:pPr>"
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\u </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{_run('O sumário é gerado com o laudo.')}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    body = "".join((
        _paragraph(_run("LAUDO PERICIAL"), "Title"),
        _paragraph(_run("[[PROCESS_NUMBER]]"), "CoverText"),
        _paragraph(_run("[[COURT]]"), "CoverText"),
        _paragraph(_run("SUMÁRIO"), "TOCHeading", page_break_before=True),
        _control(TOC_CONTROL_TAG, 1001, toc_placeholder),
        _control("CANONICAL_REPORT", 1002, _paragraph(_run("O conteúdo do laudo é inserido aqui."))),
        _paragraph(_run("[[EXPERT_FULL_NAME]]", bold=True), "Signature"),
        _paragraph(_run("[[EXPERT_TITLE]]"), "Signature"),
        _paragraph(_run("[[EXPERT_REGISTRATION]]"), "Signature"),
    ))
    section = (
        '<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader1"/>'
        '<w:footerReference w:type="default" r:id="rIdFooter1"/>'
        f'<w:pgSz w:w="{_PAGE_WIDTH}" w:h="{_PAGE_HEIGHT}"/>'
        f'<w:pgMar w:top="{margins[0]}" w:right="{margins[1]}" w:bottom="{margins[2]}" w:left="{margins[3]}" w:header="709" w:footer="709" w:gutter="0"/>'
        "</w:sectPr>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}"><w:body>{body}{section}</w:body></w:document>'
    )


def _style(style_id: str, name: str, *, paragraph: str = "", run: str = "", based_on: str | None = "Normal", next_style: str | None = None, extra: str = "") -> str:
    return (
        f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/>'
        + (f'<w:basedOn w:val="{based_on}"/>' if based_on else "")
        + (f'<w:next w:val="{next_style}"/>' if next_style else "")
        + extra
        + (f"<w:pPr>{paragraph}</w:pPr>" if paragraph else "")
        + (f"<w:rPr>{run}</w:rPr>" if run else "")
        + "</w:style>"
    )


def _styles(profile: EditorialProfile) -> str:
    typography = profile.effective_typography
    font = escape(profile.font_family)
    fonts = f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}" w:eastAsia="{font}"/>'
    def size(points: int) -> str:
        return f'<w:sz w:val="{points * 2}"/><w:szCs w:val="{points * 2}"/>'
    justify = "both" if profile.alignment == "JUSTIFIED" else "left"
    line = round(240 * profile.line_spacing)
    text_width = _PAGE_WIDTH - _twips(profile.margin_left_cm) - _twips(profile.margin_right_cm)
    bold = "<w:b/><w:bCs/>" if typography.headings_bold else ""
    heading_spacing = f'<w:spacing w:before="{typography.heading_space_before_pt * 20}" w:after="{typography.heading_space_after_pt * 20}" w:line="{line}" w:lineRule="auto"/>'
    headings = "".join(
        _style(
            f"Heading{level}", f"heading {level}", next_style="Normal",
            paragraph=f'<w:keepNext/><w:keepLines/>{heading_spacing}<w:ind w:firstLine="0"/><w:jc w:val="left"/><w:outlineLvl w:val="{level - 1}"/>',
            run=f"{bold}{size(points)}",
        )
        for level, points in ((1, typography.heading1_pt), (2, typography.heading2_pt), (3, typography.heading3_pt))
    )
    tocs = "".join(
        _style(
            f"TOC{level}", f"toc {level}", next_style="Normal",
            paragraph=f'<w:tabs><w:tab w:val="right" w:leader="none" w:pos="{text_width}"/></w:tabs><w:spacing w:after="60"/><w:ind w:left="{(level - 1) * 284}" w:firstLine="0"/><w:jc w:val="left"/>',
        )
        for level in (1, 2, 3)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:styles xmlns:w="{_W_NS}">'
        f"<w:docDefaults><w:rPrDefault><w:rPr>{fonts}{size(profile.body_font_pt)}<w:lang w:val=\"pt-BR\"/></w:rPr></w:rPrDefault>"
        f'<w:pPrDefault><w:pPr><w:spacing w:after="{typography.paragraph_space_after_pt * 20}" w:line="{line}" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
        f'<w:pPr><w:ind w:firstLine="{_twips(profile.first_line_indent_cm)}"/><w:jc w:val="{justify}"/></w:pPr>'
        f"<w:rPr>{fonts}{size(profile.body_font_pt)}</w:rPr></w:style>"
        + headings
        + tocs
        + _style("Title", "Title", paragraph='<w:spacing w:before="2400" w:after="480"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>', run=f"<w:b/><w:bCs/>{size(typography.heading1_pt + 6)}")
        + _style("CoverText", "Cover Text", paragraph='<w:spacing w:after="240"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>', run=size(profile.body_font_pt + 1))
        + _style("TOCHeading", "TOC Heading", paragraph='<w:spacing w:after="240"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>', run=f"<w:b/><w:bCs/>{size(typography.heading1_pt)}")
        + _style("Caption", "caption", next_style="Normal", paragraph='<w:spacing w:before="60" w:after="240"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>', run=size(profile.caption_font_pt))
        + _style("TableText", "Table Text", paragraph='<w:spacing w:after="0"/><w:ind w:firstLine="0"/><w:jc w:val="left"/>', run=size(profile.table_font_pt))
        + _style("Bibliography", "Bibliography", paragraph='<w:spacing w:after="240" w:line="240" w:lineRule="auto"/><w:ind w:left="0" w:firstLine="0"/><w:jc w:val="left"/>')
        + _style("Signature", "Signature", paragraph='<w:spacing w:after="0"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
        + _style("Header", "header", paragraph='<w:ind w:firstLine="0"/><w:jc w:val="right"/>', run=size(max(profile.caption_font_pt, 8)))
        + _style("Footer", "footer", paragraph='<w:ind w:firstLine="0"/><w:jc w:val="center"/>', run=size(max(profile.caption_font_pt, 8)))
        + '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblCellMar><w:left w:w="108" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>'
        + "</w:styles>"
    )


def _header() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{_W_NS}">{_paragraph(_run("Laudo técnico pericial"), "Header")}</w:hdr>'
    )


def _footer() -> str:
    # "3 de 12": one literal between the two fields, the shape the fidelity
    # oracle binds per page.
    content = _field("PAGE", "1") + _run(" de ") + _field("NUMPAGES", "1")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr xmlns:w="{_W_NS}">{_paragraph(content, "Footer")}</w:ftr>'
    )


def default_report_template(profile: EditorialProfile) -> bytes:
    """The default template for ``profile``, byte-identical for the same profile."""
    if type(profile) is not EditorialProfile:
        raise TypeError("expected EditorialProfile")
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
            '<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
            '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '<Override PartName="/docProps/custom.xml" ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" Target="docProps/custom.xml"/>'
            "</Relationships>"
        ),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
            '<Relationship Id="rIdHeader1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>'
            '<Relationship Id="rIdFooter1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": _document(profile),
        "word/styles.xml": _styles(profile),
        "word/settings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:settings xmlns:w="{_W_NS}"><w:defaultTabStop w:val="708"/><w:autoHyphenation w:val="false"/>'
            '<w:characterSpacingControl w:val="doNotCompress"/></w:settings>'
        ),
        "word/header1.xml": _header(),
        "word/footer1.xml": _footer(),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Laudo pericial</dc:title></cp:coreProperties>'
        ),
        "docProps/app.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Sistema Pericial</Application></Properties>'
        ),
        "docProps/custom.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            '<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" name="TEMPLATE_ID">'
            f"<vt:lpwstr>{DEFAULT_TEMPLATE_ID}</vt:lpwstr></property></Properties>"
        ),
    }
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for name, content in parts.items():
            info = ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = ZIP_DEFLATED
            package.writestr(info, content.encode("utf-8"))
    return output.getvalue()
