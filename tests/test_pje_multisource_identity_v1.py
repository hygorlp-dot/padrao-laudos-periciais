"""Matriz adversarial de identidade logica multi-fonte (S-05 / S-06).

Regra absoluta em teste aqui:

    SOURCE_COLLECTION_ORDER != LOGICAL_DOCUMENT_IDENTITY

A identidade autoritativa de um documento logico e source-scoped e estavel:
`(workspace_id, storage_content_id, identidade local do documento no indice)`.
Nada que dependa da ORDEM em que as fontes foram coletadas pode ser autoridade,
porque essa ordem muda quando uma fonte e acrescentada, reimportada ou lida em
outra sessao -- e decisoes profissionais ficam penduradas nessa identidade.
"""
from __future__ import annotations

import json

from scripts.planejamento_pericial.app_composition import build_pericial_local_api
from tests.test_document_intake_v1 import provision_private_root
from tests.test_final_closure_r7 import pdf_sintetico
from tests.test_local_api_v1 import TOKEN, http_request


def _request(runtime, method, path, *, value=None, body=None, headers=None):
    status, _headers, raw = http_request(
        runtime.server, method, path, value=value, raw_body=body,
        headers={"X-Local-API-Token": TOKEN, **(headers or {})},
    )
    return status, json.loads(raw) if raw else None


def _distinct_pje_pdf(path, marker: str):
    """Export PJe sintetico distinguivel, mas com os MESMOS ids locais.

    A colisao so aparece se dois exports diferentes usarem `DOC-PJE-001`, que e
    exatamente o caso real: o ordinal e local ao indice de cada export.

    O texto alterado e o da pagina complementar, que nao participa do indice nem
    dos rodapes -- muda o sha256 (logo, a fonte fisica) sem produzir pendencia.
    """
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    pdf_sintetico(path)
    reader = PdfReader(str(path))
    writer = PdfWriter()
    for number, page in enumerate(reader.pages, 1):
        writer.add_page(page)
        if number != 3:
            continue
        fonte = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        added = writer.pages[-1]
        added[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(fonte)}),
        })
        stream = StreamObject()
        stream.set_data(
            f"BT /F1 10 Tf 40 730 Td (Pagina complementar {marker}) Tj ET".encode("ascii")
        )
        added[NameObject("/Contents")] = writer._add_object(stream)
    with open(path, "wb") as handle:
        writer.write(handle)
    return path


def _import(runtime, workspace_id, pdf, filename):
    status, material = _request(
        runtime, "POST", f"/v1/workspaces/{workspace_id}/materials", body=pdf.read_bytes(),
        headers={"Content-Type": "application/pdf", "X-Document-Filename": filename},
    )
    # 201 quando cria; 200 quando os bytes ja estavam no workspace (idempotente).
    assert status in {200, 201}, material
    return material


def _identities_by_source(runtime, workspace_id):
    """document_id do snapshot, agrupado pela fonte fisica que o originou."""
    status, analysis = _request(runtime, "GET", f"/v1/workspaces/{workspace_id}/case-analysis")
    if status == 404:
        status, analysis = _request(runtime, "POST", f"/v1/workspaces/{workspace_id}/case-analysis", value={})
    assert status in {200, 201}, analysis
    grouped: dict[str, list[str]] = {}
    for item in analysis["snapshot"]["documents"]:
        grouped.setdefault(item["storage_content_id"], []).append(item["document_id"])
    return grouped


def _workspace(runtime, name="Caso"):
    status, workspace = _request(runtime, "POST", "/v1/workspaces", value={"name": name})
    assert status == 201
    return workspace["workspace_id"]


def _runtime(tmp_path, name="product.sqlite3"):
    private = tmp_path / "private"
    if not private.exists():
        provision_private_root(private)
    runtime = build_pericial_local_api(tmp_path / name, private_root=private, token=TOKEN)
    runtime.start()
    return runtime


