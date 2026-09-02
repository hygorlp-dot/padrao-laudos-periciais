"""Application operations for workspace-owned Case Analysis snapshots."""

from dataclasses import dataclass, replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from ..case_analysis import (
    CASE_ANALYSIS_ARTIFACT_ID,
    CASE_ANALYSIS_ARTIFACT_KIND,
    CaseAnalysisSnapshot,
    HumanReviewDecision,
    AnalysisStatus,
    CaseAnalysisCoverage,
    CaseClaim,
    CaseDocument,
    CounterArgument,
    CoverageStatus,
    DocumentConflict,
    EvidenceGap,
    JudicialDecision,
    PericialObject,
    PericialQuestion,
    ProceduralEvent,
    SourceProvenance,
    TechnicalDocumentReference,
    case_analysis_from_mapping,
    case_analysis_to_mapping,
)
from ..judicial_domain import (
    EntityKind, JudicialEntity, NormalizedProceduralRole, ParticipantStatus,
    ProcessParticipant, ProcessPole, ProceduralContext, ProceduralRole,
    RepresentationLink, SourceProvenance as JudicialSourceProvenance,
)
from .models import thaw_payload
from .ports import RepositoryConflict, RepositoryIntegrityError


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "case-analysis-snapshot-v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_JDM_SCHEMA = json.loads((_SCHEMA_PATH.parent / "judicial-domain-model-v1.schema.json").read_text(encoding="utf-8"))
_REGISTRY = Registry().with_resource(_JDM_SCHEMA["$id"], Resource.from_contents(_JDM_SCHEMA))
_VALIDATOR = Draft202012Validator(_SCHEMA, registry=_REGISTRY)


def _logical_document_id(storage_content_id, local_document_id):
    """Identidade autoritativa de um documento logico do PJe.

    `DOC-PJE-NNN` e um ordinal LOCAL ao indice de um export: dois exports
    distintos usam os mesmos rotulos. Qualificar pela posicao da fonte na
    colecao seria pior ainda -- essa posicao muda quando uma fonte e
    acrescentada ou quando a listagem e reordenada, e decisoes profissionais e
    proveniencia ficam penduradas nessa identidade.

    A identidade e, portanto, `(fonte fisica, identificador local)`. Ela nao
    depende de ordem, de quantas fontes existem, nem de quando foram lidas.
    """
    if local_document_id is None:
        return None
    # O dominio judicial exige identificador canonico
    # (`^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$`), entao a fonte entra como o hex do
    # UUID em maiusculas -- sem separadores estranhos e sem minusculas.
    from uuid import UUID

    return f"{local_document_id}-{UUID(str(storage_content_id)).hex.upper()}"


def validated_case_analysis_from_mapping(value: object) -> CaseAnalysisSnapshot:
    try:
        _VALIDATOR.validate(value)
        return case_analysis_from_mapping(value)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ValueError("invalid Case Analysis payload") from exc


