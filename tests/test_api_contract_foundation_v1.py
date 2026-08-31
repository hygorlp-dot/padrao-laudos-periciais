import copy
import json
import traceback
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from scripts.backend_contract.api_contract import (
    JudicialDomainPayloadError,
    parse_judicial_domain_payload,
)
from scripts.backend_contract.judicial_domain import procedural_context_from_mapping


ROOT = Path(__file__).resolve().parents[1]


def _fixture():
    return json.loads((ROOT / "tests/fixtures/judicial-domain-model-v1.json").read_text(encoding="utf-8"))


def test_openapi_component_reuses_canonical_schema_and_declares_semantic_boundary():
    contract = json.loads((ROOT / "contracts/openapi-v1.json").read_text(encoding="utf-8"))

    assert contract["openapi"] == "3.1.0"
    assert set(contract["paths"]) == {
        "/v1/workspaces/{workspace_id}/case-analysis",
        "/v1/workspaces/{workspace_id}/pericial-planning",
        "/v1/workspaces/{workspace_id}/pericial-planning/decisions",
        "/v1/workspaces/{workspace_id}/inspection-session",
            "/v1/workspaces/{workspace_id}/inspection-photos",
            "/v1/workspaces/{workspace_id}/offline-inspection",
            "/v1/workspaces/{workspace_id}/offline-sync",
        "/v1/workspaces/{workspace_id}/technical-snapshot",
        "/v1/workspaces/{workspace_id}/expert-profile",
        "/v1/workspaces/{workspace_id}/report-snapshot",
        "/v1/workspaces/{workspace_id}/report-snapshot/reviews",
        "/v1/workspaces/{workspace_id}/report-snapshot/draft-amendments",
        "/v1/workspaces/{workspace_id}/delivery-templates",
        "/v1/workspaces/{workspace_id}/delivery-supporting-files",
        "/v1/workspaces/{workspace_id}/delivery-snapshot",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/render",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/package-artifacts",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/reviews",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/finalize",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/deliver",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/reissue",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/history",
        "/v1/workspaces/{workspace_id}/delivery-snapshot/artifacts/{content_id}",
        "/v1/workspaces/{workspace_id}/budget-snapshot",
        "/v1/workspaces/{workspace_id}/budget-snapshot/history",
        "/v1/workspaces/{workspace_id}/budget-snapshot/proposals",
        "/v1/workspaces/{workspace_id}/budget-snapshot/court-approvals",
        "/v1/workspaces/{workspace_id}/budget-snapshot/expenses",
        "/v1/workspaces/{workspace_id}/budget-snapshot/payments",
        "/v1/workspaces/{workspace_id}/budget-snapshot/close",
    }
    component = contract["components"]["schemas"]["ProceduralContext"]
    assert component == {"$ref": "../schemas/judicial-domain-model-v1.schema.json"}
    assert contract["info"]["x-semantic-boundary"] == ("scripts.backend_contract.api_contract.parse_judicial_domain_payload")
    assert contract["info"]["x-delivery-snapshot-semantic-boundary"] == "scripts.backend_contract.delivery_foundation.delivery_snapshot_from_mapping"
    assert contract["components"]["schemas"]["DeliverySnapshot"] == {"$ref": "../schemas/delivery-snapshot-v1.schema.json"}
    assert contract["info"]["x-budget-snapshot-semantic-boundary"] == "scripts.backend_contract.budget_foundation.budget_snapshot_from_mapping"
    assert contract["components"]["schemas"]["BudgetSnapshot"] == {"$ref": "../schemas/budget-snapshot-v1.schema.json"}
    assert contract["info"]["x-offline-inspection-semantic-boundary"] == "scripts.backend_contract.field_mobile.offline_package_from_mapping"
    assert contract["components"]["schemas"]["OfflineInspectionPackage"] == {"$ref": "../schemas/offline-inspection-package-v1.schema.json"}
    assert "put" not in contract["paths"]["/v1/workspaces/{workspace_id}/budget-snapshot"]
    assert contract["components"]["schemas"]["RecordBudgetExpenseRequest"]["properties"]["category"]["$ref"].endswith("#/$defs/category")
    referenced = (ROOT / "contracts" / component["$ref"]).resolve()
    assert referenced.is_relative_to(ROOT)
    schema = json.loads(referenced.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_fixture())


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


def test_sanitized_error_discards_payload_bearing_exception_state():
    marker = "SYNTHETIC-PRIVATE-MARKER"
    payload = _fixture()
    payload["entities"][0]["unexpected_private_value"] = marker

    with pytest.raises(JudicialDomainPayloadError) as caught:
        parse_judicial_domain_payload(json.dumps(payload).encode("utf-8"))

    error = caught.value
    rendered = "".join(traceback.format_exception(error))
    assert error.__cause__ is None
    assert error.__context__ is None
    assert marker not in rendered


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(entities=[value["entities"][0]] * 513),
        lambda value: value["entities"][0].update(raw_name="x" * 4097),
        lambda value: value["entities"][0].update(provenance=value["entities"][0]["provenance"] * 513),
        lambda value: value["representation_links"][0].update(represented_participant_ids=[f"PART-{index:03d}" for index in range(513)]),
    ),
)
def test_boundary_rejects_over_budget_semantic_collections_before_schema_validation(monkeypatch, mutate):
    payload = _fixture()
    mutate(payload)
    schema_called = False

    def unexpected_schema_validation(_value):
        nonlocal schema_called
        schema_called = True

    monkeypatch.setattr(
        "scripts.backend_contract.api_contract._VALIDATOR",
        SimpleNamespace(validate=unexpected_schema_validation),
    )
    with pytest.raises(JudicialDomainPayloadError):
        parse_judicial_domain_payload(json.dumps(payload).encode("utf-8"))
    assert schema_called is False


def test_canonical_runtime_and_schema_share_text_and_collection_limits():
    oversized_text = _fixture()
    oversized_text["entities"][0]["raw_name"] = "x" * 4097
    with pytest.raises(ValueError):
        procedural_context_from_mapping(oversized_text)

    oversized_collection = _fixture()
    template = oversized_collection["entities"][0]
    oversized_collection["entities"] = []
    for index in range(513):
        entity = copy.deepcopy(template)
        entity["entity_id"] = f"ENT-{index:03d}"
        oversized_collection["entities"].append(entity)
    with pytest.raises((TypeError, ValueError)):
        procedural_context_from_mapping(oversized_collection)

    schema = json.loads((ROOT / "schemas/judicial-domain-model-v1.schema.json").read_text(encoding="utf-8"))
    oversized_identifier = _fixture()
    long_id = "A-" + ("A" * 4095)
    oversized_identifier["context_id"] = long_id
    for participant in oversized_identifier["participants"]:
        participant["context_id"] = long_id
    for access in oversized_identifier["access_relations"]:
        access["context_id"] = long_id
    assert list(Draft202012Validator(schema).iter_errors(oversized_identifier))
    with pytest.raises(ValueError):
        procedural_context_from_mapping(oversized_identifier)
