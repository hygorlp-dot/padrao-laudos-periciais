import json
import unittest
from pathlib import Path

from scripts.extracao_pje.catalogar_imagens import catalogar_imagens
from scripts.extracao_pje.classificar_documentos import classificar_documento
from scripts.extracao_pje.detectar_secoes_internas import criar_subdocumentos, detectar_secoes
from scripts.extracao_pje.extrair_blocos_texto import extrair_pagina_e_blocos
from scripts.extracao_pje.extrair_tabelas_documento import extrair_tabelas
from scripts.extracao_pje.validar_documento import validar_documento

RAIZ = Path(__file__).resolve().parents[1]
CASOS = json.loads((RAIZ / "tests/fixtures/pje_documentos/casos-classificacao.json").read_text(encoding="utf-8"))
CONTEXTO = {"arquivo": "processo-ficticio.pdf", "sha256": "0" * 64, "documento_id": "DOC-PJE-001", "id_pje": "900001"}


class TabelaFalsa:
    bbox = (10, 20, 100, 80)
    def extract(self): return [["Item", "Valor"], ["A", "1"]]


class PaginaFalsa:
    width, height = 600, 800
    images = [{"x0": 10, "top": 10, "x1": 310, "bottom": 410}]
    def extract_text(self): return "Foto 1\nTabela de orçamento"
    def extract_words(self, **_): return [{"text":"Foto","x0":10,"top":415,"x1":50,"bottom":430},{"text":"1","x0":55,"top":415,"x1":65,"bottom":430}]
    def find_tables(self): return [TabelaFalsa()]


class LeitorFalso:
    def pagina_geometrica(self, _): return PaginaFalsa()


class DocumentoPjeTest(unittest.TestCase):
    def test_classes_exatas_e_outro(self):
        for caso in CASOS:
            with self.subTest(caso=caso["titulo"]):
                resultado = classificar_documento(caso["titulo"], caso["tipo"])
                self.assertEqual(resultado["classe_normalizada"], caso["classe"])
        laudo = classificar_documento("LAUDO PERICIAL", "Laudo")
        self.assertEqual(laudo["status_revisao"], "PENDENTE_REVISAO")
        self.assertEqual(laudo["confianca_classificacao"]["nivel"], "BAIXA")

    def test_parecer_com_crea_e_documento_composto(self):
        secoes = [{"tipo_normalizado": "RELATORIO_FOTOGRAFICO"}, {"tipo_normalizado": "ORCAMENTO"}]
        resultado = classificar_documento("Parecer técnico", "Documento", "Responsável CREA 0000", secoes)
        self.assertEqual(resultado["classe_normalizada"], "PARECER_TECNICO_PARTE")
        self.assertEqual(resultado["subclasse_normalizada"], "DOCUMENTO_COMPOSTO")
        self.assertEqual(resultado["status_revisao"], "PENDENTE_REVISAO")

    def test_texto_tabela_imagem_e_fotografia(self):
        leitor = LeitorFalso()
        texto, blocos = extrair_pagina_e_blocos(leitor, 3, 1, CONTEXTO, 1)
        tabelas = extrair_tabelas(leitor, 3, 1, CONTEXTO, 1)
        imagens, fotos = catalogar_imagens(leitor, 3, 1, CONTEXTO, 1, 1)
        self.assertIn("Foto 1", texto)
        self.assertEqual(len(blocos), 1)
        self.assertEqual(tabelas[0]["linhas"], 2)
        self.assertEqual(len(imagens), 1)
        self.assertEqual(fotos[0]["numero_original"], "1")

    def test_anexo_interno_sem_novo_id_pje(self):
        textos = [(3, 1, "CORPO"), (4, 2, "ANEXO I — RELATÓRIO FOTOGRÁFICO")]
        secoes = detectar_secoes(textos, CONTEXTO)
        paginas = [{"referencia": {"pagina_pdf": p, "pagina_documento": p-2, "pagina_original": None},
                    "possui_texto_util": True, "possui_imagens": False, "possui_tabelas": False} for p in (3, 4)]
        subs = criar_subdocumentos(secoes, "DOC-PJE-001", paginas)
        self.assertEqual(len(subs), 1)
        self.assertNotIn("id_pje", secoes[0])
        self.assertEqual(subs[0]["documento_pai"], "DOC-PJE-001")

    def test_multiplas_secoes_explicitas_na_mesma_pagina(self):
        textos = [(3, 1, "ANEXO I — RELATÓRIO FOTOGRÁFICO\nANEXO II — ORÇAMENTO")]
        secoes = detectar_secoes(textos, CONTEXTO)
        self.assertEqual([s["tipo_normalizado"] for s in secoes], ["RELATORIO_FOTOGRAFICO", "ORCAMENTO"])
        self.assertTrue(all(s["pagina_inicio"]["pagina_pdf"] == 3 for s in secoes))

    def test_integridade_detecta_pagina_externa_e_id_divergente(self):
        doc = json.loads((RAIZ / "tests/fixtures/pje/documento-simples-valido.json").read_text(encoding="utf-8"))
        base = {"documento_id": "DOC-PJE-001", "id_pje": "900001", "pagina_pdf_inicio": 3,
                "pagina_pdf_fim": 3, "titulo_original": doc["titulo_original"],
                "tipo_original": doc["tipo_original"], "ordem_indice": doc["ordem_indice"],
                "data_hora": doc["data_hora"], "status_reconciliacao": doc["status_reconciliacao"],
                "_processo_cnj": doc["processo_cnj"], "_paginas_manifesto": []}
        doc["id_pje"] = "999999"
        doc["titulo_original"] = "Título divergente"
        doc["paginas"][0]["referencia"]["pagina_pdf"] = 4
        erros, _ = validar_documento(doc, base)
        self.assertTrue(any("id_pje" in e for e in erros))
        self.assertTrue(any("titulo_original" in e for e in erros))
        self.assertTrue(any("intervalo" in e or "página" in e for e in erros))


if __name__ == "__main__":
    unittest.main()
