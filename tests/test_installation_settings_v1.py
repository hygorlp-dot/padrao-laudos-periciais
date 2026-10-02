"""#270 — Central de Configurações: autoridade de instalação e snapshot por perícia.

Contrato provado aqui:
- padrão global com histórico append-only, restauração como revisão nova;
- nova perícia captura o padrão vigente; mudar o padrão não muda a perícia;
- ativo de marca copiado por identidade exata, nunca material do caso (F8);
- backup da perícia carrega o snapshot efetivo, não a configuração global.
"""

from __future__ import annotations

from io import BytesIO
import json
import sqlite3
from uuid import uuid4

import pytest

from scripts.backend_contract.application.ports import PersistenceSchemaError, RepositoryConflict, RepositoryIntegrityError
from scripts.backend_contract.infrastructure.installation_store import SQLiteInstallationStore, installation_database_path
from scripts.backend_contract.installation_settings import (
    DEFAULT_BRANDING,
    DEFAULT_PRESENTATION,
    WATERMARK_MAX_OPACITY,
    BrandingProfile,
    WatermarkPresentation,
    WatermarkKind,
    default_payload,
    SettingKind,
)


def _png(color=(31, 58, 77, 255), size=(64, 32), mode="RGBA"):
    from PIL import Image
    buffer = BytesIO()
    Image.new(mode, size, color if mode != "L" else 128).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(size=(40, 40)):
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", size, (200, 10, 10)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _profile(name="Perita Sintética", court="TRF5 — Cadastro 001"):
    return {
        "profile_id": "EXPERT-PROFILE-001", "revision": 1, "full_name": name, "professional_title": "Engenheira civil",
        "registration": "CREA-PE 000000", "court_registration": court, "contact_line": "perita@exemplo.invalid",
        "court_registrations": [{"court": "TRF5", "registration": "Cadastro 001", "label": "Perita do juízo", "active": True, "legacy": False}],
        "contact": {"email": "perita@exemplo.invalid", "phone": None, "office_name": None, "city": "Recife", "state": "PE"},
    }


# --- Store ---------------------------------------------------------------


def test_store_is_append_only_survives_restart_and_fails_closed_on_unknown_schema(tmp_path):
    path = tmp_path / "install.sqlite3"
    store = SQLiteInstallationStore(path)
    assert store.latest("BRANDING_PROFILE_V1", "DEFAULT") is None
    first = store.append_if_latest(setting_kind="BRANDING_PROFILE_V1", setting_id="DEFAULT", revision_id=str(uuid4()), created_at="2026-10-02T12:00:00+00:00", payload={"a": 1}, expected_revision=None)
    with pytest.raises(RepositoryConflict):
        store.append_if_latest(setting_kind="BRANDING_PROFILE_V1", setting_id="DEFAULT", revision_id=str(uuid4()), created_at="2026-10-02T12:00:00+00:00", payload={"a": 2}, expected_revision=None)
    store.append_if_latest(setting_kind="BRANDING_PROFILE_V1", setting_id="DEFAULT", revision_id=str(uuid4()), created_at="2026-10-02T12:01:00+00:00", payload={"a": 2}, expected_revision=1)
    asset = store.put_asset(b"\x89PNG-bytes", "image/png")
    assert store.put_asset(b"\x89PNG-bytes", "image/png").sha256 == asset.sha256
    store.close()
    reopened = SQLiteInstallationStore(path)
    assert [item.payload for item in reopened.history("BRANDING_PROFILE_V1", "DEFAULT")] == [{"a": 1}, {"a": 2}]
    assert reopened.latest("BRANDING_PROFILE_V1", "DEFAULT").revision == 2 and first.revision == 1
    assert reopened.get_asset(asset.sha256).content == b"\x89PNG-bytes"
    reopened.close()
    # Adulteracao do payload ou dos bytes falha fechado ao abrir.
    connection = sqlite3.connect(path)
    connection.execute("UPDATE installation_setting_revisions SET payload_json = '{\"a\":9}' WHERE revision = 1")
    connection.commit()
    connection.close()
    with pytest.raises(RepositoryIntegrityError):
        SQLiteInstallationStore(path)
    foreign = tmp_path / "foreign.sqlite3"
    connection = sqlite3.connect(foreign)
    connection.execute("CREATE TABLE something (x INTEGER)")
    connection.commit()
    connection.close()
    with pytest.raises(PersistenceSchemaError):
        SQLiteInstallationStore(foreign)


