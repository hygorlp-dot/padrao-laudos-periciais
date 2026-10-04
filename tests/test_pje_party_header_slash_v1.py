"""#285 — cabeçalho real da tabela de partes PJe ("Procurador/Terceiro vinculado").

O PJe escreve "Partes Procurador/Terceiro vinculado", com barra. A gramática só
aceitava a forma sem barra que existia nas fixtures, e a capa real virava
"nenhuma proposta" sem nenhum aviso. Tudo sintético.
"""

from __future__ import annotations

import pytest

from scripts.backend_contract.application.pje_party_table import (
    PjeParticipantPole,
    PjePartyPole,
    parse_pje_participant_rows,
    parse_pje_party_table,
)
from tests.test_process_participants_v1 import (
    _cover,
    _import,
    _proposal_set,
    _runtime,
    _text_page,
)


_SLASH = "Partes Procurador/Terceiro vinculado"
_FIXTURE = "\n".join([
    "PJe - Processo Judicial Eletrônico",
    _SLASH,
    "AUTORA SINTÉTICA (AUTOR) ADVOGADO SINTÉTICO (ADVOGADO)",
    "EMPRESA SINTÉTICA (REU)",
]) + "\n"


def _summary(result):
    return [
        (item.pole.value, item.name, [rep.name for rep in item.representatives])
        for item in result.proposals
    ]


def test_red_fixture_with_the_real_slash_header_yields_both_poles_and_the_link():
    result = _proposal_set(_text_page(_FIXTURE))
    proposals = result.proposals
    assert sum(item.pole.value == "ACTIVE" for item in proposals) == 1
    assert sum(item.pole.value == "PASSIVE" for item in proposals) == 1
    assert sum(len(item.representatives) for item in proposals) == 1
    assert _summary(result) == [
        ("ACTIVE", "AUTORA SINTÉTICA", ["ADVOGADO SINTÉTICO"]),
        ("PASSIVE", "EMPRESA SINTÉTICA", []),
    ]
    assert result.interrupted_pages == ()
    # Proveniência exata: o trecho aponta para o nome na página, byte a byte.
    for item, name in zip(proposals, ("AUTORA SINTÉTICA", "EMPRESA SINTÉTICA")):
        (source,) = item.provenance
        assert source.page == 1 and source.filename == "autos.pdf"
        assert _FIXTURE[source.source_start:source.source_end] == name
    representative = proposals[0].representatives[0]
    (rep_source,) = representative.provenance
    assert _FIXTURE[rep_source.source_start:rep_source.source_end] == "ADVOGADO SINTÉTICO"


@pytest.mark.parametrize(
    "header",
    [
        "Partes Procurador/Terceiro vinculado",
        "Partes Procurador / Terceiro vinculado",
        "Partes Procuradores/Terceiro vinculado",
        "Partes Procuradores / Terceiros vinculados",
        "PARTES PROCURADOR/TERCEIRO VINCULADO",
        "  Partes   Procurador/Terceiro   vinculado  ",
        "PARTES PROCURADOR TERCEIRO VINCULADO",
    ],
)
def test_structural_header_variants_open_the_table(header):
    text = "\n".join([header, "ALFA (AUTOR) ADV (ADVOGADO)", "BETA (REU)"])
    parsed = parse_pje_participant_rows(text)
    assert [(row.pole, row.name) for row in parsed.rows] == [
        (PjeParticipantPole.ACTIVE, "ALFA"),
        (PjeParticipantPole.PASSIVE, "BETA"),
    ]
    assert parsed.unrecognized_header is False and parsed.interrupted is False
    # A gramática legada (campos escalares) lê o mesmo cabeçalho.
    legacy = parse_pje_party_table(text)
    assert [(row.pole, row.name) for row in legacy.rows] == [(PjePartyPole.ACTIVE, "ALFA")]


@pytest.mark.parametrize(
    "header",
    [
        "Partes Procurador|Terceiro vinculado",
        "Partes Procurador/Terceiro",
        "Partes Procurador/Vinculado",
        "Partes Procurador/Terceiro vinculado e outros",
        "Partes e Procuradores",
        "Partes Procurador//Terceiro vinculado",
        "Partes Procurador/Terceiro vincul",
        "Partes\nProcurador|Terceiro vinculado",
    ],
)
def test_header_like_lines_are_never_read_as_a_table_but_are_said(header):
    text = "\n".join([header, "ALFA (AUTOR) ADV (ADVOGADO)", "BETA (REU)"])
    parsed = parse_pje_participant_rows(text)
    assert parsed.rows == ()
    assert parsed.unrecognized_header is True
    result = _proposal_set(_text_page(text))
    assert result.proposals == () and result.interrupted_pages == (("autos.pdf", 1),)


