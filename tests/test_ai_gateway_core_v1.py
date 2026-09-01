from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest

from scripts.backend_contract.ai_gateway import (
    AIContextSegment,
    AIModelProfile,
    AIProposal,
    AIRequest,
    AIResponse,
    AIRun,
    EgressClass,
    EgressDenied,
    EgressManifest,
    EgressPolicy,
    SourceRevisionRef,
    UsageRecord,
    context_manifest_sha256,
    context_manifest_payload,
    prompt_template_sha256,
    response_payload_sha256,
    structured_output_schema_sha256,
)
from scripts.backend_contract.ai_eval_productization import (
    AICostLimits,
    load_ai_eval_dataset,
)
from scripts.backend_contract.infrastructure.ai_cost_ledger import SQLiteAICostLedger
from scripts.backend_contract.application.ai_gateway import (
    AIExecutionFailed,
    AIProvider,
    AIProviderFailure,
    RunAIProposal,
)
from scripts.backend_contract.application.models import PericiaWorkspace, WorkspaceId
from scripts.backend_contract.application.ports import RepositoryConflict
from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore


WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"
SHA256 = "a" * 64
TASK_INSTRUCTIONS = "Proponha alegações estritamente apoiadas nas fontes."
SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {"type": "string"}}},
    "required": ["claims"],
    "additionalProperties": False,
}
SCHEMA_SHA256 = structured_output_schema_sha256(SCHEMA)
PROMPT_SHA256 = prompt_template_sha256("case-analysis-v1", TASK_INSTRUCTIONS)
CONTEXT_SHA256 = "d" * 64


def source_ref(*, workspace_id: str = WORKSPACE_ID) -> SourceRevisionRef:
    return SourceRevisionRef(
        workspace_id=workspace_id,
        document_id="document-1",
        revision_id="revision-1",
        sha256=SHA256,
        locator="page=1;segment=2",
    )


def manifest(
    *,
    egress_class: EgressClass = EgressClass.REMOTE_SANITIZED,
    contains_private_data: bool = False,
    explicitly_authorized: bool = False,
) -> EgressManifest:
    return EgressManifest(
        workspace_id=WORKSPACE_ID,
        egress_class=egress_class,
        source_refs=(source_ref(),),
        redaction_manifest=("cpf",) if egress_class is EgressClass.REMOTE_SANITIZED else (),
        contains_private_data=contains_private_data,
        explicitly_authorized=explicitly_authorized,
    )


def request(*, egress_manifest: EgressManifest | None = None) -> AIRequest:
    context = (AIContextSegment(source=source_ref(), content="Trecho sintético."),)
    return AIRequest(
        workspace_id=WORKSPACE_ID,
        task_type="CASE_ANALYSIS_PROPOSAL",
        task_instructions=TASK_INSTRUCTIONS,
        prompt_template_version="case-analysis-v1",
        prompt_template_hash=PROMPT_SHA256,
        structured_output_schema=SCHEMA,
        structured_output_schema_hash=SCHEMA_SHA256,
        context=context,
        context_manifest_hash=context_manifest_sha256(context),
        egress_manifest=egress_manifest or manifest(),
    )


def test_remote_egress_is_denied_by_default() -> None:
    with pytest.raises(EgressDenied, match="REMOTE_AI_EGRESS_DENIED"):
        EgressPolicy().authorize(request())


def test_remote_sanitized_requires_policy_enablement_and_exact_manifest() -> None:
    policy = EgressPolicy(remote_sanitized_enabled=True)

    assert policy.authorize(request()) is None

    mismatched = manifest()
    foreign_context = (AIContextSegment(source=source_ref(workspace_id=OTHER_WORKSPACE_ID), content="x"),)
    foreign_request = replace(
        request(),
        context=foreign_context,
        context_manifest_hash=context_manifest_sha256(foreign_context),
        egress_manifest=mismatched,
    )
    with pytest.raises(ValueError, match="workspace"):
        policy.authorize(foreign_request)


