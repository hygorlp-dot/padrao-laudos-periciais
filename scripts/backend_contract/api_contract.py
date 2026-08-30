"""Versioned ingress boundaries shared by product API consumers."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from .judicial_domain import ProceduralContext, procedural_context_from_mapping


MAX_JUDICIAL_DOMAIN_PAYLOAD_BYTES = 1_048_576
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "judicial-domain-model-v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA)


class JudicialDomainPayloadError(ValueError):
    """Sanitized public error for an invalid canonical-domain payload."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON member")
        value[key] = item
    return value


def parse_judicial_domain_payload(payload: bytes) -> ProceduralContext:
    """Decode and semantically validate a canonical judicial-domain payload.

    JSON Schema is deliberately only the structural stage. The canonical
    deserializer remains authoritative for graph identities and relations.
    """
    if type(payload) is not bytes:
        raise TypeError("payload must be bytes")
    if not payload or len(payload) > MAX_JUDICIAL_DOMAIN_PAYLOAD_BYTES:
        raise JudicialDomainPayloadError("invalid judicial domain payload")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        _VALIDATOR.validate(value)
        return procedural_context_from_mapping(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        RecursionError,
        ValueError,
        TypeError,
    ) as exc:
        raise JudicialDomainPayloadError("invalid judicial domain payload") from exc
