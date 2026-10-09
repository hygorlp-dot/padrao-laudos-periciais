"""The product's default professional report template, derived from the editorial profile.

The template is generated, never downloaded: a deterministic DOCX built from the
approved report's editorial profile (fonts, sizes, spacing, margins) with a
cover, a table of contents area, the canonical content area and a signature
block.  It carries no case data of its own; the case enters only through the
declared binding placeholders and the CANONICAL_REPORT content control.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .report_foundation import (
    DEFAULT_PROFILE_PRESENTATION,
    EditorialProfile,
    ExpertMasterProfile,
    court_registration_line,
    expert_profile_digest,
)
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


def default_template_manifest(*, professional: bool = False) -> TemplateBindingManifest:
    bindings = _BINDINGS + tuple((field, "[[" + field + "]]") for field in ("EXPERT_COVER_NAME", "PARTICIPANTS_ACTIVE", "PARTICIPANTS_PASSIVE", "ACTION_TYPE", "PROTOCOL_OPENING", "REPORT_CITY_DATE")) if professional else _BINDINGS
    return TemplateBindingManifest(
        "1.0.0", DEFAULT_TEMPLATE_ID, "DOCX",
        tuple(TemplateBinding(field, placeholder) for field, placeholder in bindings),
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


def _document(profile: EditorialProfile, *, professional: bool = False) -> str:
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
    if professional:
        first_page = "".join((
            _paragraph(_run("[[COURT]]", bold=True), "CoverText"),
            _paragraph(_run("AUTOS: [[PROCESS_NUMBER]]")),
            _paragraph(_run("AUTOR: [[PARTICIPANTS_ACTIVE]]")),
            _paragraph(_run("RÉU: [[PARTICIPANTS_PASSIVE]]")),
            _paragraph(_run("TIPO DE AÇÃO: [[ACTION_TYPE]]")),
            _paragraph(_run("PERITO: [[EXPERT_COVER_NAME]]")),
            _paragraph(_run("LAUDO PERICIAL"), "Title"),
            _paragraph(_run("[[PROTOCOL_OPENING]]")),
            _paragraph(_run("[[REPORT_CITY_DATE]]"), "CoverText"),
        ))
        marker = _paragraph(_run("SUMÁRIO"), "TOCHeading", page_break_before=True)
        body = first_page + body[body.index(marker):]
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


def _styles(profile: EditorialProfile, *, professional: bool = False) -> str:
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
        + ('<w:style w:type="table" w:styleId="ProfessionalChapterBand"><w:name w:val="Professional Chapter Band"/><w:tcPr><w:shd w:val="clear" w:fill="D9D9D9"/></w:tcPr></w:style>' if professional else '')
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


def _footer(*, professional: bool = False) -> str:
    # "3 de 12": one literal between the two fields, the shape the fidelity
    # oracle binds per page.
    content = (_run("Página ") if professional else "") + _field("PAGE", "1") + _run(" de ") + _field("NUMPAGES", "1")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr xmlns:w="{_W_NS}">{_paragraph(content, "Footer")}</w:ftr>'
    )


def default_report_template(profile: EditorialProfile, *, professional: bool = False) -> bytes:
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
        "word/document.xml": _document(profile, professional=professional),
        "word/styles.xml": _styles(profile, professional=professional),
        "word/settings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:settings xmlns:w="{_W_NS}"><w:defaultTabStop w:val="708"/><w:autoHyphenation w:val="false"/>'
            '<w:characterSpacingControl w:val="doNotCompress"/></w:settings>'
        ),
        "word/header1.xml": _header(),
        "word/footer1.xml": _footer(professional=professional),
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


# --- Modelo padrao V2: identidade visual da pericia (#271) -------------------
#
# O V1 continua byte-identico. O V2 nasce do snapshot de configuracoes da pericia
# (marca, apresentacao, ativos) e do laudo aprovado: capa com a identificacao do
# processo, cabecalho com logotipo e identidade, rodape "Pagina X de Y",
# distancias de cabecalho e rodape do perfil editorial, estilo de citacao longa
# e, quando configurados, fundo e marca d'agua. Fundo, marca d'agua e linha
# separadora sao uma unica imagem de pagina, opaca e pre-composta, ancorada atras
# do texto na parte do cabecalho: o validador de fidelidade recusa transparencia
# e confere a posicao exata de imagem ancorada em cada pagina.

BRANDED_TEMPLATE_ID = "PRODUCT-DEFAULT-REPORT-V2"
_BRANDED_BINDINGS = (
    ("PROCESS_NUMBER", "[[PROCESS_NUMBER]]"),
    ("COURT", "[[COURT]]"),
    ("PARTICIPANTS_ACTIVE", "[[PARTICIPANTS_ACTIVE]]"),
    ("PARTICIPANTS_PASSIVE", "[[PARTICIPANTS_PASSIVE]]"),
    ("EXPERT_FULL_NAME", "[[EXPERT_FULL_NAME]]"),
    ("EXPERT_TITLE", "[[EXPERT_TITLE]]"),
    ("EXPERT_REGISTRATION", "[[EXPERT_REGISTRATION]]"),
)
# Nome da propriedade que amarra o texto fixo do cabecalho ao perfil profissional
# usado para gerar o modelo; a vinculacao recusa o modelo com outro perfil.
EXPERT_PROFILE_DIGEST_PROPERTY = "EXPERT_PROFILE_DIGEST"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_EMU_PER_CM = 360_000
_RASTER_DPI = 150


def branded_template_manifest(*, professional: bool = False) -> TemplateBindingManifest:
    bindings = _BRANDED_BINDINGS + tuple((field, "[[" + field + "]]") for field in ("ACTION_TYPE", "PROTOCOL_OPENING", "REPORT_CITY_DATE")) if professional else _BRANDED_BINDINGS
    return TemplateBindingManifest(
        "1.0.0", BRANDED_TEMPLATE_ID, "DOCX",
        tuple(TemplateBinding(field, placeholder) for field, placeholder in bindings),
    )


@dataclass(frozen=True, slots=True)
class TemplateImage:
    """Imagem PNG ou JPEG ja validada na instalacao, com o tamanho em pixels."""
    content: bytes
    media_type: str
    width_px: int
    height_px: int

    def __post_init__(self):
        if self.media_type not in ("image/png", "image/jpeg") or type(self.content) is not bytes or not self.content:
            raise ValueError("template image must be PNG or JPEG")
        if any(type(value) is not int or value < 1 for value in (self.width_px, self.height_px)):
            raise ValueError("template image size is invalid")

    @property
    def extension(self) -> str:
        return "png" if self.media_type == "image/png" else "jpeg"


@dataclass(frozen=True, slots=True)
class TemplateBranding:
    presentation: object
    branding: object
    expert: ExpertMasterProfile
    logo: TemplateImage | None = None
    symbol: TemplateImage | None = None
    watermark: TemplateImage | None = None
    background: TemplateImage | None = None
    signature: TemplateImage | None = None
    seal: TemplateImage | None = None
    # "Recife, 2026": cidade da capa (ou do contato) e ano do laudo aprovado.
    city_year: str | None = None


def _hex(color: str) -> str:
    return color.lstrip("#").upper()


class _Media:
    """Partes de imagem e relacionamentos por parte do pacote."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.relationships: dict[str, list[tuple[str, str]]] = {}
        self._identity = 2000

    def add(self, part: str, name: str, content: bytes) -> tuple[str, int]:
        path = f"media/{name}"
        self.files[f"word/{path}"] = content
        entries = self.relationships.setdefault(part, [])
        relationship = f"rIdImg{len(entries) + 1}"
        entries.append((relationship, path))
        self._identity += 1
        return relationship, self._identity


