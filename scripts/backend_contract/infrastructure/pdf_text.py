"""Leitura local e limitada da camada textual de documentos PDF."""

from __future__ import annotations

import re
from typing import BinaryIO

from pypdf import PdfReader

from ..application.process_metadata import (
    PdfTextExtractionState,
    PdfTextPage,
    PdfTextResult,
)


class LocalPdfTextExtractor:
    def __init__(
        self,
        *,
        max_pages: int = 12,
        max_chars_per_page: int = 50_000,
        max_total_chars: int = 400_000,
    ):
        for value, name in (
            (max_pages, "max_pages"),
            (max_chars_per_page, "max_chars_per_page"),
            (max_total_chars, "max_total_chars"),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} inválido")
        self._max_pages = max_pages
        self._max_chars_per_page = max_chars_per_page
        self._max_total_chars = max_total_chars

    def extract(self, source: BinaryIO) -> PdfTextResult:
        if not all(hasattr(source, name) for name in ("read", "seek", "tell")):
            raise TypeError("fonte PDF deve ser seekable")
        pages: list[PdfTextPage] = []
        remaining = self._max_total_chars
        try:
            source.seek(0, 2)
            size = source.tell()
            source.seek(max(0, size - 8192))
            trailer = source.read(min(8192, size))
            startxref = re.search(rb"startxref\s+(\d+)\s+%%EOF\s*$", trailer)
            if startxref is None or int(startxref.group(1)) >= size:
                return PdfTextResult(PdfTextExtractionState.ERROR, ())
            source.seek(0)
            reader = PdfReader(source, strict=False)
            if reader.is_encrypted:
                return PdfTextResult(PdfTextExtractionState.ERROR, ())
            for index, page in enumerate(reader.pages[: self._max_pages], start=1):
                if remaining <= 0:
                    break
                extracted = page.extract_text() or ""
                normalized = extracted.replace("\x00", "").strip()
                if not normalized:
                    continue
                limited = normalized[: min(self._max_chars_per_page, remaining)]
                if limited:
                    pages.append(PdfTextPage(index, limited))
                    remaining -= len(limited)
        except Exception:
            return PdfTextResult(PdfTextExtractionState.ERROR, ())
        finally:
            try:
                source.seek(0)
            except (OSError, ValueError):
                pass
        if not pages:
            return PdfTextResult(PdfTextExtractionState.TEXT_EXTRACTION_UNAVAILABLE, ())
        return PdfTextResult(PdfTextExtractionState.AVAILABLE, tuple(pages))