def test_private_remote_egress_requires_separate_explicit_authority() -> None:
    policy = EgressPolicy(remote_sanitized_enabled=True, remote_private_enabled=True)
    denied_manifest = manifest(
        egress_class=EgressClass.REMOTE_CASE_CONTENT_EXPLICITLY_AUTHORIZED,
        contains_private_data=True,
        explicitly_authorized=False,
    )

    with pytest.raises(EgressDenied, match="PRIVATE_EGRESS_NOT_AUTHORIZED"):
        policy.authorize(request(egress_manifest=denied_manifest))

    allowed_manifest = manifest(
        egress_class=EgressClass.REMOTE_CASE_CONTENT_EXPLICITLY_AUTHORIZED,
        contains_private_data=True,
        explicitly_authorized=True,
    )
    assert policy.authorize(request(egress_manifest=allowed_manifest)) is None


def test_contracts_validate_hashes_ids_and_are_deeply_immutable() -> None:
    item = request()
    assert isinstance(item.structured_output_schema, MappingProxyType)
    with pytest.raises(TypeError):
        item.structured_output_schema["type"] = "array"
    with pytest.raises(FrozenInstanceError):
        item.task_type = "REPORT_APPROVAL"
    with pytest.raises(ValueError, match="sha256"):
        SourceRevisionRef(
            workspace_id=WORKSPACE_ID,
            document_id="document-1",
            revision_id="revision-1",
            sha256="forged",
            locator="page=1",
        )

    with pytest.raises(ValueError, match="structured_output_schema_hash"):
        replace(item, structured_output_schema_hash="b" * 64)
    with pytest.raises(ValueError, match="context_manifest_hash"):
        replace(item, context_manifest_hash="d" * 64)
    with pytest.raises(ValueError, match="prompt_template_hash"):
        replace(item, prompt_template_hash="c" * 64)
    with pytest.raises(ValueError, match="UUID"):
        EgressManifest(
            workspace_id="not-a-uuid",
            egress_class=EgressClass.LOCAL_ONLY,
            source_refs=(),
            redaction_manifest=(),
            contains_private_data=False,
            explicitly_authorized=False,
        )


def test_model_profile_and_usage_have_explicit_cost_and_token_limits() -> None:
    profile = AIModelProfile(
        profile_id="FAST_EXTRACTION",
        provider="OPENAI",
        model="configured-model",
        max_input_tokens=4_000,
        max_output_tokens=800,
        cost_ceiling_microusd=25_000,
        timeout_seconds=30.0,
        structured_output_required=True,
        model_parameters={"temperature": 0},
    )
    usage = UsageRecord(
        input_tokens=100,
        cached_input_tokens=20,
        output_tokens=30,
        total_tokens=130,
        estimated_cost_microusd=500,
    )

    assert profile.model == "configured-model"
    assert usage.total_tokens == usage.input_tokens + usage.output_tokens
    with pytest.raises(ValueError, match="total_tokens"):
        UsageRecord(100, 20, 30, 999, 500)


def test_ai_proposal_and_run_ids_are_canonical_and_carry_no_authority_field() -> None:
    context = (AIContextSegment(source=source_ref(), content="Trecho sintético."),)
    context_manifest = context_manifest_payload(context)
    proposal = AIProposal(
        proposal_id="33333333-3333-4333-8333-333333333333",
        workspace_id=WORKSPACE_ID,
        task_type="CASE_ANALYSIS_PROPOSAL",
        source_refs=(source_ref(),),
        proposal_payload={"claims": ["Alegação sintética"]},
        provider="OPENAI",
        model="configured-model",
        run_id="44444444-4444-4444-8444-444444444444",
        created_at="2026-09-01T12:00:00+00:00",
        confidence_score=0.7,
    )
    run = AIRun(
        run_id=proposal.run_id,
        workspace_id=WORKSPACE_ID,
        task_type=proposal.task_type,
        provider="OPENAI",
        model="configured-model",
        model_parameters={"temperature": 0},
        prompt_template_version="case-analysis-v1",
        prompt_template_hash=PROMPT_SHA256,
        structured_output_schema_hash=SCHEMA_SHA256,
        context_manifest=context_manifest,
        context_manifest_hash=context_manifest_sha256(context),
        source_refs=(source_ref(),),
        egress_class=EgressClass.REMOTE_SANITIZED,
        redaction_manifest=("cpf",),
        usage=UsageRecord(100, 20, 30, 130, 500),
        latency_ms=25,
        provider_response_id="response-1",
        response_hash=SHA256,
        refusal_state="NONE",
        error_classification=None,
        proposal_ids=(proposal.proposal_id,),
        created_at=proposal.created_at,
        profile_id="FAST_EXTRACTION",
        cache_hit=False,
    )

    assert UUID(proposal.proposal_id).version == 4
    assert UUID(run.run_id).version == 4
    assert not hasattr(proposal, "approved")
    assert not hasattr(proposal, "effective")
    assert not hasattr(run, "professional_decision")


