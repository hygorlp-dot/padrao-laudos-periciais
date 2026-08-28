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
_EXPLICIT_POLES = (
    ("POLO ATIVO", PjePartyPole.ACTIVE),
    ("POLO PASSIVO", PjePartyPole.PASSIVE),
)
_PARTY_ROLE_TOKENS = tuple(
    (f"({role})", role) for role in sorted(_ACTIVE_ROLES | _PASSIVE_ROLES)
)
_REPRESENTATIVE_ROLE_TOKENS = ("(ADVOGADO)", "(PROCURADOR)")


@dataclass(frozen=True, slots=True)
class _ScannedSupportedRow:
    explicit_pole: PjePartyPole | None
    role: str
    representative_role: str
    name_start: int
    name_end: int
    representative_start: int
    representative_end: int


def _skip_whitespace_forward(value: str, index: int, end: int) -> int:
    while index < end and value[index].isspace():
        index += 1
    return index


def _skip_whitespace_backward(value: str, start: int, index: int) -> int:
    while index > start and value[index - 1].isspace():
        index -= 1
    return index


def _scan_explicit_pole(
    value: str,
    start: int,
    end: int,
) -> tuple[PjePartyPole | None, int]:
    for token, pole in _EXPLICIT_POLES:
        token_end = start + len(token)
        if token_end > end or not value.startswith(token, start):
            continue
        delimiter = _skip_whitespace_forward(value, token_end, end)
        if delimiter < end and value[delimiter] in {":", "-"}:
            content_start = _skip_whitespace_forward(value, delimiter + 1, end)
            return pole, content_start
    return None, start


def _scan_terminal_representative_role(
    value: str,
    start: int,
    end: int,
) -> tuple[str, int] | None:
    for token in _REPRESENTATIVE_ROLE_TOKENS:
        token_start = end - len(token)
        if (
            token_start > start
            and value.startswith(token, token_start)
            and value[token_start - 1].isspace()
        ):
            return token[1:-1], token_start
    return None


def _scan_supported_row(normalized_line: str) -> _ScannedSupportedRow | None:
    """Reconhece uma linha suportada em uma passagem monotônica e limitada."""

    line_end = _skip_whitespace_backward(
        normalized_line,
        0,
        len(normalized_line),
    )
    content_start = _skip_whitespace_forward(normalized_line, 0, line_end)
    if content_start >= line_end:
        return None

    explicit_pole, content_start = _scan_explicit_pole(
        normalized_line,
        content_start,
        line_end,
    )
    if content_start >= line_end:
        return None

    representative_role = _scan_terminal_representative_role(
        normalized_line,
        content_start,
        line_end,
    )
    if representative_role is None:
        return None
    representative_role_name, representative_role_start = representative_role
    representative_end = _skip_whitespace_backward(
        normalized_line,
        content_start,
        representative_role_start,
    )

    candidate: _ScannedSupportedRow | None = None
    index = content_start
    while index < representative_end:
        if normalized_line[index] != "(":
            index += 1
            continue

        matched_token_length = 0
        for token, role in _PARTY_ROLE_TOKENS:
            token_end = index + len(token)
            if (
                index > content_start
                and token_end < representative_end
                and normalized_line[index - 1].isspace()
                and normalized_line[token_end].isspace()
                and normalized_line.startswith(token, index)
            ):
                name_end = _skip_whitespace_backward(
                    normalized_line,
                    content_start,
                    index,
                )
                representative_start = _skip_whitespace_forward(
                    normalized_line,
                    token_end,
                    representative_end,
                )
                if name_end > content_start and representative_start < representative_end:
                    if candidate is not None:
                        return None
                    candidate = _ScannedSupportedRow(
                        explicit_pole=explicit_pole,
                        role=role,
                        representative_role=representative_role_name,
                        name_start=content_start,
                        name_end=name_end,
                        representative_start=representative_start,
                        representative_end=representative_end,
                    )
                matched_token_length = len(token)
                break
        index += max(1, matched_token_length)

    return candidate


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

        scanned_row = _scan_supported_row(normalized)
        explicit_pole = (
            scanned_row.explicit_pole if scanned_row is not None else None
        )
        row_is_expected = state in {
            PjePartyTableState.HEADER_SEEN,
            PjePartyTableState.AFTER_ROW,
        }
        structurally_addressed = explicit_pole is not None

        if scanned_row is None or not (row_is_expected or structurally_addressed):
            if state is not PjePartyTableState.OUTSIDE_TABLE:
                state = PjePartyTableState.TERMINATED
            line_start += len(raw_line)
            continue

        role = scanned_row.role
        role_pole = _pole_for_role(role)
        if explicit_pole is not None and explicit_pole is not role_pole:
            state = PjePartyTableState.TERMINATED
            line_start += len(raw_line)
            continue

        state = PjePartyTableState.IN_TABLE
        normalized_start = scanned_row.name_start
        normalized_end = scanned_row.name_end
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
