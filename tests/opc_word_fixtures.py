"""Minimal *valid* OPC Word packages for tests.

A .docx without ``_rels/.rels`` is not a Word file at all: OPC offers no other
way to find the main part, so Word cannot open such a package.  Fixtures across
this suite used to omit it, which went unnoticed only while the delivery
boundary trusted the part *named* ``word/document.xml`` instead of resolving the
``officeDocument`` relationship that decides which part Word opens.  Both
boundaries now resolve it, so a fixture that claims to be a DOCX has to be one.

These builders add exactly the structure that makes a package real -- the
package relationship part, and a declared content type for every part stored --
and nothing more.  No product boundary was weakened to accommodate a stub.
"""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_DOCUMENT_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
DOCX_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
DOCM_MAIN_TYPE = "application/vnd.ms-word.document.macroEnabled.main+xml"
VBA_PROJECT_TYPE = "application/vnd.ms-office.vbaProject"
CONTENT_TYPES_PART = "[Content_Types].xml"
PACKAGE_RELATIONSHIP_PART = "_rels/.rels"
MAIN_DOCUMENT_PART = "word/document.xml"

# Every OPC package declares these two: the relationship parts themselves, and
# the XML parts (styles, numbering, docProps) that carry no Override.
_BASE_DEFAULTS = {
    "rels": "application/vnd.openxmlformats-package.relationships+xml",
    "xml": "application/xml",
}


def content_types(
    overrides: dict[str, str], defaults: dict[str, str] | None = None
) -> str:
    declared = {**_BASE_DEFAULTS, **(defaults or {})}
    entries = "".join(
        f'<Default Extension="{extension}" ContentType="{value}"/>'
        for extension, value in declared.items()
    ) + "".join(
        f'<Override PartName="{part}" ContentType="{value}"/>'
        for part, value in overrides.items()
    )
    return f'<Types xmlns="{CONTENT_TYPES_NS}">{entries}</Types>'


def package_relationships(target: str = MAIN_DOCUMENT_PART) -> str:
    """Exactly one package-level officeDocument relationship, as OPC requires."""
    return (
        f'<Relationships xmlns="{RELATIONSHIPS_NS}">'
        f'<Relationship Id="rId1" Type="{OFFICE_DOCUMENT_TYPE}" Target="{target}"/>'
        "</Relationships>"
    )


def word_field(code: str) -> str:
    """A field as Word writes it: begin / instruction / separate / result / end.

    Bare ``w:instrText`` is not a field to Word -- an instruction only means
    anything between a ``w:fldChar`` "begin" and the "end" closing it -- so a
    fixture standing for a real template carries the delimiters.
    """
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {code} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>1</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def word_package(
    document: str,
    *,
    main_type: str = DOCX_MAIN_TYPE,
    parts: dict[str, bytes | str] | None = None,
    overrides: dict[str, str] | None = None,
    defaults: dict[str, str] | None = None,
) -> bytes:
    """A valid minimal OPC Word package carrying ``document`` as its main part."""
    declared = {"/" + MAIN_DOCUMENT_PART: main_type, **(overrides or {})}
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(CONTENT_TYPES_PART, content_types(declared, defaults))
        package.writestr(PACKAGE_RELATIONSHIP_PART, package_relationships())
        package.writestr(MAIN_DOCUMENT_PART, document)
        for name, value in (parts or {}).items():
            package.writestr(name, value)
    return output.getvalue()


TEMPLATE_FIELD_CODES = ("TOC", "PAGE", "NUMPAGES", "SEQ Figure", "REF B", "PAGEREF B")


def bound_template_document() -> str:
    """The bound-template main part, carrying fields Word would actually run.

    The six field codes used to sit in bare ``w:instrText`` nodes with no
    ``w:fldChar`` around them.  Word reads those as nothing at all, and once the
    field sweep began judging one field at a time the whole run concatenated
    into a single unrecognised opcode.  Real delimiters make the fixture mean
    what it claims, and keep the protected field names each sweep looks for.
    """
    return (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>[[EXPERT_FULL_NAME]]</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>[[EXPERT_REGISTRATION]]</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>[[REPORT_ID]]</w:t></w:r></w:p>"
        '<w:sdt><w:sdtPr><w:tag w:val="CANONICAL_REPORT"/></w:sdtPr><w:sdtContent>'
        "<w:p><w:r><w:t>empty</w:t></w:r></w:p></w:sdtContent></w:sdt>"
        '<w:p><w:bookmarkStart w:id="1" w:name="B"/>'
        + "".join(word_field(code) for code in TEMPLATE_FIELD_CODES)
        + '<w:bookmarkEnd w:id="1"/></w:p>'
        "</w:body></w:document>"
    )
