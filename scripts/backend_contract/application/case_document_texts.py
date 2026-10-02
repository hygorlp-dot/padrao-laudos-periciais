"""Texto ja lido dos documentos do caso, para propostas de participantes e imovel.

As propostas releem o texto de cada fonte, mas nao refazem OCR a cada clique:
o cache OCR da pericia (`OCR_PAGE_CACHE_V1`, gravado na derivacao da #266) e
consultado somente para leitura, e o resultado fica memorizado em processo pela
identidade exata `workspace + content_id + sha256`. A memoria nunca e
autoridade: a chave inclui o hash da fonte, e um documento com outros bytes nao
encontra entrada.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock

from .ocr_cache import RevisionOcrPageCache
from .ports import RepositoryIntegrityError


@dataclass(frozen=True, slots=True)
class LogicalDocumentSpan:
    document_id: str
    title: str
    normalized_type: str
    page_start: int
    page_end: int
    available: bool


@dataclass(frozen=True, slots=True)
class CaseDocumentText:
    content_id: str
    checksum_sha256: str
    filename: str
    pages: tuple
    logical_documents: tuple[LogicalDocumentSpan, ...]
    # Leitura da #266 ainda nao concluida: o documento existe, mas nao ha texto
    # derivado para propor nada a partir dele.
    reading_pending: bool

    def logical_document_for(self, page: int) -> LogicalDocumentSpan | None:
        for item in self.logical_documents:
            if item.page_start <= page <= item.page_end:
                return item
        return None

    def excluded(self, page: int) -> bool:
        item = self.logical_document_for(page)
        return item is not None and not item.available


class _ReadOnlyPageCache:
    """Consulta o cache OCR; nunca grava a partir de uma leitura de proposta."""

    def __init__(self, cache: RevisionOcrPageCache):
        self._cache = cache

    def get(self, key):
        return self._cache.get(key)

    def put(self, key, page) -> None:
        return None


@dataclass(slots=True)
class CaseDocumentTexts:
    list_documents: object
    open_document: object
    extractor: object
    revisions: object
    clock: object
    ids: object
    max_entries: int = 32
    _memo: OrderedDict = field(default_factory=OrderedDict)
    _lock: Lock = field(default_factory=Lock)

    def _pages(self, workspace_id, document, capacity: int) -> tuple:
        key = (str(workspace_id), str(document.content_id), document.checksum_sha256)
        with self._lock:
            if key in self._memo:
                self._memo.move_to_end(key)
                return self._memo[key]
        cache = _ReadOnlyPageCache(RevisionOcrPageCache(self.revisions, workspace_id, self.clock, self.ids))
        with self.open_document.execute(workspace_id, document.content_id) as opened:
            metadata = opened.metadata
            if metadata.workspace_id != workspace_id:
                raise RepositoryIntegrityError("case document belongs to another workspace")
            if (str(metadata.content_id), metadata.checksum_sha256, metadata.original_filename) != (
                str(document.content_id), document.checksum_sha256, document.original_filename,
            ):
                raise RepositoryIntegrityError("case document identity diverges from its listing")
            extracted = self.extractor.extract(opened.stream, document_sha256=document.checksum_sha256, page_cache=cache)
        if extracted.document_sha256 != document.checksum_sha256:
            raise RepositoryIntegrityError("case document text diverges from its source")
        pages = tuple(extracted.pages)
        with self._lock:
            self._memo[key] = pages
            self._memo.move_to_end(key)
            while len(self._memo) > capacity:
                self._memo.popitem(last=False)
        return pages

    def execute(self, workspace_id) -> tuple[CaseDocumentText, ...]:
        result = []
        documents = tuple(self.list_documents.execute(workspace_id))
        # A varredura sequencial de um caso com muitos documentos nao pode
        # esvaziar a propria memoria a cada leitura.
        capacity = max(self.max_entries, len(documents))
        for document in documents:
            inventory = document.pje_inventory
            logical = tuple(
                LogicalDocumentSpan(row["document_id"], row["title"], row["normalized_type"], row["page_start"], row["page_end"], row["available"])
                for row in (inventory["documents"] if inventory is not None else ())
            )
            pending = bool(document.import_incomplete)
            pages = () if pending else self._pages(workspace_id, document, capacity)
            result.append(CaseDocumentText(str(document.content_id), document.checksum_sha256, document.original_filename, pages, logical, pending))
        return tuple(result)