def _picture(relationship: str, identity: int, name: str, cx: int, cy: int) -> str:
    return (
        f'<a:graphic xmlns:a="{_A_NS}"><a:graphicData uri="{_PIC_NS}">'
        f'<pic:pic xmlns:pic="{_PIC_NS}"><pic:nvPicPr><pic:cNvPr id="{identity}" name="{escape(name)}" descr="{escape(name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{relationship}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic>"
    )


def _inline_image(relationship: str, identity: int, name: str, cx: int, cy: int) -> str:
    return (
        f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0" xmlns:wp="{_WP_NS}">'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{identity}" name="{escape(name)}" descr="{escape(name)}"/>'
        f"{_picture(relationship, identity, name, cx, cy)}</wp:inline></w:drawing></w:r>"
    )


def _page_anchor(relationship: str, identity: int, name: str, cx: int, cy: int) -> str:
    # Ancorada na pagina, atras do texto, sem quebra: a posicao (0, 0) e o
    # tamanho da pagina sao conferidos no PDF derivado.
    return (
        f'<w:r><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="0" '
        f'behindDoc="1" locked="1" layoutInCell="1" allowOverlap="1" xmlns:wp="{_WP_NS}">'
        '<wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="page"><wp:posOffset>0</wp:posOffset></wp:positionV>'
        f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        f'<wp:docPr id="{identity}" name="{escape(name)}" descr="{escape(name)}"/><wp:cNvGraphicFramePr/>'
        f"{_picture(relationship, identity, name, cx, cy)}</wp:anchor></w:drawing></w:r>"
    )


