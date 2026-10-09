"""First run of the local product with no data directory yet (#283).

The Human RC starts the product with ``--database <root>/dados/produto.sqlite3``
and ``--private-root <root>/dados/privado`` on a clean machine where ``dados``
does not exist.  The product must provision that directory itself -- one level,
never a ``mkdir -p`` -- with the same guarantees the database opening demands:
no network or device path, no symlink/junction/reparse ancestry, a trusted local
device, no active recovery quarantine.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scripts.backend_contract.application.ports import RepositoryError, RepositoryIntegrityError
from scripts.backend_contract.infrastructure import private_filesystem
from scripts.backend_contract.infrastructure.private_filesystem import provision_local_storage_directory
from scripts.backend_contract.product_bridge.server import ProductBridgeConfig
from scripts.planejamento_pericial import app_composition
from scripts.planejamento_pericial.app_composition import build_pericial_application
from tests.test_product_bridge_v1 import frontend_build, request

TOKEN = "first-run-storage-test-token-with-sufficient-entropy"


def _clean_machine(tmp_path: Path) -> tuple[Path, Path]:
    """root/app exists with a built frontend; root/dados does not."""
    root = tmp_path / "SistemaPericial"
    app = root / "app"
    app.mkdir(parents=True)
    return root, frontend_build(app / "frontend")


def _start(root: Path, frontend: Path):
    return build_pericial_application(
        root / "dados" / "produto.sqlite3",
        frontend,
        private_root=root / "dados" / "privado",
        config=ProductBridgeConfig(port=0),
        token=TOKEN,
    )


def _serves_the_ui(runtime, frontend: Path) -> None:
    status, _headers, body = request(runtime, "GET", "/")
    assert status == 200
    assert body == (frontend / "index.html").read_bytes()


# --- RED/GREEN: the real composition on a clean machine ---------------------------


def test_first_run_provisions_the_data_directory_and_serves_the_ui(tmp_path):
    root, frontend = _clean_machine(tmp_path)
    assert not (root / "dados").exists()

    runtime = _start(root, frontend)
    try:
        runtime.start()
        _serves_the_ui(runtime, frontend)
    finally:
        runtime.close()

    data = root / "dados"
    assert data.is_dir() and not data.is_symlink()
    assert (data / "produto.sqlite3").is_file()
    assert (data / "privado").is_dir()
    if os.name == "posix":
        assert data.stat().st_mode & 0o777 == 0o700


def test_restart_after_first_run_keeps_the_same_database(tmp_path):
    root, frontend = _clean_machine(tmp_path)
    first = _start(root, frontend)
    first.start()
    first.close()
    database = root / "dados" / "produto.sqlite3"
    identity = (database.stat().st_dev, database.stat().st_ino)

    again = _start(root, frontend)
    try:
        again.start()
        _serves_the_ui(again, frontend)
    finally:
        again.close()
    assert (database.stat().st_dev, database.stat().st_ino) == identity


def test_an_existing_data_directory_is_used_as_is(tmp_path):
    root, frontend = _clean_machine(tmp_path)
    (root / "dados").mkdir()
    marker = root / "dados" / "kept.txt"
    marker.write_text("x", encoding="utf-8")
    runtime = _start(root, frontend)
    try:
        runtime.start()
        _serves_the_ui(runtime, frontend)
    finally:
        runtime.close()
    assert marker.read_text(encoding="utf-8") == "x"


# --- the provisioning boundary, fail closed -----------------------------------------


def test_provisioning_creates_exactly_one_directory_and_reports_it(tmp_path):
    target = tmp_path / "dados"
    assert provision_local_storage_directory(target) is True
    assert target.is_dir()
    assert provision_local_storage_directory(target) is False


def test_a_missing_grandparent_is_not_created(tmp_path):
    target = tmp_path / "ausente" / "dados"
    with pytest.raises(RepositoryError):
        provision_local_storage_directory(target)
    assert not (tmp_path / "ausente").exists()


def test_a_data_path_that_is_an_ordinary_file_fails_closed(tmp_path):
    root, frontend = _clean_machine(tmp_path)
    (root / "dados").write_text("not a directory", encoding="utf-8")
    with pytest.raises(RepositoryIntegrityError):
        _start(root, frontend)
    assert (root / "dados").read_text(encoding="utf-8") == "not a directory"


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink fixture")
def test_a_symlinked_ancestor_fails_closed_and_creates_nothing(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    frontend = frontend_build(tmp_path / "frontend")
    with pytest.raises(RepositoryIntegrityError):
        build_pericial_application(
            tmp_path / "link" / "dados" / "produto.sqlite3",
            frontend,
            private_root=tmp_path / "link" / "dados" / "privado",
            config=ProductBridgeConfig(port=0),
            token=TOKEN,
        )
    assert not (real / "dados").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink fixture")
def test_a_symlinked_data_directory_fails_closed(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "dados").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(RepositoryIntegrityError):
        provision_local_storage_directory(tmp_path / "dados")


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction fixture")
def test_a_junction_ancestor_fails_closed_and_creates_nothing(tmp_path):
    import _winapi

    real = tmp_path / "real"
    real.mkdir()
    junction = tmp_path / "juncao"
    _winapi.CreateJunction(str(real), str(junction))
    frontend = frontend_build(tmp_path / "frontend")
    with pytest.raises(RepositoryIntegrityError):
        build_pericial_application(
            junction / "dados" / "produto.sqlite3",
            frontend,
            private_root=junction / "dados" / "privado",
            config=ProductBridgeConfig(port=0),
            token=TOKEN,
        )
    assert not (real / "dados").exists()


@pytest.mark.skipif(os.name != "nt", reason="NTFS junction fixture")
def test_a_junction_as_the_data_directory_fails_closed(tmp_path):
    import _winapi

    real = tmp_path / "real"
    real.mkdir()
    _winapi.CreateJunction(str(real), str(tmp_path / "dados"))
    with pytest.raises(RepositoryIntegrityError):
        provision_local_storage_directory(tmp_path / "dados")


def test_a_reparse_point_ancestor_fails_closed(tmp_path, monkeypatch):
    """The reparse attribute is what Windows reports for junctions and mount points."""
    parent = tmp_path / "montado"
    parent.mkdir()
    real_lstat = os.lstat

    class _Reparse:
        def __init__(self, details):
            self._details = details
            self.st_file_attributes = private_filesystem._REPARSE_ATTRIBUTE

        def __getattr__(self, name):
            return getattr(self._details, name)

    def lstat(path, *args, **kwargs):
        details = real_lstat(path, *args, **kwargs)
        return _Reparse(details) if Path(path) == parent else details

    monkeypatch.setattr(private_filesystem.os, "lstat", lstat)
    with pytest.raises(RepositoryIntegrityError):
        provision_local_storage_directory(parent / "dados")
    assert not (parent / "dados").exists()


@pytest.mark.parametrize(
    "database",
    [
        "\\\\servidor\\compartilhamento\\dados\\produto.sqlite3",
        "//servidor/compartilhamento/dados/produto.sqlite3",
        "\\\\?\\C:\\SistemaPericial\\dados\\produto.sqlite3",
        "\\\\.\\PhysicalDrive0\\dados\\produto.sqlite3",
    ],
    ids=["unc", "unc-forward", "device-namespace", "device-path"],
)
def test_network_and_device_paths_fail_closed(tmp_path, database):
    frontend = frontend_build(tmp_path / "frontend")
    with pytest.raises(RepositoryIntegrityError):
        build_pericial_application(
            database, frontend, config=ProductBridgeConfig(port=0), token=TOKEN
        )
    with pytest.raises(RepositoryIntegrityError):
        provision_local_storage_directory(database.rsplit("\\", 1)[0] if "\\" in database else database.rsplit("/", 1)[0])


def test_a_recovery_quarantine_ancestor_fails_closed_before_provisioning(tmp_path):
    root, frontend = _clean_machine(tmp_path)
    (root / "RECOVERY_NOT_PROMOTABLE").write_text("", encoding="utf-8")
    with pytest.raises(RepositoryIntegrityError, match="quarantined"):
        _start(root, frontend)
    assert not (root / "dados").exists()


def test_an_untrusted_device_fails_closed_and_creates_nothing(tmp_path, monkeypatch):
    def untrusted(_identity):
        raise RepositoryError("private root deve ser armazenamento local confiável")

    monkeypatch.setattr(private_filesystem, "_validate_trusted_local_device", untrusted)
    with pytest.raises(RepositoryError):
        provision_local_storage_directory(tmp_path / "dados")
    assert not (tmp_path / "dados").exists()


def test_a_directory_swapped_for_a_link_during_provisioning_fails_closed(tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("POSIX dir_fd race fixture")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    real_mkdir = os.mkdir

    def racing_mkdir(name, mode=0o777, *, dir_fd=None):
        real_mkdir(name, mode, dir_fd=dir_fd)
        os.rmdir(name, dir_fd=dir_fd)
        os.symlink(str(elsewhere), name, dir_fd=dir_fd)

    monkeypatch.setattr(private_filesystem.os, "mkdir", racing_mkdir)
    with pytest.raises(RepositoryError):
        provision_local_storage_directory(tmp_path / "dados")


# --- startup surface ------------------------------------------------------------------


def test_permission_denied_is_a_sanitized_startup_failure(tmp_path, monkeypatch, capsys):
    root, frontend = _clean_machine(tmp_path)

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Acesso negado", str(root / "dados"))

    monkeypatch.setattr(private_filesystem.os, "mkdir", denied)
    code = app_composition.main(
        [
            "--database", str(root / "dados" / "produto.sqlite3"),
            "--frontend", str(frontend),
            "--private-root", str(root / "dados" / "privado"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Sistema Pericial não iniciou" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert str(root) not in captured.err
    assert "disponível" not in captured.out
    assert not (root / "dados").exists()


def test_the_command_line_first_run_announces_the_ui(tmp_path, monkeypatch, capsys):
    """The Human RC shortcut's exact arguments, on a clean machine."""
    root, frontend = _clean_machine(tmp_path)
    started = []

    class _Stop(Exception):
        pass

    class _AnnouncedEvent:
        """Stands in for the forever-wait once the UI has been announced."""

        def wait(self, timeout=None):
            started.append(True)
            raise _Stop

    monkeypatch.setattr(app_composition, "Event", _AnnouncedEvent)
    with pytest.raises(_Stop):
        app_composition.main(
            [
                "--database", str(root / "dados" / "produto.sqlite3"),
                "--frontend", str(frontend),
                "--private-root", str(root / "dados" / "privado"),
                "--port", "0",
            ]
        )
    assert started
    assert "Sistema Pericial disponível em http://127.0.0.1:" in capsys.readouterr().out
    assert (root / "dados" / "produto.sqlite3").is_file()


