import copy
import json
from pathlib import Path

import pytest

from scripts.backend_contract.api_contract import (
    JudicialDomainPayloadError,
    parse_judicial_domain_payload,
)


ROOT = Path(__file__).resolve().parents[1]


def _fixture():
    return json.loads((ROOT / "tests/fixtures/judicial-domain-model-v1.json").read_text(encoding="utf-8"))


def test_openapi_component_reuses_canonical_schema_and_declares_semantic_boundary():
    contract = json.loads((ROOT / "contracts/openapi-v1.json").read_text(encoding="utf-8"))

    assert contract["openapi"] == "3.1.0"
    assert contract["paths"] == {}
    component = contract["components"]["schemas"]["ProceduralContext"]
    assert component == {"$ref": "../schemas/judicial-domain-model-v1.schema.json"}
    assert contract["info"]["x-semantic-boundary"] == ("scripts.backend_contract.api_contract.parse_judicial_domain_payload")


def test_boundary_accepts_synthetic_canonical_payload():
    context = parse_judicial_domain_payload(json.dumps(_fixture(), ensure_ascii=False).encode("utf-8"))

    assert context.context_id == "CTX-001"
    assert len(context.participants) > 1


def test_boundary_rejects_structurally_valid_dangling_relation():
    payload = _fixture()
    payload["representation_links"][0]["represented_participant_ids"] = ["PART-MISSING"]

    with pytest.raises(JudicialDomainPayloadError, match="invalid judicial domain payload"):
        parse_judicial_domain_payload(json.dumps(payload).encode())


@pytest.mark.parametrize(
    "payload",
    (b"not-json", b"[]", b"{}", b"\xff", b'{"schema_version":NaN}'),
)
def test_boundary_fails_closed_with_sanitized_error(payload):
    with pytest.raises(JudicialDomainPayloadError) as caught:
        parse_judicial_domain_payload(payload)

    assert str(caught.value) == "invalid judicial domain payload"


def test_boundary_rejects_oversized_or_non_bytes_payload():
    with pytest.raises(JudicialDomainPayloadError):
        parse_judicial_domain_payload(b" " * 1_048_577)
    with pytest.raises(TypeError):
        parse_judicial_domain_payload(copy.deepcopy(_fixture()))


def test_boundary_rejects_duplicate_json_members():
    raw = json.dumps(_fixture(), ensure_ascii=False)
    ambiguous = raw.replace(
        '"schema_version": "1.0.0"',
        '"schema_version": "1.0.0", "schema_version": "1.0.0"',
        1,
    ).encode("utf-8")

    with pytest.raises(JudicialDomainPayloadError):
        parse_judicial_domain_payload(ambiguous)
