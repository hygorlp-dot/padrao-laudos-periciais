"""#266: prova operacional com um export PJe sintetico realista (grande e misto).

O Human RC encontrou o defeito com um export de ~20 MB, ~246 paginas, texto e
imagem misturados e OCR em parte das paginas. Este teste gera um export
equivalente (nenhum dado real; nada e versionado alem do gerador), importa pelo
Product Bridge com o timeout de transporte do produto (30 s) e o leitor PJe e o
OCR locais de producao, e exige:

- nenhuma resposta de falha terminal sobre a fonte aceita;
- a resposta chega antes do timeout de transporte;
- a derivacao termina READY, com o inventario PJe ligado a fonte exata.

No runner de referencia a derivacao deste export passa de 30 s: exatamente o
caso que antes virava "Armazenamento local indisponivel".
"""
from __future__ import annotations

import json
import random
import time
from io import BytesIO

from scripts.backend_contract.product_bridge.composition import build_product_runtime
from scripts.triagem_pericial.pje_intake_adapter import PjeIntakeAdapter
from tests.test_product_bridge_v1 import browser_mutation_headers, frontend_build, request

TOKEN = "r" * 43
TRANSPORT_TIMEOUT_SECONDS = 30.0


def realistic_pje_export(path, *, pages=240, seed=266):
    """Export PJe sintetico: indice + documentos com rodape `Num. X - Pag. N`.

    O documento 900002 se estende por `pages` paginas, metade imagem (exige OCR)
    e metade texto nativo; o rodape de toda pagina e texto nativo, como no PJe.
    """
    from PIL import Image, ImageDraw, ImageFont
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, StreamObject

    from tests.test_final_closure_r7 import pdf_sintetico

    base = path.with_suffix(".base.pdf")
    pdf_sintetico(base)
    writer = PdfWriter()
    for page in PdfReader(str(base)).pages:
        writer.add_page(page)
    base.unlink()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    rnd = random.Random(seed)
    pil_font = ImageFont.load_default()
    for number in range(2, pages + 2):
        footer = f"BT /F1 10 Tf 40 40 Td (Num. 900002 - Pag. {number}) Tj ET"
        stream = StreamObject()
        if number % 2:
            image = Image.new("L", (1240, 1754), 255)
            draw = ImageDraw.Draw(image)
            for line in range(40):
                words = "".join(rnd.choice("abcdefghij ") for _ in range(50))
                draw.text((80, 120 + line * 38), f"Laudo anexo pagina {number} linha {line} {words}", fill=0, font=pil_font)
            buffer = BytesIO()
            image.save(buffer, format="PDF", resolution=150)
            page = writer.add_page(PdfReader(BytesIO(buffer.getvalue())).pages[0])
            page[NameObject("/Resources")][NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
            stream.set_data(("q " + footer + " Q").encode("ascii"))
            contents = page[NameObject("/Contents")]
            reference = getattr(contents, "indirect_reference", None) or contents
            page[NameObject("/Contents")] = ArrayObject([reference, writer._add_object(stream)])
        else:
            page = writer.add_blank_page(width=612, height=792)
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream.set_data((f"BT /F1 10 Tf 40 730 Td (Continuacao da decisao sintetica, pagina {number}.) Tj ET " + footer).encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as sink:
        writer.write(sink)
    return path


def test_realistic_large_mixed_pje_export_is_accepted_and_ready_without_false_failure(tmp_path):
    content = realistic_pje_export(tmp_path / "autos-realistas.pdf").read_bytes()
    assert len(content) > 10 * 1024 * 1024
    runtime = build_product_runtime(
        tmp_path / "product.db", frontend_build(tmp_path), token=TOKEN,
        private_root=tmp_path / "private", pje_intake=PjeIntakeAdapter(),
    )
    runtime.start()
    try:
        status, _, body = request(runtime, "POST", "/app-api/v1/workspaces", headers=browser_mutation_headers(runtime), body={"name": "Export realista"})
        workspace_id = json.loads(body)["workspace_id"]
        root = f"/app-api/v1/workspaces/{workspace_id}"
        began = time.monotonic()
        status, _, body = request(
            runtime, "POST", root + "/materials",
            headers={**browser_mutation_headers(runtime), "Content-Type": "application/pdf", "X-Document-Filename": "autos-realistas.pdf"},
            raw_body=content,
        )
        answered = time.monotonic() - began
        import_status = status
        assert import_status in {201, 202}, (import_status, body[:200])
        assert answered < TRANSPORT_TIMEOUT_SECONDS, answered
        material = json.loads(body)
        deadline = time.monotonic() + 600
        while True:
            _s, _, raw = request(runtime, "GET", root + "/material-processing")
            state = json.loads(raw)["items"][0]["state"]
            if state != "PROCESSING":
                break
            assert time.monotonic() < deadline, "derivacao do export realista nao terminou"
            time.sleep(0.5)
        assert state == "READY", state
        status, _, raw = request(runtime, "GET", root + "/pje-intake")
        inventory = json.loads(raw)["intakes"][0]["inventory"]
        assert status == 200 and inventory["status"] == "OK"
        assert inventory["storage_content_id"] == material["content_id"]
        assert inventory["source_sha256"] == material["checksum_sha256"]
        assert [document["page_end"] for document in inventory["documents"]][-1] == 244
        print(f"REALISTIC_INGESTION answered={answered:.1f}s total={time.monotonic() - began:.1f}s import_status={import_status}")
    finally:
        runtime.close()
