from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.backend_contract.ai_context_routing import (
    AIResultCache,
    AIResultCacheEntry,
    ContextBudgetExceeded,
    ContextCandidate,
    ContextPriority,
    ContextSelectionRequest,
    ModelRouteRequest,
    ModelRouter,
    RoutePolicy,
    ai_result_cache_key,
    select_context,
)
from scripts.backend_contract.application.ai_context_routing import BuildRoutedAIRequest, PrivacyProcessedContext
from scripts.backend_contract.ai_gateway import (
    AIContextSegment,
    AIModelProfile,
    EgressClass,
    EgressDenied,
    EgressManifest,
    EgressPolicy,
    SourceRevisionRef,
    context_manifest_sha256,
)
from tests.test_ai_gateway_core_v1 import request


WORKSPACE = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def candidate(
    name: str,
    priority: ContextPriority,
    tokens: int,
    relevance: int,
    *,
    workspace: str = WORKSPACE,
) -> ContextCandidate:
    ref = SourceRevisionRef(
        workspace_id=workspace,
        document_id=f"document-{name}",
        revision_id=f"revision-{name}",
        sha256=(name[0].encode().hex()[0] * 64),
        locator=f"page=1;segment={name}",
    )
    return ContextCandidate(
        segment=AIContextSegment(source=ref, content=(name + "x" * (tokens * 4))[: tokens * 4]),
        priority=priority,
        estimated_tokens=tokens,
        relevance_micros=relevance,
    )


def test_context_selection_is_deterministic_ranked_and_source_grounded() -> None:
    target = candidate("target", ContextPriority.EXPLICIT_TARGET, 20, 900)
    reviewed = candidate("reviewed", ContextPriority.REVIEWED_VALUE, 20, 500)
    evidence = candidate("evidence", ContextPriority.EXACT_EVIDENCE, 20, 800)
    supporting = candidate("support", ContextPriority.SUPPORTING, 20, 999)
    selection_request = ContextSelectionRequest(workspace_id=WORKSPACE, max_input_tokens=60)

    first = select_context((supporting, evidence, reviewed, target), selection_request)
    second = select_context((reviewed, target, supporting, evidence), selection_request)

    assert first == second
    assert tuple(item.source.document_id for item in first.segments) == (
        "document-target",
        "document-reviewed",
        "document-evidence",
    )
    assert first.total_estimated_tokens == 60
    assert first.source_refs == tuple(item.source for item in first.segments)


def test_context_selection_rejects_cross_workspace_and_duplicate_source_identity() -> None:
    valid = candidate("valid", ContextPriority.EXACT_EVIDENCE, 10, 1)
    foreign = candidate("foreign", ContextPriority.EXACT_EVIDENCE, 10, 1, workspace=OTHER)

    with pytest.raises(ValueError, match="workspace"):
        select_context((valid, foreign), ContextSelectionRequest(WORKSPACE, 100))
    with pytest.raises(ValueError, match="duplicate"):
        select_context((valid, valid), ContextSelectionRequest(WORKSPACE, 100))


def test_contrary_evidence_is_never_silently_dropped_by_budget() -> None:
    target = candidate("target", ContextPriority.EXPLICIT_TARGET, 30, 1)
    contrary = candidate("contrary", ContextPriority.CONTRARY_EVIDENCE, 30, 1)

    with pytest.raises(ContextBudgetExceeded, match="CONTRARY_EVIDENCE"):
        select_context((target, contrary), ContextSelectionRequest(WORKSPACE, 40))

    selection = select_context((target, contrary), ContextSelectionRequest(WORKSPACE, 60))
    assert {item.source.document_id for item in selection.segments} == {
        "document-target",
        "document-contrary",
    }


def test_source_grounded_selection_requires_an_explicit_target_match() -> None:
    with pytest.raises(ValueError, match="EXPLICIT_TARGET"):
        select_context((), ContextSelectionRequest(WORKSPACE, 100))
    with pytest.raises(ValueError, match="EXPLICIT_TARGET"):
        select_context(
            (candidate("evidence", ContextPriority.EXACT_EVIDENCE, 10, 1),),
            ContextSelectionRequest(WORKSPACE, 100),
        )


