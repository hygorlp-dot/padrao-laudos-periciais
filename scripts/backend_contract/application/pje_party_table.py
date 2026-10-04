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
    representative_name: str
    representative_role: str
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
# Cabeçalho da tabela de partes da capa PJe. O PJe escreve
# "Partes Procurador/Terceiro vinculado" (com barra); a forma com espaço e as
# flexões de número são as mesmas colunas (#285). Nada além disso abre a
# tabela: a gramática continua estrutural.
_HEADER = re.compile(
    r"^\s*PARTES\s+PROCURADOR(?:ES)?"
    r"(?:(?:\s*/\s*|\s+)TERCEIROS?\s+VINCULADOS?)?\s*$",
    re.IGNORECASE,
)
# Linha que tem a forma de um cabeçalho de partes ("PARTES ... PROCURADOR..."
# ou "PARTES ... VINCULADO", inclusive com palavra partida pelo OCR) mas não é
# o cabeçalho aceito: a tabela pode estar ali e não foi lida, o que é dito ao
# perito em vez de virar "nenhum participante" (#285). Só sinaliza; nunca lê.
_HEADER_LIKE = re.compile(
    r"^\s*PARTES\b.*(?:\bPROCURADOR|VINCULAD)", re.IGNORECASE
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
        representative_source_start = _source_bound(source_indices, scanned_row.representative_start, len(line))
        representative_source_end = _source_bound(source_indices, scanned_row.representative_end, len(line))
        rows.append(
            PjePartyTableRow(
                name=line[local_source_start:local_source_end],
                role=role,
                pole=role_pole,
                representative_name=line[representative_source_start:representative_source_end],
                representative_role=scanned_row.representative_role,
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


# --- Participantes (#268) -------------------------------------------------
#
# A gramatica acima alimenta os campos escalares legados (`parte_requerente`,
# `parte_requerida`) e as `party_rows` do inventario PJe; ela continua
# intocada. A gramatica abaixo e a mesma leitura estrutural da capa, estendida
# ao que o PJe realmente admite: varias partes por polo, outros participantes,
# parte sem procurador e varios procuradores por parte. Continua fail-closed:
# uma linha que nao se reconhece dentro da tabela encerra a leitura.


class PjeParticipantPole(StrEnum):
    ACTIVE = "ACTIVE"
    PASSIVE = "PASSIVE"
    OTHER = "OTHER"


_PARTICIPANT_ACTIVE_ROLES = frozenset({
    "AUTOR", "AUTORA", "REQUERENTE", "EXEQUENTE", "IMPETRANTE", "EMBARGANTE", "RECLAMANTE",
})
_PARTICIPANT_PASSIVE_ROLES = frozenset({
    "REQUERIDO", "REQUERIDA", "REU", "RE", "EXECUTADO", "EXECUTADA", "IMPETRADO", "IMPETRADA",
    "EMBARGADO", "EMBARGADA", "RECLAMADO", "RECLAMADA",
})
_PARTICIPANT_OTHER_ROLES = frozenset({
    "TERCEIRO INTERESSADO", "TERCEIRA INTERESSADA", "INTERESSADO", "INTERESSADA",
    "ASSISTENTE", "FISCAL DA LEI", "CUSTOS LEGIS", "FISCAL DA ORDEM JURIDICA",
    "AMICUS CURIAE", "VITIMA", "PERITO", "PERITA", "ASSISTENTE TECNICO", "ASSISTENTE TECNICA",
})
_PARTICIPANT_REPRESENTATIVE_ROLES = frozenset({
    "ADVOGADO", "ADVOGADA", "PROCURADOR", "PROCURADORA", "DEFENSOR PUBLICO", "DEFENSORA PUBLICA",
    "DEFENSORIA PUBLICA", "REPRESENTANTE", "CURADOR", "CURADORA",
})
_PARTICIPANT_SECTIONS = {
    "POLO ATIVO": PjeParticipantPole.ACTIVE,
    "POLO PASSIVO": PjeParticipantPole.PASSIVE,
    "OUTROS PARTICIPANTES": PjeParticipantPole.OTHER,
    "OUTROS INTERESSADOS": PjeParticipantPole.OTHER,
    "TERCEIROS INTERESSADOS": PjeParticipantPole.OTHER,
}
_PARTICIPANT_PARTY_ROLES = _PARTICIPANT_ACTIVE_ROLES | _PARTICIPANT_PASSIVE_ROLES | _PARTICIPANT_OTHER_ROLES
_PARENTHESIZED_TOKEN = re.compile(r"\(([A-Z][A-Z ]{0,38}[A-Z])\)")
_SECTION_LINE = re.compile(r"^\s*(POLO ATIVO|POLO PASSIVO|OUTROS PARTICIPANTES|OUTROS INTERESSADOS|TERCEIROS INTERESSADOS)\s*:?\s*$")
_INLINE_POLE = re.compile(r"^\s*(POLO ATIVO|POLO PASSIVO|OUTROS PARTICIPANTES|OUTROS INTERESSADOS|TERCEIROS INTERESSADOS)\s*[:\-]\s*")


def participant_pole_for_role(role: str) -> PjeParticipantPole:
    if role in _PARTICIPANT_ACTIVE_ROLES:
        return PjeParticipantPole.ACTIVE
    if role in _PARTICIPANT_PASSIVE_ROLES:
        return PjeParticipantPole.PASSIVE
    if role in _PARTICIPANT_OTHER_ROLES:
        return PjeParticipantPole.OTHER
    raise ValueError("papel processual não suportado pela tabela PJe")


@dataclass(frozen=True, slots=True)
class PjeRepresentativeRow:
    name: str
    role: str
    source_line: str
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class PjeParticipantRow:
    name: str
    role: str
    pole: PjeParticipantPole
    representatives: tuple[PjeRepresentativeRow, ...]
    source_line: str
    source_start: int
    source_end: int


@dataclass(frozen=True, slots=True)
class PjeParticipantParseResult:
    rows: tuple[PjeParticipantRow, ...]
    terminated: bool
    # A tabela foi aberta por cabecalho ou secao nesta pagina.
    opened: bool = False
    # A pagina termina dentro da tabela, sem linha que a encerre: a proxima
    # pagina pode continuar a lista sem repetir o cabecalho.
    open_at_end: bool = False
    # Linha com papel de parte antes de qualquer cabecalho: continuacao de uma
    # tabela da pagina anterior que esta leitura nao associa a nenhum polo.
    leading_party_like: bool = False
    # A leitura parou numa linha com papel que nao reconhece, num conflito de
    # polo ou numa tabela PJe vazia; o fim natural da tabela nao conta.
    interrupted: bool = False
    # A pagina tem um cabecalho de partes que a gramatica nao aceita (#285):
    # a tabela nao foi lida, o que nao e o mesmo que nao haver partes.
    unrecognized_header: bool = False


def _trimmed_span(normalized: str, start: int, end: int) -> tuple[int, int]:
    start = _skip_whitespace_forward(normalized, start, end)
    end = _skip_whitespace_backward(normalized, start, end)
    return start, end


def _known_role(token: str) -> bool:
    return token in _PARTICIPANT_PARTY_ROLES or token in _PARTICIPANT_REPRESENTATIVE_ROLES


def parse_pje_participant_rows(page_text: str) -> PjeParticipantParseResult:
    """Linhas de participantes da capa PJe, com polo, papel e procuradores.

    Uma passagem por linha e uma busca linear de tokens entre parenteses por
    linha. Nunca infere polo pelo nome: o polo vem do papel declarado e tem de
    concordar com a secao ou o prefixo explicito, quando existirem.
    """
    if type(page_text) is not str:
        raise TypeError("texto da página PJe inválido")
    rows: list[PjeParticipantRow] = []
    inside = False
    terminated = False
    opened = False
    leading_party_like = False
    # Interrupcao (aviso) e diferente de fim de tabela: a tabela termina
    # naturalmente numa linha sem papel entre parenteses ("Documentos").
    # Interrompe quando a linha recusada tem papel, quando o polo conflita ou
    # quando o cabecalho PJe abriu a tabela e nenhuma linha foi lida.
    interrupted = False
    header_rows: int | None = None
    unrecognized_header = False
    section: PjeParticipantPole | None = None
    # Indice da parte que pode receber procurador em linha de continuacao; zera
    # a cada cabecalho ou secao, para nunca ligar o advogado de um polo a parte
    # de outro.
    continuation_target: int | None = None
    line_start = 0
    for raw_line in page_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        offset = line_start
        line_start += len(raw_line)
        normalized, source_indices = _ascii_upper_with_source_indices(line)
        if _HEADER.fullmatch(normalized):
            inside, terminated, section, opened, continuation_target = True, False, None, True, None
            header_rows = 0
            continue
        if _HEADER_LIKE.match(normalized):
            unrecognized_header = True
        section_match = _SECTION_LINE.fullmatch(normalized)
        if section_match:
            inside, terminated, section, opened, continuation_target = True, False, _PARTICIPANT_SECTIONS[section_match.group(1)], True, None
            continue
        if not inside:
            if not opened and any(match.group(1) in _PARTICIPANT_PARTY_ROLES or match.group(1) in _PARTICIPANT_REPRESENTATIVE_ROLES for match in _PARENTHESIZED_TOKEN.finditer(normalized)):
                leading_party_like = True
            continue
        if terminated:
            # Depois de um fim "natural", outra linha com papel na mesma pagina
            # (nome quebrado em duas linhas, razao social longa, OCR) prova que
            # a tabela continuava: a leitura foi interrompida, nao concluida.
            if not interrupted and any(_known_role(match.group(1)) for match in _PARENTHESIZED_TOKEN.finditer(normalized)):
                interrupted = True
            continue
        if not normalized.strip():
            continue
        explicit: PjeParticipantPole | None = None
        content_start = 0
        inline = _INLINE_POLE.match(normalized)
        if inline:
            explicit = _PARTICIPANT_SECTIONS[inline.group(1)]
            content_start = inline.end()
        tokens = [match for match in _PARENTHESIZED_TOKEN.finditer(normalized, content_start)]
        party_tokens = [match for match in tokens if match.group(1) in _PARTICIPANT_PARTY_ROLES]
        representative_tokens = [match for match in tokens if match.group(1) in _PARTICIPANT_REPRESENTATIVE_ROLES]
        unknown_tokens = len(tokens) - len(party_tokens) - len(representative_tokens)
        line_end = _skip_whitespace_backward(normalized, 0, len(normalized))
        # Linha que encerra a tabela: so e interrupcao se tinha papel ou se o
        # cabecalho PJe abriu uma tabela vazia.
        refused = bool(tokens) or header_rows == 0

        def source(start: int, end: int) -> tuple[int, int]:
            return (
                offset + _source_bound(source_indices, start, len(line)),
                offset + _source_bound(source_indices, end, len(line)),
            )

        if not party_tokens and len(representative_tokens) == 1 and unknown_tokens == 0 and explicit is None:
            # Continuacao: mais um procurador da parte da linha anterior.
            token = representative_tokens[0]
            name_start, name_end = _trimmed_span(normalized, content_start, token.start())
            if continuation_target is not None and token.end() == line_end and name_end > name_start:
                start, end = source(name_start, name_end)
                previous = rows[continuation_target]
                rows[continuation_target] = PjeParticipantRow(
                    previous.name, previous.role, previous.pole,
                    (*previous.representatives, PjeRepresentativeRow(page_text[start:end], token.group(1), line, start, end)),
                    previous.source_line, previous.source_start, previous.source_end,
                )
                continue
            terminated, interrupted = True, interrupted or refused
            continue
        if len(party_tokens) != 1 or unknown_tokens or len(representative_tokens) > 1:
            terminated, interrupted = True, interrupted or refused
            continue
        party = party_tokens[0]
        role = party.group(1)
        pole = participant_pole_for_role(role)
        expected = explicit or section
        if expected is not None and expected is not pole:
            terminated, interrupted = True, True
            continue
        name_start, name_end = _trimmed_span(normalized, content_start, party.start())
        if name_end <= name_start:
            terminated, interrupted = True, interrupted or refused
            continue
        representatives: tuple[PjeRepresentativeRow, ...] = ()
        if representative_tokens:
            token = representative_tokens[0]
            rep_start, rep_end = _trimmed_span(normalized, party.end(), token.start())
            if token.start() < party.end() or token.end() != line_end or rep_end <= rep_start:
                terminated, interrupted = True, interrupted or refused
                continue
            start, end = source(rep_start, rep_end)
            representatives = (PjeRepresentativeRow(page_text[start:end], token.group(1), line, start, end),)
        elif party.end() != line_end:
            terminated, interrupted = True, interrupted or refused
            continue
        start, end = source(name_start, name_end)
        rows.append(PjeParticipantRow(page_text[start:end], role, pole, representatives, line, start, end))
        continuation_target = len(rows) - 1
        if header_rows is not None:
            header_rows += 1
    return PjeParticipantParseResult(tuple(rows), terminated, opened, inside and not terminated, leading_party_like, interrupted, unrecognized_header)
