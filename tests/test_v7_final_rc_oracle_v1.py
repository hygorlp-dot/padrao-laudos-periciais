"""V7-6: oraculo pre-RC sobre o processo real do produto (Issue #256).

Sobe o produto pelo mesmo comando do Human RC (`app_composition`) como processo do
sistema operacional, opera so pela superficie HTTP do navegador (`/app-api`, com os
cabecalhos de mesma origem), encerra o processo a forca e o inicia de novo sobre o
mesmo armazenamento. Cobre os casos adversariais da V7:

- F8: PDF de apoio a entrega nao altera o inventario de fontes do caso;
- F7: mudanca na Analise -> plano V1 stale -> plano V2; vistoria V1 stale ->
  vistoria V2 com reaproveitamento so por escolha do perito; cadeia tecnica stale
  -> sucessora vazia;
- exclusao/reabilitacao de peca PJe sem reescrever historico;
- isolamento entre workspaces;
- reinicio real do processo com o mesmo estado autoritativo;
- backup -> verify (e, no Windows, staging -> promote -> reabertura em processo novo).

O caminho feliz completo (processo, imovel, constatacoes, PAT, laudo, Word, entrega,
orcamento) continua provado pelo oraculo longitudinal
(tests/test_product_integration_oracle_v1.py) no mesmo SHA.
"""
from __future__ import annotations

import http.client
import json
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
_ORIGIN = re.compile(r"Sistema Pericial disponível em (http://127\.0\.0\.1:(\d+))/")


class _Product:
    """O produto como processo real, iniciado pelo comando documentado do Human RC."""

    def __init__(self, database: Path, private: Path, frontend: Path, *, module="scripts.planejamento_pericial.app_composition", extra=()):
        arguments = ["--database", str(database), "--frontend", str(frontend), "--private-root", str(private)]
        if module == "scripts.planejamento_pericial.app_composition":
            arguments += ["--port", "0"]
        self.process = subprocess.Popen(
            [sys.executable, "-m", module, *arguments, *extra],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=lambda: [lines.put(line) for line in self.process.stdout], daemon=True).start()
        output = []
        while True:
            try:
                line = lines.get(timeout=60)
            except queue.Empty:
                self.kill()
                raise AssertionError("o produto nao anunciou a origem local: " + "".join(output)) from None
            output.append(line)
            match = _ORIGIN.search(line)
            if match:
                self.origin, self.port = match.group(1), int(match.group(2))
                return

    def kill(self) -> None:
        # Encerramento real e abrupto: nenhum fechamento cooperativo do runtime.
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=30)

    def call(self, method: str, path: str, value=None, *, raw: bytes | None = None, headers: dict | None = None):
        body = raw if raw is not None else (json.dumps(value).encode("utf-8") if value is not None else None)
        sent = {"Origin": self.origin, "Sec-Fetch-Site": "same-origin", **(headers or {})}
        if value is not None and raw is None:
            sent["Content-Type"] = "application/json; charset=utf-8"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        try:
            connection.request(method, "/app-api" + path, body=body, headers=sent)
            response = connection.getresponse()
            data = response.read()
            content_type = response.getheader("Content-Type", "")
        finally:
            connection.close()
        if content_type.startswith("application/json") and data:
            return response.status, json.loads(data)
        return response.status, data


def _start(tmp_path: Path, name: str, **launch) -> _Product:
    from tests.test_document_intake_v1 import provision_private_root
    from tests.test_product_bridge_v1 import frontend_build

    private = tmp_path / f"{name}-private"
    if not private.exists():
        provision_private_root(private)
    frontend = tmp_path / f"{name}-frontend" / "dist"
    if not frontend.exists():
        frontend_build(tmp_path / f"{name}-frontend")
    return _Product(tmp_path / f"{name}.sqlite3", private, frontend, **launch)


def _state(product: _Product, workspace: str) -> dict:
    root = f"/v1/workspaces/{workspace}"
    state = {}
    for name in ("materials", "material-processing", "case-analysis", "pericial-planning", "inspection-session", "technical-snapshot", "pje-intake"):
        status, value = product.call("GET", f"{root}/{name}")
        state[name] = (status, value)
    return state