def profile(profile_id: str, cost: int, *, output: int = 800) -> AIModelProfile:
    return AIModelProfile(
        profile_id=profile_id,
        provider="OPENAI",
        model=f"model-{profile_id.casefold()}",
        max_input_tokens=4_000,
        max_output_tokens=output,
        cost_ceiling_microusd=cost,
        timeout_seconds=30,
        structured_output_required=True,
        model_parameters={"temperature": 0},
    )


def test_model_router_is_deterministic_auditable_and_selects_cheapest_eligible_profile() -> None:
    fast = profile("FAST", 1_000)
    deep = profile("DEEP", 10_000, output=2_000)
    router = ModelRouter(
        (deep, fast),
        (
            RoutePolicy("FAST", ("EXTRACTION",), max_risk=1, reasoning_level=1, max_context_tokens=1_000),
            RoutePolicy("DEEP", ("EXTRACTION", "ANALYSIS"), max_risk=3, reasoning_level=3, max_context_tokens=4_000),
        ),
    )

    decision = router.route(ModelRouteRequest("EXTRACTION", risk=1, reasoning_level=1, context_tokens=500))

    assert decision.profile == fast
    assert decision.policy_id == "FAST"
    assert decision.reason_codes == ("TASK", "RISK", "REASONING", "CONTEXT", "STRUCTURED_OUTPUT")
    assert router.route(ModelRouteRequest("ANALYSIS", 3, 3, 2_000)).profile == deep
    assert router.route(ModelRouteRequest("EXTRACTION", 1, 1, 500, max_cost_microusd=1_000)).profile == fast
    with pytest.raises(ValueError, match="NO_ELIGIBLE_MODEL_PROFILE"):
        router.route(ModelRouteRequest("ANALYSIS", 3, 3, 2_000, max_latency_seconds=10))
    with pytest.raises(ValueError, match="NO_ELIGIBLE_MODEL_PROFILE"):
        router.route(ModelRouteRequest("ANALYSIS", 3, 3, 5_000))


def test_cache_key_binds_workspace_profile_prompt_schema_context_and_parameters() -> None:
    ai_request = request()
    base_profile = profile("FAST", 1_000)
    key = ai_result_cache_key(ai_request, base_profile)

    assert key == ai_result_cache_key(ai_request, base_profile)
    foreign_context = tuple(
        replace(segment, source=replace(segment.source, workspace_id=OTHER))
        for segment in ai_request.context
    )
    foreign_manifest = EgressManifest(
        workspace_id=OTHER,
        egress_class=EgressClass.REMOTE_SANITIZED,
        source_refs=tuple(segment.source for segment in foreign_context),
        redaction_manifest=("cpf",),
        contains_private_data=False,
        explicitly_authorized=False,
    )
    mutations = (
        replace(
            ai_request,
            workspace_id=OTHER,
            egress_manifest=foreign_manifest,
            context=foreign_context,
            context_manifest_hash=context_manifest_sha256(foreign_context),
        ),
        replace(base_profile, model="other-model"),
        replace(base_profile, model_parameters={"temperature": 0, "top_p": 0.9}),
    )
    assert all(ai_result_cache_key(value, base_profile) != key for value in mutations[:1])
    assert all(ai_result_cache_key(ai_request, value) != key for value in mutations[1:])
    assert ai_result_cache_key(replace(ai_request, task_type="REPORT_PROPOSAL"), base_profile) != key
    assert ai_result_cache_key(
        replace(ai_request, egress_manifest=replace(ai_request.egress_manifest, egress_class=EgressClass.LOCAL_ONLY)),
        base_profile,
    ) != key
    profile_mutations = (
        replace(base_profile, max_input_tokens=3_999),
        replace(base_profile, max_output_tokens=799),
        replace(base_profile, cost_ceiling_microusd=999),
        replace(base_profile, timeout_seconds=29),
        replace(base_profile, structured_output_required=False),
    )
    assert all(ai_result_cache_key(ai_request, item) != key for item in profile_mutations)


