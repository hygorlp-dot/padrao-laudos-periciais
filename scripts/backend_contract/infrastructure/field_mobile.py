from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
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
    offline_package_sha256,
)
import json


_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
# Windows' CRT binary flag is stable (``O_BINARY == 0x8000``).  Keeping the
# literal local avoids acquiring the broader mixed ``os`` capability surface.
_OPEN_BINARY = 0x8000 if os.name == "nt" else 0


@dataclass(frozen=True, slots=True)
class OfflineInventoryConflict:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class PendingOfflineInventory:
    items: tuple[OfflineInspectionPackage, ...]
    conflicts: tuple[OfflineInventoryConflict, ...]


@dataclass(frozen=True, slots=True)
class DeviceSecurityClassification:
    threat_model: str = "A"
    protects_plaintext_at_rest: bool = True
    protects_complete_tree_copy: bool = False
    protects_malicious_complete_tree_read_write: bool = False


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

    def _supersession_path(self, package_id: str) -> Path:
        name = hashlib.sha256(package_id.encode("utf-8")).hexdigest()
        return self._root / f"{name}.superseded"

    def _sync_intent_path(self, package_id: str) -> Path:
        name = hashlib.sha256(package_id.encode("utf-8")).hexdigest()
        return self._root / f"{name}.syncing"

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
        inventory = self.inventory_pending_packages()
        if inventory.conflicts:
            raise ValueError(inventory.conflicts[0].message)
        return inventory.items

    def inventory_pending_packages(self) -> PendingOfflineInventory:
        with self._lock:
            key = self._require_active()
            packages: list[OfflineInspectionPackage] = []
            conflicts: list[OfflineInventoryConflict] = []
            for path in self._root.glob("*.offline"):
                try:
                    packages.append(self._decode_package(self._read_payload(path), key))
                except (OSError, UnicodeError, ValueError):
                    conflicts.append(OfflineInventoryConflict(
                        "CORRUPT_OFFLINE_PACKAGE",
                        "Pacote offline corrompido requer recuperação explícita.",
                    ))
            pending: list[OfflineInspectionPackage] = []
            for item in packages:
                try:
                    accepted = self.last_accepted_sequence(item.device_session_id)
                    superseded = self.superseding_package_id(item.package_id)
                except (OSError, UnicodeError, ValueError):
                    conflicts.append(OfflineInventoryConflict(
                        "CORRUPT_OFFLINE_AUTHORITY",
                        "Autoridade local de sync corrompida requer recuperação explícita.",
                    ))
                    pending.append(item)
                    continue
                if item.device_sequence > accepted and superseded is None:
                    pending.append(item)
                    try:
                        for media in item.media_manifest:
                            self.load_media(item.package_id, media.record_id)
                    except (OSError, UnicodeError, ValueError):
                        conflicts.append(OfflineInventoryConflict(
                            "CORRUPT_OFFLINE_MEDIA",
                            "Mídia offline corrompida requer recuperação explícita.",
                        ))
            ordered = tuple(sorted(
                pending,
                key=lambda item: (item.created_at, item.package_revision, item.package_id),
                reverse=True,
            ))
            return PendingOfflineInventory(ordered, tuple(conflicts))

    def mark_superseded(self, package_id: str, replacement_package_id: str) -> None:
        key = self._require_active()
        previous = self.load(package_id)
        replacement = self.load(replacement_package_id)
        if (
            previous.device_session_id != replacement.device_session_id
            or replacement.package_revision != previous.package_revision + 1
            or replacement.device_sequence != previous.device_sequence + 1
        ):
            raise ValueError("offline package supersession authority is invalid")
        nonce = os.urandom(12)
        aad = f"{self._workspace_id}\0{self._device_id}\0{package_id}".encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, replacement_package_id.encode("utf-8"), aad)
        self._exclusive_write(self._supersession_path(package_id), b"SUPERSEDED-V1\0" + nonce + ciphertext)

    def superseding_package_id(self, package_id: str) -> str | None:
        key = self._require_active()
        path = self._supersession_path(package_id)
        if not path.exists():
            return None
        payload = self._read_payload(path)
        if not payload.startswith(b"SUPERSEDED-V1\0") or len(payload) < 43:
            raise ValueError("offline supersession storage is corrupt")
        nonce, ciphertext = payload[14:26], payload[26:]
        aad = f"{self._workspace_id}\0{self._device_id}\0{package_id}".encode("utf-8")
        try:
            return AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
        except (InvalidTag, UnicodeError) as exc:
            raise ValueError("offline supersession storage is corrupt") from exc

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

    def has_accepted_sync(self, package: OfflineInspectionPackage) -> bool:
        key = self._require_active()
        session_hash = hashlib.sha256(package.device_session_id.encode("utf-8")).hexdigest()
        path = self._root / f"{session_hash}.{package.device_sequence}.receipt"
        if not path.exists():
            return False
        payload = self._read_payload(path)
        if not payload.startswith(b"RECEIPT-V1\0") or len(payload) < 40:
            raise ValueError("offline sync receipt storage is corrupt")
        nonce, ciphertext = payload[11:23], payload[23:]
        aad = f"{self._workspace_id}\0{self._device_id}\0{package.device_session_id}\0{package.device_sequence}".encode("utf-8")
        try:
            clear = AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
            return clear == f"{package.device_session_id}\n{package.device_sequence}\n{package.package_id}\n{package.package_revision}"
        except (InvalidTag, UnicodeError) as exc:
            raise ValueError("offline sync receipt storage is corrupt") from exc

    def begin_sync(self, package: OfflineInspectionPackage, expected_revision: int) -> None:
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("offline sync expected revision is invalid")
        existing = self.sync_intent_expected_revision(package)
        if existing is not None:
            if existing != expected_revision:
                raise ValueError("offline sync intent diverges from canonical revision")
            return
        key = self._require_active()
        nonce = os.urandom(12)
        digest = offline_package_sha256(package)
        clear = f"{package.package_id}\n{digest}\n{expected_revision}".encode("utf-8")
        aad = f"{self._workspace_id}\0{self._device_id}\0{package.package_id}".encode("utf-8")
        payload = b"SYNCING-V1\0" + nonce + AESGCM(key).encrypt(nonce, clear, aad)
        self._exclusive_write(self._sync_intent_path(package.package_id), payload)

    def sync_intent_expected_revision(self, package: OfflineInspectionPackage) -> int | None:
        path = self._sync_intent_path(package.package_id)
        if not path.exists():
            return None
        key = self._require_active()
        payload = self._read_payload(path)
        if not payload.startswith(b"SYNCING-V1\0") or len(payload) < 40:
            raise ValueError("offline sync intent storage is corrupt")
        nonce, ciphertext = payload[11:23], payload[23:]
        aad = f"{self._workspace_id}\0{self._device_id}\0{package.package_id}".encode("utf-8")
        try:
            clear = AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")
            stored_package, stored_digest, revision = clear.split("\n")
            if stored_package != package.package_id or stored_digest != offline_package_sha256(package):
                raise ValueError
            expected = int(revision)
            if expected < 1:
                raise ValueError
            return expected
        except (InvalidTag, UnicodeError, ValueError) as exc:
            raise ValueError("offline sync intent storage is corrupt") from exc

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
        self._generation_path = self._root / ".device-generation"
        self._lifecycle_key_path = self._root / ".lifecycle-key"
        self._lifecycle_state_path = self._root / ".lifecycle-state"
        self._lifecycle_migration_path = self._root / ".lifecycle-migration-v1"
        self._lifecycle_migration_complete_path = self._root / ".lifecycle-migration-v1.complete"
        identity_is_legacy = self._identity_path.exists() and not self._identity_path.read_bytes().startswith(b"V2\n")
        pristine = not any(self._root.iterdir())
        legacy_candidate = (
            self._key_path.exists() and self._identity_path.exists() and identity_is_legacy
            and not any(path.exists() for path in (
                self._revocation_path, self._generation_path,
                self._lifecycle_key_path, self._lifecycle_state_path,
            ))
            and not any(self._root.glob(".replacement-*.json"))
            and not self._lifecycle_migration_path.exists()
        )
        if legacy_candidate and not self._lifecycle_migration_path.exists():
            legacy = {
                "device_id": self._read_identity(self._identity_path),
                "device_key_sha256": hashlib.sha256(self._key_path.read_bytes()).hexdigest(),
                "generation": 1,
                "lifecycle_key_hex": os.urandom(32).hex(),
            }
            self._publish_intent(
                self._lifecycle_migration_path,
                json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )
        migration_consumed = (
            self._lifecycle_migration_path.exists()
            and self._lifecycle_migration_path.read_bytes().startswith(b"CONSUMED-V1\n")
        )
        migration_recorded = self._lifecycle_migration_path.exists() and not migration_consumed
        migration_completed = self._lifecycle_migration_complete_path.exists()
        migration_pending = migration_recorded and not migration_completed and identity_is_legacy
        if migration_pending:
            try:
                legacy = json.loads(self._lifecycle_migration_path.read_text(encoding="utf-8"))
                if (
                    set(legacy) != {"device_id", "device_key_sha256", "generation", "lifecycle_key_hex"}
                    or legacy["generation"] != 1
                    or legacy["device_id"] != self._read_identity(self._identity_path)
                    or legacy["device_key_sha256"] != hashlib.sha256(self._key_path.read_bytes()).hexdigest()
                    or len(bytes.fromhex(legacy["lifecycle_key_hex"])) != 32
                    or (self._lifecycle_key_path.exists() and self._lifecycle_key_path.read_bytes().hex() != legacy["lifecycle_key_hex"])
                    or (self._generation_path.exists() and self._generation_path.read_text(encoding="ascii").strip() != "1")
                ):
                    raise ValueError
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise PermissionError("offline lifecycle migration authority is corrupt") from exc
        migrating = migration_pending and not self._lifecycle_state_path.exists()
        if not self._lifecycle_key_path.exists():
            if not pristine and not migrating:
                raise PermissionError("offline lifecycle authority is incomplete")
            self._provision(
                self._lifecycle_key_path,
                bytes.fromhex(legacy["lifecycle_key_hex"]) if migrating else os.urandom(32),
            )
        self._lifecycle_key = self._lifecycle_key_path.read_bytes()
        if len(self._lifecycle_key) != 32:
            raise PermissionError("offline lifecycle authority is corrupt")
        if not self._generation_path.exists():
            if not pristine and not migrating:
                raise PermissionError("offline lifecycle generation is missing")
            self._provision(self._generation_path, b"1\n")
        self._recover_pending_replacement()
        key_exists = self._key_path.exists()
        identity_exists = self._identity_path.exists()
        revoked = self._revocation_path.exists()
        if not key_exists and not identity_exists and not revoked:
            self._provision(self._key_path, os.urandom(32))
            self._provision(self._identity_path, f"V2\nDEVICE-{uuid4().hex.upper()}".encode("ascii"))
            key_exists = identity_exists = True
        elif not key_exists and identity_exists and revoked:
            self._revoked.set()
        elif key_exists != identity_exists or revoked:
            raise PermissionError("offline device authority is incomplete or revoked")
        if not self._generation_path.exists():
            self._provision(self._generation_path, b"1\n")
        try:
            self._generation = int(self._generation_path.read_text(encoding="ascii").strip())
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError("offline device generation is corrupt") from exc
        if self._generation < 1:
            raise ValueError("offline device generation is corrupt")
        self._key: bytes | None = self._key_path.read_bytes() if key_exists else None
        self.device_id = self._read_identity(self._identity_path)
        self._authority_identities = {
            self._identity_path: self._file_identity(self._identity_path),
            self._generation_path: self._file_identity(self._generation_path),
            self._lifecycle_key_path: self._file_identity(self._lifecycle_key_path),
        }
        if self._key is not None:
            self._authority_identities[self._key_path] = self._file_identity(self._key_path)
        if (self._key is not None and len(self._key) != 32) or not self.device_id.startswith("DEVICE-"):
            raise ValueError("offline device authority is corrupt")
        if not self._lifecycle_state_path.exists():
            if not pristine and not migrating:
                raise PermissionError("offline committed lifecycle state is missing")
            self._provision(self._lifecycle_state_path, self._lifecycle_state_payload(
                self.device_id, self._generation, self._key,
            ))
        if migration_pending:
            temporary_identity = self._root / f".device-id.{uuid4().hex}.new"
            self._provision(temporary_identity, f"V2\n{self.device_id}".encode("ascii"))
            os.replace(temporary_identity, self._identity_path)
            self._authority_identities[self._identity_path] = self._file_identity(self._identity_path)
            consumed = self._root / f".lifecycle-migration.{uuid4().hex}.consumed"
            self._provision(
                consumed,
                b"CONSUMED-V1\n" + hashlib.sha256(self._lifecycle_migration_path.read_bytes()).hexdigest().encode("ascii") + b"\n",
            )
            os.replace(consumed, self._lifecycle_migration_path)
            self._provision(
                self._lifecycle_migration_complete_path,
                hashlib.sha256(self._lifecycle_migration_path.read_bytes()).hexdigest().encode("ascii") + b"\n",
            )
        elif migration_completed:
            try:
                expected_state = self._lifecycle_migration_complete_path.read_text(encoding="ascii").strip()
                if expected_state != hashlib.sha256(self._lifecycle_migration_path.read_bytes()).hexdigest():
                    raise ValueError
            except (OSError, UnicodeError, ValueError) as exc:
                raise PermissionError("offline lifecycle migration completion is corrupt") from exc
        self._validate_lifecycle_state()

    @property
    def security_classification(self) -> DeviceSecurityClassification:
        """Describe proven local protection without overclaiming tree-theft resistance."""
        return DeviceSecurityClassification()

    @property
    def lifecycle_status(self) -> dict[str, object]:
        return {
            "device_id": self.device_id,
            "generation": self._generation,
            "revoked": self._revoked.is_set() or self._revocation_path.exists(),
        }

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

    @staticmethod
    def _read_identity(path: Path) -> str:
        try:
            lines = path.read_text(encoding="ascii").splitlines()
            if len(lines) == 1 and lines[0].startswith("DEVICE-"):
                return lines[0]
            if len(lines) == 2 and lines[0] == "V2" and lines[1].startswith("DEVICE-"):
                return lines[1]
        except (OSError, UnicodeError):
            pass
        raise ValueError("offline device identity is corrupt")

    def _replacement_path(self, device_id: str) -> Path:
        return self._root / f".replacement-{hashlib.sha256(device_id.encode('utf-8')).hexdigest()}.json"

    def _replacement_intent(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if set(value) != {"old_device_id", "previous_generation", "new_device_id", "new_generation", "new_key_hex", "mac"}:
                raise ValueError
            unsigned = {key: item for key, item in value.items() if key != "mac"}
            expected_mac = hmac.new(
                self._lifecycle_key,
                json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            key = bytes.fromhex(value["new_key_hex"])
            if (
                type(value["old_device_id"]) is not str
                or type(value["previous_generation"]) is not int
                or type(value["new_device_id"]) is not str
                or type(value["new_generation"]) is not int
                or len(key) != 32
                or not value["new_device_id"].startswith("DEVICE-")
                or value["new_generation"] != value["previous_generation"] + 1
                or not hmac.compare_digest(value["mac"], expected_mac)
            ):
                raise ValueError
            return value
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PermissionError("offline device replacement intent is corrupt") from exc

    def _finish_replacement(self, intent: dict, intent_path: Path) -> None:
        new_key = bytes.fromhex(intent["new_key_hex"])
        values = (
            (self._identity_path, f"V2\n{intent['new_device_id']}".encode("ascii")),
            (self._generation_path, f"{intent['new_generation']}\n".encode("ascii")),
            (self._key_path, new_key),
        )
        for target, payload in values:
            if target.exists() and target.read_bytes() == payload:
                continue
            temporary = self._root / f".{target.name}.{uuid4().hex}.new"
            self._provision(temporary, payload)
            os.replace(temporary, target)
        self._replace_lifecycle_state(
            intent["new_device_id"], intent["new_generation"], new_key,
        )
        if self._revocation_path.exists():
            self._revocation_path.unlink()
        complete = intent_path.with_suffix(".complete")
        if not complete.exists():
            self._provision(complete, b"COMPLETE\n")

    def _recover_pending_replacement(self) -> None:
        if not self._identity_path.exists() or not self._revocation_path.exists():
            return
        revoked_device, revoked_generation = self._read_revocation_authority()
        path = self._replacement_path(revoked_device)
        if not path.exists() or path.with_suffix(".complete").exists():
            return
        intent = self._replacement_intent(path)
        if intent["old_device_id"] != revoked_device or intent["previous_generation"] != revoked_generation:
            raise PermissionError("offline device replacement authority diverged")
        current = self._read_identity(self._identity_path)
        if current not in {intent["old_device_id"], intent["new_device_id"]}:
            raise PermissionError("offline device replacement authority diverged")
        self._finish_replacement(intent, path)

    def _revocation_payload(self) -> bytes:
        unsigned = f"{self.device_id}\n{self._generation}".encode("ascii")
        return unsigned + b"\n" + hmac.new(self._lifecycle_key, unsigned, hashlib.sha256).hexdigest().encode("ascii") + b"\n"

    def _read_revocation_authority(self) -> tuple[str, int]:
        try:
            device_id, generation, supplied_mac = self._revocation_path.read_text(encoding="ascii").splitlines()
            unsigned = f"{device_id}\n{generation}".encode("ascii")
            expected = hmac.new(self._lifecycle_key, unsigned, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(supplied_mac, expected):
                raise ValueError
            return device_id, int(generation)
        except (OSError, UnicodeError, ValueError) as exc:
            raise PermissionError("offline device revocation authority is corrupt") from exc

    def _lifecycle_state_payload(self, device_id: str, generation: int, key: bytes | None) -> bytes:
        if key is None:
            raise PermissionError("offline committed lifecycle key is unavailable")
        unsigned = json.dumps({
            "device_id": device_id,
            "identity_version": "V2",
            "generation": generation,
            "device_key_sha256": hashlib.sha256(key).hexdigest(),
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return unsigned + b"\n" + hmac.new(self._lifecycle_key, unsigned, hashlib.sha256).hexdigest().encode("ascii") + b"\n"

    def _replace_lifecycle_state(self, device_id: str, generation: int, key: bytes) -> None:
        temporary = self._root / f".lifecycle-state.{uuid4().hex}.new"
        self._provision(temporary, self._lifecycle_state_payload(device_id, generation, key))
        os.replace(temporary, self._lifecycle_state_path)

    def _validate_lifecycle_state(self) -> None:
        try:
            unsigned, supplied_mac = self._lifecycle_state_path.read_bytes().splitlines()
            expected = hmac.new(self._lifecycle_key, unsigned, hashlib.sha256).hexdigest().encode("ascii")
            value = json.loads(unsigned.decode("utf-8"))
            if not hmac.compare_digest(supplied_mac, expected) or set(value) != {"device_id", "identity_version", "generation", "device_key_sha256"}:
                raise ValueError
            if (
                value["device_id"] != self.device_id
                or value["identity_version"] != "V2"
                or not self._identity_path.read_bytes().startswith(b"V2\n")
                or value["generation"] != self._generation
                or (self._key is not None and value["device_key_sha256"] != hashlib.sha256(self._key).hexdigest())
            ):
                raise ValueError
        except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PermissionError("offline committed lifecycle state is corrupt") from exc

    def _publish_intent(self, target: Path, payload: bytes) -> None:
        temporary = self._root / f".replacement-intent.{uuid4().hex}.new"
        self._provision(temporary, payload)
        try:
            os.link(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()

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
            if self._key is None:
                raise PermissionError("offline device is revoked")
            namespace = self._root if self._generation == 1 else self._root / f"generation-{self._generation}-{hashlib.sha256(self.device_id.encode('utf-8')).hexdigest()}"
            directory = namespace / hashlib.sha256(workspace.encode("utf-8")).hexdigest()
            if directory.exists() and _is_link_or_reparse(os.lstat(directory)):
                raise ValueError("offline workspace root cannot be a link or reparse point")
            return DeviceOfflineVault(directory, key=self._key, device_id=self.device_id, workspace_id=workspace, global_revocation_path=self._revocation_path, lifecycle_lock=self._lifecycle_lock, revocation_event=self._revoked)

    def assert_workspace_backup_ready(self, workspace_id) -> None:
        """Refuse a canonical backup while device-local work is unresolved."""
        vault = self.vault_for(workspace_id, self.device_id)
        inventory = vault.inventory_pending_packages()
        if inventory.items or inventory.conflicts:
            raise ValueError("pending offline field work must be synchronized before backup")

    def revoke_device(self) -> None:
        with self._lifecycle_lock:
            if self._revoked.is_set() and self._revocation_path.exists() and not self._key_path.exists():
                return
            self._require_registry_active()
            if not self._revocation_path.exists():
                self._provision(self._revocation_path, self._revocation_payload())
            self._key_path.unlink()
            self._key = None
            self._revoked.set()

    def replace_revoked_device(self, expected_device_id: str) -> str:
        """Enroll a new generation while preserving the revoked identity tombstone."""
        with self._lifecycle_lock:
            details = os.lstat(self._root)
            if _is_link_or_reparse(details) or (details.st_dev, details.st_ino) != self._root_identity:
                raise PermissionError("offline registry root identity changed")
            if not self._revoked.is_set() or not self._revocation_path.exists() or self._key_path.exists():
                raise PermissionError("offline device must be revoked before replacement")
            if expected_device_id != self.device_id:
                raise PermissionError("offline revoked device identity mismatch")
            if self._file_identity(self._identity_path) != self._authority_identities[self._identity_path]:
                raise PermissionError("offline device authority identity changed")

            new_device_id = f"DEVICE-{uuid4().hex.upper()}"
            new_generation = self._generation + 1
            new_key = os.urandom(32)
            intent = {
                "old_device_id": self.device_id,
                "previous_generation": self._generation,
                "new_device_id": new_device_id,
                "new_generation": new_generation,
                "new_key_hex": new_key.hex(),
            }
            intent["mac"] = hmac.new(
                self._lifecycle_key,
                json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            intent_path = self._replacement_path(self.device_id)
            self._publish_intent(intent_path, json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            self._finish_replacement(intent, intent_path)

            self.device_id = new_device_id
            self._generation = new_generation
            self._key = new_key
            self._revoked.clear()
            self._authority_identities = {
                self._key_path: self._file_identity(self._key_path),
                self._identity_path: self._file_identity(self._identity_path),
                self._generation_path: self._file_identity(self._generation_path),
            }
            return new_device_id
