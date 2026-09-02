"""SYSTEMIC_AUDITOR reproductions for HEAD d3250f2 (Issue #181). Throwaway."""

from __future__ import annotations

import json
from urllib.parse import quote


from tests.test_document_intake_v1 import (
    frontend_build,
    product_request,
    provision_private_root,
)
from tests.test_final_closure_r7 import pdf_sintetico
from tests.test_local_api_v1 import TOKEN, http_request


def _sole_intake(envelope):
    """Adapta ao formato multi-fonte mantendo a asserção do caso de fonte única.

    A rota passou a devolver {"intakes": [...]} porque um workspace pode ter mais
    de um export PJe (S-06). Onde o teste fala de UMA fonte, esta ajuda extrai a
    única e falha alto se houver mais — nenhuma asserção foi enfraquecida.
    """
    intakes = envelope["intakes"]
    assert len(intakes) == 1, f"esperava uma unica fonte PJe, ha {len(intakes)}"
    return intakes[0]


def _api(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
    )
    return status, json.loads(raw) if raw else None


# ---------------------------------------------------------------- A1: bridge route gap
def test_A1_product_bridge_never_exposes_pje_intake_routes(tmp_path):
    """The shipped product serves the frontend through ProductBridge.

    The frontend fetches /app-api/.../pje-intake. If the bridge does not
    allowlist it, the whole feature is invisible in the product.
    """
    from scripts.planejamento_pericial.app_composition import build_pericial_application

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_application(
        tmp_path / "product.sqlite3", frontend_build(tmp_path / "dist"),
        private_root=private, token=TOKEN,
    )
    runtime.start()
    try:
        status, _h, raw = product_request(
            runtime, "POST", "/app-api/v1/workspaces",
            body=json.dumps({"name": "Caso PJe"}).encode("utf-8"),
            headers={"Origin": runtime.origin, "Sec-Fetch-Site": "same-origin",
                     "Content-Type": "application/json"},
        )
        assert status == 201, raw
        workspace_id = json.loads(raw)["workspace_id"]

        pdf = tmp_path / "autos.pdf"
        pdf_sintetico(pdf)
        status, _h, raw = product_request(
            runtime, "POST", f"/app-api/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Origin": runtime.origin, "Sec-Fetch-Site": "same-origin",
                     "Content-Type": "application/pdf",
                     "X-Document-Filename": quote("autos.pdf", safe="-._~")},
        )
        assert status == 201, raw

        # The inventory demonstrably exists on the Local API behind the bridge.
        status, intake = _api(runtime._local_api, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        assert status == 200, intake

        get_status, _h, get_body = product_request(
            runtime, "GET", f"/app-api/v1/workspaces/{workspace_id}/pje-intake",
            headers={"Origin": runtime.origin, "Sec-Fetch-Site": "same-origin"},
        )
        post_status, _h, post_body = product_request(
            runtime, "POST", f"/app-api/v1/workspaces/{workspace_id}/pje-intake/availability",
            body=json.dumps({"storage_content_id": _sole_intake(intake)["inventory"]["storage_content_id"],
                             "document_id": _sole_intake(intake)["inventory"]["documents"][0]["document_id"],
                             "available": False, "expected_revision": _sole_intake(intake)["revision"]}).encode("utf-8"),
            headers={"Origin": runtime.origin, "Sec-Fetch-Site": "same-origin",
                     "Content-Type": "application/json"},
        )
        print("BRIDGE GET ->", get_status, get_body[:200])
        print("BRIDGE POST ->", post_status, post_body[:200])
        assert get_status == 200, f"pje-intake unreachable through the product bridge: {get_status}"
        assert post_status == 200, f"availability unreachable through the product bridge: {post_status}"
    finally:
        runtime.close()


# ---------------------------------------------------------- A2: legacy composition root
def test_A2_legacy_entrypoint_still_composes_without_pje(tmp_path):
    """`python -m scripts.backend_contract.product_bridge` still exists and has no port."""
    from scripts.backend_contract.product_bridge.composition import build_product_runtime

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_product_runtime(
        tmp_path / "legacy.sqlite3", frontend_build(tmp_path / "dist"),
        private_root=private, token=TOKEN,
    )
    runtime.start()
    try:
        status, workspace = _api(runtime._local_api, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        pdf = tmp_path / "autos.pdf"
        pdf_sintetico(pdf)
        status, material = _api(
            runtime._local_api, "POST", f"/v1/workspaces/{workspace_id}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"},
        )
        assert status == 201, material
        # Asserção estreitada em relação à do auditor, deliberadamente.
        #
        # A original exigia que esta composição produzisse a decomposição PJe.
        # Isso é impossível por construção: sem o leitor de PJe injetado, nada
        # aqui pode saber que estes bytes são um export do PJe -- e a arquitetura
        # proíbe BACKEND de conhecer a ingestão, que foi justamente a decisão que
        # originou a inversão de dependência.
        #
        # O que é exigível, e é o dano real que o S-03 aponta, é que a ausência
        # da capacidade seja VISÍVEL. Antes, a rota respondia 404, que o frontend
        # lê como "este processo não tem PJe" -- indistinguível de "esta
        # instalação não lê PJe". Agora responde 503 PJE_INTAKE_UNAVAILABLE.
        status, intake = _api(runtime._local_api, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        print("LEGACY ENTRYPOINT pje-intake ->", status, intake)
        assert status == 503 and intake["error"]["code"] == "PJE_INTAKE_UNAVAILABLE", (
            "uma composição sem a porta precisa declarar a capacidade ausente, "
            "e não responder 404 como se o processo não tivesse PJe"
        )
    finally:
        runtime.close()


# ---------------------------------------------------------- A3: schema migration path
def test_A3_older_persisted_inventory_without_document_id_still_loads():
    from scripts.backend_contract.application.services import validate_pje_intake_payload

    older = {
        "schema_version": "1.0.0",
        "workspace_id": "00000000-0000-4000-8000-000000000001",
        "storage_content_id": "00000000-0000-4000-8000-000000000002",
        "source_sha256": "a" * 64,
        "instance_label": "1a VARA",
        "documents": [{
            "document_id": "DOC-PJE-001", "id_pje": "900001", "title": "Peticao",
            "raw_type": "Peticao", "normalized_type": "PETICAO",
            "page_start": 1, "page_end": 2, "available": True,
        }],
        # Shape written before this HEAD added `document_id`, same schema_version.
        "party_rows": [{
            "name": "Fulano", "role": "AUTOR", "pole": "ACTIVE",
            "representative_name": "Adv", "representative_role": "ADVOGADO",
            "page": 1, "occurrence": "linha",
        }],
    }
    validate_pje_intake_payload(older)


# ------------------------------------------------------- A4: idempotency blast radius
def test_A4_idempotent_reimport_does_not_break_material_count_contracts(tmp_path):
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / "p.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        blob = b"%PDF-1.7\ngenerico\n%%EOF\n"
        status_a, first = _api(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=blob,
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "a.pdf"},
        )
        status_b, second = _api(
            runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=blob,
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "OUTRO-NOME.pdf"},
        )
        print("first", status_a, first)
        print("second", status_b, second)
        _s, listed = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        print("listed", len(listed["items"]), [i["original_filename"] for i in listed["items"]])
        assert second["original_filename"] == "OUTRO-NOME.pdf", \
            "second import returned the FIRST material's filename under a 201 Created"
    finally:
        runtime.close()


