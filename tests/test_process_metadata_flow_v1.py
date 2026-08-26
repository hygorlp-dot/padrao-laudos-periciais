from __future__ import annotations

import http.client
import json
from datetime import UTC, datetime
from io import BytesIO
from uuid import UUID

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scripts.backend_contract.application.content import OpenPrivateContent, SeekableContent
from scripts.backend_contract.application.models import (
    ArtifactRevision,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    ProcessCaseData,
    WorkspaceId,
    thaw_payload,
)
from scripts.backend_contract.application.process_metadata import (
    FieldExtractionState,
    PageExtractionMode,
    PageProcessingStatus,
    PdfTextExtractionState,
    PdfTextPage,
    PdfTextResult,
    document_metadata_from_payload,
    document_metadata_payload,
    extract_process_metadata,
)
from scripts.backend_contract.application.ports import RepositoryIntegrityError
from scripts.backend_contract.application.services import (
    ConfirmProcessMetadata,
    GetProcessMetadataReview,
    ImportCaseDocumentWithMetadata,
)
from scripts.backend_contract.local_api.transport import LocalApi, LocalApiServices
from scripts.backend_contract.product_bridge.composition import build_product_runtime


WORKSPACE_ID = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
DOCUMENT_ID = PrivateContentId(UUID("22222222-2222-4222-8222-222222222222"))
TOKEN = "process-metadata-flow-token-with-entropy"
PDF = b"%PDF-1.7\nsynthetic\n%%EOF\n"


