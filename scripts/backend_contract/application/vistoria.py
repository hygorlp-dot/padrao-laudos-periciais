"""Application authority for workspace-owned Inspection Session revisions."""

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from ..pericial_planning import (
    PERICIAL_PLANNING_ARTIFACT_ID,
    PERICIAL_PLANNING_ARTIFACT_KIND,
    ProfessionalReviewStatus,
    pericial_planning_to_mapping,
)
from ..vistoria import (
    INSPECTION_SESSION_ARTIFACT_ID,
    INSPECTION_SESSION_ARTIFACT_KIND,
    AccessOutcome,
    ExecutionState,
    InspectionCoverage,
    InspectionItem,
    InspectionPlanSnapshot,
    InspectionReuseDecision,
    InspectionSession,
    LocationReference,
    ObservationType,
    REUSABLE_RECORD_COLLECTIONS,
    ReusedRecordKind,
    inspection_session_from_mapping,
    inspection_session_to_mapping,
)
from .models import PrivateContentId, thaw_payload
from .pericial_planning import validated_pericial_planning_from_mapping
from .ports import RepositoryConflict, RepositoryIntegrityError
from ..visit_context import VisitContext


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "inspection-session-v1.schema.json"
_VALIDATOR = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")), format_checker=FormatChecker())


def validated_inspection_session_from_mapping(value: object) -> InspectionSession:
    try:
        _VALIDATOR.validate(value)
        return inspection_session_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Inspection Session payload") from exc


def inspection_session_to_validated_mapping(value: object) -> dict[str, object]:
    if type(value) is not InspectionSession:
        raise RepositoryIntegrityError("Inspection Session persisted state is invalid")
    return inspection_session_to_mapping(value)


