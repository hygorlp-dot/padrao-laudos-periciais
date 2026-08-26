from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from types import MappingProxyType
from uuid import UUID

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scripts.backend_contract.application.models import PrivateContentId, WorkspaceId
from scripts.backend_contract.application.process_metadata import (
    FieldExtractionState,
    PdfTextPage,
    PdfTextResult,
    PdfTextExtractionState,
    aggregate_process_metadata,
    extract_process_metadata,
    validate_cnj_number,
)
from scripts.backend_contract.infrastructure.pdf_text import LocalPdfTextExtractor


WORKSPACE_ID = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
DOCUMENT_A = PrivateContentId(UUID("22222222-2222-4222-8222-222222222222"))
DOCUMENT_B = PrivateContentId(UUID("33333333-3333-4333-8333-333333333333"))
EXTRACTED_AT = "2026-08-26T12:30:00+00:00"
VALID_CNJ = "7654321-55.2025.4.05.0001"
INVALID_CNJ = "0010549-09.2026.4.05.8302"


def text_pdf(*pages: str) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        encoded = escaped.encode("latin-1", errors="replace")
        stream.set_data(b"BT /F1 10 Tf 36 750 Td (" + encoded + b") Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
    target = BytesIO()
    writer.write(target)
    return target.getvalue()


def extraction(text: str, *, document_id=DOCUMENT_A, filename="autos.pdf"):
    parsed = LocalPdfTextExtractor().extract(BytesIO(text_pdf(text)))
    return extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=document_id,
        original_filename=filename,
        text=parsed,
        extracted_at=EXTRACTED_AT,
    )


def test_cnj_checksum_and_structural_components_are_deterministic():
    parsed = validate_cnj_number(VALID_CNJ)

    assert parsed.canonical == VALID_CNJ
    assert parsed.sequential == "0010549"
    assert parsed.check_digits == "08"
    assert parsed.year == "2026"
    assert parsed.justice_segment == "4"
    assert parsed.tribunal_code == "05"
    assert parsed.origin_unit == "8302"
    assert parsed.justice_branch == "Justiça Federal"

    with pytest.raises(ValueError, match="dígito|CNJ"):
        validate_cnj_number(INVALID_CNJ)


def test_local_pdf_text_extractor_is_bounded_and_reports_textless_documents():
    extractor = LocalPdfTextExtractor(max_pages=2, max_chars_per_page=40, max_total_chars=60)
    result = extractor.extract(BytesIO(text_pdf("A" * 80, "B" * 80, "C" * 80)))

    assert result.state is PdfTextExtractionState.AVAILABLE
    assert len(result.pages) == 2
    assert all(len(page.text) <= 40 for page in result.pages)
    assert sum(len(page.text) for page in result.pages) <= 60

    textless = extractor.extract(BytesIO(text_pdf("")))
    assert textless.state is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
    assert textless.pages == ()


def test_complete_process_identity_is_extracted_with_field_level_provenance():
    result = extraction(
        "TRIBUNAL REGIONAL FEDERAL DA 5 REGIAO\n"
        "1 VARA FEDERAL DA SUBSECAO JUDICIARIA DE RECIFE/PE\n"
        f"PROCESSO: {VALID_CNJ}\n"
        "AUTOR: Maria da Conceicao Silva\n"
        "REU: Construtora Sintetica Ltda"
    )

    expected = {
        "numero_processo": VALID_CNJ,
        "ramo_justica": "Justiça Federal",
        "tribunal": "Tribunal Regional Federal da 5ª Região",
        "vara": "1ª Vara Federal",
        "comarca_municipio": "Recife",
        "uf": "PE",
        "parte_requerente": "Maria da Conceicao Silva",
        "parte_requerida": "Construtora Sintetica Ltda",
    }
    assert isinstance(result.fields, MappingProxyType)
    for name, value in expected.items():
        field = result.fields[name]
        assert field.state is FieldExtractionState.CONFIDENT
        assert field.value == value
        assert field.evidence
        assert all(item.workspace_id == WORKSPACE_ID for item in field.evidence)
        assert all(item.document_id == DOCUMENT_A for item in field.evidence)
        assert all(item.source_page == 1 for item in field.evidence)
        assert all(item.extraction_method == "LOCAL_PDF_TEXT_V1" for item in field.evidence)
        assert all(item.extraction_timestamp == EXTRACTED_AT for item in field.evidence)
        assert all(item.source_filename == "autos.pdf" for item in field.evidence)
        assert all("path" not in item.as_dict() for item in field.evidence)