@pytest.mark.parametrize(
    "line",
    [
        "Partes",
        "PARTES:",
        "As partes, por seus procuradores, requerem o que segue.",
        "Procurador/Terceiro vinculado",
        "Terceiro vinculado",
        # Prosa jurídica com quebra de linha começando em "partes".
        "Pedido de intimacao das\npartes por meio de seus procuradores constituidos.",
        "partes vinculadas ao contrato",
        "Partes intimadas na pessoa de seus procuradores.",
        "PARTES: PROCURADORIA GERAL DO ESTADO",
        "Partes\nAUTOR SINTETICO requer a juntada",
    ],
)
def test_vague_lines_neither_open_the_table_nor_raise_a_false_warning(line):
    text = "\n".join([line, "ALFA (AUTOR) ADV (ADVOGADO)", "BETA (REU)"])
    parsed = parse_pje_participant_rows(text)
    assert parsed.rows == () and parsed.unrecognized_header is False
    assert _proposal_set(_text_page(text)).interrupted_pages == ()


def test_header_split_over_two_lines_opens_the_table():
    for head, tail in (("Partes", "Procurador/Terceiro vinculado"), ("PARTES", "Procuradores / Terceiros vinculados")):
        text = "\n".join([head, tail, "FULANO DE TAL (AUTOR) ADV (ADVOGADO)", "CICLANO SA (REU)"])
        result = _proposal_set(_text_page(text))
        assert _summary(result) == [("ACTIVE", "FULANO DE TAL", ["ADV"]), ("PASSIVE", "CICLANO SA", [])]
        assert result.interrupted_pages == ()
        assert [row.name for row in parse_pje_party_table(text).rows] == ["FULANO DE TAL"]
    # A segunda linha só vale logo depois de "Partes"; separadas, nada abre.
    apart = _proposal_set(_text_page("Partes\nOutro texto\nProcurador/Terceiro vinculado\nFULANO (AUTOR)\n"))
    assert apart.proposals == ()


def test_pages_without_legible_text_are_said_never_counted_as_nothing_found():
    from types import SimpleNamespace
    from scripts.backend_contract.application.process_metadata import PageExtractionMode, PageProcessingStatus, PdfTextPage
    pages = (
        PdfTextPage(1, "", PageExtractionMode.OCR, processing_status=PageProcessingStatus.OCR_FAILED),
        PdfTextPage(2, "", processing_status=PageProcessingStatus.NOT_PROCESSED),
        PdfTextPage(3, "Despacho sintético.\n"),
    )
    from tests.test_process_participants_v1 import _document
    document = _document(*pages)
    from scripts.backend_contract.application.process_participants import ParticipantProposals
    result = ParticipantProposals(SimpleNamespace(execute=lambda _w: (document,))).execute("w")
    assert result.proposals == () and result.interrupted_pages == ()
    assert result.unread_pages == (("autos.pdf", 1), ("autos.pdf", 2))


def _slash_page(*lines):
    return _text_page("\n".join([_SLASH, *lines]) + "\n")


def test_adversarial_poles_and_representatives_with_the_slash_header():
    result = _proposal_set(_slash_page(
        "AUTORA UM (AUTORA) ADV UM (ADVOGADO)",
        "ADV DOIS (ADVOGADO)",
        "AUTOR DOIS (AUTOR)",
        "RE UM (REU) PROC UM (PROCURADOR)",
        "RE DOIS (REU)",
        "TERCEIRA (TERCEIRO INTERESSADO)",
        "ASSISTENTE SINTETICO (ASSISTENTE TECNICO)",
        "ORGAO SINTETICO (FISCAL DA LEI)",
    ))
    assert _summary(result) == [
        ("ACTIVE", "AUTORA UM", ["ADV UM", "ADV DOIS"]),
        ("ACTIVE", "AUTOR DOIS", []),
        ("PASSIVE", "RE UM", ["PROC UM"]),
        ("PASSIVE", "RE DOIS", []),
        ("OTHER", "TERCEIRA", []),
        ("OTHER", "ASSISTENTE SINTETICO", []),
        ("OTHER", "ORGAO SINTETICO", []),
    ]
    assert result.interrupted_pages == ()


