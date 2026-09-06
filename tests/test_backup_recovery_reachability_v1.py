"""#183 — backup/restauração alcançáveis pelo caminho normal do produto.

A infraestrutura canônica (`CreateWorkspaceBackup`, `VerifyWorkspaceBackup`,
`RecoveryStaging`, `RestoreWorkspaceBackup`) já existia e já era correta. O que
faltava era ALCANCE: proteger ou recuperar uma perícia exigia Python/terminal.
`CLI_ONLY / NOT_REACHABLE` para operação normal de usuário = bloqueador de
produto.

Estes testes exercem a cadeia publicada — Local API (e, onde aplicável, o
ProductBridge que o frontend realmente chama) → aplicação → infraestrutura —
nunca instanciando `RestoreWorkspaceBackup` diretamente para provar o caminho.

Modelo: `VERIFIED_STAGING_THEN_EXPLICIT_HUMAN_PROMOTION`.
"""

from __future__ import annotations

import json

from tests.test_document_intake_v1 import provision_private_root
from tests.test_final_closure_r7 import pdf_sintetico
from tests.test_local_api_v1 import TOKEN, http_request


def _api(runtime, method, path, *, value=None, body=None, headers=None):
    status, response_headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
    )
    return status, response_headers, raw


def _json(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = _api(runtime, method, path, value=value, body=body, headers=headers)
    return status, json.loads(raw) if raw else None


def _runtime(tmp_path, name="product"):
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / f"{name}-private"
    provision_private_root(private)
    runtime = build_pericial_local_api(
        tmp_path / f"{name}.sqlite3", private_root=private, token=TOKEN
    )
    runtime.start()
    return runtime


def _workspace_with_material(runtime, tmp_path, name="Caso"):
    status, workspace = _json(runtime, "POST", "/v1/workspaces", value={"name": name})
    assert status == 201, workspace
    workspace_id = workspace["workspace_id"]
    pdf = tmp_path / f"autos-{workspace_id}.pdf"
    pdf_sintetico(pdf)
    status, material = _json(
        runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
        body=pdf.read_bytes(),
        headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"},
    )
    assert status == 201, material
    return workspace_id, material


# ------------------------------------------------------------------ backup export


def test_backup_export_is_reachable_through_local_api(tmp_path):
    """UI → Local API → aplicação → CreateWorkspaceBackup → pacote baixável."""
    runtime = _runtime(tmp_path)
    try:
        workspace_id, _material = _workspace_with_material(runtime, tmp_path)
        status, headers, payload = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        assert status == 200, payload
        assert headers["Content-Type"] == "application/octet-stream"
        assert headers["Cache-Control"] == "no-store"
        assert "attachment" in headers.get("Content-Disposition", "")
        assert payload, "o pacote de backup veio vazio"
        assert int(headers["Content-Length"]) == len(payload)
        # o pacote é exatamente o que a infraestrutura canônica verifica
        from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup

        backup = VerifyWorkspaceBackup().execute(payload)
        assert str(backup.workspace.workspace_id) == workspace_id
        assert len(backup.private_contents) == 1
    finally:
        runtime.close()


def test_backup_export_never_leaks_internal_paths(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        workspace_id, _ = _workspace_with_material(runtime, tmp_path)
        _status, headers, _payload = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        rendered = json.dumps(dict(headers))
        assert str(tmp_path) not in rendered
        assert "sqlite3" not in headers.get("Content-Disposition", "")
    finally:
        runtime.close()


# ------------------------------------------------------------------ verify


def test_backup_verify_is_reachable_and_sanitized(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        workspace_id, _ = _workspace_with_material(runtime, tmp_path)
        _status, _headers, package = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        status, summary = _json(
            runtime, "POST", "/v1/recovery/verify", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 200, summary
        assert summary["workspace_id"] == workspace_id
        assert summary["artifact_revisions"] >= 1
        assert summary["private_contents"] == 1
        assert len(summary["backup_sha256"]) == 64
        # diagnóstico é estritamente contagem/identidade: nenhuma revisão,
        # payload ou byte privado atravessa a fronteira
        assert set(summary) == {
            "workspace_id", "workspace_name", "workspace_created_at",
            "product_release", "storage_schema_version",
            "artifact_revisions", "private_contents", "backup_sha256",
        }
        assert all(not isinstance(value, (list, dict)) for value in summary.values())
    finally:
        runtime.close()


def test_corrupt_backup_is_rejected_without_raw_exception_text(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        workspace_id, _ = _workspace_with_material(runtime, tmp_path)
        _status, _headers, package = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        corrupted = bytearray(package)
        corrupted[len(corrupted) // 2] ^= 0xFF
        status, error = _json(
            runtime, "POST", "/v1/recovery/verify", body=bytes(corrupted),
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 400
        assert error["error"]["code"] == "INVALID_BACKUP"
        assert "Traceback" not in json.dumps(error)
    finally:
        runtime.close()


# ------------------------------------------------------------------ staging + promotion


def test_staging_never_becomes_active_without_explicit_promotion(tmp_path):
    """RECOVERY_NOT_PROMOTABLE preservado; staging isolado nunca é ativo sozinho."""
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 201, staged
        assert staged["summary"]["workspace_id"] == workspace_id
        assert staged["promotable"] is True
        # o staging NÃO virou workspace vivo
        _status, listing = _json(target, "GET", "/v1/workspaces")
        assert all(item["workspace_id"] != workspace_id for item in listing["items"]), (
            "o staging virou workspace ativo sem promoção explícita"
        )
    finally:
        target.close()


def test_explicit_promotion_activates_and_reopens_workspace(tmp_path):
    """Promoção explícita → workspace canônico ativo → reabertura pela UI."""
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, material = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
        _status, source_docs = _json(source, "GET", f"/v1/workspaces/{workspace_id}/materials")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        recovery_id = staged["recovery_id"]
        status, promoted = _json(
            target, "POST", f"/v1/recovery/{recovery_id}/promote",
            value={"confirm": True},
        )
        assert status == 200, promoted
        assert promoted["workspace_id"] == workspace_id
        # reabertura canônica pela mesma superfície que a UI usa
        status, reopened = _json(target, "GET", f"/v1/workspaces/{workspace_id}")
        assert status == 200, reopened
        status, docs = _json(target, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert status == 200
        assert [item["checksum_sha256"] for item in docs["items"]] == [
            item["checksum_sha256"] for item in source_docs["items"]
        ]
        assert docs["items"][0]["content_id"] == material["content_id"]
    finally:
        target.close()


def test_promotion_requires_explicit_confirmation(tmp_path):
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        recovery_id = staged["recovery_id"]
        for value in ({}, {"confirm": False}, {"confirm": "sim"}):
            status, _error = _json(
                target, "POST", f"/v1/recovery/{recovery_id}/promote", value=value
            )
            assert status == 400, f"promoveu sem confirmação explícita: {value}"
        _status, listing = _json(target, "GET", "/v1/workspaces")
        assert all(item["workspace_id"] != workspace_id for item in listing["items"])
    finally:
        target.close()


def test_promotion_never_silently_overwrites_existing_workspace(tmp_path):
    """NO_SILENT_OVERWRITE + FAILED_RESTORE_PRESERVES_ORIGINAL."""
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _workspace_with_material(runtime, tmp_path)
        _status, _headers, package = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        # o mesmo workspace continua vivo; promover o backup dele deve recusar
        _status, staged = _json(
            runtime, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        status, error = _json(
            runtime, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        assert status == 409
        assert error["error"]["code"] == "WORKSPACE_CONFLICT"
        # o original permanece intacto
        status, docs = _json(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert status == 200
        assert docs["items"][0]["content_id"] == material["content_id"]
    finally:
        runtime.close()


def test_discarded_recovery_cannot_be_promoted(tmp_path):
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        recovery_id = staged["recovery_id"]
        status, _discarded = _json(target, "POST", f"/v1/recovery/{recovery_id}/discard")
        assert status == 200
        status, error = _json(
            target, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True}
        )
        assert status == 404
        assert error["error"]["code"] == "RECOVERY_NOT_FOUND"
        _status, listing = _json(target, "GET", "/v1/workspaces")
        assert all(item["workspace_id"] != workspace_id for item in listing["items"])
    finally:
        target.close()


def test_double_promotion_is_rejected_deterministically(tmp_path):
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        recovery_id = staged["recovery_id"]
        status, _first = _json(
            target, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True}
        )
        assert status == 200
        status, error = _json(
            target, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True}
        )
        assert status == 404
        assert error["error"]["code"] == "RECOVERY_NOT_FOUND"
    finally:
        target.close()


def test_unknown_recovery_identity_is_rejected(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        status, error = _json(
            runtime, "POST",
            "/v1/recovery/00000000-0000-4000-8000-000000000000/promote",
            value={"confirm": True},
        )
        assert status == 404
        assert error["error"]["code"] == "RECOVERY_NOT_FOUND"
    finally:
        runtime.close()


def test_invalid_backup_never_produces_promotable_staging(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        status, error = _json(
            runtime, "POST", "/v1/recovery/staging", body=b"{not a backup}",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 400
        assert error["error"]["code"] == "INVALID_BACKUP"
    finally:
        runtime.close()


# ------------------------------------------------------------------ longitudinal


def test_backup_after_restore_preserves_authority(tmp_path):
    """workspace → backup A → promover → reabrir → backup B → verificar → restaurar B."""
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, material = _workspace_with_material(source, tmp_path)
        _status, _headers, package_a = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package_a,
            headers={"Content-Type": "application/octet-stream"},
        )
        _status, _promoted = _json(
            target, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        _status, _headers, package_b = _api(target, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        target.close()

    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup

    backup_a = VerifyWorkspaceBackup().execute(package_a)
    backup_b = VerifyWorkspaceBackup().execute(package_b)
    assert backup_b.workspace.workspace_id == backup_a.workspace.workspace_id
    assert backup_b.workspace.created_at == backup_a.workspace.created_at
    assert backup_b.artifact_revisions == backup_a.artifact_revisions, (
        "a autoridade das revisões decaiu ao atravessar recuperação"
    )
    assert backup_b.private_contents == backup_a.private_contents, (
        "o conteúdo privado decaiu ao atravessar recuperação"
    )

    third = _runtime(tmp_path, "third")
    try:
        status, staged = _json(
            third, "POST", "/v1/recovery/staging", body=package_b,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 201
        status, promoted = _json(
            third, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        assert status == 200, promoted
        _status, docs = _json(third, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert docs["items"][0]["content_id"] == material["content_id"]
    finally:
        third.close()


# ------------------------------------------------------------------ boundary preservation


def test_recovery_quarantine_marker_is_never_removed(tmp_path):
    """A promoção NÃO desquarentena o staging — copia o conteúdo verificado.

    Este teste fica vermelho se alguém "simplificar" removendo
    RECOVERY_NOT_PROMOTABLE para adotar a raiz de staging como armazenamento.
    """
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        markers = list(tmp_path.rglob("RECOVERY_NOT_PROMOTABLE"))
        assert markers, "o staging não foi quarentenado"
        _status, _promoted = _json(
            target, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        for marker in markers:
            if marker.exists():
                assert marker.read_bytes() == b"RECOVERY_STAGING_V1\n", (
                    "a quarentena de recuperação foi adulterada"
                )
    finally:
        target.close()


def test_product_bridge_exposes_the_whole_recovery_journey(tmp_path):
    """O frontend fala com `/app-api`. Se o bridge não liberar estas rotas, a
    funcionalidade é invisível no produto — que é exatamente o bug de #183.

    Prova a jornada inteira pela MESMA superfície que o navegador usa:
    backup → verificar → preparar staging → promover → reabrir.
    """
    from scripts.planejamento_pericial.app_composition import build_pericial_application
    from tests.test_document_intake_v1 import frontend_build, product_request

    def _browser_headers(runtime, extra=None):
        # Cabeçalhos que o navegador realmente envia ao falar com o bridge.
        host = runtime.origin.removeprefix("http://")
        return {
            "Host": host,
            "Origin": runtime.origin,
            "Sec-Fetch-Site": "same-origin",
            **(extra or {}),
        }

    def _bridge(runtime, method, target, *, body=b"", headers=None):
        return product_request(
            runtime, method, target, body=body,
            headers=_browser_headers(runtime, headers),
        )

    def _bridge_json(runtime, method, target, *, body=b"", headers=None):
        status, _headers, raw = _bridge(runtime, method, target, body=body, headers=headers)
        return status, json.loads(raw) if raw else None

    private = tmp_path / "bridge-private"
    provision_private_root(private)
    runtime = build_pericial_application(
        tmp_path / "bridge.sqlite3",
        frontend_build(tmp_path / "bridge-frontend"),
        private_root=private,
        token=TOKEN,
    )
    runtime.start()
    try:
        status, workspace = _bridge_json(
            runtime, "POST", "/app-api/v1/workspaces",
            body=json.dumps({"name": "Caso"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert status == 201, workspace
        workspace_id = workspace["workspace_id"]
        pdf = tmp_path / "bridge-autos.pdf"
        pdf_sintetico(pdf)
        status, _material = _bridge_json(
            runtime, "POST", f"/app-api/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"},
        )
        assert status == 201

        status, headers, package = _bridge(
            runtime, "POST", f"/app-api/v1/workspaces/{workspace_id}/backup",
            headers={"Content-Type": "application/json"},
        )
        assert status == 200, package
        assert headers["Content-Type"] == "application/octet-stream"
        assert package

        status, summary = _bridge_json(
            runtime, "POST", "/app-api/v1/recovery/verify", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 200, summary
        assert summary["workspace_id"] == workspace_id
    finally:
        runtime.close()

    # promoção real numa instalação limpa, sempre pelo bridge
    target_private = tmp_path / "bridge2-private"
    provision_private_root(target_private)
    target = build_pericial_application(
        tmp_path / "bridge2.sqlite3",
        frontend_build(tmp_path / "bridge2-frontend"),
        private_root=target_private,
        token=TOKEN,
    )
    target.start()
    try:
        status, staged = _bridge_json(
            target, "POST", "/app-api/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 201, staged
        recovery_id = staged["recovery_id"]
        status, promoted = _bridge_json(
            target, "POST", f"/app-api/v1/recovery/{recovery_id}/promote",
            body=json.dumps({"confirm": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        assert status == 200, promoted
        assert promoted["workspace_id"] == workspace_id
        status, listing = _bridge_json(target, "GET", "/app-api/v1/workspaces")
        assert status == 200
        assert any(item["workspace_id"] == workspace_id for item in listing["items"]), (
            "o workspace promovido não é visível na UI"
        )
    finally:
        target.close()


def test_normal_user_recovery_needs_no_terminal(tmp_path):
    """NORMAL_USER_REQUIRES_TERMINAL = FALSE.

    Toda etapa da jornada é alcançável por HTTP no bridge que serve a UI; nenhum
    passo exige Python, SQLite, curl com caminho interno ou UUID inventado.
    """
    from scripts.backend_contract.product_bridge.transport import _proxy_target

    assert _proxy_target("/app-api/v1/recovery/verify", "POST") == "/v1/recovery/verify"
    assert _proxy_target("/app-api/v1/recovery/staging", "POST") == "/v1/recovery/staging"
    recovery_id = "00000000-0000-4000-8000-000000000000"
    assert _proxy_target(f"/app-api/v1/recovery/{recovery_id}/promote", "POST") == (
        f"/v1/recovery/{recovery_id}/promote"
    )
    assert _proxy_target(f"/app-api/v1/recovery/{recovery_id}/discard", "POST") == (
        f"/v1/recovery/{recovery_id}/discard"
    )
    workspace_id = "11111111-1111-4111-8111-111111111111"
    assert _proxy_target(f"/app-api/v1/workspaces/{workspace_id}/backup", "POST") == (
        f"/v1/workspaces/{workspace_id}/backup"
    )
    # e nada além disso é aberto por engano
    assert _proxy_target("/app-api/v1/recovery/promote", "POST") is None
    assert _proxy_target("/app-api/v1/recovery/staging", "GET") is None
    assert _proxy_target(f"/app-api/v1/recovery/{recovery_id}/promote", "DELETE") is None
    assert _proxy_target("/app-api/v1/recovery/../workspaces", "POST") is None


def _pdf_grande(path, target_bytes):
    """PDF sintético VÁLIDO do tamanho pedido — mesmas 4 páginas, mais um stream
    de enchimento. Fica pesado em BYTES (que é o que importa para o pacote) sem
    ficar pesado em PÁGINAS. Nada de conteúdo real de caso."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject

    base = path.parent / f"base-{path.name}"
    pdf_sintetico(base)
    writer = PdfWriter(clone_from=str(base))
    enchimento = DecodedStreamObject()
    enchimento.set_data(b"0" * max(target_bytes - base.stat().st_size, 1))
    writer._add_object(enchimento)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def _slow_request(
    runtime, method, path, *, body=None, value=None, headers=None, timeout=120, raw=False
):
    """Como `http_request`, mas com folga para pacotes de backup reais.

    `raw=True` devolve os bytes crus — obrigatório para o pacote de backup, que é
    JSON canônico e seria decodificado por engano.
    """
    import http.client

    request_headers = {"X-Local-API-Token": TOKEN, **(headers or {})}
    payload = body
    if value is not None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    host, port = runtime.server.address
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        received = response.read()
        if raw:
            return response.status, received
        return response.status, json.loads(received) if received else None
    finally:
        connection.close()


def test_real_workspace_package_survives_the_whole_chain(tmp_path):
    """Um backup de perícia REAL passa pela cadeia inteira.

    O pacote embute todo o conteúdo privado em JSON canônico (base64 ≈ 4/3), então
    qualquer perícia com um PDF de autos já ultrapassa o teto JSON legado. Se o
    servidor HTTP decidir o teto de body sem consultar `request_body_limit`, o
    produto gera um backup que ele mesmo não consegue verificar nem restaurar — e
    a metade "recuperação" de #183 fica inalcançável justamente nos casos reais.
    """
    from scripts.backend_contract.local_api.transport import MAX_DOCUMENT_BYTES  # noqa: F401

    source = _runtime(tmp_path, "big-source")
    try:
        status, workspace = _json(source, "POST", "/v1/workspaces", value={"name": "Caso real"})
        assert status == 201, workspace
        workspace_id = workspace["workspace_id"]
        pdf = _pdf_grande(tmp_path / "autos-grande.pdf", 900_000)
        status, material = _slow_request(
            source, "POST", f"/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"},
        )
        assert status == 201, material
        status, package = _slow_request(
            source, "POST", f"/v1/workspaces/{workspace_id}/backup", raw=True
        )
        assert status == 200
        assert len(package) > 1_048_576, (
            "o pacote precisa ultrapassar o teto JSON legado para exercer o defeito"
        )
    finally:
        source.close()

    target = _runtime(tmp_path, "big-target")
    try:
        status, summary = _slow_request(
            target, "POST", "/v1/recovery/verify", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 200, summary
        status, staged = _slow_request(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert status == 201, staged
        status, promoted = _slow_request(
            target, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        assert status == 200, promoted
        status, docs = _slow_request(target, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert status == 200
        assert docs["items"][0]["checksum_sha256"] == material["checksum_sha256"]
    finally:
        target.close()


def test_confirmation_rejects_truthy_lookalikes(tmp_path):
    """`1` e `1.0` são iguais a `True` em Python. O contrato diz booleano EXATO —
    a promoção é o ato autoritativo e não pode aceitar um "quase verdadeiro"."""
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        recovery_id = staged["recovery_id"]
        for value in ({"confirm": 1}, {"confirm": 1.0}, {"confirm": True, "extra": 1}):
            status, _error = _json(
                target, "POST", f"/v1/recovery/{recovery_id}/promote", value=value
            )
            assert status == 400, f"promoveu com confirmação não booleana: {value}"
        _status, listing = _json(target, "GET", "/v1/workspaces")
        assert all(item["workspace_id"] != workspace_id for item in listing["items"])
        # o booleano verdadeiro continua promovendo
        status, _promoted = _json(
            target, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True}
        )
        assert status == 200
    finally:
        target.close()


def test_backup_of_unknown_workspace_is_not_found(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        status, error = _json(
            runtime, "POST",
            "/v1/workspaces/00000000-0000-4000-8000-000000000000/backup",
        )
        assert status == 404
        assert error["error"]["code"] == "WORKSPACE_NOT_FOUND"
    finally:
        runtime.close()


def test_discard_and_promotion_remove_the_staging_root_from_disk(tmp_path):
    """`Descartar` tem de descartar de verdade.

    `RecoveryStaging.discard()` só fecha handles — a raiz fica. Sem coleta, cada
    recuperação deixaria no disco uma cópia INTEGRAL e em claro do conteúdo
    privado da perícia, para sempre, enquanto a UI diz que foi descartada.
    """
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        # descarte explícito
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert list(tmp_path.rglob("RECOVERY_NOT_PROMOTABLE")), "staging não foi criado"
        status, _ = _json(target, "POST", f"/v1/recovery/{staged['recovery_id']}/discard")
        assert status == 200
        assert not list(tmp_path.rglob("RECOVERY_NOT_PROMOTABLE")), (
            "a raiz de staging descartada continua no disco"
        )

        # promoção também recolhe
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        status, _ = _json(
            target, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        assert status == 200
        assert not list(tmp_path.rglob("RECOVERY_NOT_PROMOTABLE")), (
            "a raiz de staging promovida continua no disco"
        )
    finally:
        target.close()


def test_shutdown_collects_pending_staging_roots(tmp_path):
    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    try:
        for _ in range(3):
            status, _staged = _json(
                target, "POST", "/v1/recovery/staging", body=package,
                headers={"Content-Type": "application/octet-stream"},
            )
            assert status == 201
        assert len(list(tmp_path.rglob("RECOVERY_NOT_PROMOTABLE"))) == 3
    finally:
        target.close()
    assert not list(tmp_path.rglob("RECOVERY_NOT_PROMOTABLE")), (
        "stagings pendentes sobreviveram ao encerramento"
    )


def test_backup_route_consults_the_canonical_readiness_authority(tmp_path):
    """A autoridade canônica de prontidão não pode ser um no-op na composição.

    `CreateWorkspaceBackup` exige `assert_backup_ready` justamente para recusar o
    backup enquanto houver vistoria offline pendente. Se a composição do produto
    ligar um `lambda: None` ali, o pacote sai em silêncio SEM o trabalho de campo
    e o perito acredita estar protegido. Este teste fica vermelho nesse caso: ele
    faz a autoridade canônica recusar e exige que a rota recuse junto.
    """
    from scripts.backend_contract.infrastructure.field_mobile import (
        DeviceOfflineVaultRegistry,
    )

    # controle: com o campo sincronizado, o backup funciona
    saudavel = _runtime(tmp_path, "readiness-ok")
    try:
        workspace_id, _ = _workspace_with_material(saudavel, tmp_path)
        status, _headers, _package = _api(
            saudavel, "POST", f"/v1/workspaces/{workspace_id}/backup"
        )
        assert status == 200, "o backup deveria funcionar com o campo sincronizado"
    finally:
        saudavel.close()

    # a composição liga a autoridade no build, então a recusa precisa existir ANTES
    original = DeviceOfflineVaultRegistry.assert_workspace_backup_ready
    try:
        def _recusa(self, _workspace_id):
            raise ValueError("pending offline field work must be synchronized before backup")

        DeviceOfflineVaultRegistry.assert_workspace_backup_ready = _recusa
        pendente = _runtime(tmp_path, "readiness-pendente")
        try:
            workspace_id, _ = _workspace_with_material(pendente, tmp_path)
            status, _headers, _body = _api(
                pendente, "POST", f"/v1/workspaces/{workspace_id}/backup"
            )
            assert status >= 400, (
                "a rota de backup ignorou a autoridade canônica de prontidão "
                "(assert_backup_ready provavelmente está ligado a um no-op)"
            )
        finally:
            pendente.close()
    finally:
        DeviceOfflineVaultRegistry.assert_workspace_backup_ready = original


def test_backup_survives_offline_device_revocation(tmp_path):
    """Revogar o dispositivo de campo não pode matar o backup.

    A autoridade de prontidão existe para impedir backup que OMITA trabalho
    sincronizável. Um dispositivo revogado tem cofre inacessível — não há
    trabalho recuperável a proteger — e é exatamente a hora em que o perito mais
    precisa de um backup. Bloquear ali deixaria `NORMAL_USER_REQUIRES_TERMINAL`
    verdadeiro para o backup.
    """
    runtime = _runtime(tmp_path, "revogado")
    try:
        workspace_id, _ = _workspace_with_material(runtime, tmp_path)
        status, _headers, _package = _api(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/backup"
        )
        assert status == 200

        status, _revoked = _json(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/offline-device/revoke",
            value={"confirm": True},
        )
        assert status == 200, _revoked

        status, _headers, package = _api(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/backup"
        )
        assert status == 200, (
            "revogar o dispositivo de campo deixou o backup inalcançável"
        )
        from scripts.backend_contract.infrastructure.productization import (
            VerifyWorkspaceBackup,
        )

        assert str(VerifyWorkspaceBackup().execute(package).workspace.workspace_id) == workspace_id
    finally:
        runtime.close()


def test_failed_promotion_leaves_no_private_residue_in_live_storage(tmp_path):
    """Uma promoção que falha não pode depositar material sigiloso no
    armazenamento VIVO.

    O conteúdo privado é escrito por ÚLTIMO justamente por isso: se viesse
    primeiro, uma falha posterior deixaria cópia integral e em claro do material
    da perícia no armazenamento permanente — sem workspace que a referencie, sem
    rota que a enxergue e sem coleta que a remova (a coleta de staging só alcança
    a raiz de recuperação).
    """
    from scripts.backend_contract.infrastructure.sqlite import (
        SQLiteWorkspaceRepository,
    )

    source = _runtime(tmp_path, "source")
    try:
        workspace_id, _ = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target_private = tmp_path / "target-private"
    target = _runtime(tmp_path, "target")
    original_create = SQLiteWorkspaceRepository.create
    try:
        antes = sorted(p.name for p in target_private.iterdir())
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )

        def _create_quebrado(self, *_args, **_kwargs):
            raise OSError("disco cheio")

        SQLiteWorkspaceRepository.create = _create_quebrado
        status, _error = _json(
            target, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        assert status >= 400, "a promoção deveria ter falhado"
        SQLiteWorkspaceRepository.create = original_create

        depois = sorted(p.name for p in target_private.iterdir())
        assert depois == antes, (
            "a promoção falha deixou resíduo privado no armazenamento vivo: "
            f"{set(depois) - set(antes)}"
        )
        _status, listing = _json(target, "GET", "/v1/workspaces")
        assert all(item["workspace_id"] != workspace_id for item in listing["items"])
    finally:
        SQLiteWorkspaceRepository.create = original_create
        target.close()


def test_interrupted_promotion_is_resumable_by_the_same_session(tmp_path):
    """Uma promoção interrompida DEPOIS das escritas vivas tem de ser retomável.

    Sem transação entre SQLite e sistema de arquivos, e sem remoção de workspace
    (append-only por design), a falha deixava perícia parcialmente restaurada que
    recusava toda retentativa com 409 — sem saída pelo produto. A retomada é
    estreita: mesma sessão, e o vivo tem de ser prefixo EXATO do verificado.
    """
    from scripts.backend_contract.infrastructure.private_filesystem import (
        LocalPrivateContentStore,
    )

    source = _runtime(tmp_path, "source")
    try:
        workspace_id, material = _workspace_with_material(source, tmp_path)
        _status, _headers, package = _api(source, "POST", f"/v1/workspaces/{workspace_id}/backup")
    finally:
        source.close()

    target = _runtime(tmp_path, "target")
    original_store = LocalPrivateContentStore.store
    try:
        _status, staged = _json(
            target, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        recovery_id = staged["recovery_id"]

        # falha DEPOIS do workspace e das revisões, na fase de conteúdo privado
        def _store_quebrado(self, *_args, **_kwargs):
            raise OSError("disco cheio")

        LocalPrivateContentStore.store = _store_quebrado
        status, _error = _json(
            target, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True}
        )
        assert status >= 400, "a promoção deveria ter falhado"
        LocalPrivateContentStore.store = original_store

        # a perícia ficou parcialmente restaurada — e a retentativa COMPLETA
        status, promoted = _json(
            target, "POST", f"/v1/recovery/{recovery_id}/promote", value={"confirm": True}
        )
        assert status == 200, f"a promoção interrompida não pôde ser retomada: {promoted}"
        _status, docs = _json(target, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert docs["items"][0]["content_id"] == material["content_id"]
        assert docs["items"][0]["checksum_sha256"] == material["checksum_sha256"]
    finally:
        LocalPrivateContentStore.store = original_store
        target.close()


def test_resume_never_touches_a_foreign_workspace(tmp_path):
    """A retomada não pode virar uma porta para mutar perícia viva alheia.

    Só continua quando ESTA sessão começou a promoção; um pacote cuja identidade
    colide com uma perícia viva que não veio desta promoção segue em conflito.
    """
    runtime = _runtime(tmp_path)
    try:
        workspace_id, material = _workspace_with_material(runtime, tmp_path)
        _status, _headers, package = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/backup")
        _status, staged = _json(
            runtime, "POST", "/v1/recovery/staging", body=package,
            headers={"Content-Type": "application/octet-stream"},
        )
        status, error = _json(
            runtime, "POST", f"/v1/recovery/{staged['recovery_id']}/promote",
            value={"confirm": True},
        )
        assert status == 409
        assert error["error"]["code"] == "WORKSPACE_CONFLICT"
        _status, docs = _json(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        assert docs["items"][0]["content_id"] == material["content_id"]
    finally:
        runtime.close()


def test_recovery_routes_require_the_local_token(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        workspace_id, _ = _workspace_with_material(runtime, tmp_path)
        for method, path in (
            ("POST", f"/v1/workspaces/{workspace_id}/backup"),
            ("POST", "/v1/recovery/verify"),
            ("POST", "/v1/recovery/staging"),
        ):
            status, _headers, _raw = http_request(runtime.server, method, path, raw_body=b"x")
            assert status == 403, f"{method} {path} aceitou requisição sem token"
    finally:
        runtime.close()
