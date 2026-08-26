from __future__ import annotations

import hashlib
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scripts.backend_contract.application.process_metadata import (
    FieldExtractionState,
    PageExtractionMode,
    PageProcessingStatus,
    PdfTextExtractionState,
    document_metadata_payload,
    extract_process_metadata,
)
from scripts.backend_contract.application.models import (
    ArtifactRevision,
    PrivateContentId,
    WorkspaceId,
)
from scripts.backend_contract.infrastructure.pdf_text import LocalPdfTextExtractor


VALID_CNJ = "7654321-55.2025.4.05.0001"
WORKSPACE_A = WorkspaceId(UUID("11111111-1111-4111-8111-111111111111"))
WORKSPACE_B = WorkspaceId(UUID("22222222-2222-4222-8222-222222222222"))
DOCUMENT_A = PrivateContentId(UUID("33333333-3333-4333-8333-333333333333"))


def scanned_pdf(*lines: str) -> bytes:
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 48)
    for index, line in enumerate(lines):
        draw.text((80, 100 + index * 90), line, fill="black", font=font)
    target = BytesIO()
    image.save(target, format="PDF", resolution=150)
    return target.getvalue()


def scanned_pdf_pages(page_count: int) -> bytes:
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 48)
    pages = []
    for number in range(1, page_count + 1):
        image = Image.new("RGB", (1240, 1754), "white")
        ImageDraw.Draw(image).text(
            (80, 100), f"PÁGINA DIGITALIZADA {number}", fill="black", font=font
        )
        pages.append(image)
    target = BytesIO()
    pages[0].save(
        target,
        format="PDF",
        resolution=150,
        save_all=True,
        append_images=pages[1:],
    )
    return target.getvalue()


def native_pdf(text: str) -> bytes:
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


def mixed_pdf(native: bytes, scanned: bytes) -> bytes:
    writer = PdfWriter()
    for source in (native, scanned):
        reader = PdfReader(BytesIO(source))
        writer.add_page(reader.pages[0])
    target = BytesIO()
    writer.write(target)
    return target.getvalue()


class SyntheticOcrEngine:
    engine = "SYNTHETIC_OCR"
    engine_version = "1.0"
    model_version = "synthetic-pt-v1"
    config_version = "OCR_CONFIG_V1"

    def __init__(self, *lines: str, confidence: float = 0.99):
        self.lines = lines
        self.confidence = confidence
        self.calls = 0

    def recognize(self, _image):
        self.calls += 1
        return tuple(
            {
                "text": line,
                "confidence": self.confidence,
                "bounding_box": (80.0, 100.0, 1100.0, 180.0),
            }
            for line in self.lines
        )


def test_fully_scanned_pdf_uses_local_ocr_for_process_header():
    engine = SyntheticOcrEngine(
        "TRIBUNAL REGIONAL FEDERAL DA 5ª REGIÃO",
        f"PROCESSO: {VALID_CNJ}",
    )

    result = LocalPdfTextExtractor(ocr_engine=engine).extract(
        BytesIO(scanned_pdf("imagem sem camada textual"))
    )

    assert result.state is PdfTextExtractionState.AVAILABLE
    assert len(result.pages) == 1
    assert result.pages[0].number == 1
    assert result.pages[0].text == (
        "TRIBUNAL REGIONAL FEDERAL DA 5ª REGIÃO\n"
        f"PROCESSO: {VALID_CNJ}"
    )
    assert result.pages[0].extraction_mode == "OCR"
    assert result.pages[0].engine == "SYNTHETIC_OCR"
    assert engine.calls == 1


def metadata_from(result, *, workspace_id=WORKSPACE_A):
    return extract_process_metadata(
        workspace_id=workspace_id,
        document_id=DOCUMENT_A,
        original_filename="autos-sinteticos.pdf",
        text=result,
        extracted_at="2026-08-26T12:30:00+00:00",
    )


def test_scanned_valid_cnj_is_extracted_with_ocr_provenance():
    engine = SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")
    result = LocalPdfTextExtractor(ocr_engine=engine).extract(BytesIO(scanned_pdf("CNJ")))

    metadata = metadata_from(result)

    field = metadata.fields["numero_processo"]
    assert field.state is FieldExtractionState.CONFIDENT
    assert field.value == VALID_CNJ
    assert field.evidence[0].extraction_method == "LOCAL_OCR_V1"
    assert field.evidence[0].ocr_confidence == 0.99