def test_unreadable_installation_file_disables_settings_but_never_the_existing_cases(tmp_path):
    # Revisão do 2º conjunto, P2-2: o arquivo da instalação adulterado falha
    # fechado para as configurações, sem levar junto as perícias.
    runtime = _runtime(tmp_path)
    try:
        _upload(runtime, "PRIMARY_LOGO", _png(), "logo.png", "image/png", None)
        _, existing = _http(runtime, "POST", "/v1/workspaces", {"name": "Existente"})
    finally:
        runtime.close()
    connection = sqlite3.connect(installation_database_path(tmp_path / "pericias.sqlite3"))
    connection.execute("UPDATE installation_setting_revisions SET payload_json = '{\"a\":9}' WHERE revision = 1")
    connection.commit()
    connection.close()
    runtime = _runtime(tmp_path)
    try:
        status, listed = _http(runtime, "GET", "/v1/workspaces")
        assert status == 200 and [item["workspace_id"] for item in listed["items"]] == [existing["workspace_id"]]
        assert _http(runtime, "GET", f"/v1/workspaces/{existing['workspace_id']}")[0] == 200
        status, body = _http(runtime, "GET", "/v1/installation/settings")
        assert status == 503 and body["error"]["code"] == "SETTINGS_UNAVAILABLE"
        assert _http(runtime, "GET", "/v1/installation/test-document")[0] == 503
        status, body = _http(runtime, "GET", f"/v1/workspaces/{existing['workspace_id']}/settings-snapshot")
        assert status == 200 and body["differences"] is None and body["snapshot"]["workspace_id"] == existing["workspace_id"]
        status, body = _http(runtime, "POST", f"/v1/workspaces/{existing['workspace_id']}/settings-snapshot/refresh", {"include_profile": False, "expected_snapshot_revision": 1, "expected_profile_revision": None})
        assert status == 503 and body["error"]["code"] == "SETTINGS_UNAVAILABLE"
        status, body = _http(runtime, "POST", "/v1/workspaces", {"name": "Nova"})
        assert status == 503 and body["error"]["code"] == "SETTINGS_UNAVAILABLE"
        assert len(_http(runtime, "GET", "/v1/workspaces")[1]["items"]) == 1, "no half-created case"
    finally:
        runtime.close()


def test_installation_file_sits_next_to_the_database_and_never_inside_a_workspace(tmp_path):
    path = installation_database_path(tmp_path / "dados" / "pericias.sqlite3")
    assert path.parent == tmp_path / "dados" and path.name == ".pericias.sqlite3.installation.sqlite3"


# --- Domínio -----------------------------------------------------------------


def test_presentation_rules_protect_legibility():
    with pytest.raises(ValueError):
        BrandingProfile("#1F3A4D", "#5B7083", "#9AAAB8", "#F0F0F0")
    with pytest.raises(ValueError):
        WatermarkPresentation(True, WatermarkKind.TEXT, None, 0.08, 0.5, 0, False, True, False)
    with pytest.raises(ValueError):
        WatermarkPresentation(True, WatermarkKind.SYMBOL, None, WATERMARK_MAX_OPACITY + 0.01, 0.5, 0, False, True, False)
    loud = WatermarkPresentation(True, WatermarkKind.SYMBOL, None, 0.25, 0.5, 0, False, True, False)
    assert loud.legibility_warning and not DEFAULT_PRESENTATION.watermark.legibility_warning
    assert DEFAULT_PRESENTATION.background.kind.value == "WHITE" and DEFAULT_PRESENTATION.watermark.apply_body
    assert default_payload(SettingKind.BRANDING_PROFILE)["heading_color"] == DEFAULT_BRANDING.heading_color


# --- Produto via HTTP -------------------------------------------------------


TOKEN = "t" * 43


