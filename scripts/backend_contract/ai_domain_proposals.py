"""Strict source-grounded domain views over generic immutable AI proposals."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

import jsonschema

from .ai_gateway import AIProposal, SourceRevisionRef


class DomainProposalKind(StrEnum):
    CASE_ANALYSIS = "AI_CASE_ANALYSIS_PROPOSAL"
    PLANNING = "AI_PLANNING_PROPOSAL"
    EVIDENCE_TECHNICAL = "AI_EVIDENCE_PROPOSAL"
    TECHNICAL_FINDING = "AI_TECHNICAL_FINDING_PROPOSAL"
    REPORT_DRAFT = "AI_REPORT_DRAFT_PROPOSAL"


_ALLOWED_ITEM_TYPES = {
    DomainProposalKind.CASE_ANALYSIS: (
        "CLAIM",
        "COUNTERARGUMENT",
        "PROCEDURAL_EVENT_CANDIDATE",
        "DOCUMENT_CLASSIFICATION",
        "PERICIAL_OBJECT_CANDIDATE",
        "QUESTION_CANDIDATE",
        "EVIDENCE_GAP",
        "CONFLICT_CANDIDATE",
    ),
    DomainProposalKind.PLANNING: (
        "OBJECTIVE",
        "REQUIRED_DOCUMENT",
        "INSPECTION_REQUIREMENT",
        "MEASUREMENT_CANDIDATE",
        "PHOTO_REQUIREMENT",
        "EQUIPMENT_CANDIDATE",
        "METHOD_CANDIDATE",
        "RISK_GAP_CANDIDATE",
    ),
    DomainProposalKind.EVIDENCE_TECHNICAL: (
        "EVIDENCE_CLASSIFICATION",
        "EVIDENCE_RELATIONSHIP",
        "CONTRARY_EVIDENCE_CANDIDATE",
        "METHOD_CANDIDATE",
        "FINDING_PROPOSITION",
        "UNCERTAINTY_DESCRIPTION",
        "QUESTION_RELATIONSHIP",
    ),
    DomainProposalKind.TECHNICAL_FINDING: (
        "METHOD_CANDIDATE",
        "FINDING_PROPOSITION",
        "UNCERTAINTY_DESCRIPTION",
        "CONTRARY_EVIDENCE_CANDIDATE",
        "QUESTION_RELATIONSHIP",
    ),
    DomainProposalKind.REPORT_DRAFT: ("REPORT_SECTION_DRAFT",),
}

_FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "approved",
        "effective",
        "human_review_decision",
        "professional_decision",
        "planning_decision",
        "finalized",
        "delivered",
        "court_approval",
        "close_budget",
        "authority",
    }
)


def _source_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["workspace_id", "document_id", "revision_id", "sha256", "locator"],
        "properties": {
            "workspace_id": {"type": "string", "format": "uuid"},
            "document_id": {"type": "string", "minLength": 1},
            "revision_id": {"type": "string", "minLength": 1},
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "locator": {"type": "string", "minLength": 1},
        },
    }


def _source_payload(ref: SourceRevisionRef) -> dict[str, str]:
    return {
        "workspace_id": ref.workspace_id,
        "document_id": ref.document_id,
        "revision_id": ref.revision_id,
        "sha256": ref.sha256,
        "locator": ref.locator,
    }


def domain_proposal_schema(
    kind: DomainProposalKind,
    *,
    allowed_source_refs: tuple[SourceRevisionRef, ...] | None = None,
) -> dict[str, object]:
    if type(kind) is not DomainProposalKind:
        raise TypeError("domain proposal kind invalid")
    if allowed_source_refs is not None and (
        type(allowed_source_refs) is not tuple
        or not allowed_source_refs
        or any(type(item) is not SourceRevisionRef for item in allowed_source_refs)
    ):
        raise ValueError("allowed source refs invalid")
    source_items = (
        {"enum": [_source_payload(ref) for ref in allowed_source_refs]}
        if allowed_source_refs is not None
        else _source_schema()
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["item_type", "content", "source_refs"],
                    "properties": {
                        "item_type": {"type": "string", "enum": list(_ALLOWED_ITEM_TYPES[kind])},
                        "content": {"type": "string", "minLength": 1},
                        "source_refs": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "items": source_items,
                        },
                    },
                },
            }
        },
    }


@dataclass(frozen=True, slots=True)
class DomainProposalItem:
    item_type: str
    content: str
    source_refs: tuple[SourceRevisionRef, ...]

    def __post_init__(self) -> None:
        if type(self.item_type) is not str or not self.item_type:
            raise ValueError("domain proposal item type invalid")
        if type(self.content) is not str or not self.content.strip():
            raise ValueError("domain proposal content invalid")
        if type(self.source_refs) is not tuple or not self.source_refs or any(
            type(item) is not SourceRevisionRef for item in self.source_refs
        ):
            raise ValueError("domain proposal item must be source-grounded")


@dataclass(frozen=True, slots=True)
class DomainAIProposal:
    proposal_id: str
    workspace_id: str
    run_id: str
    kind: DomainProposalKind
    items: tuple[DomainProposalItem, ...]
    authority: str = "PROPOSAL_ONLY"

    def __post_init__(self) -> None:
        for value, field in (
            (self.proposal_id, "proposal_id"),
            (self.workspace_id, "workspace_id"),
            (self.run_id, "run_id"),
        ):
            try:
                parsed = UUID(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"domain AI proposal {field} invalid") from exc
            if str(parsed) != value:
                raise ValueError(f"domain AI proposal {field} invalid")
        if type(self.kind) is not DomainProposalKind:
            raise TypeError("domain proposal kind invalid")
        if type(self.items) is not tuple or not self.items or any(
            type(item) is not DomainProposalItem for item in self.items
        ):
            raise ValueError("domain AI proposal requires material items")
        if self.authority != "PROPOSAL_ONLY":
            raise ValueError("domain AI proposal must remain proposal-only")
        if any(ref.workspace_id != self.workspace_id for item in self.items for ref in item.source_refs):
            raise ValueError("domain AI proposal item workspace mismatch")


@dataclass(frozen=True, slots=True)
class ReportAuthorityContext:
    workspace_id: str
    case_analysis_reviewed: bool
    planning_professionally_reviewed_or_not_applicable: bool
    technical_findings_effective: bool
    professional_decisions_present: bool
    canonical_question_links_present: bool

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.workspace_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("report authority workspace invalid") from exc
        if str(parsed) != self.workspace_id:
            raise ValueError("report authority workspace invalid")
        if any(type(value) is not bool for value in (
            self.case_analysis_reviewed,
            self.planning_professionally_reviewed_or_not_applicable,
            self.technical_findings_effective,
            self.professional_decisions_present,
            self.canonical_question_links_present,
        )):
            raise TypeError("report authority flags must be boolean")

    @property
    def ready(self) -> bool:
        return all((
            self.case_analysis_reviewed,
            self.planning_professionally_reviewed_or_not_applicable,
            self.technical_findings_effective,
            self.professional_decisions_present,
            self.canonical_question_links_present,
        ))


def _normalized_key(value: str) -> str:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", snake.casefold()).strip("_")


def _reject_authority_fields(value: object) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if _normalized_key(key) in _FORBIDDEN_AUTHORITY_KEYS:
                raise ValueError("AI domain proposal contains authority field")
            _reject_authority_fields(item)
    elif type(value) is list:
        for item in value:
            _reject_authority_fields(item)


def _source_ref(raw: dict[str, object]) -> SourceRevisionRef:
    return SourceRevisionRef(
        workspace_id=raw["workspace_id"],
        document_id=raw["document_id"],
        revision_id=raw["revision_id"],
        sha256=raw["sha256"],
        locator=raw["locator"],
    )


def _thaw(value: object):
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


def validate_domain_proposal(
    proposal: AIProposal,
    kind: DomainProposalKind,
    *,
    report_authority: ReportAuthorityContext | None = None,
) -> DomainAIProposal:
    if type(proposal) is not AIProposal or type(kind) is not DomainProposalKind:
        raise TypeError("AI proposal and domain kind required")
    if proposal.task_type != kind.value:
        raise ValueError("AI proposal task type does not match domain kind")
    if kind is DomainProposalKind.REPORT_DRAFT:
        if (
            type(report_authority) is not ReportAuthorityContext
            or report_authority.workspace_id != proposal.workspace_id
            or not report_authority.ready
        ):
            raise ValueError("report upstream authority is incomplete")
    elif report_authority is not None:
        raise ValueError("report authority context is invalid for this task")
    if any(ref.workspace_id != proposal.workspace_id for ref in proposal.source_refs):
        raise ValueError("proposal source workspace mismatch")

    payload = _thaw(proposal.proposal_payload)
    _reject_authority_fields(payload)
    if type(payload) is not dict or not payload.get("items"):
        raise ValueError("material proposal requires at least one item")
    if type(payload["items"]) is list and any(
        type(item) is dict and item.get("source_refs") == [] for item in payload["items"]
    ):
        raise ValueError("material proposal must be source-grounded")
    try:
        jsonschema.Draft202012Validator(domain_proposal_schema(kind)).validate(payload)
    except jsonschema.ValidationError as exc:
        raise ValueError("invalid domain proposal schema") from exc

    allowed_sources = set(proposal.source_refs)
    items = []
    for raw in payload["items"]:
        refs = tuple(_source_ref(item) for item in raw["source_refs"])
        if not refs:
            raise ValueError("material proposal must be source-grounded")
        if any(ref.workspace_id != proposal.workspace_id for ref in refs):
            raise ValueError("domain proposal source workspace mismatch")
        if any(ref not in allowed_sources for ref in refs):
            raise ValueError("domain proposal cites unknown source")
        items.append(DomainProposalItem(raw["item_type"], raw["content"], refs))
    return DomainAIProposal(
        proposal_id=proposal.proposal_id,
        workspace_id=proposal.workspace_id,
        run_id=proposal.run_id,
        kind=kind,
        items=tuple(items),
    )
