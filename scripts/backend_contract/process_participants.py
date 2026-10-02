"""Participantes processuais como colecao estruturada (#268).

O processo tem uma ou mais partes em cada polo, outros participantes e
representantes vinculados a cada parte. Esta e a autoridade canonica da
perícia para essa colecao; os campos escalares `parte_requerente` e
`parte_requerida` de `ProcessCaseData` ficam somente como dado legado.

Vocabulario reaproveitado de `judicial_domain` (papel normalizado e tipo de
pessoa); nada aqui decide materia juridica. Uma proposta extraida da fonte
nunca vira participante confirmado sem decisao do perito.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
import json
import re
from uuid import UUID

from .judicial_domain import EntityKind, NormalizedProceduralRole


PROCESS_PARTICIPANTS_KIND = "PROCESS_PARTICIPANTS_V1"
PROCESS_PARTICIPANTS_ID = "PROCESS-PARTICIPANTS"
SCHEMA_VERSION = "1.0.0"
MAX_PARTICIPANTS = 512
MAX_REPRESENTATIVES = 64
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PARTICIPANT_ID = re.compile(r"PARTICIPANT-(?:SRC-[0-9A-F]{24}|MAN-[0-9A-F]{32}|LEGACY-(?:ACTIVE|PASSIVE))")
_NAME_LIMIT = 300
# O campo legado nao tinha limite e costuma reunir varias partes num texto so;
# a projecao preserva o texto exato ate este tamanho e nunca o corta.
LEGACY_NAME_LIMIT = 4000
_LABEL_LIMIT = 120
_EXCERPT_LIMIT = 2000


class ParticipantPole(StrEnum):
    ACTIVE = "ACTIVE"
    PASSIVE = "PASSIVE"
    OTHER = "OTHER"


class ParticipantOrigin(StrEnum):
    SOURCE = "SOURCE"
    MANUAL = "MANUAL"
    LEGACY_PROCESS_CASE = "LEGACY_PROCESS_CASE"


class ParticipantReviewState(StrEnum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


# Papel normalizado padrao para o papel literal da capa PJe; o perito pode
# corrigir. Papel desconhecido continua UNKNOWN, nunca e adivinhado.
SOURCE_ROLE_NORMALIZATION = {
    **{role: NormalizedProceduralRole.CLAIMANT for role in ("AUTOR", "AUTORA", "REQUERENTE", "EXEQUENTE", "IMPETRANTE", "EMBARGANTE", "RECLAMANTE")},
    **{role: NormalizedProceduralRole.DEFENDANT for role in ("REQUERIDO", "REQUERIDA", "REU", "RE", "EXECUTADO", "EXECUTADA", "IMPETRADO", "IMPETRADA", "EMBARGADO", "EMBARGADA", "RECLAMADO", "RECLAMADA")},
    **{role: NormalizedProceduralRole.INTERESTED_THIRD_PARTY for role in ("TERCEIRO INTERESSADO", "TERCEIRA INTERESSADA", "INTERESSADO", "INTERESSADA")},
    "ASSISTENTE": NormalizedProceduralRole.ASSISTANT,
    "FISCAL DA LEI": NormalizedProceduralRole.COSTS_LEGIS,
    "CUSTOS LEGIS": NormalizedProceduralRole.COSTS_LEGIS,
    "FISCAL DA ORDEM JURIDICA": NormalizedProceduralRole.COSTS_LEGIS,
    "AMICUS CURIAE": NormalizedProceduralRole.AMICUS_CURIAE,
    "VITIMA": NormalizedProceduralRole.VICTIM,
}

POLE_LABELS = {
    ParticipantPole.ACTIVE: "Polo ativo",
    ParticipantPole.PASSIVE: "Polo passivo",
    ParticipantPole.OTHER: "Outros participantes",
}


# Mesmo conjunto que o Word nao representa (delivery_renderer), mais quebras de
# linha: nome, papel e registro sao uma linha so no item 1.1.
_FORBIDDEN_INLINE = re.compile("[\x00-\x1f\x7f\x85\u2028\u2029\ud800-\udfff\ufffe\uffff]")
_FORBIDDEN_EXCERPT = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _text(value: object, limit: int, *, excerpt: bool = False) -> bool:
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > limit:
        return False
    return (_FORBIDDEN_EXCERPT if excerpt else _FORBIDDEN_INLINE).search(value) is None


def representable_text(value: object, limit: int = _NAME_LIMIT) -> bool:
    """Texto que cabe numa linha do laudo, sem caractere que o Word recusa."""
    return _text(value, limit)


def _timestamp(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


@dataclass(frozen=True, slots=True)
class ParticipantSource:
    """Onde o nome aparece: arquivo, pagina, trecho e modo de leitura.

    `logical_document_id` nomeia a peca do inventario PJe que contem a pagina,
    quando o arquivo e um export PJe; e isso que permite a exclusao de uma peca
    alcancar o participante que ela sustentava.
    """
    content_id: str
    source_sha256: str
    filename: str
    page: int
    source_start: int
    source_end: int
    excerpt: str
    extraction_mode: str
    logical_document_id: str | None

    def __post_init__(self):
        try:
            UUID(self.content_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("participant source content is invalid") from exc
        if type(self.source_sha256) is not str or _SHA256.fullmatch(self.source_sha256) is None:
            raise ValueError("participant source checksum is invalid")
        if not _text(self.filename, 500) or not _text(self.excerpt, _EXCERPT_LIMIT, excerpt=True):
            raise ValueError("participant source text is invalid")
        if any(type(value) is not int for value in (self.page, self.source_start, self.source_end)) or self.page < 1 or self.source_start < 0 or self.source_end <= self.source_start:
            raise ValueError("participant source locator is invalid")
        if self.extraction_mode not in ("NATIVE_TEXT", "OCR"):
            raise ValueError("participant source extraction mode is invalid")
        if self.logical_document_id is not None and not _text(self.logical_document_id, 200):
            raise ValueError("participant logical document is invalid")


@dataclass(frozen=True, slots=True)
class ParticipantRepresentative:
    name: str
    role_label: str
    registration: str | None
    provenance: tuple[ParticipantSource, ...]

    def __post_init__(self):
        if not _text(self.name, _NAME_LIMIT) or not _text(self.role_label, _LABEL_LIMIT):
            raise ValueError("participant representative is invalid")
        if self.registration is not None and not _text(self.registration, _LABEL_LIMIT):
            raise ValueError("participant representative registration is invalid")
        if type(self.provenance) is not tuple or any(type(item) is not ParticipantSource for item in self.provenance):
            raise ValueError("participant representative provenance is invalid")


@dataclass(frozen=True, slots=True)
class CaseParticipant:
    participant_id: str
    name: str
    pole: ParticipantPole
    procedural_role: NormalizedProceduralRole
    source_role_label: str
    person_type: EntityKind
    representatives: tuple[ParticipantRepresentative, ...]
    provenance: tuple[ParticipantSource, ...]
    origin: ParticipantOrigin
    review_state: ParticipantReviewState
    decided_at: str | None
    # Nome corrigido pelo perito sobre o literal da fonte; a fonte continua
    # citada e o literal fica no trecho da proveniencia.
    edited: bool = False

    def __post_init__(self):
        if type(self.participant_id) is not str or _PARTICIPANT_ID.fullmatch(self.participant_id) is None:
            raise ValueError("participant identity is invalid")
        name_limit = LEGACY_NAME_LIMIT if self.origin is ParticipantOrigin.LEGACY_PROCESS_CASE else _NAME_LIMIT
        if not _text(self.name, name_limit) or not _text(self.source_role_label, _LABEL_LIMIT):
            raise ValueError("participant text is invalid")
        for value, kind in ((self.pole, ParticipantPole), (self.procedural_role, NormalizedProceduralRole), (self.person_type, EntityKind), (self.origin, ParticipantOrigin), (self.review_state, ParticipantReviewState)):
            if type(value) is not kind:
                raise ValueError("participant classification is invalid")
        if type(self.representatives) is not tuple or len(self.representatives) > MAX_REPRESENTATIVES or any(type(item) is not ParticipantRepresentative for item in self.representatives):
            raise ValueError("participant representatives are invalid")
        if type(self.provenance) is not tuple or any(type(item) is not ParticipantSource for item in self.provenance):
            raise ValueError("participant provenance is invalid")
        if type(self.edited) is not bool:
            raise ValueError("participant edit flag is invalid")
        expected_prefix = {
            ParticipantOrigin.SOURCE: "PARTICIPANT-SRC-",
            ParticipantOrigin.MANUAL: "PARTICIPANT-MAN-",
            ParticipantOrigin.LEGACY_PROCESS_CASE: "PARTICIPANT-LEGACY-",
        }[self.origin]
        if not self.participant_id.startswith(expected_prefix):
            raise ValueError("participant identity does not match its origin")
        if self.origin is ParticipantOrigin.SOURCE and not self.provenance:
            raise ValueError("source participant requires provenance")
        if self.origin is not ParticipantOrigin.SOURCE and (self.provenance or self.edited):
            raise ValueError("only a source participant carries source provenance")
        if self.origin is ParticipantOrigin.LEGACY_PROCESS_CASE and self.pole is ParticipantPole.OTHER:
            raise ValueError("legacy participant has an active or passive pole")
        if self.review_state is ParticipantReviewState.PROPOSED:
            if self.origin is not ParticipantOrigin.SOURCE or self.decided_at is not None or self.edited:
                raise ValueError("only an undecided source proposal is PROPOSED")
        elif not _timestamp(self.decided_at):
            raise ValueError("participant decision requires a timestamp")


@dataclass(frozen=True, slots=True)
class ProcessParticipantsRegister:
    """Decisoes do perito sobre os participantes; propostas nao entram aqui."""
    schema_version: str
    workspace_id: str
    participants: tuple[CaseParticipant, ...]

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION or not _text(self.workspace_id, 64):
            raise ValueError("participants register identity is invalid")
        if type(self.participants) is not tuple or len(self.participants) > MAX_PARTICIPANTS or any(type(item) is not CaseParticipant for item in self.participants):
            raise ValueError("participants register collection is invalid")
        if len({item.participant_id for item in self.participants}) != len(self.participants):
            raise ValueError("participant identities must be unique")
        if any(item.review_state is ParticipantReviewState.PROPOSED for item in self.participants):
            raise ValueError("a proposal is not a professional decision")

    @property
    def confirmed(self) -> tuple[CaseParticipant, ...]:
        return tuple(item for item in self.participants if item.review_state is ParticipantReviewState.CONFIRMED)

    def get(self, participant_id: str) -> CaseParticipant | None:
        return next((item for item in self.participants if item.participant_id == participant_id), None)


def source_participant_id(*, workspace_id: str, content_id: str, logical_document_id: str | None, page: int, source_start: int, source_end: int, pole: ParticipantPole, role_label: str) -> str:
    """Identidade estavel da ocorrencia na fonte; nunca deriva do nome."""
    identity = json.dumps(
        [str(workspace_id), str(content_id), logical_document_id, page, source_start, source_end, pole.value, role_label],
        ensure_ascii=False, separators=(",", ":"),
    )
    return "PARTICIPANT-SRC-" + sha256(identity.encode("utf-8")).hexdigest()[:24].upper()


def manual_participant_id(value: UUID) -> str:
    if type(value) is not UUID:
        raise TypeError("manual participant identity requires a UUID")
    return "PARTICIPANT-MAN-" + value.hex.upper()


def legacy_projection(workspace_id: str, parte_requerente: str, parte_requerida: str, decided_at: str) -> tuple[ProcessParticipantsRegister, tuple[ParticipantPole, ...]]:
    """Projecao explicita dos campos escalares legados, sem dividir nem cortar strings.

    Um valor que nao cabe num participante (texto acima de `LEGACY_NAME_LIMIT`
    ou com caractere que o Word nao representa) nao e projetado; o polo volta
    em `blocked` para a tela pedir ao perito que registre as partes uma a uma.
    """
    participants = []
    blocked = []
    for value, pole, role, label, suffix in (
        (parte_requerente, ParticipantPole.ACTIVE, NormalizedProceduralRole.CLAIMANT, "Parte requerente", "ACTIVE"),
        (parte_requerida, ParticipantPole.PASSIVE, NormalizedProceduralRole.DEFENDANT, "Parte requerida", "PASSIVE"),
    ):
        name = value.strip() if type(value) is str else ""
        if not name:
            continue
        if not _text(name, LEGACY_NAME_LIMIT):
            blocked.append(pole)
            continue
        participants.append(CaseParticipant(
            f"PARTICIPANT-LEGACY-{suffix}", name, pole, role, label, EntityKind.UNKNOWN,
            (), (), ParticipantOrigin.LEGACY_PROCESS_CASE, ParticipantReviewState.CONFIRMED, decided_at,
        ))
    return ProcessParticipantsRegister(SCHEMA_VERSION, str(workspace_id), tuple(participants)), tuple(blocked)


def legacy_participants(workspace_id: str, parte_requerente: str, parte_requerida: str, decided_at: str) -> ProcessParticipantsRegister:
    return legacy_projection(workspace_id, parte_requerente, parte_requerida, decided_at)[0]


def _source_from_mapping(value: object) -> ParticipantSource:
    if type(value) is not dict or set(value) != {item.name for item in fields(ParticipantSource)}:
        raise ValueError("participant source mapping is invalid")
    return ParticipantSource(**value)


def _representative_from_mapping(value: object) -> ParticipantRepresentative:
    if type(value) is not dict or set(value) != {item.name for item in fields(ParticipantRepresentative)} or type(value["provenance"]) is not list:
        raise ValueError("participant representative mapping is invalid")
    return ParticipantRepresentative(value["name"], value["role_label"], value["registration"], tuple(_source_from_mapping(item) for item in value["provenance"]))


def participant_from_mapping(value: object) -> CaseParticipant:
    names = {item.name for item in fields(CaseParticipant)}
    if type(value) is not dict or set(value) != names or type(value["representatives"]) is not list or type(value["provenance"]) is not list:
        raise ValueError("participant mapping is invalid")
    try:
        return CaseParticipant(
            participant_id=value["participant_id"], name=value["name"], pole=ParticipantPole(value["pole"]),
            procedural_role=NormalizedProceduralRole(value["procedural_role"]), source_role_label=value["source_role_label"],
            person_type=EntityKind(value["person_type"]),
            representatives=tuple(_representative_from_mapping(item) for item in value["representatives"]),
            provenance=tuple(_source_from_mapping(item) for item in value["provenance"]),
            origin=ParticipantOrigin(value["origin"]), review_state=ParticipantReviewState(value["review_state"]),
            decided_at=value["decided_at"], edited=value["edited"],
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("participant mapping is invalid") from exc


def participant_to_mapping(value: CaseParticipant) -> dict:
    if type(value) is not CaseParticipant:
        raise TypeError("expected CaseParticipant")
    return json.loads(json.dumps(asdict(value), ensure_ascii=False))


def participants_register_from_mapping(value: object) -> ProcessParticipantsRegister:
    if type(value) is not dict or set(value) != {"schema_version", "workspace_id", "participants"} or type(value["participants"]) is not list:
        raise ValueError("participants register mapping is invalid")
    return ProcessParticipantsRegister(value["schema_version"], value["workspace_id"], tuple(participant_from_mapping(item) for item in value["participants"]))


def participants_register_to_mapping(value: ProcessParticipantsRegister) -> dict:
    if type(value) is not ProcessParticipantsRegister:
        raise TypeError("expected ProcessParticipantsRegister")
    return {"schema_version": value.schema_version, "workspace_id": value.workspace_id, "participants": [participant_to_mapping(item) for item in value.participants]}


def participants_summary(participants: tuple[CaseParticipant, ...], pole: ParticipantPole, *, limit: int = 3) -> str:
    """Resumo de um polo para a capa: nunca omite sem dizer quantos faltam."""
    names = [item.name for item in participants if item.pole is pole and item.review_state is ParticipantReviewState.CONFIRMED]
    if not names:
        return ""
    if len(names) <= limit:
        return "; ".join(names)
    shown = "; ".join(names[:limit])
    return f"{shown} e outros {len(names) - limit} (relação completa no item 1)"


def with_decision(value: CaseParticipant, state: ParticipantReviewState, decided_at: str) -> CaseParticipant:
    return replace(value, review_state=state, decided_at=decided_at)


ROLE_DISPLAY = {
    NormalizedProceduralRole.CLAIMANT: "parte autora",
    NormalizedProceduralRole.DEFENDANT: "parte ré",
    NormalizedProceduralRole.INTERESTED_THIRD_PARTY: "terceiro interessado",
    NormalizedProceduralRole.ASSISTANT: "assistente",
    NormalizedProceduralRole.COSTS_LEGIS: "fiscal da ordem jurídica",
    NormalizedProceduralRole.AMICUS_CURIAE: "amicus curiae",
    NormalizedProceduralRole.VICTIM: "vítima",
}


# A gramatica da capa PJe le em ASCII maiusculo; o laudo escreve com acento.
SOURCE_ROLE_DISPLAY = {
    "REU": "réu", "RE": "ré", "DEFENSOR PUBLICO": "defensor público", "DEFENSORA PUBLICA": "defensora pública",
    "DEFENSORIA PUBLICA": "Defensoria Pública", "ASSISTENTE TECNICO": "assistente técnico",
    "ASSISTENTE TECNICA": "assistente técnica", "VITIMA": "vítima", "FISCAL DA ORDEM JURIDICA": "fiscal da ordem jurídica",
}


def source_role_display(label: str) -> str:
    """Papel literal da fonte como o laudo o escreve, com acentuacao."""
    return SOURCE_ROLE_DISPLAY.get(label, label.lower())


def participant_role_text(value: CaseParticipant) -> str:
    """Papel como o laudo o escreve: o rotulo do perito, ou o papel normalizado da fonte."""
    if value.origin is ParticipantOrigin.SOURCE:
        return ROLE_DISPLAY.get(value.procedural_role, source_role_display(value.source_role_label))
    return value.source_role_label


def participant_line(value: CaseParticipant) -> str:
    """Uma linha do item 1.1: nome, papel e representantes vinculados."""
    line = f"{value.name} ({participant_role_text(value)})"
    if value.representatives:
        names = "; ".join(f"{item.name} ({item.role_label.lower()})" for item in value.representatives)
        line += f" — representação: {names}"
    return line