def test_scanned_parties_without_primary_identity_are_ambiguous_with_ocr_locator():
    engine = SyntheticOcrEngine(
        "AUTORA: José Gonçalves Construções Ltda.",
        "RÉU: Órgão Público de São Luís",
    )
    result = LocalPdfTextExtractor(ocr_engine=engine).extract(BytesIO(scanned_pdf("partes")))

    metadata = metadata_from(result)

    assert metadata.fields["parte_requerente"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["parte_requerente"].value == ""
    assert metadata.fields["parte_requerida"].state is FieldExtractionState.AMBIGUOUS
    assert metadata.fields["parte_requerida"].value == ""
    evidence = metadata.fields["parte_requerente"].evidence[0]
    assert evidence.extracted_value == "José Gonçalves Construções Ltda."
    assert evidence.extraction_mode == "OCR"
    assert evidence.bounding_box == (80.0, 100.0, 1100.0, 180.0)


def test_mixed_pdf_routes_each_page_independently():
    source = mixed_pdf(
        native_pdf(f"PROCESSO: {VALID_CNJ} TRIBUNAL REGIONAL FEDERAL"),
        scanned_pdf("parte digitalizada"),
    )
    engine = SyntheticOcrEngine("AUTOR: Parte Digitalizada")

    result = LocalPdfTextExtractor(ocr_engine=engine).extract(BytesIO(source))

    assert [page.extraction_mode for page in result.pages] == ["NATIVE_TEXT", "OCR"]
    assert result.ocr_pages_processed == 1
    assert result.native_pages_skipped == 1


def test_born_digital_pdf_never_calls_ocr_engine():
    engine = SyntheticOcrEngine("texto que não deve ser usado")

    result = LocalPdfTextExtractor(ocr_engine=engine).extract(
        BytesIO(native_pdf(f"PROCESSO: {VALID_CNJ} TRIBUNAL REGIONAL FEDERAL"))
    )

    assert result.pages[0].extraction_mode == "NATIVE_TEXT"
    assert result.native_pages_skipped == 1
    assert result.ocr_pages_processed == 0
    assert engine.calls == 0


@pytest.mark.parametrize("garbage", ("X" * 24, "0" * 24))
def test_obviously_repeated_hidden_text_does_not_suppress_ocr(garbage):
    engine = SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")

    result = LocalPdfTextExtractor(ocr_engine=engine).extract(
        BytesIO(native_pdf(garbage))
    )

    assert result.pages[0].extraction_mode == "OCR"
    assert engine.calls == 1


class MemoryPageCache:
    def __init__(self):
        self.values = {}
        self.hits = 0

    def get(self, key):
        value = self.values.get(key)
        if value is not None:
            self.hits += 1
        return value

    def put(self, key, value):
        self.values[key] = value


def test_oversized_page_geometry_fails_before_rasterization_or_ocr():
    class OversizedPage:
        def __init__(self):
            self.render_calls = 0

        def get_size(self):
            return 50_000.0, 50_000.0

        def render(self, **_values):
            self.render_calls += 1
            raise MemoryError("rasterization must not be attempted")

    page = OversizedPage()
    engine = SyntheticOcrEngine("must not be called")

    result, cache_hit = LocalPdfTextExtractor(ocr_engine=engine)._ocr_page(
        [page], 0, "", None
    )

    assert result is not None
    assert result.processing_status == "OCR_FAILED"
    assert cache_hit is False
    assert page.render_calls == 0
    assert engine.calls == 0


def test_pdfium_document_is_closed_after_local_ocr(monkeypatch):
    from scripts.backend_contract.infrastructure import pdf_text

    actual_factory = pdf_text.pdfium.PdfDocument
    closed = []

    class TrackedDocument:
        def __init__(self, source):
            self.inner = actual_factory(source)

        def __getitem__(self, index):
            return self.inner[index]

        def close(self):
            self.inner.close()
            closed.append(True)

    monkeypatch.setattr(pdf_text.pdfium, "PdfDocument", TrackedDocument)

    LocalPdfTextExtractor(ocr_engine=SyntheticOcrEngine("texto OCR suficiente")).extract(
        BytesIO(scanned_pdf("documento a fechar"))
    )

    assert closed == [True]


def test_ocr_text_and_blocks_are_bounded_before_cache_persistence():
    cache = MemoryPageCache()
    engine = SyntheticOcrEngine("X" * 100_000, "Y" * 100_000)

    result = LocalPdfTextExtractor(
        ocr_engine=engine,
        page_cache=cache,
        max_chars_per_page=10,
    ).extract(
        BytesIO(scanned_pdf("saÃ­da OCR superdimensionada")),
        document_sha256="a" * 64,
    )

    cached = next(iter(cache.values.values()))
    assert result.pages[0].text == "X" * 10
    assert cached.text == "X" * 10
    assert len(cached.blocks) == 1
    assert cached.blocks[0].text == "X" * 10
    assert cached.processing_status is PageProcessingStatus.TRUNCATED
    assert result.state is PdfTextExtractionState.PARTIAL


def test_native_page_character_limit_is_explicitly_partial():
    source = (
        f"PROCESSO: {VALID_CNJ} TRIBUNAL REGIONAL FEDERAL "
        "CONTEUDO TECNICO ADICIONAL NAO PROCESSADO INTEGRALMENTE"
    )

    result = LocalPdfTextExtractor(max_chars_per_page=50).extract(
        BytesIO(native_pdf(source))
    )

    assert len(result.pages[0].text) == 50
    assert result.pages[0].processing_status is PageProcessingStatus.TRUNCATED
    assert result.state is PdfTextExtractionState.PARTIAL


def test_reopen_reuses_ocr_page_cache_bound_to_source_and_engine_identity():
    source = scanned_pdf("processo digitalizado")
    digest = hashlib.sha256(source).hexdigest()
    cache = MemoryPageCache()
    engine = SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")
    reader = LocalPdfTextExtractor(ocr_engine=engine, page_cache=cache)

    first = reader.extract(BytesIO(source), document_sha256=digest)
    reopened = reader.extract(BytesIO(source), document_sha256=digest)

    assert first.pages == reopened.pages
    assert engine.calls == 1
    assert reopened.cache_hits == 1
    assert cache.hits == 1


def test_ocr_never_changes_source_pdf_bytes_or_sha256():
    source = scanned_pdf("fonte imutável")
    stream = BytesIO(source)
    before = hashlib.sha256(stream.getvalue()).hexdigest()

    result = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")
    ).extract(stream, document_sha256=before)

    assert stream.getvalue() == source
    assert hashlib.sha256(stream.getvalue()).hexdigest() == before
    assert result.document_sha256 == before


