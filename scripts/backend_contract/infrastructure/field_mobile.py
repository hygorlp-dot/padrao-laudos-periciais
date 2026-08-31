from __future__ import annotations

import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..field_mobile import (
    OfflineInspectionPackage,
    canonical_offline_package_bytes,
    offline_package_from_mapping,
)
import json


class DeviceOfflineVault:
    """Device-local, authenticated storage; no network or cloud transport."""

    def __init__(self, root: Path, *, key: bytes, device_id: str):
        if type(key) is not bytes or len(key) != 32:
            raise ValueError("device vault requires a 256-bit key")
        if type(device_id) is not str or not device_id.strip():
            raise ValueError("device identity is required")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._key: bytes | None = key
        self._device_id = device_id
        self._revocation = self._root / ".revoked"

    def _require_active(self) -> bytes:
        if self._key is None or self._revocation.exists():
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
        target = self._path(package.package_id)
        if target.exists():
            raise FileExistsError("offline package cannot be silently overwritten")
        nonce = os.urandom(12)
        aad = self._device_id.encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, canonical_offline_package_bytes(package), aad)
        target.write_bytes(b"OFFLINE-V1\0" + nonce + ciphertext)

    def load(self, package_id: str) -> OfflineInspectionPackage:
        key = self._require_active()
        payload = self._path(package_id).read_bytes()
        if not payload.startswith(b"OFFLINE-V1\0") or len(payload) < 40:
            raise ValueError("offline package storage is corrupt")
        nonce, ciphertext = payload[11:23], payload[23:]
        try:
            clear = AESGCM(key).decrypt(nonce, ciphertext, self._device_id.encode("utf-8"))
        except InvalidTag as exc:
            raise ValueError("offline package integrity verification failed") from exc
        package = offline_package_from_mapping(json.loads(clear.decode("utf-8")))
        if package.package_id != package_id or package.device_id != self._device_id:
            raise ValueError("offline package storage identity mismatch")
        return package

    def save_media(self, package_id: str, record_id: str, original: bytes) -> None:
        key = self._require_active()
        if type(original) is not bytes:
            raise TypeError("original media bytes required")
        authority = self._media_authority(package_id, record_id)
        if len(original) != authority.byte_size or hashlib.sha256(original).hexdigest() != authority.original_sha256:
            raise ValueError("original media hash/size diverges from authority")
        target = self._media_path(package_id, record_id)
        if target.exists():
            raise FileExistsError("original media cannot be silently overwritten")
        nonce = os.urandom(12)
        aad = f"{self._device_id}\0{package_id}\0{record_id}".encode("utf-8")
        target.write_bytes(b"MEDIA-V1\0" + nonce + AESGCM(key).encrypt(nonce, original, aad))

    def load_media(self, package_id: str, record_id: str) -> bytes:
        key = self._require_active()
        authority = self._media_authority(package_id, record_id)
        payload = self._media_path(package_id, record_id).read_bytes()
        if not payload.startswith(b"MEDIA-V1\0") or len(payload) < 38:
            raise ValueError("original media storage is corrupt")
        nonce, ciphertext = payload[9:21], payload[21:]
        aad = f"{self._device_id}\0{package_id}\0{record_id}".encode("utf-8")
        try:
            original = AESGCM(key).decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise ValueError("original media integrity verification failed") from exc
        if len(original) != authority.byte_size or hashlib.sha256(original).hexdigest() != authority.original_sha256:
            raise ValueError("original media hash/size diverges from authority")
        return original

    def revoke(self) -> None:
        self._revocation.write_bytes(b"REVOKED\n")
        self._key = None