@pytest.mark.parametrize(
    "secret_field",
    [
        "api_key",
        "secret",
        "authorization",
        "bearer_token",
        "openai_api_key",
        "x_api_key",
        "access_token",
        "refresh_token",
        "client_secret",
        "secret_key",
        "aws_secret_access_key",
        "private_key",
        "session_token",
        "auth_token",
        "openaiApiKey",
        "xApiKey",
        "apiToken",
        "idToken",
        "jwtToken",
        "encryptionKey",
        "signingKey",
        "accessKeyId",
        "apiTokenValue",
        "idTokenValue",
        "jwtTokenValue",
        "encryptionKeyValue",
        "signingKeyPem",
        "accessKeyIdValue",
        "openaiApiKeyValue",
        "secretValue",
        "credentials",
        "passwords",
        "secrets",
        "apitokenvalue",
        "idtokenvalue",
        "jwttokenvalue",
        "encryptionkeyvalue",
        "signingkeypem",
        "accesskeyidvalue",
        "openaikeyvalue",
        "secretvalue",
        "credentialvalue",
        "passphrase",
        "clientassertion",
    ],
)
def test_ai_payload_rejects_secret_shaped_fields(secret_field: str) -> None:
    with pytest.raises(ValueError, match="secret"):
        AIProposal(
            proposal_id="33333333-3333-4333-8333-333333333333",
            workspace_id=WORKSPACE_ID,
            task_type="CASE_ANALYSIS_PROPOSAL",
            source_refs=(source_ref(),),
            proposal_payload={secret_field: "must-not-persist"},
            provider="OPENAI",
            model="configured-model",
            run_id="44444444-4444-4444-8444-444444444444",
            created_at="2026-09-01T12:00:00+00:00",
            confidence_score=None,
        )


def test_non_secret_key_and_token_semantics_remain_valid_output_fields() -> None:
    proposal = AIProposal(
        proposal_id="33333333-3333-4333-8333-333333333333",
        workspace_id=WORKSPACE_ID,
        task_type="CASE_ANALYSIS_PROPOSAL",
        source_refs=(source_ref(),),
        proposal_payload={
            "source_key": "source-1",
            "key_findings": 1,
            "token_count": 2,
            "inspection_session_id": "inspection-session-1",
            "session_identifier": "session-1",
            "session_id": "session-1",
        },
        provider="OPENAI",
        model="configured-model",
        run_id="44444444-4444-4444-8444-444444444444",
        created_at="2026-09-01T12:00:00+00:00",
        confidence_score=None,
    )

    assert proposal.proposal_payload["source_key"] == "source-1"
    assert proposal.proposal_payload["key_findings"] == 1
    assert proposal.proposal_payload["token_count"] == 2
    assert proposal.proposal_payload["inspection_session_id"] == "inspection-session-1"
    assert proposal.proposal_payload["session_identifier"] == "session-1"
    assert proposal.proposal_payload["session_id"] == "session-1"


@pytest.mark.parametrize("secret_name", ["api_key", "password", "clientAssertion"])
def test_name_value_secret_representation_is_rejected(secret_name: str) -> None:
    with pytest.raises(ValueError, match="secret"):
        AIProposal(
            proposal_id="33333333-3333-4333-8333-333333333333",
            workspace_id=WORKSPACE_ID,
            task_type="CASE_ANALYSIS_PROPOSAL",
            source_refs=(source_ref(),),
            proposal_payload={"parameters": [{"name": secret_name, "value": "must-not-persist"}]},
            provider="OPENAI",
            model="configured-model",
            run_id="44444444-4444-4444-8444-444444444444",
            created_at="2026-09-01T12:00:00+00:00",
            confidence_score=None,
        )


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class SequenceIds:
    def __init__(self, *values: str):
        self._values = iter(UUID(value) for value in values)

    def new_uuid(self) -> UUID:
        return next(self._values)


