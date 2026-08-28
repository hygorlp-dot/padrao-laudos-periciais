"""Gramática estrutural e fail-closed da tabela de partes da capa PJe."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class PjePartyTableState(StrEnum):
    OUTSIDE_TABLE = "OUTSIDE_TABLE"
    HEADER_SEEN = "HEADER_SEEN"
    IN_TABLE = "IN_TABLE"
    IN_ROW_CONTINUATION = "IN_ROW_CONTINUATION"
    AFTER_ROW = "AFTER_ROW"
    TERMINATED = "TERMINATED"


class PjePartyPole(StrEnum):
    ACTIVE = "ACTIVE"
    PASSIVE = "PASSIVE"


@dataclass(frozen=True, slots=True)
class PjePartyTableRow:
    name: str
    role: str
    pole: PjePartyPole
    source_line: str
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class PjePartyTableParseResult:
    rows: tuple[PjePartyTableRow, ...]
    final_state: PjePartyTableState


_ACTIVE_ROLES = frozenset({"AUTOR", "AUTORA", "REQUERENTE", "EXEQUENTE"})
_PASSIVE_ROLES = frozenset(
    {"REQUERIDO", "REQUERIDA", "REU", "EXECUTADO", "EXECUTADA"}
)
_HEADER = re.compile(
    r"^\s*PARTES\s+PROCURADOR(?:ES)?(?:\s+TERCEIRO\s+VINCULADO)?\s*$",
    re.IGNORECASE,
)
_SUPPORTED_ROW = re.compile(
    r"^\s*"
    r"(?:(?P<explicit_pole>POLO\s+(?:ATIVO|PASSIVO))\s*[-:]\s*)?"
    r"(?P<name>\S(?:.*?\S)?)\s+"
    r"\((?P<role>"
    r"AUTOR|AUTORA|REQUERENTE|EXEQUENTE|"
    r"REQUERIDO|REQUERIDA|REU|EXECUTADO|EXECUTADA"
    r")\)\s+"
    r"(?P<representative>\S(?:.*?\S)?)\s+"
    r"\((?P<representative_role>ADVOGADO|PROCURADOR)\)\s*$",
    re.IGNORECASE,
)


def _ascii_upper_with_source_indices(value: str) -> tuple[str, tuple[int, ...]]:
    normalized: list[str] = []
    source_indices: list[int] = []
    for index, character in enumerate(value):
        decomposed = unicodedata.normalize("NFKD", character)
        fragment = "".join(
            item for item in decomposed if not unicodedata.combining(item)
        ).upper()
        normalized.append(fragment)
        source_indices.extend(index for _ in fragment)
    return "".join(normalized), tuple(source_indices)


def _pole_for_role(role: str) -> PjePartyPole:
    if role in _ACTIVE_ROLES:
        return PjePartyPole.ACTIVE
    if role in _PASSIVE_ROLES:
        return PjePartyPole.PASSIVE
    raise ValueError("papel processual não suportado pela tabela PJe")


def _explicit_pole(value: str | None) -> PjePartyPole | None:
    if value is None:
        return None
    return (
        PjePartyPole.ACTIVE
        if value.endswith("ATIVO")
        else PjePartyPole.PASSIVE
    )


def _source_bound(
    source_indices: tuple[int, ...],
    normalized_index: int,
    source_length: int,
) -> int:
    if normalized_index >= len(source_indices):
        return source_length
    return source_indices[normalized_index]


def parse_pje_party_table(page_text: str) -> PjePartyTableParseResult:
    """Parseia somente linhas completas suportadas, sem estado entre páginas."""

    if type(page_text) is not str:
        raise TypeError("texto da página PJe inválido")

    state = PjePartyTableState.OUTSIDE_TABLE
    rows: list[PjePartyTableRow] = []
    line_start = 0

    for raw_line in page_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        normalized, source_indices = _ascii_upper_with_source_indices(line)

        if _HEADER.fullmatch(normalized):
            state = PjePartyTableState.HEADER_SEEN
            line_start += len(raw_line)
            continue

        if state is PjePartyTableState.TERMINATED:
            line_start += len(raw_line)
            continue

        match = _SUPPORTED_ROW.fullmatch(normalized)
        explicit_pole = _explicit_pole(
            match.group("explicit_pole") if match is not None else None
        )
        row_is_expected = state in {
            PjePartyTableState.HEADER_SEEN,
            PjePartyTableState.AFTER_ROW,
        }
        structurally_addressed = explicit_pole is not None

        if match is None or not (row_is_expected or structurally_addressed):
            if state is not PjePartyTableState.OUTSIDE_TABLE:
                state = PjePartyTableState.TERMINATED
            line_start += len(raw_line)
            continue

        role = match.group("role")
        role_pole = _pole_for_role(role)
        if explicit_pole is not None and explicit_pole is not role_pole:
            state = PjePartyTableState.TERMINATED
            line_start += len(raw_line)
            continue

        state = PjePartyTableState.IN_TABLE
        normalized_start, normalized_end = match.span("name")
        local_source_start = _source_bound(
            source_indices,
            normalized_start,
            len(line),
        )
        local_source_end = _source_bound(
            source_indices,
            normalized_end,
            len(line),
        )
        rows.append(
            PjePartyTableRow(
                name=line[local_source_start:local_source_end],
                role=role,
                pole=role_pole,
                source_line=line,
                source_start=line_start + local_source_start,
                source_end=line_start + local_source_end,
            )
        )
        state = PjePartyTableState.AFTER_ROW
        line_start += len(raw_line)

    # No row-continuation grammar is currently supported. A split or incomplete
    # row therefore terminates fail-closed instead of entering that state.
    return PjePartyTableParseResult(tuple(rows), state)
