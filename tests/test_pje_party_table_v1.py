from __future__ import annotations

import string

from hypothesis import given, strategies as st

from scripts.backend_contract.application.pje_party_table import (
    PjePartyPole,
    PjePartyTableState,
    parse_pje_party_table,
)


def test_table_requires_complete_rows_and_does_not_reenter_without_a_header():
    parsed = parse_pje_party_table(
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "ALICE EXEMPLO (AUTORA) ADVOGADO UM (ADVOGADO)\n"
        "O contrato menciona MARIA EXEMPLO (AUTORA)\n"
        "CARLA EXEMPLO (AUTORA) ADVOGADO DOIS (ADVOGADO)"
    )

    assert [(row.name, row.role) for row in parsed.rows] == [
        ("ALICE EXEMPLO", "AUTORA")
    ]
    assert parsed.final_state is PjePartyTableState.TERMINATED


def test_table_accepts_multiple_complete_party_and_representative_rows():
    parsed = parse_pje_party_table(
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "ALICE EXEMPLO (AUTORA) ADVOGADO UM (ADVOGADO)\n"
        "BRUNO EXEMPLO (AUTOR) PROCURADOR DOIS (PROCURADOR)\n"
        "BANCO EXEMPLO (REU) ADVOGADO TRES (ADVOGADO)"
    )

    assert [(row.name, row.role, row.pole) for row in parsed.rows] == [
        ("ALICE EXEMPLO", "AUTORA", PjePartyPole.ACTIVE),
        ("BRUNO EXEMPLO", "AUTOR", PjePartyPole.ACTIVE),
        ("BANCO EXEMPLO", "REU", PjePartyPole.PASSIVE),
    ]
    assert parsed.final_state is PjePartyTableState.AFTER_ROW


def test_table_reenters_only_after_a_new_complete_header():
    parsed = parse_pje_party_table(
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "ALICE EXEMPLO (AUTORA) ADVOGADO UM (ADVOGADO)\n"
        "FRONTEIRA ESTRUTURAL\n"
        "IGNORADA EXEMPLO (AUTORA) ADVOGADO DOIS (ADVOGADO)\n"
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "CARLA EXEMPLO (REQUERENTE) PROCURADOR TRES (PROCURADOR)"
    )

    assert [row.name for row in parsed.rows] == ["ALICE EXEMPLO", "CARLA EXEMPLO"]
    assert parsed.final_state is PjePartyTableState.AFTER_ROW


def test_explicit_pole_does_not_reenter_a_terminated_table_without_new_header():
    parsed = parse_pje_party_table(
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "ALICE EXEMPLO (AUTORA) ADVOGADO UM (ADVOGADO)\n"
        "FRONTEIRA ESTRUTURAL\n"
        "POLO ATIVO: IGNORADA EXEMPLO (AUTORA) ADVOGADO DOIS (ADVOGADO)"
    )

    assert [row.name for row in parsed.rows] == ["ALICE EXEMPLO"]
    assert parsed.final_state is PjePartyTableState.TERMINATED


def test_explicit_pole_must_agree_with_the_party_role():
    parsed = parse_pje_party_table(
        "POLO ATIVO - ALICE EXEMPLO (AUTORA) ADVOGADO UM (ADVOGADO)\n"
        "POLO PASSIVO: BANCO EXEMPLO (REU) ADVOGADO DOIS (ADVOGADO)\n"
        "POLO ATIVO: PARTE INCOERENTE (REU) ADVOGADO TRES (ADVOGADO)"
    )

    assert [(row.name, row.pole) for row in parsed.rows] == [
        ("ALICE EXEMPLO", PjePartyPole.ACTIVE),
        ("BANCO EXEMPLO", PjePartyPole.PASSIVE),
    ]
    assert parsed.final_state is PjePartyTableState.TERMINATED


def test_unicode_name_and_reversible_source_offsets_are_preserved():
    name = "AL\ufb01CE E\u0301XEMPLO (ALFA) S.A."
    source = (
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        f"{name} (AUTORA) ADVOGADO UM (ADVOGADO)"
    )

    parsed = parse_pje_party_table(source)

    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row.name == name
    assert source[row.source_start : row.source_end] == name
    assert row.source_line == f"{name} (AUTORA) ADVOGADO UM (ADVOGADO)"


def test_representative_cell_never_becomes_a_principal_party():
    parsed = parse_pje_party_table(
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "PARTE PRINCIPAL (REQUERENTE) NOME DO PROCURADOR (PROCURADOR)"
    )

    assert [row.name for row in parsed.rows] == ["PARTE PRINCIPAL"]
    assert all("PROCURADOR" not in row.name for row in parsed.rows)


@given(
    narrative=st.text(
        alphabet=string.ascii_letters + " ",
        min_size=1,
        max_size=60,
    ).filter(lambda value: bool(value.strip())),
    role=st.sampled_from(("AUTOR", "AUTORA", "REQUERENTE", "REU")),
)
def test_role_like_line_without_a_representative_cell_terminates_the_table(
    narrative: str,
    role: str,
):
    parsed = parse_pje_party_table(
        "PARTES PROCURADOR TERCEIRO VINCULADO\n"
        "ALICE EXEMPLO (AUTORA) ADVOGADO UM (ADVOGADO)\n"
        f"{narrative.strip()} ({role})"
    )

    assert [row.name for row in parsed.rows] == ["ALICE EXEMPLO"]
    assert parsed.final_state is PjePartyTableState.TERMINATED
