from __future__ import annotations

from uuid import UUID

from scripts.backend_contract.application.models import PrivateContentId, WorkspaceId
from scripts.backend_contract.application.process_metadata import (
    FieldExtractionState,
    PageProcessingStatus,
    PdfTextExtractionState,
    PdfTextPage,
    PdfTextResult,
    extract_process_metadata,
)


WORKSPACE_ID = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
DOCUMENT_ID = PrivateContentId(UUID("22222222-2222-4222-8222-222222222222"))
PRIMARY_CNJ = "1234567-48.2024.4.01.0001"
INCIDENTAL_CNJ = "7654321-12.2025.4.03.0001"


def extract(*pages: PdfTextPage, state=PdfTextExtractionState.AVAILABLE):
    return extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_ID,
        original_filename="autos-sinteticos.pdf",
        text=PdfTextResult(state, pages, document_sha256="a" * 64),
        extracted_at="2026-08-26T12:00:00+00:00",
    )


def test_valid_cnj_without_primary_identity_anchor_is_ambiguous():
    metadata = extract(
        PdfTextPage(
            1,
            "Anexo contratual para conferência.\n"
            f"Referência documental sem identificação do processo: {INCIDENTAL_CNJ}",
        )
    )

    field = metadata.fields["numero_processo"]
    assert field.state is FieldExtractionState.AMBIGUOUS
    assert field.value == ""
    assert [item.source_page for item in field.evidence] == [1]


def test_first_page_top_reference_is_not_a_primary_identity_anchor():
    metadata = extract(
        PdfTextPage(
            1,
            f"Referência documental: {INCIDENTAL_CNJ}\n"
            + "Conteúdo sintético sem identificação do processo principal. " * 8,
        )
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""


def test_bare_first_page_top_cnj_is_not_a_primary_identity_anchor():
    metadata = extract(
        PdfTextPage(
            1,
            f"{INCIDENTAL_CNJ}\n"
            + "Conteudo sintetico sem rotulo de identidade processual. " * 8,
        )
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""


def test_repeated_unanchored_cnj_is_not_a_primary_identity_anchor():
    metadata = extract(
        PdfTextPage(2, f"{INCIDENTAL_CNJ}\nReferencia sintetica sem rotulo."),
        PdfTextPage(3, f"{INCIDENTAL_CNJ}\nOutra referencia sintetica sem rotulo."),
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""


def test_multiline_reference_label_rejects_apparent_process_anchor():
    metadata = extract(
        PdfTextPage(
            1,
            f"Referencia documental:\nPROCESSO: {INCIDENTAL_CNJ}\n"
            "Conteudo sintetico de outro feito.",
        )
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""


def test_primary_process_header_outranks_incidental_valid_cnj():
    metadata = extract(
        PdfTextPage(
            1,
            "TRIBUNAL REGIONAL FEDERAL DA 1 REGIAO\n"
            f"PROCESSO: {PRIMARY_CNJ}\n"
            "2 VARA FEDERAL\nAUTOR: Parte principal\nREU: Parte contrária",
        ),
        PdfTextPage(
            9,
            "Documento juntado para consulta histórica.\n"
            f"Referência documental: {INCIDENTAL_CNJ}",
        ),
    )

    process_number = metadata.fields["numero_processo"]
    assert process_number.state is FieldExtractionState.CONFIDENT
    assert process_number.value == PRIMARY_CNJ
    assert [item.source_page for item in process_number.evidence] == [1]
    assert metadata.fields["ramo_justica"].value == "Justiça Federal"
    assert metadata.fields["tribunal"].value == "Tribunal Regional Federal da 1ª Região"


def test_identity_fields_outside_primary_context_do_not_contaminate_result():
    metadata = extract(
        PdfTextPage(
            1,
            f"PROCESSO: {PRIMARY_CNJ}\n"
            "2 VARA FEDERAL\nAUTOR: Parte principal\nREU: Parte contrária",
        ),
        PdfTextPage(
            9,
            f"{INCIDENTAL_CNJ}\n"
            "99 VARA FEDERAL\nAUTOR: Pessoa de outro feito\nREU: Outra pessoa",
        ),
        PdfTextPage(
            13,
            "",
            processing_status=PageProcessingStatus.NOT_PROCESSED,
        ),
        state=PdfTextExtractionState.PARTIAL,
    )

    assert metadata.fields["vara"].state is FieldExtractionState.CONFIDENT
    assert metadata.fields["vara"].value == "2ª Vara Federal"
    assert metadata.fields["parte_requerente"].value == "Parte principal"
    assert metadata.fields["parte_requerida"].value == "Parte contrária"
    assert all(
        evidence.source_page == 1
        for name in ("vara", "parte_requerente", "parte_requerida")
        for evidence in metadata.fields[name].evidence
    )


def test_same_primary_cnj_on_reference_page_does_not_expand_identity_context():
    metadata = extract(
        PdfTextPage(
            1,
            f"PROCESSO: {PRIMARY_CNJ}\n"
            "AUTOR: Parte principal\nREU: Parte contraria",
        ),
        PdfTextPage(
            9,
            f"Referencia documental: {PRIMARY_CNJ}\n"
            "AUTOR: Pessoa de outro feito\nREU: Outra pessoa",
        ),
    )

    assert metadata.fields["parte_requerente"].value == "Parte principal"
    assert metadata.fields["parte_requerida"].value == "Parte contraria"
    assert all(
        evidence.source_page == 1
        for name in ("parte_requerente", "parte_requerida")
        for evidence in metadata.fields[name].evidence
    )


def test_derived_identity_uses_the_selected_anchored_occurrence():
    metadata = extract(
        PdfTextPage(
            1,
            f"Referencia documental: {PRIMARY_CNJ}\n"
            "TRIBUNAL REGIONAL FEDERAL DA 3 REGIAO",
        ),
        PdfTextPage(2, f"PROCESSO: {PRIMARY_CNJ}"),
    )

    for field_name in ("numero_processo", "ramo_justica", "tribunal"):
        field = metadata.fields[field_name]
        assert field.state is FieldExtractionState.CONFIDENT
        assert [item.source_page for item in field.evidence] == [2]
