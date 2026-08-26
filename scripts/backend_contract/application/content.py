"""Contrato Application para conteúdo privado aberto."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Callable

from ..streaming import (
    DOCUMENT_IO_CHUNK_BYTES,
    MAX_DOCUMENT_BYTES,
    SeekableContent,
    StreamBody,
    as_seekable_content,
)
from .models import PrivateContentMetadata

@dataclass(slots=True)
class OpenPrivateContent:
    metadata: PrivateContentMetadata
    stream: BinaryIO = field(repr=False)
    _close: Callable[[], None] = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._close()

    def __enter__(self) -> OpenPrivateContent:
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


__all__ = [
    "DOCUMENT_IO_CHUNK_BYTES",
    "MAX_DOCUMENT_BYTES",
    "OpenPrivateContent",
    "SeekableContent",
    "StreamBody",
    "as_seekable_content",
]