def test_A_import_order_does_not_change_logical_identity(tmp_path):
    """A identidade de cada fonte deriva SO dela mesma, em qualquer ordem.

    Comparar a string entre dois bancos nao seria oraculo: `content_id` e um
    surrogate atribuido no import, entao ela muda legitimamente. O que nao pode
    mudar e a REGRA -- a identidade de uma fonte tem de ser funcao apenas do
    proprio `content_id` e do identificador local, nunca da posicao na colecao.
    """
    from uuid import UUID

    a_pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    b_pdf = _distinct_pje_pdf(tmp_path / "b.pdf", "fonte-b")

    for label, order in (("a-depois-b", (a_pdf, b_pdf)), ("b-depois-a", (b_pdf, a_pdf))):
        runtime = _runtime(tmp_path, f"{label}.sqlite3")
        try:
            ws = _workspace(runtime)
            imported = [(pdf.name, _import(runtime, ws, pdf, pdf.name)) for pdf in order]
            grouped = _identities_by_source(runtime, ws)
            assert len(grouped) == len(imported), f"{label}: nem toda fonte foi reconhecida"
            for name, material in imported:
                own = UUID(material["content_id"]).hex.upper()
                identities = grouped[material["content_id"]]
                assert identities, f"{label}: {name} nao produziu documentos logicos"
                for identity in identities:
                    assert identity.endswith(own), (
                        f"{label}: a identidade {identity!r} de {name} nao deriva da propria fonte "
                        "-- depende da ordem de coleta"
                    )
        finally:
            runtime.close()


def test_B_adding_a_third_source_does_not_rename_the_existing_ones(tmp_path):
    a_pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    b_pdf = _distinct_pje_pdf(tmp_path / "b.pdf", "fonte-b")
    c_pdf = _distinct_pje_pdf(tmp_path / "c.pdf", "fonte-c")

    runtime = _runtime(tmp_path)
    try:
        ws = _workspace(runtime)
        a = _import(runtime, ws, a_pdf, "a.pdf")
        b = _import(runtime, ws, b_pdf, "b.pdf")
        before = _identities_by_source(runtime, ws)

        _import(runtime, ws, c_pdf, "c.pdf")
        after = _identities_by_source(runtime, ws)

        assert after[a["content_id"]] == before[a["content_id"]], "acrescentar C renomeou A"
        assert after[b["content_id"]] == before[b["content_id"]], "acrescentar C renomeou B"
    finally:
        runtime.close()


def test_F_two_sources_sharing_a_local_ordinal_do_not_collide(tmp_path):
    """Dois exports distintos usam `DOC-PJE-001`; o snapshot precisa distingui-los."""
    a_pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    b_pdf = _distinct_pje_pdf(tmp_path / "b.pdf", "fonte-b")

    runtime = _runtime(tmp_path)
    try:
        ws = _workspace(runtime)
        a = _import(runtime, ws, a_pdf, "a.pdf")
        b = _import(runtime, ws, b_pdf, "b.pdf")
        grouped = _identities_by_source(runtime, ws)
        every = [value for ids in grouped.values() for value in ids]
        assert len(every) == len(set(every)), f"identidades colidiram entre fontes: {every}"
        assert set(grouped) == {a["content_id"], b["content_id"]}
    finally:
        runtime.close()


def test_E_reimport_preserves_identity_and_the_professional_decision(tmp_path):
    a_pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    runtime = _runtime(tmp_path)
    try:
        ws = _workspace(runtime)
        a = _import(runtime, ws, a_pdf, "a.pdf")
        status, envelope = _request(runtime, "GET", f"/v1/workspaces/{ws}/pje-intake")
        assert status == 200
        intake = envelope["intakes"][0]
        excluded = intake["inventory"]["documents"][1]["document_id"]
        status, _ = _request(runtime, "POST", f"/v1/workspaces/{ws}/pje-intake/availability", value={
            "storage_content_id": a["content_id"], "document_id": excluded,
            "available": False, "expected_revision": intake["revision"],
        })
        assert status == 200
        before = _identities_by_source(runtime, ws)

        _import(runtime, ws, a_pdf, "a.pdf")
        status, envelope = _request(runtime, "GET", f"/v1/workspaces/{ws}/pje-intake")
        decided = {
            row["document_id"]: row["available"]
            for row in envelope["intakes"][0]["inventory"]["documents"]
        }
        assert decided[excluded] is False, "a exclusao profissional nao sobreviveu ao reimport"
        after = _identities_by_source(runtime, ws)
        assert after == before, "a identidade logica mudou apos reimportar a mesma fonte"
    finally:
        runtime.close()


