"""Native Microsoft Word Desktop 16.x matrix for the local render worker.

These tests drive the real product path: the product-owned Job, the exact
machine-registered WINWORD.EXE, an exact ROT moniker, ExportAsFixedFormat, and
the fidelity oracle.  They are skipped wherever Word or pywin32 is absent, so
the suite stays runnable off a Windows workstation.

Every fixture is synthetic.  No real expert-report content, no network, no
credentials, no user data.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.backend_contract import delivery_renderer
from scripts.backend_contract.infrastructure.office_pdf import (
    LocalOfficePdfConverter,
    RendererUnavailable,
)


def _word_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import win32job  # noqa: F401

        from scripts.backend_contract.infrastructure import office_word_worker

        office_word_worker._machine_word_executable()
    except Exception:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _word_available(),
    reason="native matrix requires Microsoft Word Desktop 16.x and pywin32",
)

_DOCX_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_DOCM_MAIN_TYPE = "application/vnd.ms-word.document.macroEnabled.main+xml"
_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _native_temp_root() -> Path:
    """A fixed local drive outside OneDrive, as the render root policy requires."""
    root = Path(os.environ.get("SystemDrive", "C:") + "/tmp/plp-native")
    root.mkdir(parents=True, exist_ok=True)
    return root


# A representative package declares its own docDefaults.  Without word/styles.xml
# Word falls back to its built-in Normal style -- 1.08 line spacing and 8pt after --
# which the oracle cannot observe from the package, so a faithful render is
# rejected.  That is fail-closed and only reachable with a package the product
# never produces, but the native fixture must not depend on it.
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:docDefaults><w:rPrDefault><w:rPr>"
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="24"/>'
    "</w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>"
    '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
    "</w:pPr></w:pPrDefault></w:docDefaults>"
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
    '<w:name w:val="Normal"/></w:style></w:styles>'
)
_STYLES_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
)


def _package(*, main_type: str, body: str, macro: bool = False) -> bytes:
    overrides = (
        f'<Override PartName="/word/document.xml" ContentType="{main_type}"/>'
        f'<Override PartName="/word/styles.xml" ContentType="{_STYLES_TYPE}"/>'
    )
    document_relationships = [
        '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    ]
    parts = {"word/styles.xml": _STYLES.encode("utf-8")}
    if macro:
        overrides += (
            '<Override PartName="/word/vbaProject.bin" '
            'ContentType="application/vnd.ms-office.vbaProject"/>'
        )
        parts["word/vbaProject.bin"] = b"synthetic-not-executable"
        document_relationships.append(
            '<Relationship Id="rIdVba" '
            'Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" '
            'Target="vbaProject.bin"/>'
        )
    parts["word/_rels/document.xml.rels"] = (
        f'<Relationships xmlns="{_RELS_NS}">'
        + "".join(document_relationships)
        + "</Relationships>"
    ).encode("utf-8")
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>'
            f"{overrides}</Types>",
        )
        package.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{_RELS_NS}">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        package.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main">'
            f"<w:body>{body}<w:sectPr/></w:body></w:document>",
        )
        for name, value in parts.items():
            package.writestr(name, value)
    return output.getvalue()


_BODY = (
    '<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr>'
    "<w:t>Laudo sintetico de verificacao</w:t></w:r></w:p>"
    '<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr>'
    "<w:t>Anexo I - item de conferencia</w:t></w:r></w:p>"
)


def _running_word_identities() -> set[tuple[int, str]]:
    import win32api
    import win32con
    import win32process

    identities: set[tuple[int, str]] = set()
    for pid in win32process.EnumProcesses():
        handle = None
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            image = win32process.GetModuleFileNameEx(handle, 0)
            if Path(image).name.casefold() == "winword.exe":
                times = win32process.GetProcessTimes(handle)
                identities.add((pid, str(times["CreationTime"])))
        except Exception:
            continue
        finally:
            if handle is not None:
                handle.Close()
    return identities


def _record(evidence: dict) -> None:
    """Write the native evidence package, only when explicitly collecting it.

    Running the suite must not dirty a tracked file, so recording is opt-in via
    PLP_NATIVE_EVIDENCE=1.  The committed package is produced deliberately at the
    terminal candidate, not as a side effect of every local run.
    """
    if os.environ.get("PLP_NATIVE_EVIDENCE") != "1":
        return
    target = Path("artifacts/native-word-matrix-v1.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except ValueError:
            existing = {}
    existing.update(evidence)
    target.write_text(
        json.dumps(existing, indent=2, sort_keys=True, ensure_ascii=True),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("label", "source_format", "main_type", "macro"),
    (
        ("n01_docx", "DOCX", _DOCX_MAIN_TYPE, False),
        ("n02_docm", "DOCM", _DOCM_MAIN_TYPE, False),
    ),
)
def test_native_end_to_end_render(
    label: str, source_format: str, main_type: str, macro: bool
) -> None:
    """N-01/N-02/N-03/N-05: native render, source preserved, Job drained."""
    word = _package(main_type=main_type, body=_BODY, macro=macro)
    before = sha256(word).hexdigest()
    converter = LocalOfficePdfConverter(temp_root=_native_temp_root())

    pdf = converter.convert(word, source_format)

    assert sha256(word).hexdigest() == before, "authoritative Word bytes changed"
    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    delivery_renderer.validate_final_artifact(pdf, "PDF")

    _record(
        {
            label: {
                "sourceFormat": source_format,
                "carriesMacroPart": macro,
                "wordSha256Before": before,
                "wordSha256After": sha256(word).hexdigest(),
                "pdfSha256": sha256(pdf).hexdigest(),
                "pdfBytes": len(pdf),
                "rendererVersion": converter.renderer_version,
                "rendererType": converter.renderer_type,
            }
        }
    )


def test_native_docm_reaches_word_as_exact_authoritative_bytes() -> None:
    """F-02 native proof: the DOCM the product renders is the DOCM it was given."""
    word = _package(main_type=_DOCM_MAIN_TYPE, body=_BODY)
    seen: list[tuple[bytes, str]] = []

    class _Recording(LocalOfficePdfConverter):
        def convert(self, word_bytes: bytes, source_format: str) -> bytes:
            seen.append((word_bytes, source_format))
            return super().convert(word_bytes, source_format)

    pdf = delivery_renderer.render_final_pdf_candidate(
        word_content=word,
        word_format="DOCM",
        converter=_Recording(temp_root=_native_temp_root()),
    )

    assert seen and seen[0] == (word, "DOCM")
    assert pdf.startswith(b"%PDF-")
    _record(
        {
            "n02b_docm_exact_bytes": {
                "wordSha256": sha256(word).hexdigest(),
                "converterReceivedSha256": sha256(seen[0][0]).hexdigest(),
                "converterReceivedFormat": seen[0][1],
            }
        }
    )


@pytest.mark.skip(
    reason=(
        "GAP N-02c: proving a macro-carrying DOCM opens with macros disabled needs a "
        "structurally valid OLE vbaProject.bin. A placeholder byte string is rejected "
        "by Word itself, which proves nothing about the product, and fabricating a "
        "real VBA project would add executable content to the repository. Recorded as "
        "an open gap rather than an invented proof. That the macro part survives the "
        "product path untouched is proven without Word by "
        "tests/test_office_word_authority_v1.py::"
        "test_docm_reaches_converter_as_exact_authoritative_bytes."
    )
)
def test_native_macro_carrying_docm_opens_with_macros_disabled() -> None:
    raise AssertionError("unreachable: see skip reason")


def test_native_render_leaves_an_unrelated_word_instance_running() -> None:
    """N-04: an unrelated Word process must outlive the render."""
    import subprocess  # noqa: S404 - test-only, launches the user's own Word

    from scripts.backend_contract.infrastructure import office_word_worker

    executable = str(office_word_worker._machine_word_executable())
    bystander = subprocess.Popen([executable, "/q", "/x"])
    try:
        before = _running_word_identities()
        if not before:
            pytest.skip("no observable unrelated Word instance to protect")
        word = _package(main_type=_DOCX_MAIN_TYPE, body=_BODY)
        LocalOfficePdfConverter(temp_root=_native_temp_root()).convert(word, "DOCX")
        after = _running_word_identities()

        assert before <= after, "an unrelated Word process did not survive the render"
        _record(
            {
                "n04_user_word_survives": {
                    "identitiesBefore": sorted(f"{pid}:{created}" for pid, created in before),
                    "identitiesAfter": sorted(f"{pid}:{created}" for pid, created in after),
                }
            }
        )
    finally:
        bystander.terminate()
        bystander.wait(timeout=30)


def test_native_timeout_terminates_the_job_and_yields_no_pdf() -> None:
    """N-05: a deadline must drain the owned Job and produce no final PDF."""
    from scripts.backend_contract.infrastructure.office_pdf import WordRenderDeadlines

    word = _package(main_type=_DOCX_MAIN_TYPE, body=_BODY)
    converter = LocalOfficePdfConverter(
        temp_root=_native_temp_root(),
        deadlines=WordRenderDeadlines.uniform(0.05),
    )

    with pytest.raises(RendererUnavailable):
        converter.convert(word, "DOCX")


def test_native_docx_passes_the_full_delivery_path() -> None:
    """N-01 full path: Word's own PDF must satisfy the fidelity oracle unmodified."""
    word = _package(main_type=_DOCX_MAIN_TYPE, body=_BODY)

    pdf = delivery_renderer.render_final_pdf_candidate(
        word_content=word,
        word_format="DOCX",
        converter=LocalOfficePdfConverter(temp_root=_native_temp_root()),
    )

    assert pdf.startswith(b"%PDF-")
    _record(
        {
            "n01b_docx_full_path": {
                "wordSha256": sha256(word).hexdigest(),
                "pdfSha256": sha256(pdf).hexdigest(),
                "fidelity": "PASS",
            }
        }
    )


