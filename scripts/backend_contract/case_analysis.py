"""Source-neutral, non-conclusive judicial case analysis contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import re

from .judicial_domain import ProceduralContext, procedural_context_from_mapping


class CoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class AnalysisStatus(StrEnum):
    PROPOSED_CONFLICT = "PROPOSED_CONFLICT"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    HUMAN_REJECTED = "HUMAN_REJECTED"


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    workspace_id: str
    source_document_id: str
    source_document_sha256: str
    page_or_span: str
    source_revision: int
    occurrence_id: str

    def __post_init__(self):
        if not all(
            type(value) is str and value.strip()
            for value in (self.workspace_id, self.source_document_id, self.page_or_span, self.occurrence_id)
        ):
            raise ValueError("provenance requires exact identity")
        if type(self.source_document_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.source_document_sha256) is None:
            raise ValueError("provenance requires source SHA")
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise ValueError("provenance requires source revision")


@dataclass(frozen=True, slots=True)
class CaseDocument:
    document_id: str
    storage_content_id: str
    source_sha256: str
    sequence: int
    document_role: str
    raw_type: str
    normalized_type: str
    timestamp: str | None
    participant_refs: tuple[str, ...]
    page_count_or_span: str
    content_available: bool
    analysis_revision: int

    def __post_init__(self):
        if not all(
            type(value) is str and value.strip()
            for value in (
                self.document_id,
                self.storage_content_id,
                self.document_role,
                self.raw_type,
                self.normalized_type,
                self.page_count_or_span,
            )
        ):
            raise ValueError("Case Document requires exact identity and role")
        if re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None:
            raise ValueError("Case Document requires a hexadecimal source SHA")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("Case Document sequence is invalid")
        if type(self.content_available) is not bool or type(self.analysis_revision) is not int or self.analysis_revision < 0:
            raise ValueError("Case Document analysis state is invalid")


@dataclass(frozen=True, slots=True)
class MaterialItem:
    item_id: str
    text: str
    participant_refs: tuple[str, ...]
    technical_subjects: tuple[str, ...]
    provenance: tuple[SourceProvenance, ...]
    stale: bool = False

    def __post_init__(self):
        if (
            type(self.item_id) is not str
            or not self.item_id.strip()
            or type(self.text) is not str
            or not self.text.strip()
            or not self.provenance
            or any(type(item) is not SourceProvenance for item in self.provenance)
            or any(type(item) is not str or not item.strip() for item in (*self.participant_refs, *self.technical_subjects))
        ):
            raise ValueError("material item requires provenance")


@dataclass(frozen=True, slots=True)
class CaseClaim(MaterialItem):
    pass


@dataclass(frozen=True, slots=True)
class CounterArgument(MaterialItem):
    target_claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JudicialDecision(MaterialItem):
    addressed_claim_ids: tuple[str, ...] = ()
    addressed_counterargument_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PericialObject(MaterialItem):
    pass


@dataclass(frozen=True, slots=True)
class PericialQuestion(MaterialItem):
    answer: None = None

    def __post_init__(self):
        super().__post_init__()
        if self.answer is not None:
            raise ValueError("Stage 3 cannot answer pericial questions")


@dataclass(frozen=True, slots=True)
class ProceduralEvent(MaterialItem):
    event_raw: str = ""
    event_normalized: str = ""
    timestamp: str | None = None
    normalization_authority: str = "SOURCE_RAW"


@dataclass(frozen=True, slots=True)
class TechnicalDocumentReference(MaterialItem):
    external_reference: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceGap(MaterialItem):
    pass


@dataclass(frozen=True, slots=True)
class DocumentConflict(MaterialItem):
    statement_a_id: str = ""
    statement_b_id: str = ""
    conflict_dimension: str = ""
    analysis_status: AnalysisStatus = AnalysisStatus.PROPOSED_CONFLICT
    human_review_status: str = "PENDING"

    def __post_init__(self):
        super().__post_init__()
        if self.analysis_status is not AnalysisStatus.PROPOSED_CONFLICT and self.human_review_status == "PENDING":
            raise ValueError("material conflict requires human review")


@dataclass(frozen=True, slots=True)
class HumanReviewDecision:
    review_id: str
    target_item_id: str
    original_extraction: str
    decision: str
    corrected_value: str
    reviewer: str
    revision: int
    timestamp: str
    reason: str

    def __post_init__(self):
        if not all(
            type(value) is str and value.strip()
            for value in (
                self.review_id,
                self.target_item_id,
                self.original_extraction,
                self.decision,
                self.corrected_value,
                self.reviewer,
                self.timestamp,
                self.reason,
            )
        ) or type(self.revision) is not int or self.revision < 1:
            raise ValueError("human review decision is invalid")


@dataclass(frozen=True, slots=True)
class CaseAnalysisCoverage:
    status: CoverageStatus
    documents_total: int
    documents_analyzed: int
    documents_unavailable: int
    documents_failed: int
    source_revision: int

    def __post_init__(self):
        values = (self.documents_total, self.documents_analyzed, self.documents_unavailable, self.documents_failed)
        if any(type(value) is not int or value < 0 for value in values) or self.source_revision < 1:
            raise ValueError("coverage counters are invalid")
        if self.documents_analyzed + self.documents_unavailable + self.documents_failed != self.documents_total:
            raise ValueError("coverage counters do not reconcile")
        expected = CoverageStatus.UNAVAILABLE if self.documents_analyzed == 0 else (CoverageStatus.COMPLETE if self.documents_analyzed == self.documents_total else CoverageStatus.PARTIAL)
        if self.status is not expected:
            raise ValueError("coverage status is dishonest")


@dataclass(frozen=True, slots=True)
class QueryResult:
    document_ids: tuple[str, ...]
    documents_considered: int
    documents_total: int
    full_case_rescan: bool = False


@dataclass(frozen=True, slots=True)
class CaseAnalysisSnapshot:
    snapshot_id: str
    workspace_id: str
    source_revision: int
    participant_refs: tuple[str, ...]
    judicial_context_workspace_id: str
    judicial_context: ProceduralContext
    documents: tuple[CaseDocument, ...]
    claims: tuple[CaseClaim, ...]
    counterarguments: tuple[CounterArgument, ...]
    decisions: tuple[JudicialDecision, ...]
    pericial_objects: tuple[PericialObject, ...]
    questions: tuple[PericialQuestion, ...]
    events: tuple[ProceduralEvent, ...]
    technical_document_references: tuple[TechnicalDocumentReference, ...]
    gaps: tuple[EvidenceGap, ...]
    conflicts: tuple[DocumentConflict, ...]
    coverage: CaseAnalysisCoverage
    human_reviews: tuple[HumanReviewDecision, ...]
    stale_document_ids: tuple[str, ...] = ()
    source_inventory_stale: bool = False
    unindexed_source_count: int = 0

    def __post_init__(self):
        if type(self.source_inventory_stale) is not bool or type(self.unindexed_source_count) is not int or self.unindexed_source_count < 0:
            raise ValueError("source inventory state is invalid")
        if self.source_inventory_stale != (self.unindexed_source_count > 0):
            raise ValueError("source inventory stale state is dishonest")
        if self.judicial_context_workspace_id != self.workspace_id:
            raise ValueError("JDM context workspace identity mismatch")
        participant_ids = {item.participant_id for item in self.judicial_context.participants}
        if not set(self.participant_refs) <= participant_ids:
            raise ValueError("Case Analysis participant references require canonical JDM participants")
        documents = {document.document_id: document for document in self.documents}
        if len(documents) != len(self.documents):
            raise ValueError("Case Analysis document identities must be unique")
        if any(not set(document.participant_refs) <= participant_ids for document in self.documents):
            raise ValueError("document participant references require canonical JDM participants")
        if self.coverage.source_revision != self.source_revision or self.coverage.documents_total != len(self.documents):
            raise ValueError("coverage must reconcile with the analysis snapshot")
        unavailable = sum(not document.content_available for document in self.documents)
        analyzed = sum(document.content_available and document.analysis_revision > 0 for document in self.documents)
        failed = sum(document.content_available and document.analysis_revision == 0 for document in self.documents)
        if (
            self.coverage.documents_unavailable != unavailable
            or self.coverage.documents_analyzed != analyzed
            or self.coverage.documents_failed != failed
        ):
            raise ValueError("coverage must reflect indexed document availability")
        occurrences: dict[str, tuple[str, str, str]] = {}
        item_ids = [item.item_id for item in self.material_items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("material item identities must be unique")
        claims = {item.item_id for item in self.claims}
        counterarguments = {item.item_id for item in self.counterarguments}
        item_id_set = set(item_ids)
        if any(not set(item.target_claim_ids) <= claims for item in self.counterarguments):
            raise ValueError("counterargument targets must reference canonical claims")
        if any(
            not set(item.addressed_claim_ids) <= claims
            or not set(item.addressed_counterargument_ids) <= counterarguments
            for item in self.decisions
        ):
            raise ValueError("decision targets must reference canonical analysis items")
        if any(
            item.statement_a_id not in item_id_set or item.statement_b_id not in item_id_set
            for item in self.conflicts
        ):
            raise ValueError("conflict statements must reference canonical analysis items")
        if any(review.target_item_id not in item_id_set for review in self.human_reviews):
            raise ValueError("human review target must reference a canonical analysis item")
        item_by_id = {item.item_id: item for item in self.material_items}
        review_ids: set[str] = set()
        reviews_by_target: dict[str, list[HumanReviewDecision]] = {}
        for review in self.human_reviews:
            if review.review_id in review_ids or review.decision not in {"CONFIRM", "CORRECT", "CORRECTED", "REJECT"}:
                raise ValueError("human review identity or action is invalid")
            review_ids.add(review.review_id)
            if review.decision != "CORRECTED" and review.original_extraction != item_by_id[review.target_item_id].text:
                raise ValueError("human review original extraction mismatch")
            if review.decision in {"CORRECT", "CORRECTED"} and review.corrected_value == review.original_extraction:
                raise ValueError("human correction must change the effective value")
            if review.decision not in {"CORRECT", "CORRECTED"} and review.corrected_value != review.original_extraction:
                raise ValueError("only correction may change the reviewed value")
            reviews_by_target.setdefault(review.target_item_id, []).append(review)
        if any([review.revision for review in history] != list(range(1, len(history) + 1)) for history in reviews_by_target.values()):
            raise ValueError("human review revisions must append contiguously")
        for item in self.material_items:
            if not set(item.participant_refs) <= participant_ids:
                raise ValueError("material participant references require canonical JDM participants")
            for source in item.provenance:
                if source.workspace_id != self.workspace_id:
                    raise ValueError("cross-workspace provenance")
                document = documents.get(source.source_document_id)
                if document is None or source.source_document_sha256 != document.source_sha256:
                    raise ValueError("provenance must bind to the indexed source identity")
                if source.source_revision != self.source_revision:
                    raise ValueError("provenance source revision must match the analysis source revision")
                locator = (source.source_document_id, source.source_document_sha256, source.page_or_span)
                previous = occurrences.setdefault(source.occurrence_id, locator)
                if previous != locator:
                    raise ValueError("occurrence identity resolves to conflicting source locators")
        for source in (
            *self.judicial_context.provenance,
            *(source for entity in self.judicial_context.entities for source in entity.provenance),
            *(source for participant in self.judicial_context.participants for source in participant.provenance),
            *(source for link in self.judicial_context.representation_links for source in link.provenance),
            *(source for access in self.judicial_context.access_relations for source in access.provenance),
            ):
            document = documents.get(source.source_document_id)
            if document is None or source.source_sha256 != document.source_sha256:
                raise ValueError("JDM provenance must bind to the indexed source identity")

    @property
    def material_items(self):
        return (
            *self.claims,
            *self.counterarguments,
            *self.decisions,
            *self.pericial_objects,
            *self.questions,
            *self.events,
            *self.technical_document_references,
            *self.gaps,
            *self.conflicts,
        )

    def effective_reviewed_value(self, item_id: str) -> str | None:
        """Return the reviewed semantic value without mutating source extraction."""
        item = next((candidate for candidate in self.material_items if candidate.item_id == item_id), None)
        if item is None:
            raise ValueError("effective review target is invalid")
        history = sorted(
            (review for review in self.human_reviews if review.target_item_id == item_id),
            key=lambda review: review.revision,
        )
        if not history:
            return item.text
        latest = history[-1]
        if latest.decision == "REJECT":
            return None
        return latest.corrected_value if latest.decision in {"CORRECT", "CORRECTED"} else item.text

    def project_effective_availability(self, availability: dict[str, bool]):
        """Projeta a disponibilidade vigente sobre o snapshot persistido.

        `content_available` e congelado no bootstrap, e a extracao de fontes e
        imutavel por contrato -- entao uma exclusao decidida DEPOIS do bootstrap
        nao tinha como alcancar a analise, e ficava como metadata morta. A
        decisao profissional prevalece sobre o valor de origem, mas a revisao
        persistida nao pode ser reescrita: o historico continua respondendo "o
        que era efetivo naquela revisao".

        A projecao resolve isso na LEITURA, como ja se faz com hash de fonte: o
        documento excluido deixa de estar disponivel no estado efetivo, a
        cobertura e recomputada, e ele entra em `stale_document_ids` para que
        tudo o que dele derivou seja marcado como carente de revisao em vez de
        seguir se declarando valido.
        """
        revised = {
            document.document_id: availability[document.document_id]
            for document in self.documents
            if document.document_id in availability
            and availability[document.document_id] != document.content_available
        }
        if not revised:
            return self
        documents = tuple(
            replace(document, content_available=revised[document.document_id])
            if document.document_id in revised else document
            for document in self.documents
        )
        unavailable = sum(not document.content_available for document in documents)
        analyzed = sum(document.content_available and document.analysis_revision > 0 for document in documents)
        failed = sum(document.content_available and document.analysis_revision == 0 for document in documents)
        status = (
            CoverageStatus.COMPLETE if unavailable == 0 and failed == 0
            else CoverageStatus.PARTIAL if analyzed
            else CoverageStatus.UNAVAILABLE
        )
        changed = tuple(sorted(set(self.stale_document_ids) | set(revised)))

        def stale(items):
            return tuple(
                replace(item, stale=any(p.source_document_id in changed for p in item.provenance))
                for item in items
            )

        return replace(
            self,
            documents=documents,
            coverage=replace(
                self.coverage,
                status=status,
                documents_unavailable=unavailable,
                documents_analyzed=analyzed,
                documents_failed=failed,
            ),
            claims=stale(self.claims),
            counterarguments=stale(self.counterarguments),
            decisions=stale(self.decisions),
            pericial_objects=stale(self.pericial_objects),
            questions=stale(self.questions),
            events=stale(self.events),
            technical_document_references=stale(self.technical_document_references),
            gaps=stale(self.gaps),
            conflicts=stale(self.conflicts),
            stale_document_ids=changed,
        )

    def reconcile_sources(self, source_hashes: dict[str, str]):
        changed = tuple(sorted(
            set(self.stale_document_ids)
            | {
                document.document_id
                for document in self.documents
                if source_hashes.get(document.document_id) != document.source_sha256
            }
        ))
        if not changed and not self.stale_document_ids:
            return self

        def stale(items):
            return tuple(replace(item, stale=any(p.source_document_id in changed for p in item.provenance)) for item in items)

        return replace(
            self,
            claims=stale(self.claims),
            counterarguments=stale(self.counterarguments),
            decisions=stale(self.decisions),
            pericial_objects=stale(self.pericial_objects),
            questions=stale(self.questions),
            events=stale(self.events),
            technical_document_references=stale(self.technical_document_references),
            gaps=stale(self.gaps),
            conflicts=stale(self.conflicts),
            stale_document_ids=changed,
        )


CASE_ANALYSIS_ARTIFACT_KIND = "CASE_ANALYSIS_SNAPSHOT_V1"
CASE_ANALYSIS_ARTIFACT_ID = "CASE-ANALYSIS"


def case_analysis_to_mapping(snapshot: CaseAnalysisSnapshot) -> dict:
    if type(snapshot) is not CaseAnalysisSnapshot:
        raise TypeError("canonical Case Analysis snapshot required")
    value = _json_value(asdict(snapshot))
    value["schema_version"] = "1.0.0"
    value["judicial_context"]["schema_version"] = "1.0.0"
    for name in (
        "claims",
        "counterarguments",
        "decisions",
        "pericial_objects",
        "questions",
        "events",
        "technical_document_references",
        "gaps",
        "conflicts",
    ):
        for item in value[name]:
            item.pop("stale")
    return value


def _json_value(value):
    if isinstance(value, StrEnum):
        return str(value)
    if type(value) is tuple:
        return [_json_value(item) for item in value]
    if type(value) is list:
        return [_json_value(item) for item in value]
    if type(value) is dict:
        return {key: _json_value(item) for key, item in value.items()}
    return value


_ROOT_FIELDS = {
    "schema_version",
    "snapshot_id",
    "workspace_id",
    "source_revision",
    "participant_refs",
    "judicial_context_workspace_id",
    "judicial_context",
    "documents",
    "claims",
    "counterarguments",
    "decisions",
    "pericial_objects",
    "questions",
    "events",
    "technical_document_references",
    "gaps",
    "conflicts",
    "coverage",
    "human_reviews",
    "stale_document_ids",
    "source_inventory_stale",
    "unindexed_source_count",
}


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{label} requires exact fields")
    return value


def _prov(value, workspace_id):
    if type(value) is not list or not value:
        raise ValueError("provenance is required")
    result = tuple(
        SourceProvenance(
            **_exact(
                item,
                {
                    "workspace_id",
                    "source_document_id",
                    "source_document_sha256",
                    "page_or_span",
                    "source_revision",
                    "occurrence_id",
                },
                "provenance",
            )
        )
        for item in value
    )
    if any(item.workspace_id != workspace_id for item in result):
        raise ValueError("cross-workspace provenance")
    return result


_BASE = {"item_id", "text", "participant_refs", "technical_subjects", "provenance"}


def _items(raw, cls, workspace_id, extra=()):
    rows = []
    for value in raw:
        row = _exact(value, _BASE | set(extra), cls.__name__)
        data = {key: row[key] for key in _BASE - {"provenance"}}
        data["participant_refs"] = tuple(data["participant_refs"])
        data["technical_subjects"] = tuple(data["technical_subjects"])
        data["provenance"] = _prov(row["provenance"], workspace_id)
        for key in extra:
            value = row[key]
            if key.endswith("_ids"):
                value = tuple(value)
            if key == "analysis_status":
                value = AnalysisStatus(value)
            data[key] = value
        rows.append(cls(**data))
    return tuple(rows)


def case_analysis_from_mapping(value: object) -> CaseAnalysisSnapshot:
    root = _exact(value, _ROOT_FIELDS, "CaseAnalysisSnapshot")
    if root["schema_version"] != "1.0.0":
        raise ValueError("unsupported schema version")
    workspace = root["workspace_id"]
    documents = tuple(CaseDocument(**{**row, "participant_refs": tuple(row["participant_refs"])}) for row in root["documents"])
    coverage = CaseAnalysisCoverage(**{**root["coverage"], "status": CoverageStatus(root["coverage"]["status"])})
    reviews = tuple(HumanReviewDecision(**row) for row in root["human_reviews"])
    snapshot = CaseAnalysisSnapshot(
        snapshot_id=root["snapshot_id"],
        workspace_id=workspace,
        source_revision=root["source_revision"],
        participant_refs=tuple(root["participant_refs"]),
        judicial_context_workspace_id=root["judicial_context_workspace_id"],
        judicial_context=procedural_context_from_mapping(root["judicial_context"]),
        documents=documents,
        claims=_items(root["claims"], CaseClaim, workspace),
        counterarguments=_items(root["counterarguments"], CounterArgument, workspace, {"target_claim_ids"}),
        decisions=_items(root["decisions"], JudicialDecision, workspace, {"addressed_claim_ids", "addressed_counterargument_ids"}),
        pericial_objects=_items(root["pericial_objects"], PericialObject, workspace),
        questions=_items(root["questions"], PericialQuestion, workspace, {"answer"}),
        events=_items(root["events"], ProceduralEvent, workspace, {"event_raw", "event_normalized", "timestamp", "normalization_authority"}),
        technical_document_references=_items(root["technical_document_references"], TechnicalDocumentReference, workspace, {"external_reference"}),
        gaps=_items(root["gaps"], EvidenceGap, workspace),
        conflicts=_items(root["conflicts"], DocumentConflict, workspace, {"statement_a_id", "statement_b_id", "conflict_dimension", "analysis_status", "human_review_status"}),
        coverage=coverage,
        human_reviews=reviews,
        source_inventory_stale=root["source_inventory_stale"],
        unindexed_source_count=root["unindexed_source_count"],
    )
    stale_ids = tuple(root["stale_document_ids"])
    known_ids = {document.document_id for document in snapshot.documents}
    if len(stale_ids) != len(set(stale_ids)) or not set(stale_ids) <= known_ids:
        raise ValueError("stale document identities are invalid")
    if not stale_ids:
        return snapshot

    def restore(items):
        return tuple(
            replace(item, stale=any(source.source_document_id in stale_ids for source in item.provenance))
            for item in items
        )

    return replace(
        snapshot,
        claims=restore(snapshot.claims),
        counterarguments=restore(snapshot.counterarguments),
        decisions=restore(snapshot.decisions),
        pericial_objects=restore(snapshot.pericial_objects),
        questions=restore(snapshot.questions),
        events=restore(snapshot.events),
        technical_document_references=restore(snapshot.technical_document_references),
        gaps=restore(snapshot.gaps),
        conflicts=restore(snapshot.conflicts),
        stale_document_ids=stale_ids,
    )


def query_analysis(snapshot: CaseAnalysisSnapshot, *, participant_ref: str | None = None, technical_subject: str | None = None) -> QueryResult:
    candidates = set(document.document_id for document in snapshot.documents)
    items = (
        *snapshot.claims,
        *snapshot.counterarguments,
        *snapshot.decisions,
        *snapshot.pericial_objects,
        *snapshot.questions,
        *snapshot.events,
        *snapshot.technical_document_references,
        *snapshot.gaps,
        *snapshot.conflicts,
    )
    if participant_ref is not None:
        candidates &= {document.document_id for document in snapshot.documents if participant_ref in document.participant_refs}
    if technical_subject is not None:
        needle = technical_subject.casefold()
        candidates &= {p.source_document_id for item in items if any(needle in subject.casefold() for subject in item.technical_subjects) for p in item.provenance}
    result = tuple(sorted(candidates))
    return QueryResult(result, len(result), len(snapshot.documents))