class FailingOcrEngine(SyntheticOcrEngine):
    def recognize(self, _image):
        self.calls += 1
        raise RuntimeError("synthetic local OCR failure")


class EmptyOcrEngine(SyntheticOcrEngine):
    def recognize(self, _image):
        self.calls += 1
        return ()


def test_ocr_failure_is_a_controlled_page_state():
    result = LocalPdfTextExtractor(ocr_engine=FailingOcrEngine()).extract(
        BytesIO(scanned_pdf("falha controlada"))
    )

    assert result.state is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
    assert result.pages[0].processing_status == "OCR_FAILED"
    assert result.pages[0].text == ""


def test_ocr_without_detected_text_is_a_controlled_page_state():
    result = LocalPdfTextExtractor(ocr_engine=EmptyOcrEngine()).extract(
        BytesIO(scanned_pdf("página sem texto detectável"))
    )

    assert result.state is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
    assert result.pages[0].processing_status == "OCR_FAILED"
    assert result.pages[0].text == ""


def test_low_confidence_ocr_cnj_does_not_become_effective_metadata():
    result = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}", confidence=0.41)
    ).extract(BytesIO(scanned_pdf("CNJ de baixa confiança")))

    field = metadata_from(result).fields["numero_processo"]

    assert field.state is FieldExtractionState.AMBIGUOUS
    assert field.value == ""
    assert field.evidence[0].extracted_value == VALID_CNJ


def test_ocr_only_cnj_confusions_are_bounded_and_still_require_checksum():
    confused = "OO1O549-O8.2O26.4.O5.83O2"
    result = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine(f"PROCESSO: {confused}")
    ).extract(BytesIO(scanned_pdf("CNJ com confusões de OCR")))

    field = metadata_from(result).fields["numero_processo"]

    assert field.state is FieldExtractionState.CONFIDENT
    assert field.value == VALID_CNJ
    assert field.evidence[0].normalized_text_span == confused

    native_result = LocalPdfTextExtractor().extract(
        BytesIO(native_pdf(f"PROCESSO: {confused} TRIBUNAL REGIONAL FEDERAL"))
    )
    assert metadata_from(native_result).fields["numero_processo"].value == ""