# ---------------------------------------------- A5: temp dir leaves private bytes outside store
def test_A5_adapter_temp_dir_holds_private_case_bytes(tmp_path, monkeypatch):
    import tempfile as _tempfile

    observed = []
    original = _tempfile.TemporaryDirectory

    class Watching(original):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            observed.append(self.name)

    monkeypatch.setattr(_tempfile, "TemporaryDirectory", Watching)

    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / "p.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        pdf = tmp_path / "autos.pdf"
        pdf_sintetico(pdf)
        _api(
            runtime, "POST", f"/v1/workspaces/{workspace['workspace_id']}/materials",
            body=pdf.read_bytes(),
            headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"},
        )
    finally:
        runtime.close()
    print("TEMP DIRS USED:", observed)
    assert not observed, f"private case bytes were materialized outside the private store: {observed}"


# ------------------------------------------ A6: second PJe export, positional identity leak
def _pdf_sintetico_variante(caminho, ids=("900011", "900012"),
                            titulos=("Laudo administrativo previo", "Sentenca sintetica"),
                            tipos=("PETICAO", "DECISAO")):
    """Same structure as tests.test_final_closure_r7.pdf_sintetico, different content."""
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    w = PdfWriter()

    def pagina(comandos):
        p = w.add_blank_page(width=612, height=792)
        fonte = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                  NameObject("/Subtype"): NameObject("/Type1"),
                                  NameObject("/BaseFont"): NameObject("/Helvetica")})
        p[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(fonte)})})
        s = StreamObject(); s.set_data(comandos.encode("ascii"))
        p[NameObject("/Contents")] = w._add_object(s)

    linhas = " ".join(f"{x} 650 m {x} 740 l S" for x in (40, 140, 260, 480, 570)) + \
        " 40 650 m 570 650 l S 40 680 m 570 680 l S 40 710 m 570 710 l S 40 740 m 570 740 l S"
    textos = ("BT /F1 10 Tf 45 720 Td (ID) Tj 100 0 Td (Data) Tj 120 0 Td (Titulo) Tj 220 0 Td (Tipo) Tj ET "
              f"BT /F1 10 Tf 45 690 Td ({ids[0]}) Tj 100 0 Td (03/02/2026) Tj 120 0 Td ({titulos[0]}) Tj 220 0 Td ({tipos[0]}) Tj ET "
              f"BT /F1 10 Tf 45 660 Td ({ids[1]}) Tj 100 0 Td (04/02/2026) Tj 120 0 Td ({titulos[1]}) Tj 220 0 Td ({tipos[1]}) Tj ET")
    pagina(linhas + textos + " BT /F1 10 Tf 40 760 Td (Processo 0000009-00.2026.4.00.0009) Tj ET")
    pagina("BT /F1 10 Tf 40 730 Td (Outro processo, outro conteudo, outra fonte documental.) Tj 0 -20 Td "
           "(O objeto da pericia e o imovel e o objetivo da pericia e determinar a causa.) Tj 0 -20 Td (QUESITOS:) Tj 0 -20 Td "
           f"(1. Existe umidade na parede?) Tj 0 -630 Td (Num. {ids[0]} - Pag. 1) Tj ET")
    pagina("BT /F1 10 Tf 40 730 Td (Pagina complementar sem rodape e sem link) Tj ET")
    pagina("BT /F1 10 Tf 40 730 Td (SENTENCA: julgo procedente para verificar infiltracao e determinar a causa.) Tj 0 -20 Td "
           "(O objeto da pericia e o imovel e o objetivo da pericia e sanear a controversia.) Tj 0 -650 Td "
           f"(Num. {ids[1]} - Pag. 1) Tj ET")
    with open(caminho, "wb") as arquivo:
        w.write(arquivo)
    return caminho


