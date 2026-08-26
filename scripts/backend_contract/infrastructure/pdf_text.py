"""Leitura local e limitada da camada textual de documentos PDF."""

from __future__ import annotations

from collections import Counter
import math
import re
from typing import BinaryIO

import pypdfium2 as pdfium
from pypdf import PdfReader, __version__ as PYPDF_VERSION

from ..application.ports import RepositoryError
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
        max_render_dimension: int = 8_192,
        max_render_pixels: int = 16_000_000,
        max_ocr_blocks: int = 2_000,
        ocr_engine: object | None = None,
        page_cache: object | None = None,
    ):
        for value, name in (
            (max_pages, "max_pages"),
            (max_ocr_pages, "max_ocr_pages"),
            (max_chars_per_page, "max_chars_per_page"),
            (max_total_chars, "max_total_chars"),
            (max_render_dimension, "max_render_dimension"),
            (max_render_pixels, "max_render_pixels"),
            (max_ocr_blocks, "max_ocr_blocks"),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} inválido")
        self._max_pages = max_pages
        self._max_ocr_pages = min(max_ocr_pages, max_pages)
        self._max_chars_per_page = max_chars_per_page
        self._max_total_chars = max_total_chars
        self._max_render_dimension = max_render_dimension
        self._max_render_pixels = max_render_pixels
        self._max_ocr_blocks = max_ocr_blocks
        self._ocr_engine = ocr_engine
        self._page_cache = page_cache

    @staticmethod
    def _reliable_native_text(value: str) -> bool:
        compact = "".join(value.split())
        if len(compact) < 24:
            return False
        alphanumeric = sum(character.isalnum() for character in compact)
        replacement = value.count("\ufffd") + value.count("\x00")
        alphanumeric_values = [
            character.casefold() for character in compact if character.isalnum()
        ]
        if len(set(alphanumeric_values)) < 4:
            return False
        dominant = max(Counter(alphanumeric_values).values()) / len(alphanumeric_values)
        normalized = "".join(alphanumeric_values)
        gram_count = max(0, len(normalized) - 7)
        gram_frequencies = Counter(
            normalized[index : index + 8] for index in range(gram_count)
        )
        low_ngram_diversity = (
            gram_count > 0 and len(gram_frequencies) / gram_count <= 0.35
        )
        repeated_ngram_coverage = (
            sum(
                occurrences
                for occurrences in gram_frequencies.values()
                if occurrences >= 3
            )
            / gram_count
            if gram_count
            else 0.0
        )
        obviously_repeated = low_ngram_diversity or repeated_ngram_coverage >= 0.5
        return (
            alphanumeric / len(compact) >= 0.5
            and replacement / len(compact) <= 0.02
            and dominant <= 0.8
            and not obviously_repeated
        )

    def _bounded_blocks(self, raw_blocks) -> tuple[tuple[PageTextBlock, ...], bool]:
        blocks = []
        used = 0
        truncated = False
        for raw in raw_blocks:
            if len(blocks) >= self._max_ocr_blocks:
                truncated = True
                break
            separator = int(bool(blocks))
            available = self._max_chars_per_page - used - separator
            if available <= 0:
                truncated = True
                break
            text = raw["text"]
            if type(text) is not str:
                raise TypeError("invalid local OCR text")
            limited = text[:available]
            truncated = truncated or len(limited) < len(text)
            block = PageTextBlock(
                text=limited,
                confidence=float(raw["confidence"]),
                bounding_box=tuple(float(value) for value in raw["bounding_box"]),
            )
            blocks.append(block)
            used += separator + len(block.text)
        return tuple(blocks), truncated

    def _bounded_page(self, page: PdfTextPage, limit: int) -> PdfTextPage:
        if len(page.text) <= limit:
            return page
        if page.extraction_mode is PageExtractionMode.OCR:
            blocks = []
            used = 0
            for block in page.blocks:
                separator = int(bool(blocks))
                available = limit - used - separator
                if available <= 0:
                    break
                blocks.append(
                    PageTextBlock(
                        block.text[:available],
                        confidence=block.confidence,
                        bounding_box=block.bounding_box,
                    )
                )
                used += separator + len(blocks[-1].text)
            text = "\n".join(block.text for block in blocks)
            confidence = (
                sum(block.confidence or 0.0 for block in blocks) / len(blocks)
                if blocks
                else None
            )
        else:
            text = page.text[:limit]
            blocks = []
            confidence = page.confidence
        return PdfTextPage(
            page.number,
            text,
            extraction_mode=page.extraction_mode,
            engine=page.engine,
            engine_version=page.engine_version,
            model_version=page.model_version,
            config_version=page.config_version,
            confidence=confidence,
            blocks=tuple(blocks),
            processing_status=PageProcessingStatus.TRUNCATED,
        )

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
                if (
                    len(cached.text) > self._max_chars_per_page
                    or len(cached.blocks) > self._max_ocr_blocks
                    or (
                        cached.extraction_mode is PageExtractionMode.OCR
                        and cached.processing_status in {
                            PageProcessingStatus.AVAILABLE,
                            PageProcessingStatus.TRUNCATED,
                        }
                        and cached.text != "\n".join(block.text for block in cached.blocks)
                    )
                ):
                    raise ValueError("persisted OCR cache exceeds limits")
                return cached, True
        try:
            source_page = document[index]
            width, height = source_page.get_size()
            if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                raise ValueError("invalid PDF page dimensions")
            pixel_width = math.ceil(width * 1.5)
            pixel_height = math.ceil(height * 1.5)
            if (
                pixel_width > self._max_render_dimension
                or pixel_height > self._max_render_dimension
                or pixel_width * pixel_height > self._max_render_pixels
            ):
                raise ValueError("PDF page exceeds OCR rasterization limits")
            bitmap = source_page.render(scale=1.5)
            try:
                rendered = bitmap.to_pil()
                try:
                    raw_blocks = self._ocr_engine.recognize(rendered)
                    blocks, truncated = self._bounded_blocks(raw_blocks)
                finally:
                    rendered.close()
            finally:
                bitmap.close()
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
                processing_status=(
                    PageProcessingStatus.TRUNCATED
                    if truncated
                    else PageProcessingStatus.AVAILABLE
                ),
            )
            if page_cache is not None and document_sha256:
                page_cache.put(key, page)
            return page, False
        except RepositoryError:
            raise
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
        return self._extract(
            source,
            document_sha256=document_sha256,
            page_cache=page_cache,
            ocr_page_limit=self._max_ocr_pages,
        )

    def expand(
        self,
        source: BinaryIO,
        *,
        document_sha256: str = "",
        page_cache: object | None = None,
    ) -> PdfTextResult:
        return self._extract(
            source,
            document_sha256=document_sha256,
            page_cache=page_cache,
            ocr_page_limit=self._max_pages,
        )

    def _extract(
        self,
        source: BinaryIO,
        *,
        document_sha256: str = "",
        page_cache: object | None = None,
        ocr_page_limit: int,
    ) -> PdfTextResult:
        if not all(hasattr(source, name) for name in ("read", "seek", "tell")):
            raise TypeError("fonte PDF deve ser seekable")
        pages: list[PdfTextPage] = []
        remaining = self._max_total_chars
        ocr_pages = 0
        ocr_attempts = 0
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
            total_pages = len(reader.pages)
            truncated = total_pages > self._max_pages
            for index, page in enumerate(reader.pages[: self._max_pages], start=1):
                if remaining <= 0:
                    pages.append(
                        PdfTextPage(
                            index,
                            "",
                            engine="pypdf",
                            engine_version=PYPDF_VERSION,
                            processing_status=PageProcessingStatus.NOT_PROCESSED,
                        )
                    )
                    continue
                extracted = page.extract_text() or ""
                normalized = extracted.replace("\x00", "").strip()
                result_page = None
                if self._reliable_native_text(normalized):
                    page_limit = min(self._max_chars_per_page, remaining)
                    limited = normalized[:page_limit]
                    result_page = PdfTextPage(
                        index,
                        limited,
                        engine="pypdf",
                        engine_version=PYPDF_VERSION,
                        processing_status=(
                            PageProcessingStatus.TRUNCATED
                            if len(limited) < len(normalized)
                            else PageProcessingStatus.AVAILABLE
                        ),
                    )
                    native_pages += 1
                elif self._ocr_engine is not None and ocr_attempts < ocr_page_limit:
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
                    ocr_attempts += 1
                    ocr_pages += int(not cache_hit)
                elif self._ocr_engine is not None:
                    result_page = PdfTextPage(
                        index,
                        "",
                        extraction_mode=PageExtractionMode.OCR,
                        engine=self._ocr_engine.engine,
                        engine_version=self._ocr_engine.engine_version,
                        model_version=self._ocr_engine.model_version,
                        config_version=self._ocr_engine.config_version,
                        processing_status=PageProcessingStatus.NOT_PROCESSED,
                    )
                if result_page is not None:
                    result_page = self._bounded_page(
                        result_page,
                        min(self._max_chars_per_page, remaining),
                    )
                    limited = result_page.text
                    pages.append(result_page)
                    remaining -= len(limited)
            if truncated:
                pages.append(
                    PdfTextPage(
                        self._max_pages + 1,
                        "",
                        engine="pypdf",
                        engine_version=PYPDF_VERSION,
                        processing_status=PageProcessingStatus.NOT_PROCESSED,
                    )
                )
        except RepositoryError:
            raise
        except Exception:
            return PdfTextResult(
                PdfTextExtractionState.ERROR, (), document_sha256=document_sha256
            )
        finally:
            if rendered_document is not None:
                rendered_document.close()
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
            page.processing_status in {
                PageProcessingStatus.AVAILABLE,
                PageProcessingStatus.TRUNCATED,
            }
            for page in pages
        )
        incomplete = truncated or any(
            page.processing_status is not PageProcessingStatus.AVAILABLE
            for page in pages
        )
        if has_text:
            state = (
                PdfTextExtractionState.PARTIAL
                if incomplete
                else PdfTextExtractionState.AVAILABLE
            )
        else:
            state = PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE
        return PdfTextResult(
            state,
            tuple(pages),
            document_sha256=document_sha256,
            ocr_pages_processed=ocr_pages,
            native_pages_skipped=native_pages,
            cache_hits=cache_hits,
        )