def _runtime(tmp_path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN as ORACLE_TOKEN
    runtime = build_local_api(tmp_path / "pericias.sqlite3", token=ORACLE_TOKEN, private_root=tmp_path / "private")
    runtime.start()
    return runtime


def _http(runtime, method, path, value=None, raw_body=None, headers=None):
    from tests.test_product_integration_oracle_v1 import _http as oracle_http
    return oracle_http(runtime, method, path, value=value, raw_body=raw_body, headers=headers)


def _upload(runtime, role, content, filename, media_type, expected):
    return _http(runtime, "POST", f"/v1/installation/assets/{role}", raw_body=content, headers={"Content-Type": media_type, "X-Document-Filename": filename, "X-Expected-Revision": "none" if expected is None else str(expected)})


def test_empty_install_shows_product_defaults_and_settings_persist_across_restart(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        status, overview = _http(runtime, "GET", "/v1/installation/settings")
        assert status == 200
        assert overview["readiness"] == {"expert_profile": "MISSING", "branding": "PRODUCT_DEFAULT", "document": "PRODUCT_DEFAULT", "editorial": "PRESET", "legal_editorial": "CNJ_TRF5", "template": "PRODUCT_DEFAULT"}
        assert overview["settings"]["EXPERT_PROFILE_DEFAULT_V1"] == {"configured": False, "revision": None, "revision_id": None, "created_at": None, "checksum_sha256": None, "payload": None, "product_default": None}
        assert all(item["asset"] is None for item in overview["assets"].values())
        status, saved = _http(runtime, "PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": None, "payload": _profile()})
        assert status == 200 and saved["readiness"]["expert_profile"] == "CONFIGURED"
        assert _http(runtime, "PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": None, "payload": _profile()})[0] == 409
        assert _http(runtime, "PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": 1, "payload": {**_profile(), "contact": {"email": "invalido", "phone": None, "office_name": None, "city": None, "state": None}}})[0] == 400
        assert _http(runtime, "GET", "/v1/installation/settings", headers={"X-Local-API-Token": "x" * 43})[0] == 403
    finally:
        runtime.close()
    reopened = _runtime(tmp_path)
    try:
        status, overview = _http(reopened, "GET", "/v1/installation/settings")
        assert status == 200 and overview["settings"]["EXPERT_PROFILE_DEFAULT_V1"]["payload"]["full_name"] == "Perita Sintética"
    finally:
        reopened.close()


