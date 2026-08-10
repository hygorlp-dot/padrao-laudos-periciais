import json, tempfile, unittest
from pathlib import Path

from scripts.motor_vicios.auditar import auditar
from scripts.motor_vicios.motor import executar
from scripts.motor_vicios.granularizar_questoes import granularizar
from scripts.motor_vicios.hipoteses import gerar as gerar_hipoteses
from scripts.motor_vicios.regras import classificacoes, situacao
from scripts.motor_vicios.validar_motor import validar
from scripts.motor_vicios.cenarios import executar_cenario
from scripts.vistoria_estruturada.gerar_vistoria import gerar
from scripts.vistoria_estruturada.inventariar_vistoria import inventariar

RAIZ=Path(__file__).resolve().parents[1]
def carregar(p):return json.loads((RAIZ/p).read_text(encoding="utf-8"))

class MotorViciosTest(unittest.TestCase):
    def setUp(self):
        self.processo=carregar("tests/fixtures/schemas/processo-valido.json")
        self.delimitacao=carregar("tests/fixtures/triagem/delimitacao-minima-valida.json")
        self.plano=carregar("tests/fixtures/planejamento/plano-vistoria-valido.json")
    def obs(self,resultado="OBSERVADO",manifestacao="umidade"):
        return {"id":"OBS-001","local":"Local fictício","ambiente":"Ambiente fictício","sistema":"IMPERMEABILIZACAO","elemento":"Parede","descricao_objetiva":"Sinal objetivo fictício.","manifestacao":manifestacao,"resultado":resultado,"campo_examinado":"Superfície acessível","metodo":["INSPECAO_VISUAL"],"fotografias":[],"medicoes":[],"alegacoes":["ALG-001"],"questoes":["QT-001"],"quesitos":["QUE-001"],"confianca":{"nivel":"ALTA"},"proveniencia":["ARQ-VIS-001"],"limitacoes":[]}
    def vistoria(self,obs):
        v=carregar("tests/fixtures/schemas/vistoria-valida.json");v["observacoes"]=[obs];return v
    def test_aguarda_sem_dados_e_nao_inventa(self):
        v=gerar({"arquivos":[],"status":"SEM_DADOS_DE_VISTORIA"},self.plano,self.processo["numero_processo"])
        r=executar(self.processo,self.delimitacao,self.plano,v)
        self.assertEqual(r["status_execucao"],"AGUARDANDO_DADOS_DE_VISTORIA");self.assertEqual(r["patologias"],[]);self.assertFalse(validar(r))
    def test_nao_constatado_nao_vira_inexistente(self):
        r=executar(self.processo,self.delimitacao,self.plano,self.vistoria(self.obs("NAO_CONSTATADO_NA_VISTORIA")))
        p=r["patologias"][0];self.assertEqual(p["constatacao"]["situacao"],"NAO_CONSTATADA");self.assertNotIn("inexist",p["conclusao_tecnica"].lower());self.assertFalse(validar(r))
    def test_anomalia_nao_vira_vicio_automaticamente(self):
        r=executar(self.processo,self.delimitacao,self.plano,self.vistoria(self.obs()))
        p=r["patologias"][0];self.assertEqual(p["constatacao"]["situacao"],"ANOMALIA");self.assertFalse(p["vicio_construtivo"]["caracterizado"]);self.assertEqual(p["origem"],"INCONCLUSIVA")
    def test_vicio_exige_evidencia_causa_e_origem(self):
        base={"origem":"ENDOGENA_CONSTRUTIVA","causa":"execução fictícia","evidencias":["OBS-001"],"reparo_definido":True,"fundamentacao_criticidade":"Impacto fictício","criticidade":"MEDIA"}
        self.assertTrue(classificacoes("ANOMALIA",base)[2]);base["evidencias"]=[];self.assertFalse(classificacoes("ANOMALIA",base)[2])
    def test_declaracao_nao_e_observacao(self):
        v=self.vistoria(self.obs());v["declaracoes"]=[{"id":"DEC-VIS-001","natureza":"DECLARADO_POR_TERCEIRO","declarante":"Pessoa fictícia","texto_original":"Relato fictício.","questoes":[],"alegacoes":[],"proveniencia":["ARQ-VIS-002"]}]
        r=executar(self.processo,self.delimitacao,self.plano,v);self.assertEqual(r["patologias"][0]["constatacoes"],["OBS-001"])
    def test_auditoria_bloqueia_contradicao(self):
        r=executar(self.processo,self.delimitacao,self.plano,self.vistoria(self.obs("NAO_CONSTATADO_NA_VISTORIA")));r["patologias"][0]["conclusao_tecnica"]="A manifestação inexiste.";a=auditar(r);self.assertTrue(any(x["tipo"]=="NAO_CONSTATADA_COMO_INEXISTENTE" for x in a))
    def test_motor_nao_aplica_a_outro_tipo(self):
        d=json.loads(json.dumps(self.delimitacao));d["tipo_pericia"]["tipo"]="AVALIACAO_IMOBILIARIA";r=executar(self.processo,d,self.plano,self.vistoria(self.obs()));self.assertEqual(r["status_execucao"],"MOTOR_ESPECIALIZADO_NAO_IMPLEMENTADO")
    def test_inventario_incremental(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"nota.txt").write_text("Conteúdo integralmente fictício.",encoding="utf-8");a=inventariar(p);b=inventariar(p);self.assertEqual(a["arquivos"][0]["sha256"],b["arquivos"][0]["sha256"]);self.assertEqual(b["arquivos"][0]["acao_processamento"],"REUTILIZADO")
    def test_id_incremental_nao_muda_ao_inserir_arquivo_anterior(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"b.txt").write_text("tipo=OBS;descricao=Registro fictício",encoding="utf-8");a=inventariar(p);id_b=a["arquivos"][0]["id"]
            (p/"a.txt").write_text("tipo=OBS;descricao=Outro registro fictício",encoding="utf-8");b=inventariar(p)
            self.assertEqual(next(x for x in b["arquivos"] if x["nome"]=="b.txt")["id"],id_b)
            self.assertEqual(len({x["id"] for x in b["arquivos"]}),2)
    def test_anotacao_estruturada_gera_obs_med_declaracao_e_limitacao(self):
        texto="\n".join(["tipo=OBS;descricao=Fissura visível;manifestacao=fissura;resultado=OBSERVADO","tipo=MED;grandeza=abertura;valor=0,5;unidade=mm","tipo=DECLARACAO;descricao=Relato fictício","tipo=LIMITACAO;descricao=Área inacessível"])
        inv={"arquivos":[{"id":"ARQ-VIS-001","nome":"campo.txt","caminho_relativo":"campo.txt","categoria":"ANOTACAO","metodo_ingestao":"TEXTO_SIMPLES","metadados":{"texto_original":texto}}]}
        v=gerar(inv,self.plano,self.processo["numero_processo"])
        self.assertEqual((len(v["observacoes"]),len(v["medicoes"]),len(v["declaracoes"]),len(v["limitacoes"])),(1,1,1,1))
    def test_situacao_conforme(self):self.assertEqual(situacao([{"resultado":"CONFORME"}]),"CONFORME")
    def test_situacao_falha_e_criticidade_sem_base_inconclusiva(self):
        self.assertEqual(situacao([{"resultado":"FALHA"}]),"FALHA");self.assertEqual(classificacoes("ANOMALIA",{})[1],"INCONCLUSIVA")
    def test_validador_relacional_detecta_referencia_orfa(self):
        r=executar(self.processo,self.delimitacao,self.plano,self.vistoria(self.obs()));r["patologias"][0]["alegacoes_relacionadas"]=["ALG-999"]
        self.assertTrue(any("ALG órfã" in e for e in validar(r,self.processo,self.delimitacao,self.plano,self.vistoria(self.obs()))))
    def test_granularizacao_agrega_repeticoes(self):
        p={"alegacoes":[{"id":"ALG-001","manifestacao_alegada":"Fissura","ambiente_alegado":"Sala","sistema_alegado":"VEDACOES"},{"id":"ALG-002","manifestacao_alegada":"fissura","ambiente_alegado":"sala","sistema_alegado":"VEDACOES"}]}
        q=granularizar(p,{"questoes_tecnicas":[{"id":"QT-001"}]});self.assertEqual(len(q),1);self.assertEqual(q[0]["alegacoes_relacionadas"],["ALG-001","ALG-002"])
    def test_e2e_sintetico_inventario_vistoria_motor(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"campo.txt").write_text("tipo=OBS;descricao=Umidade visível;manifestacao=umidade;resultado=OBSERVADO",encoding="utf-8")
            inv=inventariar(p);v=gerar(inv,self.plano,self.processo["numero_processo"]);v["observacoes"][0]["alegacoes"]=["ALG-001"];v["observacoes"][0]["questoes"]=["QT-001"]
            r=executar(self.processo,self.delimitacao,self.plano,v);self.assertEqual(r["patologias"][0]["id"],"PAT-001");self.assertFalse(validar(r,self.processo,self.delimitacao,self.plano,v))
    def test_gate_apto_sem_ressalva_em_constatacao_conforme(self):
        r=executar(self.processo,self.delimitacao,self.plano,self.vistoria(self.obs("CONFORME",None)))
        self.assertEqual(r["gate_redacao"],"BLOQUEADO_PARA_REDACAO")

    def test_trinta_cenarios_de_risco_executam_comportamento(self):
        cen=carregar("tests/fixtures/motor-vicios-cenarios.json");self.assertEqual(len(cen),30);relatorio=[]
        for caso in cen:
            with self.subTest(caso=caso["id"]):
                obtido=executar_cenario(caso["input"]);self.assertEqual(obtido,caso["expected"]);relatorio.append({"cenario":caso["id"],"funcao_real":"executar_cenario","input":caso["input"],"output":obtido,"expected":caso["expected"],"assert":"EQUAL","status":"APROVADO"})
        self.assertEqual(len(relatorio),30)

if __name__=="__main__":unittest.main()