def _scaled(image: TemplateImage, width_cm: float) -> tuple[int, int]:
    cx = round(width_cm * _EMU_PER_CM)
    return cx, max(1, round(cx * image.height_px / image.width_px))


def _fitted(image: TemplateImage, max_width_cm: float, max_height_cm: float) -> tuple[int, int]:
    scale = min(max_width_cm / image.width_px, max_height_cm / image.height_px)
    return max(1, round(image.width_px * scale * _EMU_PER_CM)), max(1, round(image.height_px * scale * _EMU_PER_CM))


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _opened(image: TemplateImage):
    from PIL import Image
    opened = Image.open(BytesIO(image.content))
    opened.load()
    return opened.convert("RGBA")


def _text_mark(text: str, height_px: int):
    """Marca d'agua de texto desenhada como imagem: nao entra no texto do laudo."""
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for candidate in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            font = ImageFont.truetype(candidate, height_px)
            break
        except OSError:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(height_px)
        except (OSError, TypeError) as exc:
            raise ValueError("text watermark font is unavailable on this machine") from exc
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    mark = Image.new("RGBA", (right - left + 8, bottom - top + 8), (0, 0, 0, 0))
    ImageDraw.Draw(mark).text((4 - left, 4 - top), text, font=font, fill=(0, 0, 0, 255))
    return mark


