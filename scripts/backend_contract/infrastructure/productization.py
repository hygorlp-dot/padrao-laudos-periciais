"""Versioned workspace portability without rewriting active case storage."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5
from weakref import WeakKeyDictionary

from ..application.models import (
    ArtifactRevision,
    PericiaWorkspace,
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    ProcessCaseData,
    WorkspaceId,
    canonical_payload_json,
    thaw_payload,
)
from ..application.ports import RepositoryConflict, RepositoryIntegrityError
from ..application.artifact_ownership import (
    INTERNAL_ARTIFACT_KINDS,
    PORTABLE_PRODUCT_ARTIFACT_KINDS,
    USER_DEFINED_ARTIFACT_KINDS,
)
from ..application.ocr_cache import _page_from_payload
from ..application.process_metadata import document_metadata_from_payload
from ..application.services import validate_pje_intake_payload
from ..budget_foundation import budget_snapshot_from_mapping
from ..ai_gateway import AIRun, AIProposal, EgressClass, SourceRevisionRef, UsageRecord
from ..ai_eval_productization import (
    AICostLimits,
    AIEvalTelemetry,
    HumanEvalOutcome,
    ai_eval_dataset_from_mapping,
    ai_eval_observation_from_mapping,
    ai_eval_report_from_mapping,
    evaluate_ai_dataset,
    observe_domain_proposal,
    observe_failed_run,
)
from ..ai_domain_proposals import DomainProposalKind, validate_domain_proposal
from ..case_analysis import case_analysis_from_mapping
from ..delivery_foundation import delivery_snapshot_from_mapping
from ..delivery_renderer import validate_delivery_artifact, validate_final_artifact, validate_supporting_artifact
from ..pericial_planning import pericial_planning_from_mapping
from ..report_foundation import expert_profile_from_mapping, report_snapshot_from_mapping
from ..technical_findings import technical_snapshot_from_mapping
from ..vistoria import inspection_session_from_mapping
from .private_filesystem import LocalPrivateContentStore
from .ai_cost_ledger import AI_COST_LEDGER_FILENAME, SQLiteAICostLedger
from .sqlite import SQLiteApplicationStore

import base64


BACKUP_PORTABILITY_RELEASE = "0.11.0"
# Serialized backup compatibility is a portability contract generation, not
# the independently versioned application release.
PRODUCT_RELEASE_VERSION = BACKUP_PORTABILITY_RELEASE
STORAGE_FORMAT_VERSION = 1
SUPPORTED_BACKUP_VERSIONS = frozenset({0, 1})
SUPPORTED_BACKUP_PORTABILITY_RELEASES = frozenset({"0.10.0", "0.11.0"})
SUPPORTED_PRODUCT_RELEASES = SUPPORTED_BACKUP_PORTABILITY_RELEASES
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OPEN_BINARY = 0x8000 if os.name == "nt" else 0


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ValueError("backup payload is not canonical JSON") from exc


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: object, expected: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected:
        raise ValueError(f"{name} fields are invalid")
    return dict(value)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value


def _instant(value: object, name: str) -> str:
    result = _text(value, name)
    parsed = datetime.fromisoformat(result)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} requires timezone")
    return result


@dataclass(frozen=True, slots=True)
class BackupWorkspace:
    workspace_id: str
    name: str
    created_at: str

    def __post_init__(self) -> None:
        if str(UUID(self.workspace_id)) != self.workspace_id:
            raise ValueError("workspace_id is invalid")
        _text(self.name, "workspace name")
        _instant(self.created_at, "workspace created_at")


@dataclass(frozen=True, slots=True)
class WorkspaceBackup:
    schema_version: str
    format_version: int
    product_release: str
    storage_schema_version: int
    workspace: BackupWorkspace
    artifact_revisions: tuple[dict[str, Any], ...]
    private_contents: tuple[dict[str, Any], ...]
    member_hashes: dict[str, str]
    manifest_sha256: str
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("backup schema version is unsupported")
        if self.format_version != STORAGE_FORMAT_VERSION:
            raise ValueError("backup format version is unsupported")
        _text(self.product_release, "product release")
        if type(self.storage_schema_version) is not int or self.storage_schema_version < 1:
            raise ValueError("storage schema version is invalid")
        if type(self.workspace) is not BackupWorkspace or type(self.artifact_revisions) is not tuple or type(self.private_contents) is not tuple:
            raise ValueError("backup collections are invalid")
        if type(self.member_hashes) is not dict or any(type(key) is not str or _SHA256.fullmatch(value) is None for key, value in self.member_hashes.items()):
            raise ValueError("backup member hashes are invalid")
        if _SHA256.fullmatch(self.manifest_sha256) is None:
            raise ValueError("backup manifest hash is invalid")
        _instant(self.created_at, "backup created_at")


def migrate_backup_mapping(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError("backup version is invalid")
    result = deepcopy(value)
    version = result.get("format_version")
    if type(version) is not int or version not in SUPPORTED_BACKUP_VERSIONS:
        raise ValueError("backup version is unsupported")
    if version == 0:
        result["schema_version"] = "1.0.0"
        result["format_version"] = 1
        result["member_hashes"] = {
            "artifact_revisions": _hash(result.get("artifact_revisions")),
            "private_contents": _hash(result.get("private_contents")),
        }
        result["manifest_sha256"] = _hash({key: item for key, item in result.items() if key != "manifest_sha256"})
    return result


def workspace_backup_from_mapping(value: object) -> WorkspaceBackup:
    data = _exact(
        value,
        {"schema_version", "format_version", "product_release", "storage_schema_version", "workspace", "artifact_revisions", "private_contents", "member_hashes", "manifest_sha256", "created_at"},
        "WorkspaceBackup",
    )
    workspace = _exact(data["workspace"], {"workspace_id", "name", "created_at"}, "BackupWorkspace")
    if type(data["artifact_revisions"]) is not list or type(data["private_contents"]) is not list:
        raise ValueError("backup collections are invalid")
    data["workspace"] = BackupWorkspace(**workspace)
    data["artifact_revisions"] = tuple(deepcopy(data["artifact_revisions"]))
    data["private_contents"] = tuple(deepcopy(data["private_contents"]))
    return WorkspaceBackup(**data)


def workspace_backup_to_mapping(value: WorkspaceBackup) -> dict[str, Any]:
    if type(value) is not WorkspaceBackup:
        raise TypeError("WorkspaceBackup is required")
    result = asdict(value)
    result["artifact_revisions"] = list(result["artifact_revisions"])
    result["private_contents"] = list(result["private_contents"])
    return result


@dataclass(frozen=True, slots=True)
class _ValidatedAIArtifact:
    workspace_id: str


def _validate_ai_envelope(value: object, kind: str) -> _ValidatedAIArtifact:
    fields = {
        "AI_RUN": {
            "run_id", "workspace_id", "task_type", "provider", "model", "model_parameters",
            "prompt_template_version", "prompt_template_hash", "structured_output_schema_hash",
            "context_manifest", "context_manifest_hash", "source_refs", "egress_class",
            "redaction_manifest", "usage", "latency_ms", "provider_response_id", "response_hash",
            "refusal_state", "error_classification", "proposal_ids", "created_at", "profile_id",
            "cache_hit",
        },
        "AI_PROPOSAL": {
            "proposal_id", "workspace_id", "task_type", "source_refs", "proposal_payload",
            "provider", "model", "run_id", "created_at", "confidence_score",
        },
    }[kind]
    data = _exact(value, fields, kind)
    workspace_id = str(WorkspaceId.parse(data["workspace_id"]))
    source_refs = data["source_refs"]
    if type(source_refs) not in {list, tuple} or not source_refs or any(
        type(ref) is not dict
        or set(ref) != {"workspace_id", "document_id", "revision_id", "sha256", "locator"}
        or ref["workspace_id"] != workspace_id
        or _SHA256.fullmatch(ref["sha256"]) is None
        for ref in source_refs
    ):
        raise RepositoryIntegrityError("AI artifact source provenance is invalid")
    try:
        canonical_refs = tuple(SourceRevisionRef(**ref) for ref in source_refs)
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("AI artifact source provenance is invalid") from exc
    if any(ref.workspace_id != workspace_id for ref in canonical_refs):
        raise RepositoryIntegrityError("AI artifact source provenance is invalid")
    canonical_payload_json(data)
    try:
        if kind == "AI_RUN":
            usage = data["usage"]
            if (
                type(data["redaction_manifest"]) not in {list, tuple}
                or any(type(item) is not str or not item for item in data["redaction_manifest"])
                or type(data["proposal_ids"]) not in {list, tuple}
            ):
                raise ValueError("AI run immutable collections invalid")
            for proposal_id in data["proposal_ids"]:
                UUID(proposal_id)
            parsed = AIRun(
                run_id=data["run_id"], workspace_id=workspace_id, task_type=data["task_type"],
                provider=data["provider"], model=data["model"], model_parameters=data["model_parameters"],
                prompt_template_version=data["prompt_template_version"],
                prompt_template_hash=data["prompt_template_hash"],
                structured_output_schema_hash=data["structured_output_schema_hash"],
                context_manifest=data["context_manifest"], context_manifest_hash=data["context_manifest_hash"],
                source_refs=canonical_refs, egress_class=EgressClass(data["egress_class"]),
                redaction_manifest=tuple(data["redaction_manifest"]),
                usage=None if usage is None else UsageRecord(**usage), latency_ms=data["latency_ms"],
                provider_response_id=data["provider_response_id"], response_hash=data["response_hash"],
                refusal_state=data["refusal_state"], error_classification=data["error_classification"],
                proposal_ids=tuple(data["proposal_ids"]), created_at=data["created_at"],
                profile_id=data["profile_id"], cache_hit=data["cache_hit"],
            )
            if (
                (parsed.error_classification is None and parsed.refusal_state == "NONE" and not parsed.proposal_ids)
                or (parsed.error_classification is not None and parsed.proposal_ids)
            ):
                raise ValueError("AI run outcome cardinality invalid")
            context_manifest = data["context_manifest"]
            context_fields = {
                "workspace_id", "document_id", "revision_id", "source_sha256",
                "locator", "content_sha256",
            }
            if (
                type(context_manifest) not in {list, tuple}
                or len(context_manifest) != len(canonical_refs)
                or any(
                    type(item) is not dict
                    or set(item) != context_fields
                    or _SHA256.fullmatch(item["source_sha256"]) is None
                    or _SHA256.fullmatch(item["content_sha256"]) is None
                    for item in context_manifest
                )
            ):
                raise ValueError("AI run context manifest shape invalid")
            context_sources = tuple(
                (
                    item.get("workspace_id"), item.get("document_id"), item.get("revision_id"),
                    item.get("source_sha256"), item.get("locator"),
                )
                for item in context_manifest
            )
            declared_sources = tuple(
                (ref.workspace_id, ref.document_id, ref.revision_id, ref.sha256, ref.locator)
                for ref in canonical_refs
            )
            if context_sources != declared_sources:
                raise ValueError("AI run context/source provenance diverges")
        else:
            parsed = AIProposal(
                proposal_id=data["proposal_id"], workspace_id=workspace_id,
                task_type=data["task_type"], source_refs=canonical_refs,
                proposal_payload=data["proposal_payload"], provider=data["provider"],
                model=data["model"], run_id=data["run_id"], created_at=data["created_at"],
                confidence_score=data["confidence_score"],
            )
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("AI artifact domain invariants are invalid") from exc
    return parsed


_ARTIFACT_VALIDATORS = {
    "BUDGET_SNAPSHOT_V1": budget_snapshot_from_mapping,
    "CASE_ANALYSIS_SNAPSHOT_V1": case_analysis_from_mapping,
    "DELIVERY_SNAPSHOT_V1": delivery_snapshot_from_mapping,
    "EXPERT_MASTER_PROFILE_V1": expert_profile_from_mapping,
    "INSPECTION_SESSION_V1": inspection_session_from_mapping,
    "PERICIAL_PLANNING_SNAPSHOT_V1": pericial_planning_from_mapping,
    "PJE_INTAKE_V1": validate_pje_intake_payload,
    "PROCESS_CASE": ProcessCaseData.from_mapping,
    "REPORT_SNAPSHOT_V1": report_snapshot_from_mapping,
    "TECHNICAL_SNAPSHOT_V1": technical_snapshot_from_mapping,
    "AI_RUN": lambda value: _validate_ai_envelope(value, "AI_RUN"),
    "AI_PROPOSAL": lambda value: _validate_ai_envelope(value, "AI_PROPOSAL"),
    "AI_EVAL_OBSERVATION": ai_eval_observation_from_mapping,
    "AI_EVAL_REPORT": ai_eval_report_from_mapping,
    "AI_EVAL_DATASET": ai_eval_dataset_from_mapping,
    "AI_COST_LEDGER_V1": lambda value: _validate_ai_cost_ledger(value),
}
ARTIFACT_COMPATIBILITY = {kind: {"current_version": "1.0.0", "supported_versions": ("1.0.0",), "migration": None, "future_version_policy": "FAIL_CLOSED"} for kind in _ARTIFACT_VALIDATORS}


def _validate_ai_cost_ledger(value: object) -> _ValidatedAIArtifact:
    data = _exact(value, {"workspace_id", "reservations"}, "AI cost ledger")
    workspace_id = str(WorkspaceId.parse(data["workspace_id"]))
    rows = data["reservations"]
    if type(rows) not in {list, tuple}:
        raise RepositoryIntegrityError("AI cost ledger reservations are invalid")
    for row in rows:
        if (
            type(row) is not dict
            or set(row) != {"session_id", "tokens", "cost_microusd"}
            or type(row["session_id"]) is not str
            or not row["session_id"].strip()
            or type(row["tokens"]) is not int
            or row["tokens"] < 0
            or type(row["cost_microusd"]) is not int
            or row["cost_microusd"] < 0
        ):
            raise RepositoryIntegrityError("AI cost ledger reservation is invalid")
    canonical_payload_json(data)
    return _ValidatedAIArtifact(workspace_id)


def _validate_ocr_cache(value: object) -> None:
    payload = thaw_payload(value)
    if type(payload) is not dict:
        raise RepositoryIntegrityError("cache OCR persistido inválido")
    key = tuple(payload.get(name) for name in ("document_sha256", "page_number", "engine", "engine_version", "model_version", "config_version"))
    _page_from_payload(value, key)


def _validate_confirmation(value: object) -> None:
    if (
        type(value) is not dict
        or set(value) != {"schema_version", "confirmed_revision", "extraction_fingerprint"}
        or value["schema_version"] != 1
        or type(value["confirmed_revision"]) is not int
        or value["confirmed_revision"] < 1
        or type(value["extraction_fingerprint"]) is not str
        or _SHA256.fullmatch(value["extraction_fingerprint"]) is None
    ):
        raise RepositoryIntegrityError("process metadata confirmation is invalid")


def _validate_source_confirmation(value: object) -> None:
    expected = {
        "schema_version",
        "decision",
        "field_name",
        "process_case_revision",
        "extraction_fingerprint",
        "evidence_id",
        "document_id",
        "document_sha256",
        "source_page",
        "evidence_source_start",
        "selection_start",
        "selection_end",
        "source_start",
        "source_end",
        "selected_value",
    }
    if (
        type(value) is not dict
        or set(value) != expected
        or value["schema_version"] != 1
        or value["decision"] != "HUMAN_CONFIRMED"
        or value["field_name"] not in {"parte_requerente", "parte_requerida"}
    ):
        raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    if any(
        type(value[name]) is not int or value[name] < 0 for name in ("process_case_revision", "source_page", "evidence_source_start", "selection_start", "selection_end", "source_start", "source_end")
    ):
        raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    if value["process_case_revision"] < 1 or value["source_page"] < 1 or value["selection_end"] <= value["selection_start"] or value["source_end"] <= value["source_start"]:
        raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    for name in ("extraction_fingerprint", "evidence_id", "document_sha256"):
        if type(value[name]) is not str or _SHA256.fullmatch(value[name]) is None:
            raise RepositoryIntegrityError("process metadata source confirmation is invalid")
    PrivateContentId.parse(value["document_id"])
    _text(value["selected_value"], "selected_value")


_INTERNAL_ARTIFACT_VALIDATORS = {
    "PROCESS_METADATA_EXTRACTION": document_metadata_from_payload,
    "PROCESS_METADATA_CONFIRMATION": _validate_confirmation,
    "PROCESS_METADATA_SOURCE_CONFIRMATION": _validate_source_confirmation,
    "OCR_PAGE_CACHE_V1": _validate_ocr_cache,
}


def _validate_user_artifact(value: object) -> None:
    canonical_payload_json(value)


_USER_ARTIFACT_VALIDATORS = {kind: _validate_user_artifact for kind in USER_DEFINED_ARTIFACT_KINDS}

_CANONICAL_PRODUCT_ARTIFACT_IDS = {
    "BUDGET_SNAPSHOT_V1": "BUDGET-SNAPSHOT",
    "CASE_ANALYSIS_SNAPSHOT_V1": "CASE-ANALYSIS",
    "DELIVERY_SNAPSHOT_V1": "DELIVERY-SNAPSHOT",
    "EXPERT_MASTER_PROFILE_V1": "EXPERT-PROFILE",
    "INSPECTION_SESSION_V1": "INSPECTION-SESSION",
    "PERICIAL_PLANNING_SNAPSHOT_V1": "PERICIAL-PLANNING",
    "PROCESS_CASE": "PROCESS_CASE",
    "REPORT_SNAPSHOT_V1": "REPORT-SNAPSHOT",
    "TECHNICAL_SNAPSHOT_V1": "TECHNICAL-SNAPSHOT",
}
_DOMAIN_REVISION_FIELDS = {
    "BUDGET_SNAPSHOT_V1": "revision",
    "DELIVERY_SNAPSHOT_V1": "revision",
    "EXPERT_MASTER_PROFILE_V1": "revision",
}


def _expected_internal_artifact_id(kind: str, payload: object) -> str | None:
    if type(payload) is not dict:
        return None
    if kind == "PROCESS_METADATA_EXTRACTION":
        return payload.get("document_id") if type(payload.get("document_id")) is str else None
    if kind == "PJE_INTAKE_V1":
        # O inventario e endereçado pela fonte fisica que descreve; o envelope
        # tem de concordar com o payload, como ja acontece com a extracao de
        # metadados. Sem isso um inventario poderia ser restaurado sob a
        # identidade de outra fonte.
        return payload.get("storage_content_id") if type(payload.get("storage_content_id")) is str else None
    if kind == "OCR_PAGE_CACHE_V1":
        names = ("document_sha256", "page_number", "engine", "engine_version", "model_version", "config_version")
        key = tuple(payload.get(name) for name in names)
        return hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if kind == "AI_RUN":
        return payload.get("run_id") if type(payload.get("run_id")) is str else None
    if kind == "AI_PROPOSAL":
        return payload.get("proposal_id") if type(payload.get("proposal_id")) is str else None
    if kind == "AI_EVAL_OBSERVATION":
        return payload.get("attestation_sha256") if type(payload.get("attestation_sha256")) is str else None
    if kind == "AI_EVAL_REPORT":
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    if kind == "AI_EVAL_DATASET":
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    if kind == "AI_COST_LEDGER_V1":
        return "AI-COST-LEDGER"
    return None

if frozenset(_ARTIFACT_VALIDATORS) != PORTABLE_PRODUCT_ARTIFACT_KINDS:
    raise RuntimeError("portable artifact validators diverge from application ownership")
if frozenset(_INTERNAL_ARTIFACT_VALIDATORS) != INTERNAL_ARTIFACT_KINDS:
    raise RuntimeError("internal artifact validators diverge from application ownership")


def _revision_mapping(record: ArtifactRevision) -> dict[str, Any]:
    return {
        "workspace_id": str(record.workspace_id),
        "artifact_kind": record.artifact_kind,
        "artifact_id": record.artifact_id,
        "revision_id": record.revision_id,
        "revision": record.revision,
        "created_at": record.created_at,
        "checksum_sha256": record.checksum_sha256,
        "payload": thaw_payload(record.payload),
    }


def _revision_from_mapping(value: object, workspace_id: str) -> ArtifactRevision:
    data = _exact(value, {"workspace_id", "artifact_kind", "artifact_id", "revision_id", "revision", "created_at", "checksum_sha256", "payload"}, "ArtifactRevision")
    if data["workspace_id"] != workspace_id:
        raise RepositoryIntegrityError("backup revision belongs to another workspace")
    record = ArtifactRevision(
        workspace_id=WorkspaceId.parse(data["workspace_id"]),
        artifact_kind=data["artifact_kind"],
        artifact_id=data["artifact_id"],
        revision_id=data["revision_id"],
        revision=data["revision"],
        created_at=data["created_at"],
        checksum_sha256=data["checksum_sha256"],
        payload=data["payload"],
    )
    canonical = canonical_payload_json(thaw_payload(record.payload))
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != record.checksum_sha256:
        raise RepositoryIntegrityError("backup revision checksum diverges")
    validator = (
        _ARTIFACT_VALIDATORS.get(record.artifact_kind)
        or _INTERNAL_ARTIFACT_VALIDATORS.get(record.artifact_kind)
        or _USER_ARTIFACT_VALIDATORS.get(record.artifact_kind)
    )
    expected_artifact_id = _CANONICAL_PRODUCT_ARTIFACT_IDS.get(record.artifact_kind)
    if expected_artifact_id is not None and record.artifact_id != expected_artifact_id:
        raise RepositoryIntegrityError("backup canonical artifact envelope identity diverges")
    revision_field = _DOMAIN_REVISION_FIELDS.get(record.artifact_kind)
    payload = thaw_payload(record.payload)
    expected_internal_id = _expected_internal_artifact_id(record.artifact_kind, payload)
    if expected_internal_id is not None and record.artifact_id != expected_internal_id:
        raise RepositoryIntegrityError("backup internal artifact envelope identity diverges")
    if revision_field is not None and (type(payload) is not dict or payload.get(revision_field) != record.revision):
        raise RepositoryIntegrityError("backup artifact envelope revision diverges")
    if validator is not None:
        validation_value = record.payload if record.artifact_kind in {"PROCESS_METADATA_EXTRACTION", "OCR_PAGE_CACHE_V1"} else payload
        parsed = validator(validation_value)
        payload_workspace = _declared_workspace(parsed)
        if payload_workspace is not None and str(payload_workspace) != workspace_id:
            raise RepositoryIntegrityError("backup payload belongs to another workspace")
        if record.artifact_kind == "AI_EVAL_DATASET" and any(
            case.workspace_id != workspace_id for case in parsed.cases
        ):
            raise RepositoryIntegrityError("backup AI dataset belongs to another workspace")
    else:
        raise RepositoryIntegrityError("backup artifact kind is not portable")
    return record


def _declared_workspace(parsed: object) -> object | None:
    """Workspace declared by a validated artifact, whatever canonical shape it has.

    Artifact validators do not agree on a return type: most build a typed object
    carrying ``workspace_id``, while some return the validated mapping itself.
    Reading the attribute alone therefore treated "this artifact declares no
    workspace" and "this artifact declares one, in a mapping" as the same answer,
    silently skipping the cross-workspace check for the second group. Both shapes
    are now read explicitly; an artifact that genuinely declares no workspace
    still returns ``None``.
    """
    if isinstance(parsed, Mapping):
        return parsed.get("workspace_id")
    return getattr(parsed, "workspace_id", None)


def _verify_dependency_closure(revisions: tuple[ArtifactRevision, ...]) -> None:
    by_kind_revision = {
        (record.artifact_kind, record.revision): record
        for record in revisions
    }
    by_kind_id = {
        (record.artifact_kind, record.artifact_id): record
        for record in revisions
    }

    def require_ai(kind: str, artifact_id: str) -> ArtifactRevision:
        record = by_kind_id.get((kind, artifact_id))
        if record is None:
            raise RepositoryIntegrityError("backup AI dependency closure is incomplete")
        return record

    def require(kind: str, revision: int, digest: str, identity_field: str, identity: str) -> ArtifactRevision:
        record = by_kind_revision.get((kind, revision))
        if record is None or record.checksum_sha256 != digest:
            raise RepositoryIntegrityError("backup dependency closure is incomplete")
        payload = thaw_payload(record.payload)
        if type(payload) is not dict or payload.get(identity_field) != identity:
            raise RepositoryIntegrityError("backup dependency identity diverges")
        return record

    for record in revisions:
        payload = thaw_payload(record.payload)
        if record.artifact_kind == "PERICIAL_PLANNING_SNAPSHOT_V1":
            plan = payload["plan"]
            require("CASE_ANALYSIS_SNAPSHOT_V1", plan["case_analysis_revision"], plan["case_analysis_digest"], "snapshot_id", plan["case_analysis_snapshot_id"])
        elif record.artifact_kind == "INSPECTION_SESSION_V1":
            binding = payload["plan_snapshot"]
            require("PERICIAL_PLANNING_SNAPSHOT_V1", binding["planning_revision"], binding["planning_digest"], "snapshot_id", binding["planning_snapshot_id"])
        elif record.artifact_kind == "TECHNICAL_SNAPSHOT_V1":
            binding = payload["source_snapshot"]
            require("CASE_ANALYSIS_SNAPSHOT_V1", binding["case_analysis_revision"], binding["case_analysis_digest"], "snapshot_id", binding["case_analysis_snapshot_id"])
            require("INSPECTION_SESSION_V1", binding["inspection_session_revision"], binding["inspection_session_digest"], "session_id", binding["inspection_session_id"])
        elif record.artifact_kind == "REPORT_SNAPSHOT_V1":
            binding = payload["source_snapshot"]
            require("CASE_ANALYSIS_SNAPSHOT_V1", binding["case_analysis_revision"], binding["case_analysis_digest"], "snapshot_id", binding["case_analysis_snapshot_id"])
            require("INSPECTION_SESSION_V1", binding["inspection_session_revision"], binding["inspection_session_digest"], "session_id", binding["inspection_session_id"])
            require("TECHNICAL_SNAPSHOT_V1", binding["technical_snapshot_revision"], binding["technical_snapshot_digest"], "snapshot_id", binding["technical_snapshot_id"])
            require("EXPERT_MASTER_PROFILE_V1", binding["expert_profile_revision"], binding["expert_profile_digest"], "profile_id", binding["expert_profile_id"])
        elif record.artifact_kind == "DELIVERY_SNAPSHOT_V1":
            binding = payload["binding"]
            require("CASE_ANALYSIS_SNAPSHOT_V1", binding["case_analysis_revision"], binding["case_analysis_digest"], "snapshot_id", binding["case_analysis_snapshot_id"])
            require("PERICIAL_PLANNING_SNAPSHOT_V1", binding["planning_revision"], binding["planning_digest"], "snapshot_id", binding["planning_snapshot_id"])
            require("INSPECTION_SESSION_V1", binding["inspection_revision"], binding["inspection_digest"], "session_id", binding["inspection_snapshot_id"])
            require("TECHNICAL_SNAPSHOT_V1", binding["technical_revision"], binding["technical_digest"], "snapshot_id", binding["technical_snapshot_id"])
            report_record = require("REPORT_SNAPSHOT_V1", binding["report_revision"], binding["report_digest"], "report_id", binding["report_snapshot_id"])
            report = report_snapshot_from_mapping(thaw_payload(report_record.payload))
            approval = next((item for item in report.review_decisions if item.review_id == binding["report_approval_id"]), None)
            if (
                report.state.value != "APPROVED"
                or approval is None
                or approval is not report.review_decisions[-1]
                or approval.action.value != "APPROVE"
                or approval.professional_id != binding["professional_id"]
            ):
                raise RepositoryIntegrityError("backup delivery professional authority diverges")
        elif record.artifact_kind == "AI_RUN":
            for proposal_id in payload["proposal_ids"]:
                proposal = require_ai("AI_PROPOSAL", proposal_id)
                proposal_payload = thaw_payload(proposal.payload)
                if (
                    proposal_payload["run_id"] != record.artifact_id
                    or proposal_payload["workspace_id"] != payload["workspace_id"]
                    or proposal_payload["task_type"] != payload["task_type"]
                    or proposal_payload["provider"] != payload["provider"]
                    or proposal_payload["model"] != payload["model"]
                    or proposal_payload["source_refs"] != payload["source_refs"]
                ):
                    raise RepositoryIntegrityError("backup AI run/proposal identity diverges")
        elif record.artifact_kind == "AI_PROPOSAL":
            run = require_ai("AI_RUN", payload["run_id"])
            run_payload = thaw_payload(run.payload)
            if (
                payload["proposal_id"] not in run_payload["proposal_ids"]
                or payload["workspace_id"] != run_payload["workspace_id"]
                or payload["task_type"] != run_payload["task_type"]
                or payload["provider"] != run_payload["provider"]
                or payload["model"] != run_payload["model"]
                or payload["source_refs"] != run_payload["source_refs"]
            ):
                raise RepositoryIntegrityError("backup AI proposal/run identity diverges")
        elif record.artifact_kind == "AI_EVAL_OBSERVATION":
            dataset_record = require_ai("AI_EVAL_DATASET", payload["dataset_sha256"])
            dataset = ai_eval_dataset_from_mapping(thaw_payload(dataset_record.payload))
            case = next((item for item in dataset.cases if item.case_id == payload["case_id"]), None)
            if case is None:
                raise RepositoryIntegrityError("backup AI observation case is absent")
            run = require_ai("AI_RUN", payload["run_id"])
            run_payload = thaw_payload(run.payload)
            canonical_run = _validate_ai_envelope(run_payload, "AI_RUN")
            usage = run_payload["usage"]
            expected_usage = {
                "input_tokens": usage["input_tokens"] if usage else 0,
                "cached_input_tokens": usage["cached_input_tokens"] if usage else 0,
                "output_tokens": usage["output_tokens"] if usage else 0,
                "estimated_cost_microusd": (usage["estimated_cost_microusd"] or 0) if usage else 0,
            }
            if (
                payload["workspace_id"] != run_payload["workspace_id"]
                or payload["task_type"] != run_payload["task_type"]
                or payload["provider"] != run_payload["provider"]
                or payload["profile_id"] != run_payload["profile_id"]
                or payload["model"] != run_payload["model"]
                or payload["prompt_template_version"] != run_payload["prompt_template_version"]
                or payload["prompt_template_hash"] != run_payload["prompt_template_hash"]
                or payload["structured_output_schema_hash"] != run_payload["structured_output_schema_hash"]
                or payload["source_refs"] != run_payload["source_refs"]
                or payload["latency_ms"] != run_payload["latency_ms"]
                or payload["cache_hit"] != run_payload["cache_hit"]
                or payload["error_classification"] != run_payload["error_classification"]
                or any(payload[key] != value for key, value in expected_usage.items())
                or (payload["proposal_id"] is None) != (not run_payload["proposal_ids"])
                or (
                    payload["proposal_id"] is not None
                    and payload["proposal_id"] not in run_payload["proposal_ids"]
                )
            ):
                raise RepositoryIntegrityError("backup AI observation/run provenance diverges")
            if payload["proposal_id"] is not None:
                proposal = require_ai("AI_PROPOSAL", payload["proposal_id"])
                if thaw_payload(proposal.payload)["run_id"] != run.artifact_id:
                    raise RepositoryIntegrityError("backup AI observation provenance diverges")
                canonical_proposal = _validate_ai_envelope(
                    thaw_payload(proposal.payload), "AI_PROPOSAL"
                )
                domain_proposal = validate_domain_proposal(
                    canonical_proposal, DomainProposalKind(case.task_type)
                )
                usage = canonical_run.usage
                telemetry = AIEvalTelemetry(
                    canonical_run.provider, canonical_run.profile_id, canonical_run.model,
                    canonical_run.prompt_template_version, canonical_run.prompt_template_hash,
                    canonical_run.structured_output_schema_hash,
                    usage.input_tokens if usage else 0,
                    usage.cached_input_tokens if usage else 0,
                    usage.output_tokens if usage else 0,
                    (usage.estimated_cost_microusd or 0) if usage else 0,
                    canonical_run.latency_ms, canonical_run.cache_hit,
                )
                expected_observation = observe_domain_proposal(
                    dataset.version, dataset.sha256, case, domain_proposal, canonical_run,
                    telemetry, HumanEvalOutcome(payload["human_outcome"]),
                )
            else:
                expected_observation = observe_failed_run(
                    dataset.version, dataset.sha256, case, canonical_run,
                    HumanEvalOutcome(payload["human_outcome"]),
                )
            if ai_eval_observation_from_mapping(payload) != expected_observation:
                raise RepositoryIntegrityError("backup AI observation derivation diverges")
        elif record.artifact_kind == "AI_EVAL_REPORT":
            dataset_record = require_ai("AI_EVAL_DATASET", payload["dataset_sha256"])
            dataset = ai_eval_dataset_from_mapping(thaw_payload(dataset_record.payload))
            if (
                dataset.version != payload["dataset_version"]
                or tuple(case.case_id for case in dataset.cases) != tuple(payload["observation_case_ids"])
            ):
                raise RepositoryIntegrityError("backup AI report dataset manifest diverges")
            observations = []
            for case_id, attestation in zip(
                payload["observation_case_ids"],
                payload["observation_attestations"],
                strict=True,
            ):
                observation = require_ai("AI_EVAL_OBSERVATION", attestation)
                observed = thaw_payload(observation.payload)
                if (
                    observed["case_id"] != case_id
                    or
                    observed["workspace_id"] != payload["workspace_id"]
                    or observed["dataset_version"] != payload["dataset_version"]
                    or observed["dataset_sha256"] != payload["dataset_sha256"]
                ):
                    raise RepositoryIntegrityError("backup AI report provenance diverges")
                observations.append(ai_eval_observation_from_mapping(observed))
            if evaluate_ai_dataset(dataset, tuple(observations)) != ai_eval_report_from_mapping(payload):
                raise RepositoryIntegrityError("backup AI report aggregate diverges")


def _private_mapping(metadata: PrivateContentMetadata, content: bytes) -> dict[str, Any]:
    return {
        "workspace_id": str(metadata.workspace_id),
        "content_id": str(metadata.content_id),
        "original_filename": metadata.original_filename,
        "byte_size": metadata.byte_size,
        "checksum_sha256": metadata.checksum_sha256,
        "media_type": metadata.media_type,
        "imported_at": metadata.imported_at,
        "origin": metadata.origin.value,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _private_from_mapping(value: object, workspace_id: str) -> PrivateContent:
    data = _exact(value, {"workspace_id", "content_id", "original_filename", "byte_size", "checksum_sha256", "media_type", "imported_at", "origin", "content_base64"}, "PrivateContent")
    if data["workspace_id"] != workspace_id:
        raise RepositoryIntegrityError("backup private content belongs to another workspace")
    try:
        content = base64.b64decode(data.pop("content_base64"), validate=True)
        data["workspace_id"] = WorkspaceId.parse(data["workspace_id"])
        data["content_id"] = PrivateContentId.parse(data["content_id"])
        data["origin"] = PrivateContentOrigin(data["origin"])
        return PrivateContent(PrivateContentMetadata(**data), content)
    except (TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("backup private content is invalid") from exc


def _manifest_hash(mapping: dict[str, Any]) -> str:
    return _hash({key: value for key, value in mapping.items() if key != "manifest_sha256"})


@dataclass(frozen=True, slots=True)
class VerifyWorkspaceBackup:
    def execute(self, payload: bytes) -> WorkspaceBackup:
        if type(payload) is not bytes:
            raise TypeError("backup requires bytes")
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise RepositoryIntegrityError("backup package is invalid") from exc
        migrated = migrate_backup_mapping(raw)
        value = workspace_backup_from_mapping(migrated)
        mapping = workspace_backup_to_mapping(value)
        if mapping["product_release"] not in SUPPORTED_PRODUCT_RELEASES or mapping["storage_schema_version"] != 1:
            raise RepositoryIntegrityError("backup compatibility window is unsupported")
        expected_members = {"artifact_revisions": _hash(mapping["artifact_revisions"]), "private_contents": _hash(mapping["private_contents"])}
        if mapping["member_hashes"] != expected_members or mapping["manifest_sha256"] != _manifest_hash(mapping):
            raise RepositoryIntegrityError("backup package checksum diverges")
        workspace_id = value.workspace.workspace_id
        revisions = tuple(_revision_from_mapping(item, workspace_id) for item in value.artifact_revisions)
        revision_order = [(item.artifact_kind, item.artifact_id, item.revision) for item in revisions]
        if revision_order != sorted(revision_order):
            raise RepositoryIntegrityError("backup revision order is not canonical")
        identities: set[str] = set()
        sequences: dict[tuple[str, str], list[int]] = {}
        for record in revisions:
            if record.revision_id in identities:
                raise RepositoryIntegrityError("backup revision identity is duplicated")
            identities.add(record.revision_id)
            sequences.setdefault((record.artifact_kind, record.artifact_id), []).append(record.revision)
        if any(items != list(range(1, len(items) + 1)) for items in sequences.values()):
            raise RepositoryIntegrityError("backup revision sequence is incomplete")
        _verify_dependency_closure(revisions)
        private_contents = tuple(_private_from_mapping(item, workspace_id) for item in value.private_contents)
        private_ids = [item["content_id"] for item in value.private_contents]
        if len(private_ids) != len(set(private_ids)):
            raise RepositoryIntegrityError("backup private identity is duplicated")
        private_authority = {
            str(item.metadata.content_id): item.metadata.checksum_sha256
            for item in private_contents
        }
        private_by_id = {str(item.metadata.content_id): item for item in private_contents}
        for record in revisions:
            if record.artifact_kind == "CASE_ANALYSIS_SNAPSHOT_V1":
                case = case_analysis_from_mapping(thaw_payload(record.payload))
                if any(
                    private_authority.get(item.storage_content_id) != item.source_sha256
                    for item in case.documents
                ):
                    raise RepositoryIntegrityError("backup Case Analysis source authority is incomplete")
            elif record.artifact_kind == "PJE_INTAKE_V1":
                # O inventario nomeia a fonte privada de que foi derivado. Sem
                # este fecho, um backup podia ser certificado intacto e restaurar
                # um inventario cuja fonte nao veio junto, deixando a Case
                # Analysis permanentemente indisponivel no workspace restaurado.
                inventory = validate_pje_intake_payload(thaw_payload(record.payload))
                if private_authority.get(inventory["storage_content_id"]) != inventory["source_sha256"]:
                    raise RepositoryIntegrityError("backup PJe source authority is incomplete")
            elif record.artifact_kind == "INSPECTION_SESSION_V1":
                inspection = inspection_session_from_mapping(thaw_payload(record.payload))
                media = (*inspection.photos, *inspection.videos, *inspection.sketches)
                if any(
                    private_authority.get(item.private_content_id) != item.original_sha256
                    for item in media
                ):
                    raise RepositoryIntegrityError("backup inspection media authority is incomplete")
            elif record.artifact_kind == "DELIVERY_SNAPSHOT_V1":
                delivery = delivery_snapshot_from_mapping(thaw_payload(record.payload))
                if private_authority.get(delivery.template_content_id) != delivery.template_digest or any(
                    private_authority.get(item.content_id) != item.checksum_sha256
                    for item in delivery.artifacts
                ):
                    raise RepositoryIntegrityError("backup delivery byte authority is incomplete")
                try:
                    validate_final_artifact(
                        private_by_id[delivery.template_content_id].content,
                        delivery.template_format.value,
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise RepositoryIntegrityError("backup delivery template is invalid") from exc
                for artifact in delivery.artifacts:
                    try:
                        content = private_by_id[artifact.content_id].content
                        if artifact.format.value == "OTHER":
                            validate_supporting_artifact(content, artifact.media_type)
                        else:
                            validate_delivery_artifact(content, artifact.format.value)
                    except (KeyError, TypeError, ValueError) as exc:
                        raise RepositoryIntegrityError("backup delivery artifact is invalid") from exc
        return value


@dataclass(frozen=True, slots=True)
class CreateWorkspaceBackup:
    workspaces: object
    revisions: object
    private_contents: object | None
    clock: object
    assert_backup_ready: object
    ai_cost_ledger: object | None = None

    def execute(self, workspace_id: WorkspaceId) -> bytes:
        self.assert_backup_ready(workspace_id)
        workspace = self.workspaces.get(workspace_id)
        if workspace is None:
            raise ValueError("workspace is unavailable")
        revision_items = [
            _revision_mapping(item) for item in self.revisions.list_workspace(workspace_id)
            if self.ai_cost_ledger is None or item.artifact_kind != "AI_COST_LEDGER_V1"
        ]
        ai_activity = any(item["artifact_kind"].startswith("AI_") for item in revision_items)
        if ai_activity and self.ai_cost_ledger is None:
            raise RepositoryIntegrityError("AI cost authority is required for backup")
        private_items = []
        if self.private_contents is not None:
            for metadata in self.private_contents.list_all(workspace_id):
                with self.private_contents.open_content(workspace_id, metadata.content_id) as opened:
                    content = opened.stream.read()
                private_items.append(_private_mapping(metadata, content))
        now = self.clock.now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("backup clock requires timezone")
        if self.ai_cost_ledger is not None:
            rows = self.ai_cost_ledger.export_workspace(str(workspace_id))
            cost_payload = {"workspace_id": str(workspace_id), "reservations": list(rows)}
            cost_checksum = hashlib.sha256(canonical_payload_json(cost_payload).encode("utf-8")).hexdigest()
            revision_items.append({
                "workspace_id": str(workspace_id),
                "artifact_kind": "AI_COST_LEDGER_V1",
                "artifact_id": "AI-COST-LEDGER",
                "revision_id": str(uuid5(NAMESPACE_URL, f"ai-cost-ledger:{workspace_id}:{cost_checksum}")),
                "revision": 1,
                "created_at": now.isoformat(),
                "checksum_sha256": cost_checksum,
                "payload": cost_payload,
            })
        revision_items.sort(key=lambda item: (item["artifact_kind"], item["artifact_id"], item["revision"]))
        mapping = {
            "schema_version": "1.0.0",
            "format_version": 1,
            "product_release": PRODUCT_RELEASE_VERSION,
            "storage_schema_version": 1,
            "workspace": {"workspace_id": str(workspace.workspace_id), "name": workspace.name, "created_at": workspace.created_at},
            "artifact_revisions": revision_items,
            "private_contents": private_items,
            "member_hashes": {"artifact_revisions": _hash(revision_items), "private_contents": _hash(private_items)},
            "manifest_sha256": "0" * 64,
            "created_at": now.isoformat(),
        }
        mapping["manifest_sha256"] = _manifest_hash(mapping)
        payload = _canonical(mapping)
        VerifyWorkspaceBackup().execute(payload)
        return payload


@dataclass(frozen=True, slots=True)
class RestoreReceipt:
    workspace_id: str
    backup_sha256: str
    artifact_revisions: int
    private_contents: int
    product_release: str
    storage_schema_version: int


_AUTHORIZED_RECOVERY_STAGING: WeakKeyDictionary["RecoveryStaging", tuple[Path, SQLiteApplicationStore, LocalPrivateContentStore, os.stat_result]] = WeakKeyDictionary()


class RecoveryStaging:
    """Owns a new disposable storage root until external promotion."""

    __slots__ = ("_root", "_database", "_private_contents", "_identity", "_closed", "_discarded", "__weakref__")

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("recovery staging must be created by RecoveryStaging.create")

    @classmethod
    def create(cls, root: str | Path) -> "RecoveryStaging":
        if not isinstance(root, (str, Path)):
            raise TypeError("recovery staging root is invalid")
        raw = str(root)
        if not raw.strip() or "\x00" in raw or raw.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
            raise RepositoryIntegrityError("recovery staging root must be local")
        target = Path(root)
        if not target.is_absolute():
            raise RepositoryIntegrityError("recovery staging root must be absolute")
        parent = target.parent.resolve(strict=True)
        if parent != target.parent.absolute():
            raise RepositoryIntegrityError("recovery staging parent must not redirect")
        if target.exists() or target.is_symlink():
            raise RepositoryConflict("recovery staging root must not exist")
        os.mkdir(target, 0o700)
        marker_fd = os.open(target / "RECOVERY_NOT_PROMOTABLE", os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_BINARY, 0o600)
        try:
            remaining = memoryview(b"RECOVERY_STAGING_V1\n")
            while remaining:
                written = os.write(marker_fd, remaining)
                if written <= 0:
                    raise RepositoryIntegrityError("recovery quarantine marker write failed")
                remaining = remaining[written:]
            os.fsync(marker_fd)
        finally:
            os.close(marker_fd)
        marker = target / "RECOVERY_NOT_PROMOTABLE"
        if marker.read_bytes() != b"RECOVERY_STAGING_V1\n":
            raise RepositoryIntegrityError("recovery quarantine marker is incomplete")
        if os.name == "posix":
            directory_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        identity = os.lstat(target)
        database = None
        private = None
        try:
            database = SQLiteApplicationStore(target / "workspace.sqlite3")
            database.mark_recovery_quarantine()
            private = LocalPrivateContentStore.open_or_provision(target / "private")
            private.mark_recovery_quarantine()
            staging = object.__new__(cls)
            staging._root = target.resolve(strict=True)
            staging._database = database
            staging._private_contents = private
            staging._identity = identity
            staging._closed = False
            staging._discarded = False
            _AUTHORIZED_RECOVERY_STAGING[staging] = (staging._root, database, private, identity)
            return staging
        except BaseException:
            if private is not None:
                private.close()
            if database is not None:
                database.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        authority = _AUTHORIZED_RECOVERY_STAGING.pop(self, None)
        database = authority[1] if authority is not None else self._database
        private_contents = authority[2] if authority is not None else self._private_contents
        try:
            private_contents.close()
        finally:
            database.close()

    def discard(self) -> None:
        if self._discarded:
            return
        self._discarded = True
        self.close()

    @property
    def discarded(self) -> bool:
        return self._discarded

    @property
    def root(self) -> Path:
        return self._root

    @property
    def database(self) -> SQLiteApplicationStore:
        return self._database

    @property
    def workspaces(self):
        return self._database.workspaces

    @property
    def revisions(self):
        return self._database.revisions

    @property
    def private_contents(self) -> LocalPrivateContentStore:
        return self._private_contents


@dataclass(frozen=True, slots=True)
class RestoreWorkspaceBackup:
    staging: RecoveryStaging

    def execute(self, payload: bytes) -> RestoreReceipt:
        authority = _AUTHORIZED_RECOVERY_STAGING.get(self.staging) if type(self.staging) is RecoveryStaging else None
        if authority is None or self.staging._closed:
            raise TypeError("restore requires first-party recovery staging")
        _root, database, private_contents, _identity = authority
        workspaces = database.workspaces
        revisions = database.revisions
        try:
            backup = VerifyWorkspaceBackup().execute(payload)
            workspace_id = WorkspaceId.parse(backup.workspace.workspace_id)
            if workspaces.list_all() != ():
                raise RepositoryConflict("restore staging workspace is not empty")
            revision_records = tuple(_revision_from_mapping(item, backup.workspace.workspace_id) for item in backup.artifact_revisions)
            private_records = tuple(_private_from_mapping(item, backup.workspace.workspace_id) for item in backup.private_contents)
            workspaces.create(PericiaWorkspace(workspace_id, backup.workspace.name, backup.workspace.created_at))
            for record in revision_records:
                revisions.append(
                    workspace_id=workspace_id,
                    artifact_kind=record.artifact_kind,
                    artifact_id=record.artifact_id,
                    revision_id=record.revision_id,
                    created_at=record.created_at,
                    payload=thaw_payload(record.payload),
                )
            for item in private_records:
                private_contents.store(item.metadata, item.content)
            cost_records = [item for item in revision_records if item.artifact_kind == "AI_COST_LEDGER_V1"]
            if len(cost_records) > 1:
                raise RepositoryIntegrityError("restored AI cost authority is ambiguous")
            if cost_records:
                cost_payload = thaw_payload(cost_records[0].payload)
                ledger = SQLiteAICostLedger(
                    AICostLimits(1, 1, 1, 1), self.staging.root / AI_COST_LEDGER_FILENAME
                )
                ledger.import_workspace(str(workspace_id), cost_payload["reservations"])
            reopened = revisions.list_workspace(workspace_id)
            if tuple(_revision_mapping(item) for item in reopened) != backup.artifact_revisions:
                raise RepositoryIntegrityError("restored workspace failed canonical reopen")
            for item in private_records:
                with private_contents.open_content(workspace_id, item.metadata.content_id) as opened:
                    if opened.stream.read() != item.content:
                        raise RepositoryIntegrityError("restored private content diverges")
            return RestoreReceipt(str(workspace_id), hashlib.sha256(payload).hexdigest(), len(revision_records), len(private_records), backup.product_release, backup.storage_schema_version)
        except BaseException:
            self.staging.discard()
            raise


@dataclass(frozen=True, slots=True)
class SupportDiagnostic:
    product_release: str
    storage_schema_version: int
    supported_backup_versions: tuple[int, ...]
    integrity_status: str
    artifact_revision_count: int
    private_content_count: int
    error_code: str | None
    private_egress: bool = False


def collect_support_diagnostics(payload: bytes) -> SupportDiagnostic:
    try:
        value = VerifyWorkspaceBackup().execute(payload)
        return SupportDiagnostic(
            PRODUCT_RELEASE_VERSION, value.storage_schema_version, tuple(sorted(SUPPORTED_BACKUP_VERSIONS)), "PASS", len(value.artifact_revisions), len(value.private_contents), None
        )
    except (RepositoryIntegrityError, TypeError, ValueError):
        return SupportDiagnostic(PRODUCT_RELEASE_VERSION, 1, tuple(sorted(SUPPORTED_BACKUP_VERSIONS)), "FAIL", 0, 0, "BACKUP_INTEGRITY_INVALID")
