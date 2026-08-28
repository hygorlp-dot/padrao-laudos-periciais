from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from io import BytesIO
from types import MappingProxyType
from uuid import UUID

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scripts.backend_contract.application.models import PrivateContentId, WorkspaceId
from scripts.backend_contract.application.process_metadata import (
    FieldExtractionState,
    PageProcessingStatus,
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
INVALID_CNJ = "7654321-56.2025.4.05.0001"


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
    assert parsed.sequential == "7654321"
    assert parsed.check_digits == "55"
    assert parsed.year == "2025"
    assert parsed.justice_segment == "4"
    assert parsed.tribunal_code == "05"
    assert parsed.origin_unit == "0001"
    assert parsed.justice_branch == "Justiça Federal"

    with pytest.raises(ValueError, match="dígito|CNJ"):
        validate_cnj_number(INVALID_CNJ)


def test_local_pdf_text_extractor_is_bounded_and_reports_textless_documents():
    extractor = LocalPdfTextExtractor(max_pages=2, max_chars_per_page=40, max_total_chars=60)
    result = extractor.extract(
        BytesIO(
            text_pdf(
                "Pagina A descreve fundacao, alvenaria, cobertura e acabamento.",
                "Pagina B registra vistoria, medidas, fotografias e anomalias.",
                "Pagina C consolida conclusoes, ressalvas, anexos e referencias.",
                "Pagina D permanece fora do limite de processamento configurado.",
                "Pagina E tambem deve constar na cobertura nao processada.",
            )
        )
    )

    assert result.state is PdfTextExtractionState.PARTIAL
    assert [page.number for page in result.pages] == [1, 2, 3, 4, 5]
    assert all(
        page.processing_status is PageProcessingStatus.NOT_PROCESSED
        for page in result.pages[2:]
    )
    assert all(len(page.text) <= 40 for page in result.pages)
    assert sum(len(page.text) for page in result.pages) <= 60
    assert result.pages[0].processing_status is PageProcessingStatus.TRUNCATED

    textless = extractor.extract(BytesIO(text_pdf("")))
    assert textless.state is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
    assert [page.number for page in textless.pages] == [1]
    assert textless.pages[0].processing_status is PageProcessingStatus.NOT_PROCESSED


def test_native_scan_reports_a_textless_page_between_recoverable_pages():
    result = LocalPdfTextExtractor().extract(
        BytesIO(
            text_pdf(
                "Pagina um com texto nativo diversificado e recuperavel.",
                "",
                "Pagina tres com texto nativo diversificado e recuperavel.",
            )
        )
    )

    assert result.state is PdfTextExtractionState.PARTIAL
    assert [page.number for page in result.pages] == [1, 2, 3]
    assert result.pages[1].processing_status is PageProcessingStatus.NOT_PROCESSED


def test_default_native_scan_reaches_supported_metadata_on_the_last_page():
    pages = [
        f"Pagina sintetica {number} com conteudo textual diverso para cobertura integral."
        for number in range(1, 15)
    ]
    pages[-1] += f" PROCESSO: {VALID_CNJ}"

    parsed = LocalPdfTextExtractor().extract(BytesIO(text_pdf(*pages)))
    metadata = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_A,
        original_filename="autos-sinteticos.pdf",
        text=parsed,
        extracted_at=EXTRACTED_AT,
    )

    assert parsed.state is PdfTextExtractionState.AVAILABLE
    assert [page.number for page in parsed.pages] == list(range(1, 15))
    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""
    assert metadata.fields["numero_processo"].evidence[0].source_page == 14


def test_long_early_native_page_does_not_hide_a_later_supported_candidate():
    parsed = LocalPdfTextExtractor(max_chars_per_page=128).extract(
        BytesIO(
            text_pdf(
                " ".join(
                    hashlib.sha256(f"termo-{number}".encode()).hexdigest()
                    for number in range(40)
                ),
                f"Pagina final com identidade sujeita a revisao PROCESSO: {VALID_CNJ}",
            )
        )
    )
    metadata = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_A,
        original_filename="autos-sinteticos.pdf",
        text=parsed,
        extracted_at=EXTRACTED_AT,
    )

    assert parsed.state is PdfTextExtractionState.PARTIAL
    assert parsed.pages[0].processing_status is PageProcessingStatus.TRUNCATED
    assert parsed.pages[1].processing_status is PageProcessingStatus.AVAILABLE
    assert metadata.fields["numero_processo"].evidence[0].source_page == 2


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
        assert field.state is FieldExtractionState.AMBIGUOUS
        assert field.value == ""
        assert field.evidence
        assert value in {item.extracted_value for item in field.evidence}
        assert all(item.workspace_id == WORKSPACE_ID for item in field.evidence)
        assert all(item.document_id == DOCUMENT_A for item in field.evidence)
        assert all(item.source_page == 1 for item in field.evidence)
        assert all(item.extraction_method == "LOCAL_PDF_TEXT_V1" for item in field.evidence)
        assert all(item.extraction_timestamp == EXTRACTED_AT for item in field.evidence)
        assert all(item.source_filename == "autos.pdf" for item in field.evidence)
        assert all("path" not in item.as_dict() for item in field.evidence)