def text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(
        b"BT /F1 10 Tf 36 750 Td ("
        + escaped.encode("latin-1", errors="replace")
        + b") Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    target = BytesIO()
    writer.write(target)
    return target.getvalue()


def product_request(runtime, method: str, target: str, body: bytes = b"", headers=None):
    connection = http.client.HTTPConnection(*runtime.address, timeout=10)
    request_headers = {} if headers is None else dict(headers)
    if method == "POST":
        request_headers.setdefault("Origin", runtime.origin)
        request_headers.setdefault("Sec-Fetch-Site", "same-origin")
        request_headers.setdefault("Content-Length", str(len(body)))
    connection.request(method, target, body=body or None, headers=request_headers)
    response = connection.getresponse()
    payload = response.read()
    status = response.status
    content_type = response.getheader("Content-Type") or ""
    connection.close()
    return status, content_type, payload


class FixedClock:
    def now(self):
        return datetime(2026, 8, 26, 12, 30, tzinfo=UTC)


class SequenceIds:
    def __init__(self):
        self.value = 0

    def new_uuid(self):
        self.value += 1
        return UUID(f"00000000-0000-4000-8000-{self.value:012d}")


class MemoryRevisions:
    def __init__(self):
        self.records = []

    def append(self, **values):
        existing = [
            record
            for record in self.records
            if record.workspace_id == values["workspace_id"]
            and record.artifact_kind == values["artifact_kind"]
            and record.artifact_id == values["artifact_id"]
        ]
        record = ArtifactRevision(
            **values,
            revision=len(existing) + 1,
            checksum_sha256="a" * 64,
        )
        self.records.append(record)
        return record

    def latest(self, workspace_id, artifact_kind, artifact_id):
        matching = [
            record
            for record in self.records
            if record.workspace_id == workspace_id
            and record.artifact_kind == artifact_kind
            and record.artifact_id == artifact_id
        ]
        return matching[-1] if matching else None


class ExistingWorkspace:
    def get(self, workspace_id):
        return object() if workspace_id == WORKSPACE_ID else None


class StaticTextExtractor:
    def extract(self, source, **context):
        assert source.read(5) == b"%PDF-"
        source.seek(0)
        return PdfTextResult(
            PdfTextExtractionState.AVAILABLE,
            (
                PdfTextPage(
                    1,
                    "TRIBUNAL REGIONAL FEDERAL DA 5 REGIAO\n"
                    "1 VARA FEDERAL DA SUBSECAO JUDICIARIA DE RECIFE/PE\n"
                    "PROCESSO: 7654321-55.2025.4.05.0001\n"
                    "AUTOR: Parte Sintetica\nREU: Parte Contraria",
                ),
            ),
            document_sha256=context["document_sha256"],
        )


class ImportOnly:
    def execute(self, **kwargs):
        from scripts.backend_contract.application.models import (
            PrivateContentMetadata,
            PrivateContentOrigin,
        )

        return PrivateContentMetadata(
            workspace_id=WORKSPACE_ID,
            content_id=DOCUMENT_ID,
            original_filename=kwargs["original_filename"],
            byte_size=len(PDF),
            checksum_sha256="b" * 64,
            media_type="application/pdf",
            imported_at="2026-08-26T12:30:00+00:00",
            origin=PrivateContentOrigin.USER_IMPORT,
        )


class OpenStored:
    def __init__(self, content=PDF, metadata=None):
        self.content = content
        self.metadata = metadata

    def execute(self, workspace_id, content_id):
        metadata = self.metadata or PrivateContentMetadata(
            workspace_id=workspace_id,
            content_id=content_id,
            original_filename="autos.pdf",
            byte_size=len(self.content),
            checksum_sha256="b" * 64,
            media_type="application/pdf",
            imported_at="2026-08-26T12:30:00+00:00",
            origin=PrivateContentOrigin.USER_IMPORT,
        )
        stream = BytesIO(self.content)
        return OpenPrivateContent(metadata, stream, stream.close)


class ListDocuments:
    def __init__(self, records):
        self.records = records

    def execute(self, workspace_id):
        assert workspace_id == WORKSPACE_ID
        return self.records


class SaveProcess:
    def __init__(self):
        self.calls = []

    def execute(self, workspace_id, data, expected_revision):
        from scripts.backend_contract.application.models import ProcessCaseSnapshot

        self.calls.append((workspace_id, data, expected_revision))
        return ProcessCaseSnapshot(
            workspace_id,
            2,
            "2026-08-26T12:30:00+00:00",
            data,
        )


def test_import_persists_redacted_field_provenance_separately_from_effective_data():
    revisions = MemoryRevisions()
    importer = ImportCaseDocumentWithMetadata(
        documents=ImportOnly(),
        document_streams=OpenStored(),
        extractor=StaticTextExtractor(),
        revisions=revisions,
        clock=FixedClock(),
        ids=SequenceIds(),
    )

    record = importer.execute(
        workspace_id=WORKSPACE_ID,
        original_filename="autos.pdf",
        content=SeekableContent(BytesIO(PDF), len(PDF)),
        media_type="application/pdf",
    )

    assert record.content_id == DOCUMENT_ID
    assert len(revisions.records) == 1
    extraction = revisions.records[0]
    assert extraction.artifact_kind == "PROCESS_METADATA_EXTRACTION"
    assert extraction.artifact_id == str(DOCUMENT_ID)
    payload = thaw_payload(extraction.payload)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["schema_version"] == 2
    assert payload["document_sha256"] == "b" * 64
    assert payload["page_evidence"][0]["document_sha256"] == "b" * 64
    assert payload["document_id"] == str(DOCUMENT_ID)
    assert payload["source_filename"] == "autos.pdf"
    assert payload["fields"]["numero_processo"]["value"] == "7654321-55.2025.4.05.0001"
    assert "private" not in serialized.lower()
    assert "path" not in serialized.lower()
    assert "TRIBUNAL REGIONAL" not in serialized


def test_review_aggregates_persisted_extractions_and_confirmation_is_separate():
    revisions = MemoryRevisions()
    importer = ImportCaseDocumentWithMetadata(
        ImportOnly(), OpenStored(), StaticTextExtractor(), revisions, FixedClock(), SequenceIds()
    )
    metadata = importer.execute(
        workspace_id=WORKSPACE_ID,
        original_filename="autos.pdf",
        content=SeekableContent(BytesIO(PDF), len(PDF)),
        media_type="application/pdf",
    )
    review_service = GetProcessMetadataReview(
        ExistingWorkspace(), ListDocuments((metadata,)), revisions
    )

    before = review_service.execute(WORKSPACE_ID)
    assert before.state == "EXTRACTED"
    assert before.confirmed_revision is None
    assert before.fields["numero_processo"].value == "7654321-55.2025.4.05.0001"

    save = SaveProcess()
    confirmation = ConfirmProcessMetadata(
        save, review_service, revisions, FixedClock(), SequenceIds()
    )
    corrected = ProcessCaseData.from_mapping(
        {
            "numero_processo": "7654321-55.2025.4.05.0001",
            "ramo_justica": "Justiça Federal",
            "tribunal": "Tribunal Regional Federal da 5ª Região",
            "vara": "2ª Vara Federal",
            "comarca_municipio": "Recife",
            "uf": "PE",
            "parte_requerente": "Parte Sintética corrigida",
            "parte_requerida": "Parte Contrária",
        }
    )
    snapshot = confirmation.execute(WORKSPACE_ID, corrected, None)

    assert snapshot.data.vara == "2ª Vara Federal"
    after = review_service.execute(WORKSPACE_ID)
    assert after.state == "CONFIRMED"
    assert after.confirmed_revision == 2
    assert after.fields["vara"].value == "1ª Vara Federal"
    assert after.fields["parte_requerente"].value == "Parte Sintetica"
    assert revisions.records[0].payload == before.document_payloads[0]


def test_textless_document_is_exposed_as_controlled_document_state():
    revisions = MemoryRevisions()
    extractor = type(
        "TextlessExtractor",
        (),
        {
                "extract": lambda _self, _source, **_context: PdfTextResult(
                    PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE,
                    (),
                    document_sha256=_context["document_sha256"],
                )
        },
    )()
    importer = ImportCaseDocumentWithMetadata(
        ImportOnly(),
        OpenStored(
            metadata=ImportOnly().execute(
                original_filename="imagem-digitalizada.pdf"
            )
        ),
        extractor,
        revisions,
        FixedClock(),
        SequenceIds(),
    )
    metadata = importer.execute(
        workspace_id=WORKSPACE_ID,
        original_filename="imagem-digitalizada.pdf",
        content=SeekableContent(BytesIO(PDF), len(PDF)),
        media_type="application/pdf",
    )

    review = GetProcessMetadataReview(
        ExistingWorkspace(), ListDocuments((metadata,)), revisions
    ).execute(WORKSPACE_ID)

    assert review.state == "PARTIAL"
    assert len(review.documents) == 1
    assert review.documents[0].document_id == DOCUMENT_ID
    assert review.documents[0].source_filename == "imagem-digitalizada.pdf"
    assert (
        review.documents[0].text_state
        is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
    )


def test_missing_extraction_is_error_and_new_evidence_invalidates_confirmation():
    revisions = MemoryRevisions()
    importer = ImportCaseDocumentWithMetadata(
        ImportOnly(), OpenStored(), StaticTextExtractor(), revisions, FixedClock(), SequenceIds()
    )
    metadata = importer.execute(
        workspace_id=WORKSPACE_ID,
        original_filename="autos.pdf",
        content=SeekableContent(BytesIO(PDF), len(PDF)),
        media_type="application/pdf",
    )
    documents = ListDocuments((metadata,))
    review_service = GetProcessMetadataReview(ExistingWorkspace(), documents, revisions)
    confirmation = ConfirmProcessMetadata(
        SaveProcess(), review_service, revisions, FixedClock(), SequenceIds()
    )
    confirmation.execute(WORKSPACE_ID, ProcessCaseData.empty(), None)
    assert review_service.execute(WORKSPACE_ID).state == "CONFIRMED"

    updated = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_ID,
        original_filename="autos.pdf",
        text=PdfTextResult(
            PdfTextExtractionState.AVAILABLE,
            (PdfTextPage(1, "AUTOR: Outra Parte Sintetica"),),
            document_sha256="b" * 64,
        ),
        extracted_at="2026-08-26T12:31:00+00:00",
    )
    revisions.append(
        workspace_id=WORKSPACE_ID,
        artifact_kind="PROCESS_METADATA_EXTRACTION",
        artifact_id=str(DOCUMENT_ID),
        revision_id="00000000-0000-4000-8000-000000000099",
        created_at="2026-08-26T12:31:00+00:00",
        payload=document_metadata_payload(updated),
    )
    assert review_service.execute(WORKSPACE_ID).state != "CONFIRMED"

    orphan = PrivateContentMetadata(
        workspace_id=WORKSPACE_ID,
        content_id=PrivateContentId(UUID("44444444-4444-4444-8444-444444444444")),
        original_filename="sem-extracao.pdf",
        byte_size=len(PDF),
        checksum_sha256="c" * 64,
        media_type="application/pdf",
        imported_at="2026-08-26T12:32:00+00:00",
        origin=PrivateContentOrigin.USER_IMPORT,
    )
    documents.records = (metadata, orphan)
    failed = review_service.execute(WORKSPACE_ID)
    assert failed.state == "ERROR"
    assert failed.documents[-1].text_state is PdfTextExtractionState.ERROR


