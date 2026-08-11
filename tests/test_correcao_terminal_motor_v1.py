import copy,json,unittest
from pathlib import Path

from scripts.auditoria_pericial.deep_audit import executar_deep_audit
from scripts.auditoria_pericial.detector import executar_detector
from scripts.auditoria_pericial.grounding import auditar_claim
from scripts.motor_vicios.autocorrigir import autocorrigir
from scripts.motor_vicios.evidencias import construir_catalogo,extrair_aspectos
from scripts.motor_vicios.hipoteses import capacidade_causal,SISTEMAS_AUDITADOS
from scripts.motor_vicios.normas import avaliar_conformidade_normativa
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.vistoria_estruturada.gerar_vistoria import gerar

RAIZ=Path(__file__).resolve().parents[1]
def load(p):return json.loads((RAIZ/p).read_text(encoding="utf-8"))
def inventario(texto):return {"arquivos":[{"id":"ARQ-VIS-001","nome":"notas.txt","caminho_relativo":"notas.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":texto}}]}

class CorrecaoTerminalMotorV1Test(unittest.TestCase):
    def setUp(self):self.processo=load("tests/fixtures/schemas/processo-valido.json");self.delim=load("tests/fixtures/triagem/delimitacao-minima-valida.json");self.plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json")
    def gerar(self,texto):return gerar(inventario(texto),self.plano,self.processo["numero_processo"])

    def test_obs_pol_01_02_03_05(self):
        casos=(("Sala: Não há fissura na parede.","NAO_CONSTATADO_NA_VISTORIA"),("Sala: fissura superficial sem degrau.","OBSERVADO"),("Sem sinais de infiltração ativa.","NAO_CONSTATADO_NA_VISTORIA"),("Não foi possível determinar se existe infiltração.","INCONCLUSIVO"))
        for texto,esperado in casos:
            with self.subTest(texto=texto):self.assertEqual(self.gerar(texto)["observacoes"][0]["resultado"],esperado)

    def test_obs_pol_04_duas_proposicoes(self):
        obs=self.gerar("Não há fissura na parede, mas existe fissura no teto.")["observacoes"];self.assertEqual([(x["ambiente"],x["resultado"]) for x in obs],[("PAREDE","NAO_CONSTATADO_NA_VISTORIA"),("TETO","OBSERVADO")])

    def test_obs_pol_06_pipeline_nao_afirma_anomalia(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.gerar("Sala: Não há fissura na parede."));p=r["analise_final"]["patologias"][0];self.assertEqual(p["constatacao"]["situacao"],"NAO_CONSTATADA");self.assertNotIn("foi observada",p["conclusao_tecnica"].lower())

    def norma(self):return {"id":"NOR-001","tipo":"NORMA","requisito":"interface com vedação deteriorada não atende ao requisito","verificada":True,"proveniencia":["FONTE"],"metodo_verificacao":"medição","criterio":{"operador":"<=","valor":.5,"unidade":"mm","grandeza":"abertura"}}

    def test_nor_src_01_05_tipagem_epistemica(self):
        e=construir_catalogo({},normas=[self.norma()])[0];self.assertIn("REQUISITO_NORMATIVO_VERIFICADO",e["aspectos_suportados"]);self.assertFalse({"VEDACAO_DETERIORADA","INTERFACE_IDENTIFICADA","FISSURA_PRESENTE"}&set(e["aspectos_suportados"]))
        n=self.norma();n["requisito"]="fissura: requisito aplicável";self.assertNotIn("FISSURA_PRESENTE",construir_catalogo({},normas=[n])[0]["aspectos_suportados"])

    def test_nor_src_02_03_04_comparacao(self):
        n=self.norma();base={"id":"MED-001","tipo":"MEDICAO","grandeza":"abertura","unidade":"mm"};self.assertEqual(avaliar_conformidade_normativa(n,[])["resultado"],"INCONCLUSIVO");self.assertEqual(avaliar_conformidade_normativa(n,[{**base,"valor":.4}])["resultado"],"ATENDE");self.assertEqual(avaliar_conformidade_normativa(n,[{**base,"valor":.8}])["resultado"],"NAO_ATENDE")

    def test_claim_audit_rejeita_norma_como_fato(self):
        e={"id":"NOR-001","tipo":"NORMA","classe_probatoria":"EVIDENCIA_PRIMARIA","proveniencia":["FONTE"],"aspectos_suportados":["FISSURA_PRESENTE"],"aspectos_contraditos":[],"acessivel":True};c={"id":"CLM-001","tipo":"ASPECTO_OBSERVAVEL","natureza":"FACTUAL","saliencia":"LOAD_BEARING","texto":"Fissura presente no imóvel","aspectos_requeridos":["FISSURA_PRESENTE"]};self.assertNotEqual(auditar_claim(c,[e],[e])["veredito"],"GROUNDED")

    def test_nor_src_06_norma_e_chuva_nao_criam_causa(self):
        v=load("tests/fixtures/schemas/vistoria-valida.json");v["observacoes"][0].update({"descricao_objetiva":"Chuva registrada no período.","manifestacao":"umidade","sistema":"IMPERMEABILIZACAO"});n=self.norma();n.update({"titulo":"impermeabilização","sistema":"IMPERMEABILIZACAO"});r=executar_pipeline_motor(self.processo,self.delim,self.plano,v,{"normas":[n]});p=r["analise_final"]["patologias"][0];self.assertIsNone(p["causa"]);self.assertNotEqual(p["origem"],"ENDOGENA_CONSTRUTIVA");self.assertFalse(p["vicio_construtivo"]["caracterizado"])

    def test_detectores_deep_e_autocorrecao_terminal(self):
        obs={"id":"OBS-001","tipo":"OBSERVACAO","resultado":"OBSERVADO","aspectos_suportados":["FISSURA_PRESENTE"],"auditoria_aspectos":[{"aspecto":"FISSURA_PRESENTE","polaridade":"NEGADO","aspectos_derivados_consultados":False}]};nor={"id":"NOR-001","tipo":"NORMA","aspectos_suportados":["REQUISITO_NORMATIVO_VERIFICADO","VEDACAO_DETERIORADA"],"auditoria_aspectos":[]};pat={"id":"PAT-001","constatacoes":["OBS-001"],"constatacao":{"situacao":"ANOMALIA"},"causa":"falha","origem":"ENDOGENA_CONSTRUTIVA","vicio_construtivo":{"caracterizado":True},"elegibilidade_orcamento":"ELEGIVEL_ORCAMENTO_VICIO","analise_causal":{"fundamentos":["NOR-001"]},"recomendacao":{"necessaria":True,"descricao":{}},"normas_relacionadas":[]};r={"patologias":[pat],"catalogo_evidencias":[obs,nor],"cobertura_quesitos":[],"questoes_saneadas":[]};tipos={x["tipo"] for x in executar_detector(r)};self.assertTrue({"OBS_NEGADA_COM_RESULTADO_OBSERVADO","NORMA_USADA_COMO_FATO_DO_CASO"}<=tipos);prof=executar_deep_audit([],r);self.assertTrue({"OBS_NEGADA_COM_RESULTADO_OBSERVADO","NORMA_USADA_COMO_FATO_DO_CASO"}<={x["tipo"] for x in prof});final,_=autocorrigir(r,[],[],prof);self.assertEqual(final["catalogo_evidencias"][0]["resultado"],"NAO_CONSTATADO_NA_VISTORIA");self.assertEqual(final["catalogo_evidencias"][1]["aspectos_suportados"],["REQUISITO_NORMATIVO_VERIFICADO"])

    def test_detectores_terminais_nao_geram_falso_positivo(self):
        obs={"id":"OBS-001","tipo":"OBSERVACAO","resultado":"OBSERVADO","aspectos_suportados":["FISSURA_PRESENTE"],"auditoria_aspectos":[{"aspecto":"FISSURA_PRESENTE","polaridade":"AFIRMADO","aspectos_derivados_consultados":False}]};nor={"id":"NOR-001","tipo":"NORMA","aspectos_suportados":["REQUISITO_NORMATIVO_VERIFICADO"],"auditoria_aspectos":[]};r={"patologias":[],"catalogo_evidencias":[obs,nor],"cobertura_quesitos":[],"questoes_saneadas":[]};self.assertFalse({"OBS_NEGADA_COM_RESULTADO_OBSERVADO","NORMA_USADA_COMO_FATO_DO_CASO"}&{x["tipo"] for x in executar_detector(r)});self.assertFalse({"OBS_NEGADA_COM_RESULTADO_OBSERVADO","NORMA_USADA_COMO_FATO_DO_CASO"}&{x["tipo"] for x in executar_deep_audit([],r)})

    def obs_vedacao(self):
        v=load("tests/fixtures/schemas/vistoria-valida.json");v["atividades_executadas"][0]["questoes"]=["QT-001"];v["observacoes"][0].update({"descricao_objetiva":"Fissura observada.","manifestacao":"fissura","sistema":"VEDACOES","resultado":"OBSERVADO"});return v

    def test_cap_01_02_registro_dos_sistemas(self):
        self.assertEqual(set(SISTEMAS_AUDITADOS),{"IMPERMEABILIZACAO","REVESTIMENTOS","ESQUADRIAS","ESTRUTURA","VEDACOES","PINTURA","COBERTURA","FORROS","INSTALACOES_ELETRICAS","INSTALACOES_HIDROSSANITARIAS","DRENAGEM","OUTRO"});self.assertEqual(capacidade_causal("IMPERMEABILIZACAO")["nivel_de_capacidade"],"SUPORTE_CAUSAL_PARCIAL");self.assertEqual(capacidade_causal("VEDACOES")["nivel_de_capacidade"],"MOTOR_CAUSAL_NAO_IMPLEMENTADO")

    def test_cap_03_existencia_continua_saneavel(self):
        d=copy.deepcopy(self.delim);d["questoes_tecnicas"][0]["descricao"]="Há fissura?";r=executar_pipeline_motor(self.processo,d,self.plano,self.obs_vedacao());self.assertEqual(r["analise_final"]["questoes_saneadas"][0]["status"],"SANEADA");self.assertEqual(r["analise_final"]["patologias"][0]["constatacao"]["situacao"],"ANOMALIA")

    def test_cap_04_05_causa_declara_limitacao_do_software(self):
        d=copy.deepcopy(self.delim);d["questoes_tecnicas"][0]["descricao"]="Qual a causa da fissura?";r=executar_pipeline_motor(self.processo,d,self.plano,self.obs_vedacao());q=r["analise_final"]["questoes_saneadas"][0];p=r["analise_final"]["patologias"][0];self.assertEqual(q["status"],"INCONCLUSIVA_POR_LIMITACAO");self.assertEqual(q["ressalvas"],["BLOQUEIO_INTERNO_POR_CAPACIDADE_DO_MOTOR"]);self.assertEqual(p["analise_causal"]["status_capacidade"],"MOTOR_CAUSAL_NAO_IMPLEMENTADO");self.assertIsNone(p["causa"])

    def polaridades(self,texto):
        return {x["aspecto"]:x["polaridade"] for x in extrair_aspectos({"tipo":"OBSERVACAO","descricao":texto})}

    def test_neg_coord_01_02_03(self):
        casos=(("N\u00e3o h\u00e1 fissura e trinca na parede.",("FISSURA_PRESENTE","TRINCA_PRESENTE")),("Sem sinais de umidade e infiltra\u00e7\u00e3o ativa.",("UMIDADE_OBSERVADA","INFILTRACAO_ATIVA")),("N\u00e3o h\u00e1 risco grave de seguran\u00e7a e perda de funcionalidade.",("RISCO_SEGURANCA_REGISTRADO","PERDA_FUNCIONAL_REGISTRADA")))
        for texto,aspectos in casos:
            with self.subTest(texto=texto):p=self.polaridades(texto);self.assertTrue(all(p[x]=="NEGADO" for x in aspectos))

    def test_neg_coord_04_05_06_07(self):
        itens=extrair_aspectos({"tipo":"OBSERVACAO","descricao":"N\u00e3o h\u00e1 fissura e existe fissura no teto."});self.assertEqual([x["polaridade"] for x in itens if x["aspecto"]=="FISSURA_PRESENTE"],["NEGADO","AFIRMADO"])
        p=self.polaridades("N\u00e3o h\u00e1 fissura, trinca ou deforma\u00e7\u00e3o.");self.assertTrue(all(p[x]=="NEGADO" for x in ("FISSURA_PRESENTE","TRINCA_PRESENTE","DEFORMACAO_PRESENTE")))
        p=self.polaridades("N\u00e3o h\u00e1 fissura e n\u00e3o h\u00e1 trinca.");self.assertEqual((p["FISSURA_PRESENTE"],p["TRINCA_PRESENTE"]),("NEGADO","NEGADO"))
        p=self.polaridades("Fissura superficial e sem degrau.");self.assertEqual((p["FISSURA_PRESENTE"],p["DEGRAU_PRESENTE"]),("AFIRMADO","NEGADO"))

    def test_neg_coord_08_pipeline_nao_cria_anomalia(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.gerar("Sala: N\u00e3o h\u00e1 fissura e trinca na parede."));self.assertTrue(all(p["constatacao"]["situacao"]!="ANOMALIA" for p in r["analise_final"]["patologias"]))

    def executar_qt_vedacao(self,texto):
        d=copy.deepcopy(self.delim);d["questoes_tecnicas"][0]["descricao"]=texto;return executar_pipeline_motor(self.processo,d,self.plano,self.obs_vedacao())

    def test_cap_gate_01_02_03_04(self):
        existencia=self.executar_qt_vedacao("Existe fissura na parede?");self.assertEqual(existencia["analise_final"]["questoes_saneadas"][0]["status"],"SANEADA");self.assertNotEqual(existencia["gate"],"BLOQUEADO_PARA_REDACAO");self.assertFalse(any(x["tipo"]=="QT_CAUSAL_SEM_CAPACIDADE_DO_MOTOR" for x in existencia["detector_final"]))
        for texto in ("Qual a causa da fissura?","Qual a origem da fissura?","Existe fissura e qual a causa?"):
            with self.subTest(texto=texto):r=self.executar_qt_vedacao(texto);self.assertEqual(r["gate"],"BLOQUEADO_PARA_REDACAO");self.assertTrue(any(x["tipo"]=="QT_CAUSAL_SEM_CAPACIDADE_DO_MOTOR" for x in r["detector_final"]));self.assertTrue(any(x["tipo"]=="ANALISE_CAUSAL_NAO_EXECUTADA" for x in r["deep_audit_final"]));self.assertIsNone(r["analise_final"]["patologias"][0]["causa"])
        mista=self.executar_qt_vedacao("Existe fissura e qual a causa?")["analise_final"]["questoes_saneadas"][0]["dimensoes_saneamento"];self.assertEqual({x["intencao"]:x["status"] for x in mista},{"CAUSALIDADE":"NAO_SANEADA_POR_CAPACIDADE","EXISTENCIA":"SANEADA"})

    def test_cap_gate_07_08_nao_bloqueiam(self):
        for texto in ("Quem deve indenizar pela causa da fissura?","Qual a medi\u00e7\u00e3o da fissura?"):
            with self.subTest(texto=texto):self.assertNotEqual(self.executar_qt_vedacao(texto)["gate"],"BLOQUEADO_PARA_REDACAO")

if __name__=="__main__":unittest.main()
