from __future__ import annotations

import string
from statistics import median
from time import perf_counter

from hypothesis import given, strategies as st

from scripts.backend_contract.application.pje_party_table import (
    PjePartyPole,
    PjePartyTableState,
    parse_pje_party_table,
)


_HEADER = "PARTES PROCURADOR TERCEIRO VINCULADO\n"


def _repeated_to_length(fragment: str, length: int) -> str:
    return (fragment * ((length // len(fragment)) + 1))[:length]


def _median_parse_seconds(source: str, *, samples: int = 3) -> float:
    parse_pje_party_table(_HEADER + "A (AUTORA) B (ADVOGADO)")
    durations = []
    for _ in range(samples):
        started = perf_counter()
        parse_pje_party_table(source)
        durations.append(perf_counter() - started)
    return median(durations)


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


def test_repetitive_incomplete_rows_reject_with_bounded_linear_scaling():
    one_thousand = _HEADER + _repeated_to_length("X (AUTOR) ", 1_000)
    ten_thousand = _HEADER + _repeated_to_length("X (AUTOR) ", 10_000)
    fifty_thousand = _HEADER + _repeated_to_length("X (AUTOR) ", 50_000)

    assert parse_pje_party_table(one_thousand).rows == ()
    assert parse_pje_party_table(ten_thousand).rows == ()
    assert parse_pje_party_table(fifty_thousand).rows == ()

    ten_thousand_median = _median_parse_seconds(ten_thousand)
    fifty_thousand_median = _median_parse_seconds(fifty_thousand)

    assert fifty_thousand_median <= 1.0
    assert fifty_thousand_median / max(ten_thousand_median, 1e-9) <= 8.0


def test_apparent_representative_suffix_does_not_resolve_multiple_party_roles():
    ambiguous = (
        _HEADER
        + _repeated_to_length("X (AUTOR) ", 49_000)
        + "NOME APARENTE (ADVOGADO)"
    )

    parsed = parse_pje_party_table(ambiguous)

    assert parsed.rows == ()
    assert parsed.final_state is PjePartyTableState.TERMINATED


def test_different_party_roles_without_a_unique_partition_fail_closed():
    parsed = parse_pje_party_table(
        _HEADER
        + "ALFA (AUTOR) BETA (REQUERENTE) GAMA (REU) "
        + "DELTA (EXECUTADO) REPRESENTANTE (ADVOGADO)"
    )

    assert parsed.rows == ()
    assert parsed.final_state is PjePartyTableState.TERMINATED


def test_long_valid_row_is_linear_and_preserves_the_exact_source_slice():
    party_name = "P" * 24_950
    representative_name = "R" * 24_950
    source = (
        _HEADER
        + f"{party_name} (AUTORA) {representative_name} (ADVOGADO)"
    )

    started = perf_counter()
    parsed = parse_pje_party_table(source)
    duration = perf_counter() - started

    assert len(parsed.rows) == 1
    assert parsed.rows[0].name == party_name
    assert source[parsed.rows[0].source_start : parsed.rows[0].source_end] == party_name
    assert duration <= 1.0


@given(
    first_role=st.sampled_from(("AUTOR", "AUTORA", "REQUERENTE", "REU")),
    second_role=st.sampled_from(
        ("EXEQUENTE", "REQUERIDO", "REQUERIDA", "EXECUTADO")
    ),
)
def test_multiple_plausible_party_role_partitions_always_fail_closed(
    first_role: str,
    second_role: str,
):
    parsed = parse_pje_party_table(
        _HEADER
        + f"PARTE UM ({first_role}) PARTE DOIS ({second_role}) "
        + "REPRESENTANTE (PROCURADOR)"
    )

    assert parsed.rows == ()
    assert parsed.final_state is PjePartyTableState.TERMINATED


@given(
    party_name=st.text(
        alphabet="ABCDE abcdeáéíóúÇﬁ",
        min_size=1,
        max_size=80,
    ).filter(lambda value: bool(value.strip())),
    representative_name=st.text(
        alphabet="FGHIJ fghijáéíóúÇﬁ",
        min_size=1,
        max_size=80,
    ).filter(lambda value: bool(value.strip())),
)
def test_supported_unicode_row_always_round_trips_its_source_slice(
    party_name: str,
    representative_name: str,
):
    party_name = party_name.strip()
    representative_name = representative_name.strip()
    source = (
        _HEADER
        + f"{party_name} (AUTORA) {representative_name} (ADVOGADO)"
    )

    parsed = parse_pje_party_table(source)

    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row.name == party_name
    assert source[row.source_start : row.source_end] == party_name