def test_pje_cover_surfaces_header_unit_region_and_each_party_for_review():
    result = extraction(
        "JUSTICA FEDERAL DA 5 REGIAO\n"
        "PJE - PROCESSO JUDICIAL ELETRONICO\n"
        f"NUMERO: {VALID_CNJ}\n"
        "CLASSE: PROCEDIMENTO SINTETICO\n"
        "ORGAO JULGADOR: 24 VARA FEDERAL PE\n"
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "ALICE EXEMPLO (AUTOR) ADVOGADO UM (ADVOGADO)\n"
        "BRUNO EXEMPLO (AUTOR) ADVOGADO DOIS (ADVOGADO)\n"
        "BANCO EXEMPLO SA (REU) ADVOGADO TRES (ADVOGADO)"
    )

    expected = {
        "tribunal": "Tribunal Regional Federal da 5\u00aa Regi\u00e3o",
        "vara": "24\u00aa Vara Federal",
        "uf": "PE",
        "parte_requerida": "BANCO EXEMPLO SA",
    }
    for field, value in expected.items():
        evidence = result.fields[field].evidence
        assert value in {item.extracted_value for item in evidence}
        assert all(item.source_page == 1 for item in evidence if item.extracted_value == value)

    assert {
        item.extracted_value for item in result.fields["parte_requerente"].evidence
    } >= {"ALICE EXEMPLO", "BRUNO EXEMPLO"}
    assert all(
        field.state is FieldExtractionState.AMBIGUOUS
        and field.value == ""
        for field in result.fields.values()
        if field.evidence
    )


def test_pje_heading_uses_only_canonical_supported_federal_tribunal_regions():
    coherent = extraction(
        "JUSTICA FEDERAL DA 5 REGIAO\n"
        f"PROCESSO: {VALID_CNJ}"
    )
    impossible = extraction("JUSTICA FEDERAL DA 99 REGIAO")

    assert {
        item.extracted_value for item in coherent.fields["tribunal"].evidence
    } == {"Tribunal Regional Federal da 5\u00aa Regi\u00e3o"}
    assert impossible.fields["tribunal"].state is FieldExtractionState.NOT_FOUND
    assert impossible.fields["tribunal"].evidence == ()


def test_pje_party_parser_requires_table_or_pole_context_and_preserves_aliases():
    result = extraction(
        "O contrato menciona JOAO DA SILVA (AUTOR) apenas como referencia.\n"
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "BANCO EXEMPLO (BE) S.A. (REU) ADVOGADO UM (ADVOGADO)"
    )

    assert result.fields["parte_requerente"].state is FieldExtractionState.NOT_FOUND
    assert {
        item.extracted_value for item in result.fields["parte_requerida"].evidence
    } == {"BANCO EXEMPLO (BE) S.A."}
    assert result.fields["parte_requerida"].state is FieldExtractionState.AMBIGUOUS
    assert result.fields["parte_requerida"].value == ""


def test_pje_party_candidates_preserve_unicode_source_offsets_and_drop_pole_labels():
    claimant = "AL\ufb01CE E\u0301XEMPLO"
    defendant = "RE\u0301U SINT\u0301ETICO"
    result = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_A,
        original_filename="tabela-pje-sintetica.pdf",
        text=PdfTextResult(
            PdfTextExtractionState.AVAILABLE,
            (
                PdfTextPage(
                    1,
                    f"POLO ATIVO - {claimant} (AUTORA) ADVOGADO UM (ADVOGADO)\n"
                    f"POLO PASSIVO: {defendant} (REU) ADVOGADO DOIS (ADVOGADO)",
                ),
            ),
        ),
        extracted_at=EXTRACTED_AT,
    )

    assert {
        item.extracted_value for item in result.fields["parte_requerente"].evidence
    } == {claimant}
    assert {
        item.extracted_value for item in result.fields["parte_requerida"].evidence
    } == {defendant}
    assert all(
        field.state is FieldExtractionState.AMBIGUOUS and field.value == ""
        for field in (
            result.fields["parte_requerente"],
            result.fields["parte_requerida"],
        )
    )


def test_partial_multiple_unicode_and_duplicate_values_do_not_inflate_confidence():
    result = extraction(
        f"Processo {VALID_CNJ}\n"
        "REQUERENTE: Joao Sintetico\n"
        "REQUERENTE: Joao Sintetico\n"
        "AUTORA: Ana Goncalves\n"
        "REQUERIDO: Orgao Publico\n"
        "REQUERIDO: Empresa Dois"
    )

    assert result.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert result.fields["tribunal"].state is FieldExtractionState.AMBIGUOUS
    assert result.fields["vara"].state is FieldExtractionState.NOT_FOUND
    assert result.fields["parte_requerente"].value == ""
    assert result.fields["parte_requerida"].value == ""
    assert {
        item.extracted_value for item in result.fields["parte_requerente"].evidence
    } == {"Joao Sintetico", "Ana Goncalves"}
    assert {
        item.extracted_value for item in result.fields["parte_requerida"].evidence
    } == {"Orgao Publico", "Empresa Dois"}
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

    for name, expected in {
        "tribunal": "Tribunal Regional Federal da 5ª Região",
        "parte_requerente": "Conceição Gonçalves",
        "parte_requerida": "Órgão Público Sintético",
    }.items():
        assert result.fields[name].state is FieldExtractionState.AMBIGUOUS
        assert result.fields[name].value == ""
        assert result.fields[name].evidence[0].extracted_value == expected


def test_duplicate_filenames_remain_distinct_by_document_identity():
    first = extraction(f"PROCESSO: {VALID_CNJ}", filename="autos.pdf")
    second = extraction(
        "PROCESSO: 0000001-59.2026.8.05.0001",
        document_id=DOCUMENT_B,
        filename="autos.pdf",
    )

    field = aggregate_process_metadata((first, second)).fields["numero_processo"]

    assert field.state is FieldExtractionState.AMBIGUOUS
    assert field.value == ""
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

    assert aggregate.state == "PARTIAL"
    assert aggregate.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
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
