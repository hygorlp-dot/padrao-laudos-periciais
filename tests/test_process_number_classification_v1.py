"""#286 — número do processo principal x processos citados nos autos.

Tudo sintético. Os números CNJ são gerados com dígito verificador válido.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.backend_contract.application.case_document_texts import CaseDocumentText, LogicalDocumentSpan
from scripts.backend_contract.application.process_metadata import (
    PageExtractionMode,
    PageProcessingStatus,
    PdfTextPage,
    validate_cnj_number,
)
from scripts.backend_contract.application.process_number_classification import (
    GetProcessNumberClassification,
    OccurrenceContext,
    PrimaryResolution,
    ProcessNumberClass,
    UnresolvedReason,
    classify_process_numbers,
    process_number_classification_dto,
)


def _cnj(sequence: int, year: int = 2024, segment: int = 4, court: int = 5, origin: int = 1) -> str:
    for check in range(100):
        value = f"{sequence:07d}-{check:02d}.{year}.{segment}.{court:02d}.{origin:04d}"
        try:
            return validate_cnj_number(value).canonical
        except ValueError:
            continue
    raise AssertionError("sem dígito verificador")


MAIN = _cnj(1234567)
OTHER = _cnj(7654321)
PRECEDENTS = [_cnj(7000000 + index, 2019) for index in range(12)]

COVER = "\n".join([
    "PODER JUDICIÁRIO",
    "PJe - Processo Judicial Eletrônico",
    f"Número: {MAIN}",
    "Classe: PROCEDIMENTO COMUM CÍVEL",
    "Órgão julgador: 1ª Vara Federal",
])
DECISION = "\n".join([
    "PODER JUDICIÁRIO",
    "JUSTIÇA FEDERAL",
    "1ª VARA FEDERAL",
    f"PROCESSO: {MAIN}",
    "AUTOR: ALFA SINTÉTICA",
    "RÉU: BETA SINTÉTICA",
    "DECISÃO",
])


def _page(text: str, number: int = 1, *, mode=PageExtractionMode.NATIVE_TEXT, confidence=None, status=PageProcessingStatus.AVAILABLE):
    return PdfTextPage(number, text, mode, confidence=confidence, processing_status=status)


def _doc(*pages, filename="autos.pdf", content="11111111-1111-4111-8111-111111111111", logical=(), pending=False):
    return CaseDocumentText(content, "a" * 64, filename, tuple(pages), tuple(logical), pending)


def _classify(*documents):
    return classify_process_numbers(documents)


def _classes(result):
    return {item.value: item.classification for item in result.candidates}


def test_main_number_and_ten_cited_precedents():
    citations = "\n".join(f"Nesse sentido: TRF5, AC {number}, Rel. Des. Fulano, julgado em 2020." for number in PRECEDENTS[:10])
    result = _classify(_doc(_page(DECISION + "\n" + citations)))
    assert result.resolution is PrimaryResolution.RESOLVED and result.primary_value == MAIN
    assert result.confidence == "MEDIUM"
    classes = _classes(result)
    assert classes.pop(MAIN) is ProcessNumberClass.PRIMARY
    assert set(classes.values()) == {ProcessNumberClass.CITED_CASE} and len(classes) == 10
    assert result.candidates[0].value == MAIN


def test_precedent_repeated_twenty_times_never_wins_by_frequency():
    repeated = "\n".join(f"Conforme REsp {PRECEDENTS[0]}, STJ." for _ in range(20))
    result = _classify(_doc(_page(DECISION + "\n" + repeated)))
    assert result.primary_value == MAIN
    cited = next(item for item in result.candidates if item.value == PRECEDENTS[0])
    assert cited.classification is ProcessNumberClass.CITED_CASE and cited.occurrence_count == 20
    # Sem número principal, a frequência também não promove nada.
    alone = _classify(_doc(_page("PETIÇÃO\n" + repeated)))
    assert alone.resolution is PrimaryResolution.UNRESOLVED and alone.primary_value is None
    assert alone.unresolved_reason is UnresolvedReason.NO_PRIMARY_SOURCE
    assert _classes(alone) == {PRECEDENTS[0]: ProcessNumberClass.CITED_CASE}


@pytest.mark.parametrize("line", [
    f"Processo relacionado: {OTHER}",
    f"Distribuído por dependência ao processo {OTHER}",
    f"Autos de origem: {OTHER}",
    f"Referência: {OTHER}",
])
def test_related_case_is_classified_and_not_promoted(line):
    result = _classify(_doc(_page(DECISION + "\n" + line)))
    assert result.primary_value == MAIN
    assert _classes(result)[OTHER] is ProcessNumberClass.RELATED_CASE


def test_related_case_declared_on_the_previous_heading_line():
    result = _classify(_doc(_page(DECISION + "\nProcessos relacionados:\n" + OTHER)))
    assert _classes(result)[OTHER] is ProcessNumberClass.RELATED_CASE


def test_number_only_on_the_pje_cover_is_primary_with_high_confidence():
    result = _classify(_doc(_page(COVER)))
    assert result.resolution is PrimaryResolution.RESOLVED and result.primary_value == MAIN
    assert result.confidence == "HIGH"
    (evidence,) = result.candidates[0].occurrences
    assert evidence.context is OccurrenceContext.PJE_COVER and evidence.page == 1
    assert COVER[evidence.source_start:evidence.source_end] == MAIN


def test_cover_decision_and_initial_petition_corroborate():
    result = _classify(_doc(_page(COVER, 1), _page(DECISION, 2), _page(f"PETIÇÃO INICIAL\nAutos n. {MAIN}\n", 3)))
    assert result.primary_value == MAIN and result.confidence == "HIGH"
    (candidate,) = result.candidates
    assert candidate.occurrence_count == 3
    assert [o.context for o in candidate.occurrences] == [
        OccurrenceContext.PJE_COVER, OccurrenceContext.JUDICIAL_HEADER, OccurrenceContext.UNQUALIFIED,
    ]


def test_two_conflicting_pje_covers_leave_the_primary_unresolved():
    result = _classify(_doc(_page(COVER, 1), _page(COVER.replace(MAIN, OTHER), 2)))
    assert result.resolution is PrimaryResolution.UNRESOLVED and result.primary_value is None
    assert result.unresolved_reason is UnresolvedReason.CONFLICTING_PRIMARY_SOURCES
    assert all(item.primary_evidence for item in result.candidates)
    assert ProcessNumberClass.PRIMARY not in set(_classes(result).values())


def test_composite_pdf_of_two_cases_is_unresolved():
    result = _classify(_doc(_page(DECISION, 1), _page(DECISION.replace(MAIN, OTHER), 2)))
    assert result.resolution is PrimaryResolution.UNRESOLVED
    assert result.unresolved_reason is UnresolvedReason.CONFLICTING_PRIMARY_SOURCES
    # Capa de um processo e cabeçalho de outro: também conflito, nunca escolha.
    mixed = _classify(_doc(_page(COVER, 1)), _doc(_page(DECISION.replace(MAIN, OTHER)), filename="outro.pdf", content="22222222-2222-4222-8222-222222222222"))
    assert mixed.resolution is PrimaryResolution.UNRESOLVED


def test_partial_ocr_never_supports_the_primary_and_unread_pages_are_said():
    weak = _page(DECISION, 1, mode=PageExtractionMode.OCR, confidence=0.5)
    failed = PdfTextPage(2, "", PageExtractionMode.OCR, processing_status=PageProcessingStatus.OCR_FAILED)
    result = _classify(_doc(weak, failed))
    assert result.primary_value is None and result.resolution is PrimaryResolution.UNRESOLVED
    assert result.unresolved_reason is UnresolvedReason.READING_INCOMPLETE
    assert result.unread_pages == (("autos.pdf", 2),)
    assert _classes(result) == {MAIN: ProcessNumberClass.UNKNOWN}
    # OCR confiável com confusão de dígitos (O/0) ainda é lido.
    strong = _page(DECISION.replace(MAIN, MAIN.replace("0", "O")), 1, mode=PageExtractionMode.OCR, confidence=0.95)
    assert _classify(_doc(strong)).primary_value == MAIN


def test_truncated_or_invalid_numbers_are_never_candidates():
    truncated = DECISION.replace(MAIN, MAIN[:15])
    result = _classify(_doc(_page(truncated)))
    assert result.resolution is PrimaryResolution.NOT_FOUND and result.candidates == ()
    wrong_check = MAIN[:8] + ("00" if MAIN[8:10] != "00" else "01") + MAIN[10:]
    invalid = _classify(_doc(_page(DECISION.replace(MAIN, wrong_check))))
    assert invalid.candidates == () and invalid.invalid_occurrences == (("autos.pdf", 1),)


def test_citation_on_the_labelled_line_or_in_a_jurisprudence_section_is_cited():
    inline = _classify(_doc(_page(DECISION + f"\nPROCESSO: {OTHER} (AgInt no REsp, Rel. Min. Fulano)")))
    assert inline.primary_value == MAIN and _classes(inline)[OTHER] is ProcessNumberClass.CITED_CASE
    section = _classify(_doc(_page(DECISION + f"\nJURISPRUDÊNCIA\nPROCESSO: {OTHER}\nTexto da ementa sintética.")))
    assert section.primary_value == MAIN and _classes(section)[OTHER] is ProcessNumberClass.CITED_CASE


def test_an_unlabelled_number_in_a_judicial_piece_is_not_promoted():
    text = DECISION.replace(f"PROCESSO: {MAIN}", "") + f"\nVistos. O feito {OTHER} segue concluso."
    result = _classify(_doc(_page(text)))
    assert result.primary_value is None and _classes(result) == {OTHER: ProcessNumberClass.UNKNOWN}


def test_excluded_piece_and_pending_documents_are_respected():
    excluded = LogicalDocumentSpan("DOC-1", "Decisão", "DECISAO", 1, 1, False)
    result = _classify(_doc(_page(DECISION), logical=(excluded,)), _doc(filename="nova.pdf", content="33333333-3333-4333-8333-333333333333", pending=True))
    assert result.candidates == () and result.pending_documents == ("nova.pdf",)
    assert result.resolution is PrimaryResolution.UNRESOLVED and result.unresolved_reason is UnresolvedReason.READING_INCOMPLETE


def test_read_failure_is_unavailable_not_nothing_found():
    def broken(_workspace):
        raise OSError("disco")
    result = GetProcessNumberClassification(SimpleNamespace(execute=broken)).execute("w")
    assert result.resolution is PrimaryResolution.UNRESOLVED
    assert result.unresolved_reason is UnresolvedReason.SOURCES_UNAVAILABLE


def test_dto_lists_structural_evidence_first_and_caps_occurrences():
    repeated = "\n".join(f"Conforme REsp {PRECEDENTS[0]}, STJ." for _ in range(20))
    dto = process_number_classification_dto(_classify(_doc(_page(f"Autos n. {MAIN}\n" + DECISION + "\n" + repeated))))
    assert dto["resolution"] == "RESOLVED" and dto["primary_value"] == MAIN
    primary = dto["candidates"][0]
    assert primary["classification"] == "PRIMARY" and primary["occurrences"][0]["context"] == "JUDICIAL_HEADER"
    cited = dto["candidates"][1]
    assert cited["occurrence_count"] == 20 and len(cited["occurrences"]) == 5


def test_product_route_proposes_the_cover_number_and_lists_cited_cases(tmp_path):
    from tests.test_process_participants_v1 import _cover, _import, _runtime
    from tests.test_product_integration_oracle_v1 import _http
    runtime = _runtime(tmp_path)
    try:
        status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Número principal"})
        assert status == 201
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        status, empty = _http(runtime, "GET", root + "/process-number")
        assert status == 200 and empty["resolution"] == "NOT_FOUND" and empty["candidates"] == []
        _import(runtime, root, _cover([
            f"Número: {MAIN}",
            f"Nesse sentido: TRF5, AC {PRECEDENTS[0]}, Rel. Des. Fulano.",
        ]), "capa.pdf")
        status, view = _http(runtime, "GET", root + "/process-number")
        assert status == 200
        assert view["resolution"] == "RESOLVED" and view["primary_value"] == MAIN and view["confidence"] == "HIGH"
        assert [(c["value"], c["classification"]) for c in view["candidates"]] == [
            (MAIN, "PRIMARY"), (PRECEDENTS[0], "CITED_CASE"),
        ]
        assert view["candidates"][0]["occurrences"][0]["filename"] == "capa.pdf"
        # Nada foi gravado no registro do processo.
        status, process = _http(runtime, "GET", root + "/process-case")
        assert status == 200 and process["data"]["numero_processo"] == ""
        assert _http(runtime, "POST", root + "/process-number", {})[0] == 405
    finally:
        runtime.close()


# --- Revisão independente da PR (#286).

_JUDICIAL_TOP = "PODER JUDICIÁRIO\nJUSTIÇA FEDERAL\n2ª VARA FEDERAL\n"


def test_precedent_labelled_after_an_inline_ementa_is_never_primary():
    text = _JUDICIAL_TOP + f"AUTOR: x\nEMENTA: ADMINISTRATIVO. RESPONSABILIDADE.\nProcesso: {OTHER}\nClasse: APELAÇÃO CÍVEL\nRelator: Des. Z\n"
    result = _classify(_doc(_page(text)))
    assert result.primary_value is None and _classes(result)[OTHER] is ProcessNumberClass.CITED_CASE


def test_precedent_labelled_inside_the_body_with_citation_on_the_next_line_is_cited():
    text = _JUDICIAL_TOP + (
        f"PROCEDIMENTO COMUM CÍVEL Nº {MAIN}\nAUTOR: x\nRÉU: y\nSENTENÇA\nCito julgado do TRF5:\n"
        f"PROCESSO: {OTHER}\nAPELAÇÃO CÍVEL, DESEMBARGADOR FEDERAL FULANO, julgado em 2020.\n"
    )
    result = _classify(_doc(_page(text)))
    assert result.primary_value is None
    assert _classes(result)[OTHER] is ProcessNumberClass.CITED_CASE


@pytest.mark.parametrize("line", [
    "PROCESSO Nº: {n} - APELAÇÃO CÍVEL",
    "PROCESSO: {n} - APELAÇÃO CÍVEL (198) - RELATOR: DES. FED. Z",
    "PROCESSO: {n} - TRF5",
])
def test_appellate_header_of_the_case_itself_is_primary_not_a_precedent(line):
    text = _JUDICIAL_TOP + line.format(n=MAIN) + "\nAPELANTE: x\nAPELADO: y\nAUTOR: x\nACÓRDÃO\n"
    result = _classify(_doc(_page(text)))
    assert result.primary_value == MAIN
    assert _classes(result)[MAIN] is ProcessNumberClass.PRIMARY


def test_labelled_number_with_class_only_outside_a_header_is_not_called_a_precedent():
    result = _classify(_doc(_page(f"Petição sintética\nPROCESSO: {MAIN} - APELAÇÃO CÍVEL\nRequer a juntada.\n")))
    assert result.primary_value is None and _classes(result)[MAIN] is ProcessNumberClass.UNKNOWN


def test_cover_label_on_the_previous_line_is_read():
    cover = "PODER JUDICIÁRIO\nPJe - Processo Judicial Eletrônico\nNúmero:\n" + MAIN + "\nClasse: PROCEDIMENTO COMUM CÍVEL\n"
    result = _classify(_doc(_page(cover)))
    assert result.primary_value == MAIN and result.confidence == "HIGH"


def test_weak_ocr_cover_says_why_it_is_unresolved():
    result = _classify(_doc(_page(COVER, mode=PageExtractionMode.OCR, confidence=0.5)))
    assert result.primary_value is None and result.unresolved_reason is UnresolvedReason.LOW_CONFIDENCE_OCR


def test_long_single_line_pages_stay_linear():
    from time import perf_counter
    line = " ".join(f"ver {PRECEDENTS[0]}" for _ in range(5000))
    started = perf_counter()
    result = _classify(_doc(_page(_JUDICIAL_TOP + "AUTOR: x\n" + line)))
    assert perf_counter() - started < 5.0
    assert result.candidates[0].occurrence_count == 5000


# --- Revisão delta (#286): cabeçalho sem título de peça.

@pytest.mark.parametrize("body", [
    "AUTOR: x\nRÉU: y\nProcesso nº {b}\n(STJ, julgado em 2020)\n",
    "Vistos etc.\nCito julgado do TRF5:\nPROCESSO: {b}\nAPELAÇÃO CÍVEL, DESEMBARGADOR FEDERAL FULANO, 4ª TURMA, JULGAMENTO: 01/01/2020.\n",
    "AUTOR: x\nRÉU: y\nTrata-se de ação. Confira-se julgado:\nProcesso: {b}\nClasse: APELAÇÃO CÍVEL\nRelator: Des. Z\nJulgado em 01/01/2020\n",
])
def test_precedent_inside_an_untitled_header_zone_is_never_primary(body):
    text = _JUDICIAL_TOP + f"PROCEDIMENTO COMUM CÍVEL Nº {MAIN}\nAUTOR: x\nRÉU: y\n" + body.format(b=OTHER)
    result = _classify(_doc(_page(text)))
    assert result.primary_value != OTHER
    assert _classes(result)[OTHER] is ProcessNumberClass.CITED_CASE


def test_numero_unico_label_and_origin_without_de():
    cover = "PODER JUDICIÁRIO\nPJe - Processo Judicial Eletrônico\n" + f"Número único: {MAIN}\nProcesso origem: {OTHER}\n"
    result = _classify(_doc(_page(cover)))
    assert result.primary_value == MAIN and _classes(result)[OTHER] is ProcessNumberClass.RELATED_CASE


# --- Segunda revisão delta (#286): zona de cabeçalho por forma de linha.

@pytest.mark.parametrize("lead", [
    "Transcrevo o seguinte julgado:",
    "TRANSCREVO O SEGUINTE JULGADO DO TRF5",
    "Veja o julgado abaixo",
    "Conforme o Tribunal decidiu:",
])
def test_any_non_header_line_closes_the_header_zone(lead):
    text = _JUDICIAL_TOP + f"AUTOR: x\nRÉU: y\n{lead}\nPROCESSO: {OTHER}\nAPELAÇÃO CÍVEL, DESEMBARGADOR FEDERAL FULANO, 4ª TURMA.\n"
    result = _classify(_doc(_page(text)))
    assert result.primary_value is None, lead


@pytest.mark.parametrize("top", [
    "TRIBUNAL REGIONAL FEDERAL DA 5ª REGIÃO\nGABINETE DO DESEMBARGADOR FEDERAL Z\n",
    "PODER JUDICIÁRIO\nJUSTIÇA FEDERAL DE 1º GRAU EM PERNAMBUCO\n",
    "Tribunal Regional Federal da 5ª Região\n",
    "2ª Vara Federal da Seção Judiciária de Pernambuco\nAv. Desembargador Guerra Barreto, s/n - Recife - PE\n",
    "Tribunal de Justiça do Estado de Pernambuco\nJuízo Federal da 2ª Vara - PE\n",
])
def test_real_header_layouts_keep_the_case_number_primary(top):
    text = top + f"PROCESSO Nº: {MAIN} - APELAÇÃO CÍVEL\nAPELANTE: x\nAPELADO: y\nRELATOR: DESEMBARGADOR FEDERAL Z\nDATA DE JULGAMENTO: 01/01/2024\nACÓRDÃO\n"
    result = _classify(_doc(_page(text)))
    assert result.primary_value == MAIN, top


# --- Terceira revisão delta (#286): fim do bloco de partes, primeiro rótulo.

@pytest.mark.parametrize("tail", [
    "PROCEDIMENTO COMUM CÍVEL Nº {a}\nAUTOR: x\nRÉU: y\nProcesso: {b}\nClasse: APELAÇÃO CÍVEL\nRelator: Des. Z\nÓrgão julgador: 4ª Turma\nJulgado em 01/01/2020\n",
    "AUTOR: x\nRÉU: y\nProcesso: {b}\nClasse: APELAÇÃO CÍVEL\nRelator: Des. Z\n",
    "AUTOR: x\nRÉU: y\nProcesso {b}, Apelação Cível, 4ª Turma, TRF5.\n",
    "AUTOR: x\nRÉU: y\nJustiça gratuita deferida.\nProcesso nº {b} - Apelação Cível - TRF5\n",
    "AUTOR: x\nRÉU: y\nTribunal Regional Federal da 5ª Região, no\nPROCESSO: {b}, APELAÇÃO CÍVEL, 4ª TURMA\n",
])
def test_a_labelled_number_after_the_party_block_is_never_primary(tail):
    result = _classify(_doc(_page(_JUDICIAL_TOP + tail.format(a=MAIN, b=OTHER))))
    assert result.primary_value != OTHER


def test_only_the_first_labelled_number_of_the_header_counts():
    text = _JUDICIAL_TOP + f"PROCESSO: {MAIN}\nPROCESSO: {OTHER}\nAUTOR: x\nRÉU: y\nSENTENÇA\n"
    result = _classify(_doc(_page(text)))
    assert result.primary_value == MAIN and _classes(result)[OTHER] is ProcessNumberClass.UNKNOWN


@pytest.mark.parametrize("top", [
    "Seção A da 12ª Vara Cível da Capital\n",
    "Fórum Desembargador Rodolfo Aureliano\n",
    "Juiz Federal Fulano de Tal\n",
    "Assinado eletronicamente por: FULANO - 01/01/2024\nNum. 123456 - Pág. 1\n",
])
def test_more_real_header_lines_keep_the_case_number(top):
    text = "PODER JUDICIÁRIO\n" + top + f"PROCESSO: {MAIN}\nAUTOR: x\nRÉU: y\nSENTENÇA\n"
    assert _classify(_doc(_page(text))).primary_value == MAIN, top