@pytest.mark.parametrize("blanks", (1, 2, 3, 5))
def test_native_empty_paragraphs_are_accepted(blanks: int) -> None:
    """N-09: Word's real line pitch must satisfy the blank-paragraph model."""
    run = '<w:r><w:rPr><w:sz w:val="24"/></w:rPr>'
    body = (
        f"<w:p>{run}<w:t>Primeiro paragrafo</w:t></w:r></w:p>"
        + "<w:p/>" * blanks
        + f"<w:p>{run}<w:t>Segundo paragrafo</w:t></w:r></w:p>"
    )
    word = _package(main_type=_DOCX_MAIN_TYPE, body=body)

    delivery_renderer.render_final_pdf_candidate(
        word_content=word,
        word_format="DOCX",
        converter=LocalOfficePdfConverter(temp_root=_native_temp_root()),
    )


def test_native_line_wrap_is_accepted() -> None:
    """N-10: a paragraph Word wraps across lines must not read as a relocation."""
    text = (
        "Primeira parte do paragrafo extenso que o Word precisa quebrar em varias "
        "linhas sucessivas para caber na largura util da pagina, sem que isso seja "
        "confundido com deslocamento vertical material do conteudo."
    )
    body = f'<w:p><w:r><w:rPr><w:sz w:val="24"/></w:rPr><w:t>{text}</w:t></w:r></w:p>'
    word = _package(main_type=_DOCX_MAIN_TYPE, body=body)

    delivery_renderer.render_final_pdf_candidate(
        word_content=word,
        word_format="DOCX",
        converter=LocalOfficePdfConverter(temp_root=_native_temp_root()),
    )