# --- independent review (#283) -------------------------------------------------------


def test_private_root_provisioning_keeps_mapping_os_errors(tmp_path, monkeypatch):
    """provision_private_content_root still turns an OSError into RepositoryError."""

    def denied(*_args, **_kwargs):
        raise PermissionError(13, "Acesso negado", str(tmp_path / "privado"))

    monkeypatch.setattr(private_filesystem.os, "mkdir", denied)
    with pytest.raises(RepositoryError) as raised:
        private_filesystem.provision_private_content_root(tmp_path / "privado")
    assert str(tmp_path) not in str(raised.value)


def test_a_private_root_failure_is_a_sanitized_startup_failure(tmp_path, monkeypatch, capsys):
    root, frontend = _clean_machine(tmp_path)
    real_mkdir = os.mkdir

    def deny_private(path, *args, **kwargs):
        if str(path).endswith("privado"):
            raise PermissionError(13, "Acesso negado", str(path))
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(private_filesystem.os, "mkdir", deny_private)
    code = app_composition.main(
        [
            "--database", str(root / "dados" / "produto.sqlite3"),
            "--frontend", str(frontend),
            "--private-root", str(root / "dados" / "privado"),
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "Sistema Pericial não iniciou" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert str(root) not in captured.err


def test_the_volume_root_is_validated_not_created():
    """The trusted volume is the one the interpreter runs from (C:\\ on the RC)."""
    assert provision_local_storage_directory(Path(Path(sys.executable).anchor)) is False


def test_a_directory_refused_after_creation_fails_closed_without_deleting(tmp_path, monkeypatch):
    """The private filesystem never deletes; a refused creation stays an empty directory."""
    real = private_filesystem._validate_local_storage_device
    calls = []

    def refuse_the_created_directory(details):
        calls.append(details)
        if len(calls) == 2:
            raise RepositoryError("armazenamento local deve estar em dispositivo local confiável")
        return real(details)

    monkeypatch.setattr(private_filesystem, "_validate_local_storage_device", refuse_the_created_directory)
    with pytest.raises(RepositoryError):
        provision_local_storage_directory(tmp_path / "dados")
    assert len(calls) == 2
    assert (tmp_path / "dados").is_dir() and not any((tmp_path / "dados").iterdir())


def test_a_port_in_use_is_a_sanitized_startup_failure(tmp_path, capsys):
    import socket

    root, frontend = _clean_machine(tmp_path)
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    try:
        code = app_composition.main(
            [
                "--database", str(root / "dados" / "produto.sqlite3"),
                "--frontend", str(frontend),
                "--private-root", str(root / "dados" / "privado"),
                "--port", str(holder.getsockname()[1]),
            ]
        )
    finally:
        holder.close()
    captured = capsys.readouterr()
    assert code == 2
    assert "Sistema Pericial não iniciou" in captured.err
    assert "Traceback" not in captured.err + captured.out
    assert "disponível em" not in captured.out
