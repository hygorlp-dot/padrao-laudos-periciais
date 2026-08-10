import json
import unittest
from pathlib import Path

from scripts.extracao_pje.detectar_rodape_pje import detectar_rodape
from scripts.extracao_pje.normalizar_id_pje import normalizar_id_pje
from scripts.extracao_pje.reconciliar_indice import reconciliar_documento
from scripts.extracao_pje.segmentar_documentos import segmentar_documentos
from scripts.extracao_pje.validar_integridade import validar_integridade


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "pje_parser" / "casos.json").read_text(encoding="utf-8"))


def pagina(numero, ident=None, interna=None):
    return {"pagina_pdf": numero, "possui_rodape_pje": ident is not None, "id_pje_detectado": ident,
            "pagina_documento_detectada": interna, "requer_ocr": False, "quantidade_caracteres": 10}


class ParserPjeTest(unittest.TestCase):
    def test_rodape_valido_e_ausente(self):
        for caso in FIXTURE["rodapes"]:
            resultado = detectar_rodape(caso["texto"], 7)
            self.assertEqual(resultado["id_pje"] if resultado else None, caso["id"])
            self.assertEqual(resultado["pagina_documento"] if resultado else None, caso["pagina"])

    def test_id_fragmentado(self):
        caso = FIXTURE["id_fragmentado"]
        resultado = normalizar_id_pje(caso["valor"])
        self.assertEqual(resultado["valor_normalizado"], caso["normalizado"])
        self.assertEqual(resultado["metodo"], caso["metodo"])

    def test_mudanca_id_e_link_presente(self):
        itens = [{"id_pje": "10", "ordem_indice": 1, "pagina_destino_link": 2},
                 {"id_pje": "20", "ordem_indice": 2, "pagina_destino_link": 4}]
        paginas = [pagina(1), pagina(2, "10", 1), pagina(3, "10", 2), pagina(4, "20", 1)]
        docs = segmentar_documentos(itens, paginas)
        self.assertEqual([(d["id_pje"], d["total_paginas"]) for d in docs], [("10", 2), ("20", 1)])

    def test_hyperlink_ausente_usa_rodape(self):
        item = {"id_pje": "10", "ordem_indice": 1, "pagina_destino_link": None}
        docs = segmentar_documentos([item], [pagina(1), pagina(2, "10", 1)])
        self.assertEqual(docs[0]["pagina_pdf_inicio"], 2)

    def test_reconciliacao_confirmada_e_conflitante(self):
        base = {"pagina_pdf_inicio": 2, "pagina_pdf_fim": 3, "item_indice": {"id_pje": "10", "pagina_destino_link": 2}}
        self.assertEqual(reconciliar_documento({**base, "id_rodape": "10"})["status"], "CONFIRMADO")
        self.assertEqual(reconciliar_documento({**base, "id_rodape": "11"})["status"], "CONFLITANTE")

    def test_integridade_detecta_total_e_salto(self):
        rec = {"status": "CONFIRMADO", "id_indice": "10", "id_rodape": "10"}
        doc = {"documento_id": "DOC-PJE-001", "pagina_pdf_inicio": 2, "pagina_pdf_fim": 3,
               "total_paginas": 99, "status_reconciliacao": rec}
        manifesto = {"documentos": [doc], "indice": {"itens": [{}], "paginas": [1]},
                     "paginas": [pagina(1), pagina(2, "10", 1), pagina(3, "10", 3)], "conflitos": [],
                     "processo": {"numero_cnj": {"proveniencia": {"pagina_pdf": 1}}},
                     "metricas_extracao": {"documentos_segmentados": 1, "documentos_indice": 1,
                     "documentos_confirmados": 1, "paginas_com_rodape": 2, "paginas_candidatas_ocr": 0, "conflitos_abertos": 0}}
        erros, _ = validar_integridade(manifesto)
        self.assertTrue(any("total" in e for e in erros))
        self.assertTrue(any("salto" in e for e in erros))


if __name__ == "__main__":
    unittest.main()