def test_v7_adversarial_oracle_through_the_real_product_process(tmp_path):
    from tests.test_photo_library_v1 import jpeg
    from tests.test_pje_multisource_identity_v1 import _distinct_pje_pdf
    from tests.test_property_record_v1 import _text_pdf

    product = _start(tmp_path, "product")
    try:
        status, a = product.call("POST", "/v1/workspaces", {"name": "Oráculo V7 sintético"})
        status, b = product.call("POST", "/v1/workspaces", {"name": "Workspace sentinela"})
        assert status == 201 and a["workspace_id"] != b["workspace_id"]
        root = f"/v1/workspaces/{a['workspace_id']}"
        sentinel_before = _state(product, b["workspace_id"])
        profile = json.loads((ROOT / "tests/fixtures/report-snapshot-v1.json").read_text(encoding="utf-8"))["expert_profile"]
        assert product.call("PUT", root + "/expert-profile", {"expected_revision": None, "profile": profile})[0] == 200
        quesitos = _text_pdf(["QUESITOS DA PARTE AUTORA", "01) A parede apresenta umidade?", "", "2. Qual a extensão?"])
        status, material = product.call("POST", root + "/materials", raw=quesitos, headers={"Content-Type": "application/pdf", "X-Document-Filename": "quesitos.pdf"})
        assert status == 201
        assert product.call("POST", root + "/case-analysis", {})[0] == 201
        status, proposed = product.call("GET", root + "/case-analysis/intake")
        first, second = proposed["questions"][:2]

        def accept(proposal):
            status, current = product.call("GET", root + "/case-analysis")
            status, case = product.call("POST", root + "/case-analysis/questions", {"selections": [{"proposal_id": proposal["proposal_id"], "origin": proposal["source"]["origin"]}], "expected_revision": current["revision"]})
            assert status == 200, case
            return case

        case = accept(first)
        for item in case["snapshot"]["questions"]:
            status, case = product.call("POST", root + "/case-analysis/reviews", {"expected_revision": case["revision"], "target_item_id": item["item_id"], "action": "CONFIRM", "corrected_value": None, "reviewer": profile["profile_id"], "reason": "Fonte sintética conferida."})
            assert status == 200

        def approve_all(plan):
            for name in ("issues", "inspection_requirements", "question_links"):
                for item in plan["snapshot"][name]:
                    status, plan = product.call("POST", root + "/pericial-planning/decisions", {"expected_revision": plan["revision"], "target_item_id": item["item_id"], "action": "APPROVE", "reviewer": profile["profile_id"], "reason": "Confirmado.", "decided_value": None})
                    assert status == 200, plan
            return plan

        status, plan = product.call("POST", root + "/pericial-planning", {"title": "Plano V1"})
        assert status == 201
        plan_v1 = approve_all(plan)
        status, inspection = product.call("POST", root + "/inspection-session", {"responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
        assert status == 201
        photo = jpeg()
        status, stored = product.call("POST", root + "/inspection-photos", raw=photo, headers={"Content-Type": "image/jpeg", "X-Document-Filename": "parede.jpg"})
        assert status == 201
        snapshot = json.loads(json.dumps(inspection["snapshot"]))
        item = snapshot["items"][0]
        location = snapshot["locations"][0]["location_id"]
        snapshot["observations"].append({"observation_id": "OBSERVATION-ORACLE", "inspection_item_id": item["item_id"], "observation_type": "DIRECT_OBSERVATION", "raw_observation": "Mancha de umidade.", "location_id": location, "timestamp": "2026-09-20T09:30:00-03:00", "operator": profile["profile_id"], "provenance": "Campo sintético."})
        item["observation_ids"] = ["OBSERVATION-ORACLE"]
        status, inspection_v1 = product.call("PUT", root + "/inspection-session", {"expected_revision": inspection["revision"], "snapshot": snapshot})
        assert status == 200, inspection_v1
        status, technical_v1 = product.call("POST", root + "/technical-snapshot", {})
        assert status == 201, technical_v1

        # F8: anexo PDF de apoio a entrega nao e fonte do caso.
        status, materials_before = product.call("GET", root + "/materials")
        status, case_before = product.call("GET", root + "/case-analysis")
        support = _text_pdf(["ANEXO DE APOIO", "Planilha sintética."])
        assert product.call("POST", root + "/delivery-supporting-files", raw=support, headers={"Content-Type": "application/pdf", "X-Document-Filename": "apoio.pdf"})[0] == 201
        status, materials_after = product.call("GET", root + "/materials")
        status, case_after = product.call("GET", root + "/case-analysis")
        assert materials_after == materials_before
        assert case_after["snapshot"]["source_inventory_stale"] is False
        assert case_after["snapshot"]["documents"] == case_before["snapshot"]["documents"]

        # F7: a Analise muda depois da vistoria; plano e vistoria tem sucessores explicitos.
        accept(second)
        status, stale_plan = product.call("GET", root + "/pericial-planning")
        assert stale_plan["snapshot"]["upstream_stale"] is True
        status, plan_v2 = product.call("POST", root + "/pericial-planning/successor", {"expected_revision": stale_plan["revision"], "title": "Plano V2"})
        assert status == 201 and plan_v2["snapshot"]["decisions"] == []
        approve_all(plan_v2)
        status, stale_inspection = product.call("GET", root + "/inspection-session")
        assert stale_inspection["snapshot"]["upstream_stale"] is True
        status, inspection_v2 = product.call("POST", root + "/inspection-session/successor", {"expected_revision": stale_inspection["revision"], "responsible_professional": profile["profile_id"], "location_context": "Imóvel sintético", "participant_references": []})
        assert status == 201 and inspection_v2["snapshot"]["observations"] == []
        status, offered = product.call("GET", root + "/inspection-session/reuse-candidates")
        assert [item["source_record_id"] for item in offered["candidates"]] == ["OBSERVATION-ORACLE"]
        status, reused = product.call("POST", root + "/inspection-session/reuse", {"expected_revision": inspection_v2["revision"], "selections": [{key: offered["candidates"][0][key] for key in ("source_session_id", "source_record_id", "target_item_id")}]})
        assert status == 200 and all(item["state"] == "PENDING" for item in reused["snapshot"]["items"])
        # A cadeia tecnica iniciada sobre a vistoria anterior tambem tem sucessora explicita.
        status, stale_technical = product.call("GET", root + "/technical-snapshot")
        assert stale_technical["snapshot"]["upstream_stale"] is True
        status, technical_v2 = product.call("POST", root + "/technical-snapshot/successor", {"expected_revision": stale_technical["revision"]})
        assert status == 200 and technical_v2["snapshot"]["upstream_stale"] is False, technical_v2
        assert technical_v2["snapshot"]["snapshot_id"] != technical_v1["snapshot"]["snapshot_id"]
        assert technical_v2["snapshot"]["source_snapshot"]["inspection_session_id"] == reused["snapshot"]["session_id"]

        # Exclusao e reabilitacao de peca PJe em outro workspace.
        status, c = product.call("POST", "/v1/workspaces", {"name": "PJe sintético"})
        pje_root = f"/v1/workspaces/{c['workspace_id']}"
        pdf = _distinct_pje_pdf(tmp_path / "autos.pdf", "oraculo-v7")
        status, autos = product.call("POST", pje_root + "/materials", raw=pdf.read_bytes(), headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        assert status == 201
        # #266: fonte aceita e derivacao concluida tem estado explicito READY.
        assert product.call("GET", pje_root + "/material-processing") == (200, {"items": [{"content_id": autos["content_id"], "state": "READY"}]})
        assert product.call("POST", pje_root + "/case-analysis", {})[0] == 201

        def availability(available):
            status, intake = product.call("GET", pje_root + "/pje-intake")
            current = next(item for item in intake["intakes"] if item["inventory"]["storage_content_id"] == autos["content_id"])
            status, result = product.call("POST", pje_root + "/pje-intake/availability", {"storage_content_id": autos["content_id"], "document_id": "DOC-PJE-002", "available": available, "expected_revision": current["revision"]})
            assert status == 200, result
            status, analysis = product.call("GET", pje_root + "/case-analysis")
            return next(d for d in analysis["snapshot"]["documents"] if d["document_id"].startswith("DOC-PJE-002-"))

        excluded = availability(False)
        assert excluded["content_available"] is False
        restored = availability(True)
        assert restored["content_available"] is True

        # Isolamento: nada do que aconteceu em A ou C tocou o sentinela B.
        assert _state(product, b["workspace_id"]) == sentinel_before

        before_restart = {name: _state(product, workspace) for name, workspace in (("a", a["workspace_id"]), ("c", c["workspace_id"]))}
        status, backup = product.call("POST", root + "/backup", raw=b"", headers={"Content-Type": "application/json"})
        assert status == 200 and isinstance(backup, bytes) and backup
    finally:
        product.kill()

    # Reinicio real: processo novo sobre o mesmo armazenamento.
    product = _start(tmp_path, "product")
    try:
        after_restart = {name: _state(product, workspace) for name, workspace in (("a", a["workspace_id"]), ("c", c["workspace_id"]))}
        assert after_restart == before_restart
        assert after_restart["a"]["inspection-session"][1]["snapshot"]["reuse_decisions"] == reused["snapshot"]["reuse_decisions"]
        assert plan_v1["snapshot"]["plan"]["plan_id"] != after_restart["a"]["pericial-planning"][1]["snapshot"]["plan"]["plan_id"]
        status, verified = product.call("POST", "/v1/recovery/verify", raw=backup, headers={"Content-Type": "application/octet-stream"})
        assert status == 200 and verified["workspace_id"] == a["workspace_id"], verified
    finally:
        product.kill()

    if os.name != "nt":
        pytest.skip("staging/promote de recovery mutavel e suportado somente no Windows; verify ja provado acima")

    # Recovery em instalacao nova: staging -> promocao explicita -> reabertura.
    recovered = _start(tmp_path, "recovered")
    try:
        status, staged = recovered.call("POST", "/v1/recovery/staging", raw=backup, headers={"Content-Type": "application/octet-stream"})
        assert status == 201 and staged["promotable"] is True, staged
        status, promoted = recovered.call("POST", f"/v1/recovery/{staged['recovery_id']}/promote", {"confirm": True})
        assert status == 200 and promoted["workspace_id"] == a["workspace_id"], promoted
    finally:
        recovered.kill()
    recovered = _start(tmp_path, "recovered")
    try:
        reopened = _state(recovered, a["workspace_id"])
        for name in ("case-analysis", "pericial-planning", "inspection-session", "technical-snapshot"):
            assert reopened[name] == before_restart["a"][name], name
    finally:
        recovered.kill()


def test_realistic_document_ingestion_lifecycle_survives_a_real_kill_mid_processing(tmp_path):
    """REALISTIC_DOCUMENT_INGESTION_LIFECYCLE (#266) sobre processos reais.

    O export PJe e aceito por um produto cuja leitura PJe esta retida (mesma
    composicao, adaptador de producao atras de um portao), o processo e MORTO no
    meio da derivacao e o produto normal (`app_composition`) reabre o mesmo
    armazenamento: a fonte existe, nunca aparece como pronta, a analise nao a conta
    como lida, e a nova tentativa explicita conclui sem segunda fonte.
    """
    import time

    from tests.test_pje_multisource_identity_v1 import _distinct_pje_pdf

    gate = tmp_path / "gate-never-opened"
    pdf = _distinct_pje_pdf(tmp_path / "autos-grandes.pdf", "oraculo-266").read_bytes()
    gated = _start(tmp_path, "ingest", module="tests.gated_product_launcher", extra=("--gate", str(gate)))
    try:
        status, workspace = gated.call("POST", "/v1/workspaces", {"name": "Ingestão interrompida"})
        root = f"/v1/workspaces/{workspace['workspace_id']}"
        status, material = gated.call("POST", root + "/materials", raw=pdf, headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        assert status == 202, material
        assert gated.call("GET", root + "/material-processing")[1]["items"] == [{"content_id": material["content_id"], "state": "PROCESSING"}]
        assert gated.call("GET", root + "/materials")[1]["items"][0]["checksum_sha256"] == material["checksum_sha256"]
    finally:
        gated.kill()

    product = _start(tmp_path, "ingest")
    try:
        assert product.call("GET", root + "/material-processing")[1]["items"] == [{"content_id": material["content_id"], "state": "INTERRUPTED"}]
        assert product.call("GET", root + "/pje-intake")[0] == 404
        status, analysis = product.call("POST", root + "/case-analysis", {})
        assert status == 201 and analysis["snapshot"]["coverage"]["status"] != "COMPLETE", analysis
        status, retried = product.call("POST", root + f"/material-processing/{material['content_id']}", {})
        assert status in {200, 202}, retried
        deadline = time.monotonic() + 120
        while product.call("GET", root + "/material-processing")[1]["items"][0]["state"] != "READY":
            assert time.monotonic() < deadline, "a nova tentativa nao concluiu"
            time.sleep(0.2)
        status, intake = product.call("GET", root + "/pje-intake")
        inventory = intake["intakes"][0]["inventory"]
        assert inventory["storage_content_id"] == material["content_id"]
        assert inventory["source_sha256"] == material["checksum_sha256"]
        # Reimportar os mesmos bytes nao cria segunda fonte.
        status, again = product.call("POST", root + "/materials", raw=pdf, headers={"Content-Type": "application/pdf", "X-Document-Filename": "autos.pdf"})
        assert status == 200 and again["content_id"] == material["content_id"]
        assert len(product.call("GET", root + "/materials")[1]["items"]) == 1
        ready = _state(product, workspace["workspace_id"])
    finally:
        product.kill()

    # Pronto sobrevive a outro reinicio real com o mesmo estado.
    product = _start(tmp_path, "ingest")
    try:
        assert _state(product, workspace["workspace_id"]) == ready
    finally:
        product.kill()



def test_round3_oracle_settings_branding_participants_and_property_through_the_real_process(tmp_path):
    """Human RC Round 3: o que a rodada nova testa, pelo processo real do produto.

    GLOBAL_SETTINGS, GLOBAL_ASSETS, WORKSPACE_SETTINGS_SNAPSHOT (padrão novo não
    reescreve perícia antiga), BRANDING_WORD / WATERMARK_WORD / HEADER_FOOTER_WORD
    pelo documento de teste, MULTI_PARTICIPANT_PROCESS / OTHER_PARTICIPANT /
    REPRESENTATIVE_LINKS pela capa PJe, PROPERTY_CONTEXT_EXTRACTION sem endereço
    de parte, RESTART e BACKUP com o snapshot da perícia.
    """
    from io import BytesIO
    from zipfile import ZipFile
    from PIL import Image
    from tests.test_process_participants_v1 import _HEADER, _cover
    from tests.test_property_record_v1 import _text_pdf

    def png(color):
        buffer = BytesIO()
        Image.new("RGBA", (240, 80), color).save(buffer, "PNG")
        return buffer.getvalue()

    def upload(product, role, content, expected):
        return product.call("POST", f"/v1/installation/assets/{role}", raw=content, headers={"Content-Type": "image/png", "X-Document-Filename": f"{role.lower()}.png", "X-Expected-Revision": expected})

    product = _start(tmp_path, "round3")
    try:
        profile = {
            "profile_id": "EXPERT-PROFILE-001", "revision": 1, "full_name": "Perita Sintética Round 3", "professional_title": "Engenheira civil",
            "registration": "CREA-PE 000000", "court_registration": "TRF5 — 001", "contact_line": "perita@exemplo.invalid",
            "court_registrations": [{"court": "TRF5", "registration": "001", "label": "Perita do juízo", "active": True, "legacy": False}],
            "contact": {"email": "perita@exemplo.invalid", "phone": None, "office_name": None, "city": "Recife", "state": "PE"},
        }
        status, overview = product.call("PUT", "/v1/installation/settings/EXPERT_PROFILE_DEFAULT_V1", {"expected_revision": None, "payload": profile})
        assert status == 200 and overview["readiness"]["expert_profile"] == "CONFIGURED"
        assert upload(product, "PRIMARY_LOGO", png((31, 58, 77, 255)), "none")[0] == 201
        assert upload(product, "WATERMARK", png((31, 58, 77, 255)), "none")[0] == 201
        presentation = overview["settings"]["DOCUMENT_PRESENTATION_PROFILE_V1"]["payload"]
        presentation["watermark"] = {**presentation["watermark"], "enabled": True, "kind": "IMAGE", "opacity": 0.08}
        assert product.call("PUT", "/v1/installation/settings/DOCUMENT_PRESENTATION_PROFILE_V1", {"expected_revision": None, "payload": presentation})[0] == 200

        # Documento de teste: Word real, com logotipo, imagem de página e "Página X de Y".
        status, document = product.call("GET", "/v1/installation/test-document")
        assert status == 200 and isinstance(document, bytes)
        with ZipFile(BytesIO(document)) as package:
            header = package.read("word/header1.xml").decode("utf-8")
            footer = package.read("word/footer1.xml").decode("utf-8")
            assert 'behindDoc="1"' in header and "Perita Sintética Round 3" in header
            assert "Página " in footer and "NUMPAGES" in footer
            assert sum(name.startswith("word/media/") for name in package.namelist()) >= 2

        status, a = product.call("POST", "/v1/workspaces", {"name": "Round 3 A"})
        assert status == 201
        root = f"/v1/workspaces/{a['workspace_id']}"
        status, settings_a = product.call("GET", root + "/settings-snapshot")
        assert status == 200 and {item["role"] for item in settings_a["snapshot"]["assets"]} == {"PRIMARY_LOGO", "WATERMARK"}
        # O padrão global muda depois: a perícia A continua com o que capturou.
        assert upload(product, "PRIMARY_LOGO", png((150, 20, 20, 255)), "1")[0] == 201
        status, again = product.call("GET", root + "/settings-snapshot")
        assert again["snapshot"] == settings_a["snapshot"] and again["differences"]["settings_changes"] == ["ASSET:PRIMARY_LOGO"]

        # Participantes: várias partes por polo, outro participante e procuradores vinculados.
        cover = _cover([
            _HEADER, "POLO ATIVO", "AUTORA SINTETICA UM (AUTORA) ADVOGADA SINTETICA (ADVOGADA)", "AUTOR SINTETICO DOIS (AUTOR)",
            "POLO PASSIVO", "BANCO SINTETICO S.A. (REU) PROCURADOR SINTETICO (PROCURADOR)", "CONSTRUTORA SINTETICA LTDA (REU)",
            "OUTROS PARTICIPANTES", "MUNICIPIO SINTETICO (TERCEIRO INTERESSADO)",
        ])
        assert product.call("POST", root + "/materials", raw=cover, headers={"Content-Type": "application/pdf", "X-Document-Filename": "capa.pdf"})[0] == 201
        status, process = product.call("GET", root + "/process-case")
        data = {**process["data"], "numero_processo": "0000000-00.2026.4.05.0000", "vara": "1ª Vara Federal Sintética"}
        assert product.call("POST", root + "/process-case", {"expected_revision": process["revision"], "data": data})[0] in (200, 201)
        status, view = product.call("GET", root + "/process-participants")
        assert status == 200 and view["interrupted_pages"] == []
        assert [(p["pole"], p["name"]) for p in view["proposals"]] == [
            ("ACTIVE", "AUTORA SINTETICA UM"), ("ACTIVE", "AUTOR SINTETICO DOIS"),
            ("PASSIVE", "BANCO SINTETICO S.A."), ("PASSIVE", "CONSTRUTORA SINTETICA LTDA"), ("OTHER", "MUNICIPIO SINTETICO"),
        ]
        assert [r["name"] for r in view["proposals"][0]["representatives"]] == ["ADVOGADA SINTETICA"]
        assert view["proposals"][3]["representatives"] == []
        revision = None
        for proposal in view["proposals"]:
            status, view = product.call("POST", root + "/process-participants/decisions", {"action": "CONFIRM", "expected_revision": revision, "payload": {"proposal_id": proposal["participant_id"]}})
            assert status == 200, view
            revision = view["revision"]
        assert len([p for p in view["participants"] if p["review_state"] == "CONFIRMED"]) == 5

        # Imóvel: o endereço do imóvel objeto é proposto; o da parte, nunca.
        petition = _text_pdf([
            "FULANA SINTETICA, residente e domiciliada na Av. Rua da Parte Sintetica, nº 45, Bairro Centro Sintetico.",
            "A autora adquiriu o imóvel objeto da ação, situado na Rua do Imovel Sintetico, nº 120.",
        ])
        assert product.call("POST", root + "/materials", raw=petition, headers={"Content-Type": "application/pdf", "X-Document-Filename": "inicial.pdf"})[0] == 201
        status, found = product.call("GET", root + "/property-record/proposals")
        values = {(p["field"], p["value"]) for p in found["proposals"]}
        assert ("street", "Rua do Imovel Sintetico") in values
        assert not any("Parte" in value for field, value in values if field == "street")

        before = {name: product.call("GET", f"{root}/{name}") for name in ("process-participants", "settings-snapshot")}
        status, backup = product.call("POST", root + "/backup", raw=b"", headers={"Content-Type": "application/json"})
        assert status == 200 and isinstance(backup, bytes) and backup
    finally:
        product.kill()

    product = _start(tmp_path, "round3")
    try:
        after = {name: product.call("GET", f"{root}/{name}") for name in ("process-participants", "settings-snapshot")}
        assert after == before
        status, verified = product.call("POST", "/v1/recovery/verify", raw=backup, headers={"Content-Type": "application/octet-stream"})
        assert status == 200 and verified["workspace_id"] == a["workspace_id"], verified
    finally:
        product.kill()