class LocalRetriever:
    def __init__(self, candidates: tuple[ContextCandidate, ...]):
        self.candidates = candidates
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def retrieve(self, workspace_id: str, task_type: str, evidence_classes: tuple[str, ...]):
        self.calls.append((workspace_id, task_type, evidence_classes))
        return self.candidates


class SourceAuthority:
    def __init__(self, refs: tuple[SourceRevisionRef, ...]):
        self.refs = set(refs)

    def is_current(self, ref: SourceRevisionRef) -> bool:
        return ref in self.refs


class PrivacyAuthority:
    def classify_and_redact(self, workspace_id: str, segments: tuple[AIContextSegment, ...]):
        contains_private = any("CPF " in item.content for item in segments)
        return PrivacyProcessedContext(
            workspace_id=workspace_id,
            segments=segments,
            redaction_manifest=("CPF_PRESENT",) if contains_private else (),
            contains_private_data=contains_private,
        )


def test_application_builds_request_from_only_the_audited_local_selection() -> None:
    selected = candidate("target", ContextPriority.EXPLICIT_TARGET, 20, 900)
    omitted = candidate("support", ContextPriority.SUPPORTING, 80, 999)
    retriever = LocalRetriever((omitted, selected))

    routed = BuildRoutedAIRequest(
        retriever,
        SourceAuthority((selected.segment.source, omitted.segment.source)),
        PrivacyAuthority(),
    ).execute(
        request(),
        evidence_classes=("EXPLICIT_TARGET", "CONTRARY_EVIDENCE", "SUPPORTING"),
        max_input_tokens=20,
    )

    assert retriever.calls == [(
        WORKSPACE,
        "CASE_ANALYSIS_PROPOSAL",
        ("EXPLICIT_TARGET", "CONTRARY_EVIDENCE", "SUPPORTING"),
    )]
    assert routed.context == (selected.segment,)
    assert routed.context_manifest_hash == context_manifest_sha256(routed.context)
    assert routed.egress_manifest.source_refs == (selected.segment.source,)
    assert routed.egress_manifest.workspace_id == WORKSPACE


def test_application_fails_closed_when_retriever_returns_foreign_context() -> None:
    retriever = LocalRetriever((candidate("foreign", ContextPriority.EXACT_EVIDENCE, 10, 1, workspace=OTHER),))
    with pytest.raises(ValueError, match="workspace"):
        BuildRoutedAIRequest(retriever, SourceAuthority(()), PrivacyAuthority()).execute(
            request(),
            evidence_classes=("EXPLICIT_TARGET", "CONTRARY_EVIDENCE"),
            max_input_tokens=100,
        )


def test_application_requires_contrary_retrieval_and_current_source_authority() -> None:
    target = candidate("target", ContextPriority.EXPLICIT_TARGET, 10, 1)
    retriever = LocalRetriever((target,))
    builder = BuildRoutedAIRequest(retriever, SourceAuthority((target.segment.source,)), PrivacyAuthority())
    with pytest.raises(ValueError, match="CONTRARY_EVIDENCE"):
        builder.execute(request(), evidence_classes=("EXPLICIT_TARGET",), max_input_tokens=100)

    forged = replace(target, segment=replace(target.segment, source=replace(target.segment.source, sha256="f" * 64)))
    with pytest.raises(ValueError, match="current source"):
        BuildRoutedAIRequest(
            LocalRetriever((forged,)),
            SourceAuthority((target.segment.source,)),
            PrivacyAuthority(),
        ).execute(
            request(),
            evidence_classes=("EXPLICIT_TARGET", "CONTRARY_EVIDENCE"),
            max_input_tokens=100,
        )