def test_A6_second_pje_export_inherits_a_decision_taken_about_another_source(tmp_path):
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / "p.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]

        first_pdf = tmp_path / "autos-a.pdf"; pdf_sintetico(first_pdf)
        _s, mat_a = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
                         body=first_pdf.read_bytes(),
                         headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos-a.pdf"})
        _s, intake = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        print("A inventory:", [(d["document_id"], d["id_pje"], d["title"]) for d in _sole_intake(intake)["inventory"]["documents"]])
        excluded = _sole_intake(intake)["inventory"]["documents"][1]["document_id"]
        _s, intake = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability",
                          value={"storage_content_id": _sole_intake(intake)["inventory"]["storage_content_id"],
                                 "document_id": excluded, "available": False,
                                 "expected_revision": _sole_intake(intake)["revision"]})

        second_pdf = tmp_path / "autos-b.pdf"; _pdf_sintetico_variante(second_pdf)
        status, mat_b = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
                             body=second_pdf.read_bytes(),
                             headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos-b.pdf"})
        print("second PJe import ->", status, mat_b)
        assert mat_b["content_id"] != mat_a["content_id"]

        _s, after = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        print("B inventory:", [(d["document_id"], d["id_pje"], d["title"], d["available"])
                               for d in _sole_intake(after)["inventory"]["documents"]])
        print("bound to:", _sole_intake(after)["inventory"]["storage_content_id"], "b=", mat_b["content_id"], "a=", mat_a["content_id"])
        leaked = [d for d in _sole_intake(after)["inventory"]["documents"] if not d["available"]]
        assert not leaked, f"decision about source A leaked onto source B by positional id: {leaked}"
    finally:
        runtime.close()


