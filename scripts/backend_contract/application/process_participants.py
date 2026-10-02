"""Participantes processuais: proposta da fonte, decisao do perito, historico (#268)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..judicial_domain import EntityKind, NormalizedProceduralRole
from ..process_participants import (
    PROCESS_PARTICIPANTS_ID,
    PROCESS_PARTICIPANTS_KIND,
    SCHEMA_VERSION,
    SOURCE_ROLE_NORMALIZATION,
    CaseParticipant,
    ParticipantOrigin,
    ParticipantPole,
    ParticipantRepresentative,
    ParticipantReviewState,
    ParticipantSource,
    ProcessParticipantsRegister,
    legacy_participants,
    manual_participant_id,
    participant_to_mapping,
    participants_register_from_mapping,
    participants_register_to_mapping,
    source_participant_id,
)
from .models import ProcessCaseData, thaw_payload
from .pje_party_table import parse_pje_participant_rows
from .ports import ArtifactRevisionNotFound, RepositoryConflict, RepositoryIntegrityError

__all__ = [
    "ParticipantProposals", "GetProcessParticipants", "DecideProcessParticipants", "ProcessParticipantsView",
    "participant_to_mapping",
]

_MAX_DECISION_NAME = 300


@dataclass(frozen=True, slots=True)
class ParticipantProposalSet:
    proposals: tuple[CaseParticipant, ...]
    # Documentos ainda em leitura (#266): a ausencia de proposta nao e ausencia
    # de participante.
    pending_documents: tuple[str, ...]
    # A leitura estruturada parou numa linha que nao reconhece; o restante da
    # tabela pode conter participantes que nao foram propostos.
    interrupted_pages: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ParticipantProposals:
    """Propostas a partir da tabela de partes de cada fonte, sem decidir nada."""
    texts: object

    def execute(self, workspace_id) -> ParticipantProposalSet:
        proposals: dict[str, CaseParticipant] = {}
        pending: list[str] = []
        interrupted: list[tuple[str, int]] = []
        for document in self.texts.execute(workspace_id):
            if document.reading_pending:
                pending.append(document.filename)
                continue
            for page in document.pages:
                mode = page.extraction_mode.value
                if mode not in ("NATIVE_TEXT", "OCR") or not page.text:
                    continue
                # Peca excluida pelo perito nao sustenta proposta nova.
                if document.excluded(page.number):
                    continue
                parsed = parse_pje_participant_rows(page.text)
                if parsed.terminated and parsed.rows:
                    interrupted.append((document.filename, page.number))
                logical = document.logical_document_for(page.number)
                logical_id = logical.document_id if logical is not None else None
                for row in parsed.rows:
                    pole = ParticipantPole(row.pole.value)
                    source = ParticipantSource(
                        document.content_id, document.checksum_sha256, document.filename, page.number,
                        row.source_start, row.source_end, row.source_line.strip(), mode, logical_id,
                    )
                    representatives = tuple(
                        ParticipantRepresentative(
                            item.name.strip(), item.role.capitalize(), None,
                            (ParticipantSource(
                                document.content_id, document.checksum_sha256, document.filename, page.number,
                                item.source_start, item.source_end, item.source_line.strip(), mode, logical_id,
                            ),),
                        )
                        for item in row.representatives
                    )
                    participant_id = source_participant_id(
                        workspace_id=str(workspace_id), content_id=document.content_id, logical_document_id=logical_id,
                        page=page.number, source_start=row.source_start, source_end=row.source_end, pole=pole, role_label=row.role,
                    )
                    proposals[participant_id] = CaseParticipant(
                        participant_id, row.name.strip(), pole,
                        SOURCE_ROLE_NORMALIZATION.get(row.role, NormalizedProceduralRole.UNKNOWN),
                        row.role, EntityKind.UNKNOWN, representatives, (source,),
                        ParticipantOrigin.SOURCE, ParticipantReviewState.PROPOSED, None,
                    )
        return ParticipantProposalSet(tuple(proposals.values()), tuple(pending), tuple(interrupted))


@dataclass(frozen=True, slots=True)
class ProcessParticipantsView:
    revision: int | None
    updated_at: str | None
    register: ProcessParticipantsRegister
    # Sem registro gravado, os campos escalares antigos aparecem como projecao.
    legacy_projection: bool
    proposals: tuple[CaseParticipant, ...]
    pending_documents: tuple[str, ...]
    interrupted_pages: tuple[tuple[str, int], ...]
    # Participante confirmado cuja peca de origem o perito excluiu depois.
    stale_participant_ids: tuple[str, ...]


def _stale_ids(register: ProcessParticipantsRegister, texts) -> tuple[str, ...]:
    by_content = {item.content_id: item for item in texts}
    stale = []
    for participant in register.participants:
        if participant.origin is not ParticipantOrigin.SOURCE or participant.review_state is not ParticipantReviewState.CONFIRMED:
            continue
        for source in participant.provenance:
            document = by_content.get(source.content_id)
            if document is None or document.checksum_sha256 != source.source_sha256 or document.excluded(source.page):
                stale.append(participant.participant_id)
                break
    return tuple(stale)


@dataclass(frozen=True, slots=True)
class GetProcessParticipants:
    get_latest_revision: object
    get_process_case: object
    texts: object | None
    proposals: object | None

    def stored(self, workspace_id):
        try:
            record = self.get_latest_revision.execute(workspace_id, PROCESS_PARTICIPANTS_KIND, PROCESS_PARTICIPANTS_ID)
        except ArtifactRevisionNotFound:
            return None, None
        register = participants_register_from_mapping(thaw_payload(record.payload))
        if register.workspace_id != str(workspace_id):
            raise RepositoryIntegrityError("participants register belongs to another workspace")
        return record, register

    def effective(self, workspace_id):
        """Registro gravado, ou a projecao legada dos campos escalares."""
        record, register = self.stored(workspace_id)
        if register is not None:
            return record, register, False
        snapshot = self.get_process_case.execute(workspace_id)
        data = snapshot.data if type(snapshot.data) is ProcessCaseData else ProcessCaseData.empty()
        decided_at = snapshot.updated_at or "1970-01-01T00:00:00+00:00"
        projected = legacy_participants(str(workspace_id), data.parte_requerente, data.parte_requerida, decided_at)
        return None, projected, bool(projected.participants)

    def execute(self, workspace_id) -> ProcessParticipantsView:
        record, register, legacy = self.effective(workspace_id)
        texts = self.texts.execute(workspace_id) if self.texts is not None else ()
        proposal_set = self.proposals.execute(workspace_id) if self.proposals is not None else ParticipantProposalSet((), (), ())
        decided = {item.participant_id for item in register.participants}
        open_proposals = tuple(item for item in proposal_set.proposals if item.participant_id not in decided)
        return ProcessParticipantsView(
            record.revision if record is not None else None,
            record.created_at if record is not None else None,
            register, legacy, open_proposals,
            proposal_set.pending_documents, proposal_set.interrupted_pages,
            _stale_ids(register, texts),
        )


def _required_text(value: object, limit: int = _MAX_DECISION_NAME) -> str:
    if type(value) is not str or not value.strip() or len(value.strip()) > limit or "\x00" in value:
        raise ValueError("participant text is invalid")
    return value.strip()


def _representatives_from_dto(value: object) -> tuple[ParticipantRepresentative, ...]:
    if type(value) is not list:
        raise ValueError("participant representatives are invalid")
    result = []
    for item in value:
        if type(item) is not dict or set(item) != {"name", "role_label", "registration"}:
            raise ValueError("participant representative is invalid")
        registration = item["registration"]
        if registration is not None:
            registration = _required_text(registration, 120)
        result.append(ParticipantRepresentative(_required_text(item["name"]), _required_text(item["role_label"], 120), registration, ()))
    return tuple(result)


def _classification_from_dto(value: object) -> dict:
    if type(value) is not dict or set(value) != {"name", "pole", "procedural_role", "source_role_label", "person_type", "representatives"}:
        raise ValueError("participant request is invalid")
    try:
        return {
            "name": _required_text(value["name"]),
            "pole": ParticipantPole(value["pole"]),
            "procedural_role": NormalizedProceduralRole(value["procedural_role"]),
            "source_role_label": _required_text(value["source_role_label"], 120),
            "person_type": EntityKind(value["person_type"]),
            "representatives": _representatives_from_dto(value["representatives"]),
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("participant request is invalid") from exc


def _merge_source_representatives(current: tuple[ParticipantRepresentative, ...], edited: tuple[ParticipantRepresentative, ...]) -> tuple[ParticipantRepresentative, ...]:
    """Mantem a proveniencia do procurador lido da fonte quando o perito o preserva."""
    by_identity = {(item.name, item.role_label): item for item in current}
    merged = []
    for item in edited:
        original = by_identity.get((item.name, item.role_label))
        merged.append(replace(item, provenance=original.provenance) if original is not None else item)
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class DecideProcessParticipants:
    get_participants: GetProcessParticipants
    revisions: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, action: str, expected_revision: int | None, payload: dict):
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("participants expected revision is invalid")
        if type(payload) is not dict:
            raise ValueError("participants request is invalid")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("participants authority guard is unavailable")
        with self.authority_guard():
            record, register, _legacy = self.get_participants.effective(workspace_id)
            if (record.revision if record is not None else None) != expected_revision:
                raise RepositoryConflict("expected participants revision is not latest")
            now = self.clock.now()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("participants clock requires timezone")
            decided_at = now.isoformat()
            participants = list(register.participants)
            index = {item.participant_id: position for position, item in enumerate(participants)}
            if action in ("CONFIRM", "REJECT"):
                if set(payload) != {"proposal_id"} or type(payload["proposal_id"]) is not str:
                    raise ValueError("participants request is invalid")
                if payload["proposal_id"] in index:
                    raise RepositoryConflict("participant proposal was already decided")
                current = self.get_participants.proposals.execute(workspace_id) if self.get_participants.proposals is not None else None
                proposal = next((item for item in (current.proposals if current is not None else ()) if item.participant_id == payload["proposal_id"]), None)
                if proposal is None:
                    raise ValueError("participant proposal is stale or belongs to another workspace")
                state = ParticipantReviewState.CONFIRMED if action == "CONFIRM" else ParticipantReviewState.REJECTED
                participants.append(replace(proposal, review_state=state, decided_at=decided_at))
            elif action == "ADD_MANUAL":
                if set(payload) != {"participant"}:
                    raise ValueError("participants request is invalid")
                values = _classification_from_dto(payload["participant"])
                participants.append(CaseParticipant(
                    manual_participant_id(self.ids.new_uuid()), values["name"], values["pole"], values["procedural_role"],
                    values["source_role_label"], values["person_type"], values["representatives"], (),
                    ParticipantOrigin.MANUAL, ParticipantReviewState.CONFIRMED, decided_at,
                ))
            elif action == "EDIT":
                if set(payload) != {"participant_id", "participant"} or payload["participant_id"] not in index:
                    raise ValueError("participants request is invalid")
                current = participants[index[payload["participant_id"]]]
                if current.review_state is not ParticipantReviewState.CONFIRMED:
                    raise ValueError("only a confirmed participant can be edited")
                values = _classification_from_dto(payload["participant"])
                if current.origin is ParticipantOrigin.LEGACY_PROCESS_CASE and values["pole"] is not current.pole:
                    raise ValueError("a legacy participant keeps its pole; add a new participant instead")
                representatives = _merge_source_representatives(current.representatives, values["representatives"])
                edited = current.origin is ParticipantOrigin.SOURCE and (current.edited or values["name"] != current.name)
                participants[index[current.participant_id]] = replace(
                    current, name=values["name"], pole=values["pole"], procedural_role=values["procedural_role"],
                    source_role_label=values["source_role_label"], person_type=values["person_type"],
                    representatives=representatives, decided_at=decided_at, edited=edited,
                )
            elif action in ("REMOVE", "RESTORE"):
                if set(payload) != {"participant_id"} or payload["participant_id"] not in index:
                    raise ValueError("participants request is invalid")
                current = participants[index[payload["participant_id"]]]
                expected_state = ParticipantReviewState.CONFIRMED if action == "REMOVE" else ParticipantReviewState.REJECTED
                if current.review_state is not expected_state:
                    raise RepositoryConflict("participant decision changed")
                target = ParticipantReviewState.REJECTED if action == "REMOVE" else ParticipantReviewState.CONFIRMED
                participants[index[current.participant_id]] = replace(current, review_state=target, decided_at=decided_at)
            elif action == "REORDER":
                if set(payload) != {"participant_ids"} or type(payload["participant_ids"]) is not list:
                    raise ValueError("participants request is invalid")
                order = payload["participant_ids"]
                if sorted(order) != sorted(index) or len(set(order)) != len(order):
                    raise ValueError("participants order must name every participant once")
                participants = [participants[index[item]] for item in order]
            else:
                raise ValueError("participants action is invalid")
            updated = ProcessParticipantsRegister(SCHEMA_VERSION, str(workspace_id), tuple(participants))
            saved = self.revisions.append_if_latest(
                workspace_id=workspace_id, artifact_kind=PROCESS_PARTICIPANTS_KIND, artifact_id=PROCESS_PARTICIPANTS_ID,
                revision_id=str(self.ids.new_uuid()), created_at=decided_at,
                payload=participants_register_to_mapping(updated), expected_revision=expected_revision,
            )
            return saved, updated
