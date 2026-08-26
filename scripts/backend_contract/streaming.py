"""Neutral bounded primitives for binary content transport."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from typing import BinaryIO, Callable


MIB = 1024 * 1024
MAX_DOCUMENT_BYTES = 128 * MIB
DOCUMENT_IO_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class SeekableContent:
    stream: BinaryIO = field(repr=False)
    byte_size: int

    def __post_init__(self):
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("tamanho de conteudo invalido")
        if not all(hasattr(self.stream, operation) for operation in ("read", "seek", "tell")):
            raise TypeError("conteudo deve ser seekable")

    @classmethod
    def from_bytes(cls, content: bytes) -> SeekableContent:
        if type(content) is not bytes:
            raise TypeError("conteudo exige bytes")
        return cls(BytesIO(content), len(content))

    def rewind(self) -> None:
        if self.stream.seek(0) != 0:
            raise ValueError("fonte de conteudo nao retornou ao inicio")

    def sha256(self) -> str:
        digest = hashlib.sha256()
        self.rewind()
        remaining = self.byte_size
        while remaining:
            block = self.stream.read(min(DOCUMENT_IO_CHUNK_BYTES, remaining))
            if type(block) is not bytes or not block:
                raise ValueError("fonte de conteudo truncada")
            if len(block) > remaining:
                raise ValueError("fonte de conteudo excede tamanho declarado")
            digest.update(block)
            remaining -= len(block)
        if self.stream.read(1):
            raise ValueError("fonte de conteudo excede tamanho declarado")
        self.rewind()
        return digest.hexdigest()

    def prefix(self, size: int) -> bytes:
        self.rewind()
        value = self.stream.read(min(size, self.byte_size))
        self.rewind()
        return value

    def suffix(self, size: int) -> bytes:
        offset = max(0, self.byte_size - size)
        self.stream.seek(offset)
        value = self.stream.read(self.byte_size - offset)
        self.rewind()
        return value


def as_seekable_content(content: bytes | SeekableContent) -> SeekableContent:
    if type(content) is bytes:
        return SeekableContent.from_bytes(content)
    if type(content) is not SeekableContent:
        raise TypeError("conteudo privado exige bytes ou fonte seekable")
    return content


@dataclass(slots=True)
class StreamBody:
    stream: BinaryIO = field(repr=False)
    byte_size: int
    _close: Callable[[], None] = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        if type(self.byte_size) is not int or self.byte_size < 0:
            raise ValueError("tamanho de body invalido")
        if not hasattr(self.stream, "read"):
            raise TypeError("body streaming invalido")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._close()