def test_native_roman_numerals_are_observable() -> None:
    """F-21 native proof: narrow glyphs in Word's own output are visible content."""
    run = '<w:r><w:rPr><w:sz w:val="24"/></w:rPr>'
    body = "".join(
        f"<w:p>{run}<w:t>{value}</w:t></w:r></w:p>"
        for value in ("Anexo I", "Inciso II", "Item III", "Peca l")
    )
    word = _package(main_type=_DOCX_MAIN_TYPE, body=body)
    converter = LocalOfficePdfConverter(temp_root=_native_temp_root())

    pdf = converter.convert(word, "DOCX")
    *_, unsafe = delivery_renderer._pdfium_visible_layout(pdf)

    assert unsafe is False
    delivery_renderer._validate_pdf_fidelity(word, pdf)


def test_native_environment_is_recorded() -> None:
    """Section 25 evidence: identify the machine, Word build and candidate commit."""
    import subprocess  # noqa: S404 - reads this repository's own HEAD

    import win32api

    from scripts.backend_contract.infrastructure import office_word_worker

    executable = office_word_worker._machine_word_executable()
    version = win32api.GetFileVersionInfo(str(executable), "\\")
    major = int(version["FileVersionMS"]) >> 16
    minor = int(version["FileVersionMS"]) & 0xFFFF
    build = int(version["FileVersionLS"]) >> 16
    revision = int(version["FileVersionLS"]) & 0xFFFF
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert major == 16
    _record(
        {
            "environment": {
                "candidateHead": head,
                "wordExecutable": str(executable),
                "wordFileVersion": f"{major}.{minor}.{build}.{revision}",
                "pywin32": getattr(win32api, "__file__", "unknown"),
                "python": sys.version.split()[0],
                "platform": sys.platform,
            }
        }
    )