def test_import_extracts_only_from_the_verified_persisted_snapshot():
    original = PDF
    caller = BytesIO(original)
    seen = []

    class MutatingImport(ImportOnly):
        def execute(self, **kwargs):
            record = super().execute(**kwargs)
            kwargs["content"].stream.seek(0)
            kwargs["content"].stream.write(b"%PDF-TAMPERED-1234")
            kwargs["content"].stream.seek(0)
            return record

    class CaptureExtractor:
        def extract(self, source, **context):
            seen.append(source.read())
            return PdfTextResult(
                PdfTextExtractionState.AVAILABLE,
                (PdfTextPage(1, "TRIBUNAL REGIONAL FEDERAL PROCESSO"),),
                document_sha256=context["document_sha256"],
            )

    revisions = MemoryRevisions()
    ImportCaseDocumentWithMetadata(
        MutatingImport(), OpenStored(original), CaptureExtractor(), revisions,
        FixedClock(), SequenceIds(),
    ).execute(
        workspace_id=WORKSPACE_ID,
        original_filename="autos.pdf",
        content=SeekableContent(caller, len(original)),
        media_type="application/pdf",
    )

    assert seen == [original]


def test_review_rejects_extraction_bound_to_a_different_document_sha():
    revisions = MemoryRevisions()
    metadata = ImportOnly().execute(original_filename="autos.pdf")
    extracted = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_ID,
        original_filename="autos.pdf",
        text=PdfTextResult(
            PdfTextExtractionState.AVAILABLE,
            (PdfTextPage(1, "PROCESSO: 7654321-55.2025.4.05.0001"),),
            document_sha256="c" * 64,
        ),
        extracted_at="2026-08-26T12:30:00+00:00",
    )
    revisions.append(
        workspace_id=WORKSPACE_ID,
        artifact_kind="PROCESS_METADATA_EXTRACTION",
        artifact_id=str(DOCUMENT_ID),
        revision_id="00000000-0000-4000-8000-000000000001",
        created_at="2026-08-26T12:30:00+00:00",
        payload=document_metadata_payload(extracted),
    )

    with pytest.raises(RepositoryIntegrityError, match="checksum|material"):
        GetProcessMetadataReview(
            ExistingWorkspace(), ListDocuments((metadata,)), revisions
        ).execute(WORKSPACE_ID)