@dataclass(frozen=True, slots=True)
class SaveCaseAnalysis:
    revisions: object
    get_latest_revision: object
    clock: object
    ids: object
    list_documents: object | None
    authority_guard: object

    def execute(self, workspace_id, snapshot: CaseAnalysisSnapshot, expected_revision: int | None, *, allow_review_transition: bool = False, allow_item_append: bool = False):
        if type(snapshot) is not CaseAnalysisSnapshot or str(workspace_id) != snapshot.workspace_id:
            raise ValueError("Case Analysis workspace identity mismatch")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        if expected_revision is None and (snapshot.human_reviews or snapshot.material_items):
            raise ValueError("initial Case Analysis must be the canonical authority-free bootstrap")
        if not callable(self.authority_guard):
            raise RepositoryIntegrityError("Case Analysis authority guard is unavailable")
        with self.authority_guard():
            return self._execute_guarded(workspace_id, snapshot, expected_revision, allow_review_transition, allow_item_append)

    def _execute_guarded(self, workspace_id, snapshot: CaseAnalysisSnapshot, expected_revision: int | None, allow_review_transition: bool, allow_item_append: bool):
        if self.list_documents is None:
            raise RepositoryIntegrityError("Case Analysis source inventory is unavailable")
        authoritative = {
            str(document.content_id): document.checksum_sha256
            for document in self.list_documents.execute(workspace_id)
        }
        storage_ids = [document.storage_content_id for document in snapshot.documents]
        if snapshot.source_inventory_stale or set(storage_ids) != set(authoritative) or any(
            authoritative.get(document.storage_content_id) != document.source_sha256
            for document in snapshot.documents
        ):
            raise RepositoryIntegrityError("Case Analysis source inventory mismatch")
        if expected_revision is not None:
            record = self.get_latest_revision.execute(workspace_id, CASE_ANALYSIS_ARTIFACT_KIND, CASE_ANALYSIS_ARTIFACT_ID)
            if record.revision != expected_revision:
                raise RepositoryConflict("expected Case Analysis revision is not latest")
            predecessor = validated_case_analysis_from_mapping(thaw_payload(record.payload))
            immutable_identity = (
                "snapshot_id", "workspace_id", "source_revision", "participant_refs",
                "judicial_context_workspace_id", "judicial_context",
            )
            if any(getattr(predecessor, name) != getattr(snapshot, name) for name in immutable_identity):
                raise ValueError("Case Analysis canonical identity and JDM provenance are immutable")
            if predecessor.documents != snapshot.documents:
                raise ValueError("Case Analysis source extraction is immutable")
            if allow_item_append:
                prior = {item.item_id: item for item in predecessor.material_items}
                current = {item.item_id: item for item in snapshot.material_items}
                if not prior.keys() <= current.keys() or any(current[item_id] != item for item_id, item in prior.items()):
                    raise ValueError("Case Analysis material history is append-only")
            elif predecessor.material_items != snapshot.material_items:
                raise ValueError("Case Analysis material mutation requires a dedicated command")
            if not allow_review_transition and predecessor.human_reviews != snapshot.human_reviews:
                raise ValueError("Case Analysis reviews require the dedicated review command")
            if snapshot.human_reviews[:len(predecessor.human_reviews)] != predecessor.human_reviews:
                raise ValueError("Case Analysis human review history is append-only")
        created_at = self.clock.now()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Case Analysis clock requires timezone")
        return self.revisions.append_if_latest(
            workspace_id=workspace_id,
            artifact_kind=CASE_ANALYSIS_ARTIFACT_KIND,
            artifact_id=CASE_ANALYSIS_ARTIFACT_ID,
            revision_id=str(self.ids.new_uuid()),
            created_at=created_at.isoformat(),
            payload=case_analysis_to_mapping(snapshot),
            expected_revision=expected_revision,
        )


@dataclass(frozen=True, slots=True)
class ReviewCaseAnalysisItem:
    get_analysis: object
    save_analysis: object
    clock: object
    ids: object

    def execute(self, workspace_id, *, target_item_id: str, action: str, corrected_value: str | None, reviewer: str, reason: str, expected_revision: int):
        if action not in {"CONFIRM", "CORRECT", "REJECT"}:
            raise ValueError("Case Analysis review action is invalid")
        record, snapshot = self.get_analysis.execute(workspace_id)
        if record.revision != expected_revision or snapshot.stale_document_ids or snapshot.source_inventory_stale:
            raise RepositoryConflict("Case Analysis review source or revision is stale")
        item = next((candidate for candidate in snapshot.material_items if candidate.item_id == target_item_id), None)
        if item is None:
            raise ValueError("Case Analysis review target is invalid")
        if action == "CORRECT":
            if type(corrected_value) is not str or not corrected_value.strip() or corrected_value == item.text:
                raise ValueError("Case Analysis correction requires a distinct value")
            effective = corrected_value.strip()
        elif corrected_value is not None:
            raise ValueError("only Case Analysis correction may carry a corrected value")
        else:
            effective = item.text
        if type(reviewer) is not str or not reviewer.strip() or type(reason) is not str or not reason.strip():
            raise ValueError("Case Analysis reviewer and reason are required")
        now = self.clock.now()
        history = [review for review in snapshot.human_reviews if review.target_item_id == target_item_id]
        decision = HumanReviewDecision(
            review_id=f"CASE-REVIEW-{self.ids.new_uuid().hex.upper()}", target_item_id=target_item_id,
            original_extraction=item.text, decision=action, corrected_value=effective, reviewer=reviewer.strip(),
            revision=len(history) + 1, timestamp=now.isoformat(), reason=reason.strip(),
        )
        reviewed = replace(snapshot, human_reviews=(*snapshot.human_reviews, decision))
        saved = self.save_analysis.execute(workspace_id, reviewed, expected_revision, allow_review_transition=True)
        return saved, reviewed


