from __future__ import annotations

from types import MappingProxyType
from uuid import UUID

import pytest

from scripts.backend_contract.application import process_metadata as metadata_module
from scripts.backend_contract.application.models import PrivateContentId, WorkspaceId
from scripts.backend_contract.application.process_metadata import (
    FieldExtractionState,
    PageProcessingStatus,
    PageExtractionMode,
    PageTextBlock,
    PdfTextExtractionState,
    PdfTextPage,
    PdfTextResult,
    aggregate_process_metadata,
    document_metadata_from_payload,
    document_metadata_payload,
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


def freeze_payload(value):
    if type(value) is dict:
        return MappingProxyType({key: freeze_payload(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(freeze_payload(item) for item in value)
    return value


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


def test_unanchored_valid_cnj_surfaces_deterministic_justice_candidates_fail_closed():
    metadata = extract(
        PdfTextPage(
            1,
            f"Nº {PRIMARY_CNJ}\nDocumento sintetico sujeito a revisao humana.",
        )
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""
    assert metadata.fields["ramo_justica"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["ramo_justica"].value == ""
    assert metadata.fields["ramo_justica"].evidence[0].extracted_value == "Justiça Federal"
    assert metadata.fields["ramo_justica"].evidence[0].source_page == 1
    assert metadata.fields["tribunal"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["tribunal"].value == ""
    assert (
        metadata.fields["tribunal"].evidence[0].extracted_value
        == "Tribunal Regional Federal da 1ª Região"
    )
    assert metadata.fields["tribunal"].evidence[0].source_page == 1


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


def test_process_header_outside_first_document_page_is_not_primary_proof():
    metadata = extract(
        PdfTextPage(1, f"{PRIMARY_CNJ}\nDocumento principal sem rotulo."),
        PdfTextPage(
            7,
            f"Documento juntado para consulta historica.\nPROCESSO: {INCIDENTAL_CNJ}\n"
            "AUTOR: Pessoa incidental",
        ),
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""
    assert metadata.fields["parte_requerente"].state is not FieldExtractionState.CONFIDENT


def test_outro_processo_prefix_is_not_an_explicit_primary_anchor():
    metadata = extract(
        PdfTextPage(
            1,
            f"ANEXO PARA CONFERENCIA\nOUTRO PROCESSO: {INCIDENTAL_CNJ}\n"
            "AUTOR: Pessoa incidental",
        )
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""
    assert metadata.fields["parte_requerente"].state is not FieldExtractionState.CONFIDENT


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
    assert process_number.state is FieldExtractionState.AMBIGUOUS
    assert process_number.value == ""
    assert process_number.evidence[0].extracted_value == PRIMARY_CNJ
    assert [item.source_page for item in process_number.evidence] == [1]
    assert metadata.fields["ramo_justica"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["ramo_justica"].evidence[0].extracted_value == "Justiça Federal"
    assert metadata.fields["tribunal"].state is FieldExtractionState.AMBIGUOUS
    assert (
        metadata.fields["tribunal"].evidence[0].extracted_value
        == "Tribunal Regional Federal da 1ª Região"
    )


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

    for name, expected in {
        "vara": "2ª Vara Federal",
        "parte_requerente": "Parte principal",
        "parte_requerida": "Parte contrária",
    }.items():
        assert metadata.fields[name].state is FieldExtractionState.AMBIGUOUS
        assert metadata.fields[name].value == ""
        assert metadata.fields[name].evidence[0].extracted_value == expected
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

    assert metadata.fields["parte_requerente"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["parte_requerente"].value == ""
    assert metadata.fields["parte_requerente"].evidence[0].extracted_value == "Parte principal"
    assert metadata.fields["parte_requerida"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["parte_requerida"].value == ""
    assert metadata.fields["parte_requerida"].evidence[0].extracted_value == "Parte contraria"
    assert all(
        evidence.source_page == 1
        for name in ("parte_requerente", "parte_requerida")
        for evidence in metadata.fields[name].evidence
    )


def test_secondary_section_on_primary_page_does_not_contaminate_identity_fields():
    metadata = extract(
        PdfTextPage(
            1,
            f"PROCESSO: {PRIMARY_CNJ}\n"
            "AUTOR: Parte principal\nREU: Parte contraria\n"
            "ANEXO DE OUTRO FEITO\n"
            f"{INCIDENTAL_CNJ}\n"
            "AUTOR: Pessoa incidental\nREU: Outra pessoa",
        )
    )

    for name, expected in {
        "numero_processo": PRIMARY_CNJ,
        "parte_requerente": "Parte principal",
        "parte_requerida": "Parte contraria",
    }.items():
        assert metadata.fields[name].state is FieldExtractionState.AMBIGUOUS
        assert metadata.fields[name].value == ""
        assert metadata.fields[name].evidence[0].extracted_value == expected


def test_prior_incidental_cnj_prevents_same_page_primary_confidence():
    metadata = extract(
        PdfTextPage(
            1,
            f"{INCIDENTAL_CNJ}\n"
            "AUTOR: Pessoa incidental\n"
            f"PROCESSO: {PRIMARY_CNJ}\n"
            "AUTOR: Parte principal",
        )
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""
    assert metadata.fields["parte_requerente"].state is not FieldExtractionState.CONFIDENT


def test_ocr_primary_anchor_uses_exact_occurrence_confidence_and_bounding_box():
    high_box = (1.0, 1.0, 2.0, 2.0)
    low_box = (3.0, 3.0, 4.0, 4.0)
    metadata = extract(
        PdfTextPage(
            1,
            f"Referencia documental: {PRIMARY_CNJ}\nPROCESSO: {PRIMARY_CNJ}",
            extraction_mode=PageExtractionMode.OCR,
            engine="ocr-local",
            engine_version="1",
            model_version="modelo-local",
            confidence=0.595,
            blocks=(
                PageTextBlock(
                    f"Referencia documental: {PRIMARY_CNJ}",
                    confidence=0.99,
                    bounding_box=high_box,
                ),
                PageTextBlock(
                    f"PROCESSO: {PRIMARY_CNJ}",
                    confidence=0.2,
                    bounding_box=low_box,
                ),
            ),
        )
    )

    field = metadata.fields["numero_processo"]
    assert field.state is FieldExtractionState.AMBIGUOUS
    assert field.value == ""
    assert any(
        evidence.ocr_confidence == 0.2 and evidence.bounding_box == low_box
        for evidence in field.evidence
    )


def test_legacy_v2_extraction_cannot_preserve_pre_fix_confidence():
    extracted = extract(PdfTextPage(1, f"PROCESSO: {PRIMARY_CNJ}"))
    payload = document_metadata_payload(extracted)
    payload["schema_version"] = 2

    restored = document_metadata_from_payload(freeze_payload(payload))
    aggregate = aggregate_process_metadata((restored,))

    assert restored.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert restored.fields["numero_processo"].value == ""
    assert aggregate.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS


def test_pre_fix_v3_extraction_cannot_preserve_confidence_after_reopen():
    extracted = extract(PdfTextPage(1, f"PROCESSO: {PRIMARY_CNJ}"))
    payload = document_metadata_payload(extracted)
    payload["schema_version"] = 3
    payload["fields"]["numero_processo"]["state"] = "CONFIDENT"
    payload["fields"]["numero_processo"]["value"] = PRIMARY_CNJ

    restored = document_metadata_from_payload(freeze_payload(payload))
    aggregate = aggregate_process_metadata((restored,))

    assert restored.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert restored.fields["numero_processo"].value == ""
    assert aggregate.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS


def test_current_v4_payload_cannot_assert_automatic_confidence():
    extracted = extract(PdfTextPage(1, f"PROCESSO: {PRIMARY_CNJ}"))
    payload = document_metadata_payload(extracted)
    payload["fields"]["numero_processo"]["state"] = "CONFIDENT"
    payload["fields"]["numero_processo"]["value"] = PRIMARY_CNJ

    with pytest.raises(ValueError, match="confiança automática"):
        document_metadata_from_payload(freeze_payload(payload))


def test_automatic_identity_requires_human_review_without_primary_document_role():
    metadata = extract(
        PdfTextPage(
            1,
            f"PROCESSO: {PRIMARY_CNJ}\n"
            "1 VARA FEDERAL\nAUTOR: Parte principal\nREU: Parte contraria",
        )
    )

    assert all(
        field.state is not FieldExtractionState.CONFIDENT
        for field in metadata.fields.values()
    )
    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""
    assert metadata.fields["numero_processo"].evidence


def test_ocr_offset_mapping_work_is_linear_in_page_size(monkeypatch):
    confused_cnj = PRIMARY_CNJ.replace("0", "O")
    blocks = tuple(
        PageTextBlock(
            f"Referencia {index}: {confused_cnj}",
            confidence=0.99,
            bounding_box=(float(index), 1.0, float(index + 1), 2.0),
        )
        for index in range(40)
    )
    text = "\n".join(block.text for block in blocks)
    original = metadata_module._ascii_upper
    processed_characters = 0

    def counted_ascii_upper(value):
        nonlocal processed_characters
        processed_characters += len(value)
        return original(value)

    monkeypatch.setattr(metadata_module, "_ascii_upper", counted_ascii_upper)
    extract(
        PdfTextPage(
            1,
            text,
            extraction_mode=PageExtractionMode.OCR,
            engine="ocr-local",
            engine_version="1",
            model_version="modelo-local",
            confidence=0.99,
            blocks=blocks,
        )
    )

    assert processed_characters < len(text) * 20


def test_later_page_anchor_cannot_override_first_page_reference():
    metadata = extract(
        PdfTextPage(
            1,
            f"Referencia documental: {PRIMARY_CNJ}\n"
            "TRIBUNAL REGIONAL FEDERAL DA 3 REGIAO",
        ),
        PdfTextPage(2, f"PROCESSO: {PRIMARY_CNJ}"),
    )

    assert metadata.fields["numero_processo"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["numero_processo"].value == ""
    assert metadata.fields["ramo_justica"].state is not FieldExtractionState.CONFIDENT
    assert metadata.fields["tribunal"].state is not FieldExtractionState.CONFIDENT