def test_legacy_extraction_is_explicitly_rebound_to_the_immutable_document_identity():
    extracted = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_ID,
        original_filename="autos.pdf",
        text=PdfTextResult(
            PdfTextExtractionState.AVAILABLE,
            (PdfTextPage(1, "PROCESSO: 7654321-55.2025.4.05.0001"),),
            document_sha256="b" * 64,
        ),
        extracted_at="2026-08-26T12:30:00+00:00",
    )
    legacy = json.loads(json.dumps(document_metadata_payload(extracted)))
    legacy["schema_version"] = 1
    legacy.pop("document_sha256")
    legacy.pop("page_evidence")
    v2_only = {
        "extraction_mode", "ocr_engine", "engine_version", "model_version",
        "ocr_confidence", "bounding_box",
    }
    for field in legacy["fields"].values():
        for evidence in field["evidence"]:
            for key in v2_only:
                evidence.pop(key)

    revision = MemoryRevisions().append(
        workspace_id=WORKSPACE_ID,
        artifact_kind="PROCESS_METADATA_EXTRACTION",
        artifact_id=str(DOCUMENT_ID),
        revision_id="00000000-0000-4000-8000-000000000001",
        created_at="2026-08-26T12:30:00+00:00",
        payload=legacy,
    )
    restored = document_metadata_from_payload(
        revision.payload, legacy_document_sha256="b" * 64
    )

    assert restored.document_sha256 == "b" * 64
    assert restored.fields["numero_processo"].evidence[0].engine_version == ""


