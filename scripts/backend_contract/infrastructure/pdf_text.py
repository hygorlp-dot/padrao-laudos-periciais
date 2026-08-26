"""Leitura local e limitada da camada textual de documentos PDF."""

from __future__ import annotations

import re
from typing import BinaryIO

import pypdfium2 as pdfium
from pypdf import PdfReader, __version__ as PYPDF_VERSION

from ..application.process_metadata import (
    PageExtractionMode,
    PageProcessingStatus,
    PageTextBlock,
    PdfTextExtractionState,
    PdfTextPage,
    PdfTextResult,
)


class LocalPdfTextExtractor:
    def __init__(
        self,
        *,
        max_pages: int = 12,
        max_ocr_pages: int = 4,
        max_chars_per_page: int = 50_000,
        max_total_chars: int = 400_000,
        ocr_engine: object | None = None,
        page_cache: object | None = None,
    ):
        for value, name in (
            (max_pages, "max_pages"),
            (max_ocr_pages, "max_ocr_pages"),
            (max_chars_per_page, "max_chars_per_page"),
            (max_total_chars, "max_total_chars"),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} inválido")
        self._max_pages = max_pages
        self._max_ocr_pages = min(max_ocr_pages, max_pages)
        self._max_chars_per_page = max_chars_per_page
        self._max_total_chars = max_total_chars
        self._ocr_engine = ocr_engine
        self._page_cache = page_cache

    @staticmethod
    def _reliable_native_text(value: str) -> bool:
        compact = "".join(value.split())
        if len(compact) < 24:
            return False
        alphanumeric = sum(character.isalnum() for character in compact)
        replacement = value.count("\ufffd") + value.count("\x00")
        return alphanumeric / len(compact) >= 0.5 and replacement / len(compact) <= 0.02

    def _ocr_page(
        self,
        document,
        index: int,
        document_sha256: str,
        page_cache: object | None,
    ) -> tuple[PdfTextPage | None, bool]:
        if self._ocr_engine is None:
            return None, False
        key = (
            document_sha256,
            index + 1,
            self._ocr_engine.engine,
            self._ocr_engine.engine_version,
            self._ocr_engine.model_version,
            self._ocr_engine.config_version,
        )
        if page_cache is not None and document_sha256:
            cached = page_cache.get(key)
            if cached is not None:
                if type(cached) is not PdfTextPage or cached.number != index + 1:
                    raise ValueError("cache OCR persistido inválido")
                return cached, True
        try:
            rendered = document[index].render(scale=1.5).to_pil()
            raw_blocks = self._ocr_engine.recognize(rendered)
            blocks = tuple(
                PageTextBlock(
                    text=block["text"],
                    confidence=float(block["confidence"]),
                    bounding_box=tuple(float(value) for value in block["bounding_box"]),
                )
                for block in raw_blocks
            )
            if not blocks:
                return (
                    PdfTextPage(
                        index + 1,
                        "",
                        extraction_mode=PageExtractionMode.OCR,
                        engine=self._ocr_engine.engine,
                        engine_version=self._ocr_engine.engine_version,
                        model_version=self._ocr_engine.model_version,
                        config_version=self._ocr_engine.config_version,
                        processing_status=PageProcessingStatus.OCR_FAILED,
                    ),
                    False,
                )
            text = "\n".join(block.text for block in blocks)
            page = PdfTextPage(
                index + 1,
                text,
                extraction_mode=PageExtractionMode.OCR,
                engine=self._ocr_engine.engine,
                engine_version=self._ocr_engine.engine_version,
                model_version=self._ocr_engine.model_version,
                config_version=self._ocr_engine.config_version,
                confidence=sum(block.confidence or 0.0 for block in blocks) / len(blocks),
                blocks=blocks,
            )
            if page_cache is not None and document_sha256:
                page_cache.put(key, page)
            return page, False
        except Exception:
            return (
                PdfTextPage(
                    index + 1,
                    "",
                    extraction_mode=PageExtractionMode.OCR,
                    engine=self._ocr_engine.engine,
                    engine_version=self._ocr_engine.engine_version,
                    model_version=self._ocr_engine.model_version,
                    config_version=self._ocr_engine.config_version,
                    processing_status=PageProcessingStatus.OCR_FAILED,
                ),
                False,
            )

    def extract(
        self,
        source: BinaryIO,
        *,
        document_sha256: str = "",
        page_cache: object | None = None,
    ) -> PdfTextResult:
        if not all(hasattr(source, name) for name in ("read", "seek", "tell")):
            raise TypeError("fonte PDF deve ser seekable")
        pages: list[PdfTextPage] = []
        remaining = self._max_total_chars
        ocr_pages = 0
        native_pages = 0
        cache_hits = 0
        rendered_document = None
        active_cache = self._page_cache if page_cache is None else page_cache
        try:
            source.seek(0, 2)
            size = source.tell()
            source.seek(max(0, size - 8192))
            trailer = source.read(min(8192, size))
            startxref = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", trailer)
            if startxref is None or int(startxref.group(1)) >= size:
                return PdfTextResult(
                    PdfTextExtractionState.ERROR, (), document_sha256=document_sha256
                )
            source.seek(0)
            reader = PdfReader(source, strict=False)
            if reader.is_encrypted:
                return PdfTextResult(
                    PdfTextExtractionState.ERROR, (), document_sha256=document_sha256
                )
            for index, page in enumerate(reader.pages[: self._max_pages], start=1):
                if remaining <= 0:
                    break
                extracted = page.extract_text() or ""
                normalized = extracted.replace("\x00", "").strip()
                result_page = None
                if self._reliable_native_text(normalized):
                    limited = normalized[: min(self._max_chars_per_page, remaining)]
                    result_page = PdfTextPage(
                        index,
                        limited,
                        engine="pypdf",
                        engine_version=PYPDF_VERSION,
                    )
                    native_pages += 1
                elif self._ocr_engine is not None and ocr_pages < self._max_ocr_pages:
                    if rendered_document is None:
                        source.seek(0)
                        rendered_document = pdfium.PdfDocument(source)
                    result_page, cache_hit = self._ocr_page(
                        rendered_document,
                        index - 1,
                        document_sha256,
                        active_cache,
                    )
                    cache_hits += int(cache_hit)
                    ocr_pages += int(not cache_hit)
                if result_page is not None:
                    limited = result_page.text[: min(self._max_chars_per_page, remaining)]
                    if limited != result_page.text:
                        result_page = PdfTextPage(
                            result_page.number,
                            limited,
                            extraction_mode=result_page.extraction_mode,
                            engine=result_page.engine,
                            engine_version=result_page.engine_version,
                            model_version=result_page.model_version,
                            config_version=result_page.config_version,
                            confidence=result_page.confidence,
                            blocks=result_page.blocks,
                        )
                    pages.append(result_page)
                    remaining -= len(limited)
        except Exception:
            return PdfTextResult(
                PdfTextExtractionState.ERROR, (), document_sha256=document_sha256
            )
        finally:
            try:
                source.seek(0)
            except (OSError, ValueError):
                pass
        if not pages:
            return PdfTextResult(
                PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE,
                (),
                document_sha256=document_sha256,
                ocr_pages_processed=ocr_pages,
                native_pages_skipped=native_pages,
                cache_hits=cache_hits,
            )
        has_text = any(
            page.processing_status is PageProcessingStatus.AVAILABLE for page in pages
        )
        state = (
            PdfTextExtractionState.AVAILABLE
            if has_text
            else PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
        )
        return PdfTextResult(
            state,
            tuple(pages),
            document_sha256=document_sha256,
            ocr_pages_processed=ocr_pages,
            native_pages_skipped=native_pages,
            cache_hits=cache_hits,
        )