def test_S05_identity_is_derived_from_the_source_not_from_its_position(tmp_path):
    """Oraculo deterministico: nao depende do sorteio de UUID nem da ordenacao.

    Um esquema posicional (`S1-`, `S2-`, indice na lista) pode passar por acaso
    quando a colecao esta ordenada de forma estavel. Esta assercao e estrutural:
    a identidade de cada documento tem de conter a fonte fisica de que ele veio.
    Nenhum esquema baseado em posicao satisfaz isso.
    """
    a_pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    b_pdf = _distinct_pje_pdf(tmp_path / "b.pdf", "fonte-b")

    runtime = _runtime(tmp_path)
    try:
        ws = _workspace(runtime)
        _import(runtime, ws, a_pdf, "a.pdf")
        _import(runtime, ws, b_pdf, "b.pdf")
        grouped = _identities_by_source(runtime, ws)
        assert grouped, "nenhuma fonte PJe foi reconhecida"
        for storage_content_id, identities in grouped.items():
            from uuid import UUID

            expected = UUID(storage_content_id).hex.upper()
            for identity in identities:
                assert identity.endswith(expected), (
                    f"a identidade {identity!r} nao nomeia a fonte {storage_content_id!r}: "
                    "identidade posicional nao e identidade"
                )
    finally:
        runtime.close()


def test_B_backup_restore_reopen_preserves_source_and_logical_identities(tmp_path):
    """Identidade e decisao profissional atravessam a fronteira de portabilidade."""
    from scripts.backend_contract.infrastructure.productization import (
        CreateWorkspaceBackup,
        RecoveryStaging,
        RestoreWorkspaceBackup,
    )
    from scripts.backend_contract.infrastructure.sqlite import SQLiteApplicationStore
    from scripts.backend_contract.application.models import WorkspaceId, thaw_payload
    from scripts.backend_contract.application.services import validate_pje_intake_payload
    from scripts.backend_contract.infrastructure.private_filesystem import LocalPrivateContentStore

    a_pdf = _distinct_pje_pdf(tmp_path / "a.pdf", "fonte-a")
    b_pdf = _distinct_pje_pdf(tmp_path / "b.pdf", "fonte-b")

    database = tmp_path / "product.sqlite3"
    private = tmp_path / "private"
    provision_private_root(private)
    runtime = build_pericial_local_api(database, private_root=private, token=TOKEN)
    runtime.start()
    try:
        ws = _workspace(runtime)
        a = _import(runtime, ws, a_pdf, "a.pdf")
        _import(runtime, ws, b_pdf, "b.pdf")
        status, envelope = _request(runtime, "GET", f"/v1/workspaces/{ws}/pje-intake")
        assert status == 200 and len(envelope["intakes"]) == 2
        target = next(i for i in envelope["intakes"] if i["inventory"]["storage_content_id"] == a["content_id"])
        excluded = target["inventory"]["documents"][1]["document_id"]
        status, _ = _request(runtime, "POST", f"/v1/workspaces/{ws}/pje-intake/availability", value={
            "storage_content_id": a["content_id"], "document_id": excluded,
            "available": False, "expected_revision": target["revision"],
        })
        assert status == 200
        before = _identities_by_source(runtime, ws)
    finally:
        runtime.close()

    class _Clock:
        def now(self):
            from datetime import UTC, datetime

            return datetime(2026, 9, 2, 12, 0, tzinfo=UTC)

    source_store = SQLiteApplicationStore(database)
    private_store = LocalPrivateContentStore(private)
    try:
        package = CreateWorkspaceBackup(
            source_store.workspaces, source_store.revisions, private_store, _Clock(), lambda _: None
        ).execute(WorkspaceId.parse(ws))
    finally:
        private_store.close()
        source_store.close()

    staging = RecoveryStaging.create(tmp_path / "restored")
    RestoreWorkspaceBackup(staging).execute(package)

    restored_inventories = {}
    for content_id in before:
        record = staging.revisions.latest(WorkspaceId.parse(ws), "PJE_INTAKE_V1", content_id)
        assert record is not None, f"inventario da fonte {content_id} nao sobreviveu ao restore"
        restored_inventories[content_id] = validate_pje_intake_payload(thaw_payload(record.payload))

    assert set(restored_inventories) == set(before), "uma fonte fisica se perdeu no restore"
    for content_id, inventory in restored_inventories.items():
        assert inventory["storage_content_id"] == content_id
        local_ids = [row["document_id"] for row in inventory["documents"]]
        expected = [_logical(content_id, local) for local in local_ids]
        assert sorted(expected) == sorted(before[content_id]), (
            f"identidades logicas de {content_id} mudaram na restauracao"
        )
    restored_a = restored_inventories[a["content_id"]]
    assert any(row["available"] is False for row in restored_a["documents"]), (
        "a exclusao profissional nao sobreviveu ao backup/restore"
    )


def _logical(content_id: str, local_id: str) -> str:
    from uuid import UUID

    return f"{local_id}-{UUID(content_id).hex.upper()}"