def test_partial_document_cannot_be_reported_as_fully_extracted():
    document = extract_process_metadata(
        workspace_id=WORKSPACE_ID,
        document_id=DOCUMENT_ID,
        original_filename="autos.pdf",
        text=PdfTextResult(
            PdfTextExtractionState.PARTIAL,
            (
                PdfTextPage(
                    1,
                    "PROCESSO: 7654321-55.2025.4.05.0001\n"
                    "1 VARA FEDERAL COMARCA DE RECIFE/PE\n"
                    "AUTOR: Parte A\nREU: Parte B",
                ),
                PdfTextPage(
                    2,
                    "",
                    extraction_mode=PageExtractionMode.OCR,
                    engine="SYNTHETIC_OCR",
                    engine_version="1.0",
                    model_version="synthetic-pt-v1",
                    processing_status=PageProcessingStatus.OCR_FAILED,
                ),
            ),
            document_sha256="b" * 64,
        ),
        extracted_at="2026-08-26T12:30:00+00:00",
    )
    assert all(
        field.state is FieldExtractionState.CONFIDENT
        for field in document.fields.values()
    )

    from scripts.backend_contract.application.process_metadata import aggregate_process_metadata

    assert aggregate_process_metadata((document,)).state == "PARTIAL"


def test_import_expands_the_bounded_reader_when_initial_metadata_is_unresolved():
    class ProgressiveExtractor:
        def __init__(self):
            self.expansions = 0

        def extract(self, _source, **context):
            return PdfTextResult(
                PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE,
                (
                    PdfTextPage(
                        1,
                        "",
                        extraction_mode=PageExtractionMode.OCR,
                        engine="SYNTHETIC_OCR",
                        engine_version="1.0",
                        model_version="synthetic-pt-v1",
                        processing_status=PageProcessingStatus.OCR_FAILED,
                    ),
                    PdfTextPage(
                        2,
                        "",
                        extraction_mode=PageExtractionMode.OCR,
                        engine="SYNTHETIC_OCR",
                        engine_version="1.0",
                        model_version="synthetic-pt-v1",
                        processing_status=PageProcessingStatus.NOT_PROCESSED,
                    ),
                ),
                document_sha256=context["document_sha256"],
            )

        def expand(self, _source, **context):
            self.expansions += 1
            return PdfTextResult(
                PdfTextExtractionState.AVAILABLE,
                (PdfTextPage(2, "PROCESSO: 7654321-55.2025.4.05.0001"),),
                document_sha256=context["document_sha256"],
            )

    extractor = ProgressiveExtractor()
    revisions = MemoryRevisions()
    ImportCaseDocumentWithMetadata(
        ImportOnly(), OpenStored(), extractor, revisions, FixedClock(), SequenceIds()
    ).execute(
        workspace_id=WORKSPACE_ID,
        original_filename="autos.pdf",
        content=SeekableContent(BytesIO(PDF), len(PDF)),
        media_type="application/pdf",
    )

    assert extractor.expansions == 1
    payload = thaw_payload(revisions.records[-1].payload)
    assert payload["fields"]["numero_processo"]["value"] == "7654321-55.2025.4.05.0001"


def test_local_api_exposes_review_without_raw_text_path_or_token():
    review = type(
        "ReviewService",
        (),
        {"execute": lambda _self, workspace_id: GetProcessMetadataReview.empty(workspace_id)},
    )()
    inert = type("Inert", (), {"execute": lambda *_args, **_kwargs: None})()
    api = LocalApi(
        LocalApiServices(
            create_workspace=inert,
            get_workspace=inert,
            list_workspaces=inert,
            append_artifact_revision=inert,
            get_latest_artifact=inert,
            get_artifact_revision=inert,
            list_artifact_revisions=inert,
            get_process_case=inert,
            save_process_case=inert,
            get_process_metadata_review=review,
        ),
        token=TOKEN,
    )

    response = api.handle(
        "GET",
        f"/v1/workspaces/{WORKSPACE_ID}/process-metadata",
        {"Host": "127.0.0.1", "X-Local-API-Token": TOKEN},
        b"",
    )

    assert response.status == 200
    payload = json.loads(response.body)
    assert payload["workspace_id"] == str(WORKSPACE_ID)
    assert payload["state"] == "WAITING_FOR_DOCUMENTS"
    assert payload["documents"] == []
    assert set(payload["fields"]) == {
        "numero_processo",
        "ramo_justica",
        "tribunal",
        "vara",
        "comarca_municipio",
        "uf",
        "parte_requerente",
        "parte_requerida",
    }
    assert "token" not in response.body.decode().lower()
    assert "path" not in response.body.decode().lower()


