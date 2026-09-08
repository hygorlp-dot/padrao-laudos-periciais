"""Lossless product authority wrapper for construction-defect PAT results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from enum import StrEnum
import math
import re
from types import MappingProxyType


CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_KIND = "CONSTRUCTION_DEFECT_ANALYSIS_V1"
CONSTRUCTION_DEFECT_ANALYSIS_ARTIFACT_ID = "CONSTRUCTION-DEFECT-ANALYSIS"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PAT_ID = re.compile(r"PAT-[0-9]{3,}")


class ObservationOutcome(StrEnum):
    OBSERVED = "OBSERVED"
    NOT_OBSERVED = "NOT_OBSERVED"
    CONFORMING = "CONFORMING"
    INCONCLUSIVE = "INCONCLUSIVE"


class PathologyReviewAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class ConstructionDefectAnalysisProposal:
    observation_contexts: tuple[ObservationContext, ...]
    identity_links: tuple[CanonicalIdentityLink, ...]
    analysis_final: MappingProxyType
    gate: str

    def __post_init__(self) -> None:
        if not self.observation_contexts or not self.identity_links:
            raise ValueError("construction-defect proposal provenance is incomplete")
        if not isinstance(self.analysis_final, MappingProxyType):
            raise TypeError("construction-defect proposal must be immutable")
        if self.analysis_final.get("estado_analise") != "PAT_FINAL":
            raise ValueError("construction-defect proposal is not PAT_FINAL")
        if self.gate not in {
            "APTO_PARA_REDACAO",
            "APTO_PARA_REDACAO_COM_RESSALVAS",
            "BLOQUEADO_PARA_REDACAO",
        }:
            raise ValueError("construction-defect proposal gate is invalid")


def _text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _texts(value: tuple[str, ...], *, allow_empty: bool = True) -> None:
    if type(value) is not tuple or (not allow_empty and not value):
        raise ValueError("identity collection is invalid")
    if any(not _text(item) for item in value) or len(value) != len(set(value)):
        raise ValueError("identity collection is invalid")


def _timestamp(value: object) -> datetime:
    if not _text(value):
        raise ValueError("review timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("review timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("review timestamp requires timezone")
    return parsed


def freeze_json_payload(value: object, active: set[int] | None = None) -> object:
    active = set() if active is None else active
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("analysis JSON contains non-finite number")
        return value
    if type(value) not in {dict, list}:
        raise TypeError("analysis JSON is invalid")
    if id(value) in active:
        raise ValueError("analysis JSON cannot be cyclic")
    active.add(id(value))
    try:
        if type(value) is list:
            return tuple(freeze_json_payload(item, active) for item in value)
        if any(type(key) is not str for key in value):
            raise TypeError("analysis JSON keys must be text")
        return MappingProxyType(
            {key: freeze_json_payload(item, active) for key, item in value.items()}
        )
    finally:
        active.remove(id(value))


def thaw_json_payload(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {key: thaw_json_payload(item) for key, item in value.items()}
    if type(value) is tuple:
        return [thaw_json_payload(item) for item in value]
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise TypeError("analysis JSON contains unsupported value")


@dataclass(frozen=True, slots=True)
class ConstructionDefectSourceSnapshot:
    workspace_id: str
    process_case_revision: int
    process_case_digest: str
    case_analysis_snapshot_id: str
    case_analysis_revision: int
    case_analysis_digest: str
    planning_snapshot_id: str
    planning_revision: int
    planning_digest: str
    inspection_session_id: str
    inspection_revision: int
    inspection_digest: str
    source_revision: int

    def __post_init__(self) -> None:
        text_fields = (
            "workspace_id",
            "case_analysis_snapshot_id",
            "planning_snapshot_id",
            "inspection_session_id",
        )
        if any(not _text(getattr(self, name)) for name in text_fields):
            raise ValueError("construction-defect source identity is invalid")
        revisions = (
            self.process_case_revision,
            self.case_analysis_revision,
            self.planning_revision,
            self.inspection_revision,
            self.source_revision,
        )
        if any(type(value) is not int or value < 1 for value in revisions):
            raise ValueError("construction-defect source revision is invalid")
        digests = (
            self.process_case_digest,
            self.case_analysis_digest,
            self.planning_digest,
            self.inspection_digest,
        )
        if any(type(value) is not str or _SHA256.fullmatch(value) is None for value in digests):
            raise ValueError("construction-defect source digest is invalid")


@dataclass(frozen=True, slots=True)
class ObservationContext:
    observation_id: str
    manifestation: str
    system: str | None
    element: str | None
    outcome: ObservationOutcome
    methods: tuple[str, ...]
    measurement_ids: tuple[str, ...]
    photo_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    question_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _text(self.observation_id) or not _text(self.manifestation):
            raise ValueError("observation context identity and manifestation are required")
        if self.system is not None and not _text(self.system):
            raise ValueError("observation context system is invalid")
        if self.element is not None and not _text(self.element):
            raise ValueError("observation context element is invalid")
        if type(self.outcome) is not ObservationOutcome:
            raise TypeError("observation context outcome is invalid")
        _texts(self.methods, allow_empty=False)
        _texts(self.measurement_ids)
        _texts(self.photo_ids)
        _texts(self.claim_ids)
        _texts(self.question_ids)


@dataclass(frozen=True, slots=True)
class CanonicalIdentityLink:
    canonical_kind: str
    canonical_id: str
    legacy_kind: str
    legacy_id: str

    def __post_init__(self) -> None:
        if any(not _text(getattr(self, field.name)) for field in fields(self)):
            raise ValueError("canonical identity link is invalid")


@dataclass(frozen=True, slots=True)
class PathologyReview:
    review_id: str
    pat_id: str
    action: PathologyReviewAction
    professional_id: str
    reason: str
    reviewed_at: str
    supersedes_review_id: str | None

    def __post_init__(self) -> None:
        if any(
            not _text(value)
            for value in (
                self.review_id,
                self.pat_id,
                self.professional_id,
                self.reason,
            )
        ):
            raise ValueError("pathology review is invalid")
        if _PAT_ID.fullmatch(self.pat_id) is None:
            raise ValueError("pathology review target is invalid")
        if type(self.action) is not PathologyReviewAction:
            raise TypeError("pathology review action is invalid")
        _timestamp(self.reviewed_at)
        if self.supersedes_review_id is not None and not _text(self.supersedes_review_id):
            raise ValueError("pathology supersession identity is invalid")


@dataclass(frozen=True, slots=True)
class ConstructionDefectAnalysisSnapshot:
    schema_version: str
    snapshot_id: str
    workspace_id: str
    source_snapshot: ConstructionDefectSourceSnapshot
    observation_contexts: tuple[ObservationContext, ...]
    identity_links: tuple[CanonicalIdentityLink, ...]
    analysis_final: MappingProxyType
    gate: str
    reviews: tuple[PathologyReview, ...]
    upstream_stale: bool
    upstream_stale_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0" or not _text(self.snapshot_id) or not _text(self.workspace_id):
            raise ValueError("construction-defect snapshot identity is invalid")
        if self.source_snapshot.workspace_id != self.workspace_id:
            raise ValueError("construction-defect snapshot workspace mismatch")
        if type(self.observation_contexts) is not tuple or not self.observation_contexts:
            raise ValueError("construction-defect snapshot requires observation context")
        if type(self.identity_links) is not tuple or not self.identity_links:
            raise ValueError("construction-defect snapshot requires identity links")
        if type(self.analysis_final) is dict:
            object.__setattr__(
                self, "analysis_final", freeze_json_payload(self.analysis_final)
            )
        if not isinstance(self.analysis_final, MappingProxyType):
            raise TypeError("construction-defect analysis must be immutable JSON")
        if self.analysis_final.get("estado_analise") != "PAT_FINAL":
            raise ValueError("construction-defect analysis is not PAT_FINAL")
        if self.gate not in {
            "APTO_PARA_REDACAO",
            "APTO_PARA_REDACAO_COM_RESSALVAS",
            "BLOQUEADO_PARA_REDACAO",
        }:
            raise ValueError("construction-defect gate is invalid")
        _texts(self.upstream_stale_reasons)
        if type(self.upstream_stale) is not bool or self.upstream_stale != bool(self.upstream_stale_reasons):
            raise ValueError("construction-defect stale status is dishonest")
        self._validate_graph()

    def _validate_graph(self) -> None:
        contexts = [item.observation_id for item in self.observation_contexts]
        if len(contexts) != len(set(contexts)):
            raise ValueError("observation context identity is duplicated")
        canonical_keys = [(item.canonical_kind, item.canonical_id) for item in self.identity_links]
        legacy_keys = [(item.legacy_kind, item.legacy_id) for item in self.identity_links]
        if len(canonical_keys) != len(set(canonical_keys)) or len(legacy_keys) != len(set(legacy_keys)):
            raise ValueError("construction-defect identity mapping is ambiguous")
        link_by_canonical = {
            (item.canonical_kind, item.canonical_id): item
            for item in self.identity_links
        }
        required_links = {
            ("FIELD_OBSERVATION", context.observation_id): "OBSERVATION"
            for context in self.observation_contexts
        }
        required_links.update(
            {
                ("MEASUREMENT", item): "MEASUREMENT"
                for context in self.observation_contexts
                for item in context.measurement_ids
            }
        )
        required_links.update(
            {
                ("PHOTO_RECORD", item): "PHOTO"
                for context in self.observation_contexts
                for item in context.photo_ids
            }
        )
        required_links.update(
            {
                ("CASE_CLAIM", item): "ALLEGATION"
                for context in self.observation_contexts
                for item in context.claim_ids
            }
        )
        required_links.update(
            {
                ("CASE_QUESTION", item): "QUESTION"
                for context in self.observation_contexts
                for item in context.question_ids
            }
        )
        required_links.update(
            {
                ("TECHNICAL_QUESTION", item): "TECHNICAL_QUESTION"
                for context in self.observation_contexts
                for item in context.question_ids
            }
        )
        if any(
            (link := link_by_canonical.get(key)) is None
            or link.legacy_kind != legacy_kind
            for key, legacy_kind in required_links.items()
        ):
            raise ValueError("construction-defect canonical identity link is incomplete")
        pathologies = self.analysis_final.get("patologias")
        if type(pathologies) is not tuple:
            raise ValueError("PAT_FINAL pathology collection is invalid")
        pat_ids = tuple(
            item.get("id")
            for item in pathologies
            if isinstance(item, MappingProxyType)
        )
        if len(pat_ids) != len(pathologies) or any(
            type(item) is not str or _PAT_ID.fullmatch(item) is None for item in pat_ids
        ):
            raise ValueError("PAT_FINAL pathology identity is invalid")
        if len(pat_ids) != len(set(pat_ids)):
            raise ValueError("PAT_FINAL pathology identity is duplicated")
        linked_pat_ids = {
            item.canonical_id
            for item in self.identity_links
            if item.canonical_kind == "PATHOLOGY"
            and item.legacy_kind == "PATHOLOGY"
            and item.canonical_id == item.legacy_id
        }
        if set(pat_ids) != linked_pat_ids:
            raise ValueError("every PAT requires one lossless identity link")
        expected_prefixes = {
            "OBSERVATION": "OBS-",
            "MEASUREMENT": "MED-",
            "PHOTO": "FOT-",
            "ALLEGATION": "ALG-",
            "QUESTION": "QUE-",
            "TECHNICAL_QUESTION": "QT-",
        }
        for key, legacy_kind in required_links.items():
            link = link_by_canonical[key]
            if not link.legacy_id.startswith(expected_prefixes[legacy_kind]):
                raise ValueError("construction-defect legacy identity is invalid")
        legacy_by_kind = {
            kind: {
                item.legacy_id
                for item in self.identity_links
                if item.legacy_kind == kind
            }
            for kind in expected_prefixes
        }
        for pathology in pathologies:
            references = {
                "OBSERVATION": pathology.get("constatacoes", ()),
                "MEASUREMENT": pathology.get("medicoes", ()),
                "PHOTO": pathology.get("constatacao", {}).get("fotografias", ()),
                "ALLEGATION": pathology.get("alegacoes_relacionadas", ()),
            }
            if any(
                type(values) is not tuple
                or not set(values) <= legacy_by_kind[kind]
                for kind, values in references.items()
            ):
                raise ValueError("PAT_FINAL contains an unmapped legacy identity")
        embedded_gate = self.analysis_final.get("gate_redacao")
        if embedded_gate is not None and embedded_gate != self.gate:
            raise ValueError("construction-defect gate diverges from PAT_FINAL")
        review_by_id: dict[str, PathologyReview] = {}
        latest_by_pat: dict[str, PathologyReview] = {}
        for review in self.reviews:
            if review.review_id in review_by_id or review.pat_id not in pat_ids:
                raise ValueError("pathology review identity or target is invalid")
            previous = latest_by_pat.get(review.pat_id)
            if previous is None:
                if review.supersedes_review_id is not None:
                    raise ValueError("first pathology review cannot supersede another review")
            elif (
                review.supersedes_review_id != previous.review_id
                or _timestamp(review.reviewed_at) <= _timestamp(previous.reviewed_at)
            ):
                raise ValueError("pathology review history is not linear")
            review_by_id[review.review_id] = review
            latest_by_pat[review.pat_id] = review

    @property
    def effective_pat_ids(self) -> tuple[str, ...]:
        if self.upstream_stale or self.gate == "BLOQUEADO_PARA_REDACAO":
            return ()
        latest: dict[str, PathologyReview] = {}
        for review in self.reviews:
            latest[review.pat_id] = review
        return tuple(
            sorted(
                pat_id
                for pat_id, review in latest.items()
                if review.action is PathologyReviewAction.APPROVE
            )
        )


_SNAPSHOT_FIELDS = {field.name for field in fields(ConstructionDefectAnalysisSnapshot)}
_SOURCE_FIELDS = {field.name for field in fields(ConstructionDefectSourceSnapshot)}
_CONTEXT_FIELDS = {field.name for field in fields(ObservationContext)}
_LINK_FIELDS = {field.name for field in fields(CanonicalIdentityLink)}
_REVIEW_FIELDS = {field.name for field in fields(PathologyReview)}


def _object(value: object, expected: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} fields are invalid")
    return value


def _array(value: object, name: str) -> list[object]:
    if type(value) is not list:
        raise ValueError(f"{name} must be an array")
    return value


def observation_context_from_mapping(value: object) -> ObservationContext:
    row = _object(value, _CONTEXT_FIELDS, "observation context")
    return ObservationContext(
        **{
            **row,
            "outcome": ObservationOutcome(row["outcome"]),
            "methods": tuple(_array(row["methods"], "observation methods")),
            "measurement_ids": tuple(
                _array(row["measurement_ids"], "observation measurements")
            ),
            "photo_ids": tuple(_array(row["photo_ids"], "observation photos")),
            "claim_ids": tuple(_array(row["claim_ids"], "observation claims")),
            "question_ids": tuple(
                _array(row["question_ids"], "observation questions")
            ),
        }
    )


def construction_defect_analysis_from_mapping(value: object) -> ConstructionDefectAnalysisSnapshot:
    root = _object(value, _SNAPSHOT_FIELDS, "construction-defect snapshot")
    source = ConstructionDefectSourceSnapshot(
        **_object(root["source_snapshot"], _SOURCE_FIELDS, "construction-defect source")
    )
    contexts = tuple(
        observation_context_from_mapping(item)
        for item in _array(root["observation_contexts"], "observation contexts")
    )
    links = tuple(
        CanonicalIdentityLink(**_object(item, _LINK_FIELDS, "canonical identity link"))
        for item in _array(root["identity_links"], "identity links")
    )
    reviews = tuple(
        PathologyReview(
            **{
                **row,
                "action": PathologyReviewAction(row["action"]),
            }
        )
        for item in _array(root["reviews"], "pathology reviews")
        for row in [_object(item, _REVIEW_FIELDS, "pathology review")]
    )
    analysis = root["analysis_final"]
    if type(analysis) is not dict:
        raise ValueError("analysis_final must be an object")
    return ConstructionDefectAnalysisSnapshot(
        schema_version=root["schema_version"],
        snapshot_id=root["snapshot_id"],
        workspace_id=root["workspace_id"],
        source_snapshot=source,
        observation_contexts=contexts,
        identity_links=links,
        analysis_final=freeze_json_payload(analysis),
        gate=root["gate"],
        reviews=reviews,
        upstream_stale=root["upstream_stale"],
        upstream_stale_reasons=tuple(
            _array(root["upstream_stale_reasons"], "stale reasons")
        ),
    )


def construction_defect_analysis_to_mapping(
    value: ConstructionDefectAnalysisSnapshot,
) -> dict[str, object]:
    if type(value) is not ConstructionDefectAnalysisSnapshot:
        raise TypeError("construction-defect snapshot is invalid")
    return {
        "schema_version": value.schema_version,
        "snapshot_id": value.snapshot_id,
        "workspace_id": value.workspace_id,
        "source_snapshot": asdict(value.source_snapshot),
        "observation_contexts": [
            {
                **asdict(item),
                "outcome": item.outcome.value,
                "methods": list(item.methods),
                "measurement_ids": list(item.measurement_ids),
                "photo_ids": list(item.photo_ids),
                "claim_ids": list(item.claim_ids),
                "question_ids": list(item.question_ids),
            }
            for item in value.observation_contexts
        ],
        "identity_links": [asdict(item) for item in value.identity_links],
        "analysis_final": thaw_json_payload(value.analysis_final),
        "gate": value.gate,
        "reviews": [
            {**asdict(item), "action": item.action.value} for item in value.reviews
        ],
        "upstream_stale": value.upstream_stale,
        "upstream_stale_reasons": list(value.upstream_stale_reasons),
    }
