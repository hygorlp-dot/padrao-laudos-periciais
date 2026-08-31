from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from threading import Event, RLock
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..field_mobile import (
    OfflineInspectionPackage,
    canonical_offline_package_bytes,
    offline_package_from_mapping,
)
import json


_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# Windows' CRT binary flag is stable (``O_BINARY == 0x8000``).  Keeping the
# literal local avoids acquiring the broader mixed ``os`` capability surface.
_OPEN_BINARY = 0x8000 if os.name == "nt" else 0


def _is_link_or_reparse(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(getattr(details, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


class DeviceOfflineVault:
    """Device-local, authenticated storage; no network or cloud transport."""

    def __init__(self, root: Path, *, key: bytes, device_id: str, workspace_id: str, global_revocation_path: Path | None = None, lifecycle_lock: RLock | None = None, revocation_event: Event | None = None):
        if type(key) is not bytes or len(key) != 32:
            raise ValueError("device vault requires a 256-bit key")
        if any(type(value) is not str or not value.strip() for value in (device_id, workspace_id)):
            raise ValueError("device and workspace identity are required")
        raw_root = str(root)
        if raw_root.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
            raise ValueError("device vault requires trusted local storage")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        details = os.lstat(self._root)
        if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode):
            raise ValueError("device vault root must be a plain local directory")
        self._root_identity = (details.st_dev, details.st_ino)
        try:
            os.chmod(self._root, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        except OSError as exc:
            raise ValueError("device vault permissions cannot be restricted") from exc
        self._key: bytes | None = key
        self._device_id = device_id
        self._workspace_id = workspace_id
        self._lock = RLock() if lifecycle_lock is None else lifecycle_lock
        self._revocation = self._root / ".revoked"
        self._global_revocation = global_revocation_path
        self._revocation_event = revocation_event

    def _require_active(self) -> bytes:
        try:
            details = os.lstat(self._root)
        except OSError as exc:
            raise PermissionError("device vault root identity is unavailable") from exc
        if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode) or (details.st_dev, details.st_ino) != self._root_identity:
            raise PermissionError("device vault root identity changed")
        if self._key is None or self._revocation.exists() or (self._revocation_event is not None and self._revocation_event.is_set()) or (self._global_revocation is not None and self._global_revocation.exists()):
            raise PermissionError("device session is revoked")
        return self._key

    def _path(self, package_id: str) -> Path:
        name = hashlib.sha256(package_id.encode("utf-8")).hexdigest()
        return self._root / f"{name}.offline"

    def _media_path(self, package_id: str, record_id: str) -> Path:
        identity = f"{package_id}\0{record_id}".encode("utf-8")
        return self._root / f"{hashlib.sha256(identity).hexdigest()}.media"

    def _media_authority(self, package_id: str, record_id: str):
        package = self.load(package_id)
        matches = [item for item in package.media_manifest if item.record_id == record_id]
        if len(matches) != 1:
            raise ValueError("media authority is absent or ambiguous")
        return matches[0]

    def save(self, package: OfflineInspectionPackage) -> None:
        key = self._require_active()
        if package.device_id != self._device_id:
            raise PermissionError("offline package device mismatch")
        if package.workspace_id != self._workspace_id:
            raise PermissionError("offline package workspace mismatch")
        target = self._path(package.package_id)
        nonce = os.urandom(12)
        aad = f"{self._workspace_id}\0{self._device_id}".encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, canonical_offline_package_bytes(package), aad)
        self._exclusive_write(target, b"OFFLINE-V1\0" + nonce + ciphertext)

    def load(self, package_id: str) -> OfflineInspectionPackage:
        with self._lock:
            key = self._require_active()
            payload = self._read_payload(self._path(package_id))
            package = self._decode_package(payload, key)
            if package.package_id != package_id:
                raise ValueError("offline package storage identity mismatch")
            return package

    def _decode_package(self, payload: bytes, key: bytes) -> OfflineInspectionPackage:
        if not payload.startswith(b"OFFLINE-V1\0") or len(payload) < 40:
            raise ValueError("offline package storage is corrupt")
        nonce, ciphertext = payload[11:23], payload[23:]
        try:
            clear = AESGCM(key).decrypt(nonce, ciphertext, f"{self._workspace_id}\0{self._device_id}".encode("utf-8"))
        except InvalidTag as exc:
            raise ValueError("offline package integrity verification failed") from exc
        package = offline_package_from_mapping(json.loads(clear.decode("utf-8")))
        if package.device_id != self._device_id or package.workspace_id != self._workspace_id:
            raise ValueError("offline package storage identity mismatch")
        return package

    def list_pending_packages(self) -> tuple[OfflineInspectionPackage, ...]:
        with self._lock:
            key = self._require_active()
            packages = [self._decode_package(self._read_payload(path), key) for path in self._root.glob("*.offline")]
            pending = [item for item in packages if item.device_sequence > self.last_accepted_sequence(item.device_session_id)]
            return tuple(sorted(pending, key=lambda item: (item.created_at, item.package_revision, item.package_id), reverse=True))

    def save_media(self, package_id: str, record_id: str, original: bytes) -> None:
        key = self._require_active()
        if type(original) is not bytes:
            raise TypeError("original media bytes required")
        authority = self._media_authority(package_id, record_id)
        if len(original) != authority.byte_size or hashlib.sha256(original).hexdigest() != authority.original_sha256:
            raise ValueError("original media hash/size diverges from authority")
        target = self._media_path(package_id, record_id)
        nonce = os.urandom(12)
        aad = f"{self._workspace_id}\0{self._device_id}\0{package_id}\0{record_id}".encode("utf-8")
        self._exclusive_write(target, b"MEDIA-V1\0" + nonce + AESGCM(key).encrypt(nonce, original, aad))

    def load_media(self, package_id: str, record_id: str) -> bytes:
        with self._lock:
            key = self._require_active()
            authority = self._media_authority(package_id, record_id)
            payload = self._read_payload(self._media_path(package_id, record_id))
            if not payload.startswith(b"MEDIA-V1\0") or len(payload) < 38:
                raise ValueError("original media storage is corrupt")
            nonce, ciphertext = payload[9:21], payload[21:]
            aad = f"{self._workspace_id}\0{self._device_id}\0{package_id}\0{record_id}".encode("utf-8")
            try:
                original = AESGCM(key).decrypt(nonce, ciphertext, aad)
            except InvalidTag as exc:
                raise ValueError("original media integrity verification failed") from exc
            if len(original) != authority.byte_size or hashlib.sha256(original).hexdigest() != authority.original_sha256:
                raise ValueError("original media hash/size diverges from authority")
            return original

    def revoke(self) -> None:
        with self._lock:
            if not self._revocation.exists():
                self._exclusive_write(self._revocation, b"REVOKED\n")
            self._key = None

    def verify_media_authority(self, package_id: str) -> bool:
        package = self.load(package_id)
        for item in package.media_manifest:
            self.load_media(package_id, item.record_id)
        return True

    def last_accepted_sequence(self, device_session_id: str) -> int:
        with self._lock:
            key = self._require_active()
            session_hash = hashlib.sha256(device_session_id.encode("utf-8")).hexdigest()
            sequences = []
            for path in self._root.glob(f"{session_hash}.*.receipt"):
                try:
                    sequence = int(path.name.split(".")[1])
                    payload = self._read_payload(path)
                    if not payload.startswith(b"RECEIPT-V1\0") or len(payload) < 40:
                        raise ValueError
                    nonce, ciphertext = payload[11:23], payload[23:]
                    aad = f"{self._workspace_id}\0{self._device_id}\0{device_session_id}\0{sequence}".encode("utf-8")
                    clear = AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
                    stored_session, stored_sequence, _package_id, _revision = clear.split("\n")
                    if stored_session != device_session_id or int(stored_sequence) != sequence:
                        raise ValueError
                    sequences.append(sequence)
                except (InvalidTag, UnicodeError, ValueError, IndexError) as exc:
                    raise ValueError("offline sync receipt storage is corrupt") from exc
            return max(sequences, default=0)

    def record_accepted_sync(self, package: OfflineInspectionPackage) -> None:
        key = self._require_active()
        session_hash = hashlib.sha256(package.device_session_id.encode("utf-8")).hexdigest()
        target = self._root / f"{session_hash}.{package.device_sequence}.receipt"
        clear = f"{package.device_session_id}\n{package.device_sequence}\n{package.package_id}\n{package.package_revision}".encode("utf-8")
        nonce = os.urandom(12)
        aad = f"{self._workspace_id}\0{self._device_id}\0{package.device_session_id}\0{package.device_sequence}".encode("utf-8")
        self._exclusive_write(target, b"RECEIPT-V1\0" + nonce + AESGCM(key).encrypt(nonce, clear, aad))

    def _exclusive_write(self, target: Path, payload: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_BINARY
        with self._lock:
            self._require_active()
            try:
                descriptor = os.open(target, flags, stat.S_IRUSR | stat.S_IWUSR)
            except FileExistsError as exc:
                raise FileExistsError("offline data cannot be silently overwritten") from exc
            try:
                if target != self._revocation:
                    self._require_active()
                else:
                    details = os.lstat(self._root)
                    if _is_link_or_reparse(details) or (details.st_dev, details.st_ino) != self._root_identity:
                        raise PermissionError("device vault root identity changed")
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                details = os.fstat(descriptor)
                if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1 or details.st_size != len(payload):
                    raise ValueError("offline durable write verification failed")
            finally:
                os.close(descriptor)

    def _read_payload(self, target: Path) -> bytes:
        with self._lock:
            self._require_active()
            descriptor = os.open(target, os.O_RDONLY | _OPEN_BINARY)
            try:
                self._require_active()
                with os.fdopen(descriptor, "rb", closefd=False) as stream:
                    return stream.read()
            finally:
                os.close(descriptor)


class DeviceOfflineVaultRegistry:
    """Provisions one device identity/key and workspace-isolated vaults."""

    def __init__(self, root: Path):
        self._lifecycle_lock = RLock()
        self._revoked = Event()
        self._root = Path(root) / "offline-field-v1"
        self._root.mkdir(parents=True, exist_ok=True)
        root_details = os.lstat(self._root)
        if _is_link_or_reparse(root_details) or not stat.S_ISDIR(root_details.st_mode):
            raise ValueError("offline registry root cannot be a link")
        self._root_identity = (root_details.st_dev, root_details.st_ino)
        os.chmod(self._root, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        self._key_path = self._root / ".device-key"
        self._identity_path = self._root / ".device-id"
        self._revocation_path = self._root / ".device-revoked"
        key_exists = self._key_path.exists()
        identity_exists = self._identity_path.exists()
        if key_exists != identity_exists:
            raise PermissionError("offline device authority is incomplete or revoked")
        if not key_exists:
            self._provision(self._key_path, os.urandom(32))
            self._provision(self._identity_path, f"DEVICE-{uuid4().hex.upper()}".encode("ascii"))
        self._key = self._key_path.read_bytes()
        self.device_id = self._identity_path.read_text(encoding="ascii")
        self._authority_identities = {
            self._key_path: self._file_identity(self._key_path),
            self._identity_path: self._file_identity(self._identity_path),
        }
        if len(self._key) != 32 or not self.device_id.startswith("DEVICE-"):
            raise ValueError("offline device authority is corrupt")

    @staticmethod
    def _provision(path: Path, payload: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_BINARY, stat.S_IRUSR | stat.S_IWUSR)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _file_identity(path: Path) -> tuple[int, int]:
        details = os.lstat(path)
        if _is_link_or_reparse(details) or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise PermissionError("offline device authority identity is invalid")
        return details.st_dev, details.st_ino

    def _require_registry_active(self) -> None:
        details = os.lstat(self._root)
        if _is_link_or_reparse(details) or not stat.S_ISDIR(details.st_mode) or (details.st_dev, details.st_ino) != self._root_identity:
            raise PermissionError("offline registry root identity changed")
        if self._revoked.is_set():
            raise PermissionError("offline device is revoked")
        if any(self._file_identity(path) != identity for path, identity in self._authority_identities.items()):
            raise PermissionError("offline device authority identity changed")
        if self._revocation_path.exists():
            raise PermissionError("offline device is revoked")

    def vault_for(self, workspace_id, device_id: str) -> DeviceOfflineVault:
        with self._lifecycle_lock:
            self._require_registry_active()
            if device_id != self.device_id:
                raise PermissionError("offline device is not authorized")
            workspace = str(workspace_id)
            directory = self._root / hashlib.sha256(workspace.encode("utf-8")).hexdigest()
            if directory.exists() and _is_link_or_reparse(os.lstat(directory)):
                raise ValueError("offline workspace root cannot be a link or reparse point")
            return DeviceOfflineVault(directory, key=self._key, device_id=self.device_id, workspace_id=workspace, global_revocation_path=self._revocation_path, lifecycle_lock=self._lifecycle_lock, revocation_event=self._revoked)

    def revoke_device(self) -> None:
        with self._lifecycle_lock:
            self._require_registry_active()
            if not self._revocation_path.exists():
                self._provision(self._revocation_path, b"REVOKED\n")
            self._key_path.unlink()
            self._revoked.set()
