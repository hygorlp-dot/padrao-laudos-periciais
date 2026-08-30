"""Source-neutral, non-conclusive judicial case analysis contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum


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

    def __post_init__(self):
        if not all(type(value) is str and value.strip() for value in (self.workspace_id, self.source_document_id, self.page_or_span)):
            raise ValueError("provenance requires exact identity")
        if type(self.source_document_sha256) is not str or len(self.source_document_sha256) != 64:
            raise ValueError("provenance requires source SHA")
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise ValueError("provenance requires source revision")


@dataclass(frozen=True, slots=True)
class CaseDocument:
    document_id: str
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


@dataclass(frozen=True, slots=True)
class MaterialItem:
    item_id: str
    text: str
    participant_refs: tuple[str, ...]
    technical_subjects: tuple[str, ...]
    provenance: tuple[SourceProvenance, ...]
    stale: bool = False

    def __post_init__(self):
        if not self.provenance:
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

    def reconcile_sources(self, source_hashes: dict[str, str]):
        changed = tuple(sorted(document.document_id for document in self.documents if source_hashes.get(document.document_id) != document.source_sha256))
        if not changed:
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
    value.pop("stale_document_ids")
    value["schema_version"] = "1.0.0"
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


@dataclass(frozen=True, slots=True)
class SaveCaseAnalysis:
    append_revision: object
    get_latest_revision: object

    def execute(self, workspace_id, snapshot: CaseAnalysisSnapshot, expected_revision: int | None):
        if type(snapshot) is not CaseAnalysisSnapshot or str(workspace_id) != snapshot.workspace_id:
            raise ValueError("Case Analysis workspace identity mismatch")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision < 1):
            raise ValueError("expected revision is invalid")
        try:
            current = self.get_latest_revision.execute(workspace_id, CASE_ANALYSIS_ARTIFACT_KIND, CASE_ANALYSIS_ARTIFACT_ID)
        except Exception as exc:
            if exc.__class__.__name__ != "ArtifactRevisionNotFound":
                raise
            current = None
        current_revision = None if current is None else current.revision
        if current_revision != expected_revision:
            from .application.ports import RepositoryConflict

            raise RepositoryConflict("Case Analysis revision conflict")
        return self.append_revision.execute(
            workspace_id=workspace_id,
            artifact_kind=CASE_ANALYSIS_ARTIFACT_KIND,
            artifact_id=CASE_ANALYSIS_ARTIFACT_ID,
            payload=case_analysis_to_mapping(snapshot),
        )


@dataclass(frozen=True, slots=True)
class GetCaseAnalysis:
    get_latest_revision: object

    def execute(self, workspace_id):
        record = self.get_latest_revision.execute(workspace_id, CASE_ANALYSIS_ARTIFACT_KIND, CASE_ANALYSIS_ARTIFACT_ID)
        snapshot = case_analysis_from_mapping(_mutable_payload(record.payload))
        if snapshot.workspace_id != str(workspace_id):
            raise ValueError("persisted Case Analysis workspace mismatch")
        return record, snapshot


def _mutable_payload(value):
    from .application.models import thaw_payload

    return thaw_payload(value)


_ROOT_FIELDS = {
    "schema_version",
    "snapshot_id",
    "workspace_id",
    "source_revision",
    "participant_refs",
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
}


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"{label} requires exact fields")
    return value


def _prov(value, workspace_id):
    if type(value) is not list or not value:
        raise ValueError("provenance is required")
    result = tuple(SourceProvenance(**_exact(item, {"workspace_id", "source_document_id", "source_document_sha256", "page_or_span", "source_revision"}, "provenance")) for item in value)
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
    return CaseAnalysisSnapshot(
        snapshot_id=root["snapshot_id"],
        workspace_id=workspace,
        source_revision=root["source_revision"],
        participant_refs=tuple(root["participant_refs"]),
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
