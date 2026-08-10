import unittest
from scripts.auditoria_pericial import auditar_claim,executar_deep_audit,executar_detector,registrar_trilha,executar_auditoria_integrada
from scripts.auditoria_pericial.fontes import ordenar_fontes

class AuditoriaPericialTest(unittest.TestCase):
    def claim(self):return {"id":"CLM-001","tipo":"CAUSA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"A fissura decorre de recalque diferencial."}
    def ev(self,**extras):return {**{"id":"OBS-001","tipo":"OBSERVACAO","proveniencia":["ARQ-VIS-001"]},**extras}
    def audit(self,claim,evidencias):return auditar_claim(claim,evidencias,evidencias)
    def test_claim_bem_sustentada(self):
        evidencias=[self.ev(aspectos_suportados=["CAUSA"])];r=self.audit(self.claim(),evidencias);self.assertEqual(r["veredito"],"GROUNDED")
    def test_claim_parcial_material_e_insuficiente(self):
        c=self.claim();c["aspectos_requeridos"]=["MECANISMO","CAUSA"];e=[self.ev(aspectos_suportados=["MECANISMO"])];r=self.audit(c,e);self.assertEqual(r["veredito"],"INSUFFICIENT")
    def test_detalhe_interpolado(self):
        c=self.claim();c["detalhe_nao_suportado"]=True;e=[self.ev(aspectos_suportados=["CAUSA"])];self.assertEqual(self.audit(c,e)["veredito"],"INTERPOLATED")
    def test_evidencia_contradiz(self):
        e=[self.ev(aspectos_contraditos=["CAUSA"])];self.assertEqual(self.audit(self.claim(),e)["veredito"],"CONTRADICTED")
    def test_fonte_inacessivel(self):
        e=[{"id":"NOR-001","tipo":"NORMA","proveniencia":["fonte"],"acessivel":False}];self.assertEqual(self.audit(self.claim(),e)["veredito"],"UNVERIFIABLE")
    def test_deep_audit_reduz_recalque_sem_medicao(self):
        c=self.claim();c["aspectos_requeridos"]=["MECANISMO","CAUSA"];e=[self.ev(aspectos_suportados=["MECANISMO"])];audit=self.audit(c,e);achados=executar_deep_audit([audit]);self.assertEqual(achados[0]["tipo"],"CONCLUSAO_EXCEDE_EVIDENCIA")
    def test_detector_encontra_referencia_orfa(self):
        resultado={"patologias":[{"id":"PAT-001","alegacoes_relacionadas":[],"constatacoes":["OBS-999"],"medicoes":[],"constatacao":{"fotografias":[],"situacao":"ANOMALIA"},"origem":"INCONCLUSIVA","vicio_construtivo":{"caracterizado":False},"criticidade":"INCONCLUSIVA","consequencias":{},"normas_relacionadas":[]}],"cobertura_quesitos":[]}
        vistoria={"observacoes":[{"id":"OBS-001"}]};self.assertEqual(executar_detector(resultado,vistoria=vistoria)[0]["tipo"],"OBS_INEXISTENTE")
    def test_trilha_rejeita_chain_of_thought(self):
        with self.assertRaises(ValueError):registrar_trilha(execucao_id="X",chain_of_thought="não registrar")
        with self.assertRaises(ValueError):registrar_trilha(execucao_id="X",decisoes_autonomas=[{"chain_of_thought":"não registrar"}])
    def test_trilha_registra_justificativa_profissional(self):
        t=registrar_trilha(execucao_id="X",decisoes_autonomas=[{"decisao":"Origem inconclusiva","evidencia":"OBS-001","justificativa":"Causa não demonstrada"}]);self.assertNotIn("chain_of_thought",t)
    def test_caso_anterior_nao_e_evidencia_fatica(self):
        e=[{"id":"MOD-0001","tipo":"MODELO_REFERENCIAL","proveniencia":["modelo"],"aspectos_suportados":[]}];r=self.audit(self.claim(),e);self.assertEqual(r["veredito"],"UNVERIFIABLE")
    def test_item_normativo_nao_consultado_nao_sustenta_claim(self):
        c={**self.claim(),"tipo":"CONFORMIDADE_NORMATIVA"};e=[{"id":"NOR-001","tipo":"NORMA","proveniencia":["fonte"],"acessivel":False}];r=self.audit(c,e);self.assertEqual(r["veredito"],"UNVERIFIABLE")
    def test_integrada_bloqueia_claim_material_insuficiente(self):
        c=self.claim();c["aspectos_requeridos"]=["MECANISMO","CAUSA"];e=[self.ev(aspectos_suportados=["MECANISMO"])];r=executar_auditoria_integrada({"patologias":[],"cobertura_quesitos":[]},[{"claim":c,"evidencias":e,"catalogo":e}]);self.assertEqual(r["gate"],"BLOQUEADO_PARA_REDACAO")
    def test_gate_bloqueia_claim_material_nao_verificavel(self):
        r=executar_auditoria_integrada({"patologias":[],"cobertura_quesitos":[]},[{"claim":self.claim(),"evidencias":[]}]);self.assertEqual(r["gate"],"BLOQUEADO_PARA_REDACAO")
    def test_evidencia_autodeclarada_sem_proveniencia_nao_grounda(self):
        r=auditar_claim(self.claim(),[{"id":"QUALQUER","tipo":"OBSERVACAO","aspectos_suportados":["CAUSA"]}]);self.assertEqual(r["veredito"],"UNVERIFIABLE")
    def test_evidencia_nao_reconciliada_nao_grounda(self):
        e=[self.ev(aspectos_suportados=["CAUSA"])];catalogo=[self.ev(proveniencia=["OUTRA-FONTE"])];self.assertEqual(auditar_claim(self.claim(),e,catalogo)["veredito"],"UNVERIFIABLE")
    def test_relacao_nao_pode_inventar_poder_de_suporte(self):
        relacao=[self.ev(aspectos_suportados=["CAUSA"])];catalogo=[self.ev(aspectos_suportados=[])];self.assertEqual(auditar_claim(self.claim(),relacao,catalogo)["veredito"],"UNSUBSTANTIATED")
    def test_claim_id_deve_seguir_schema(self):
        with self.assertRaises(ValueError):auditar_claim({**self.claim(),"id":"CLM-X"},[],[])
    def test_claim_com_enum_invalido_e_rejeitada(self):
        c={**self.claim(),"natureza":"INVALIDA"}
        with self.assertRaises(ValueError):self.audit(c,[self.ev(aspectos_suportados=["CAUSA"])])
    def test_detector_detecta_orfa_com_catalogo_vazio(self):
        resultado={"patologias":[{"id":"PAT-001","alegacoes_relacionadas":[],"constatacoes":["OBS-999"],"medicoes":[],"constatacao":{"fotografias":[],"situacao":"ANOMALIA"},"origem":"INCONCLUSIVA","vicio_construtivo":{"caracterizado":False},"criticidade":"INCONCLUSIVA","consequencias":{},"normas_relacionadas":[]}],"cobertura_quesitos":[]};self.assertEqual(executar_detector(resultado,vistoria={})[0]["tipo"],"OBS_INEXISTENTE")
    def test_detector_sinaliza_catalogos_ausentes(self):
        resultado={"patologias":[{"id":"PAT-001","alegacoes_relacionadas":["ALG-999"],"constatacoes":[],"medicoes":[],"constatacao":{"fotografias":[],"situacao":"ANOMALIA"},"origem":"INCONCLUSIVA","vicio_construtivo":{"caracterizado":False},"criticidade":"INCONCLUSIVA","consequencias":{},"normas_relacionadas":[{"id":"NOR-999","proveniencia":["x"],"verificada":True}],"ressalvas_relacionadas":["RES-999"]}],"cobertura_quesitos":[]}
        tipos={a["tipo"] for a in executar_detector(resultado)};self.assertTrue({"CATALOGO_ALG_AUSENTE","CATALOGO_NOR_AUSENTE","CATALOGO_RES_AUSENTE"}<=tipos)
    def test_deep_audit_distingue_negacao_de_divergencia_de_suporte(self):
        base={"tipo":"CAUSA","saliencia":"SUPPORTING"};claims=[{**base,"claim_id":"CLM-001","texto":"Há recalque","veredito":"GROUNDED"},{**base,"claim_id":"CLM-002","texto":"Não há recalque","veredito":"GROUNDED"}]
        self.assertIn("CONTRADICAO_ENTRE_CLAIMS",{a["tipo"] for a in executar_deep_audit(claims)})
        iguais=[{**base,"claim_id":"CLM-003","texto":"Há recalque","veredito":"GROUNDED"},{**base,"claim_id":"CLM-004","texto":"Há recalque","veredito":"WEAKLY_GROUNDED"}]
        self.assertNotIn("CONTRADICAO_ENTRE_CLAIMS",{a["tipo"] for a in executar_deep_audit(iguais)})
    def test_deep_audit_reconhece_formas_explicitas_de_ausencia(self):
        base={"tipo":"CAUSA","saliencia":"SUPPORTING","veredito":"GROUNDED"};claims=[{**base,"claim_id":"CLM-001","texto":"Há recalque"},{**base,"claim_id":"CLM-002","texto":"Ausência de recalque"}]
        self.assertIn("CONTRADICAO_ENTRE_CLAIMS",{a["tipo"] for a in executar_deep_audit(claims)})
    def test_fonte_primaria_tem_prioridade(self):
        fontes=ordenar_fontes([{"id":"SEC","tipo":"FONTE_SECUNDARIA"},{"id":"PRI","tipo":"FONTE_PRIMARIA_OFICIAL"}]);self.assertEqual(fontes[0]["id"],"PRI")
if __name__=="__main__":unittest.main()
