"""Application orchestration for proposal-only domain AI tasks."""

from __future__ import annotations

from typing import Protocol

from ..ai_domain_proposals import (
    DomainAIProposal,
    DomainProposalKind,
    ReportAuthorityContext,
    domain_proposal_schema,
    validate_domain_proposal,
)
from ..ai_gateway import AIModelProfile, AIProposal, AIRequest, structured_output_schema_sha256


class AIProposalRunner(Protocol):
    def execute(self, request: AIRequest, profile: AIModelProfile) -> AIProposal: ...


class ReportAuthorityReader(Protocol):
    def get(self, workspace_id: str) -> ReportAuthorityContext | None: ...


class RunDomainAIProposal:
    def __init__(
        self,
        runner: AIProposalRunner,
        report_authority: ReportAuthorityReader | None = None,
    ):
        self._runner = runner
        self._report_authority = report_authority

    def execute(
        self,
        request: AIRequest,
        profile: AIModelProfile,
        kind: DomainProposalKind,
    ) -> DomainAIProposal:
        if request.task_type != kind.value:
            raise ValueError("AI request task type does not match domain kind")
        context_refs = tuple(segment.source for segment in request.context)
        if (
            request.egress_manifest.workspace_id != request.workspace_id
            or context_refs != request.egress_manifest.source_refs
            or any(ref.workspace_id != request.workspace_id for ref in context_refs)
        ):
            raise ValueError("domain AI request workspace/source manifest mismatch")
        expected_schema = domain_proposal_schema(
            kind,
            allowed_source_refs=request.egress_manifest.source_refs,
        )
        if request.structured_output_schema_hash != structured_output_schema_sha256(expected_schema):
            raise ValueError("AI request does not use the exact source-bound domain schema")

        authority = None
        if kind is DomainProposalKind.REPORT_DRAFT:
            if self._report_authority is None:
                raise ValueError("report upstream authority is unavailable")
            authority = self._report_authority.get(request.workspace_id)
            if (
                type(authority) is not ReportAuthorityContext
                or authority.workspace_id != request.workspace_id
                or not authority.ready
            ):
                raise ValueError("report upstream authority is incomplete")

        proposal = self._runner.execute(request, profile)
        if (
            type(proposal) is not AIProposal
            or proposal.workspace_id != request.workspace_id
            or proposal.task_type != request.task_type
            or proposal.source_refs != request.egress_manifest.source_refs
            or proposal.provider != profile.provider
            or proposal.model != profile.model
        ):
            raise ValueError("AI proposal runner result is not bound to request/profile")
        return validate_domain_proposal(proposal, kind, report_authority=authority)
