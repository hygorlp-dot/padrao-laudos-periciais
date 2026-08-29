from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

import pytest
from hypothesis import given, settings, strategies as st

from scripts.backend_contract.application.models import (
    PrivateContentId,
    ProcessCaseData,
    ProcessCaseSnapshot,
    WorkspaceId,
)
from scripts.backend_contract.application.ports import RepositoryConflict
from scripts.backend_contract.application.process_metadata import (
    DocumentExtractionSummary,
    PdfTextExtractionState,
    PdfTextPage,
    PdfTextResult,
    ProcessMetadataReview,
    aggregate_process_metadata,
    document_metadata_payload,
    extract_process_metadata,
)
from scripts.backend_contract.application.services import ConfirmProcessMetadataSourceSpan


WORKSPACE_A = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
WORKSPACE_B = WorkspaceId(UUID("22222222-2222-4222-8222-222222222222"))
DOCUMENT_ID = PrivateContentId(UUID("33333333-3333-4333-8333-333333333333"))
EXTRACTED_AT = "2026-08-28T18:00:00+00:00"


class FixedClock:
    def now(self):
        return datetime(2026, 8, 28, 18, 5, tzinfo=UTC)


class SequenceIds:
    def __init__(self):
        self.value = 0

    def new_uuid(self):
        self.value += 1
        return UUID(f"00000000-0000-4000-8000-{self.value:012d}")


class StaticReview:
    def __init__(self, review):
        self.review = review

    def execute(self, _workspace_id):
        return self.review


class StaticProcessCase:
    def __init__(self, workspace_id=WORKSPACE_A, revision=None, data=None):
        self.snapshot = ProcessCaseSnapshot(
            workspace_id,
            revision,
            None if revision is None else "2026-08-28T18:01:00+00:00",
            ProcessCaseData.empty() if data is None else data,
        )

    def execute(self, _workspace_id):
        return self.snapshot


class RecordingSave:
    def __init__(self):
        self.calls = []
        self.atomic_calls = []

    def execute(self, workspace_id, data, expected_revision):
        self.calls.append((workspace_id, data, expected_revision))
        return ProcessCaseSnapshot(
            workspace_id,
            1 if expected_revision is None else expected_revision + 1,
            "2026-08-28T18:05:00+00:00",
            data,
        )

    def execute_with_source_confirmation(
        self,
        workspace_id,
        data,
        expected_revision,
        *,
        confirmation,
        source_expectations,
    ):
        self.atomic_calls.append(
            (
                workspace_id,
                data,
                expected_revision,
                confirmation,
                source_expectations,
            )
        )
        return ProcessCaseSnapshot(
            workspace_id,
            1 if expected_revision is None else expected_revision + 1,
            "2026-08-28T18:05:00+00:00",
            data,
        )


class RecordingRevisions:
    def __init__(self):
        self.calls = []

    def append(self, **values):
        self.calls.append(values)
        return object()


def review_for(source: str, *, workspace_id=WORKSPACE_A):
    document = extract_process_metadata(
        workspace_id=workspace_id,
        document_id=DOCUMENT_ID,
        original_filename="autos-sinteticos.pdf",
        text=PdfTextResult(
            PdfTextExtractionState.AVAILABLE,
            (PdfTextPage(1, source),),
            document_sha256="a" * 64,
        ),
        extracted_at=EXTRACTED_AT,
    )
    aggregate = aggregate_process_metadata((document,))
    return ProcessMetadataReview(
        workspace_id,
        aggregate.state,
        None,
        MappingProxyType(dict(aggregate.fields)),
        (
            DocumentExtractionSummary(
                DOCUMENT_ID,
                "autos-sinteticos.pdf",
                PdfTextExtractionState.AVAILABLE,
            ),
        ),
        "f" * 64,
        (document_metadata_payload(document),),
        (
            {
                "artifact_kind": "PROCESS_METADATA_EXTRACTION",
                "artifact_id": str(DOCUMENT_ID),
                "revision": 1,
                "checksum_sha256": "c" * 64,
            },
        ),
    )


def service_for(review, *, process_case=None):
    save = RecordingSave()
    revisions = RecordingRevisions()
    service = ConfirmProcessMetadataSourceSpan(
        StaticProcessCase() if process_case is None else process_case,
        save,
        StaticReview(review),
    )
    return service, save, revisions


