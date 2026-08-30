"""Versioned ingress boundaries shared by product API consumers."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from .judicial_domain import (
    MAX_DOMAIN_COLLECTION_ITEMS,
    MAX_DOMAIN_TEXT_CHARS,
    ProceduralContext,
    procedural_context_from_mapping,
)


MAX_JUDICIAL_DOMAIN_PAYLOAD_BYTES = 1_048_576
MAX_JUDICIAL_DOMAIN_NODES = 10_000
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


def _require_bounded_json(value: object) -> None:
    pending = [value]
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > MAX_JUDICIAL_DOMAIN_NODES:
            raise ValueError("JSON graph exceeds limit")
        if type(item) is str and len(item) > MAX_DOMAIN_TEXT_CHARS:
            raise ValueError("JSON text exceeds limit")
        if type(item) is list:
            if len(item) > MAX_DOMAIN_COLLECTION_ITEMS:
                raise ValueError("JSON collection exceeds limit")
            pending.extend(item)
        elif type(item) is dict:
            pending.extend(item.values())


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
        _require_bounded_json(value)
        _VALIDATOR.validate(value)
        context = procedural_context_from_mapping(value)
    except (
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        RecursionError,
        ValueError,
        TypeError,
    ):
        pass
    else:
        return context
    # Raise after leaving the handler so no payload-bearing exception survives
    # as either __cause__ or __context__ on the public boundary error.
    raise JudicialDomainPayloadError("invalid judicial domain payload")
