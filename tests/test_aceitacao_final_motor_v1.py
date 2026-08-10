import copy,json,tempfile,time,unittest
from pathlib import Path

from scripts.auditoria_pericial.grounding import auditar_claim
from scripts.auditoria_pericial.proposition import auditar_proposicoes
from scripts.conhecimento_privado.pesquisa_online import reconciliar_fontes
from scripts.motor_vicios.autocorrigir import autocorrigir
from scripts.motor_vicios.normas import aplicabilidade_temporal
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.motor_vicios.regras import classificacoes
from scripts.planejamento_pericial.gerar_plano import gerar as gerar_plano
from scripts.planejamento_pericial.gerar_processo import gerar as gerar_processo
from scripts.planejamento_pericial.aprofundar_delimitacao import aprofundar
from scripts.triagem_pericial.gerar_delimitacao import gerar as gerar_delimitacao
from scripts.vistoria_estruturada.inventariar_vistoria import inventariar
from scripts.vistoria_estruturada.gerar_vistoria import gerar as gerar_vistoria

RAIZ=Path(__file__).resolve().parents[1]
def load(p):return json.loads((RAIZ/p).read_text(encoding="utf-8"))

class AceitacaoFinalMotorV1Test(unittest.TestCase):
    def setUp(self):
        self.processo=load("tests/fixtures/schemas/processo-valido.json");self.delim=load("tests/fixtures/triagem/delimitacao-minima-valida.json");self.plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json")
    def obs(self,i=1,aspectos=None,resultado="OBSERVADO"):
        return {"id":f"OBS-{i:03d}","local":"Local sintético","ambiente":"Sala sintética","sistema":"IMPERMEABILIZACAO","elemento":"Parede","descricao_objetiva":"Interface sob chuva com vedação deteriorada","manifestacao":"umidade","resultado":resultado,"campo_examinado":"Superfície acessível","metodo":["INSPECAO_VISUAL"],"fotografias":[],"medicoes":[],"alegacoes":["ALG-001"],"questoes":["QT-001"],"quesitos":["QUE-001"],"confianca":{"nivel":"ALTA"},"proveniencia":[f"ARQ-VIS-{i:03d}"],"limitacoes":[],"aspectos_suportados":aspectos or []}
    def vistoria(self,obs):
        v=load("tests/fixtures/schemas/vistoria-valida.json");v["observacoes"]=obs;return v
    def forte(self):
        obs=[self.obs(1),self.obs(2)];docs=[{"id":"DOC-VIS-001","descricao":"Projeto executivo com detalhe executivo especifica a vedação.","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-DOC-001"]},{"id":"DOC-VIS-002","descricao":"Controle tecnológico documenta execução divergente e resultado incompatível com o requisito.","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-DOC-002"]}]
        return executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria(obs),{"documentos":docs})

    def test_t_final_01_vicio_autonomo_sem_validado_perito(self):
        c={"origem":"ENDOGENA_CONSTRUTIVA","causa":"falha executiva","evidencias":["OBS-001"]};self.assertTrue(classificacoes("ANOMALIA",c)[2]);self.assertNotIn("validado_perito",c)
    def test_t_final_02_pat_nao_faz_self_grounding(self):self._self_ground("PAT-001","INFERENCIA_TECNICA")
    def test_t_final_03_qt_nao_faz_self_grounding(self):self._self_ground("QT-001","INFERENCIA_TECNICA")
    def test_t_final_04_hip_nao_e_prova_primaria(self):self._self_ground("HIP-001","INFERENCIA_TECNICA")
    def _self_ground(self,eid,tipo):
        c={"id":"CLM-001","tipo":"CAUSA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"Causa sintética","aspectos_requeridos":["CAUSA"]};e={"id":eid,"tipo":tipo,"classe_probatoria":"INFERENCIA_INTERMEDIARIA","proveniencia":["x"],"aspectos_suportados":["CAUSA"],"aspectos_contraditos":[]};self.assertNotEqual(auditar_claim(c,[e],[e])["veredito"],"GROUNDED")
    def test_t_final_05_round_robin_ausente(self):
        fonte=(RAIZ/"scripts/planejamento_pericial/gerar_plano.py").read_text(encoding="utf-8");self.assertNotIn("% len",fonte);self.assertNotIn("(i - 1)",fonte)
    def test_t_final_06_ordem_qt_nao_altera_plano(self):
        d1=copy.deepcopy(self.delim);d1["questoes_tecnicas"]=[{"id":f"QT-{i:03d}","descricao":f"Verificar condição {i}","alegacoes_relacionadas":[],"quesitos_relacionados":[],**{k:v for k,v in d1["questoes_tecnicas"][0].items() if k not in {"id","descricao","alegacoes_relacionadas","quesitos_relacionados"}}} for i in range(1,11)]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"processo.json").write_text(json.dumps(self.processo),encoding="utf-8");(p/"delimitacao-pericial.json").write_text(json.dumps(d1),encoding="utf-8");a=gerar_plano(p);d1["questoes_tecnicas"].reverse();(p/"delimitacao-pericial.json").write_text(json.dumps(d1),encoding="utf-8");b=gerar_plano(p)
        mapa=lambda x:{tuple(a["questoes_tecnicas"]):a["metodo"] for a in x["atividades"]};self.assertEqual(mapa(a),mapa(b));self.assertEqual(len(a["atividades"]),10)
    def test_t_final_07_norma_decorativa_nao_sustenta_causa(self):
        c={"id":"CLM-001","tipo":"CAUSA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"Argamassa causou desplacamento","aspectos_requeridos":["CAUSA"]};n={"id":"NOR-001","tipo":"NORMA","classe_probatoria":"EVIDENCIA_PRIMARIA","proveniencia":["fonte"],"aspectos_suportados":["CONFORMIDADE_NORMATIVA"],"aspectos_contraditos":[],"acessivel":True};self.assertEqual(auditar_claim(c,[n],[n])["veredito"],"UNSUBSTANTIATED")
    def test_t_final_08_requisito_normativo_verificado_sustenta_claim(self):
        c={"id":"CLM-001","tipo":"REQUISITO_NORMATIVO","natureza":"FACTUAL","saliencia":"LOAD_BEARING","texto":"Requisito X verificado","aspectos_requeridos":["REQUISITO_NORMATIVO_VERIFICADO"]};n={"id":"NOR-001","tipo":"NORMA","classe_probatoria":"EVIDENCIA_PRIMARIA","proveniencia":["fonte"],"aspectos_suportados":["REQUISITO_NORMATIVO_VERIFICADO"],"aspectos_contraditos":[],"acessivel":True};self.assertEqual(auditar_claim(c,[n],[n])["veredito"],"GROUNDED")
    def test_t_final_09_norma_posterior(self):self.assertEqual(aplicabilidade_temporal({"edicao":"2022","verificada":True,"requisito":"X"},"2015"),"NAO_APLICAVEL")
    def test_t_final_10_oficial_prevalece_na_reconciliacao(self):
        r=reconciliar_fontes([{"id":"SEC","url":"https://blog.invalid/x","status_vigencia":"VIGENTE"},{"id":"OFI","url":"https://www.gov.br/x","oficial":True,"status_vigencia":"REVOGADA"}]);self.assertEqual(r["fonte_prevalente"],"OFI");self.assertIn("SEC",r["fontes_rejeitadas"])
    def test_t_final_11_proposition_material_sem_fonte_nao_e_auditada(self):
        c={"id":"CLM-001","tipo":"REQUISITO_NORMATIVO"};g=[{"claim_id":"CLM-001","veredito":"UNVERIFIABLE","evidencias":[]}];self.assertEqual(auditar_proposicoes([c],g,[])[0]["verdict"],"UNVERIFIABLE")
    def test_t_final_12_autocorrecao_muda_pat(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([self.obs()]));self.assertIsNone(r["analise_inicial"]["patologias"][0]["causa"]);self.assertIsNone(r["analise_final"]["patologias"][0]["causa"])
    def test_t_final_13_pat_final_revalidado(self):self.assertEqual(self.forte()["erros_finais"],[])
    def test_t_final_14_apto_autonomo(self):
        r=self.forte();self.assertEqual(r["gate"],"APTO_PARA_REDACAO");self.assertTrue(r["analise_final"]["patologias"][0]["vicio_construtivo"]["caracterizado"])
    def test_t_final_15_apto_com_ressalvas(self):self.assertEqual(executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([self.obs()]))["gate"],"APTO_PARA_REDACAO_COM_RESSALVAS")
    def test_t_final_16_bloqueado(self):
        o=self.obs();o["alegacoes"]=["ALG-999"];self.assertEqual(executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([o]))["gate"],"BLOQUEADO_PARA_REDACAO")
    def test_e2e_final_01_vicio_endogeno_autonomo(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/"documentos").mkdir();manifesto=load("tests/fixtures/pje/manifesto-minimo-valido.json");doc=load("tests/fixtures/pje/documento-simples-valido.json");texto="A autora alega infiltracao, fissura, trinca e descolamento no imovel adquirido, decorrentes de vicio construtivo. Requer pericia para determinar causa.\nQUESITOS:\n1. Existe umidade na parede?";doc["paginas"][0]["texto_bruto"]=texto;doc["blocos_texto"]=[{"bloco_id":"BLT-001","texto":texto,"pagina":doc["paginas"][0]["referencia"],"proveniencia":doc["fontes"][0]}];(d/"manifesto-pje.json").write_text(json.dumps(manifesto),encoding="utf-8");(d/"documentos/DOC-PJE-001.json").write_text(json.dumps(doc),encoding="utf-8")
            delim=gerar_delimitacao(d);(d/"delimitacao-pericial.json").write_text(json.dumps(delim),encoding="utf-8");processo=gerar_processo(d);(d/"processo.json").write_text(json.dumps(processo),encoding="utf-8");delim=aprofundar(d);(d/"delimitacao-pericial.json").write_text(json.dumps(delim),encoding="utf-8");plano=gerar_plano(d);campo=d/"campo";campo.mkdir()
            for i,a in enumerate(plano["atividades"],1):(campo/f"nota-{i}.txt").write_text(f"tipo=OBS;descricao=interface sob chuva com vedação deteriorada;manifestacao=umidade;resultado=OBSERVADO;sistema=IMPERMEABILIZACAO;ambiente=Sala sintética;elemento=Parede;atividade_planejada={a['id']}",encoding="utf-8")
            for i,m in enumerate(plano["medicoes"],1):(campo/f"med-{i}.txt").write_text(f"tipo=MED;grandeza=abertura;valor=0,2;unidade=mm;medicao_planejada={m['id']}",encoding="utf-8")
            (campo/"foto-interface.jpg").write_bytes(b"imagem sintetica")
            vistoria=gerar_vistoria(inventariar(campo),plano,processo["numero_processo"]);norma={"id":"NOR-001","titulo":"Requisito sintético de impermeabilização","requisito":"Interface deve atender ao requisito X","verificada":True,"edicao":"2010","pagina":1,"item":"1","tipo_requisito":"DESEMPENHO","metodo_verificacao":"Inspeção e medição","criterio":"Requisito X","proveniencia":["https://oficial.example/norma"],"sistema":"IMPERMEABILIZACAO","classificacao_fonte":"FONTE_PRIMARIA_OFICIAL","entidade":"Entidade sintética","documento":"Norma sintética","dominio":"oficial.example","url":"https://oficial.example/norma","dominio_oficial":True,"status_verificacao":"VERIFICADO","escopo_fonte":"CONTEUDO_NORMATIVO","conteudo_normativo_verificado":True,"conteudo_consultado":"Interface deve atender ao requisito X"};docs=[{"id":"DOC-VIS-001","descricao":"Projeto executivo com detalhe executivo especifica vedação.","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-DOC-001"]},{"id":"DOC-VIS-002","descricao":"Controle tecnológico documenta execução divergente e resultado incompatível com o requisito.","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-DOC-002"]}];r=executar_pipeline_motor(processo,delim,plano,vistoria,{"normas":[norma],"documentos":docs,"data_relevante":"2015"})
        p=r["analise_final"]["patologias"][0];self.assertTrue(vistoria["fotografias"] and vistoria["medicoes"]);self.assertEqual((p["causa"],p["origem"],p["vicio_construtivo"]["caracterizado"],r["gate"]),("falha de vedação","ENDOGENA_CONSTRUTIVA",True,"APTO_PARA_REDACAO"))
    def test_e2e_final_02_autocorrecao_conservadora(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([self.obs()]));pi=r["analise_inicial"]["patologias"][0];pf=r["analise_final"]["patologias"][0]
        self.assertIsNone(pi["causa"]);self.assertIsNone(pf["causa"]);self.assertEqual(pf["origem"],"INCONCLUSIVA");self.assertEqual(r["gate"],"APTO_PARA_REDACAO_COM_RESSALVAS")
    def test_e2e_final_03_medicao_indispensavel_bloqueia(self):
        plano=copy.deepcopy(self.plano);plano["medicoes"]=[{"id":"MED-PLANO-001","obrigatoriedade":"OBRIGATORIA"}];v=self.vistoria([self.obs()]);v["cobertura"]=[{"tipo":"MEDICAO","planejado":"MED-PLANO-001","status":"NAO_EXECUTADO","executado":[],"evidencia_equivalente":[],"impacto":"Medição indispensável ausente."}]
        self.assertEqual(executar_pipeline_motor(self.processo,self.delim,plano,v)["gate"],"BLOQUEADO_PARA_REDACAO")
    def test_escala_150_alg_120_que_80_documentos(self):
        processo=copy.deepcopy(self.processo);processo["alegacoes"]=[{"id":f"ALG-{i:03d}","sistema_alegado":"VEDACOES"} for i in range(1,151)];processo["documentos_tecnicos"]=[f"DOC-PJE-{i:03d}" for i in range(1,81)]
        delim=copy.deepcopy(self.delim);modelo=delim["questoes_tecnicas"][0];delim["questoes_tecnicas"]=[{**copy.deepcopy(modelo),"id":f"QT-{i:03d}","descricao":f"Verificar manifestação sintética {i}","alegacoes_relacionadas":[f"ALG-{i:03d}"],"quesitos_relacionados":[f"QUE-{i:03d}"] if i<=120 else []} for i in range(1,151)];delim["quesitos"]=[{"id":f"QUE-{i:03d}","pertinencia":"PERTINENTE_TECNICO","questoes_tecnicas_relacionadas":[f"QT-{i:03d}"]} for i in range(1,121)]
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"processo.json").write_text(json.dumps(processo),encoding="utf-8");(p/"delimitacao-pericial.json").write_text(json.dumps(delim),encoding="utf-8");inicio=time.perf_counter();plano=gerar_plano(p);duracao=time.perf_counter()-inicio
        self.assertEqual((len(processo["alegacoes"]),len(delim["quesitos"]),len(processo["documentos_tecnicos"])),(150,120,80));self.assertEqual(len(plano["atividades"]),150);self.assertEqual(len({x["id"] for x in plano["atividades"]}),150);self.assertTrue(all(len(c["atividades"])==1 for c in plano["cobertura"]));self.assertLess(duracao,5)

if __name__=="__main__":unittest.main()
