"""Canonical, source-neutral judicial entities and procedural relations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} contains invalid Unicode") from exc


def _identifier(value: str, field: str) -> None:
    _text(value, field)
    if _ID.fullmatch(value) is None:
        raise ValueError(f"{field} is not canonical")


def _provenance(value: tuple[SourceProvenance, ...], field: str) -> None:
    if type(value) is not tuple or not value or any(type(item) is not SourceProvenance for item in value):
        raise ValueError(f"{field} requires provenance")


class EntityKind(StrEnum):
    NATURAL_PERSON = "NATURAL_PERSON"
    LEGAL_ENTITY = "LEGAL_ENTITY"
    PUBLIC_ENTITY = "PUBLIC_ENTITY"
    AUTHORITY = "AUTHORITY"
    UNKNOWN = "UNKNOWN"


class ProcessPole(StrEnum):
    ACTIVE = "ACTIVE"
    PASSIVE = "PASSIVE"
    THIRD = "THIRD"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class NormalizedProceduralRole(StrEnum):
    CLAIMANT = "CLAIMANT"
    DEFENDANT = "DEFENDANT"
    APPELLANT = "APPELLANT"
    RESPONDENT = "RESPONDENT"
    PROSECUTOR_PARTY = "PROSECUTOR_PARTY"
    COSTS_LEGIS = "COSTS_LEGIS"
    INTERESTED_THIRD_PARTY = "INTERESTED_THIRD_PARTY"
    ASSISTANT = "ASSISTANT"
    AMICUS_CURIAE = "AMICUS_CURIAE"
    VICTIM = "VICTIM"
    COURT_WITNESS = "COURT_WITNESS"
    AUTHORITY = "AUTHORITY"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ParticipantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    source_system: str
    source_document_id: str
    source_sha256: str
    page: int
    occurrence: str
    occurrence_id: str

    def __post_init__(self) -> None:
        _text(self.source_system, "source_system")
        _identifier(self.source_document_id, "source_document_id")
        if type(self.source_sha256) is not str or _SHA256.fullmatch(self.source_sha256) is None:
            raise ValueError("source_sha256 is invalid")
        if type(self.page) is not int or self.page < 1:
            raise ValueError("page is invalid")
        _text(self.occurrence, "occurrence")
        _identifier(self.occurrence_id, "occurrence_id")


@dataclass(frozen=True, slots=True)
class ProceduralRole:
    raw_label: str
    normalized: NormalizedProceduralRole

    def __post_init__(self) -> None:
        _text(self.raw_label, "raw_label")
        if type(self.normalized) is not NormalizedProceduralRole:
            raise TypeError("normalized role is invalid")


@dataclass(frozen=True, slots=True)
class JudicialEntity:
    entity_id: str
    raw_name: str
    kind: EntityKind
    provenance: tuple[SourceProvenance, ...]

    def __post_init__(self) -> None:
        _identifier(self.entity_id, "entity_id")
        _text(self.raw_name, "raw_name")
        if type(self.kind) is not EntityKind:
            raise TypeError("entity kind is invalid")
        _provenance(self.provenance, "JudicialEntity")


@dataclass(frozen=True, slots=True)
class ProcessParticipant:
    participant_id: str
    entity_id: str
    context_id: str
    pole: ProcessPole
    role: ProceduralRole
    principal: bool
    status: ParticipantStatus
    provenance: tuple[SourceProvenance, ...]

    def __post_init__(self) -> None:
        _identifier(self.participant_id, "participant_id")
        _identifier(self.entity_id, "entity_id")
        _identifier(self.context_id, "context_id")
        if type(self.pole) is not ProcessPole:
            raise TypeError("process pole is invalid")
        if type(self.role) is not ProceduralRole:
            raise TypeError("procedural role is invalid")
        if type(self.principal) is not bool:
            raise TypeError("principal must be boolean")
        if type(self.status) is not ParticipantStatus:
            raise TypeError("participant status is invalid")
        _provenance(self.provenance, "ProcessParticipant")


@dataclass(frozen=True, slots=True)
class RepresentationLink:
    link_id: str
    representative_entity_id: str
    represented_participant_ids: tuple[str, ...]
    representation_role_raw: str
    provenance: tuple[SourceProvenance, ...]

    def __post_init__(self) -> None:
        _identifier(self.link_id, "link_id")
        _identifier(self.representative_entity_id, "representative_entity_id")
        if (
            type(self.represented_participant_ids) is not tuple
            or not self.represented_participant_ids
            or len(set(self.represented_participant_ids)) != len(self.represented_participant_ids)
        ):
            raise ValueError("represented participants are invalid")
        for value in self.represented_participant_ids:
            _identifier(value, "represented_participant_id")
        _text(self.representation_role_raw, "representation_role_raw")
        _provenance(self.provenance, "RepresentationLink")


@dataclass(frozen=True, slots=True)
class AccessRelation:
    access_id: str
    entity_id: str
    context_id: str
    access_type_raw: str
    provenance: tuple[SourceProvenance, ...]

    def __post_init__(self) -> None:
        _identifier(self.access_id, "access_id")
        _identifier(self.entity_id, "entity_id")
        _identifier(self.context_id, "context_id")
        _text(self.access_type_raw, "access_type_raw")
        _provenance(self.provenance, "AccessRelation")


@dataclass(frozen=True, slots=True)
class ProceduralContext:
    context_id: str
    instance_label: str
    snapshot_id: str
    entities: tuple[JudicialEntity, ...]
    participants: tuple[ProcessParticipant, ...]
    representation_links: tuple[RepresentationLink, ...]
    access_relations: tuple[AccessRelation, ...]
    provenance: tuple[SourceProvenance, ...]

    def __post_init__(self) -> None:
        _identifier(self.context_id, "context_id")
        _text(self.instance_label, "instance_label")
        _identifier(self.snapshot_id, "snapshot_id")
        _provenance(self.provenance, "ProceduralContext")
        collections = (
            (self.entities, JudicialEntity, "entity_id"),
            (self.participants, ProcessParticipant, "participant_id"),
            (self.representation_links, RepresentationLink, "link_id"),
            (self.access_relations, AccessRelation, "access_id"),
        )
        identities: dict[str, set[str]] = {}
        for values, expected_type, identity_field in collections:
            if type(values) is not tuple or any(type(item) is not expected_type for item in values):
                raise TypeError(f"{identity_field} collection is invalid")
            ids = [getattr(item, identity_field) for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {identity_field}")
            identities[identity_field] = set(ids)
        entity_ids = identities["entity_id"]
        participant_ids = identities["participant_id"]
        for item in self.participants:
            if item.entity_id not in entity_ids or item.context_id != self.context_id:
                raise ValueError("participant relation is dangling or belongs to another context")
        for item in self.representation_links:
            if item.representative_entity_id not in entity_ids or not set(item.represented_participant_ids) <= participant_ids:
                raise ValueError("representation relation is dangling")
        for item in self.access_relations:
            if item.entity_id not in entity_ids or item.context_id != self.context_id:
                raise ValueError("access relation is dangling or belongs to another context")
        all_provenance = [*self.provenance]
        for collection in (self.entities, self.participants, self.representation_links, self.access_relations):
            for item in collection:
                all_provenance.extend(item.provenance)
        occurrence_identities: dict[tuple[str, str, str, str], tuple[int, str]] = {}
        for item in all_provenance:
            key = (item.source_system, item.source_document_id, item.source_sha256, item.occurrence_id)
            locator = (item.page, item.occurrence)
            if key in occurrence_identities and occurrence_identities[key] != locator:
                raise ValueError("occurrence_id resolves to conflicting source locators")
            occurrence_identities[key] = locator


def legacy_singular_party_view(context: ProceduralContext) -> dict[str, str] | None:
    """Return a lossy legacy view only when both singular parties are unambiguous."""
    if type(context) is not ProceduralContext:
        raise TypeError("context is invalid")
    if any(
        item.status is not ParticipantStatus.ACTIVE
        or item.pole is ProcessPole.UNKNOWN
        or item.role.normalized is NormalizedProceduralRole.UNKNOWN
        for item in context.participants
    ):
        return None
    entity_names = {item.entity_id: item.raw_name for item in context.entities}
    active = [
        item for item in context.participants
        if item.pole is ProcessPole.ACTIVE and item.role.normalized is NormalizedProceduralRole.CLAIMANT
        and item.principal and item.status is ParticipantStatus.ACTIVE
    ]
    passive = [
        item for item in context.participants
        if item.pole is ProcessPole.PASSIVE and item.role.normalized is NormalizedProceduralRole.DEFENDANT
        and item.principal and item.status is ParticipantStatus.ACTIVE
    ]
    selected = {*active, *passive}
    if (
        len(active) != 1 or len(passive) != 1
        or any(item.principal and item not in selected for item in context.participants)
    ):
        return None
    return {
        "parte_requerente": entity_names[active[0].entity_id],
        "parte_requerida": entity_names[passive[0].entity_id],
    }


def _exact_mapping(value: object, fields: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{label} shape is invalid")
    return value


def _provenance_from_mapping(value: object) -> SourceProvenance:
    row = _exact_mapping(
        value,
        {"source_system", "source_document_id", "source_sha256", "page", "occurrence", "occurrence_id"},
        "SourceProvenance",
    )
    return SourceProvenance(**row)


def _provenance_tuple(value: object) -> tuple[SourceProvenance, ...]:
    if type(value) is not list:
        raise ValueError("provenance list is invalid")
    return tuple(_provenance_from_mapping(item) for item in value)


def procedural_context_from_mapping(value: object) -> ProceduralContext:
    """Deserialize JSON data through the canonical semantic graph validator."""
    root = _exact_mapping(
        value,
        {
            "schema_version", "context_id", "instance_label", "snapshot_id", "entities",
            "participants", "representation_links", "access_relations", "provenance",
        },
        "ProceduralContext",
    )
    if root["schema_version"] != "1.0.0":
        raise ValueError("schema_version is unsupported")
    if not all(type(root[name]) is list for name in ("entities", "participants", "representation_links", "access_relations")):
        raise ValueError("procedural relation collection is invalid")
    entities = tuple(
        JudicialEntity(
            entity_id=row["entity_id"], raw_name=row["raw_name"], kind=EntityKind(row["kind"]),
            provenance=_provenance_tuple(row["provenance"]),
        )
        for raw in root["entities"]
        for row in [_exact_mapping(raw, {"entity_id", "raw_name", "kind", "provenance"}, "JudicialEntity")]
    )
    participants = []
    for raw in root["participants"]:
        row = _exact_mapping(
            raw,
            {"participant_id", "entity_id", "context_id", "pole", "role", "principal", "status", "provenance"},
            "ProcessParticipant",
        )
        role = _exact_mapping(row["role"], {"raw_label", "normalized"}, "ProceduralRole")
        participants.append(ProcessParticipant(
            participant_id=row["participant_id"], entity_id=row["entity_id"], context_id=row["context_id"],
            pole=ProcessPole(row["pole"]),
            role=ProceduralRole(role["raw_label"], NormalizedProceduralRole(role["normalized"])),
            principal=row["principal"], status=ParticipantStatus(row["status"]),
            provenance=_provenance_tuple(row["provenance"]),
        ))
    representations = tuple(
        RepresentationLink(
            link_id=row["link_id"], representative_entity_id=row["representative_entity_id"],
            represented_participant_ids=tuple(row["represented_participant_ids"]),
            representation_role_raw=row["representation_role_raw"],
            provenance=_provenance_tuple(row["provenance"]),
        )
        for raw in root["representation_links"]
        for row in [_exact_mapping(
            raw,
            {"link_id", "representative_entity_id", "represented_participant_ids", "representation_role_raw", "provenance"},
            "RepresentationLink",
        )]
    )
    accesses = tuple(
        AccessRelation(
            access_id=row["access_id"], entity_id=row["entity_id"], context_id=row["context_id"],
            access_type_raw=row["access_type_raw"], provenance=_provenance_tuple(row["provenance"]),
        )
        for raw in root["access_relations"]
        for row in [_exact_mapping(
            raw, {"access_id", "entity_id", "context_id", "access_type_raw", "provenance"}, "AccessRelation",
        )]
    )
    return ProceduralContext(
        context_id=root["context_id"], instance_label=root["instance_label"], snapshot_id=root["snapshot_id"],
        entities=entities, participants=tuple(participants), representation_links=representations,
        access_relations=accesses, provenance=_provenance_tuple(root["provenance"]),
    )