class WorkspaceRepo:
    def __init__(self):
        self.item = PericiaWorkspace(WorkspaceId.parse(WORKSPACE_ID), "Sintético", "2026-09-01T12:00:00+00:00")

    def get(self, workspace_id):
        return self.item if workspace_id == self.item.workspace_id else None


class RecordingRevisions:
    def __init__(self):
        self.appended = []
        self.pairs = []
        self.records = {}

    def append(self, **value):
        self.appended.append(value)
        return value

    def append_if_latest(self, **value):
        self.appended.append(value)
        self.records[(value["artifact_kind"], value["artifact_id"])] = value["payload"]
        return value

    def append_pair_if_latest(self, **value):
        self.pairs.append(value)
        for item in (value["first"], value["second"]):
            self.records[(item["artifact_kind"], item["artifact_id"])] = item["payload"]
        return value["first"], value["second"]

    def latest(self, _workspace_id, artifact_kind, artifact_id):
        payload = self.records.get((artifact_kind, artifact_id))
        return None if payload is None else SimpleNamespace(payload=payload)


class RecordingProvider(AIProvider):
    is_remote = True

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = []

    def execute(self, ai_request, profile):
        self.calls.append((ai_request, profile))
        if self.error is not None:
            raise self.error
        return self.result


def profile() -> AIModelProfile:
    return AIModelProfile(
        profile_id="FAST_EXTRACTION",
        provider="OPENAI",
        model="configured-model",
        max_input_tokens=4_000,
        max_output_tokens=800,
        cost_ceiling_microusd=25_000,
        timeout_seconds=30.0,
        structured_output_required=True,
        model_parameters={"temperature": 0},
    )


def _legacy_response_fixture(payload=None) -> AIResponse:
    response_payload = {"claims": ["Alegação sintética"]} if payload is None else payload
    return AIResponse(
        provider="OPENAI",
        model="configured-model",
        provider_response_id="response-1",
        payload={"claims": ["Alegação sintética"]} if payload is None else payload,
        response_hash=response_payload_sha256(response_payload),
        usage=UsageRecord(100, 20, 30, 130, 500),
        latency_ms=25,
        refusal_state="NONE",
    )


def response(payload=None) -> AIResponse:
    legacy = _legacy_response_fixture(payload)
    return replace(legacy, response_hash=response_payload_sha256(legacy.payload))


def ids(*, success: bool) -> SequenceIds:
    count = 8 if success else 4
    return SequenceIds(*(str(uuid4()) for _ in range(count)))


def generous_cost_ledger() -> SQLiteAICostLedger:
    path = Path(tempfile.gettempdir()) / f"ai-cost-test-{uuid4()}.sqlite3"
    return SQLiteAICostLedger(AICostLimits(100_000, 100_000, 1_000_000, 1_000_000), path)


def service(provider, revisions, *, policy=None, id_source=None, cost_ledger=None) -> RunAIProposal:
    return RunAIProposal(
        WorkspaceRepo(),
        revisions,
        provider,
        policy or EgressPolicy(remote_sanitized_enabled=True),
        FixedClock(),
        id_source or ids(success=True),
        cost_ledger or generous_cost_ledger(),
    )


def test_accumulated_cost_budget_fails_before_provider_execution() -> None:
    provider = RecordingProvider(result=response())
    revisions = RecordingRevisions()
    ledger = SQLiteAICostLedger(
        AICostLimits(10_000, 30_000, 20_000, 20_000),
        Path(tempfile.gettempdir()) / f"ai-cost-test-{uuid4()}.sqlite3",
    )

    with pytest.raises(AIExecutionFailed, match="COST_OR_TOKEN_BUDGET_EXCEEDED"):
        service(provider, revisions, cost_ledger=ledger).execute(request(), profile())

    assert provider.calls == []
    assert revisions.appended == []