@pytest.mark.parametrize(
    ("source", "selected"),
    (
        ("AUTOR: PARTE ALFA", "PARTE ALFA"),
        ("AUTOR: PARTE ALFA REPRESENTANTE BETA", "PARTE ALFA"),
        ("AUTORA: CONCEI\u00c7\u00c3O A\u0301LFA \ufb01LHA", "CONCEI\u00c7\u00c3O A\u0301LFA \ufb01LHA"),
    ),
)
def test_server_derives_exact_human_confirmed_value_from_trusted_source_offsets(
    source,
    selected,
):
    review = review_for(source)
    evidence = review.fields["parte_requerente"].evidence[0]
    service, save, revisions = service_for(review)
    start = evidence.source_text.index(selected)

    snapshot = service.execute(
        workspace_id=WORKSPACE_A,
        field_name="parte_requerente",
        evidence_id=evidence.evidence_id,
        source_start=start,
        source_end=start + len(selected),
        expected_source_revision=review.extraction_fingerprint,
        expected_revision=None,
    )

    assert snapshot.data.parte_requerente == selected
    assert save.calls == []
    assert save.atomic_calls[0][1].parte_requerente == selected
    payload = save.atomic_calls[0][3]["payload"]
    assert payload["decision"] == "HUMAN_CONFIRMED"
    assert payload["selected_value"] == selected
    assert payload["source_start"] == evidence.source_start + start
    assert payload["source_end"] == evidence.source_start + start + len(selected)
    assert payload["document_id"] == str(DOCUMENT_ID)
    assert payload["document_sha256"] == "a" * 64
    assert payload["source_page"] == 1
    assert save.atomic_calls[0][4]
    assert revisions.calls == []


@pytest.mark.parametrize(
    ("start", "end"),
    ((7, 7), (7, 200), (18, 7), (-1, 4)),
)
def test_invalid_source_span_is_rejected_without_mutation(start, end):
    review = review_for("AUTOR: PARTE ALFA REPRESENTANTE BETA")
    evidence = review.fields["parte_requerente"].evidence[0]
    service, save, revisions = service_for(review)

    with pytest.raises(ValueError):
        service.execute(
            workspace_id=WORKSPACE_A,
            field_name="parte_requerente",
            evidence_id=evidence.evidence_id,
            source_start=start,
            source_end=end,
            expected_source_revision=review.extraction_fingerprint,
            expected_revision=None,
        )

    assert save.calls == []
    assert revisions.calls == []


def test_stale_source_revision_is_rejected_without_mutation():
    review = review_for("AUTOR: PARTE ALFA")
    evidence = review.fields["parte_requerente"].evidence[0]
    service, save, revisions = service_for(review)

    with pytest.raises(RepositoryConflict):
        service.execute(
            workspace_id=WORKSPACE_A,
            field_name="parte_requerente",
            evidence_id=evidence.evidence_id,
            source_start=7,
            source_end=17,
            expected_source_revision="0" * 64,
            expected_revision=None,
        )

    assert save.calls == []
    assert revisions.calls == []


def test_cross_workspace_evidence_is_rejected_without_mutation():
    review = review_for("AUTOR: PARTE ALFA", workspace_id=WORKSPACE_A)
    evidence = review.fields["parte_requerente"].evidence[0]
    service, save, revisions = service_for(review)

    with pytest.raises(ValueError):
        service.execute(
            workspace_id=WORKSPACE_B,
            field_name="parte_requerente",
            evidence_id=evidence.evidence_id,
            source_start=7,
            source_end=17,
            expected_source_revision=review.extraction_fingerprint,
            expected_revision=None,
        )

    assert save.calls == []
    assert revisions.calls == []


def test_non_party_field_cannot_use_source_span_confirmation():
    review = review_for("AUTOR: PARTE ALFA")
    evidence = review.fields["parte_requerente"].evidence[0]
    service, save, revisions = service_for(review)

    with pytest.raises(ValueError):
        service.execute(
            workspace_id=WORKSPACE_A,
            field_name="numero_processo",
            evidence_id=evidence.evidence_id,
            source_start=7,
            source_end=17,
            expected_source_revision=review.extraction_fingerprint,
            expected_revision=None,
        )

    assert save.calls == []
    assert revisions.calls == []


def test_cancel_is_client_local_and_causes_no_application_mutation():
    review = review_for("AUTOR: PARTE ALFA")
    _service, save, revisions = service_for(review)

    assert save.calls == []
    assert revisions.calls == []


@settings(max_examples=30, deadline=None)
@given(
    st.text(
        alphabet=tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ áçã") + ("\u0301", "\ufb01"),
        min_size=1,
        max_size=24,
    ).filter(lambda value: bool(value.strip()))
)
def test_exact_unicode_source_slice_is_reversible_for_supported_text(value):
    source = f"AUTOR: {value}"
    review = review_for(source)
    evidence = review.fields["parte_requerente"].evidence[0]
    service, _save, _revisions = service_for(review)
    start = evidence.source_text.index(value)

    snapshot = service.execute(
        workspace_id=WORKSPACE_A,
        field_name="parte_requerente",
        evidence_id=evidence.evidence_id,
        source_start=start,
        source_end=start + len(value),
        expected_source_revision=review.extraction_fingerprint,
        expected_revision=None,
    )

    assert snapshot.data.parte_requerente == value