def test_history_is_append_only_and_restore_writes_a_new_revision(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        branding = {"primary_color": "#1F3A4D", "secondary_color": "#5B7083", "rule_color": "#9AAAB8", "heading_color": "#1F3A4D"}
        assert _http(runtime, "PUT", "/v1/installation/settings/BRANDING_PROFILE_V1", {"expected_revision": None, "payload": branding})[0] == 200
        assert _http(runtime, "PUT", "/v1/installation/settings/BRANDING_PROFILE_V1", {"expected_revision": 1, "payload": {**branding, "heading_color": "#2B2B2B"}})[0] == 200
        status, restored = _http(runtime, "POST", "/v1/installation/settings/BRANDING_PROFILE_V1/restore", {"revision": 1, "expected_revision": 2})
        assert status == 200 and restored["settings"]["BRANDING_PROFILE_V1"]["revision"] == 3
        status, history = _http(runtime, "GET", "/v1/installation/settings/BRANDING_PROFILE_V1/history")
        assert [item["payload"]["heading_color"] for item in history["items"]] == ["#1F3A4D", "#2B2B2B", "#1F3A4D"]
        assert _http(runtime, "POST", "/v1/installation/settings/BRANDING_PROFILE_V1/restore", {"revision": 9, "expected_revision": 3})[0] == 400
    finally:
        runtime.close()


def test_assets_accept_png_and_jpeg_only_and_refuse_bad_images(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        assert _upload(runtime, "PRIMARY_LOGO", _png(), "logo.png", "image/png", None)[0] == 201
        assert _upload(runtime, "SYMBOL", _jpeg(), "simbolo.jpg", "image/jpeg", None)[0] == 201
        assert _upload(runtime, "SIGNATURE_IMAGE", _png(mode="L", size=(80, 30)), "assinatura.png", "image/png", None)[0] == 201
        status, body = _upload(runtime, "WATERMARK", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "marca.svg", "image/png", None)
        assert status == 422 and body["error"]["code"] == "ASSET_IMAGE_UNREADABLE"
        status, body = _upload(runtime, "WATERMARK", _jpeg(), "marca.png", "image/png", None)
        assert status == 422 and body["error"]["code"] == "ASSET_FORMAT_MISMATCH"
        status, body = _upload(runtime, "WATERMARK", _png(size=(4, 4)), "minimo.png", "image/png", None)
        assert status == 422 and body["error"]["code"] == "ASSET_DIMENSIONS_OUT_OF_RANGE"
        status, body = _upload(runtime, "DEFAULT_WORD_TEMPLATE", b"PK not a docx", "modelo.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", None)
        assert status == 422 and body["error"]["code"] == "ASSET_TEMPLATE_INVALID"
        status, overview = _http(runtime, "GET", "/v1/installation/settings")
        assert overview["assets"]["PRIMARY_LOGO"]["asset"]["width"] == 64 and overview["assets"]["WATERMARK"]["asset"] is None
        from tests.test_product_integration_oracle_v1 import TOKEN as ORACLE_TOKEN, http_request
        status, headers, content = http_request(runtime.server, "GET", "/v1/installation/assets/PRIMARY_LOGO/content", headers={"X-Local-API-Token": ORACLE_TOKEN})
        assert status == 200 and content == _png() and dict(headers)["Content-Type"] == "image/png"
        assert _http(runtime, "POST", "/v1/installation/assets/PRIMARY_LOGO/removal", {"expected_revision": 1})[0] == 200
        assert _http(runtime, "GET", "/v1/installation/settings")[1]["assets"]["PRIMARY_LOGO"]["asset"] is None
    finally:
        runtime.close()


def test_global_change_never_rewrites_an_existing_workspace_and_new_workspace_gets_it(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        _http(runtime, "PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": None, "payload": _profile()})
        _upload(runtime, "PRIMARY_LOGO", _png((10, 10, 10, 255)), "logo-r1.png", "image/png", None)
        _, a = _http(runtime, "POST", "/v1/workspaces", {"name": "Perícia A"})
        root_a = f"/v1/workspaces/{a['workspace_id']}"
        status, settings_a = _http(runtime, "GET", root_a + "/settings-snapshot")
        assert status == 200 and settings_a["revision"] == 1
        logo_a = next(item for item in settings_a["snapshot"]["assets"] if item["role"] == "PRIMARY_LOGO")
        assert _http(runtime, "GET", root_a + "/expert-profile")[1]["profile"]["full_name"] == "Perita Sintética"
        assert settings_a["differences"] == {"snapshot_revision": 1, "profile_revision": 1, "settings_changes": [], "profile_changes": []}
        # Padrão global muda: r2 do perfil e logo r2.
        _http(runtime, "PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": 1, "payload": _profile(name="Perita Sintética Atualizada")})
        _upload(runtime, "PRIMARY_LOGO", _png((200, 10, 10, 255)), "logo-r2.png", "image/png", 1)
        status, again = _http(runtime, "GET", root_a + "/settings-snapshot")
        assert again["snapshot"] == settings_a["snapshot"] and again["revision"] == 1
        assert _http(runtime, "GET", root_a + "/expert-profile")[1]["profile"]["full_name"] == "Perita Sintética"
        assert again["differences"]["settings_changes"] == ["ASSET:PRIMARY_LOGO"] and "full_name" in again["differences"]["profile_changes"]
        _, b = _http(runtime, "POST", "/v1/workspaces", {"name": "Perícia B"})
        root_b = f"/v1/workspaces/{b['workspace_id']}"
        settings_b = _http(runtime, "GET", root_b + "/settings-snapshot")[1]
        logo_b = next(item for item in settings_b["snapshot"]["assets"] if item["role"] == "PRIMARY_LOGO")
        assert logo_b["sha256"] != logo_a["sha256"] and logo_b["filename"] == "logo-r2.png"
        assert _http(runtime, "GET", root_b + "/expert-profile")[1]["profile"]["full_name"] == "Perita Sintética Atualizada"
        # Atualização explícita de A: nova revisão, histórico preservado.
        assert _http(runtime, "POST", root_a + "/settings-snapshot/refresh", {"include_profile": True, "expected_snapshot_revision": 9, "expected_profile_revision": 1})[0] == 409
        status, refreshed = _http(runtime, "POST", root_a + "/settings-snapshot/refresh", {"include_profile": True, "expected_snapshot_revision": 1, "expected_profile_revision": 1})
        assert status == 200 and refreshed["revision"] == 2 and refreshed["snapshot"]["reason"] == "UPDATED_FROM_INSTALLATION_DEFAULTS"
        profile_a = _http(runtime, "GET", root_a + "/expert-profile")[1]
        assert profile_a["revision"] == 2 and profile_a["profile"]["full_name"] == "Perita Sintética Atualizada"
    finally:
        runtime.close()


def test_branding_copies_never_become_case_materials(tmp_path):
    runtime = _runtime(tmp_path)
    try:
        _upload(runtime, "PRIMARY_LOGO", _png(), "logo.png", "image/png", None)
        _upload(runtime, "WATERMARK", _png((50, 50, 50, 40)), "marca.png", "image/png", None)
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "F8 com marca"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        status, materials = _http(runtime, "GET", root + "/materials")
        assert status == 200 and materials["items"] == []
        status, analysis = _http(runtime, "GET", root + "/process-participants")
        assert status == 200 and analysis["pending_documents"] == []
        status, proposals = _http(runtime, "GET", root + "/property-record/proposals")
        assert status == 200 and proposals["proposals"] == []
    finally:
        runtime.close()


def test_workspace_backup_carries_its_snapshot_not_the_installation(tmp_path):
    from scripts.backend_contract.infrastructure.productization import VerifyWorkspaceBackup
    from tests.test_product_integration_oracle_v1 import TOKEN as ORACLE_TOKEN, _reseal, http_request
    runtime = _runtime(tmp_path)
    try:
        _http(runtime, "PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": None, "payload": _profile()})
        _upload(runtime, "PRIMARY_LOGO", _png(), "logo.png", "image/png", None)
        _, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Backup com marca"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        status, _, backup = http_request(runtime.server, "POST", root + "/backup", value={}, headers={"X-Local-API-Token": ORACLE_TOKEN})
        assert status == 200
        verified = VerifyWorkspaceBackup().execute(backup)
        kinds = {item["artifact_kind"] for item in verified.artifact_revisions}
        assert {"WORKSPACE_SETTINGS_SNAPSHOT_V1", "EXPERT_MASTER_PROFILE_V1", "PRIVATE_CONTENT_ROLE_V1"} <= kinds
        assert not any("INSTALLATION" in kind for kind in kinds)
        package = json.loads(backup)
        snapshot = next(item for item in package["artifact_revisions"] if item["artifact_kind"] == "WORKSPACE_SETTINGS_SNAPSHOT_V1")
        snapshot["payload"]["assets"][0]["sha256"] = "f" * 64
        with pytest.raises(RepositoryIntegrityError, match="workspace settings asset"):
            VerifyWorkspaceBackup().execute(_reseal(package))
    finally:
        runtime.close()