def test_ocr_page_evidence_is_workspace_scoped_and_contains_no_path():
    result = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")
    ).extract(BytesIO(scanned_pdf("evidência isolada")))

    first = document_metadata_payload(metadata_from(result, workspace_id=WORKSPACE_A))
    second = document_metadata_payload(metadata_from(result, workspace_id=WORKSPACE_B))

    assert first["page_evidence"][0]["workspace_id"] == str(WORKSPACE_A)
    assert second["page_evidence"][0]["workspace_id"] == str(WORKSPACE_B)
    assert first["page_evidence"][0]["document_id"] == str(DOCUMENT_A)
    assert "path" not in repr(first).lower()


def test_unicode_portuguese_party_without_primary_identity_preserves_ambiguous_provenance():
    result = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine("AUTORA: Conceição d'Ávila")
    ).extract(BytesIO(scanned_pdf("parte com Unicode")))

    field = metadata_from(result).fields["parte_requerente"]

    assert field.state is FieldExtractionState.AMBIGUOUS
    assert field.value == ""
    assert field.evidence[0].extracted_value == "Conceição d'Ávila"
    assert field.evidence[0].ocr_confidence == 0.99
    assert field.evidence[0].ocr_engine == "SYNTHETIC_OCR"


def test_large_scanned_pdf_only_ocrs_bounded_early_pages():
    engine = SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")

    result = LocalPdfTextExtractor(
        ocr_engine=engine,
        max_pages=8,
        max_ocr_pages=2,
    ).extract(BytesIO(scanned_pdf_pages(8)))

    assert engine.calls == 2
    assert result.ocr_pages_processed == 2
    assert [page.number for page in result.pages] == list(range(1, 9))
    assert result.state is PdfTextExtractionState.PARTIAL
    assert all(
        page.processing_status is PageProcessingStatus.NOT_PROCESSED
        for page in result.pages[2:]
    )


@pytest.mark.parametrize(
    "native_text",
    (
        "ABCD" * 20,
        "SYSTEM GENERATED " * 10,
        "PROCESSO " * 20,
        "ALFA BETA GAMA " * 10,
        "THIS PDF IS SCANNED " * 10,
        "ALFA BETA GAMA " * 10 + "1",
        "SYSTEM GENERATED " * 10 + " PAGE 1",
        "THIS PDF IS SCANNED " * 10 + "END",
        "PAGE 1 " + "ALFA BETA GAMA " * 10,
        "ALFA BETA GAMA " * 10
        + " DOCUMENTO DIGITALIZADO AUTOMATICAMENTE PAGINA 1",
        " CABECALHO DO SISTEMA PROCESSUAL ELETRONICO PAGINA 0001"
        + "ALFA BETA GAMA " * 10,
        "CABECALHO PROCESSUAL "
        + "ALFA BETA GAMA " * 10
        + " DOCUMENTO DIGITALIZADO PAGINA 1",
        (
            "DOCUMENTO DIGITALIZADO AUTOMATICAMENTE PELO SISTEMA PROCESSUAL "
            "ELETRONICO PAGINA ORIGINAL "
        )
        * 3
        + " CABECALHO PROCESSUAL UNICO COM IDENTIFICADOR 2026",
        "AUTOS JUDICIAIS PAGINA 1 "
        + (
            "ESTE DOCUMENTO FOI GERADO E ASSINADO DIGITALMENTE NO SISTEMA "
            "PROCESSUAL ELETRONICO OFICIAL "
        )
        * 3
        + " RODAPE PROCESSUAL IDENTIFICADOR 2026",
    ),
)
def test_repeated_native_token_patterns_route_to_local_ocr(native_text):
    engine = SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")

    result = LocalPdfTextExtractor(ocr_engine=engine).extract(
        BytesIO(native_pdf(native_text))
    )

    assert engine.calls == 1
    assert result.pages[0].extraction_mode is PageExtractionMode.OCR


def test_majority_periodic_core_counts_repetition_boundary_ngrams():
    period = hashlib.sha256(b"periodic-native-core").hexdigest() + "x"
    prefix = (
        hashlib.sha256(b"unique-prefix-a").hexdigest()
        + hashlib.sha256(b"unique-prefix-b").hexdigest()[:16]
        + "abcde"
    )
    suffix = (
        hashlib.sha256(b"unique-suffix-a").hexdigest()
        + hashlib.sha256(b"unique-suffix-b").hexdigest()[:16]
        + "wxyz"
    )
    native_text = prefix + period * 3 + suffix
    assert len(period) == 65
    assert len(period) * 3 > len(native_text) / 2
    engine = SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")

    result = LocalPdfTextExtractor(ocr_engine=engine).extract(
        BytesIO(native_pdf(native_text))
    )

    assert engine.calls == 1
    assert result.pages[0].extraction_mode is PageExtractionMode.OCR


