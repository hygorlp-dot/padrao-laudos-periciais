"""Read-only Git worktree facts from the `.git` files themselves.

No process is spawned: the tracked-path list comes from the index file and the
live HEAD from `HEAD`/refs/packed-refs. Anything this reader does not understand
(split or sparse index, unknown version, truncated data) fails closed with
`GitWorktreeError` instead of guessing.
"""
from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path

SHA_HEX = r"[0-9a-f]{40}"
_ENTRY_FIXED = 62
_EXTENDED_FLAG = 0x4000
_NAME_MASK = 0x0FFF
_MODE_TYPE_MASK = 0o170000
_MODE_DIRECTORY = 0o040000
_MODE_SYMLINK = 0o120000
_MODE_GITLINK = 0o160000
_UNSUPPORTED_EXTENSIONS = {b"link", b"sdir"}


class GitWorktreeError(RuntimeError):
    """The Git metadata cannot be read with certainty."""


@dataclass(frozen=True)
class IndexEntry:
    path: str
    mode: int
    blob_sha: str

    @property
    def is_symlink(self) -> bool:
        return self.mode & _MODE_TYPE_MASK == _MODE_SYMLINK

    @property
    def is_gitlink(self) -> bool:
        return self.mode & _MODE_TYPE_MASK == _MODE_GITLINK


def git_dir(root: Path) -> Path:
    dot_git = Path(root) / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir:"):
            raise GitWorktreeError("unrecognized .git file")
        target = Path(text[len("gitdir:"):].strip())
        return target if target.is_absolute() else (Path(root) / target).resolve()
    raise GitWorktreeError("not a Git worktree")


def _common_dir(gdir: Path) -> Path:
    marker = gdir / "commondir"
    if not marker.is_file():
        return gdir
    target = Path(marker.read_text(encoding="utf-8").strip())
    return target if target.is_absolute() else (gdir / target).resolve()


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    # Offset encoding of index v4 path prefixes (same as OFS_DELTA in packs).
    byte = data[offset]
    offset += 1
    value = byte & 0x7F
    while byte & 0x80:
        byte = data[offset]
        offset += 1
        value = ((value + 1) << 7) | (byte & 0x7F)
    return value, offset


def read_index(root: Path) -> tuple[IndexEntry, ...]:
    """Every stage-0 entry of the index, in index order (sorted by path)."""
    path = git_dir(root) / "index"
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GitWorktreeError("index unavailable") from exc
    if len(data) < 32 or data[:4] != b"DIRC":
        raise GitWorktreeError("index signature")
    if hashlib.sha1(data[:-20]).digest() != data[-20:]:
        raise GitWorktreeError("index checksum")
    version, count = struct.unpack(">II", data[4:12])
    if version not in {2, 3, 4}:
        raise GitWorktreeError(f"index version {version}")
    offset = 12
    previous = b""
    entries: list[IndexEntry] = []
    end = len(data) - 20
    for _ in range(count):
        if offset + _ENTRY_FIXED > end:
            raise GitWorktreeError("truncated index entry")
        mode = struct.unpack(">I", data[offset + 24:offset + 28])[0]
        blob = data[offset + 40:offset + 60].hex()
        flags = struct.unpack(">H", data[offset + 60:offset + 62])[0]
        cursor = offset + _ENTRY_FIXED
        if flags & _EXTENDED_FLAG:
            if version < 3:
                raise GitWorktreeError("extended flag in index v2")
            cursor += 2
        if version == 4:
            strip, cursor = _varint(data, cursor)
            terminator = data.index(b"\0", cursor)
            if strip > len(previous):
                raise GitWorktreeError("index v4 prefix")
            name = previous[:len(previous) - strip] + data[cursor:terminator]
            offset = terminator + 1
        else:
            terminator = data.index(b"\0", cursor)
            name = data[cursor:terminator]
            if (flags & _NAME_MASK) != _NAME_MASK and len(name) != flags & _NAME_MASK:
                raise GitWorktreeError("index name length")
            entry_length = terminator - offset
            offset += (entry_length // 8 + 1) * 8
        previous = name
        if mode & _MODE_TYPE_MASK == _MODE_DIRECTORY:
            raise GitWorktreeError("sparse index is not supported")
        stage = (flags >> 12) & 0x3
        if stage:
            continue
        entries.append(IndexEntry(name.decode("utf-8"), mode, blob))
    while offset + 8 <= end:
        signature = data[offset:offset + 4]
        size = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        if signature in _UNSUPPORTED_EXTENSIONS:
            raise GitWorktreeError(f"index extension {signature.decode()} is not supported")
        offset += 8 + size
    return tuple(entries)


def tracked_paths(root: Path) -> tuple[str, ...]:
    return tuple(entry.path for entry in read_index(root))


def _resolve_ref(gdir: Path, ref: str) -> str | None:
    for base in (gdir, _common_dir(gdir)):
        loose = base / ref
        if loose.is_file():
            value = loose.read_text(encoding="utf-8").strip()
            if re.fullmatch(SHA_HEX, value):
                return value
            raise GitWorktreeError(f"unreadable ref {ref}")
    packed = _common_dir(gdir) / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2 and parts[1] == ref and re.fullmatch(SHA_HEX, parts[0]):
                return parts[0]
    return None


def live_head(root: Path) -> str:
    """The commit HEAD points to right now, read from `.git` (never a tracked file)."""
    gdir = git_dir(root)
    text = (gdir / "HEAD").read_text(encoding="utf-8").strip()
    if re.fullmatch(SHA_HEX, text):
        return text
    if not text.startswith("ref: "):
        raise GitWorktreeError("unrecognized HEAD")
    sha = _resolve_ref(gdir, text[len("ref: "):])
    if sha is None:
        raise GitWorktreeError("HEAD has no commit")
    return sha