def test_A7_second_pje_export_does_not_silently_erase_the_first_decomposition(tmp_path):
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / "p.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        a = tmp_path / "a.pdf"; pdf_sintetico(a)
        b = tmp_path / "b.pdf"; _pdf_sintetico_variante(b)
        _s, mat_a = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=a.read_bytes(),
                         headers={"Content-Type": "application/pdf", "X-Document-Filename": "a.pdf"})
        _s, mat_b = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=b.read_bytes(),
                         headers={"Content-Type": "application/pdf", "X-Document-Filename": "b.pdf"})
        status, analysis = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
        print("case-analysis ->", status)
        docs = [(d["document_id"], d["storage_content_id"], d["raw_type"], d["page_count_or_span"])
                for d in analysis["snapshot"]["documents"]]
        for row in docs:
            print("  ", row)
        by_storage = {}
        for d in analysis["snapshot"]["documents"]:
            by_storage.setdefault(d["storage_content_id"], []).append(d["document_id"])
        assert len(by_storage.get(mat_a["content_id"], [])) >= 2, \
            f"first PJe export lost its logical decomposition: {by_storage}"
    finally:
        runtime.close()


# ------------------------------- A8: availability decided AFTER bootstrap never reaches analysis
def test_A8_availability_change_after_bootstrap_reaches_case_analysis_or_signals_staleness(tmp_path):
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / "p.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        pdf = tmp_path / "autos.pdf"; pdf_sintetico(pdf)
        _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
             headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})

        status, analysis = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
        assert status == 201
        print("bootstrap coverage:", analysis["snapshot"]["coverage"])

        _s, intake = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        target = _sole_intake(intake)["inventory"]["documents"][1]["document_id"]
        status, intake = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/pje-intake/availability",
                              value={"storage_content_id": _sole_intake(intake)["inventory"]["storage_content_id"],
                                     "document_id": target, "available": False,
                                     "expected_revision": _sole_intake(intake)["revision"]})
        print("availability toggle after bootstrap ->", status)
        assert status == 200

        status, after = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        snap = after["snapshot"]
        print("post-toggle coverage:", snap["coverage"])
        print("post-toggle stale flag:", snap["source_inventory_stale"], "stale ids:", snap.get("stale_document_ids"))
        print("post-toggle availability:", [(d["document_id"], d["content_available"]) for d in snap["documents"]])
        # A identidade no snapshot e qualificada pela fonte (S-05); o id do
        # inventario e local. Casar pelo prefixo local preserva a assercao.
        excluded = next(d for d in snap["documents"] if d["document_id"].startswith(f"{target}-"))
        assert excluded["content_available"] is False or snap["source_inventory_stale"] is True, (
            "the perito excluded a document and Case Analysis neither reflects it nor flags staleness"
        )
    finally:
        runtime.close()