def test_failed_or_unprocessed_pages_are_never_hidden_by_available_pages():
    engine = SyntheticOcrEngine("")

    result = LocalPdfTextExtractor(ocr_engine=engine, max_ocr_pages=1).extract(
        BytesIO(scanned_pdf_pages(3))
    )

    assert result.state is PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
    assert [page.number for page in result.pages] == [1, 2, 3]
    assert result.pages[0].processing_status is PageProcessingStatus.OCR_FAILED
    assert all(
        page.processing_status is PageProcessingStatus.NOT_PROCESSED
        for page in result.pages[1:]
    )


def test_real_rapidocr_latin_engine_reads_portuguese_and_cnj_offline():
    from scripts.backend_contract.infrastructure.rapid_ocr import RapidOcrLatinEngine

    image = Image.new("RGB", (1800, 900), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 48)
    lines = (
        "AUTORA: José Gonçalves Construções Ltda.",
        "RÉU: Órgão Público de São Luís",
        f"PROCESSO: {VALID_CNJ}",
    )
    for index, line in enumerate(lines):
        draw.text((80, 80 + index * 120), line, fill="black", font=font)

    blocks = RapidOcrLatinEngine().recognize(image)
    text = "\n".join(block["text"] for block in blocks)

    assert "José Gonçalves Construções Ltda." in text
    assert "Órgão Público de São Luís" in text
    assert VALID_CNJ in text
    assert all(0.0 <= block["confidence"] <= 1.0 for block in blocks)
    assert all(len(block["bounding_box"]) == 4 for block in blocks)


def test_rapidocr_model_identity_mismatch_fails_closed_without_download(tmp_path):
    from scripts.backend_contract.infrastructure.rapid_ocr import (
        LocalOcrModelError,
        RapidOcrLatinEngine,
    )

    wrong_model = tmp_path / "latin_PP-OCRv5_rec_mobile.onnx"
    wrong_model.write_bytes(b"not the protected model")

    with pytest.raises(LocalOcrModelError, match="identidade|modelo"):
        RapidOcrLatinEngine(recognition_model_path=wrong_model).recognize(
            Image.new("RGB", (100, 100), "white")
        )


class CacheRevisions:
    def __init__(self):
        self.values = {}

    def latest(self, workspace_id, artifact_kind, artifact_id):
        return self.values.get((workspace_id, artifact_kind, artifact_id))

    def append(self, **values):
        record = ArtifactRevision(
            **values,
            revision=1,
            checksum_sha256="c" * 64,
        )
        self.values[
            (values["workspace_id"], values["artifact_kind"], values["artifact_id"])
        ] = record
        return record

    def append_if_latest(self, *, expected_revision, **values):
        if expected_revision is not None or self.latest(
            values["workspace_id"], values["artifact_kind"], values["artifact_id"]
        ) is not None:
            from scripts.backend_contract.application.ports import RepositoryConflict

            raise RepositoryConflict("concurrent cache write")
        return self.append(**values)


class CacheClock:
    def now(self):
        from datetime import UTC, datetime

        return datetime(2026, 8, 26, 12, 30, tzinfo=UTC)


class CacheIds:
    def new_uuid(self):
        return UUID("44444444-4444-4444-8444-444444444444")


def test_revision_page_cache_survives_reconstruction_and_isolates_workspace():
    from scripts.backend_contract.application.ocr_cache import RevisionOcrPageCache

    revisions = CacheRevisions()
    first = RevisionOcrPageCache(revisions, WORKSPACE_A, CacheClock(), CacheIds())
    isolated = RevisionOcrPageCache(revisions, WORKSPACE_B, CacheClock(), CacheIds())
    key = (
        "a" * 64,
        1,
        "SYNTHETIC_OCR",
        "1.0",
        "synthetic-pt-v1",
        "OCR_CONFIG_V1",
    )
    page = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")
    ).extract(BytesIO(scanned_pdf("cache persistido")), document_sha256="a" * 64).pages[0]

    first.put(key, page)
    reopened = RevisionOcrPageCache(revisions, WORKSPACE_A, CacheClock(), CacheIds())

    assert reopened.get(key) == page
    assert isolated.get(key) is None