def test_partial_multiple_unicode_and_duplicate_values_do_not_inflate_confidence():
    result = extraction(
        f"Processo {VALID_CNJ}\n"
        "REQUERENTE: Joao Sintetico\n"
        "REQUERENTE: Joao Sintetico\n"
        "AUTORA: Ana Goncalves\n"
        "REQUERIDO: Orgao Publico\n"
        "REQUERIDO: Empresa Dois"
    )

    assert result.fields["numero_processo"].state is FieldExtractionState.CONFIDENT
    assert result.fields["tribunal"].state is FieldExtractionState.CONFIDENT
    assert result.fields["vara"].state is FieldExtractionState.NOT_FOUND
    assert result.fields["parte_requerente"].value == "Joao Sintetico; Ana Goncalves"
    assert result.fields["parte_requerida"].value == "Orgao Publico; Empresa Dois"
    assert len(result.fields["parte_requerente"].evidence) == 2


def test_unicode_parties_and_unusual_valid_heading_are_preserved_without_guessing():
    result = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_A,
        original_filename="cabecalho-sintetico.pdf",
        text=PdfTextResult(
            PdfTextExtractionState.AVAILABLE,
            (
                PdfTextPage(
                    1,
                    "Tribunal Regional Federal da 5ª Região\n"
                    f"PROCESSO: {VALID_CNJ}\n"
                    "AUTORA: Conceição Gonçalves\n"
                    "RÉU: Órgão Público Sintético",
                ),
            ),
        ),
        extracted_at=EXTRACTED_AT,
    )

    assert result.fields["tribunal"].value == "Tribunal Regional Federal da 5ª Região"
    assert result.fields["parte_requerente"].value == "Conceição Gonçalves"
    assert result.fields["parte_requerida"].value == "Órgão Público Sintético"


def test_duplicate_filenames_remain_distinct_by_document_identity():
    first = extraction(f"PROCESSO: {VALID_CNJ}", filename="autos.pdf")
    second = extraction(
        "PROCESSO: 0000001-59.2026.8.05.0001",
        document_id=DOCUMENT_B,
        filename="autos.pdf",
    )

    field = aggregate_process_metadata((first, second)).fields["numero_processo"]

    assert field.state is FieldExtractionState.CONFLICTING
    assert {item.document_id for item in field.evidence} == {DOCUMENT_A, DOCUMENT_B}
    assert {item.source_filename for item in field.evidence} == {"autos.pdf"}


def test_invalid_cnj_and_contradictory_header_never_become_effective_silently():
    invalid = extraction(f"PROCESSO: {INVALID_CNJ}")
    assert invalid.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert invalid.fields["numero_processo"].value == ""
    assert invalid.fields["numero_processo"].evidence[0].extracted_value == INVALID_CNJ

    contradictory = extraction(
        f"TRIBUNAL REGIONAL FEDERAL DA 24 REGIAO\nPROCESSO: {VALID_CNJ}"
    )
    assert contradictory.fields["tribunal"].state is FieldExtractionState.CONFLICTING
    assert contradictory.fields["tribunal"].value == ""
    assert {item.extracted_value for item in contradictory.fields["tribunal"].evidence} == {
        "Tribunal Regional Federal da 5ª Região",
        "Tribunal Regional Federal da 24ª Região",
    }


def test_aggregate_surfaces_cross_document_conflict_and_keeps_exact_sources():
    first = extraction(
        f"PROCESSO: {VALID_CNJ}\nAUTOR: Parte Um",
        filename="primeiro.pdf",
    )
    second = extraction(
        "PROCESSO: 0000001-59.2026.8.05.0001\nAUTOR: Parte Dois",
        document_id=DOCUMENT_B,
        filename="segundo.pdf",
    )

    aggregate = aggregate_process_metadata((first, second))

    assert aggregate.state == "CONFLICT"
    assert aggregate.fields["numero_processo"].state is FieldExtractionState.CONFLICTING
    assert aggregate.fields["numero_processo"].value == ""
    assert {item.source_filename for item in aggregate.fields["numero_processo"].evidence} == {
        "primeiro.pdf",
        "segundo.pdf",
    }
    assert aggregate.fields["vara"].state is FieldExtractionState.NOT_FOUND


def test_extraction_timestamp_must_be_timezone_aware_and_no_private_path_is_accepted():
    parsed = LocalPdfTextExtractor().extract(BytesIO(text_pdf(f"PROCESSO: {VALID_CNJ}")))
    with pytest.raises(ValueError, match="timezone|timestamp"):
        extract_process_metadata(
            workspace_id=WORKSPACE_ID,
            document_id=DOCUMENT_A,
            original_filename="autos.pdf",
            text=parsed,
            extracted_at=datetime(2026, 8, 26, 12, 30).isoformat(),
        )
    with pytest.raises(ValueError, match="nome|filename|path"):
        extract_process_metadata(
            workspace_id=WORKSPACE_ID,
            document_id=DOCUMENT_A,
            original_filename="C:/private/autos.pdf",
            text=parsed,
            extracted_at=datetime(2026, 8, 26, 12, 30, tzinfo=UTC).isoformat(),
        )