# ------- A9: portability boundary does not verify PJE_INTAKE_V1 private source authority
def test_A9_resealed_backup_missing_the_pje_source_is_rejected(tmp_path):
    """The same threat model the repo already blocks for the three sibling kinds."""
    import hashlib

    from scripts.backend_contract.application.models import (
        PericiaWorkspace, PrivateContentId, PrivateContentMetadata, PrivateContentOrigin, WorkspaceId,
    )
    from scripts.backend_contract.application.ports import RepositoryIntegrityError
    from scripts.backend_contract.infrastructure.private_filesystem import LocalPrivateContentStore
    from scripts.backend_contract.infrastructure.productization import (
        CreateWorkspaceBackup, RecoveryStaging, RestoreWorkspaceBackup, VerifyWorkspaceBackup,
    )
    from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
    from tests.test_productization_foundation_v1 import reseal_backup
    from datetime import UTC, datetime

    class Clock:
        def now(self):
            return datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    workspace_uuid = "11111111-1111-4111-8111-111111111111"
    content_uuid = "22222222-2222-4222-8222-222222222222"
    store = SQLiteApplicationStore(tmp_path / "source.sqlite3")
    workspace_id = WorkspaceId.parse(workspace_uuid)
    store.workspaces.create(PericiaWorkspace(workspace_id, "Caso", "2026-08-31T12:00:00+00:00"))

    provision_private_root(tmp_path / "private")
    private = LocalPrivateContentStore(tmp_path / "private")
    body = b"%PDF-1.7\nfonte-privada\n%%EOF\n"
    digest = hashlib.sha256(body).hexdigest()
    private.store(PrivateContentMetadata(
        workspace_id, PrivateContentId.parse(content_uuid), "autos.pdf", len(body), digest,
        "application/pdf", "2026-08-31T12:00:00+00:00", PrivateContentOrigin.LOCAL_IMPORT,
    ), body)

    store.revisions.append(
        workspace_id=workspace_id, artifact_kind="PJE_INTAKE_V1", artifact_id="PJE-INTAKE",
        revision_id="33333333-3333-4333-8333-333333333333", created_at="2026-08-31T12:00:00+00:00",
        payload={
            "schema_version": "1.0.0", "workspace_id": workspace_uuid,
            "storage_content_id": content_uuid, "source_sha256": digest,
            "instance_label": "Vara", "party_rows": [],
            "documents": [{"document_id": "DOC-PJE-001", "id_pje": "900001", "title": "Peticao",
                           "raw_type": "PETICAO", "normalized_type": "PETICAO_INICIAL",
                           "page_start": 1, "page_end": 2, "available": True}],
        },
    )

    package = CreateWorkspaceBackup(store.workspaces, store.revisions, private, Clock(), lambda _: None).execute(workspace_id)
    VerifyWorkspaceBackup().execute(package)

    tampered = json.loads(package)
    tampered["private_contents"] = [i for i in tampered["private_contents"] if i["content_id"] != content_uuid]
    resealed = reseal_backup(tampered)

    try:
        VerifyWorkspaceBackup().execute(resealed)
        rejected = False
    except RepositoryIntegrityError as exc:
        rejected = True
        print("verify rejected:", exc)
    if not rejected:
        staging = RecoveryStaging.create(tmp_path / "staging")
        receipt = RestoreWorkspaceBackup(staging).execute(resealed)
        print("RESTORED a PJe inventory with NO private source:", receipt)
        restored = staging.revisions.latest(workspace_id, "PJE_INTAKE_V1", "PJE-INTAKE")
        print("dangling storage_content_id:", restored.payload["storage_content_id"])
        staging.close()
    store.close(); private.close()
    assert rejected, "resealed backup missing the PJe source passed the portability boundary"