def page_raster(*, page_width_pt: float, page_height_pt: float, background, background_image: TemplateImage | None,
                watermark, watermark_image: TemplateImage | None, rule: tuple[float, str, float] | None) -> bytes | None:
    """Fundo, marca d'agua e linha separadora numa imagem de pagina opaca.

    A marca d'agua e misturada ao fundo com a opacidade configurada (limitada no
    dominio), de modo que o resultado seja uma imagem sem transparencia. Sem
    nada a desenhar, nao ha imagem de pagina.
    """
    from PIL import Image, ImageDraw
    background_kind = getattr(background, "kind", None)
    kind_value = getattr(background_kind, "value", background_kind)
    draws_background = kind_value in ("SOLID", "IMAGE")
    draws_watermark = watermark is not None
    if not draws_background and not draws_watermark and rule is None:
        return None
    width = max(1, round(page_width_pt / 72 * _RASTER_DPI))
    height = max(1, round(page_height_pt / 72 * _RASTER_DPI))
    page = Image.new("RGB", (width, height), (255, 255, 255))
    if kind_value == "SOLID":
        page = Image.new("RGB", (width, height), _rgb(background.color))
    elif kind_value == "IMAGE":
        if background_image is None:
            raise ValueError("background image asset is missing")
        source = _opened(background_image).resize((width, height))
        # Fundo de imagem sempre clareado para manter o texto legivel.
        white = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        page = Image.blend(white, source, 0.25).convert("RGB")
    if draws_watermark:
        watermark_kind = getattr(watermark.kind, "value", watermark.kind)
        if watermark_kind == "TEXT":
            mark = _text_mark(watermark.text, max(12, round(height * 0.06)))
        else:
            if watermark_image is None:
                raise ValueError("watermark image asset is missing")
            mark = _opened(watermark_image)
        if watermark.rotation_degrees:
            mark = mark.rotate(watermark.rotation_degrees, expand=True, resample=Image.BICUBIC)
        target_width = max(1, round(width * watermark.scale))
        target_height = max(1, round(mark.height * target_width / mark.width))
        if target_height > height * 0.9:
            target_height = round(height * 0.9)
            target_width = max(1, round(mark.width * target_height / mark.height))
        mark = mark.resize((target_width, target_height))
        alpha = mark.getchannel("A").point(lambda value: round(value * watermark.opacity))
        layer = Image.new("RGB", mark.size, (0, 0, 0))
        layer.paste(mark.convert("RGB"))
        page.paste(layer, ((width - target_width) // 2, (height - target_height) // 2), alpha)
    if rule is not None:
        y_cm, color, thickness_pt = rule
        y = round(y_cm / 2.54 * _RASTER_DPI)
        stroke = max(1, round(thickness_pt / 72 * _RASTER_DPI))
        draw = ImageDraw.Draw(page)
        margin = round(2.0 / 2.54 * _RASTER_DPI)
        draw.rectangle((margin, y, width - margin, y + stroke - 1), fill=_rgb(color))
    output = BytesIO()
    page.save(output, "PNG", optimize=True)
    return output.getvalue()


def _identity_lines(expert: ExpertMasterProfile, header) -> list[str]:
    presentation = expert.presentation or DEFAULT_PROFILE_PRESENTATION
    lines = []
    if header.show_name:
        lines.append(expert.signature_name or expert.full_name)
    if header.show_title:
        title = expert.professional_title
        if presentation.show_registration_header and expert.registration:
            title = f"{title} · {expert.registration}"
        lines.append(title)
    if presentation.show_court_registration_header:
        registrations = court_registration_line(expert.court_registrations) if expert.court_registrations else expert.court_registration
        if registrations:
            lines.append(registrations)
    contact = expert.contact
    pieces = []
    if contact is not None and presentation.show_phone_header and contact.phone:
        pieces.append(contact.phone)
    if contact is not None and presentation.show_email_header and contact.email:
        pieces.append(contact.email)
    if pieces:
        lines.append(" · ".join(pieces))
    return lines


def _part(root: str, content: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:{root} xmlns:w="{_W_NS}" xmlns:r="{_R_NS}">{content}</w:{root}>'
    )


def branded_report_template(profile: EditorialProfile, branding: TemplateBranding, *, professional: bool = False) -> bytes:
    """Modelo padrao com a identidade visual da pericia; deterministico."""
    if type(profile) is not EditorialProfile or type(branding) is not TemplateBranding:
        raise TypeError("expected EditorialProfile and TemplateBranding")
    presentation = branding.presentation
    layout = profile.effective_layout
    cover, header, footer = presentation.cover, presentation.header, presentation.footer
    media = _Media()
    page_width_pt, page_height_pt = _PAGE_WIDTH / 20, _PAGE_HEIGHT / 20
    page_cx, page_cy = round(_PAGE_WIDTH * 635), round(_PAGE_HEIGHT * 635)
    text_width_cm = (_PAGE_WIDTH - _twips(profile.margin_left_cm) - _twips(profile.margin_right_cm)) / 567
    alignment = {"LEFT": "left", "CENTER": "center", "RIGHT": "right"}[getattr(header.alignment, "value", header.alignment)]

    def paragraph(content: str, style: str, *, jc: str | None = None, page_break: bool = False) -> str:
        properties = f'<w:pStyle w:val="{style}"/>' + ("<w:pageBreakBefore/>" if page_break else "") + (f'<w:jc w:val="{jc}"/>' if jc else "")
        return f"<w:p><w:pPr>{properties}</w:pPr>{content}</w:p>"

    # Imagens de pagina: corpo e capa podem diferir (fundo e marca so na capa,
    # so no corpo, ou nos dois).
    watermark = presentation.watermark if presentation.watermark.enabled else None
    watermark_image = branding.symbol if watermark is not None and getattr(watermark.kind, "value", watermark.kind) == "SYMBOL" else branding.watermark
    rule = None
    if header.enabled and header.separator_enabled:
        rule = (max(layout.header_distance_cm + 0.4, profile.margin_top_cm - 0.35), branding.branding.rule_color, header.separator_thickness_pt)
    background = presentation.background

    def raster(for_cover: bool) -> bytes | None:
        applies_background = background.apply_cover if for_cover else background.apply_body
        applies_watermark = watermark is not None and (watermark.apply_cover if for_cover else watermark.apply_body)
        return page_raster(
            page_width_pt=page_width_pt, page_height_pt=page_height_pt,
            background=background if applies_background else None, background_image=branding.background,
            watermark=watermark if applies_watermark else None, watermark_image=watermark_image,
            rule=None if for_cover else rule,
        )

    def header_part(part: str, *, for_cover: bool) -> str:
        content = []
        page_image = raster(for_cover)
        anchor = ""
        if page_image is not None:
            relationship, identity = media.add(part, f"{'capa' if for_cover else 'pagina'}-fundo.png", page_image)
            anchor = _page_anchor(relationship, identity, "Fundo da página (decorativo)", page_cx, page_cy)
        if not for_cover and header.enabled:
            if header.show_logo and branding.logo is not None:
                relationship, identity = media.add(part, f"logotipo.{branding.logo.extension}", branding.logo.content)
                cx, cy = _scaled(branding.logo, min(header.logo_width_cm, text_width_cm))
                content.append(paragraph(anchor + _inline_image(relationship, identity, "Logotipo do perito", cx, cy), "Header", jc=alignment))
                anchor = ""
            for line in _identity_lines(branding.expert, header):
                content.append(paragraph(anchor + _run(line), "Header", jc=alignment))
                anchor = ""
        if anchor or not content:
            content.insert(0, paragraph(anchor, "Header", jc=alignment))
        return _part("hdr", "".join(content))

    def footer_part(*, for_cover: bool) -> str:
        if for_cover:
            return _part("ftr", paragraph("", "Footer"))
        numbering = getattr(footer.page_numbering, "value", footer.page_numbering)
        number = _run("Página ") + _field("PAGE", "1") + (_run(" de ") + _field("NUMPAGES", "1") if numbering == "PAGE_X_OF_Y" else "")
        lines = [paragraph(number, "Footer")]
        if footer.institutional_text:
            lines.append(paragraph(_run(footer.institutional_text), "Footer"))
        expert = branding.expert
        if (expert.presentation or DEFAULT_PROFILE_PRESENTATION).show_email_footer and expert.contact is not None and expert.contact.email:
            lines.append(paragraph(_run(expert.contact.email), "Footer"))
        return _part("ftr", "".join(lines))

    body = []
    if cover.enabled:
        if cover.show_logo and branding.logo is not None:
            relationship, identity = media.add("document", f"capa-logotipo.{branding.logo.extension}", branding.logo.content)
            cx, cy = _fitted(branding.logo, min(8.0, text_width_cm), 4.0)
            body.append(paragraph(_inline_image(relationship, identity, "Logotipo do perito", cx, cy), "CoverLogo"))
    body.append(paragraph(_run(cover.title), "Title"))
    if cover.subtitle:
        body.append(paragraph(_run(cover.subtitle), "CoverText"))
    body.append(paragraph(_run("Processo nº ") + _run("[[PROCESS_NUMBER]]"), "CoverText"))
    body.append(paragraph(_run("[[COURT]]"), "CoverText"))
    body.append(paragraph(_run("Polo ativo: ", bold=True) + _run("[[PARTICIPANTS_ACTIVE]]"), "CoverParties"))
    body.append(paragraph(_run("Polo passivo: ", bold=True) + _run("[[PARTICIPANTS_PASSIVE]]"), "CoverParties"))
    if professional:
        body.append(paragraph(_run("Tipo de ação: ", bold=True) + _run("[[ACTION_TYPE]]"), "CoverParties"))
        body.append(paragraph(_run("[[PROTOCOL_OPENING]]"), "Normal"))
        body.append(paragraph(_run("[[REPORT_CITY_DATE]]"), "CoverCity"))
    if cover.enabled and cover.show_expert:
        body.append(paragraph(_run(branding.expert.full_name, bold=True), "CoverExpert"))
        body.append(paragraph(_run(branding.expert.professional_title), "CoverText"))
    if not professional and cover.enabled and cover.show_city_year and branding.city_year:
        body.append(paragraph(_run(branding.city_year), "CoverCity"))
    toc_placeholder = (
        "<w:p><w:pPr><w:pStyle w:val=\"TOC1\"/></w:pPr>"
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\u </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{_run('O sumário é gerado com o laudo.')}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    body.append(_paragraph(_run("SUMÁRIO"), "TOCHeading", page_break_before=True))
    body.append(_control(TOC_CONTROL_TAG, 1001, toc_placeholder))
    body.append(_control("CANONICAL_REPORT", 1002, _paragraph(_run("O conteúdo do laudo é inserido aqui."))))
    if branding.signature is not None:
        relationship, identity = media.add("document", f"assinatura.{branding.signature.extension}", branding.signature.content)
        cx, cy = _fitted(branding.signature, 6.0, 2.5)
        body.append(paragraph(_inline_image(relationship, identity, "Assinatura do perito", cx, cy), "Signature"))
    body.append(_paragraph(_run("[[EXPERT_FULL_NAME]]", bold=True), "Signature"))
    body.append(_paragraph(_run("[[EXPERT_TITLE]]"), "Signature"))
    body.append(_paragraph(_run("[[EXPERT_REGISTRATION]]"), "Signature"))
    if branding.seal is not None:
        relationship, identity = media.add("document", f"selo.{branding.seal.extension}", branding.seal.content)
        cx, cy = _fitted(branding.seal, 3.5, 3.5)
        body.append(paragraph(_inline_image(relationship, identity, "Selo profissional", cx, cy), "Signature"))

    headers = {"word/header1.xml": header_part("header1", for_cover=False)}
    footers = {"word/footer1.xml": footer_part(for_cover=False)}
    references = '<w:headerReference w:type="default" r:id="rIdHeader1"/><w:footerReference w:type="default" r:id="rIdFooter1"/>'
    if cover.enabled:
        headers["word/header2.xml"] = header_part("header2", for_cover=True)
        footers["word/footer2.xml"] = footer_part(for_cover=True)
        references += '<w:headerReference w:type="first" r:id="rIdHeader2"/><w:footerReference w:type="first" r:id="rIdFooter2"/>'
    margins = (_twips(profile.margin_top_cm), _twips(profile.margin_right_cm), _twips(profile.margin_bottom_cm), _twips(profile.margin_left_cm))
    section = (
        f"<w:sectPr>{references}"
        f'<w:pgSz w:w="{_PAGE_WIDTH}" w:h="{_PAGE_HEIGHT}"/>'
        f'<w:pgMar w:top="{margins[0]}" w:right="{margins[1]}" w:bottom="{margins[2]}" w:left="{margins[3]}" '
        f'w:header="{_twips(layout.header_distance_cm)}" w:footer="{_twips(layout.footer_distance_cm)}" w:gutter="0"/>'
        + ("<w:titlePg/>" if cover.enabled else "")
        + "</w:sectPr>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}"><w:body>{"".join(body)}{section}</w:body></w:document>'
    )
    styles = _branded_styles(profile, branding, alignment)
    if professional:
        styles = styles.replace('</w:styles>', '<w:style w:type="table" w:styleId="ProfessionalChapterBand"><w:name w:val="Professional Chapter Band"/><w:tcPr><w:shd w:val="clear" w:fill="D9D9D9"/></w:tcPr></w:style></w:styles>')

    def relationships(extra: list[tuple[str, str]]) -> str:
        image = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
        return "".join(f'<Relationship Id="{rid}" Type="{image}" Target="{target}"/>' for rid, target in extra)

    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>'
        + "".join(
            f'<Relationship Id="rId{kind.capitalize()}{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" Target="{kind}{index}.xml"/>'
            for kind, parts in (("header", headers), ("footer", footers)) for index in range(1, len(parts) + 1)
        )
        + relationships(media.relationships.get("document", []))
        + "</Relationships>"
    )
    overrides = "".join(
        f'<Override PartName="/{name}" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>'
        for kind, parts in (("header", headers), ("footer", footers)) for name in parts
    )
    defaults = "".join(
        f'<Default Extension="{extension}" ContentType="{content_type}"/>'
        for extension, content_type in (("png", "image/png"), ("jpeg", "image/jpeg"))
        if any(name.endswith("." + extension) for name in media.files)
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            + defaults
            + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
            + overrides
            + '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
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
        "word/_rels/document.xml.rels": document_rels,
        "word/document.xml": document,
        "word/styles.xml": styles,
        "word/settings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:settings xmlns:w="{_W_NS}"><w:defaultTabStop w:val="708"/><w:autoHyphenation w:val="false"/>'
            '<w:characterSpacingControl w:val="doNotCompress"/></w:settings>'
        ),
        **headers,
        **footers,
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
            f"<vt:lpwstr>{BRANDED_TEMPLATE_ID}</vt:lpwstr></property>"
            f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="3" name="{EXPERT_PROFILE_DIGEST_PROPERTY}">'
            f"<vt:lpwstr>{expert_profile_digest(branding.expert)}</vt:lpwstr></property></Properties>"
        ),
    }
    for part, entries in media.relationships.items():
        if part == "document":
            continue
        parts[f"word/_rels/{part}.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + relationships(entries) + "</Relationships>"
        )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        for name, content in parts.items():
            info = ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = ZIP_DEFLATED
            package.writestr(info, content.encode("utf-8"))
        for name, content in media.files.items():
            info = ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = ZIP_DEFLATED
            package.writestr(info, content)
    return output.getvalue()


