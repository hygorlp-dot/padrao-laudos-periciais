"""Composition root do runtime local navegável."""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from ..local_api.composition import LocalApiRuntime, build_local_api
from ..local_api.server import LocalServerConfig
from .server import ProductBridgeConfig, ProductBridgeServer


class ProductRuntime:
    def __init__(self, local_api: LocalApiRuntime, bridge: ProductBridgeServer):
        self._local_api = local_api
        self._bridge = bridge
        self._started = False
        self._closed = False
        self._lock = Lock()

    def __repr__(self) -> str:
        return f"ProductRuntime(origin={self.origin!r}, started={self._started})"

    @property
    def address(self) -> tuple[str, int]:
        return self._bridge.address

    @property
    def origin(self) -> str:
        return self._bridge.origin

    def start(self) -> tuple[str, int]:
        with self._lock:
            if self._closed:
                raise RuntimeError("runtime do produto fechado")
            if self._started:
                raise RuntimeError("runtime do produto já iniciado")
            try:
                self._local_api.start()
                address = self._bridge.start()
            except Exception:
                self._closed = True
                try:
                    self._bridge.close()
                finally:
                    self._local_api.close()
                raise
            self._started = True
            return address

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._bridge.close()
            finally:
                self._local_api.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()


def build_product_runtime(
    database: str | Path,
    frontend_root: str | Path,
    *,
    config: ProductBridgeConfig | None = None,
    token: str | None = None,
    private_root: str | Path | None = None,
) -> ProductRuntime:
    root = Path(frontend_root)
    if not root.is_dir() or not (root / "index.html").is_file():
        raise ValueError("build frontend inválido")
    bridge_config = ProductBridgeConfig() if config is None else config
    if type(bridge_config) is not ProductBridgeConfig:
        raise TypeError("configuração do bridge inválida")
    local_api = build_local_api(
        database,
        token=token,
        private_root=private_root,
        config=LocalServerConfig(
            max_body_bytes=bridge_config.max_body_bytes,
            request_timeout_seconds=bridge_config.request_timeout_seconds,
        ),
    )
    try:
        bridge = ProductBridgeServer(
            frontend_root=root,
            upstream_address=local_api.address,
            token=local_api.token,
            config=bridge_config,
        )
    except Exception:
        local_api.close()
        raise
    return ProductRuntime(local_api, bridge)