def test_policy_denial_never_calls_provider_or_persists_run() -> None:
    provider = RecordingProvider(result=response())
    revisions = RecordingRevisions()
    use_case = service(provider, revisions, policy=EgressPolicy())

    with pytest.raises(EgressDenied):
        use_case.execute(request(), profile())

    assert provider.calls == []
    assert revisions.appended == []
    assert revisions.pairs == []


def test_local_only_request_never_calls_remote_provider() -> None:
    provider = RecordingProvider(result=response())
    revisions = RecordingRevisions()
    local_request = request(
        egress_manifest=replace(request().egress_manifest, egress_class=EgressClass.LOCAL_ONLY)
    )

    with pytest.raises(EgressDenied, match="LOCAL_ONLY_PROVIDER_MISMATCH"):
        service(provider, revisions, policy=EgressPolicy()).execute(local_request, profile())

    assert provider.calls == []
    assert revisions.appended == []


def test_valid_structured_response_persists_run_and_proposal_atomically() -> None:
    provider = RecordingProvider(result=response())
    revisions = RecordingRevisions()

    proposal = service(provider, revisions).execute(request(), profile())

    assert proposal.proposal_payload["claims"] == ("Alegação sintética",)
    assert len(provider.calls) == 1
    assert revisions.appended == []
    assert len(revisions.pairs) == 1
    pair = revisions.pairs[0]
    assert pair["first"]["artifact_kind"] == "AI_RUN"
    assert pair["second"]["artifact_kind"] == "AI_PROPOSAL"
    assert pair["first"]["payload"]["proposal_ids"] == [proposal.proposal_id]
    context_manifest = pair["first"]["payload"]["context_manifest"]
    assert context_manifest[0]["document_id"] == "document-1"
    assert context_manifest[0]["content_sha256"]
    assert "Trecho sintético." not in repr(context_manifest)
    assert "api_key" not in repr(pair).casefold()


def test_forged_provider_response_hash_is_audited_and_never_creates_proposal() -> None:
    provider = RecordingProvider(result=replace(response(), response_hash="0" * 64))
    revisions = RecordingRevisions()

    with pytest.raises(AIExecutionFailed, match="INVALID_RESPONSE_HASH"):
        service(provider, revisions, id_source=ids(success=False)).execute(request(), profile())

    assert revisions.pairs == []
    assert len(revisions.appended) == 1
    assert revisions.appended[0]["payload"]["error_classification"] == "INVALID_RESPONSE_HASH"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"claims": "not-an-array"}, "INVALID_STRUCTURED_OUTPUT"),
        ({"claims": [], "approved": True}, "INVALID_STRUCTURED_OUTPUT"),
    ],
)
def test_invalid_or_extra_provider_output_records_sanitized_failed_run(payload, code) -> None:
    provider = RecordingProvider(result=response(payload))
    revisions = RecordingRevisions()

    with pytest.raises(AIExecutionFailed, match=code):
        service(provider, revisions, id_source=ids(success=False)).execute(request(), profile())

    assert len(revisions.appended) == 1
    assert revisions.appended[0]["artifact_kind"] == "AI_RUN"
    assert revisions.appended[0]["payload"]["error_classification"] == code
    assert revisions.pairs == []


@pytest.mark.parametrize("provider_code", ["TIMEOUT", "INVALID_CREDENTIALS", "RATE_LIMIT"])
def test_provider_failures_record_one_sanitized_run(provider_code: str) -> None:
    provider = RecordingProvider(error=AIProviderFailure(provider_code, "sk-secret-must-not-leak", latency_ms=31))
    revisions = RecordingRevisions()

    with pytest.raises(AIExecutionFailed, match=provider_code) as caught:
        service(provider, revisions, id_source=ids(success=False)).execute(request(), profile())

    assert "secret" not in str(caught.value).casefold()
    assert len(revisions.appended) == 1
    persisted = revisions.appended[0]
    assert persisted["payload"]["error_classification"] == provider_code
    assert persisted["payload"]["latency_ms"] == 31
    assert "sk-secret" not in repr(persisted)


