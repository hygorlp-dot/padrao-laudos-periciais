"""The next version of a superseded or stale report (#239, reproduced P1).

A report superseded in review, or bound to authorities that changed after it
was written, refused every amendment, review and restart: the expert was left
with no way to continue short of a new workspace, while the screen told them to
"start a new version" that did not exist.  The next version is a draft bound
to the current authorities; what they still support is carried over, what they
no longer support is dropped and reported, and every review starts again.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from scripts.backend_contract.application.models import _freeze_payload
from scripts.backend_contract.application.ports import RepositoryConflict
from scripts.backend_contract.application.report_foundation import SaveReportSnapshot, StartReportVersion
from scripts.backend_contract.report_foundation import (
    ReportReviewDecision,
    ReportState,
    ReviewAction,
    report_snapshot_to_mapping,
)
from tests.test_report_foundation_v1 import bound_report, upstreams


def _superseded():
    report = bound_report()
    decision = ReportReviewDecision("REPORT-REVIEW-003", ReviewAction.SUPERSEDE, report.expert_profile.profile_id, "Correção pedida pelo juízo.", "2026-08-31T12:00:00+00:00", "REPORT-REVIEW-002")
    return replace(report, review_decisions=(*report.review_decisions, decision), state=ReportState.SUPERSEDED, coverage=replace(report.coverage, complete=False, reasons=("Superseded.",)))


def _service(stored, *, records=None, inspection=None):
    default_records, case, default_inspection, technical, profile = upstreams()
    records = records or default_records
    inspection = inspection or default_inspection
    stored_record = SimpleNamespace(revision=4, payload=_freeze_payload(report_snapshot_to_mapping(stored)))
    appended = []

    def append_if_latest(**kwargs):
        appended.append(kwargs)
        return SimpleNamespace(revision=5, created_at=kwargs["created_at"])

    latest = SimpleNamespace(execute=lambda *_args: stored_record)
    readers = (
        SimpleNamespace(execute=lambda _w: (records[0], case)),
        SimpleNamespace(execute=lambda _w: (records[1], inspection)),
        SimpleNamespace(execute=lambda _w: (records[2], technical)),
        SimpleNamespace(execute=lambda _w: (records[3], profile)),
    )
    ids = SimpleNamespace(new_uuid=lambda: UUID("99999999-9999-4999-8999-999999999999"))
    save = SaveReportSnapshot(
        SimpleNamespace(append_if_latest=append_if_latest), *readers, latest, nullcontext,
        SimpleNamespace(now=lambda: datetime(2026, 9, 26, 13, 0, tzinfo=UTC)), ids,
    )
    return StartReportVersion(latest, *readers, save, ids), appended


def test_a_superseded_report_opens_a_draft_that_keeps_what_its_sources_support() -> None:
    stored = _superseded()
    service, appended = _service(stored)
    _record, draft, dropped = service.execute(stored.workspace_id, expected_revision=4)
    assert (draft.state, draft.review_decisions, draft.upstream_stale) == (ReportState.DRAFT, (), False)
    assert draft.claims == stored.claims and draft.answers == stored.answers and draft.report_id == stored.report_id
    assert dropped == {"claims": 0, "answers": 0, "context_fields": [], "findings_table": False, "site_location": False}
    assert appended[0]["expected_revision"] == 4 and appended[0]["payload"]["state"] == "DRAFT"


def test_a_stale_report_is_rebound_and_drops_what_the_current_sources_no_longer_hold() -> None:
    records, *_ = upstreams()
    moved = (records[0], SimpleNamespace(**{**vars(records[1]), "revision": 3, "checksum_sha256": "e" * 64}), records[2], records[3])
    stored = bound_report()
    orphan = replace(stored.claims[1], provenance=(replace(stored.claims[1].provenance[0], source_id="CLAIM-GONE"),))
    stored = replace(stored, claims=(stored.claims[0], orphan, *stored.claims[2:]))
    service, _ = _service(stored, records=moved)
    _record, draft, dropped = service.execute(stored.workspace_id, expected_revision=4)
    assert dropped["claims"] == 1 and orphan.claim_id not in {item.claim_id for item in draft.claims}
    observed = next(item for item in draft.claims if item.provenance[0].source_kind == "FIELD_OBSERVATION")
    assert observed.provenance[0].source_revision == 3 and draft.source_snapshot.inspection_session_revision == 3
    assert draft.state is ReportState.DRAFT and not draft.review_decisions


def test_a_current_report_or_a_moved_revision_opens_no_version() -> None:
    stored = bound_report()
    service, appended = _service(stored)
    with pytest.raises(ValueError, match="superseded or stale"):
        service.execute(stored.workspace_id, expected_revision=4)
    with pytest.raises(RepositoryConflict):
        _service(_superseded())[0].execute(stored.workspace_id, expected_revision=3)
    assert appended == []