def inspection_planning_digest(snapshot) -> str:
    encoded = json.dumps(
        pericial_planning_to_mapping(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _executable_planning_item_ids(snapshot) -> tuple[str, ...]:
    executable_types = {
        "InspectionRequirement", "MeasurementRequirement", "PhotoRequirement", "AccessRequirement",
    }
    return tuple(
        item.item_id for item in snapshot.material_items
        if type(item).__name__ in executable_types
        and item.professional_review_status in {
            ProfessionalReviewStatus.APPROVED, ProfessionalReviewStatus.MODIFIED
        }
    )


def _reconcile(session: InspectionSession, *, planning_record, planning) -> InspectionSession:
    reasons = []
    binding = session.plan_snapshot
    if binding.planning_snapshot_id != planning.snapshot_id:
        reasons.append("planning snapshot identity changed")
    if binding.planning_revision != planning_record.revision:
        reasons.append("planning artifact revision changed")
    if binding.planning_digest != inspection_planning_digest(planning):
        reasons.append("planning content digest changed")
    if binding.source_revision != planning.plan.case_analysis_source_revision:
        reasons.append("planning source revision changed")
    if planning.upstream_stale:
        reasons.append("planning is stale against Case Analysis")
    if tuple(binding.approved_item_ids) != _executable_planning_item_ids(planning):
        reasons.append("approved executable planning items changed")
    return replace(session, upstream_stale=bool(reasons), upstream_stale_reasons=tuple(reasons))


def _validate_execution_against_planning(session: InspectionSession, planning) -> None:
    planning_by_id = {item.item_id: item for item in planning.material_items}
    for item in session.items:
        planned = planning_by_id[item.planning_item_id]
        if item.state is not ExecutionState.PENDING and not (item.note and item.note.strip()):
            raise ValueError("executed inspection item requires an explicit professional note")
        if item.state in {ExecutionState.PARTIAL, ExecutionState.NOT_EXECUTED, ExecutionState.BLOCKED} and not item.limitation_ids:
            raise ValueError("incomplete inspection item requires an explicit limitation")
        if item.state is not ExecutionState.COMPLETED:
            continue
        name = type(planned).__name__
        if name == "InspectionRequirement" and not any(
            record.inspection_item_id == item.item_id and record.observation_type is ObservationType.DIRECT_OBSERVATION
            for record in session.observations
        ):
            raise ValueError("completed inspection requirement requires field observation")
        if name == "MeasurementRequirement" and not item.measurement_ids:
            raise ValueError("completed measurement requirement requires measurement")
        if name == "PhotoRequirement" and not item.photo_ids:
            raise ValueError("completed photo requirement requires private photo record")
        if name == "AccessRequirement" and not any(
            record.inspection_item_id == item.item_id and record.outcome is AccessOutcome.FULL_ACCESS
            for record in session.access_occurrences
        ):
            raise ValueError("completed access requirement requires full access occurrence")


_FIELD_RECORD_COLLECTIONS = (
    "observations", "statements", "measurements", "measurement_series", "methods", "instruments",
    "instrument_statuses", "photos", "videos", "sketches", "environmental_conditions",
    "access_occurrences", "limitations", "missing_items", "evidence_candidates", "reviews",
)


def _is_fresh_session(session) -> bool:
    return (
        type(session) is InspectionSession
        and session.visit_context is None and session.ended_at is None and not session.reuse_decisions
        and all(not getattr(session, name) for name in _FIELD_RECORD_COLLECTIONS)
        and all(
            item.state is ExecutionState.PENDING and item.note is None
            and not (item.observation_ids or item.measurement_ids or item.photo_ids or item.limitation_ids)
            for item in session.items
        )
    )


@dataclass(frozen=True, slots=True)
class SaveInspectionSession:
    revisions: object
    get_latest_revision: object
    get_planning: object
    get_private_content: object
    authority_guard: object
    clock: object
    ids: object

    def execute(self, workspace_id, session: InspectionSession, expected_revision: int | None, *, allow_initial_create: bool = False, allow_visit_confirmation: bool = False, allow_succession: bool = False, allow_reuse: bool = False):
        if sum((allow_initial_create, allow_visit_confirmation, allow_succession, allow_reuse)) > 1:
            raise ValueError("Inspection Session mutation authority is ambiguous")
        if (allow_succession or allow_reuse) and expected_revision is None:
            raise ValueError("Inspection Session succession and reuse require the latest revision")
        if allow_succession and not _is_fresh_session(session):
            raise ValueError("Inspection Session successor must start without field records")
        if type(session) is not InspectionSession or str(workspace_id) != session.workspace_id:
            raise ValueError("Inspection Session workspace identity mismatch")
        if session.upstream_stale:
            raise ValueError("stale Inspection Session cannot be persisted")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        if expected_revision is None and not allow_initial_create:
            raise ValueError("initial Inspection Session requires the canonical start command")
        if expected_revision is None and session.visit_context is not None:
            raise ValueError("visit facts require the dedicated confirmation command")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Inspection Session authority guard is unavailable")
        with self.authority_guard():
            if expected_revision is not None:
                predecessor_record = self.get_latest_revision.execute(
                    workspace_id, INSPECTION_SESSION_ARTIFACT_KIND, INSPECTION_SESSION_ARTIFACT_ID
                )
                if predecessor_record.revision != expected_revision:
                    raise RepositoryConflict("expected Inspection Session revision is not latest")
                predecessor = validated_inspection_session_from_mapping(thaw_payload(predecessor_record.payload))
            if expected_revision is not None and allow_succession:
                # A sessao anterior nao e reescrita: continua como revisao imutavel do
                # mesmo artefato. So uma sessao que deixou de refletir o planejamento
                # vigente (lido nesta transacao) pode ser sucedida.
                planning_record, planning = self.get_planning.execute(workspace_id)
                if not _reconcile(predecessor, planning_record=planning_record, planning=planning).upstream_stale:
                    raise ValueError("only a stale Inspection Session can be succeeded")
                if session.session_id == predecessor.session_id:
                    raise ValueError("Inspection Session successor requires a new session identity")
            elif expected_revision is not None:
                if allow_reuse:
                    if session.reuse_decisions[:len(predecessor.reuse_decisions)] != predecessor.reuse_decisions or len(session.reuse_decisions) <= len(predecessor.reuse_decisions):
                        raise ValueError("Inspection Session reuse must append professional reuse decisions")
                    if [(item.item_id, item.state, item.note) for item in session.items] != [(item.item_id, item.state, item.note) for item in predecessor.items]:
                        raise ValueError("reused field records cannot change inspection item execution state")
                elif session.reuse_decisions != predecessor.reuse_decisions:
                    raise ValueError("Inspection Session reuse requires the dedicated professional command")
                immutable = ("session_id", "workspace_id", "plan_snapshot", "started_at", "responsible_professional", "source_revision")
                if any(getattr(session, name) != getattr(predecessor, name) for name in immutable):
                    raise ValueError("Inspection Session immutable authority changed")
                if {(item.item_id, item.planning_item_id): item.title for item in session.items} != {
                    (item.item_id, item.planning_item_id): item.title for item in predecessor.items
                }:
                    raise ValueError("Inspection Session planned item identity or title changed")
                if session.visit_context != predecessor.visit_context and not allow_visit_confirmation:
                    raise ValueError("visit facts require the dedicated confirmation command")
                if allow_visit_confirmation and session.reviews != predecessor.reviews:
                    raise ValueError("visit confirmation cannot rewrite inspection review history")
                if session.reviews != predecessor.reviews and not allow_visit_confirmation:
                    raise ValueError("Inspection Session reviews require a dedicated professional command")
                append_only = (
                    "observations", "statements", "measurements", "measurement_series", "methods", "instruments",
                    "instrument_statuses", "photos", "videos", "sketches", "locations", "environmental_conditions",
                    "access_occurrences", "limitations", "missing_items", "evidence_candidates",
                )
                if any(getattr(session, name)[:len(getattr(predecessor, name))] != getattr(predecessor, name) for name in append_only):
                    raise ValueError("Inspection Session field history cannot be rewritten")
            planning_record, planning = self.get_planning.execute(workspace_id)
            reconciled = _reconcile(session, planning_record=planning_record, planning=planning)
            if reconciled.upstream_stale:
                raise ValueError("Inspection Session does not bind the latest approved planning authority")
            _validate_execution_against_planning(session, planning)
            self._verify_photos(workspace_id, session)
            created_at = self.clock.now()
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError("Inspection Session clock requires timezone")
            # Mesma regra da Analise do Caso: a escrita valida o schema que a leitura
            # valida. Sem isso, um valor que o dominio aceita e o schema recusa era
            # gravado com 200 e toda leitura seguinte falhava (sessao perdida).
            payload = inspection_session_to_mapping(session)
            try:
                _VALIDATOR.validate(payload)
            except ValidationError as exc:
                raise ValueError("Inspection Session payload violates its published schema") from exc
            return self.revisions.append_if_latest(
                workspace_id=workspace_id,
                artifact_kind=INSPECTION_SESSION_ARTIFACT_KIND,
                artifact_id=INSPECTION_SESSION_ARTIFACT_ID,
                revision_id=str(self.ids.new_uuid()),
                created_at=created_at.isoformat(),
                payload=payload,
                expected_revision=expected_revision,
                expected_dependencies=({
                    "artifact_kind": getattr(planning_record, "artifact_kind", "PERICIAL_PLANNING_SNAPSHOT_V1"),
                    "artifact_id": getattr(planning_record, "artifact_id", "PERICIAL-PLANNING"),
                    "revision": planning_record.revision,
                    "checksum_sha256": getattr(planning_record, "checksum_sha256", inspection_planning_digest(planning)),
                },),
            )

    def _verify_photos(self, workspace_id, session: InspectionSession) -> None:
        for photo in session.photos:
            record = self.get_private_content.execute(workspace_id, PrivateContentId.parse(photo.private_content_id))
            metadata = getattr(record, "metadata", None)
            if (
                metadata is None or metadata.workspace_id != workspace_id
                or str(metadata.content_id) != photo.private_content_id
                or metadata.checksum_sha256 != photo.original_sha256
                or type(metadata.media_type) is not str or not metadata.media_type.startswith("image/")
            ):
                raise ValueError("photo record diverges from private original authority")


@dataclass(frozen=True, slots=True)
class ConfirmInspectionVisit:
    get_session: object
    save_session: object
    get_expert_profile: object
    clock: object

    def execute(self, workspace_id, *, values, expected_revision):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("visit expected revision is invalid")
        record, session = self.get_session.execute(workspace_id)
        if record.revision != expected_revision or session.upstream_stale:
            raise RepositoryConflict("visit session is stale")
        _, profile = self.get_expert_profile.execute(workspace_id)
        context = VisitContext.from_values(values, confirmed_by=profile.profile_id, confirmed_at=self.clock.now().isoformat())
        # A confirmação cria uma nova revisão da sessão, mas a trilha profissional
        # anterior continua histórica e auditável. Invalidar autoridade corrente não
        # autoriza apagar os registros que explicam como a sessão chegou até aqui.
        updated = replace(session, visit_context=context, participant_references=tuple(dict.fromkeys(person.name for person in context.attendants)))
        saved = self.save_session.execute(workspace_id, updated, expected_revision, allow_visit_confirmation=True)
        return saved, updated


@dataclass(frozen=True, slots=True)
class GetInspectionSession:
    get_latest_revision: object
    get_planning: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id, INSPECTION_SESSION_ARTIFACT_KIND, INSPECTION_SESSION_ARTIFACT_ID
        )
        session = validated_inspection_session_from_mapping(thaw_payload(record.payload))
        if session.workspace_id != str(workspace_id):
            raise ValueError("persisted Inspection Session workspace mismatch")
        planning_record, planning = self.get_planning.execute(workspace_id)
        return record, _reconcile(session, planning_record=planning_record, planning=planning)


@dataclass(frozen=True, slots=True)
class StartInspectionSession:
    get_planning: object
    save_session: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, responsible_professional: str, location_context: str, participant_references: tuple[str, ...]):
        session = self.propose(
            workspace_id, responsible_professional=responsible_professional,
            location_context=location_context, participant_references=participant_references,
        )
        saved = self.save_session.execute(workspace_id, session, None, allow_initial_create=True)
        return saved, session

    def propose(self, workspace_id, *, responsible_professional: str, location_context: str, participant_references: tuple[str, ...]) -> InspectionSession:
        """Sessao nova, sem registros de campo, sobre o planejamento vigente."""
        if not isinstance(responsible_professional, str) or not responsible_professional.strip():
            raise ValueError("responsible professional is required")
        if not isinstance(location_context, str) or not location_context.strip():
            raise ValueError("inspection location context is required")
        if type(participant_references) is not tuple or any(type(item) is not str or not item.strip() for item in participant_references):
            raise ValueError("inspection participant references are invalid")
        record, planning = self.get_planning.execute(workspace_id)
        if planning.upstream_stale:
            raise ValueError("stale planning cannot start an Inspection Session")
        approved_ids = _executable_planning_item_ids(planning)
        if not approved_ids:
            raise ValueError("approved planning has no executable inspection items")
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Inspection Session clock requires timezone")
        item_by_id = {item.item_id: item for item in planning.material_items}
        # Capture the approved context now, in this bound planning revision.
        # Reopening an old session must never borrow text from a newer plan.
        decisions = {item_id: max((decision for decision in planning.decisions if decision.target_item_id == item_id), key=lambda decision: decision.revision) for item_id in approved_ids}
        contexts = {item_id: decision.decided_value or decision.proposal_value for item_id, decision in decisions.items()}
        location_id = f"LOCATION-{self.ids.new_uuid().hex.upper()}"
        items = tuple(
            InspectionItem(
                item_id=f"INSPECTION-ITEM-{self.ids.new_uuid().hex.upper()}",
                planning_item_id=item_id,
                title=f"{item_by_id[item_id].title} — {contexts[item_id]}" if contexts[item_id] != item_by_id[item_id].title else contexts[item_id],
                state=ExecutionState.PENDING,
                observation_ids=(), measurement_ids=(), photo_ids=(), limitation_ids=(), note=None,
            )
            for item_id in approved_ids
        )
        session = InspectionSession(
            schema_version="1.0.0",
            session_id=f"INSPECTION-SESSION-{self.ids.new_uuid().hex.upper()}",
            workspace_id=str(workspace_id),
            plan_snapshot=InspectionPlanSnapshot(
                plan_id=planning.plan.plan_id, planning_snapshot_id=planning.snapshot_id,
                planning_revision=record.revision, planning_digest=inspection_planning_digest(planning),
                workspace_id=str(workspace_id), approved_item_ids=approved_ids,
                source_revision=planning.plan.case_analysis_source_revision,
            ),
            started_at=now.isoformat(), ended_at=None, location_context=location_context,
            participant_references=participant_references, responsible_professional=responsible_professional,
            source_revision=planning.plan.case_analysis_source_revision, items=items,
            observations=(), statements=(), measurements=(), measurement_series=(), methods=(),
            instruments=(), instrument_statuses=(), photos=(), videos=(), sketches=(),
            locations=(LocationReference(location_id, location_context, None),), environmental_conditions=(),
            access_occurrences=(), limitations=(), missing_items=(), evidence_candidates=(),
            coverage=InspectionCoverage(
                total_items=len(items), pending_items=len(items), completed_items=0, partial_items=0,
                not_executed_items=0, not_applicable_items=0, blocked_items=0, complete=False,
                limitation_ids=(), reasons=("Itens de vistoria aguardam execução.",),
            ),
            reviews=(),
        )
        return session