def test_revision_page_cache_rejects_a_divergent_concurrent_first_write():
    from scripts.backend_contract.application.ocr_cache import RevisionOcrPageCache
    from scripts.backend_contract.application.ports import (
        RepositoryConflict,
        RepositoryIntegrityError,
    )

    class RacingCacheRevisions(CacheRevisions):
        def append_if_latest(self, *, expected_revision, **values):
            competing = dict(values)
            competing_payload = dict(values["payload"])
            competing_payload["normalized_text"] = "DIVERGENT"
            competing_blocks = [dict(block) for block in competing_payload["blocks"]]
            competing_blocks[0]["text"] = "DIVERGENT"
            competing_payload["blocks"] = competing_blocks
            competing["payload"] = competing_payload
            self.append(**competing)
            raise RepositoryConflict("concurrent cache write")

    revisions = RacingCacheRevisions()
    cache = RevisionOcrPageCache(revisions, WORKSPACE_A, CacheClock(), CacheIds())
    key = (
        "a" * 64,
        1,
        "SYNTHETIC_OCR",
        "1.0",
        "synthetic-pt-v1",
        "OCR_CONFIG_V1",
    )
    page = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")
    ).extract(BytesIO(scanned_pdf("concorrência")), document_sha256="a" * 64).pages[0]

    with pytest.raises(RepositoryIntegrityError, match="imutável|diverge"):
        cache.put(key, page)


def test_extractor_propagates_persisted_cache_integrity_failures():
    from scripts.backend_contract.application.ports import RepositoryIntegrityError

    class DivergentCache:
        def get(self, _key):
            return None

        def put(self, _key, _page):
            raise RepositoryIntegrityError("divergent concurrent cache winner")

    with pytest.raises(RepositoryIntegrityError, match="divergent concurrent"):
        LocalPdfTextExtractor(
            ocr_engine=SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}"),
            page_cache=DivergentCache(),
        ).extract(
            BytesIO(scanned_pdf("falha de integridade")),
            document_sha256="a" * 64,
        )


def test_import_service_binds_reader_to_stored_sha_and_persisted_page_cache():
    from scripts.backend_contract.application.content import OpenPrivateContent, SeekableContent
    from scripts.backend_contract.application.models import (
        PrivateContentMetadata,
        PrivateContentOrigin,
    )
    from scripts.backend_contract.application.services import ImportCaseDocumentWithMetadata

    revisions = CacheRevisions()
    source_sha256 = "d" * 64
    page = LocalPdfTextExtractor(
        ocr_engine=SyntheticOcrEngine(f"PROCESSO: {VALID_CNJ}")
    ).extract(BytesIO(scanned_pdf("importação")), document_sha256=source_sha256).pages[0]

    class ImportDocument:
        def execute(self, **_values):
            return PrivateContentMetadata(
                WORKSPACE_A,
                DOCUMENT_A,
                "autos.pdf",
                15,
                source_sha256,
                "application/pdf",
                "2026-08-26T12:30:00+00:00",
                PrivateContentOrigin.USER_IMPORT,
            )

    class OpenDocument:
        def execute(self, _workspace_id, _content_id):
            metadata = ImportDocument().execute()
            stream = BytesIO(b"%PDF-1.7\n%%EOF")
            return OpenPrivateContent(metadata, stream, stream.close)

    class CacheAwareReader:
        def extract(self, source, *, document_sha256, page_cache):
            assert source.read(5) == b"%PDF-"
            assert document_sha256 == source_sha256
            key = (
                source_sha256,
                1,
                page.engine,
                page.engine_version,
                page.model_version,
                page.config_version,
            )
            page_cache.put(key, page)
            assert type(page_cache).__name__ == "RevisionOcrPageCache"
            return PdfTextResult(
                PdfTextExtractionState.AVAILABLE,
                (page,),
                document_sha256=source_sha256,
                ocr_pages_processed=1,
            )

    from scripts.backend_contract.application.process_metadata import PdfTextResult

    service = ImportCaseDocumentWithMetadata(
        ImportDocument(), OpenDocument(), CacheAwareReader(), revisions, CacheClock(), CacheIds()
    )

    service.execute(
        workspace_id=WORKSPACE_A,
        original_filename="autos.pdf",
        content=SeekableContent(BytesIO(b"%PDF-1.7\n%%EOF"), 15),
        media_type="application/pdf",
    )

    assert any(key[1] == "OCR_PAGE_CACHE_V1" for key in revisions.values)
    assert any(key[1] == "PROCESS_METADATA_EXTRACTION" for key in revisions.values)
