"""Filesystem privado plano, ancorado, recuperável e fail-closed."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
from functools import wraps
from pathlib import Path
from uuid import uuid4

from ..application.models import (
    PrivateContent,
    PrivateContentId,
    PrivateContentMetadata,
    PrivateContentOrigin,
    WorkspaceId,
)
from ..application.ports import (
    RepositoryConflict,
    RepositoryError,
    RepositoryIntegrityError,
)


if os.name == "nt":
    import msvcrt

    _OPEN_BINARY = os.O_BINARY
    _OPEN_NOFOLLOW = 0
elif os.name == "posix":
    import fcntl

    _OPEN_BINARY = 0
    _OPEN_NOFOLLOW = os.O_NOFOLLOW
else:  # pragma: no cover
    raise RuntimeError("sistema operacional sem contrato de armazenamento privado")


DEFAULT_PRIVATE_CONTENT_LIMIT_BYTES = 64 * 1024 * 1024
_MANIFEST_SCHEMA_VERSION = 1
_MAX_MANIFEST_BYTES = 64 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_MAX_JOURNAL_ENTRIES = 10_000
_MAX_ROOT_ENTRIES = (
    _MAX_JOURNAL_ENTRIES
    * 16
) + 16
_LOCK_NAME = ".store-lock"
_JOURNAL_NAME = ".commit-log"
_ANCHOR_NAME = ".commit-anchor"
_MEMBERS = ("content", "metadata", "metadata-sha256")
_COMMITTED_MEMBERS = frozenset((*_MEMBERS, "commit"))
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_FINAL_NAME = re.compile(
    rf"^(?P<workspace>{_UUID})\.(?P<content>{_UUID})\."
    r"(?P<member>content|metadata|metadata-sha256|commit)$"
)
_STAGING_NAME = re.compile(
    rf"^\.staging\.(?P<workspace>{_UUID})\.(?P<content>{_UUID})\."
    r"(?P<nonce>[0-9a-f]{32})\."
    r"(?P<member>content|metadata|metadata-sha256|commit)$"
)
_RETIRED_NAME = re.compile(r"^\.retired\.(?P<nonce>[0-9a-f]{32})$")
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _controlled_filesystem_errors(message: str):
    def decorate(operation):
        @wraps(operation)
        def guarded(*args, **kwargs):
            try:
                return operation(*args, **kwargs)
            except RepositoryError:
                raise
            except OSError as exc:
                raise RepositoryError(message) from exc

        return guarded

    return decorate


def _path_is_link_or_reparse(path: Path) -> bool:
    details = os.lstat(path)
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _entry_name(path: Path) -> str:
    name = path.name
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise RepositoryIntegrityError("nome físico privado inválido")
    return name


def _lstat(path: Path, *, root_fd: int | None) -> os.stat_result:
    name = _entry_name(path)
    if root_fd is None:
        return os.lstat(path)
    return os.stat(name, dir_fd=root_fd, follow_symlinks=False)


def _entry_exists(path: Path, *, root_fd: int | None) -> bool:
    try:
        _lstat(path, root_fd=root_fd)
        return True
    except FileNotFoundError:
        return False


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _identity_key(left) == _identity_key(right)


def _identity_key(details: os.stat_result) -> tuple[int, int, int]:
    return (details.st_dev, details.st_ino, stat.S_IFMT(details.st_mode))


def _validate_regular(
    details: os.stat_result,
    *,
    expected_links: int | None,
) -> None:
    if not stat.S_ISREG(details.st_mode):
        raise RepositoryIntegrityError("objeto físico privado não é arquivo regular")
    if expected_links is not None and details.st_nlink != expected_links:
        raise RepositoryIntegrityError("arquivo privado possui hard link inesperado")
    if getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE:
        raise RepositoryIntegrityError("arquivo privado é reparse point")


def _validate_retired(details: os.stat_result) -> None:
    _validate_regular(details, expected_links=None)
    if details.st_nlink < 2 or details.st_nlink > 4:
        raise RepositoryIntegrityError("marcador privado aposentado sem vínculo exato")


def _open_existing_regular(
    path: Path,
    *,
    root_fd: int | None,
    expected_links: int = 1,
) -> tuple[int, os.stat_result]:
    try:
        before = _lstat(path, root_fd=root_fd)
        _validate_regular(before, expected_links=expected_links)
        flags = os.O_RDONLY | _OPEN_BINARY | _OPEN_NOFOLLOW
        if root_fd is None:
            descriptor = os.open(path, flags)
        else:
            descriptor = os.open(_entry_name(path), flags, dir_fd=root_fd)
        try:
            opened = os.fstat(descriptor)
            _validate_regular(opened, expected_links=expected_links)
            after = _lstat(path, root_fd=root_fd)
            if not _same_identity(before, opened) or not _same_identity(opened, after):
                raise RepositoryIntegrityError(
                    "identidade física privada mudou durante a abertura"
                )
            return descriptor, opened
        except Exception:
            os.close(descriptor)
            raise
    except RepositoryIntegrityError:
        raise
    except (FileNotFoundError, OSError) as exc:
        raise RepositoryIntegrityError("arquivo privado ausente ou inacessível") from exc


def _open_control_regular(
    path: Path,
    *,
    root_fd: int | None,
) -> tuple[int, os.stat_result]:
    flags = os.O_RDWR | _OPEN_BINARY | _OPEN_NOFOLLOW
    try:
        before = None
        try:
            before = _lstat(path, root_fd=root_fd)
            _validate_regular(before, expected_links=1)
        except FileNotFoundError:
            pass
        if root_fd is None:
            descriptor = os.open(path, flags, 0o600)
        else:
            descriptor = os.open(_entry_name(path), flags, 0o600, dir_fd=root_fd)
        try:
            opened = os.fstat(descriptor)
            _validate_regular(opened, expected_links=1)
            after = _lstat(path, root_fd=root_fd)
            if not _same_identity(opened, after) or (
                before is not None and not _same_identity(before, opened)
            ):
                raise RepositoryIntegrityError(
                    "identidade do controle privado mudou durante a abertura"
                )
            return descriptor, opened
        except Exception:
            os.close(descriptor)
            raise
    except RepositoryIntegrityError:
        raise
    except (FileNotFoundError, OSError) as exc:
        raise RepositoryIntegrityError("controle privado ausente ou inacessível") from exc


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset : offset + _READ_CHUNK_BYTES])
        if written <= 0:
            raise OSError("escrita privada não avançou")
        offset += written


def _write_fsynced(
    path: Path,
    payload: bytes,
    *,
    root_fd: int | None = None,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_BINARY | _OPEN_NOFOLLOW
    if root_fd is None:
        descriptor = os.open(path, flags, 0o600)
    else:
        descriptor = os.open(_entry_name(path), flags, 0o600, dir_fd=root_fd)
    opened = os.fstat(descriptor)
    try:
        _validate_regular(opened, expected_links=1)
        observed = _lstat(path, root_fd=root_fd)
        if not _same_identity(opened, observed):
            raise RepositoryIntegrityError(
                "identidade física privada mudou durante a criação"
            )
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    except Exception:
        os.close(descriptor)
        try:
            _retire_if_owned(path, opened, root_fd=root_fd)
        except (OSError, RepositoryIntegrityError):
            pass
        raise
    else:
        os.close(descriptor)


def _read_exact(descriptor: int, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        block = os.read(descriptor, min(_READ_CHUNK_BYTES, size - len(result)))
        if not block:
            break
        result.extend(block)
    return bytes(result)


def _read_regular(
    path: Path,
    *,
    root_fd: int | None,
    maximum_bytes: int,
    expected_size: int | None = None,
    expected_links: int = 1,
) -> bytes:
    descriptor, opened = _open_existing_regular(
        path,
        root_fd=root_fd,
        expected_links=expected_links,
    )
    try:
        if opened.st_size > maximum_bytes:
            raise RepositoryIntegrityError("arquivo privado excede limite operacional")
        if expected_size is not None and opened.st_size != expected_size:
            raise RepositoryIntegrityError("tamanho de arquivo privado diverge")
        payload = _read_exact(descriptor, opened.st_size)
        if len(payload) != opened.st_size or os.read(descriptor, 1):
            raise RepositoryIntegrityError("arquivo privado mudou durante a leitura")
        after = os.fstat(descriptor)
        if not _same_identity(opened, after) or after.st_size != opened.st_size:
            raise RepositoryIntegrityError("arquivo privado mudou durante a leitura")
        return payload
    finally:
        os.close(descriptor)


def _hash_regular(
    path: Path,
    *,
    root_fd: int | None,
    maximum_bytes: int,
    expected_size: int,
    load_content: bool,
    expected_links: int = 1,
) -> tuple[str, bytes | None]:
    descriptor, opened = _open_existing_regular(
        path,
        root_fd=root_fd,
        expected_links=expected_links,
    )
    try:
        if opened.st_size > maximum_bytes or opened.st_size != expected_size:
            raise RepositoryIntegrityError("tamanho do conteúdo privado diverge")
        digest = hashlib.sha256()
        content = bytearray() if load_content else None
        remaining = opened.st_size
        while remaining:
            block = os.read(descriptor, min(_READ_CHUNK_BYTES, remaining))
            if not block:
                raise RepositoryIntegrityError("conteúdo privado truncado")
            digest.update(block)
            if content is not None:
                content.extend(block)
            remaining -= len(block)
        if os.read(descriptor, 1):
            raise RepositoryIntegrityError("conteúdo privado cresceu durante a leitura")
        after = os.fstat(descriptor)
        if not _same_identity(opened, after) or after.st_size != opened.st_size:
            raise RepositoryIntegrityError("conteúdo privado mudou durante a leitura")
        return digest.hexdigest(), bytes(content) if content is not None else None
    finally:
        os.close(descriptor)


def _publish_durable(
    source: Path,
    destination: Path,
    *,
    expected_source: os.stat_result,
    root_fd: int | None = None,
) -> None:
    destination_identity = None
    try:
        observed_source = _lstat(source, root_fd=root_fd)
        _validate_regular(observed_source, expected_links=1)
        if not _same_identity(expected_source, observed_source):
            raise RepositoryIntegrityError(
                "identidade do staging privado mudou antes da publicação"
            )
        if root_fd is None:
            os.link(source, destination, follow_symlinks=False)
            destination_identity = os.lstat(destination)
        else:
            os.link(
                _entry_name(source),
                _entry_name(destination),
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
                follow_symlinks=False,
            )
            destination_identity = _lstat(destination, root_fd=root_fd)
        if not _same_identity(expected_source, destination_identity):
            raise RepositoryIntegrityError(
                "identidade do staging privado mudou durante a publicação"
            )
        if root_fd is not None:
            os.fsync(root_fd)
    except FileExistsError:
        raise
    except (OSError, RepositoryIntegrityError):
        if destination_identity is not None:
            try:
                _retire_if_owned(destination, expected_source, root_fd=root_fd)
            except (OSError, RepositoryIntegrityError):
                pass
        raise


def _retire_if_owned(
    path: Path,
    expected: os.stat_result,
    *,
    root_fd: int | None,
) -> None:
    observed = _lstat(path, root_fd=root_fd)
    _validate_regular(observed, expected_links=None)
    if not _same_identity(expected, observed):
        raise RepositoryIntegrityError(
            "identidade do objeto privado mudou antes da limpeza"
        )
    retired = path.parent / f".retired.{uuid4().hex}"
    if root_fd is None:
        os.link(path, retired, follow_symlinks=False)
        retired_details = os.lstat(retired)
    else:
        os.link(
            _entry_name(path),
            _entry_name(retired),
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
            follow_symlinks=False,
        )
        retired_details = _lstat(retired, root_fd=root_fd)
    _validate_retired(retired_details)
    if not _same_identity(expected, retired_details):
        raise RepositoryIntegrityError(
            "identidade do objeto privado mudou durante a aposentadoria"
        )
    if root_fd is not None:
        os.fsync(root_fd)


def _canonical_manifest(payload: dict) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RepositoryIntegrityError("metadados privados inválidos") from exc
    if len(encoded) > _MAX_MANIFEST_BYTES:
        raise RepositoryIntegrityError("manifesto privado excede limite")
    return encoded


def _manifest_for(metadata: PrivateContentMetadata) -> dict:
    return {
        "byteSize": metadata.byte_size,
        "checksumSha256": metadata.checksum_sha256,
        "contentId": str(metadata.content_id),
        "importedAt": metadata.imported_at,
        "mediaType": metadata.media_type,
        "origin": metadata.origin.value,
        "originalFilename": metadata.original_filename,
        "schemaVersion": _MANIFEST_SCHEMA_VERSION,
        "workspaceId": str(metadata.workspace_id),
    }


def _metadata_from_manifest(payload: object) -> PrivateContentMetadata:
    expected = {
        "byteSize",
        "checksumSha256",
        "contentId",
        "importedAt",
        "mediaType",
        "origin",
        "originalFilename",
        "schemaVersion",
        "workspaceId",
    }
    try:
        if type(payload) is not dict or set(payload) != expected:
            raise ValueError("campos de manifesto divergentes")
        if (
            type(payload["schemaVersion"]) is not int
            or payload["schemaVersion"] != _MANIFEST_SCHEMA_VERSION
        ):
            raise ValueError("versão de manifesto desconhecida")
        raw_workspace = payload["workspaceId"]
        raw_content = payload["contentId"]
        if type(raw_workspace) is not str or type(raw_content) is not str:
            raise ValueError("identidade privada inválida")
        workspace_id = WorkspaceId.parse(raw_workspace)
        content_id = PrivateContentId.parse(raw_content)
        if str(workspace_id) != raw_workspace or str(content_id) != raw_content:
            raise ValueError("identidade privada não canônica")
        return PrivateContentMetadata(
            workspace_id=workspace_id,
            content_id=content_id,
            original_filename=payload["originalFilename"],
            byte_size=payload["byteSize"],
            checksum_sha256=payload["checksumSha256"],
            media_type=payload["mediaType"],
            imported_at=payload["importedAt"],
            origin=PrivateContentOrigin(payload["origin"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("metadados privados inválidos") from exc


def _prefix(workspace_id: WorkspaceId, content_id: PrivateContentId) -> str:
    return f"{workspace_id}.{content_id}"


def _record_paths(
    root: Path,
    workspace_id: WorkspaceId,
    content_id: PrivateContentId,
) -> dict[str, Path]:
    prefix = _prefix(workspace_id, content_id)
    return {
        member: root / f"{prefix}.{member}" for member in _COMMITTED_MEMBERS
    }


class LocalPrivateContentStore:
    """Implementa o port privado em um namespace plano e ancorado."""

    def __init__(
        self,
        private_root: str | Path,
        *,
        max_content_bytes: int = DEFAULT_PRIVATE_CONTENT_LIMIT_BYTES,
    ):
        if not isinstance(private_root, (str, Path)):
            raise RepositoryError("private root inválido")
        raw = str(private_root)
        if not raw.strip() or "\x00" in raw:
            raise RepositoryError("private root inválido")
        if type(max_content_bytes) is not int or max_content_bytes < 0:
            raise RepositoryError("limite privado inválido")
        root = Path(private_root)
        if not root.is_absolute():
            raise RepositoryError("private root deve ser absoluto")
        self._mutex = threading.RLock()
        self._closed = False
        self._close_failed = False
        self._lock_stream = None
        self._lock_released = False
        self._lock_identity = None
        self._journal_fd = None
        self._journal_identity = None
        self._anchor_fd = None
        self._anchor_identity = None
        self._root_fd = None
        self._root_identity = None
        self._max_content_bytes = max_content_bytes
        try:
            if not os.path.lexists(root):
                raise RepositoryError(
                    "private root deve ser provisionado antes da abertura"
                )
            if _path_is_link_or_reparse(root):
                raise RepositoryIntegrityError(
                    "private root simbólico ou reparse não é permitido"
                )
            root_identity = os.lstat(root)
            if not stat.S_ISDIR(root_identity.st_mode):
                raise RepositoryIntegrityError("private root inválido")
            configured_root = root.absolute()
            self._root = root.resolve(strict=True)
            observed_root = os.lstat(configured_root)
            resolved_root = os.lstat(self._root)
            if (
                _path_is_link_or_reparse(configured_root)
                or not _same_identity(root_identity, observed_root)
                or not _same_identity(observed_root, resolved_root)
            ):
                raise RepositoryIntegrityError(
                    "identidade do private root mudou durante a abertura"
                )
            self._configured_root = configured_root
            self._root_identity = root_identity
            if os.name == "posix":
                self._root_fd = os.open(
                    self._root,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                )
                if not _same_identity(root_identity, os.fstat(self._root_fd)):
                    raise RepositoryIntegrityError(
                        "identidade do private root mudou durante a abertura"
                    )
            self._acquire_singleton()
            self._open_journal()
            self._open_anchor()
            self._committed = self._recover()
        except (RepositoryError, RepositoryIntegrityError):
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise RepositoryError("falha ao abrir armazenamento privado") from exc

    def _root_names(self) -> tuple[str, ...]:
        target = self._root if self._root_fd is None else self._root_fd
        names = []
        with os.scandir(target) as entries:
            for entry in entries:
                if len(names) >= _MAX_ROOT_ENTRIES:
                    raise RepositoryIntegrityError(
                        "inventário privado excede limite operacional"
                    )
                names.append(entry.name)
        return tuple(sorted(names))

    def _acquire_singleton(self) -> None:
        lock_path = self._root / _LOCK_NAME
        descriptor, identity = _open_control_regular(
            lock_path,
            root_fd=self._root_fd,
        )
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if os.fstat(descriptor).st_size != 1:
                raise RepositoryIntegrityError("trust anchor privado inválido")
            stream.seek(0)
            if stream.read(1) != b"0":
                raise RepositoryIntegrityError("trust anchor privado inválido")
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed_root = os.lstat(self._configured_root)
            if (
                _path_is_link_or_reparse(self._configured_root)
                or not _same_identity(self._root_identity, observed_root)
                or not _same_identity(observed_root, os.lstat(self._root))
            ):
                raise RepositoryIntegrityError("private root mudou durante a abertura")
        except (OSError, RepositoryIntegrityError) as exc:
            stream.close()
            if isinstance(exc, RepositoryIntegrityError):
                raise
            raise RepositoryConflict("armazenamento privado já está aberto") from exc
        self._lock_stream = stream
        self._lock_identity = identity

    def _open_journal(self) -> None:
        descriptor, identity = _open_control_regular(
            self._root / _JOURNAL_NAME,
            root_fd=self._root_fd,
        )
        os.fsync(descriptor)
        if self._root_fd is not None:
            os.fsync(self._root_fd)
        self._journal_fd = descriptor
        self._journal_identity = identity

    def _open_anchor(self) -> None:
        descriptor, identity = _open_control_regular(
            self._root / _ANCHOR_NAME,
            root_fd=self._root_fd,
        )
        os.fsync(descriptor)
        if self._root_fd is not None:
            os.fsync(self._root_fd)
        self._anchor_fd = descriptor
        self._anchor_identity = identity

    def _validate_control_identity(
        self,
        name: str,
        descriptor: int,
        expected: os.stat_result,
    ) -> None:
        observed = _lstat(self._root / name, root_fd=self._root_fd)
        opened = os.fstat(descriptor)
        _validate_regular(observed, expected_links=1)
        _validate_regular(opened, expected_links=1)
        if not _same_identity(expected, opened) or not _same_identity(opened, observed):
            raise RepositoryIntegrityError("identidade do controle privado diverge")

    @staticmethod
    def _is_partial_journal_entry(raw: bytes) -> bool:
        if not raw or len(raw) > 73:
            return False
        try:
            value = raw.decode("ascii")
        except UnicodeDecodeError:
            return False
        separators = {8: "-", 13: "-", 18: "-", 23: "-", 36: ".", 45: "-", 50: "-", 55: "-", 60: "-"}
        return all(
            character == separators[index]
            if index in separators
            else character in "0123456789abcdef"
            for index, character in enumerate(value)
        )

    def _ledger_entries(
        self,
        descriptor: int,
        *,
        label: str,
    ) -> tuple[tuple[str, ...], int, bytes | None]:
        os.lseek(descriptor, 0, os.SEEK_SET)
        pending = bytearray()
        entries = []
        seen = set()
        confirmed_bytes = 0
        while True:
            block = os.read(descriptor, _READ_CHUNK_BYTES)
            if not block:
                break
            pending.extend(block)
            while b"\n" in pending:
                raw, _, pending = pending.partition(b"\n")
                if len(raw) > 80:
                    raise RepositoryIntegrityError(f"{label} privado inválido")
                try:
                    entry = raw.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise RepositoryIntegrityError(f"{label} privado inválido") from exc
                if not re.fullmatch(rf"{_UUID}\.{_UUID}", entry) or entry in seen:
                    raise RepositoryIntegrityError(f"{label} privado inválido")
                if len(entries) >= _MAX_JOURNAL_ENTRIES:
                    raise RepositoryIntegrityError(f"{label} privado excede limite")
                entries.append(entry)
                seen.add(entry)
                confirmed_bytes += len(raw) + 1
            if len(pending) > 80:
                raise RepositoryIntegrityError(f"{label} privado inválido")
        if pending:
            raw_tail = bytes(pending)
            if not self._is_partial_journal_entry(raw_tail):
                raise RepositoryIntegrityError(f"{label} privado truncado")
            return tuple(entries), confirmed_bytes, raw_tail
        return tuple(entries), confirmed_bytes, None

    @staticmethod
    def _append_ledger(descriptor: int, prefix: str) -> None:
        os.lseek(descriptor, 0, os.SEEK_END)
        _write_all(descriptor, prefix.encode("ascii") + b"\n")
        os.fsync(descriptor)

    @staticmethod
    def _truncate_ledger(descriptor: int, size: int) -> None:
        os.ftruncate(descriptor, size)
        os.fsync(descriptor)

    def _append_intent(self, prefix: str) -> None:
        self._append_ledger(self._journal_fd, prefix)

    def _confirm_intent(self, prefix: str) -> None:
        self._append_ledger(self._anchor_fd, prefix)

    def _retire_internal(
        self,
        path: Path,
        *,
        expected: os.stat_result,
    ) -> None:
        _retire_if_owned(path, expected, root_fd=self._root_fd)

    def _all_existing_paths_retired(self, paths) -> bool:
        retired_identities = set()
        for name in self._root_names():
            if not _RETIRED_NAME.fullmatch(name):
                continue
            details = _lstat(self._root / name, root_fd=self._root_fd)
            _validate_retired(details)
            retired_identities.add(_identity_key(details))
        for path in paths:
            if not _entry_exists(path, root_fd=self._root_fd):
                continue
            details = _lstat(path, root_fd=self._root_fd)
            if _identity_key(details) not in retired_identities:
                return False
        return True

    def _audit_runtime_inventory(self) -> None:
        self._validate_control_identity(
            _LOCK_NAME,
            self._lock_stream.fileno(),
            self._lock_identity,
        )
        self._validate_control_identity(
            _JOURNAL_NAME,
            self._journal_fd,
            self._journal_identity,
        )
        self._validate_control_identity(
            _ANCHOR_NAME,
            self._anchor_fd,
            self._anchor_identity,
        )
        groups: dict[str, set[str]] = {}
        stage_groups: dict[str, set[str]] = {}
        stages = []
        finals = []
        retired_identities = set()
        for name in self._root_names():
            if name in {_LOCK_NAME, _JOURNAL_NAME, _ANCHOR_NAME}:
                continue
            if _RETIRED_NAME.fullmatch(name):
                details = _lstat(self._root / name, root_fd=self._root_fd)
                _validate_retired(details)
                retired_identities.add(_identity_key(details))
                continue
            stage = _STAGING_NAME.fullmatch(name)
            if stage:
                details = _lstat(self._root / name, root_fd=self._root_fd)
                _validate_regular(details, expected_links=None)
                stages.append(
                    (
                        f"{stage['workspace']}.{stage['content']}",
                        stage["member"],
                        details,
                    )
                )
                continue
            final = _FINAL_NAME.fullmatch(name)
            if final is None:
                raise RepositoryIntegrityError("objeto inesperado no private root")
            prefix = f"{final['workspace']}.{final['content']}"
            details = _lstat(self._root / name, root_fd=self._root_fd)
            _validate_regular(details, expected_links=None)
            finals.append((prefix, final["member"], details))

        def is_retired(details: os.stat_result) -> bool:
            return _identity_key(details) in retired_identities

        stages = [item for item in stages if not is_retired(item[2])]
        finals = [item for item in finals if not is_retired(item[2])]
        finals_by_key = {
            (prefix, member): details for prefix, member, details in finals
        }
        for prefix, member, _ in stages:
            stage_groups.setdefault(prefix, set()).add(member)
        for prefix, member, _ in finals:
            groups.setdefault(prefix, set()).add(member)
        if set(groups) != self._committed or any(
            members != _COMMITTED_MEMBERS for members in groups.values()
        ) or set(stage_groups) != self._committed or any(
            members != _COMMITTED_MEMBERS for members in stage_groups.values()
        ):
            raise RepositoryIntegrityError("inventário privado diverge do estado confirmado")
        for prefix, member, stage_details in stages:
            final_details = finals_by_key.get((prefix, member))
            if final_details is None or not _same_identity(
                stage_details, final_details
            ):
                raise RepositoryIntegrityError(
                    "staging privado confirmado sem destino exato"
                )
            _validate_regular(stage_details, expected_links=2)
            _validate_regular(final_details, expected_links=2)
        journal, _, journal_tail = self._ledger_entries(
            self._journal_fd, label="journal"
        )
        anchor, _, anchor_tail = self._ledger_entries(
            self._anchor_fd, label="anchor"
        )
        if (
            journal_tail is not None
            or anchor_tail is not None
            or journal != anchor
            or set(journal) != self._committed
        ):
            raise RepositoryIntegrityError("journal privado diverge do estado confirmado")

    def _recover(self) -> set[str]:
        groups: dict[str, set[str]] = {}
        stages: list[tuple[str, str, Path, os.stat_result]] = []
        final_objects: list[tuple[str, str, Path, os.stat_result]] = []
        retired_identities = set()
        for name in self._root_names():
            if name in {_LOCK_NAME, _JOURNAL_NAME, _ANCHOR_NAME}:
                continue
            if _RETIRED_NAME.fullmatch(name):
                retired_path = self._root / name
                retired_details = _lstat(retired_path, root_fd=self._root_fd)
                _validate_retired(retired_details)
                retired_identities.add(_identity_key(retired_details))
                continue
            stage = _STAGING_NAME.fullmatch(name)
            if stage:
                stage_path = self._root / name
                stage_details = _lstat(stage_path, root_fd=self._root_fd)
                _validate_regular(stage_details, expected_links=None)
                stage_prefix = f"{stage['workspace']}.{stage['content']}"
                stages.append(
                    (stage_prefix, stage["member"], stage_path, stage_details)
                )
                continue
            final = _FINAL_NAME.fullmatch(name)
            if final is None:
                raise RepositoryIntegrityError("objeto inesperado no private root")
            prefix = f"{final['workspace']}.{final['content']}"
            final_path = self._root / name
            final_objects.append(
                (
                    prefix,
                    final["member"],
                    final_path,
                    _lstat(final_path, root_fd=self._root_fd),
                )
            )

        def is_retired(details: os.stat_result) -> bool:
            return _identity_key(details) in retired_identities

        stages = [item for item in stages if not is_retired(item[3])]
        final_objects = [item for item in final_objects if not is_retired(item[3])]
        finals_by_key = {
            (prefix, member): (path, details)
            for prefix, member, path, details in final_objects
        }
        for prefix, member, _, _ in final_objects:
            groups.setdefault(prefix, set()).add(member)

        journal, _, journal_tail = self._ledger_entries(
            self._journal_fd, label="journal"
        )
        anchor, anchor_bytes, anchor_tail = self._ledger_entries(
            self._anchor_fd, label="anchor"
        )

        common_length = 0
        for journal_entry, anchor_entry in zip(journal, anchor):
            if journal_entry != anchor_entry:
                break
            common_length += 1
        if common_length != min(len(journal), len(anchor)):
            raise RepositoryIntegrityError("journal e anchor privados divergem")
        if len(anchor) > len(journal):
            raise RepositoryIntegrityError("journal privado perdeu proveniência")
        common = list(anchor)
        journal_extra = journal[len(anchor) :]
        if len(journal_extra) > 1 or (journal_extra and journal_tail):
            raise RepositoryIntegrityError("journal privado perdeu proveniência")
        committed_groups = {
            prefix for prefix, members in groups.items() if "commit" in members
        }
        uncommitted_groups = set(groups) - committed_groups

        pending_prefix = journal_extra[0] if journal_extra else None
        if journal_tail is not None:
            if anchor_tail is not None:
                raise RepositoryIntegrityError("journal privado perdeu proveniência")
            fragment = journal_tail.decode("ascii")
            candidates = [
                prefix
                for prefix in uncommitted_groups
                if prefix.startswith(fragment)
            ]
            if len(candidates) != 1:
                raise RepositoryIntegrityError(
                    "journal privado truncado sem proveniência"
                )
            pending_prefix = candidates[0]
        if anchor_tail is not None:
            if (
                pending_prefix is None
                or not pending_prefix.startswith(anchor_tail.decode("ascii"))
                or pending_prefix not in committed_groups
            ):
                raise RepositoryIntegrityError(
                    "anchor privado truncado sem proveniência"
                )
        if any(prefix not in committed_groups for prefix in common):
            raise RepositoryIntegrityError("journal privado diverge de commits confirmados")
        expected_commits = set(common)
        if pending_prefix in committed_groups:
            expected_commits.add(pending_prefix)
        if expected_commits != committed_groups:
            raise RepositoryIntegrityError("journal privado diverge de commits confirmados")

        linked_members: dict[str, set[str]] = {}
        for stage_prefix, stage_member, stage_path, stage_details in stages:
            if stage_prefix != pending_prefix and stage_prefix not in committed_groups:
                raise RepositoryIntegrityError("staging privado sem proveniência durável")
            if stage_prefix == pending_prefix and stage_prefix not in committed_groups:
                continue
            if stage_details.st_nlink == 1:
                raise RepositoryIntegrityError(
                    "staging privado confirmado sem destino exato"
                )
            if stage_details.st_nlink != 2:
                raise RepositoryIntegrityError("staging privado possui hard link inesperado")
            matching = finals_by_key.get((stage_prefix, stage_member))
            if matching is None:
                raise RepositoryIntegrityError("hard link de staging sem destino exato")
            final_path, final_details = matching
            observed_final = _lstat(final_path, root_fd=self._root_fd)
            if not _same_identity(final_details, observed_final) or not _same_identity(
                stage_details, observed_final
            ):
                raise RepositoryIntegrityError("hard link de staging sem destino exato")
            linked_members.setdefault(stage_prefix, set()).add(stage_member)

        for prefix, member, final_path, details in final_objects:
            expected_links = (
                None
                if prefix == pending_prefix and prefix not in committed_groups
                else 2 if member in linked_members.get(prefix, set()) else 1
            )
            _validate_regular(details, expected_links=expected_links)

        committed = set()
        cleanup_finals: list[tuple[Path, os.stat_result]] = []
        for prefix, members in groups.items():
            workspace_raw, content_raw = prefix.split(".", 1)
            workspace_id = WorkspaceId.parse(workspace_raw)
            content_id = PrivateContentId.parse(content_raw)
            paths = _record_paths(self._root, workspace_id, content_id)
            if prefix in committed_groups:
                if members != _COMMITTED_MEMBERS:
                    raise RepositoryIntegrityError(
                        "registro privado confirmado incompleto"
                    )
                self._read_record(
                    workspace_id,
                    content_id,
                    load_content=False,
                    recovery_link_members=frozenset(linked_members.get(prefix, set())),
                )
                committed.add(prefix)
                continue
            if "commit" not in members:
                if (
                    prefix != pending_prefix
                    or not members.issubset(set(_MEMBERS))
                ):
                    raise RepositoryIntegrityError(
                        "registro privado sem proveniência durável"
                    )
                for member in members:
                    cleanup_path = paths[member]
                    final_match = finals_by_key.get((prefix, member))
                    if final_match is None:
                        raise RepositoryIntegrityError(
                            "registro privado sem proveniência durável"
                        )
                    cleanup_finals.append(
                        (
                            cleanup_path,
                            final_match[1],
                        )
                    )
                continue
            raise RepositoryIntegrityError("registro privado confirmado incompleto")

        common_bytes = sum(len(entry) + 1 for entry in common)
        pending_is_committed = pending_prefix in committed_groups
        for final_path, final_details in cleanup_finals:
            self._retire_internal(final_path, expected=final_details)
        for stage_prefix, _, stage_path, stage_details in stages:
            if stage_prefix not in committed_groups:
                self._retire_internal(stage_path, expected=stage_details)
        if journal_tail is not None or (
            pending_prefix is not None and not pending_is_committed
        ):
            self._truncate_ledger(self._journal_fd, common_bytes)
        if pending_is_committed:
            self._truncate_ledger(self._anchor_fd, common_bytes)
            self._append_ledger(self._anchor_fd, pending_prefix)
        elif anchor_bytes != common_bytes or anchor_tail is not None:
            self._truncate_ledger(self._anchor_fd, common_bytes)
        return committed

    def _ensure_open(self) -> None:
        if self._closed or self._close_failed:
            raise RepositoryError("armazenamento privado fechado")

    @staticmethod
    def _validate_keys(
        workspace_id: WorkspaceId,
        content_id: PrivateContentId | None = None,
    ) -> None:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        if content_id is not None and type(content_id) is not PrivateContentId:
            raise TypeError("content_id inválido")

    def _read_record(
        self,
        workspace_id: WorkspaceId,
        content_id: PrivateContentId,
        *,
        load_content: bool,
        require_commit: bool = True,
        recovery_link_members: frozenset[str] = _COMMITTED_MEMBERS,
    ) -> PrivateContent | PrivateContentMetadata:
        paths = _record_paths(self._root, workspace_id, content_id)
        metadata_bytes = _read_regular(
            paths["metadata"],
            root_fd=self._root_fd,
            maximum_bytes=_MAX_MANIFEST_BYTES,
            expected_links=2 if "metadata" in recovery_link_members else 1,
        )
        checksum_bytes = _read_regular(
            paths["metadata-sha256"],
            root_fd=self._root_fd,
            maximum_bytes=64,
            expected_size=64,
            expected_links=(
                2 if "metadata-sha256" in recovery_link_members else 1
            ),
        )
        commit_bytes = None
        if require_commit:
            commit_bytes = _read_regular(
                paths["commit"],
                root_fd=self._root_fd,
                maximum_bytes=64,
                expected_size=64,
                expected_links=2 if "commit" in recovery_link_members else 1,
            )
        try:
            declared_metadata_checksum = checksum_bytes.decode("ascii")
            declared_commit = (
                commit_bytes.decode("ascii") if commit_bytes is not None else None
            )
        except UnicodeDecodeError as exc:
            raise RepositoryIntegrityError("checksum de metadados inválido") from exc
        actual_metadata_checksum = hashlib.sha256(metadata_bytes).hexdigest()
        if (
            len(declared_metadata_checksum) != 64
            or any(
                character not in "0123456789abcdef"
                for character in declared_metadata_checksum
            )
            or declared_metadata_checksum != actual_metadata_checksum
            or (
                declared_commit is not None
                and declared_commit != actual_metadata_checksum
            )
        ):
            raise RepositoryIntegrityError("metadados privados divergem do checksum")
        try:
            payload = json.loads(metadata_bytes.decode("utf-8"))
        except (
            RecursionError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            raise RepositoryIntegrityError("metadados privados inválidos") from exc
        if _canonical_manifest(payload) != metadata_bytes:
            raise RepositoryIntegrityError("metadados privados não são canônicos")
        metadata = _metadata_from_manifest(payload)
        if metadata.workspace_id != workspace_id or metadata.content_id != content_id:
            raise RepositoryIntegrityError("identidade do conteúdo privado diverge")
        if metadata.byte_size > self._max_content_bytes:
            raise RepositoryIntegrityError("conteúdo privado excede limite operacional")
        checksum, content = _hash_regular(
            paths["content"],
            root_fd=self._root_fd,
            maximum_bytes=self._max_content_bytes,
            expected_size=metadata.byte_size,
            load_content=load_content,
            expected_links=2 if "content" in recovery_link_members else 1,
        )
        if checksum != metadata.checksum_sha256:
            raise RepositoryIntegrityError("conteúdo privado diverge do checksum")
        if not load_content:
            return metadata
        try:
            return PrivateContent(metadata, content)
        except (TypeError, ValueError) as exc:
            raise RepositoryIntegrityError("conteúdo privado corrompido") from exc

    @_controlled_filesystem_errors("falha ao armazenar conteúdo privado")
    def store(
        self,
        metadata: PrivateContentMetadata,
        content: bytes,
    ) -> PrivateContentMetadata:
        self._ensure_open()
        if (
            type(content) is bytes and len(content) > self._max_content_bytes
        ) or (
            type(metadata) is PrivateContentMetadata
            and metadata.byte_size > self._max_content_bytes
        ):
            raise RepositoryError("conteúdo privado excede limite operacional")
        record = PrivateContent(metadata, content)
        self._validate_keys(metadata.workspace_id, metadata.content_id)
        prefix = _prefix(metadata.workspace_id, metadata.content_id)
        paths = _record_paths(self._root, metadata.workspace_id, metadata.content_id)
        with self._mutex:
            self._ensure_open()
            self._audit_runtime_inventory()
            if prefix in self._committed or any(
                _entry_exists(path, root_fd=self._root_fd)
                for path in paths.values()
            ):
                raise RepositoryConflict("identidade de conteúdo privado já existe")
            if len(self._committed) >= _MAX_JOURNAL_ENTRIES:
                raise RepositoryError("armazenamento privado atingiu limite de registros")
            nonce = uuid4().hex
            stages = {
                member: self._root / f".staging.{prefix}.{nonce}.{member}"
                for member in (*_MEMBERS, "commit")
            }
            manifest = _canonical_manifest(_manifest_for(metadata))
            metadata_checksum = hashlib.sha256(manifest).hexdigest().encode("ascii")
            published: list[tuple[Path, os.stat_result]] = []
            stage_identities: dict[Path, os.stat_result] = {}
            journal_start = os.lseek(self._journal_fd, 0, os.SEEK_END)
            anchor_start = os.lseek(self._anchor_fd, 0, os.SEEK_END)
            commit_created = False
            try:
                self._append_intent(prefix)
                _write_fsynced(stages["content"], record.content, root_fd=self._root_fd)
                stage_identities[stages["content"]] = _lstat(
                    stages["content"], root_fd=self._root_fd
                )
                _write_fsynced(stages["metadata"], manifest, root_fd=self._root_fd)
                stage_identities[stages["metadata"]] = _lstat(
                    stages["metadata"], root_fd=self._root_fd
                )
                _write_fsynced(
                    stages["metadata-sha256"],
                    metadata_checksum,
                    root_fd=self._root_fd,
                )
                stage_identities[stages["metadata-sha256"]] = _lstat(
                    stages["metadata-sha256"], root_fd=self._root_fd
                )
                for member in _MEMBERS:
                    _publish_durable(
                        stages[member],
                        paths[member],
                        expected_source=stage_identities[stages[member]],
                        root_fd=self._root_fd,
                    )
                    published.append(
                        (
                            paths[member],
                            _lstat(paths[member], root_fd=self._root_fd),
                        )
                    )
                verified = self._read_record(
                    metadata.workspace_id,
                    metadata.content_id,
                    load_content=True,
                    require_commit=False,
                    recovery_link_members=frozenset(_MEMBERS),
                )
                if verified != record:
                    raise RepositoryIntegrityError(
                        "verificação final do conteúdo privado diverge"
                    )
                _write_fsynced(
                    stages["commit"],
                    metadata_checksum,
                    root_fd=self._root_fd,
                )
                stage_identities[stages["commit"]] = _lstat(
                    stages["commit"], root_fd=self._root_fd
                )
                _publish_durable(
                    stages["commit"],
                    paths["commit"],
                    expected_source=stage_identities[stages["commit"]],
                    root_fd=self._root_fd,
                )
                commit_created = True
                self._confirm_intent(prefix)
                self._committed.add(prefix)
                return metadata
            except FileExistsError as exc:
                raise RepositoryConflict(
                    "identidade de conteúdo privado já existe"
                ) from exc
            except (RepositoryConflict, RepositoryIntegrityError):
                raise
            except OSError as exc:
                raise RepositoryError("falha ao armazenar conteúdo privado") from exc
            finally:
                if not commit_created:
                    cleanup_complete = True
                    for path, identity in published:
                        try:
                            if _entry_exists(path, root_fd=self._root_fd):
                                self._retire_internal(path, expected=identity)
                        except (OSError, RepositoryIntegrityError):
                            cleanup_complete = False
                    for stage in stages.values():
                        try:
                            if stage in stage_identities and _entry_exists(
                                stage, root_fd=self._root_fd
                            ):
                                self._retire_internal(
                                    stage,
                                    expected=stage_identities[stage],
                                )
                        except (OSError, RepositoryIntegrityError):
                            cleanup_complete = False
                    try:
                        cleanup_complete = cleanup_complete and (
                            self._all_existing_paths_retired(
                                (*paths.values(), *stages.values())
                            )
                        )
                    except (OSError, RepositoryIntegrityError):
                        cleanup_complete = False
                    if cleanup_complete:
                        try:
                            self._truncate_ledger(self._journal_fd, journal_start)
                            self._truncate_ledger(self._anchor_fd, anchor_start)
                        except OSError:
                            pass

    @_controlled_filesystem_errors("falha ao ler conteúdo privado")
    def get(
        self,
        workspace_id: WorkspaceId,
        content_id: PrivateContentId,
    ) -> PrivateContent | None:
        self._ensure_open()
        self._validate_keys(workspace_id, content_id)
        prefix = _prefix(workspace_id, content_id)
        with self._mutex:
            self._ensure_open()
            self._audit_runtime_inventory()
            if prefix not in self._committed:
                return None
            result = self._read_record(workspace_id, content_id, load_content=True)
            if type(result) is not PrivateContent:
                raise RepositoryIntegrityError("conteúdo privado inválido")
            return result

    @_controlled_filesystem_errors("falha ao listar conteúdo privado")
    def list_all(
        self,
        workspace_id: WorkspaceId,
    ) -> tuple[PrivateContentMetadata, ...]:
        self._ensure_open()
        self._validate_keys(workspace_id)
        with self._mutex:
            self._ensure_open()
            self._audit_runtime_inventory()
            records = []
            prefix_start = f"{workspace_id}."
            for prefix in sorted(self._committed):
                if not prefix.startswith(prefix_start):
                    continue
                content_id = PrivateContentId.parse(prefix[len(prefix_start) :])
                result = self._read_record(workspace_id, content_id, load_content=False)
                if type(result) is not PrivateContentMetadata:
                    raise RepositoryIntegrityError("metadados privados inválidos")
                records.append(result)
            return tuple(records)

    @_controlled_filesystem_errors("falha ao fechar armazenamento privado")
    def close(self) -> None:
        mutex = getattr(self, "_mutex", None)
        if mutex is None:
            return
        with mutex:
            if getattr(self, "_closed", True):
                return
            failures = []
            if self._journal_fd is not None:
                try:
                    os.close(self._journal_fd)
                    self._journal_fd = None
                    self._journal_identity = None
                except OSError as exc:
                    failures.append(exc)
            if self._anchor_fd is not None:
                try:
                    os.close(self._anchor_fd)
                    self._anchor_fd = None
                    self._anchor_identity = None
                except OSError as exc:
                    failures.append(exc)
            if self._lock_stream is not None:
                try:
                    if not self._lock_released:
                        self._lock_stream.seek(0)
                        if os.name == "nt":
                            msvcrt.locking(
                                self._lock_stream.fileno(),
                                msvcrt.LK_UNLCK,
                                1,
                            )
                        else:
                            fcntl.flock(self._lock_stream.fileno(), fcntl.LOCK_UN)
                        self._lock_released = True
                    self._lock_stream.close()
                    self._lock_stream = None
                    self._lock_identity = None
                except OSError as exc:
                    failures.append(exc)
            if self._root_fd is not None:
                try:
                    os.close(self._root_fd)
                    self._root_fd = None
                except OSError as exc:
                    failures.append(exc)
            self._close_failed = bool(failures)
            self._closed = not failures and all(
                resource is None
                for resource in (
                    self._journal_fd,
                    self._anchor_fd,
                    self._lock_stream,
                    self._root_fd,
                )
            )
            if failures:
                raise failures[0]

    def __enter__(self) -> LocalPrivateContentStore:
        self._ensure_open()
        return self

    def __exit__(self, _exc_type, exc_value, _traceback) -> None:
        try:
            self.close()
        except RepositoryError as close_error:
            if exc_value is None:
                raise
            exc_value.add_note(
                f"falha adicional ao fechar armazenamento privado: {close_error}"
            )