@dataclass(frozen=True, slots=True)
class StartCaseAnalysis:
    list_documents: object
    save_analysis: object
    ids: object

    def execute(self, workspace_id):
        stored = tuple(self.list_documents.execute(workspace_id))
        if not stored:
            raise ValueError("Case Analysis requires at least one stored document")
        source_revision = 1
        # Cada export PJe abre em varios documentos logicos sobre a SUA autoridade
        # fisica, e um workspace pode ter mais de um (autos em dois volumes sao
        # rotina). Os demais materiais continuam sendo fontes por direito proprio.
        # Descartar qualquer um dos dois grupos seria perda silenciosa.
        pje_sources = [item for item in stored if getattr(item, "pje_inventory", None) is not None]
        composed: list[CaseDocument] = []
        for source in pje_sources:
            for row in source.pje_inventory["documents"]:
                composed.append(CaseDocument(
                    document_id=_logical_document_id(source.content_id, row["document_id"]),
                    storage_content_id=str(source.content_id),
                    source_sha256=source.checksum_sha256, sequence=len(composed) + 1,
                    document_role="CASE_SOURCE", raw_type=row["raw_type"],
                    normalized_type=row["normalized_type"], timestamp=None,
                    participant_refs=(), page_count_or_span=(
                        f"p. {row['page_start']}" + (f"-{row['page_end']}" if row["page_end"] != row["page_start"] else "")
                        + f" | PJe {row['id_pje']}"
                    ), content_available=row["available"], analysis_revision=1 if row["available"] else 0,
                ))
        pje_content_ids = {item.content_id for item in pje_sources}
        for item in stored:
            if item.content_id in pje_content_ids:
                continue
            composed.append(CaseDocument(
                document_id=f"DOC-{len(composed) + 1:03d}", storage_content_id=str(item.content_id),
                source_sha256=item.checksum_sha256, sequence=len(composed) + 1,
                document_role="CASE_SOURCE",
                raw_type=getattr(item, "original_filename", "Documento"),
                normalized_type="UNCLASSIFIED", timestamp=None, participant_refs=(),
                page_count_or_span="Documento completo", content_available=True, analysis_revision=1,
            ))
        documents = tuple(composed)
        if not documents:
            raise ValueError("PJe inventory requires logical documents")
        first = documents[0]
        context_id = f"CONTEXT-{self.ids.new_uuid().hex.upper()}"
        entities, participants, representation_links = [], [], []
        # Um documento que o perito marcou indisponivel permanece inventariado,
        # mas nao pode alimentar o contexto efetivo: deixar suas linhas de parte
        # entrarem aqui reintroduziria, sob a identidade de outro documento,
        # exatamente o conteudo que a exclusao mandou deixar de fora.
        by_document = {item.document_id: item for item in documents}

        party_rows = []
        excluded = set()
        for source in pje_sources:
            for row in source.pje_inventory["documents"]:
                if not row["available"]:
                    excluded.add(_logical_document_id(source.content_id, row["document_id"]))
            for row in source.pje_inventory.get("party_rows", ()):
                party_rows.append({
                    **row,
                    "document_id": _logical_document_id(source.content_id, row.get("document_id")),
                })

        for index, row in enumerate(party_rows, 1):
            if row.get("document_id") in excluded:
                continue
            # A proveniencia nomeia o documento logico que realmente contem a
            # pagina; atribuir tudo ao primeiro documento tornava o triplo
            # (documento, sha, pagina) internamente inconsistente.
            origin = by_document.get(row.get("document_id"), first)
            source = JudicialSourceProvenance(
                "PJE", origin.document_id, origin.source_sha256, row["page"], row["occurrence"],
                f"OCCURRENCE-PJE-PARTY-{index:03d}",
            )
            entity_id, participant_id = f"ENTITY-PJE-PARTY-{index:03d}", f"PARTICIPANT-PJE-{index:03d}"
            entities.append(JudicialEntity(entity_id, row["name"], EntityKind.UNKNOWN, (source,)))
            pole = ProcessPole.ACTIVE if row["pole"] == "ACTIVE" else ProcessPole.PASSIVE
            role = NormalizedProceduralRole.CLAIMANT if pole is ProcessPole.ACTIVE else NormalizedProceduralRole.DEFENDANT
            participants.append(ProcessParticipant(participant_id, entity_id, context_id, pole, ProceduralRole(row["role"], role), True, ParticipantStatus.ACTIVE, (source,)))
            if row.get("representative_name"):
                representative_id = f"ENTITY-PJE-REPRESENTATIVE-{index:03d}"
                entities.append(JudicialEntity(representative_id, row["representative_name"], EntityKind.UNKNOWN, (source,)))
                representation_links.append(RepresentationLink(f"REPRESENTATION-PJE-{index:03d}", representative_id, (participant_id,), row["representative_role"], (source,)))
        context = ProceduralContext(
            context_id=context_id,
            instance_label=(pje_sources[0].pje_inventory.get("instance_label") or "NÃO CLASSIFICADA") if pje_sources else "NÃO CLASSIFICADA",
            snapshot_id=f"JDM-SNAPSHOT-{self.ids.new_uuid().hex.upper()}", entities=tuple(entities), participants=tuple(participants),
            representation_links=tuple(representation_links), access_relations=(), provenance=(JudicialSourceProvenance(
                source_system="PJE" if pje_sources else "LOCAL_CASE_DOCUMENT", source_document_id=first.document_id,
                source_sha256=first.source_sha256, page=1, occurrence="Índice documental",
                occurrence_id=f"OCCURRENCE-{self.ids.new_uuid().hex.upper()}",
            ),),
        )
        analyzed = sum(item.content_available for item in documents)
        unavailable = len(documents) - analyzed
        coverage_status = CoverageStatus.COMPLETE if unavailable == 0 else CoverageStatus.PARTIAL if analyzed else CoverageStatus.UNAVAILABLE
        snapshot = CaseAnalysisSnapshot(
            snapshot_id=f"CASE-ANALYSIS-{self.ids.new_uuid().hex.upper()}", workspace_id=str(workspace_id),
            source_revision=source_revision, participant_refs=tuple(item.participant_id for item in participants), judicial_context_workspace_id=str(workspace_id),
            judicial_context=context, documents=documents, claims=(), counterarguments=(), decisions=(),
            pericial_objects=(), questions=(), events=(), technical_document_references=(), gaps=(), conflicts=(),
            coverage=CaseAnalysisCoverage(coverage_status, len(documents), analyzed, unavailable, 0, source_revision),
            human_reviews=(),
        )
        saved = self.save_analysis.execute(workspace_id, snapshot, None)
        return saved, snapshot


