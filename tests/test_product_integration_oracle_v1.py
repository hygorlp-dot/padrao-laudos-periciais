from __future__ import annotations

import json
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.backend_contract.application.delivery_foundation import reconcile_delivery
from scripts.backend_contract.application.ports import RepositoryIntegrityError
from scripts.backend_contract.budget_foundation import budget_snapshot_from_mapping
from scripts.backend_contract.case_analysis import case_analysis_from_mapping
from scripts.backend_contract.delivery_foundation import DeliveryState, delivery_snapshot_from_mapping
from scripts.backend_contract.infrastructure.productization import CreateWorkspaceBackup, RecoveryStaging, RestoreWorkspaceBackup, VerifyWorkspaceBackup
from scripts.backend_contract.application.models import PrivateContentId, WorkspaceId, thaw_payload
from scripts.backend_contract.pericial_planning import pericial_planning_from_mapping
from scripts.backend_contract.report_foundation import report_snapshot_from_mapping
from scripts.backend_contract.technical_findings import technical_snapshot_from_mapping
from scripts.backend_contract.vistoria import inspection_session_from_mapping


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _fixture(name: str) -> dict:
    return _repair_text(json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")))


def _repair_text(value: object) -> object:
    if type(value) is dict:
        return {key: _repair_text(item) for key, item in value.items()}
    if type(value) is list:
        return [_repair_text(item) for item in value]
    if type(value) is str:
        result = value
        for _ in range(2):
            if not any(token in result for token in ("Ã", "Â", "â€")):
                break
            try:
                result = result.encode("latin1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                break
        return result
    return value


def _replace_text(value: object, replacements: dict[str, str]) -> object:
    if type(value) is dict:
        return {key: _replace_text(item, replacements) for key, item in value.items()}
    if type(value) is list:
        return [_replace_text(item, replacements) for item in value]
    return replacements.get(value, value) if type(value) is str else value


def _docx() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Laudo sintético aprovado</w:t></w:r></w:p></w:body></w:document>')
    return output.getvalue()


def _private(content_id: str, content: bytes, filename: str, media_type: str) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "content_id": content_id,
        "original_filename": filename,
        "byte_size": len(content),
        "checksum_sha256": hashlib.sha256(content).hexdigest(),
        "media_type": media_type,
        "imported_at": "2026-09-01T12:00:00+00:00",
        "origin": "LOCAL_IMPORT",
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _revision(kind: str, artifact_id: str, payload: dict, revision: int, serial: int) -> dict:
    return {
        "workspace_id": WORKSPACE_ID,
        "artifact_kind": kind,
        "artifact_id": artifact_id,
        "revision_id": f"90000000-0000-4000-8000-{serial:012d}",
        "revision": revision,
        "created_at": "2026-09-01T12:00:00+00:00",
        "checksum_sha256": _digest(payload),
        "payload": deepcopy(payload),
    }


def _reseal(mapping: dict) -> bytes:
    for record in mapping["artifact_revisions"]:
        record["checksum_sha256"] = _digest(record["payload"])
    mapping["member_hashes"] = {
        "artifact_revisions": _digest(mapping["artifact_revisions"]),
        "private_contents": _digest(mapping["private_contents"]),
    }
    mapping["manifest_sha256"] = _digest({key: value for key, value in mapping.items() if key != "manifest_sha256"})
    return _canonical(mapping)


def _longitudinal_backup() -> tuple[bytes, dict[str, dict]]:
    case = _fixture("case-analysis-snapshot-v1.json")
    planning = _fixture("pericial-planning-snapshot-v1.json")
    inspection = _fixture("inspection-session-v1.json")
    technical = _fixture("technical-snapshot-v1.json")
    report = _fixture("report-snapshot-v1.json")
    budget = _fixture("budget-snapshot-v1.json")
    profile = deepcopy(report["expert_profile"])

    source_private = []
    source_replacements = {}
    for index, document in enumerate(case["documents"], 1):
        content = f"fonte processual sintética {index}".encode()
        digest = hashlib.sha256(content).hexdigest()
        source_replacements[document["source_sha256"]] = digest
        source_private.append(_private(document["storage_content_id"], content, f"fonte-{index}.pdf", "application/pdf"))
    case = _replace_text(case, source_replacements)

    media_private = []
    for kind, content, media_type in (("photos", b"photo", "image/jpeg"), ("videos", b"video", "video/mp4"), ("sketches", b"sketch", "image/png")):
        item = inspection[kind][0]
        item["original_sha256"] = hashlib.sha256(content).hexdigest()
        media_private.append(_private(item["private_content_id"], content, f"{kind}.bin", media_type))

    planning["plan"]["case_analysis_digest"] = _digest(case)
    planning["plan"]["case_analysis_revision"] = 3
    inspection["plan_snapshot"]["planning_revision"] = 1
    inspection["plan_snapshot"]["planning_digest"] = _digest(planning)
    technical["source_snapshot"]["case_analysis_snapshot_id"] = case["snapshot_id"]
    technical["source_snapshot"]["case_analysis_digest"] = _digest(case)
    technical["source_snapshot"]["inspection_session_revision"] = 1
    technical["source_snapshot"]["inspection_session_digest"] = _digest(inspection)
    for link in technical["source_links"]:
        if link["source_kind"] in {"FIELD_OBSERVATION", "MEASUREMENT", "PHOTO", "VIDEO", "SKETCH", "PARTICIPANT_STATEMENT"}:
            link["source_revision"] = 1
    report["source_snapshot"]["case_analysis_snapshot_id"] = case["snapshot_id"]
    report["source_snapshot"]["case_analysis_digest"] = _digest(case)
    report["source_snapshot"]["inspection_session_revision"] = 1
    report["source_snapshot"]["inspection_session_digest"] = _digest(inspection)
    report["source_snapshot"]["technical_snapshot_revision"] = 1
    report["source_snapshot"]["technical_snapshot_digest"] = _digest(technical)
    report["source_snapshot"]["expert_profile_digest"] = _digest(profile)
    for claim in report["claims"]:
        for provenance in claim["provenance"]:
            if provenance["source_kind"] in {"FIELD_OBSERVATION", "MEASUREMENT"}:
                provenance["source_revision"] = 1
            elif provenance["source_kind"] in {"TECHNICAL_FINDING", "PROFESSIONAL_DECISION"}:
                provenance["source_revision"] = 1

    word = _docx()
    template = _docx()
    delivery = _fixture("delivery-snapshot-v1.json")
    delivery["workspace_id"] = delivery["binding"]["workspace_id"] = WORKSPACE_ID
    delivery["binding"].update({
        "source_snapshot_id": f"SOURCE-INVENTORY-{case['source_revision']}",
        "source_revision": case["source_revision"],
        "case_analysis_snapshot_id": case["snapshot_id"], "case_analysis_revision": 3, "case_analysis_digest": _digest(case),
        "planning_snapshot_id": planning["snapshot_id"], "planning_revision": 1, "planning_digest": _digest(planning),
        "inspection_snapshot_id": inspection["session_id"], "inspection_revision": 1, "inspection_digest": _digest(inspection),
        "technical_snapshot_id": technical["snapshot_id"], "technical_revision": 1, "technical_digest": _digest(technical),
        "report_snapshot_id": report["report_id"], "report_revision": 1, "report_digest": _digest(report),
        "report_approval_id": report["review_decisions"][-1]["review_id"],
        "professional_id": profile["profile_id"],
    })
    delivery["template_digest"] = hashlib.sha256(template).hexdigest()
    delivery["artifacts"] = [{
        "artifact_id": "ARTIFACT-WORD-001", "role": "MAIN_REPORT", "format": "DOCX",
        "filename": "laudo-sintetico-r1.docx", "content_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "byte_size": len(word), "checksum_sha256": hashlib.sha256(word).hexdigest(),
    }]
    delivery["package"]["artifact_ids"] = ["ARTIFACT-WORD-001"]
    delivery["decisions"] = [
        {"decision_id": "DELIVERY-DECISION-1", "action": "MARK_READY_FOR_REVIEW", "professional_id": profile["profile_id"], "reason": "Revisão sintética.", "timestamp": "2026-09-01T12:01:00+00:00", "supersedes_decision_id": None},
        {"decision_id": "DELIVERY-DECISION-2", "action": "APPROVE", "professional_id": profile["profile_id"], "reason": "Aprovação sintética.", "timestamp": "2026-09-01T12:02:00+00:00", "supersedes_decision_id": "DELIVERY-DECISION-1"},
        {"decision_id": "DELIVERY-DECISION-3", "action": "FINALIZE", "professional_id": profile["profile_id"], "reason": "Finalização sintética.", "timestamp": "2026-09-01T12:03:00+00:00", "supersedes_decision_id": "DELIVERY-DECISION-2"},
        {"decision_id": "DELIVERY-DECISION-4", "action": "DELIVER", "professional_id": profile["profile_id"], "reason": "Entrega sintética.", "timestamp": "2026-09-01T12:04:00+00:00", "supersedes_decision_id": "DELIVERY-DECISION-3"},
    ]
    delivery["state"] = "DELIVERED"

    payloads = {"case": case, "planning": planning, "inspection": inspection, "technical": technical, "profile": profile, "report": report, "delivery": delivery, "budget": budget}
    case_v1 = deepcopy(case)
    case_v1["human_reviews"] = []
    case_v2 = deepcopy(case)
    case_v2["human_reviews"] = case_v2["human_reviews"][:1]
    delivery_v1 = deepcopy(delivery)
    delivery_v1.update(revision=1, artifacts=[], decisions=[], state="DRAFT")
    delivery_v1["package"]["artifact_ids"] = []
    delivery_v2 = deepcopy(delivery)
    delivery_v2.update(revision=2, decisions=[], state="DRAFT")
    delivery_v3 = deepcopy(delivery)
    delivery_v3.update(revision=3, decisions=delivery_v3["decisions"][:1], state="READY_FOR_REVIEW")
    delivery_v4 = deepcopy(delivery)
    delivery_v4.update(revision=4, decisions=delivery_v4["decisions"][:2], state="APPROVED")
    delivery_v5 = deepcopy(delivery)
    delivery_v5.update(revision=5, decisions=delivery_v5["decisions"][:3], state="FINALIZED")
    delivery_v6 = deepcopy(delivery)
    delivery_v6["revision"] = 6
    delivery = delivery_v6
    payloads["delivery"] = delivery
    definitions = (
        ("CASE_ANALYSIS_SNAPSHOT_V1", "CASE-ANALYSIS", (case_v1, case_v2, case)),
        ("PERICIAL_PLANNING_SNAPSHOT_V1", "PERICIAL-PLANNING", (planning,)),
        ("INSPECTION_SESSION_V1", "INSPECTION-SESSION", (inspection,)),
        ("TECHNICAL_SNAPSHOT_V1", "TECHNICAL-SNAPSHOT", (technical,)),
        ("EXPERT_MASTER_PROFILE_V1", "EXPERT-PROFILE", (profile,)),
        ("REPORT_SNAPSHOT_V1", "REPORT-SNAPSHOT", (report,)),
        ("DELIVERY_SNAPSHOT_V1", "DELIVERY-SNAPSHOT", (delivery_v1, delivery_v2, delivery_v3, delivery_v4, delivery_v5, delivery_v6)),
        ("BUDGET_SNAPSHOT_V1", "BUDGET-SNAPSHOT", (budget,)),
    )
    revisions = []
    serial = 1
    for kind, artifact_id, history in definitions:
        for revision, payload in enumerate(history, 1):
            revisions.append(_revision(kind, artifact_id, payload, revision, serial))
            serial += 1
    revisions.sort(key=lambda item: (item["artifact_kind"], item["artifact_id"], item["revision"]))

    private_contents = [*source_private, *media_private]
    private_contents.extend((
        _private(delivery["template_content_id"], template, "template.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        _private(delivery["artifacts"][0]["content_id"], word, "laudo-sintetico-r1.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ))

    mapping = {
        "schema_version": "1.0.0", "format_version": 1, "product_release": "0.11.0", "storage_schema_version": 1,
        "workspace": {"workspace_id": WORKSPACE_ID, "name": "Perícia longitudinal sintética", "created_at": "2026-09-01T11:00:00+00:00"},
        "artifact_revisions": revisions, "private_contents": private_contents,
        "member_hashes": {"artifact_revisions": _digest(revisions), "private_contents": _digest(private_contents)},
        "manifest_sha256": "0" * 64, "created_at": "2026-09-01T13:00:00+00:00",
    }
    mapping["manifest_sha256"] = _digest({key: value for key, value in mapping.items() if key != "manifest_sha256"})
    return _canonical(mapping), payloads


def test_d1_to_d7_longitudinal_authority_delivery_budget_and_recovery(tmp_path: Path) -> None:
    package, payloads = _longitudinal_backup()
    verified = VerifyWorkspaceBackup().execute(package)
    assert verified.workspace.workspace_id == WORKSPACE_ID

    case = case_analysis_from_mapping(payloads["case"])
    assert case.human_reviews and case.effective_reviewed_value(case.human_reviews[0].target_item_id) is not None
    assert pericial_planning_from_mapping(payloads["planning"]).decisions
    assert inspection_session_from_mapping(payloads["inspection"]).photos
    assert technical_snapshot_from_mapping(payloads["technical"]).decisions
    assert report_snapshot_from_mapping(payloads["report"]).state.value == "APPROVED"
    delivery = delivery_snapshot_from_mapping(payloads["delivery"])
    assert delivery.state is DeliveryState.DELIVERED
    assert delivery.artifacts[0].format.value == "DOCX"
    budget = budget_snapshot_from_mapping(payloads["budget"])
    assert budget.court_approvals and budget.payments
    assert not ({"budget_id", "court_approvals", "payments"} & set(payloads["technical"]))
    assert not ({"budget_id", "court_approvals", "payments"} & set(payloads["delivery"]["binding"]))

    changed_binding = replace(delivery.binding, report_digest="f" * 64)
    stale = reconcile_delivery(delivery, changed_binding)
    assert stale.state is DeliveryState.STALE and stale.stale_origin_state is DeliveryState.DELIVERED

    staging = RecoveryStaging.create(tmp_path / "recovery")
    receipt = RestoreWorkspaceBackup(staging).execute(package)
    assert receipt.artifact_revisions == len(verified.artifact_revisions)
    assert receipt.private_contents == len(verified.private_contents)
    reopened = staging.revisions.list_workspace(WorkspaceId.parse(verified.workspace.workspace_id))
    assert len(reopened) == len(verified.artifact_revisions)
    for actual, expected in zip(reopened, verified.artifact_revisions, strict=True):
        assert (actual.artifact_kind, actual.artifact_id, actual.revision, actual.checksum_sha256) == (
            expected["artifact_kind"], expected["artifact_id"], expected["revision"], expected["checksum_sha256"],
        )
        assert thaw_payload(actual.payload) == expected["payload"]
    for expected in verified.private_contents:
        with staging.private_contents.open_content(
            WorkspaceId.parse(verified.workspace.workspace_id),
            PrivateContentId.parse(expected["content_id"]),
        ) as opened:
            assert opened.stream.read() == base64.b64decode(expected["content_base64"])
    staging.close()


def test_d1_d6_d7_backup_rejects_missing_source_final_word_or_template_bytes() -> None:
    package, payloads = _longitudinal_backup()
    missing_authorities = (
        payloads["case"]["documents"][0]["storage_content_id"],
        payloads["delivery"]["template_content_id"],
        payloads["delivery"]["artifacts"][0]["content_id"],
    )
    for missing_id in missing_authorities:
        mapping = json.loads(package)
        mapping["private_contents"] = [item for item in mapping["private_contents"] if item["content_id"] != missing_id]
        mapping["member_hashes"]["private_contents"] = _digest(mapping["private_contents"])
        mapping["manifest_sha256"] = _digest({key: value for key, value in mapping.items() if key != "manifest_sha256"})
        try:
            VerifyWorkspaceBackup().execute(_canonical(mapping))
        except RepositoryIntegrityError as exc:
            assert "authority" in str(exc)
        else:
            raise AssertionError("missing delivery authority was accepted")


def test_d2_d6_generic_authority_attacks_fail_closed() -> None:
    package, _ = _longitudinal_backup()
    mapping = json.loads(package)
    delivery_record = [item for item in mapping["artifact_revisions"] if item["artifact_kind"] == "DELIVERY_SNAPSHOT_V1"][-1]
    delivery_record["payload"]["binding"]["report_approval_id"] = "NONEXISTENT-APPROVAL"
    delivery_record["payload"]["binding"]["professional_id"] = "NONEXISTENT-PROFESSIONAL"
    try:
        VerifyWorkspaceBackup().execute(_reseal(mapping))
    except RepositoryIntegrityError as exc:
        assert "professional authority" in str(exc)
    else:
        raise AssertionError("forged professional Delivery authority was accepted")

    foreign = json.loads(package)
    budget_record = next(item for item in foreign["artifact_revisions"] if item["artifact_kind"] == "BUDGET_SNAPSHOT_V1")
    budget_record["payload"]["workspace_id"] = "22222222-2222-4222-8222-222222222222"
    try:
        VerifyWorkspaceBackup().execute(_reseal(foreign))
    except RepositoryIntegrityError as exc:
        assert "another workspace" in str(exc)
    else:
        raise AssertionError("cross-workspace canonical payload was accepted")


def test_d6_final_word_bytes_are_revalidated_after_recovery() -> None:
    package, payloads = _longitudinal_backup()
    mapping = json.loads(package)
    content_id = payloads["delivery"]["artifacts"][0]["content_id"]
    private = next(item for item in mapping["private_contents"] if item["content_id"] == content_id)
    forged = b"not-a-docx"
    private["content_base64"] = base64.b64encode(forged).decode("ascii")
    private["byte_size"] = len(forged)
    private["checksum_sha256"] = hashlib.sha256(forged).hexdigest()
    for delivery_record in [item for item in mapping["artifact_revisions"] if item["artifact_kind"] == "DELIVERY_SNAPSHOT_V1"]:
        for artifact in delivery_record["payload"]["artifacts"]:
            artifact["byte_size"] = len(forged)
            artifact["checksum_sha256"] = hashlib.sha256(forged).hexdigest()
    try:
        VerifyWorkspaceBackup().execute(_reseal(mapping))
    except RepositoryIntegrityError as exc:
        assert "final artifact" in str(exc)
    else:
        raise AssertionError("invalid final Word bytes were accepted")


def test_d8_runtime_and_persisted_product_text_has_no_mojibake() -> None:
    governed = (
        ROOT / "config" / "core-invariants.json",
        ROOT / "scripts" / "backend_contract",
        ROOT / "scripts" / "auditoria_pericial",
        ROOT / "scripts" / "extracao_pje",
        ROOT / "scripts" / "redacao_pericial",
        ROOT / "scripts" / "vistoria_estruturada",
        ROOT / "frontend" / "src",
    )
    forbidden = ("Ãƒ", "Ã£", "Ã§", "Ã©", "Ã¡", "Ã­", "Ã³", "Ãµ", "Ãª", "Ã´", "Â", "â€", "â‚¬", "�")
    failures: list[str] = []
    for boundary in governed:
        paths = (boundary,) if boundary.is_file() else tuple(boundary.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix not in {".json", ".py", ".ts", ".tsx"} or ".test." in path.name:
                continue
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in forbidden):
                failures.append(str(path.relative_to(ROOT)))
    assert failures == []

    package, payloads = _longitudinal_backup()
    assert not any(token in package.decode("utf-8") for token in forbidden)
    runtime_text = " ".join(
        [item.text for item in case_analysis_from_mapping(payloads["case"]).material_items]
        + [item.text for item in report_snapshot_from_mapping(payloads["report"]).claims]
    )
    assert not any(token in runtime_text for token in forbidden)


def test_d5_pending_offline_authority_blocks_backup_before_workspace_read() -> None:
    class Workspaces:
        def get(self, _workspace_id):
            raise AssertionError("workspace was read before pending-offline refusal")

    service = CreateWorkspaceBackup(Workspaces(), object(), None, object(), lambda _workspace: (_ for _ in ()).throw(ValueError("pending offline")))
    try:
        service.execute(WorkspaceId.parse(WORKSPACE_ID))
    except ValueError as exc:
        assert str(exc) == "pending offline"
    else:
        raise AssertionError("pending offline work did not block backup")


def test_d9_d10_maturity_truth_is_derived_and_stage_10_remains_closed() -> None:
    maturity = json.loads((ROOT / "config" / "product-maturity-v1.json").read_text(encoding="utf-8"))
    stages = maturity["stages"]
    assert [item["stage"] for item in stages] == list(range(13))
    stage_10 = stages[10]
    assert stage_10 == {
        "stage": 10,
        "name": "AI_AUTOMATION_FOUNDATION",
        "status": "NOT_IMPLEMENTED_OR_NOT_PROVEN",
    }
    derived_complete = all(item["status"] == "COMPLETE" for item in stages)
    assert maturity["product_roadmap_stage_0_to_12_complete"] is derived_complete is False
    assert maturity["stage_10_authorized"] is False

    report = (ROOT / "docs" / "PRODUCT_MATURITY_REPORT_V1.md").read_text(encoding="utf-8")
    assert "Stage 10 is `NOT_IMPLEMENTED_OR_NOT_PROVEN`" in report
    assert "PRODUCT_ROADMAP_STAGE_0_TO_12_COMPLETE = FALSE" in report
