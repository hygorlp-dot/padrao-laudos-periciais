"""Adapter purpose-specific para OpenAI Responses; único import SDK do produto."""

from __future__ import annotations

import hashlib
import json
import os
import re
from time import monotonic

from openai import OpenAI

from ..ai_gateway import AIModelProfile, AIRequest, AIResponse, EgressPolicy, SYSTEM_AUTHORITY_CONTRACT, UsageRecord
from ..application.ai_gateway import AIProviderFailure
from ..application.models import thaw_payload


_ALLOWED_MODEL_PARAMETERS = frozenset({"temperature", "top_p", "reasoning", "service_tier"})
_ERROR_CODES = {
    "APITimeoutError": "TIMEOUT",
    "AuthenticationError": "INVALID_CREDENTIALS",
    "PermissionDeniedError": "INVALID_CREDENTIALS",
    "RateLimitError": "RATE_LIMIT",
    "APIConnectionError": "NETWORK",
}


def _error_code(exc: Exception) -> str:
    for error_type in type(exc).__mro__:
        code = _ERROR_CODES.get(error_type.__name__)
        if code is not None:
            return code
    return "PROVIDER_UNAVAILABLE"


def _schema_name(task_type: str) -> str:
    value = re.sub(r"[^a-z0-9_]+", "_", task_type.casefold()).strip("_")
    return value[:64] or "ai_proposal"


def _ref_payload(ref) -> dict[str, str]:
    return {
        "workspace_id": ref.workspace_id,
        "document_id": ref.document_id,
        "revision_id": ref.revision_id,
        "sha256": ref.sha256,
        "locator": ref.locator,
    }


def _provider_input(request: AIRequest) -> list[dict[str, object]]:
    expected_refs = tuple(segment.source for segment in request.context)
    if expected_refs != request.egress_manifest.source_refs:
        raise AIProviderFailure("CONTEXT_MANIFEST_MISMATCH")
    if any(ref.workspace_id != request.workspace_id for ref in expected_refs):
        raise AIProviderFailure("CROSS_WORKSPACE_AI_CONTEXT")
    blocks = []
    for segment in request.context:
        data = {"source": _ref_payload(segment.source), "content": segment.content}
        blocks.append(
            {
                "type": "input_text",
                "text": json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            }
        )
    return [{"role": "user", "content": blocks}]


def _refusal_state(response) -> str:
    for item in getattr(response, "output", ()) or ():
        for content in getattr(item, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                return "REFUSED"
    return "NONE"


def _usage(response) -> UsageRecord | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = int(getattr(usage, "input_tokens", 0))
    output_tokens = int(getattr(usage, "output_tokens", 0))
    details = getattr(usage, "input_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0)) if details is not None else 0
    return UsageRecord(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_microusd=None,
    )


def _reject_non_finite_json(value: str):
    raise ValueError(f"non-finite JSON constant denied: {value}")


class EnvironmentOpenAIClientFactory:
    """Cria o cliente sem persistir nem devolver a credencial local."""

    def create(self, *, timeout_seconds: float):
        api_key = os.environ.get("OPENAI_API_KEY")
        if type(api_key) is not str or not api_key.strip():
            raise AIProviderFailure("INVALID_CREDENTIALS")
        return OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=2)


class OpenAIProvider:
    is_remote = True

    def __init__(self, client, *, egress_policy: EgressPolicy | None = None, monotonic_clock=monotonic):
        if client is None or not hasattr(client, "responses"):
            raise TypeError("OpenAI client inválido")
        self._client = client
        self._egress_policy = egress_policy or EgressPolicy()
        self._monotonic = monotonic_clock

    def execute(self, request: AIRequest, profile: AIModelProfile) -> AIResponse:
        self._egress_policy.authorize(request)
        if profile.provider != "OPENAI":
            raise AIProviderFailure("PROVIDER_PROFILE_MISMATCH")
        if request.egress_manifest.egress_class.value == "LOCAL_ONLY":
            raise AIProviderFailure("LOCAL_ONLY_PROVIDER_MISMATCH")
        if not profile.structured_output_required:
            raise AIProviderFailure("STRUCTURED_OUTPUT_REQUIRED")
        parameters = thaw_payload(profile.model_parameters)
        if set(parameters) - _ALLOWED_MODEL_PARAMETERS:
            raise AIProviderFailure("MODEL_PARAMETERS_DENIED")
        started = self._monotonic()
        try:
            response = self._client.responses.create(
                model=profile.model,
                instructions=f"{SYSTEM_AUTHORITY_CONTRACT}\n\nTask instructions:\n{request.task_instructions}",
                input=_provider_input(request),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": _schema_name(request.task_type),
                        "strict": True,
                        "schema": thaw_payload(request.structured_output_schema),
                    }
                },
                max_output_tokens=profile.max_output_tokens,
                store=False,
                timeout=profile.timeout_seconds,
                **parameters,
            )
        except AIProviderFailure:
            raise
        except Exception as exc:
            latency_ms = max(0, round((self._monotonic() - started) * 1000))
            raise AIProviderFailure(_error_code(exc), latency_ms=latency_ms) from None
        latency_ms = max(0, round((self._monotonic() - started) * 1000))
        refusal_state = _refusal_state(response)
        if refusal_state != "NONE":
            payload = {}
        else:
            try:
                payload = json.loads(response.output_text, parse_constant=_reject_non_finite_json)
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                raise AIProviderFailure("INVALID_STRUCTURED_OUTPUT", latency_ms=latency_ms) from None
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return AIResponse(
            provider="OPENAI",
            model=response.model,
            provider_response_id=getattr(response, "id", None),
            payload=payload,
            response_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            usage=_usage(response),
            latency_ms=latency_ms,
            refusal_state=refusal_state,
        )