def test_workspace_without_private_storage_keeps_legacy_behavior(tmp_path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from tests.test_product_integration_oracle_v1 import TOKEN as ORACLE_TOKEN
    runtime = build_local_api(tmp_path / "plain.sqlite3", token=ORACLE_TOKEN)
    runtime.start()
    try:
        status, workspace = _http(runtime, "POST", "/v1/workspaces", {"name": "Sem armazenamento privado"})
        assert status == 201
        assert _http(runtime, "GET", f"/v1/workspaces/{workspace['workspace_id']}/settings-snapshot")[0] == 503
    finally:
        runtime.close()


def _default_template_service(runtime, stored):
    from types import SimpleNamespace
    from scripts.backend_contract.application.delivery_foundation import StoreDefaultDeliveryTemplate
    from scripts.backend_contract.application.installation_settings import WorkspaceSettings
    from scripts.backend_contract.application.services import GetLatestArtifact, GetPrivateContent
    from tests.test_default_report_template_v1 import _report

    def store(**kwargs):
        stored.append(kwargs)
        return SimpleNamespace(**kwargs)

    settings = WorkspaceSettings(None, None, GetLatestArtifact(runtime._store.revisions), None, None, None, None)
    return StoreDefaultDeliveryTemplate(
        SimpleNamespace(execute=lambda _w: (None, _report())), SimpleNamespace(execute=store),
        settings, GetPrivateContent(runtime._store.workspaces, runtime._private_store),
    )


def test_default_template_follows_the_case_snapshot_and_custom_word_is_the_visual_authority(tmp_path):
    from io import BytesIO
    from zipfile import ZipFile
    from scripts.backend_contract.application.models import WorkspaceId
    from scripts.backend_contract.report_default_template import BRANDED_TEMPLATE_ID
    runtime = _runtime(tmp_path)
    try:
        _upload(runtime, "PRIMARY_LOGO", _png(), "logo.png", "image/png", None)
        _, branded = _http(runtime, "POST", "/v1/workspaces", {"name": "Com identidade"})
        stored = []
        service = _default_template_service(runtime, stored)
        _record, manifest = service.execute(WorkspaceId.parse(branded["workspace_id"]))
        assert manifest.template_id == BRANDED_TEMPLATE_ID
        with ZipFile(BytesIO(stored[-1]["content"])) as package:
            media = [name for name in package.namelist() if name.startswith("word/media/")]
            assert any(package.read(name) == _png() for name in media)
        # Modelo Word personalizado escolhido na instalacao: devolvido como capturado.
        custom = _custom_template(b"ESCRITORIO-SINTETICO-V1")
        docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        status, uploaded = _upload(runtime, "DEFAULT_WORD_TEMPLATE", custom, "modelo-escritorio.docx", docx, None)
        assert status == 201
        sha = uploaded["assets"]["DEFAULT_WORD_TEMPLATE"]["asset"]["sha256"]
        assert _http(runtime, "PUT", "/v1/installation/settings/DEFAULT_TEMPLATE_SELECTION_V1", {"expected_revision": None, "payload": {"mode": "CUSTOM", "template_sha256": sha}})[0] == 200
        _, chosen = _http(runtime, "POST", "/v1/workspaces", {"name": "Modelo do escritório"})
        before = len(stored)
        record, manifest = service.execute(WorkspaceId.parse(chosen["workspace_id"]))
        assert len(stored) == before, "the custom template is reused, never regenerated"
        assert manifest.template_id == "ESCRITORIO-SINTETICO-V1" and record.checksum_sha256 == sha
        assert [item.field for item in manifest.bindings] == ["EXPERT_FULL_NAME", "EXPERT_REGISTRATION", "REPORT_ID"]
    finally:
        runtime.close()


def _custom_template(template_id: bytes) -> bytes:
    from zipfile import ZipFile
    from tests.test_default_report_template_v1 import _report
    from scripts.backend_contract.report_default_template import DEFAULT_TEMPLATE_ID, default_report_template
    with ZipFile(BytesIO(default_report_template(_report().editorial_profile))) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    entries["docProps/custom.xml"] = entries["docProps/custom.xml"].replace(DEFAULT_TEMPLATE_ID.encode(), template_id)
    # Um modelo enviado vincula só nome, registro e identificação do laudo.
    for name, data in entries.items():
        if name.startswith("word/") and name.endswith(".xml"):
            entries[name] = data.replace(b"[[COURT]]", b"[[REPORT_ID]]").replace(b"[[PROCESS_NUMBER]]", "Escritório Sintético".encode()).replace(b"[[EXPERT_TITLE]]", b"Engenharia")
    output = BytesIO()
    with ZipFile(output, "w") as target:
        for name, data in entries.items():
            target.writestr(name, data)
    return output.getvalue()


def test_custom_selection_always_names_the_stored_template_so_case_creation_never_breaks(tmp_path):
    # Revisão do 2º conjunto, P1-3: trocar ou restaurar o modelo com o modo
    # personalizado ativo deixava a seleção apontando para outros bytes, e toda
    # perícia nova falhava com cópias de ativo órfãs.
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    runtime = _runtime(tmp_path)
    try:
        _, first = _upload(runtime, "DEFAULT_WORD_TEMPLATE", _custom_template(b"ESCRITORIO-A-V1"), "a.docx", docx, None)
        sha_a = first["assets"]["DEFAULT_WORD_TEMPLATE"]["asset"]["sha256"]
        assert _http(runtime, "PUT", "/v1/installation/settings/DEFAULT_TEMPLATE_SELECTION_V1", {"expected_revision": None, "payload": {"mode": "CUSTOM", "template_sha256": sha_a}})[0] == 200
        status, refused = _upload(runtime, "DEFAULT_WORD_TEMPLATE", _custom_template(b"ESCRITORIO-B-V1"), "b.docx", docx, 1)
        assert status == 409 and refused["error"]["code"] == "TEMPLATE_IN_USE"
        status, refused = _http(runtime, "POST", "/v1/installation/assets/DEFAULT_WORD_TEMPLATE/removal", {"expected_revision": 1})
        assert status == 409 and refused["error"]["code"] == "TEMPLATE_IN_USE"
        status, created = _http(runtime, "POST", "/v1/workspaces", {"name": "Modelo A"})
        assert status == 201, created
        # Com o modelo do produto escolhido, trocar é livre; restaurar a seleção
        # antiga (que cita A) é recusado, porque o modelo guardado agora é B.
        assert _http(runtime, "PUT", "/v1/installation/settings/DEFAULT_TEMPLATE_SELECTION_V1", {"expected_revision": 1, "payload": {"mode": "PRODUCT_DEFAULT", "template_sha256": None}})[0] == 200
        assert _upload(runtime, "DEFAULT_WORD_TEMPLATE", _custom_template(b"ESCRITORIO-B-V1"), "b.docx", docx, 1)[0] == 201
        status, _ = _http(runtime, "POST", "/v1/installation/settings/DEFAULT_TEMPLATE_SELECTION_V1/restore", {"revision": 1, "expected_revision": 2})
        assert status == 400
        _, overview = _http(runtime, "GET", "/v1/installation/settings")
        assert overview["readiness"]["template"] == "PRODUCT_DEFAULT"
        status, created = _http(runtime, "POST", "/v1/workspaces", {"name": "Modelo do produto"})
        assert status == 201, created
        # Restaurar o modelo A com a seleção CUSTOM(B) ativa também é recusado.
        sha_b = overview["assets"]["DEFAULT_WORD_TEMPLATE"]["asset"]["sha256"]
        assert _http(runtime, "PUT", "/v1/installation/settings/DEFAULT_TEMPLATE_SELECTION_V1", {"expected_revision": 2, "payload": {"mode": "CUSTOM", "template_sha256": sha_b}})[0] == 200
        status, refused = _http(runtime, "POST", "/v1/installation/settings/INSTALLATION_ASSET_V1/restore", {"revision": 1, "expected_revision": 2})
        assert status == 404  # ativos não têm restauração genérica pela rota de configurações
        from scripts.backend_contract.application.installation_settings import AssetRole, CustomTemplateInUse, InstallationSettings, SettingKind
        from scripts.backend_contract.local_api.composition import _SystemClock, _UuidGenerator
        service = InstallationSettings(runtime._installation_store, _SystemClock(), _UuidGenerator(), None)
        with pytest.raises(CustomTemplateInUse):
            service.restore(SettingKind.INSTALLATION_ASSET, 1, 2, setting_id=AssetRole.DEFAULT_WORD_TEMPLATE.value)
        _, overview = _http(runtime, "GET", "/v1/installation/settings")
        assert overview["settings"]["DEFAULT_TEMPLATE_SELECTION_V1"]["payload"]["template_sha256"] == overview["assets"]["DEFAULT_WORD_TEMPLATE"]["asset"]["sha256"]
    finally:
        runtime.close()


def test_test_document_uses_the_real_renderer_with_fictitious_data_and_writes_nothing(tmp_path):
    from io import BytesIO
    from zipfile import ZipFile
    from scripts.backend_contract.delivery_renderer import validate_final_artifact
    from tests.test_product_integration_oracle_v1 import TOKEN as ORACLE_TOKEN, http_request
    runtime = _runtime(tmp_path)
    try:
        _http(runtime, "PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": None, "payload": _profile()})
        _upload(runtime, "PRIMARY_LOGO", _png(), "logo.png", "image/png", None)
        before = _http(runtime, "GET", "/v1/installation/settings")[1]
        workspaces = _http(runtime, "GET", "/v1/workspaces")[1]
        status, headers, content = http_request(runtime.server, "GET", "/v1/installation/test-document", headers={"X-Local-API-Token": ORACLE_TOKEN})
        assert status == 200 and dict(headers)["Content-Type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        validate_final_artifact(content, "DOCX")
        with ZipFile(BytesIO(content)) as package:
            document = package.read("word/document.xml").decode("utf-8")
            header = package.read("word/header1.xml").decode("utf-8")
            assert any(package.read(name) == _png() for name in package.namelist() if name.startswith("word/media/"))
        assert "0000000-00.0000.0.00.0000" in document and "Vara fictícia" in document and "AUTORA FICTÍCIA UM" in document and "Perita Sintética" in header
        assert "e outros 1 (relação completa no item 1)" in document
        # Nada gravado: configurações e perícias iguais.
        assert _http(runtime, "GET", "/v1/installation/settings")[1] == before
        assert _http(runtime, "GET", "/v1/workspaces")[1] == workspaces
        assert http_request(runtime.server, "GET", "/v1/installation/test-document")[0] in (401, 403)
    finally:
        runtime.close()


def test_uploaded_template_must_bind_as_an_uploaded_template(tmp_path):
    # Um Word válido, mas com os campos do modelo do produto, era aceito e só
    # falhava na entrega.
    from zipfile import ZipFile
    from tests.test_default_report_template_v1 import _report
    from scripts.backend_contract.report_default_template import DEFAULT_TEMPLATE_ID, default_report_template
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with ZipFile(BytesIO(default_report_template(_report().editorial_profile))) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    entries["docProps/custom.xml"] = entries["docProps/custom.xml"].replace(DEFAULT_TEMPLATE_ID.encode(), b"ESCRITORIO-SINTETICO-V1")
    output = BytesIO()
    with ZipFile(output, "w") as target:
        for name, data in entries.items():
            target.writestr(name, data)
    runtime = _runtime(tmp_path)
    try:
        status, body = _upload(runtime, "DEFAULT_WORD_TEMPLATE", output.getvalue(), "produto.docx", docx, None)
        assert status == 422 and body["error"]["code"] == "ASSET_TEMPLATE_FIELDS"
        status, body = _upload(runtime, "DEFAULT_WORD_TEMPLATE", default_report_template(_report().editorial_profile), "v1.docx", docx, None)
        assert status == 422 and body["error"]["code"] == "ASSET_TEMPLATE_FIELDS", "the product identity is refused"
        assert _upload(runtime, "DEFAULT_WORD_TEMPLATE", _custom_template(b"ESCRITORIO-SINTETICO-V1"), "escritorio.docx", docx, None)[0] == 201
    finally:
        runtime.close()


def test_case_capture_reads_the_installation_in_one_snapshot(tmp_path):
    # Revisão do 2º conjunto, rodada 2, P2-c: seleção do modelo e ativos lidos
    # no mesmo estado; uma gravação concorrente espera o fim da captura.
    import threading
    store = SQLiteInstallationStore(tmp_path / "install.sqlite3")
    try:
        done = threading.Event()

        def write():
            store.append_if_latest(setting_kind="BRANDING_PROFILE_V1", setting_id="DEFAULT", revision_id=str(uuid4()), created_at="2026-10-02T12:00:00+00:00", payload={"a": 1}, expected_revision=None)
            done.set()

        with store.consistent_reads():
            writer = threading.Thread(target=write)
            writer.start()
            assert not done.wait(0.3), "a write must wait for the consistent read to end"
        writer.join(5)
        assert done.is_set()
    finally:
        store.close()
    from scripts.backend_contract.application import installation_settings as module
    entered = []

    class Spy:
        def consistent(self):
            from contextlib import contextmanager

            @contextmanager
            def reads():
                entered.append(True)
                yield
            return reads()

    from contextlib import nullcontext
    settings = module.WorkspaceSettings(Spy(), None, None, None, nullcontext, None, None)
    with pytest.raises(Exception):
        settings.seed("11111111-1111-4111-8111-111111111111")
    assert entered == [True], "seed enters the installation snapshot before reading it"
