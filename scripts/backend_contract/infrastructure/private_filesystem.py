"""Filesystem local privado com identidade interna, integridade e escrita atômica."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

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


_MANIFEST_SCHEMA_VERSION = 1
_RECORD_FILES = frozenset({"content.bin", "metadata.json", "metadata.sha256"})
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

if os.name == "nt":
    _OPEN_BINARY = os.O_BINARY
    _OPEN_NOFOLLOW = 0
elif os.name == "posix":
    _OPEN_BINARY = 0
    _OPEN_NOFOLLOW = os.O_NOFOLLOW
else:  # pragma: no cover - fail closed on unsupported operating systems
    raise RuntimeError("sistema operacional sem contrato de armazenamento privado")


def _path_is_link_or_reparse(path: Path) -> bool:
    details = os.lstat(path)
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _write_fsynced(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _canonical_manifest(payload: dict) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RepositoryIntegrityError("metadados privados inválidos") from exc
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
        if payload["schemaVersion"] != _MANIFEST_SCHEMA_VERSION:
            raise ValueError("versão de manifesto desconhecida")
        return PrivateContentMetadata(
            workspace_id=WorkspaceId.parse(payload["workspaceId"]),
            content_id=PrivateContentId.parse(payload["contentId"]),
            original_filename=payload["originalFilename"],
            byte_size=payload["byteSize"],
            checksum_sha256=payload["checksumSha256"],
            media_type=payload["mediaType"],
            imported_at=payload["importedAt"],
            origin=PrivateContentOrigin(payload["origin"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RepositoryIntegrityError("metadados privados inválidos") from exc


class LocalPrivateContentStore:
    """Implementa o port privado sob um root explícito e sem expor paths."""

    def __init__(self, private_root: str | Path):
        if not isinstance(private_root, (str, Path)):
            raise RepositoryError("private root inválido")
        raw = str(private_root)
        if not raw.strip() or "\x00" in raw:
            raise RepositoryError("private root inválido")
        root = Path(private_root)
        if not root.is_absolute():
            raise RepositoryError("private root deve ser absoluto")
        try:
            if os.path.lexists(root) and _path_is_link_or_reparse(root):
                raise RepositoryIntegrityError(
                    "private root simbólico ou reparse não é permitido"
                )
            root.mkdir(parents=True, exist_ok=True)
            if _path_is_link_or_reparse(root) or not root.is_dir():
                raise RepositoryIntegrityError("private root inválido")
            self._root = root.resolve(strict=True)
            self._workspaces = self._root / "workspaces"
            self._staging = self._root / ".staging"
            self._leases = self._root / ".leases"
            self._workspaces.mkdir(exist_ok=True)
            self._staging.mkdir(exist_ok=True)
            self._leases.mkdir(exist_ok=True)
            for internal in (self._workspaces, self._staging, self._leases):
                self._assert_safe_path(internal)
        except (RepositoryError, RepositoryIntegrityError):
            raise
        except OSError as exc:
            raise RepositoryError("falha ao abrir armazenamento privado") from exc
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise RepositoryError("armazenamento privado fechado")

    def _assert_safe_path(self, path: Path) -> None:
        try:
            relative = path.relative_to(self._root)
        except ValueError as exc:
            raise RepositoryIntegrityError(
                "path de armazenamento privado escapou do root"
            ) from exc
        current = self._root
        for part in relative.parts:
            current = current / part
            if os.path.lexists(current) and _path_is_link_or_reparse(current):
                raise RepositoryIntegrityError(
                    "path simbólico ou reparse no armazenamento privado"
                )
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(self._root)
        except (OSError, ValueError) as exc:
            raise RepositoryIntegrityError(
                "path de armazenamento privado escapou do root"
            ) from exc

    @staticmethod
    def _validate_keys(
        workspace_id: WorkspaceId, content_id: PrivateContentId | None = None
    ) -> None:
        if type(workspace_id) is not WorkspaceId:
            raise TypeError("workspace_id inválido")
        if content_id is not None and type(content_id) is not PrivateContentId:
            raise TypeError("content_id inválido")

    def _contents_dir(self, workspace_id: WorkspaceId) -> Path:
        self._validate_keys(workspace_id)
        return self._workspaces / str(workspace_id) / "contents"

    def _record_dir(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> Path:
        self._validate_keys(workspace_id, content_id)
        return self._contents_dir(workspace_id) / str(content_id)

    def _lease_path(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> Path:
        self._validate_keys(workspace_id, content_id)
        return self._leases / f"{workspace_id}.{content_id}.lease"

    def _ensure_contents_dir(self, workspace_id: WorkspaceId) -> Path:
        contents = self._contents_dir(workspace_id)
        try:
            contents.mkdir(parents=True, exist_ok=True)
            self._assert_safe_path(contents)
            if not contents.is_dir():
                raise RepositoryIntegrityError("diretório privado inválido")
            return contents
        except (RepositoryIntegrityError, RepositoryError):
            raise
        except OSError as exc:
            raise RepositoryError("falha ao preparar armazenamento privado") from exc

    def _read_regular(self, path: Path) -> bytes:
        self._assert_safe_path(path)
        try:
            if not os.path.lexists(path):
                raise RepositoryIntegrityError("registro privado incompleto")
            if _path_is_link_or_reparse(path):
                raise RepositoryIntegrityError(
                    "arquivo simbólico ou reparse no armazenamento privado"
                )
            flags = os.O_RDONLY | _OPEN_BINARY | _OPEN_NOFOLLOW
            descriptor = os.open(path, flags)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise RepositoryIntegrityError("registro privado incompleto")
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    return stream.read()
            finally:
                os.close(descriptor)
        except RepositoryIntegrityError:
            raise
        except OSError as exc:
            raise RepositoryError("falha ao ler conteúdo privado") from exc

    def _read_record(
        self,
        record_dir: Path,
        workspace_id: WorkspaceId,
        content_id: PrivateContentId,
    ) -> PrivateContent:
        self._assert_safe_path(record_dir)
        try:
            if _path_is_link_or_reparse(record_dir):
                raise RepositoryIntegrityError(
                    "diretório simbólico ou reparse no armazenamento privado"
                )
            if not record_dir.is_dir():
                raise RepositoryIntegrityError("registro privado incompleto")
            inventory = {item.name for item in record_dir.iterdir()}
        except RepositoryIntegrityError:
            raise
        except OSError as exc:
            raise RepositoryError("falha ao inspecionar conteúdo privado") from exc
        if inventory != _RECORD_FILES:
            raise RepositoryIntegrityError("registro privado incompleto ou inesperado")

        content = self._read_regular(record_dir / "content.bin")
        metadata_bytes = self._read_regular(record_dir / "metadata.json")
        checksum_bytes = self._read_regular(record_dir / "metadata.sha256")
        try:
            declared_metadata_checksum = checksum_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise RepositoryIntegrityError("checksum de metadados inválido") from exc
        if (
            len(declared_metadata_checksum) != 64
            or any(character not in "0123456789abcdef" for character in declared_metadata_checksum)
            or hashlib.sha256(metadata_bytes).hexdigest() != declared_metadata_checksum
        ):
            raise RepositoryIntegrityError("metadados privados divergem do checksum")
        try:
            decoded = metadata_bytes.decode("utf-8")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError("metadados privados inválidos") from exc
        if _canonical_manifest(payload) != metadata_bytes:
            raise RepositoryIntegrityError("metadados privados não são canônicos")
        metadata = _metadata_from_manifest(payload)
        if metadata.workspace_id != workspace_id:
            raise RepositoryIntegrityError("workspace do conteúdo privado diverge")
        if metadata.content_id != content_id:
            raise RepositoryIntegrityError("identidade do conteúdo privado diverge")
        try:
            return PrivateContent(metadata, content)
        except (TypeError, ValueError) as exc:
            raise RepositoryIntegrityError("conteúdo privado corrompido") from exc

    @staticmethod
    def _cleanup_owned_temp(temp_dir: Path) -> None:
        for name in _RECORD_FILES:
            candidate = temp_dir / name
            try:
                if os.path.lexists(candidate) and not candidate.is_dir():
                    candidate.unlink()
            except OSError:
                pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass

    def store(
        self, metadata: PrivateContentMetadata, content: bytes
    ) -> PrivateContentMetadata:
        self._ensure_open()
        try:
            record = PrivateContent(metadata, content)
        except (TypeError, ValueError):
            raise
        self._ensure_contents_dir(metadata.workspace_id)
        final_dir = self._record_dir(metadata.workspace_id, metadata.content_id)
        self._assert_safe_path(final_dir)
        lease = self._lease_path(metadata.workspace_id, metadata.content_id)
        self._assert_safe_path(lease)
        try:
            _write_fsynced(lease, b"PRIVATE_CASE_STORAGE_V1")
        except FileExistsError as exc:
            raise RepositoryConflict(
                "identidade de conteúdo privado já está em escrita"
            ) from exc
        except OSError as exc:
            raise RepositoryError("falha ao reservar conteúdo privado") from exc

        temp_dir = None
        try:
            if os.path.lexists(final_dir):
                if _path_is_link_or_reparse(final_dir):
                    raise RepositoryIntegrityError(
                        "identidade privada ocupada por link ou reparse"
                    )
                raise RepositoryConflict("identidade de conteúdo privado já existe")
            temp_dir = Path(
                tempfile.mkdtemp(
                    prefix=f"{metadata.workspace_id}.{metadata.content_id}.",
                    dir=self._staging,
                )
            )
            self._assert_safe_path(temp_dir)
            manifest = _canonical_manifest(_manifest_for(metadata))
            _write_fsynced(temp_dir / "content.bin", record.content)
            _write_fsynced(temp_dir / "metadata.json", manifest)
            _write_fsynced(
                temp_dir / "metadata.sha256",
                hashlib.sha256(manifest).hexdigest().encode("ascii"),
            )
            verified = self._read_record(
                temp_dir, metadata.workspace_id, metadata.content_id
            )
            if verified != record:
                raise RepositoryIntegrityError(
                    "verificação temporária do conteúdo privado diverge"
                )
            os.replace(temp_dir, final_dir)
            return metadata
        except (RepositoryConflict, RepositoryIntegrityError):
            raise
        except OSError as exc:
            raise RepositoryError("falha ao armazenar conteúdo privado") from exc
        finally:
            if temp_dir is not None:
                self._cleanup_owned_temp(temp_dir)
            try:
                lease.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # A lease órfã bloqueia fail-closed uma reutilização futura da
                # identidade; nunca mascara a falha original nem libera no escuro.
                pass

    def get(
        self, workspace_id: WorkspaceId, content_id: PrivateContentId
    ) -> PrivateContent | None:
        self._ensure_open()
        record_dir = self._record_dir(workspace_id, content_id)
        self._assert_safe_path(record_dir)
        if not os.path.lexists(record_dir):
            return None
        return self._read_record(record_dir, workspace_id, content_id)

    def list_all(
        self, workspace_id: WorkspaceId
    ) -> tuple[PrivateContentMetadata, ...]:
        self._ensure_open()
        contents = self._contents_dir(workspace_id)
        self._assert_safe_path(contents)
        if not os.path.lexists(contents):
            return ()
        try:
            if _path_is_link_or_reparse(contents) or not contents.is_dir():
                raise RepositoryIntegrityError("diretório privado inválido")
            entries = sorted(contents.iterdir(), key=lambda item: item.name)
        except RepositoryIntegrityError:
            raise
        except OSError as exc:
            raise RepositoryError("falha ao listar conteúdo privado") from exc
        records = []
        for entry in entries:
            try:
                content_id = PrivateContentId.parse(entry.name)
            except (TypeError, ValueError) as exc:
                raise RepositoryIntegrityError(
                    "identidade física de conteúdo privado inválida"
                ) from exc
            records.append(
                self._read_record(entry, workspace_id, content_id).metadata
            )
        return tuple(records)

    def close(self) -> None:
        self._closed = True

    def __enter__(self) -> LocalPrivateContentStore:
        self._ensure_open()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()