def test_persisted_provider_failure_enters_eval_as_hard_failure_observation() -> None:
    dataset = load_ai_eval_dataset(Path(__file__).parent / "fixtures" / "ai-eval-dataset-v1.json")
    case = dataset.cases[0]
    failed_request = replace(request(), task_type=case.task_type)
    revisions = RecordingRevisions()
    gateway = service(
        RecordingProvider(error=AIProviderFailure("TIMEOUT")), revisions,
        id_source=ids(success=False),
    )
    with pytest.raises(AIExecutionFailed, match="TIMEOUT") as caught:
        gateway.execute(failed_request, profile())

    observation = gateway.observe_persisted_failed_run(dataset.version, case, caught.value.run)
    assert observation.error_classification == "TIMEOUT"
    assert observation.schema_valid is False
    assert observation.proposal_id is None
    assert revisions.appended[-1]["artifact_kind"] == "AI_EVAL_OBSERVATION"
    assert revisions.appended[-1]["artifact_id"] == observation.attestation_sha256


def test_eval_observation_reopens_from_real_append_only_repository(tmp_path) -> None:
    path = tmp_path / "ai-eval-reopen.sqlite3"
    dataset = load_ai_eval_dataset(Path(__file__).parent / "fixtures" / "ai-eval-dataset-v1.json")
    case = dataset.cases[0]
    store = SQLiteApplicationStore(path)
    workspace = WorkspaceRepo().item
    store.workspaces.create(workspace)
    gateway = RunAIProposal(
        store.workspaces, store.revisions,
        RecordingProvider(error=AIProviderFailure("TIMEOUT")),
        EgressPolicy(remote_sanitized_enabled=True), FixedClock(),
        ids(success=False), generous_cost_ledger(),
    )
    with pytest.raises(AIExecutionFailed) as caught:
        gateway.execute(replace(request(), task_type=case.task_type), profile())
    observation = gateway.observe_persisted_failed_run(dataset.version, case, caught.value.run)
    store.close()

    reopened = SQLiteApplicationStore(path)
    try:
        record = reopened.revisions.latest(
            workspace.workspace_id, "AI_EVAL_OBSERVATION", observation.attestation_sha256
        )
        assert record is not None
        assert record.payload["attestation_sha256"] == observation.attestation_sha256
        assert len(reopened.revisions.list_all(
            workspace.workspace_id, "AI_EVAL_OBSERVATION", observation.attestation_sha256
        )) == 1
    finally:
        reopened.close()


def test_provider_refusal_records_failed_run_without_proposal() -> None:
    revisions = RecordingRevisions()

    with pytest.raises(AIExecutionFailed, match="PROVIDER_REFUSAL"):
        service(
            RecordingProvider(result=replace(response(), refusal_state="REFUSED")),
            revisions,
            id_source=ids(success=False),
        ).execute(request(), profile())

    assert revisions.pairs == []
    assert revisions.appended[0]["payload"]["refusal_state"] == "REFUSED"
    assert revisions.appended[0]["payload"]["error_classification"] == "PROVIDER_REFUSAL"


@pytest.mark.parametrize(
    ("usage", "code"),
    [
        (UsageRecord(4_001, 0, 30, 4_031, 500), "TOKEN_CEILING_EXCEEDED"),
        (UsageRecord(100, 0, 801, 901, 500), "TOKEN_CEILING_EXCEEDED"),
        (UsageRecord(100, 0, 30, 130, 25_001), "COST_CEILING_EXCEEDED"),
    ],
)
def test_usage_ceiling_violation_records_failed_run_without_proposal(usage, code) -> None:
    over_limit = replace(response(), usage=usage)
    revisions = RecordingRevisions()

    with pytest.raises(AIExecutionFailed, match=code):
        service(
            RecordingProvider(result=over_limit),
            revisions,
            id_source=ids(success=False),
        ).execute(request(), profile())

    assert revisions.pairs == []
    assert revisions.appended[0]["payload"]["error_classification"] == code