def test_same_name_in_both_poles_or_twice_in_one_pole_is_never_merged():
    result = _proposal_set(_slash_page(
        "NOME IGUAL (AUTOR)", "NOME IGUAL (AUTOR)", "NOME IGUAL (REU)",
    ))
    assert _summary(result) == [
        ("ACTIVE", "NOME IGUAL", []), ("ACTIVE", "NOME IGUAL", []), ("PASSIVE", "NOME IGUAL", []),
    ]
    assert len({item.participant_id for item in result.proposals}) == 3


@pytest.mark.parametrize(
    "lines, names",
    [
        # Linha quebrada no meio do nome.
        (["ALFA (AUTOR)", "BETA SINTETICA DE NOME", "MUITO LONGO (REU)"], ["ALFA"]),
        # Papel desconhecido.
        (["ALFA (AUTOR)", "BETA (LITISCONSORTE)"], ["ALFA"]),
        # Polo explícito contraditório.
        (["POLO ATIVO", "ALFA (REU)"], []),
        # Representante depois da troca de polo não se liga à parte anterior.
        (["POLO ATIVO", "ALFA (AUTOR)", "POLO PASSIVO", "ADV SOLTO (ADVOGADO)"], ["ALFA"]),
        # Caractere de controle.
        (["ALFA (AUTOR)", "BE\x02TA (REU)"], ["ALFA"]),
    ],
)
def test_broken_rows_stop_and_are_said(lines, names):
    result = _proposal_set(_slash_page(*lines))
    assert [item.name for item in result.proposals] == names
    assert result.interrupted_pages == (("autos.pdf", 1),)
    for item in result.proposals:
        assert item.representatives == ()


def test_ocr_spacing_around_the_slash_is_tolerated_but_not_inside_words():
    spaced = _proposal_set(_text_page("Partes  Procurador /  Terceiro  vinculado\nALFA (AUTOR)\n"))
    assert [item.name for item in spaced.proposals] == ["ALFA"]
    split = _proposal_set(_text_page("Partes Procu rador/Terceiro vinculado\nALFA (AUTOR)\n"))
    assert split.proposals == () and split.interrupted_pages == (("autos.pdf", 1),)


def test_representative_on_the_next_page_is_flagged_not_attached():
    result = _proposal_set(
        _slash_page("ALFA (AUTOR)"),
        _text_page("ADV PROXIMA PAGINA (ADVOGADO)\nOutro texto\n", 2),
    )
    assert _summary(result) == [("ACTIVE", "ALFA", [])]
    assert result.interrupted_pages == (("autos.pdf", 2),)


def test_product_flow_reads_the_real_slash_cover_over_http(tmp_path):
    from tests.test_product_integration_oracle_v1 import _http
    runtime = _runtime(tmp_path)
    try:
        status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Capa com barra"})
        assert status == 201
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        _import(runtime, root, _cover([
            _SLASH,
            "AUTORA SINTÉTICA (AUTOR) ADVOGADO SINTÉTICO (ADVOGADO)",
            "EMPRESA SINTÉTICA (REU)",
        ]), "capa-barra.pdf")
        status, view = _http(runtime, "GET", root + "/process-participants")
        assert status == 200
        assert [(p["pole"], p["name"], [r["name"] for r in p["representatives"]]) for p in view["proposals"]] == [
            ("ACTIVE", "AUTORA SINTÉTICA", ["ADVOGADO SINTÉTICO"]),
            ("PASSIVE", "EMPRESA SINTÉTICA", []),
        ]
        assert all(p["review_state"] == "PROPOSED" for p in view["proposals"])
        assert view["participants"] == [] and view["interrupted_pages"] == [] and view["unread_pages"] == []
        source = view["proposals"][0]["provenance"][0]
        assert source["filename"] == "capa-barra.pdf" and source["page"] == 1
        assert source["excerpt"].startswith("AUTORA SINTÉTICA (AUTOR)")
    finally:
        runtime.close()