def test_native_hyperlinked_cross_reference_is_accepted() -> None:
    ""r"N-12: Word emits a /Link annotation for a PAGEREF \h cross-reference."""
    run = '<w:r><w:rPr><w:sz w:val="24"/></w:rPr>'
    body = (
        '<w:p><w:bookmarkStart w:id="1" w:name="Secao1"/>'
        + run
        + '<w:t>Secao Um</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p><w:p>'
        + run
        + '<w:fldChar w:fldCharType="begin"/></w:r>'
        + run
        + r'<w:instrText xml:space="preserve"> PAGEREF Secao1 \h </w:instrText></w:r>'
        + run
        + '<w:fldChar w:fldCharType="separate"/></w:r>'
        + run
        + '<w:t>1</w:t></w:r>'
        + run
        + '<w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    word = _package(main_type=_DOCX_MAIN_TYPE, body=body)

    delivery_renderer.render_final_pdf_candidate(
        word_content=word,
        word_format="DOCX",
        converter=LocalOfficePdfConverter(temp_root=_native_temp_root()),
    )


def _author_word_template(directory: Path) -> Path:
    """Author a template in real Word: placeholders, the six protected field
    kinds, the CANONICAL_REPORT control and the TEMPLATE_ID property."""
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = win32com.client.Dispatch("Word.Application")
    app.Visible = False
    app.DisplayAlerts = 0
    try:
        document = app.Documents.Add()
        document.Content.InsertAfter(
            "[[EXPERT_FULL_NAME]]\r[[EXPERT_REGISTRATION]]\r"
            "[[REPORT_ID]]\rMarcador\r"
        )
        document.Bookmarks.Add("Marca", document.Paragraphs(4).Range)
        document.Content.InsertParagraphAfter()
        paragraph = document.Paragraphs(document.Paragraphs.Count)
        paragraph.Range.InsertAfter("corpo")
        control = document.ContentControls.Add(0, paragraph.Range)
        control.Tag = "CANONICAL_REPORT"
        control.Title = "CANONICAL_REPORT"
        for code in (
            "TOC \\o",
            "PAGE",
            "NUMPAGES",
            "SEQ Figura",
            "REF Marca",
            "PAGEREF Marca",
        ):
            document.Content.InsertParagraphAfter()
            end = document.Content.End - 1
            document.Fields.Add(
                Range=document.Range(end, end), Type=-1, Text=code, PreserveFormatting=False
            )
        document.CustomDocumentProperties.Add("TEMPLATE_ID", False, 4, "TEMPLATE-1")
        path = directory / "template.docx"
        document.SaveAs2(FileName=str(path), FileFormat=16)
        document.Close(SaveChanges=0)
    finally:
        app.Quit(SaveChanges=0)
        pythoncom.CoUninitialize()
    return path


def test_native_product_template_path_renders(tmp_path: Path) -> None:
    """OPC Case B: a Word-authored template must survive the whole product path.

    Template validation -> binding -> canonical injection -> pre-COM validation
    -> native render. This is the only test that exercises a genuine Word
    package rather than a hand-built ZIP, and it is what caught the canonical
    injection destroying the package's namespace prefixes.
    """
    import json as _json

    from scripts.backend_contract.infrastructure import office_word_worker
    from scripts.backend_contract.report_foundation import report_snapshot_from_mapping
    from scripts.backend_contract.report_template import (
        template_binding_manifest_from_mapping,
    )

    template = _author_word_template(tmp_path).read_bytes()
    report = report_snapshot_from_mapping(
        _json.loads(
            (Path(__file__).parents[1] / "tests/fixtures/report-snapshot-v1.json").read_text(
                encoding="utf-8"
            )
        )
    )
    manifest = template_binding_manifest_from_mapping(
        {
            "schema_version": "1.0.0",
            "template_id": "TEMPLATE-1",
            "output_kind": "DOCX",
            "bindings": [
                {"field": "EXPERT_FULL_NAME", "placeholder": "[[EXPERT_FULL_NAME]]"},
                {"field": "EXPERT_REGISTRATION", "placeholder": "[[EXPERT_REGISTRATION]]"},
                {"field": "REPORT_ID", "placeholder": "[[REPORT_ID]]"},
            ],
        }
    )

    candidate = delivery_renderer.render_word_candidate(
        template_bytes=template, report=report, manifest=manifest
    ).output_bytes
    source = tmp_path / "source.docx"
    source.write_bytes(candidate)
    office_word_worker._validate_word_source(source, "DOCX")

    pdf = LocalOfficePdfConverter(temp_root=_native_temp_root()).convert(candidate, "DOCX")

    assert pdf.startswith(b"%PDF-")
    _record(
        {
            "n13_product_template_path": {
                "templateSha256": sha256(template).hexdigest(),
                "candidateSha256": sha256(candidate).hexdigest(),
                "pdfSha256": sha256(pdf).hexdigest(),
                "preComValidation": "ACCEPT",
            }
        }
    )