@dataclass(frozen=True, slots=True)
class StartSuccessorInspectionSession:
    """Nova vistoria sobre o planejamento vigente quando a atual ficou para tras (#252).

    A sessao anterior continua como revisao imutavel do mesmo artefato, com todos os
    registros de campo, no historico e no backup. A sucessora nasce sem registros;
    trazer algo da anterior e decisao explicita do perito (ReuseInspectionRecords).
    """

    get_session: object
    start_session: StartInspectionSession
    save_session: object

    def execute(self, workspace_id, *, expected_revision: int, responsible_professional: str, location_context: str, participant_references: tuple[str, ...]):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected revision is invalid")
        record, _current = self.get_session.execute(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Inspection Session revision is not latest")
        session = self.start_session.propose(
            workspace_id, responsible_professional=responsible_professional,
            location_context=location_context, participant_references=participant_references,
        )
        saved = self.save_session.execute(workspace_id, session, expected_revision, allow_succession=True)
        return saved, session


def _lineage(planning) -> dict[str, tuple[str, tuple[str, ...]]]:
    # Correspondencia entre planos por derivacao semantica: o tipo do requisito e
    # os itens da Analise do Caso de que ele deriva. O titulo nao participa.
    return {
        item.item_id: (type(item).__name__, tuple(sorted(item.derivation.case_analysis_item_ids)))
        for item in planning.material_items
        if item.derivation.case_analysis_item_ids
    }


def _record_summary(kind: ReusedRecordKind, record) -> tuple[str, str | None]:
    if kind is ReusedRecordKind.OBSERVATION:
        return record.raw_observation, record.timestamp
    if kind is ReusedRecordKind.MEASUREMENT:
        return f"{record.quantity}: {record.raw_value} {record.raw_unit}", record.timestamp
    if kind is ReusedRecordKind.PHOTO:
        return record.caption, record.reliable_capture_timestamp
    if kind is ReusedRecordKind.STATEMENT:
        return f"{record.speaker} ({record.declared_role}): {record.verbatim_or_summary}", record.timestamp
    if kind is ReusedRecordKind.ACCESS_OCCURRENCE:
        return f"{record.outcome.value}: {record.description}", record.timestamp
    return f"{record.kind.value}: {record.description}", None


@dataclass(frozen=True, slots=True)
class InspectionReuseCandidates:
    """Registros da vistoria anterior que podem ser oferecidos ao perito.

    Nada aqui altera a sessao: so propoe pares (registro anterior, item atual) cuja
    linhagem semantica coincide. Quem decide e o comando de reaproveitamento.
    """

    get_session: object
    revisions: object
    get_planning: object

    def _previous_sessions(self, workspace_id, current, record):
        """Ultima revisao de cada vistoria anterior, da mais recente para a mais antiga.

        Uma cadeia V1 -> V2 -> V3 nao pode esconder registros da V1 que a V2 nunca
        reaproveitou: todas as vistorias anteriores sao fonte, cada uma lida contra o
        proprio planejamento de origem.
        """
        history = self.revisions.list_all(workspace_id, INSPECTION_SESSION_ARTIFACT_KIND, INSPECTION_SESSION_ARTIFACT_ID)
        latest: dict[str, object] = {}
        for item in sorted(history, key=lambda value: value.revision):
            session_id = thaw_payload(item.payload).get("session_id")
            if item.revision < record.revision and session_id != current.session_id:
                latest[session_id] = item
        sources = []
        for source_record in sorted(latest.values(), key=lambda value: value.revision, reverse=True):
            source = validated_inspection_session_from_mapping(thaw_payload(source_record.payload))
            if source.workspace_id != str(workspace_id):
                raise RepositoryIntegrityError("previous Inspection Session belongs to another workspace")
            planning_record = self.revisions.get_revision(
                workspace_id, PERICIAL_PLANNING_ARTIFACT_KIND, PERICIAL_PLANNING_ARTIFACT_ID, source.plan_snapshot.planning_revision,
            )
            if planning_record is None:
                raise RepositoryIntegrityError("previous Inspection Session planning authority is missing")
            source_planning = validated_pericial_planning_from_mapping(thaw_payload(planning_record.payload))
            if inspection_planning_digest(source_planning) != source.plan_snapshot.planning_digest:
                raise RepositoryIntegrityError("previous Inspection Session planning authority diverges")
            sources.append((source_record, source, _lineage(source_planning)))
        return sources

    def resolve(self, workspace_id):
        record, current = self.get_session.execute(workspace_id)
        if current.upstream_stale:
            raise ValueError("stale Inspection Session cannot receive reused records")
        sources = self._previous_sessions(workspace_id, current, record)
        _, planning = self.get_planning.execute(workspace_id)
        target_lineage = _lineage(planning)
        targets_by_signature: dict[tuple, list] = {}
        for item in current.items:
            signature = target_lineage.get(item.planning_item_id)
            if signature is not None:
                targets_by_signature.setdefault(signature, []).append(item)
        already = {(item.source_session_id, item.source_record_id) for item in current.reuse_decisions}
        candidates = []
        for source_record, source, source_lineage in sources:
            source_items = {item.item_id: item for item in source.items}
            # Copia ja reaproveitada naquela vistoria nao e um original: o original e
            # oferecido a partir da sessao de onde veio, uma unica vez.
            copies = {item.target_record_id for item in source.reuse_decisions}
            for kind, (collection, identity) in REUSABLE_RECORD_COLLECTIONS.items():
                for field_record in getattr(source, collection):
                    record_id = getattr(field_record, identity)
                    source_item = source_items[field_record.inspection_item_id]
                    signature = source_lineage.get(source_item.planning_item_id)
                    if record_id in copies or (source.session_id, record_id) in already or signature is None:
                        continue
                    summary, captured_at = _record_summary(kind, field_record)
                    for target in targets_by_signature.get(signature, ()):
                        candidates.append({
                            "source_session_id": source.session_id, "source_revision": source_record.revision,
                            "source_record_id": record_id, "record_kind": kind.value,
                            "source_item_title": source_item.title, "target_item_id": target.item_id,
                            "target_item_title": target.title, "summary": summary, "captured_at": captured_at,
                        })
        return record, current, {source.session_id: (source_record, source) for source_record, source, _ in sources}, tuple(candidates)

    def execute(self, workspace_id):
        record, _current, _sources, candidates = self.resolve(workspace_id)
        return {"revision": record.revision, "candidates": list(candidates)}


_REUSE_ID_PREFIX = {
    ReusedRecordKind.OBSERVATION: "OBSERVATION", ReusedRecordKind.MEASUREMENT: "MEASUREMENT",
    ReusedRecordKind.PHOTO: "PHOTO", ReusedRecordKind.STATEMENT: "STATEMENT",
    ReusedRecordKind.ACCESS_OCCURRENCE: "ACCESS", ReusedRecordKind.LIMITATION: "LIMITATION",
}
_ITEM_LINKS = {
    ReusedRecordKind.OBSERVATION: "observation_ids", ReusedRecordKind.MEASUREMENT: "measurement_ids",
    ReusedRecordKind.PHOTO: "photo_ids", ReusedRecordKind.LIMITATION: "limitation_ids",
}


@dataclass(frozen=True, slots=True)
class ReuseInspectionRecords:
    """Traz para a vistoria atual os registros que o perito escolheu, um a um.

    O conteudo original e preservado (horario de captura, bytes e SHA da foto, texto,
    proveniencia). A decisao registra sessao e revisao de origem, quem decidiu e
    quando. O estado do item atual nao muda: o perito continua julgando o item.
    """

    candidates: InspectionReuseCandidates
    save_session: object
    get_expert_profile: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, expected_revision: int, selections):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected revision is invalid")
        fields_ = {"source_session_id", "source_record_id", "target_item_id"}
        if type(selections) is not list or not selections or len(selections) > 512 or any(
            type(item) is not dict or set(item) != fields_ or any(type(item[name]) is not str for name in fields_)
            for item in selections
        ):
            raise ValueError("inspection reuse selections are invalid")
        if len({(item["source_session_id"], item["source_record_id"]) for item in selections}) != len(selections):
            raise ValueError("a previous record can be reused only once")
        record, current, sources, candidates = self.candidates.resolve(workspace_id)
        if record.revision != expected_revision:
            raise RepositoryConflict("expected Inspection Session revision is not latest")
        offered = {(item["source_session_id"], item["source_record_id"], item["target_item_id"]): item for item in candidates}
        if any((item["source_session_id"], item["source_record_id"], item["target_item_id"]) not in offered for item in selections):
            raise ValueError("inspection reuse selection is not an offered lineage match")
        _, profile = self.get_expert_profile.execute(workspace_id)
        decided_at = self.clock.now().isoformat()
        session = current
        collections = {name: list(getattr(session, name)) for name in ("observations", "measurements", "photos", "statements", "access_occurrences", "limitations", "locations", "methods", "instruments")}
        links = {item.item_id: {name: list(getattr(item, name)) for name in _ITEM_LINKS.values()} for item in session.items}
        decisions = list(session.reuse_decisions)

        def bring(source, name, identity, value):
            match = next(item for item in getattr(source, name) if getattr(item, identity) == value)
            existing = next((item for item in collections[name] if getattr(item, identity) == value), None)
            if existing is None:
                collections[name].append(match)
                if name == "locations" and match.parent_location_id is not None:
                    bring(source, "locations", "location_id", match.parent_location_id)
            elif existing != match:
                # Mesma identidade com conteudo diferente: o registro copiado nao pode
                # passar a apontar para algo que nao e o que sustentava o original.
                raise ValueError("reused record reference collides with a different record of this session")

        for selection in selections:
            key = (selection["source_session_id"], selection["source_record_id"], selection["target_item_id"])
            source_record, source = sources[selection["source_session_id"]]
            kind = ReusedRecordKind(offered[key]["record_kind"])
            collection, identity = REUSABLE_RECORD_COLLECTIONS[kind]
            original = next(item for item in getattr(source, collection) if getattr(item, identity) == selection["source_record_id"])
            new_id = f"{_REUSE_ID_PREFIX[kind]}-{self.ids.new_uuid().hex.upper()}"
            copy = replace(original, **{identity: new_id, "inspection_item_id": selection["target_item_id"]})
            if hasattr(copy, "location_id"):
                bring(source, "locations", "location_id", copy.location_id)
            if kind is ReusedRecordKind.MEASUREMENT:
                bring(source, "methods", "method_id", copy.method_id)
                bring(source, "instruments", "instrument_id", copy.instrument_id)
            collections[collection].append(copy)
            if kind in _ITEM_LINKS:
                links[selection["target_item_id"]][_ITEM_LINKS[kind]].append(new_id)
            decisions.append(InspectionReuseDecision(
                decision_id=f"INSPECTION-REUSE-{self.ids.new_uuid().hex.upper()}",
                source_session_id=source.session_id, source_session_revision=source_record.revision,
                source_record_kind=kind, source_record_id=selection["source_record_id"],
                target_record_id=new_id, target_item_id=selection["target_item_id"],
                decided_by=profile.profile_id, decided_at=decided_at,
            ))
        items = tuple(replace(item, **{name: tuple(values) for name, values in links[item.item_id].items()}) for item in session.items)
        limitation_ids = tuple(item.limitation_id for item in collections["limitations"])
        coverage = session.coverage
        complete = not any((coverage.pending_items, coverage.partial_items, coverage.not_executed_items, coverage.blocked_items, len(limitation_ids)))
        updated = replace(
            session, items=items, reuse_decisions=tuple(decisions),
            coverage=replace(coverage, limitation_ids=limitation_ids, complete=complete),
            **{name: tuple(values) for name, values in collections.items()},
        )
        saved = self.save_session.execute(workspace_id, updated, expected_revision, allow_reuse=True)
        return saved, updated
