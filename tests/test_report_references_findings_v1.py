"""References, citations and the findings summary table (#239, Phase C2).

A reference is a standard, law or work the expert relies on -- never a case
document.  The references section is generated from the selected references;
the findings summary is captured from approved pathologies and bound to their
revision like any claim.  Word 16 renders both through the fidelity oracle,
whose table reading needed one repair: a cell whose text wraps is read inside
its painted borders (RED_THIS_REPAIR below).
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.backend_contract import delivery_renderer as dr
from scripts.backend_contract.application.report_foundation import AmendReportDraft
from scripts.backend_contract.construction_defect_analysis import construction_defect_analysis_from_mapping
from scripts.backend_contract.report_default_template import default_report_template, default_template_manifest
from scripts.backend_contract.report_foundation import (
    ReportFindingRow,
    ReportProvenance,
    ReportReference,
    report_snapshot_from_mapping,
    report_snapshot_to_mapping,
)
from tests.test_report_authoring_v1 import _Record, _draft_bound_to, _upstream

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _nbr() -> ReportReference:
    return ReportReference(
        "REFERENCE-1", "TECHNICAL_STANDARD", "Associação Brasileira de Normas Técnicas",
        "Edificações habitacionais — Desempenho — Parte 1: Requisitos gerais", 2021, "ABNT NBR 15575-1", "Rio de Janeiro",
    )


def _rows() -> tuple[ReportFindingRow, ...]:
    return tuple(
        ReportFindingRow(manifestation, environment, finding, situation, ReportProvenance(f"PROVENANCE-{index}", "PATHOLOGY", f"PAT-00{index}", 3))
        for index, (manifestation, environment, finding, situation) in enumerate([
            ("Umidade visível na interface parede-piso.", "Banheiro social", "Manchas de umidade ascendente até 40 cm de altura, com eflorescência.", "ANOMALIA"),
            ("Fissura inclinada no canto da esquadria.", "Dormitório 1", "Fissura de 0,4 mm partindo do vértice superior da janela, sem verga aparente.", "FALHA"),
            ("Descolamento de revestimento cerâmico.", None, "Placas com som cavo em 12 % da área do piso.", None),
        ], 1)
    )


# --- the domain ---------------------------------------------------------------


def test_a_reference_is_cited_author_date_and_listed_as_abnt_entry() -> None:
    nbr = _nbr()
    assert nbr.citation == "(ABNT NBR 15575-1, 2021)"
    assert nbr.entry == "ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS. ABNT NBR 15575-1: Edificações habitacionais — Desempenho — Parte 1: Requisitos gerais. Rio de Janeiro, 2021."
    book = ReportReference("R2", "TECHNICAL_LITERATURE", "Thomaz, Ercio", "Trincas em edifícios", 2020, None, "2. ed. São Paulo: Oficina de Textos")
    assert (book.citation, book.entry) == ("(THOMAZ, 2020)", "THOMAZ, Ercio. Trincas em edifícios. 2. ed. São Paulo: Oficina de Textos, 2020.")
    law = ReportReference("R3", "LEGAL_REFERENCE", "Brasil", "Lei nº 13.105, de 16 de março de 2015. Código de Processo Civil.", None, None, None)
    assert (law.citation, law.entry) == ("(BRASIL)", "BRASIL. Lei nº 13.105, de 16 de março de 2015. Código de Processo Civil.")


@pytest.mark.parametrize("change", [
    {"kind": "CASE_DOCUMENT"}, {"kind": "SOURCE_DOCUMENT"}, {"year": 1500}, {"title": " "},
    {"identifier": ""}, {"details": " padded "}, {"author": "x" * 301},
])
def test_a_case_document_or_malformed_work_is_not_a_reference(change) -> None:
    values = {"reference_id": "R", "kind": "TECHNICAL_STANDARD", "author": "ABNT", "title": "Norma", "year": 2021, "identifier": None, "details": None}
    with pytest.raises(ValueError):
        ReportReference(**{**values, **change})


def test_new_collections_round_trip_and_legacy_mapping_stays_exact() -> None:
    legacy = _fixture("report-snapshot-v1.json")
    report = report_snapshot_from_mapping(legacy)
    assert report_snapshot_to_mapping(report) == legacy and "references" not in legacy
    enriched = replace(report, references=(_nbr(),), findings_table=_rows())
    mapping = report_snapshot_to_mapping(enriched)
    assert report_snapshot_from_mapping(mapping) == enriched
    for name in ("references", "findings_table"):
        for dishonest in (None, []):
            with pytest.raises(ValueError):
                report_snapshot_from_mapping({**mapping, name: dishonest})
    duplicated = replace(_nbr(), reference_id="REFERENCE-2")
    with pytest.raises(ValueError, match="unique"):
        replace(report, references=(_nbr(), duplicated))
    with pytest.raises(ValueError, match="pathology provenance"):
        ReportFindingRow("m", None, "f", None, ReportProvenance("P", "TECHNICAL_FINDING", "F", 1))


# --- the amendments -----------------------------------------------------------


def _service(report, pathology=None):
    case, technical, _ = _upstream()
    saved = []
    service = AmendReportDraft(
        get_snapshot=SimpleNamespace(execute=lambda _w: (_Record(revision=7), report)),
        save_snapshot=SimpleNamespace(execute=lambda _w, snapshot, expected: saved.append(snapshot) or _Record(revision=8)),
        ids=SimpleNamespace(new_uuid=iter(f"00000000-0000-4000-8000-{index:012d}" for index in range(1, 99)).__next__),
        get_case_analysis=SimpleNamespace(execute=lambda _w: (_Record(revision=report.source_snapshot.case_analysis_revision), case)),
        get_technical_snapshot=SimpleNamespace(execute=lambda _w: (_Record(revision=report.source_snapshot.technical_snapshot_revision), technical)),
        get_construction_defect_analysis=None if pathology is None else SimpleNamespace(execute=lambda _w: (_Record(revision=3), pathology)),
    )
    return service, saved


def _draft():
    case, technical, _ = _upstream()
    return _draft_bound_to(case, technical)


def test_references_are_added_and_removed_on_a_draft() -> None:
    service, _ = _service(_draft())
    values = {"kind": "TECHNICAL_STANDARD", "author": " Associação Brasileira de Normas Técnicas ", "title": "Desempenho", "year": 2021, "identifier": "ABNT NBR 15575-1", "details": ""}
    _, added = service.execute("w", expected_revision=7, action="ADD_REFERENCE", values=values)
    reference = added.references[0]
    assert (reference.author, reference.details, reference.citation) == ("Associação Brasileira de Normas Técnicas", None, "(ABNT NBR 15575-1, 2021)")
    service, _ = _service(added)
    with pytest.raises(ValueError, match="unique"):
        service.execute("w", expected_revision=7, action="ADD_REFERENCE", values=values)
    with pytest.raises(ValueError):
        service.execute("w", expected_revision=7, action="ADD_REFERENCE", values={**values, "year": "2021"})
    _, removed = service.execute("w", expected_revision=7, action="REMOVE_REFERENCE", values={"reference_id": reference.reference_id})
    assert removed.references is None and "references" not in report_snapshot_to_mapping(removed)


def test_the_findings_table_is_captured_from_approved_pathologies_only() -> None:
    pathology = construction_defect_analysis_from_mapping(_fixture("construction-defect-analysis-v1.json"))
    source = replace(_draft().source_snapshot, construction_defect_analysis_snapshot_id="S", construction_defect_analysis_revision=3, construction_defect_analysis_digest="0" * 64)
    report = replace(_draft(), source_snapshot=source)
    service, _ = _service(report, pathology)
    _, tabled = service.execute("w", expected_revision=7, action="SET_FINDINGS_TABLE", values={})
    (row,) = tabled.findings_table
    item = pathology.analysis_final["patologias"][0]
    assert (row.manifestation, row.environment, row.finding, row.situation) == (item["manifestacao"], None, item["conclusao_tecnica"], None)
    assert (row.provenance.source_kind, row.provenance.source_id, row.provenance.source_revision) == ("PATHOLOGY", "PAT-001", 3)
    # Nothing is captured from a pathology the expert has not approved, and a
    # report bound to no pathology analysis has no table to capture.
    unapproved = replace(pathology, reviews=())
    with pytest.raises(ValueError, match="approved pathologies"):
        _service(report, unapproved)[0].execute("w", expected_revision=7, action="SET_FINDINGS_TABLE", values={})
    with pytest.raises(ValueError, match="no bound pathology"):
        _service(_draft(), pathology)[0].execute("w", expected_revision=7, action="SET_FINDINGS_TABLE", values={})
    _, untabled = _service(tabled)[0].execute("w", expected_revision=7, action="REMOVE_FINDINGS_TABLE", values={})
    assert untabled.findings_table is None


# --- the presentation ---------------------------------------------------------


def test_the_report_presents_the_table_in_findings_and_the_references_last() -> None:
    report = replace(report_snapshot_from_mapping(_fixture("report-snapshot-v1.json")), references=(_nbr(), ReportReference("R0", "LEGAL_REFERENCE", "Brasil", "Código de Processo Civil", 2015, None, None)), findings_table=_rows())
    blocks = dr.professional_report_blocks(report)
    kinds = [block.kind for block in blocks]
    caption = kinds.index("CAPTION")
    assert blocks[caption - 1].text.endswith("ACHADOS TÉCNICOS") and kinds[caption + 1] == "TABLE"
    table = blocks[caption + 1]
    assert table.rows[0] == dr.FINDINGS_TABLE_HEADER and table.rows[3][2:] == ("Não informado", "Placas com som cavo em 12 % da área do piso.", "Não informada")
    assert blocks[caption].text == "Tabela 1 – Resumo dos achados técnicos"
    references = [block.text for block in blocks if block.kind == "REFERENCE"]
    assert references == ["ASSOCIAÇÃO BRASILEIRA DE NORMAS TÉCNICAS. ABNT NBR 15575-1: Edificações habitacionais — Desempenho — Parte 1: Requisitos gerais. Rio de Janeiro, 2021.", "BRASIL. Código de Processo Civil. 2015."]
    assert blocks[kinds.index("REFERENCE") - 1].text.endswith("REFERÊNCIAS")
    text = "\n".join(t for block in blocks for t in block.paragraph_texts)
    assert "PAT-00" not in text and "REFERENCE-1" not in text and "PROVENANCE" not in text
    trail = dr.canonical_report_audit_lines(report)
    assert any(line.startswith("TABELA DE ACHADOS | PATHOLOGY | PAT-001 | revisão 3") for line in trail)
    assert any(line.startswith("REFERÊNCIA | REFERENCE-1 | TECHNICAL_STANDARD") for line in trail)


def test_the_bound_word_carries_the_table_as_a_painted_grid_over_the_text_width() -> None:
    report = replace(report_snapshot_from_mapping(_fixture("report-snapshot-v1.json")), references=(_nbr(),), findings_table=_rows())
    template = default_report_template(report.editorial_profile)
    word = dr.render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest()).output_bytes
    from io import BytesIO
    from zipfile import ZipFile

    document = ZipFile(BytesIO(word)).read("word/document.xml")
    assert b'w:tblStyle w:val="TableGrid"' in document and b'w:type="dxa"' in document
    widths = [int(value) for value in __import__("re").findall(rb'<w:gridCol w:w="(\d+)"/>', document)[-5:]]
    assert sum(widths) == dr._text_width_twips(document) and widths[0] == 800


# --- the oracle repair --------------------------------------------------------


def _text(text, x, top, *, size=10.0):
    return dr._PositionedText(0, text, x, top - size, size, x + len(text) * size * 0.5, top - size, top, page_width=595.0, page_height=842.0, strict_text=text)


def _border(x, bottom, top):
    return dr._VerticalBarrier(0, x - 0.25, x + 0.25, bottom, top)


def _wrapped_row():
    # Two cells whose text wraps: reading order runs across the row, so each
    # cell's second line follows the other cell's first line.
    left = [_text("Umidade visivel na", 90.0, 700.0), _text("interface parede.", 90.0, 688.0)]
    right = [_text("Manchas ate 40 cm", 250.0, 700.0), _text("de altura.", 250.0, 688.0)]
    return dr._positioned_reading_order([*left, *right]), [_border(85.0, 680.0, 712.0), _border(240.0, 680.0, 712.0), _border(400.0, 680.0, 712.0)]


def test_a_wrapped_cell_is_read_inside_its_painted_borders() -> None:
    """RED_THIS_REPAIR: a faithful table whose cell text wraps was refused."""
    ordered, borders = _wrapped_row()
    row = ("Umidade visivel na interface parede.", "Manchas ate 40 cm de altura.")
    assert dr._fragment_sequence_end(row[0], ordered, 0, borders, allow_line_wrap=True, alignment="left", strict_identity=True) is None
    assert dr._table_rows_match([row], ordered, borders)
    assert dr._row_line_at_or_after(row, ordered, borders, None) is not None


def test_the_painted_cell_still_demands_its_own_text() -> None:
    ordered, borders = _wrapped_row()
    # Without painted borders there is no cell to read.
    assert not dr._table_rows_match([("Umidade visivel na interface parede.", "Manchas ate 40 cm de altura.")], ordered, [])
    # The other column's continuation cannot complete a cell, nor swap rows.
    assert not dr._table_rows_match([("Umidade visivel na de altura.", "Manchas ate 40 cm interface parede.")], ordered, borders)
    assert dr._cell_column_match("Umidade visivel na interface parede alterada.", ordered, 0, borders, strict_identity=True) is None


# --- Microsoft Word 16 ----------------------------------------------------------


def _native():
    from tests.test_office_word_native_matrix_v1 import _word_available

    return _word_available()


@pytest.mark.skipif("not __import__('tests.test_report_references_findings_v1', fromlist=['_native'])._native()", reason="Microsoft Word 16 unavailable")
def test_word_16_renders_table_and_references_faithfully_and_a_changed_cell_is_refused() -> None:
    from scripts.backend_contract.infrastructure.office_pdf import LocalOfficePdfConverter

    report = replace(report_snapshot_from_mapping(_fixture("report-snapshot-v1.json")), references=(_nbr(),), findings_table=_rows())
    template = default_report_template(report.editorial_profile)
    word = dr.render_word_candidate(template_bytes=template, report=report, manifest=default_template_manifest()).output_bytes
    pdf = dr.render_final_pdf_candidate(word_content=word, word_format="DOCX", converter=LocalOfficePdfConverter())
    dr.validate_final_artifact(pdf, "PDF")
    rows = _rows()
    changed = replace(report, findings_table=(replace(rows[0], finding="Manchas de umidade ascendente até 90 cm de altura, com eflorescência."), *rows[1:]))
    other = dr.render_word_candidate(template_bytes=template, report=changed, manifest=default_template_manifest()).output_bytes
    copy, _format = dr.safe_pdf_conversion_copy(other, "DOCX")
    with pytest.raises(ValueError, match="faithfully"):
        dr._validate_pdf_fidelity(copy, pdf)