def test_token_budget_is_derived_from_content_not_retriever_claim() -> None:
    segment = candidate("large", ContextPriority.EXPLICIT_TARGET, 1, 1).segment
    with pytest.raises(ValueError, match="estimated_tokens"):
        ContextCandidate(segment=replace(segment, content="x" * 1_000_000), priority=ContextPriority.EXPLICIT_TARGET, estimated_tokens=1, relevance_micros=1)


def test_routed_context_privacy_is_reclassified_and_old_authorization_is_cleared() -> None:
    private = candidate("private", ContextPriority.EXPLICIT_TARGET, 10, 1)
    private = replace(
        private,
        segment=replace(private.segment, content="CPF 123.456.789-00"),
        estimated_tokens=5,
    )
    base = request()
    stale_authorization = replace(
        base.egress_manifest,
        explicitly_authorized=True,
        redaction_manifest=("STALE",),
    )
    routed = BuildRoutedAIRequest(
        LocalRetriever((private,)),
        SourceAuthority((private.segment.source,)),
        PrivacyAuthority(),
    ).execute(
        replace(base, egress_manifest=stale_authorization),
        evidence_classes=("EXPLICIT_TARGET", "CONTRARY_EVIDENCE"),
        max_input_tokens=10,
    )

    assert routed.egress_manifest.contains_private_data is True
    assert routed.egress_manifest.redaction_manifest == ("CPF_PRESENT",)
    assert routed.egress_manifest.explicitly_authorized is False
    with pytest.raises(EgressDenied, match="REMOTE_SANITIZED_MANIFEST_INVALID"):
        EgressPolicy(remote_sanitized_enabled=True).authorize(routed)


def test_privacy_authority_cannot_change_source_identity_or_expand_past_budget() -> None:
    target = candidate("target", ContextPriority.EXPLICIT_TARGET, 10, 1)

    class BadPrivacyAuthority:
        def __init__(self, segment: AIContextSegment):
            self.segment = segment

        def classify_and_redact(self, workspace_id: str, segments: tuple[AIContextSegment, ...]):
            return PrivacyProcessedContext(workspace_id, (self.segment,), (), False)

    changed_source = replace(target.segment, source=replace(target.segment.source, revision_id="forged"))
    expanded = replace(target.segment, content="x" * 1_000)
    for processed, message in ((changed_source, "source identity"), (expanded, "token budget")):
        with pytest.raises(ValueError, match=message):
            BuildRoutedAIRequest(
                LocalRetriever((target,)),
                SourceAuthority((target.segment.source,)),
                BadPrivacyAuthority(processed),
            ).execute(
                request(),
                evidence_classes=("EXPLICIT_TARGET", "CONTRARY_EVIDENCE"),
                max_input_tokens=10,
            )


def test_local_result_cache_invalidates_stale_source_and_never_crosses_workspace() -> None:
    ai_request = request()
    item = AIResultCacheEntry.create(ai_request, profile("FAST", 1_000), {"proposal": "synthetic"})
    cache = AIResultCache()
    cache.put(item)
    current = ai_request.egress_manifest.source_refs

    assert cache.get(ai_request, profile("FAST", 1_000), current) == item
    with pytest.raises(TypeError):
        item.result["proposal"] = "mutated"
    stale = tuple(replace(ref, revision_id="changed-revision") for ref in current)
    assert cache.get(ai_request, profile("FAST", 1_000), stale) is None
    assert cache.get(ai_request, profile("FAST", 1_000), current + stale) is None

    with pytest.raises(ValueError, match="workspace"):
        replace(item, workspace_id=OTHER)
    foreign_ref = replace(item.source_refs[0], workspace_id=OTHER)
    with pytest.raises(ValueError, match="source workspace"):
        replace(item, source_refs=(foreign_ref,))


def test_router_rejects_duplicate_policy_identity() -> None:
    fast = profile("FAST", 1_000)
    policy = RoutePolicy("FAST", ("EXTRACTION",), 1, 1, 1_000)
    with pytest.raises(ValueError, match="duplicate route policy"):
        ModelRouter((fast,), (policy, policy))
