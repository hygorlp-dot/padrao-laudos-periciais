"""S-09: materializacao temporaria de conteudo privado.

Usar %TEMP% nao e defeito por si. O que importa e medido: quantas copias
integrais existem, quem e dono da limpeza, se ela e deterministica inclusive no
caminho de falha, e se algum handle sobrevive ao retorno -- em Windows um handle
aberto impede renomear/remover, entao a prova nao pode ser apenas um `finally`.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from scripts.planejamento_pericial.app_composition import build_pericial_local_api
from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter
from tests.test_document_intake_v1 import provision_private_root
from tests.test_final_closure_r7 import pdf_sintetico
from tests.test_local_api_v1 import TOKEN, http_request


def _request(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
    )
    return status, json.loads(raw) if raw else None


def _import(runtime, workspace_id, body, filename):
    return _request(
        runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=body,
        headers={"Content-Type": "application/pdf", "X-Document-Filename": filename},
    )


def _runtime(tmp_path, name="product.sqlite3"):
    private = tmp_path / "private"
    if not private.exists():
        provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / name, private_root=private, token=TOKEN)
    runtime.start()
    return runtime


def _watch_temp_dirs(monkeypatch):
    """Observa cada TemporaryDirectory criado durante a importacao."""
    created: list[dict] = []
    real = tempfile.TemporaryDirectory

    class Watched(real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._record = {"root": self.name, "prefix": kwargs.get("prefix", "")}
            created.append(self._record)

    import scripts.backend_contract.application.services as services_mod
    import scripts.triagem_pericial.pje_intake_adapter as adapter_mod

    monkeypatch.setattr(services_mod.tempfile, "TemporaryDirectory", Watched)
    monkeypatch.setattr(adapter_mod.tempfile, "TemporaryDirectory", Watched)
    return created


def test_a_pje_import_materializes_private_bytes_under_a_single_owner(tmp_path, monkeypatch):
    """Duas raizes temporarias significavam dois donos de limpeza."""
    created = _watch_temp_dirs(monkeypatch)
    pdf = tmp_path / "autos.pdf"
    pdf_sintetico(pdf)
    runtime = _runtime(tmp_path)
    try:
        _s, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        status, material = _import(runtime, workspace["workspace_id"], pdf.read_bytes(), "autos.pdf")
        assert status == 201, material
    finally:
        runtime.close()

    assert len(created) == 1, (
        f"conteudo privado materializado em {len(created)} raizes temporarias: "
        f"{[r['prefix'] for r in created]}"
    )
    assert not Path(created[0]["root"]).exists(), "a area de trabalho privada sobreviveu ao retorno"


@pytest.mark.parametrize(
    ("label", "body"),
    (
        ("nao_pje", b"%PDF-1.7\nnao-e-pje\n%%EOF\n"),
        ("pje_valido", None),
    ),
)
def test_no_private_staging_survives_the_operation(tmp_path, monkeypatch, label, body):
    created = _watch_temp_dirs(monkeypatch)
    if body is None:
        pdf = tmp_path / "autos.pdf"
        pdf_sintetico(pdf)
        body = pdf.read_bytes()
    runtime = _runtime(tmp_path, f"{label}.sqlite3")
    try:
        _s, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": label})
        _import(runtime, workspace["workspace_id"], body, f"{label}.pdf")
    finally:
        runtime.close()
    survivors = [r["root"] for r in created if Path(r["root"]).exists()]
    assert survivors == [], f"areas privadas sobreviveram: {survivors}"


def test_cleanup_is_deterministic_when_the_parser_raises_midway(tmp_path, monkeypatch):
    """Falha no meio do parse nao pode deixar os autos orfaos em %TEMP%."""
    created = _watch_temp_dirs(monkeypatch)

    import scripts.triagem_pericial.pje_intake_adapter as adapter_mod

    def _explode(*_args, **_kwargs):
        raise RuntimeError("falha sintetica no meio do parser")

    monkeypatch.setattr(adapter_mod, "construir_manifesto", _explode)

    pdf = tmp_path / "autos.pdf"
    pdf_sintetico(pdf)
    runtime = _runtime(tmp_path)
    try:
        _s, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        status, _payload = _import(runtime, workspace["workspace_id"], pdf.read_bytes(), "autos.pdf")
        # A falha e interna e nao mascarada como erro do cliente.
        assert status == 500, status
    finally:
        runtime.close()

    assert created, "nenhuma area temporaria foi observada"
    survivors = [r["root"] for r in created if Path(r["root"]).exists()]
    assert survivors == [], f"a falha deixou conteudo privado para tras: {survivors}"


def test_no_windows_handle_survives_the_adapter(tmp_path):
    """Prova de handle real: em Windows um handle aberto impede remover a arvore.

    `finally: unlink()` nao prova nada -- se o leitor de PDF mantivesse o arquivo
    aberto, a remocao do diretorio falharia com PermissionError.
    """
    pdf = tmp_path / "autos.pdf"
    pdf_sintetico(pdf)
    staging = tmp_path / "staging"
    staging.mkdir()
    outcome = PjeIntakeAdapter().logical_inventory(pdf, staging)
    assert outcome["status"] in {"OK", "BLOCKED", "NOT_PJE"}

    # Se algum handle sobrevivesse, estas operacoes falhariam no Windows.
    renamed = tmp_path / "staging-renomeado"
    staging.rename(renamed)
    shutil.rmtree(renamed)
    assert not renamed.exists()

    moved = tmp_path / "autos-movido.pdf"
    pdf.rename(moved)
    moved.unlink()
    assert not moved.exists()