def _branded_styles(profile: EditorialProfile, branding: TemplateBranding, header_alignment: str) -> str:
    """Estilos do V1 com a cor dos titulos, controle de paragrafo e citacao longa."""
    base = _styles(profile)
    layout = profile.effective_layout
    color = f'<w:color w:val="{_hex(branding.branding.heading_color)}"/>'
    # Titulos e titulo da capa na cor da identidade (contraste AA garantido no dominio).
    for style_id in ("Heading1", "Heading2", "Heading3", "Title", "TOCHeading"):
        marker = f'w:styleId="{style_id}">'
        start = base.index(marker)
        run_end = base.index("</w:rPr>", start)
        base = base[:run_end] + color + base[run_end:]
    # Controle de linhas viuvas/orfas e manter com o proximo no texto corrido.
    normal_ppr = '<w:pPr><w:ind w:firstLine='
    controls = ("<w:widowControl/>" if layout.widow_orphan_control else '<w:widowControl w:val="0"/>')
    base = base.replace(normal_ppr, "<w:pPr>" + controls + "<w:ind w:firstLine=", 1)
    if layout.heading1_page_break_before:
        marker = 'w:styleId="Heading1">'
        start = base.index(marker)
        # Ordem do esquema: keepNext, keepLines, pageBreakBefore.
        keep = base.index("<w:keepLines/>", start) + len("<w:keepLines/>")
        base = base[:keep] + "<w:pageBreakBefore/>" + base[keep:]
    header_style = '<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:firstLine="0"/><w:jc w:val="right"/></w:pPr>'
    if base.count(header_style) != 1:
        raise ValueError("default header style changed; branded styles cannot be derived")
    base = base.replace(
        '<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:firstLine="0"/><w:jc w:val="right"/></w:pPr>',
        f'<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/><w:ind w:firstLine="0"/><w:jc w:val="{header_alignment}"/></w:pPr>',
    )
    quote_size = max(8, profile.body_font_pt - layout.long_quote_font_pt_delta) * 2
    quote = _style(
        "Quote", "Quote", next_style="Normal",
        paragraph=(
            f'<w:spacing w:before="0" w:after="240" w:line="{round(240 * layout.long_quote_line_spacing)}" w:lineRule="auto"/>'
            f'<w:ind w:left="{_twips(layout.long_quote_indent_cm)}" w:firstLine="0"/><w:jc w:val="both"/>'
        ),
        run=f'<w:sz w:val="{quote_size}"/><w:szCs w:val="{quote_size}"/>',
    )
    cover = (
        _style("CoverLogo", "Cover Logo", paragraph='<w:spacing w:before="600" w:after="240"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
        + _style("CoverParties", "Cover Parties", paragraph='<w:spacing w:after="120"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
        + _style("CoverExpert", "Cover Expert", paragraph='<w:spacing w:before="1200" w:after="60"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
        + _style("CoverCity", "Cover City", paragraph='<w:spacing w:before="1200" w:after="0"/><w:ind w:firstLine="0"/><w:jc w:val="center"/>')
    )
    return base.replace("</w:styles>", quote + cover + "</w:styles>")