@dataclass(frozen=True, slots=True)
class AddCaseAnalysisItem:
    get_analysis: object
    save_analysis: object
    ids: object

    def execute(self, workspace_id, *, item_kind: str, text: str, source_document_id: str, page_or_span: str, technical_subjects: tuple[str, ...], values: dict, expected_revision: int):
        record, snapshot = self.get_analysis.execute(workspace_id)
        if record.revision != expected_revision or snapshot.stale_document_ids or snapshot.source_inventory_stale:
            raise RepositoryConflict("Case Analysis item source or revision is stale")
        document = next((item for item in snapshot.documents if item.document_id == source_document_id), None)
        if document is None or type(text) is not str or not text.strip() or type(page_or_span) is not str or not page_or_span.strip():
            raise ValueError("Case Analysis item source input is invalid")
        if type(technical_subjects) is not tuple or any(type(item) is not str or not item.strip() for item in technical_subjects) or type(values) is not dict:
            raise ValueError("Case Analysis item structured input is invalid")
        token = self.ids.new_uuid().hex.upper()
        provenance = (SourceProvenance(str(workspace_id), document.document_id, document.source_sha256, page_or_span.strip(), snapshot.source_revision, f"OCCURRENCE-{token}"),)
        item_id_prefix = item_kind.replace("_", "-")
        base = dict(item_id=f"{item_id_prefix}-{token}", text=text.strip(), participant_refs=(), technical_subjects=technical_subjects, provenance=provenance)
        constructors = {
            "CLAIM": lambda: CaseClaim(**base),
            "COUNTERARGUMENT": lambda: CounterArgument(**base, target_claim_ids=tuple(values.get("target_claim_ids", ()))),
            "JUDICIAL_DECISION": lambda: JudicialDecision(**base, addressed_claim_ids=tuple(values.get("addressed_claim_ids", ())), addressed_counterargument_ids=tuple(values.get("addressed_counterargument_ids", ()))),
            "PERICIAL_OBJECT": lambda: PericialObject(**base),
            "PERICIAL_QUESTION": lambda: PericialQuestion(**base),
            "PROCEDURAL_EVENT": lambda: ProceduralEvent(**base, event_raw=values.get("event_raw", text), event_normalized=values.get("event_normalized", "UNCLASSIFIED"), timestamp=values.get("timestamp")),
            "TECHNICAL_DOCUMENT_REFERENCE": lambda: TechnicalDocumentReference(**base, external_reference=values.get("external_reference", False)),
            "EVIDENCE_GAP": lambda: EvidenceGap(**base),
            "PROPOSED_CONFLICT": lambda: DocumentConflict(**base, statement_a_id=values.get("statement_a_id", ""), statement_b_id=values.get("statement_b_id", ""), conflict_dimension=values.get("conflict_dimension", ""), analysis_status=AnalysisStatus.PROPOSED_CONFLICT, human_review_status="PENDING"),
        }
        if item_kind not in constructors:
            raise ValueError("Case Analysis item kind is invalid")
        item = constructors[item_kind]()
        field_by_kind = {
            "CLAIM": "claims", "COUNTERARGUMENT": "counterarguments", "JUDICIAL_DECISION": "decisions",
            "PERICIAL_OBJECT": "pericial_objects", "PERICIAL_QUESTION": "questions", "PROCEDURAL_EVENT": "events",
            "TECHNICAL_DOCUMENT_REFERENCE": "technical_document_references", "EVIDENCE_GAP": "gaps",
            "PROPOSED_CONFLICT": "conflicts",
        }
        field = field_by_kind[item_kind]
        amended = replace(snapshot, **{field: (*getattr(snapshot, field), item)})
        saved = self.save_analysis.execute(workspace_id, amended, expected_revision, allow_item_append=True)
        return saved, amended


@dataclass(frozen=True, slots=True)
class GetCaseAnalysis:
    get_latest_revision: object
    list_documents: object | None

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(
            workspace_id,
            CASE_ANALYSIS_ARTIFACT_KIND,
            CASE_ANALYSIS_ARTIFACT_ID,
        )
        snapshot = validated_case_analysis_from_mapping(thaw_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Case Analysis workspace mismatch")
        if self.list_documents is None:
            raise RepositoryIntegrityError("Case Analysis source inventory is unavailable")
        authoritative = {
            str(document.content_id): document.checksum_sha256
            for document in self.list_documents.execute(workspace_id)
        }
        current_hashes = {
            document.document_id: authoritative.get(document.storage_content_id)
            for document in snapshot.documents
        }
        reconciled = snapshot.reconcile_sources(current_hashes)
        unindexed = set(authoritative) - {document.storage_content_id for document in snapshot.documents}
        return record, replace(
            reconciled,
            source_inventory_stale=bool(unindexed),
            unindexed_source_count=len(unindexed),
        )