def test_real_local_pdf_flow_extracts_confirms_and_survives_reopen(tmp_path):
    build = tmp_path / "dist"
    build.mkdir()
    (build / "index.html").write_text("<!doctype html><title>test</title>", encoding="utf-8")
    database = tmp_path / "case.db"
    private_root = tmp_path / "private"
    pdf = text_pdf(
        "TRIBUNAL REGIONAL FEDERAL DA 5 REGIAO\n"
        "1 VARA FEDERAL DA SUBSECAO JUDICIARIA DE RECIFE/PE\n"
        "PROCESSO: 7654321-55.2025.4.05.0001\n"
        "AUTOR: Parte Sintetica\nREU: Parte Contraria"
    )

    runtime = build_product_runtime(
        database,
        build,
        private_root=private_root,
        token="metadata-product-flow-token-with-entropy",
    )
    runtime.start()
    try:
        create_body = json.dumps({"name": "Perícia sintética"}).encode()
        status, _, raw = product_request(
            runtime,
            "POST",
            "/app-api/v1/workspaces",
            create_body,
            {"Content-Type": "application/json"},
        )
        assert status == 201
        workspace_id = json.loads(raw)["workspace_id"]

        status, _, raw = product_request(
            runtime,
            "POST",
            f"/app-api/v1/workspaces/{workspace_id}/materials",
            pdf,
            {
                "Content-Type": "application/pdf",
                "X-Document-Filename": "autos-sinteticos.pdf",
            },
        )
        assert status == 201
        content_id = json.loads(raw)["content_id"]

        status, _, raw = product_request(
            runtime,
            "GET",
            f"/app-api/v1/workspaces/{workspace_id}/process-metadata",
        )
        review = json.loads(raw)
        assert status == 200
        assert review["state"] == "EXTRACTED"
        assert review["fields"]["numero_processo"]["value"] == "7654321-55.2025.4.05.0001"
        assert review["fields"]["tribunal"]["value"] == "Tribunal Regional Federal da 5ª Região"
        assert review["documents"] == [{
            "document_id": content_id,
            "source_filename": "autos-sinteticos.pdf",
            "text_state": "AVAILABLE",
        }]

        effective = {
            name: field["value"]
            for name, field in review["fields"].items()
        }
        effective["vara"] = "2ª Vara Federal"
        confirmation_body = json.dumps(
            {"expected_revision": None, "data": effective},
            ensure_ascii=False,
        ).encode("utf-8")
        status, _, _ = product_request(
            runtime,
            "POST",
            f"/app-api/v1/workspaces/{workspace_id}/process-case",
            confirmation_body,
            {"Content-Type": "application/json"},
        )
        assert status == 200
    finally:
        runtime.close()

    reopened = build_product_runtime(
        database,
        build,
        private_root=private_root,
        token="metadata-product-reopen-token-with-entropy",
    )
    reopened.start()
    try:
        status, _, raw = product_request(
            reopened,
            "GET",
            f"/app-api/v1/workspaces/{workspace_id}/process-metadata",
        )
        restored_review = json.loads(raw)
        assert status == 200
        assert restored_review["state"] == "CONFIRMED"
        assert restored_review["fields"]["vara"]["value"] == "1ª Vara Federal"
        assert restored_review["fields"]["vara"]["evidence"][0]["source_filename"] == "autos-sinteticos.pdf"

        status, _, raw = product_request(
            reopened,
            "GET",
            f"/app-api/v1/workspaces/{workspace_id}/process-case",
        )
        assert status == 200
        assert json.loads(raw)["data"]["vara"] == "2ª Vara Federal"

        status, content_type, opened_pdf = product_request(
            reopened,
            "GET",
            f"/app-api/v1/workspaces/{workspace_id}/materials/{content_id}",
        )
        assert status == 200
        assert content_type == "application/pdf"
        assert opened_pdf == pdf
        browser_payload = json.dumps(restored_review, ensure_ascii=False)
        assert str(private_root) not in browser_payload
        assert "token" not in browser_payload.lower()
    finally:
        reopened.close()