# --- A10: a material imported without the port can never acquire an inventory afterwards
def test_A10_material_imported_without_the_port_can_still_gain_its_inventory(tmp_path):
    """Legacy entrypoint (A2) + idempotent re-import (this HEAD) = permanent dead end."""
    from scripts.backend_contract.local_api.composition import build_local_api
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / "private"
    provision_private_root(private)
    db = tmp_path / "p.sqlite3"
    pdf = tmp_path / "autos.pdf"; pdf_sintetico(pdf)

    # Session 1: started the old way (no PJe port).
    legacy = build_local_api(db, private_root=private, token=TOKEN)
    legacy.start()
    try:
        _s, workspace = _api(legacy, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        status, _m = _api(legacy, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
                          headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        assert status == 201
        status, _i = _api(legacy, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        print("legacy session inventory ->", status)
    finally:
        legacy.close()

    # Session 2: started the new way. The perito re-imports the SAME file to get PJe.
    fixed = build_pericial_local_api(db, private_root=private, token=TOKEN)
    fixed.start()
    try:
        status, again = _api(fixed, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
                             headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        print("re-import on the fixed runtime ->", status, again["content_id"])
        status, intake = _api(fixed, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        print("inventory after re-import ->", status, intake)
        assert status == 200, "the PJe inventory can never be produced for this material"
    finally:
        fixed.close()


# --- A11: an inventory this build cannot validate bricks Case Analysis with no repair path
def test_A11_unvalidatable_stored_inventory_does_not_brick_case_analysis(tmp_path):
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api
    from scripts.backend_contract.application.models import WorkspaceId
    from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore

    private = tmp_path / "private"; provision_private_root(private)
    db = tmp_path / "p.sqlite3"
    runtime = build_pericial_local_api(db, private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        _s, mat = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
                       body=b"%PDF-1.7\ngenerico\n%%EOF\n",
                       headers={"Content-Type": "application/pdf", "X-Document-Filename": "g.pdf"})
    finally:
        runtime.close()

    # An inventory persisted by a build one commit older: party_rows had no document_id.
    store = SQLiteApplicationStore(db)
    store.revisions.append(
        workspace_id=WorkspaceId.parse(workspace_id), artifact_kind="PJE_INTAKE_V1",
        artifact_id="PJE-INTAKE", revision_id="44444444-4444-4444-8444-444444444444",
        created_at="2026-08-31T12:00:00+00:00",
        payload={"schema_version": "1.0.0", "workspace_id": workspace_id,
                 "storage_content_id": mat["content_id"], "source_sha256": mat["checksum_sha256"],
                 "instance_label": "Vara",
                 "documents": [{"document_id": "DOC-PJE-001", "id_pje": "900001", "title": "P",
                                "raw_type": "PETICAO", "normalized_type": "PETICAO_INICIAL",
                                "page_start": 1, "page_end": 2, "available": True}],
                 "party_rows": [{"name": "MARIA", "role": "AUTORA", "pole": "ACTIVE",
                                 "representative_name": "JOAO", "representative_role": "ADVOGADO",
                                 "page": 1, "occurrence": "linha"}]},
    )
    store.close()

    reopened = build_pericial_local_api(db, private_root=private, token=TOKEN)
    reopened.start()
    try:
        s1, b1 = _api(reopened, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        s2, b2 = _api(reopened, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
        s3, b3 = _api(reopened, "GET", f"/v1/workspaces/{workspace_id}/materials")
        print("GET pje-intake  ->", s1, b1)
        print("POST case-analysis ->", s2, b2)
        print("GET materials   ->", s3, (b3 or {}).get("items") and len(b3["items"]))
        assert s2 < 500, "a legacy-shaped inventory makes Case Analysis a permanent server error"
    finally:
        reopened.close()


# --- A12: judicial domain silently drops parties the strict grammar could not parse
def test_A12_unparsed_party_lines_are_diagnosed_not_silently_dropped():
    from scripts.backend_contract.application.pje_party_table import parse_pje_party_table

    page = (
        "PARTES PROCURADOR\n"
        "POLO ATIVO: MARIA DA SILVA (AUTORA) JOAO ADVOGADO (ADVOGADO)\n"
        "POLO PASSIVO: CONSTRUTORA XYZ LTDA (REQUERIDA) ANA PROCURADORA (PROCURADOR)\n"
        "POLO PASSIVO: PEDRO SEM ADVOGADO (REQUERIDO)\n"
        "POLO PASSIVO: UNIAO (REQUERIDA) DEFENSORIA PUBLICA (DEFENSOR)\n"
    )
    result = parse_pje_party_table(page)
    print("final_state:", result.final_state, "rows:", len(result.rows))
    import inspect
    from scripts.backend_contract.application import services
    body = inspect.getsource(services._pje_inventory_payload)
    print("consumer inspects final_state?", "final_state" in body)
    assert "final_state" in body, (
        "the parser reports it gave up mid-table and the inventory builder ignores it; "
        f"{len(result.rows)} of 4 party lines reach the judicial domain with no gap recorded"
    )


# --- A13: backup -> restore -> reopen identity exactness for a real PJe workspace
def test_A13_pje_workspace_backup_restore_reopen_is_identity_exact(tmp_path):
    from datetime import UTC, datetime

    from scripts.backend_contract.application.models import WorkspaceId
    from scripts.backend_contract.infrastructure.private_filesystem import LocalPrivateContentStore
    from scripts.backend_contract.infrastructure.productization import (
        CreateWorkspaceBackup, RecoveryStaging, RestoreWorkspaceBackup, VerifyWorkspaceBackup,
    )
    from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    class Clock:
        def now(self):
            return datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    private = tmp_path / "private"; provision_private_root(private)
    db = tmp_path / "p.sqlite3"
    runtime = build_pericial_local_api(db, private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso PJe"})
        workspace_id = workspace["workspace_id"]
        pdf = tmp_path / "autos.pdf"; pdf_sintetico(pdf)
        _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
             headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
        _s, before_intake = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        _s, before_case = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
    finally:
        runtime.close()

    store = SQLiteApplicationStore(db)
    priv = LocalPrivateContentStore(private)
    wid = WorkspaceId.parse(workspace_id)
    package = CreateWorkspaceBackup(store.workspaces, store.revisions, priv, Clock(), lambda _: None).execute(wid)
    VerifyWorkspaceBackup().execute(package)
    source_history = store.revisions.list_workspace(wid)
    store.close(); priv.close()

    staging = RecoveryStaging.create(tmp_path / "staging")
    receipt = RestoreWorkspaceBackup(staging).execute(package)
    print("receipt:", receipt)
    assert staging.revisions.list_workspace(wid) == source_history, "restored history is not identity-exact"
    staging.close()

    reopened = build_pericial_local_api(tmp_path / "staging" / "workspace.sqlite3"
                                        if (tmp_path / "staging" / "workspace.sqlite3").exists()
                                        else db, private_root=private, token=TOKEN)
    reopened.start()
    try:
        _s, after_intake = _api(reopened, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        _s, after_case = _api(reopened, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
        assert after_intake == before_intake
        assert after_case == before_case
        print("reopen identity: EXACT")
    finally:
        reopened.close()


def _pje_with_unresolved_index_item(caminho, n_docs=3, footers=(True, False, True)):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject
    w = PdfWriter()
    def pagina(cmd):
        p = w.add_blank_page(width=612, height=792)
        f = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        p[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(f)})})
        s = StreamObject(); s.set_data(cmd.encode("ascii")); p[NameObject("/Contents")] = w._add_object(s)
    top, rowh = 740, 30
    ys = [top - rowh * i for i in range(n_docs + 2)]
    vl = " ".join(f"{x} {ys[-1]} m {x} {top} l S" for x in (40, 140, 260, 480, 570))
    hl = " ".join(f"40 {y} m 570 {y} l S" for y in ys)
    txt = f"BT /F1 10 Tf 45 {top-20} Td (ID) Tj 100 0 Td (Data) Tj 120 0 Td (Titulo) Tj 220 0 Td (Tipo) Tj ET "
    for i in range(n_docs):
        idp = 900001 + i; y = top - 20 - rowh * (i + 1)
        txt += f"BT /F1 10 Tf 45 {y} Td ({idp}) Tj 100 0 Td (0{(i%9)+1}/01/2026) Tj 120 0 Td (Documento numero {i+1}) Tj 220 0 Td ({'PETICAO' if i%2==0 else 'DECISAO'}) Tj ET "
    pagina(vl + " " + hl + " " + txt + " BT /F1 10 Tf 40 770 Td (Processo 0000001-00.2026.4.00.0001) Tj ET")
    for i in range(n_docs):
        foot = f" 0 -650 Td (Num. {900001+i} - Pag. 1) Tj" if footers[i] else ""
        pagina(f"BT /F1 10 Tf 40 730 Td (Conteudo do documento {i+1} sobre infiltracao.) Tj{foot} ET")
    with open(caminho, "wb") as fh:
        w.write(fh)
    return caminho


# --- A14: an ordinary PJe export with one unresolved index item can no longer be imported
def test_A14_pje_export_with_a_pendencia_can_still_be_stored_as_material(tmp_path):
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    private = tmp_path / "private"; provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / "p.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        pdf = _pje_with_unresolved_index_item(tmp_path / "autos.pdf")
        status, payload = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials",
                               body=pdf.read_bytes(),
                               headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        print("import of a PJe export with one unresolved index item ->", status, payload)
        _s, listed = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        print("materials after ->", len(listed["items"]))
        assert status == 201, "the perito can no longer even store this PJe export as a material"
    finally:
        runtime.close()


# --- A15: the failed import is not atomic and the retry silently loses PJe forever
def test_A15_failed_pje_import_is_atomic_and_retryable(tmp_path):
    from scripts.backend_contract.local_api.composition import build_local_api
    from scripts.planejamento_pericial.app_composition import build_pericial_local_api

    pdf = _pje_with_unresolved_index_item(tmp_path / "autos.pdf")

    # Baseline: the same bytes through a composition WITHOUT the port (== BASE behaviour).
    base_private = tmp_path / "base-private"; provision_private_root(base_private)
    base = build_local_api(tmp_path / "base.sqlite3", private_root=base_private, token=TOKEN)
    base.start()
    try:
        _s, w = _api(base, "POST", "/v1/workspaces", value={"name": "Caso"})
        status, _p = _api(base, "POST", f"/v1/workspaces/{w['workspace_id']}/materials", body=pdf.read_bytes(),
                          headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        print("BASE-equivalent import ->", status)
    finally:
        base.close()

    private = tmp_path / "private"; provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / "p.sqlite3", private_root=private, token=TOKEN)
    runtime.start()
    try:
        _s, workspace = _api(runtime, "POST", "/v1/workspaces", value={"name": "Caso"})
        workspace_id = workspace["workspace_id"]
        s1, _p1 = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
                       headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        _s, listed = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/materials")
        print("first attempt ->", s1, "| materials left behind:", len(listed["items"]))
        s2, p2 = _api(runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
                      headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        s3, i3 = _api(runtime, "GET", f"/v1/workspaces/{workspace_id}/pje-intake")
        print("retry ->", s2, "| pje-intake after retry ->", s3)
        assert not (s1 >= 500 and listed["items"]), "a rejected import left the material stored anyway"
    finally:
        runtime.close()