def test_workspace_mismatch_fails_before_provider_call() -> None:
    provider = RecordingProvider(result=response())
    revisions = RecordingRevisions()
    foreign = replace(request(), workspace_id=OTHER_WORKSPACE_ID)

    with pytest.raises(AIExecutionFailed, match="WORKSPACE_NOT_FOUND"):
        service(provider, revisions, id_source=ids(success=False)).execute(foreign, profile())

    assert provider.calls == []
    assert revisions.appended == []


def test_successful_run_reopens_from_real_append_only_repository(tmp_path) -> None:
    store = SQLiteApplicationStore(tmp_path / "ai-gateway.sqlite3")
    try:
        workspace = WorkspaceRepo().item
        store.workspaces.create(workspace)
        use_case = RunAIProposal(
            store.workspaces,
            store.revisions,
            RecordingProvider(result=response()),
            EgressPolicy(remote_sanitized_enabled=True),
            FixedClock(),
            ids(success=True),
            generous_cost_ledger(),
        )

        proposal, run = use_case.execute_with_run(request(), profile())
        use_case.verify_persisted(run, proposal)

        run_revision = store.revisions.latest(workspace.workspace_id, "AI_RUN", proposal.run_id)
        proposal_revision = store.revisions.latest(workspace.workspace_id, "AI_PROPOSAL", proposal.proposal_id)
        assert run_revision is not None
        assert proposal_revision is not None
        assert run_revision.payload["proposal_ids"] == (proposal.proposal_id,)
        assert "effective" not in proposal_revision.payload
    finally:
        store.close()


def test_ai_run_and_proposal_identity_cannot_be_rewritten(tmp_path) -> None:
    store = SQLiteApplicationStore(tmp_path / "ai-run-rewrite.sqlite3")
    fixed_values = tuple(str(uuid4()) for _ in range(4))
    try:
        workspace = WorkspaceRepo().item
        store.workspaces.create(workspace)
        first = RunAIProposal(
            store.workspaces,
            store.revisions,
            RecordingProvider(result=response()),
            EgressPolicy(remote_sanitized_enabled=True),
            FixedClock(),
            SequenceIds(*fixed_values),
            generous_cost_ledger(),
        )
        second = RunAIProposal(
            store.workspaces,
            store.revisions,
            RecordingProvider(result=response(payload={"claims": ["Outra"]})),
            EgressPolicy(remote_sanitized_enabled=True),
            FixedClock(),
            SequenceIds(*fixed_values),
            generous_cost_ledger(),
        )
        proposal = first.execute(request(), profile())

        with pytest.raises(RepositoryConflict, match="revisão processual desatualizada"):
            second.execute(request(), profile())

        history = store.revisions.list_all(workspace.workspace_id, "AI_RUN", proposal.run_id)
        assert len(history) == 1
        assert history[0].payload["proposal_ids"] == (proposal.proposal_id,)
    finally:
        store.close()


def test_failed_ai_run_identity_cannot_be_rewritten(tmp_path) -> None:
    store = SQLiteApplicationStore(tmp_path / "failed-ai-run-rewrite.sqlite3")
    run_id, first_revision_id, second_revision_id = (str(uuid4()) for _ in range(3))
    try:
        workspace = WorkspaceRepo().item
        store.workspaces.create(workspace)
        first = RunAIProposal(
            store.workspaces,
            store.revisions,
            RecordingProvider(error=AIProviderFailure("TIMEOUT")),
            EgressPolicy(remote_sanitized_enabled=True),
            FixedClock(),
            SequenceIds(run_id, first_revision_id),
            generous_cost_ledger(),
        )
        second = RunAIProposal(
            store.workspaces,
            store.revisions,
            RecordingProvider(error=AIProviderFailure("RATE_LIMIT")),
            EgressPolicy(remote_sanitized_enabled=True),
            FixedClock(),
            SequenceIds(run_id, second_revision_id),
            generous_cost_ledger(),
        )

        with pytest.raises(AIExecutionFailed, match="TIMEOUT"):
            first.execute(request(), profile())
        with pytest.raises(RepositoryConflict):
            second.execute(request(), profile())

        history = store.revisions.list_all(workspace.workspace_id, "AI_RUN", run_id)
        assert len(history) == 1
        assert history[0].payload["error_classification"] == "TIMEOUT"
    finally:
        store.close()
