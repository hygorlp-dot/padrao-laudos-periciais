import copy
import unittest

from scripts.conhecimento_privado.pesquisa_online import EgressPolicy, buscar_seguro
from scripts.auditoria_pericial import auditar_claim
from scripts.motor_vicios.auditar import comparar_medicao, classificar_autoauditoria
from scripts.motor_vicios.evidencias import selecionar
from scripts.motor_vicios.pipeline import recalcular_gate
from scripts.planejamento_pericial.validar_plano import recalcular_cobertura
from scripts.triagem_pericial.gerar_delimitacao import resultado_criterio


class CorePericialP0Test(unittest.TestCase):
    def test_catalogo_nao_muda_e_ordem_nao_muda_relacoes(self):
        catalogo = [
            {"id": "DOC-001", "tipo": "DOCUMENTO", "questoes": ["QT-001"], "sistema": "FACHADA"},
            {"id": "DOC-002", "tipo": "DOCUMENTO", "questoes": ["QT-999"], "sistema": "PISCINA"},
        ]
        original = copy.deepcopy(catalogo)
        contexto = {"questoes": ["QT-001"], "sistema": "FACHADA"}
        ab = selecionar(catalogo, contexto=contexto, relacao_id="MAN-001")
        ba = selecionar(list(reversed(catalogo)), contexto=contexto, relacao_id="MAN-001")
        self.assertEqual(catalogo, original)
        self.assertEqual([x["id"] for x in ab], [x["id"] for x in ba])
        self.assertEqual(ab[0]["relacao_associacao"]["relacao_id"], "MAN-001")
        self.assertNotIn("associacao", catalogo[0])

    def test_evidencia_irrelevante_nao_altera_e_remocao_essencial_bloqueia(self):
        contexto = {"questoes": ["QT-001"], "sistema": "FACHADA"}
        essencial = {"id": "DOC-001", "tipo": "DOCUMENTO", "questoes": ["QT-001"], "sistema": "FACHADA"}
        irrelevante = {"id": "DOC-999", "tipo": "DOCUMENTO", "questoes": ["QT-999"], "sistema": "PISCINA"}
        self.assertEqual([x["id"] for x in selecionar([essencial], contexto=contexto, relacao_id="PAT-001")],
                         [x["id"] for x in selecionar([essencial, irrelevante], contexto=contexto, relacao_id="PAT-001")])
        self.assertEqual(selecionar([irrelevante], contexto=contexto, relacao_id="PAT-001"), [])
        self.assertEqual(selecionar([irrelevante], ids=["DOC-999"], contexto=contexto, relacao_id="PAT-001"), [])
        claim={"id":"CLM-001","tipo":"CAUSA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"Causa sintética","aspectos_requeridos":["CAUSA"]}
        evidencia={"id":"OBS-001","tipo":"OBSERVACAO","proveniencia":["VISTORIA-SINTETICA"],"aspectos_suportados":["CAUSA"]}
        com=auditar_claim(claim,[evidencia],[evidencia]);sem=auditar_claim(claim,[],[])
        self.assertEqual(recalcular_gate({"materiais":[com]}),"APTO_PARA_REDACAO")
        self.assertEqual(recalcular_gate({"materiais":[sem]}), "BLOQUEADO_PARA_REDACAO")

    def test_cobertura_required_to_planned_por_tipo(self):
        plano = {"questoes_tecnicas": ["QT-001"], "quesitos_relacionados": ["QUE-001"],
                 "atividades": [{"id": "ATV-001", "questoes_tecnicas": ["QT-001"]}],
                 "medicoes": [], "fotografias": [], "ensaios": [], "documentos_a_solicitar": [],
                 "cobertura": [{"quesito": "QUE-001", "questoes_tecnicas": ["QT-001"], "atividades": ["ATV-001"],
                                "medicoes": [], "fotografias": [], "ensaios": [], "documentos": [], "planejada": True}],
                 "requisitos_cobertura": [{"questao_tecnica": "QT-001", "tipo": "MEDICAO", "obrigatoriedade": "OBRIGATORIA"}]}
        resultado = recalcular_cobertura(plano)
        self.assertFalse(resultado["cobertura"]["QUE-001"])
        plano["medicoes"] = [{"id": "MED-PLANO-001", "questoes_tecnicas": ["QT-001"]}]
        plano["cobertura"][0]["medicoes"] = ["MED-PLANO-001"]
        self.assertTrue(recalcular_cobertura(plano)["cobertura"]["QUE-001"])
        plano["medicoes"] = [{"id": "MED-PLANO-999", "questoes_tecnicas": ["QT-999"]}]
        plano["cobertura"][0]["medicoes"] = ["MED-PLANO-999"]
        self.assertFalse(recalcular_cobertura(plano)["cobertura"]["QUE-001"])
        plano.pop("requisitos_cobertura")
        self.assertFalse(recalcular_cobertura(plano)["apto"])

    def test_fidelidade_numerica_decimal_unidade_e_conversao(self):
        self.assertFalse(comparar_medicao("40 mm", {"valor": "4", "unidade": "mm"}))
        self.assertFalse(comparar_medicao("4 cm", {"valor": "4", "unidade": "mm"}))
        self.assertTrue(comparar_medicao("4,0 mm", {"valor": "4.0", "unidade": "mm"}))
        self.assertTrue(comparar_medicao("0,4 cm", {"valor": "4", "unidade": "mm"}, permitir_conversao=True))
        self.assertFalse(comparar_medicao("0,4 cm", {"valor": "4", "unidade": "mm"}, permitir_conversao=False))

    def test_egress_deny_pii_e_consulta_publica_saneada(self):
        provider = type("P", (), {"buscar": lambda self, q: [{"url": "https://www.gov.br/fonte", "q": q}]})()
        politica = EgressPolicy()
        self.assertFalse(politica.permitir_egress)
        self.assertEqual(buscar_seguro("norma técnica pública", provider)["status"], "BLOQUEADO_POR_EGRESS")
        casos = ["CPF 123.456.789-00", "0000001-00.2026.4.00.0001", "Rua Alfa, 123", "a@b.com", "(71) 99999-9999", "a parte autora afirmou infiltração nos autos"]
        for caso in casos:
            with self.subTest(caso=caso):
                self.assertEqual(buscar_seguro(caso, provider, politica)["status"], "BLOQUEADO_POR_EGRESS")
        for caso in ("Travessa Alfa 123", "petição inicial com dados das partes"):
            self.assertEqual(buscar_seguro(caso, provider, EgressPolicy(permitir_egress=True))["status"], "BLOQUEADO_POR_EGRESS")
        ok = buscar_seguro("norma técnica pública sobre fachadas", provider, EgressPolicy(permitir_egress=True))
        self.assertEqual(ok["status"], "CONCLUIDA")
        self.assertNotIn("CPF", ok["consulta"])

    def test_autoauditoria_derivada_e_gate_recalculado(self):
        self.assertEqual(resultado_criterio(True),"APROVADO")
        self.assertEqual(resultado_criterio(False),"BLOQUEADO")
        self.assertEqual(classificar_autoauditoria([]), "APROVADO")
        self.assertEqual(classificar_autoauditoria([{"bloqueante": False}]), "APROVADO_COM_RESSALVA")
        self.assertEqual(classificar_autoauditoria([{"bloqueante": True}]), "REPROVADO")
        estado = {"erros": [], "detector": [], "proposition_bloqueante": False, "medicao_ausente": False,
                  "materiais": [], "autoauditoria": [], "ressalvas": False}
        self.assertEqual(recalcular_gate(estado, status_declarado="BLOQUEADO_PARA_REDACAO"), "APTO_PARA_REDACAO")
        estado["erros"] = ["falha"]
        self.assertEqual(recalcular_gate(estado, status_declarado="APTO_PARA_REDACAO"), "BLOQUEADO_PARA_REDACAO")


if __name__ == "__main__":
    unittest.main()
