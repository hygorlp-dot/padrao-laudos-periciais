import copy
import json
import unittest
from pathlib import Path

from scripts.motor_vicios.evidencias import construir_catalogo
from scripts.motor_vicios.hipoteses import gerar
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.motor_vicios.regras import (avaliar_consequencias, classificacoes,
    derivar_criticidade, estruturar_reparo, inferir_origem, tipo_vicio)
from scripts.vistoria_estruturada.gerar_vistoria import gerar as gerar_vistoria

RAIZ=Path(__file__).resolve().parents[1]
def load(p):return json.loads((RAIZ/p).read_text(encoding="utf-8"))

class BloqueiosFinaisMotorV1Test(unittest.TestCase):
    def setUp(self):
        self.processo=load("tests/fixtures/schemas/processo-valido.json");self.delim=load("tests/fixtures/triagem/delimitacao-minima-valida.json");self.plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json")
    def obs(self,i,texto="Interface sob chuva com vedação deteriorada",**extra):
        dado={"id":f"OBS-{i:03d}","ambiente":"Sala","sistema":"IMPERMEABILIZACAO","elemento":"Parede","descricao_objetiva":texto,"manifestacao":"umidade","resultado":"OBSERVADO","metodo":["INSPECAO_VISUAL"],"fotografias":["FOT-001"],"medicoes":["MED-001"],"alegacoes":["ALG-001"],"questoes":["QT-001"],"quesitos":["QUE-001"],"proveniencia":[f"ARQ-{i:03d}"]};dado.update(extra);return dado
    def vistoria(self,observacoes):
        v=load("tests/fixtures/schemas/vistoria-valida.json");v["observacoes"]=observacoes;v["medicoes"]=[{"id":"MED-001","grandeza":"teor de umidade","valor":18.0,"unidade":"%","ambiente":"Sala","sistema":"IMPERMEABILIZACAO","instrumento":"medidor","questoes":["QT-001"],"proveniencia":["ARQ-MED-001"]}];v["fotografias"]=[{"id":"FOT-001","descricao_objetiva":"Registro da mancha e interface","ambiente":"Sala","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-FOT-001"]}];return v
    def evidencias(self,*textos):
        return construir_catalogo(self.vistoria([self.obs(i+1,t) for i,t in enumerate(textos)]))

    def test_t_blind_01_e_e2e_c1_endogeno_sem_rotulo(self):
        docs=[{"id":"DOC-VIS-001","descricao":"Projeto executivo com detalhe executivo especifica vedação.","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-DOC-1"]},{"id":"DOC-VIS-002","descricao":"Controle tecnológico documenta execução divergente e resultado incompatível com o requisito.","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-DOC-2"]}]
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([self.obs(1),self.obs(2)]),{"documentos":docs});p=r["analise_final"]["patologias"][0]
        self.assertFalse(any("CAUSA:" in str(x) for x in self.vistoria([self.obs(1)])["observacoes"]));self.assertEqual((p["causa"],p["origem"],p["vicio_construtivo"]["caracterizado"]),("falha de vedação","ENDOGENA_CONSTRUTIVA",True))

    def test_t_link_01_med_chega_pat(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([self.obs(1)]));self.assertIn("MED-001",r["analise_final"]["patologias"][0]["medicoes"])
    def test_t_link_02_fot_chega_pat(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([self.obs(1)]));self.assertIn("FOT-001",r["analise_final"]["patologias"][0]["constatacao"]["fotografias"])
    def test_t_link_03_doc_sustenta_hipotese(self):
        cat=construir_catalogo(self.vistoria([self.obs(1)]),[{"id":"DOC-VIS-001","descricao":"Detalhe executivo da interface sob chuva especifica vedação; execução divergente","sistema":"IMPERMEABILIZACAO","proveniencia":["DOC"]}]);self.assertIn("DOC-VIS-001",gerar("umidade","MAN-001",sistema="IMPERMEABILIZACAO",catalogo=cat)[0]["evidencias_favoraveis"])
    def test_t_link_04_ensaio_altera_hipotese(self):
        v=self.vistoria([self.obs(1)]);v["ensaios"]=[{"id":"ENS-001","nome":"Ensaio de estanqueidade","resultado":"pressurização positiva com vazamento","sistema":"IMPERMEABILIZACAO","proveniencia":["ENS"]}];hips=gerar("umidade","MAN-001",sistema="IMPERMEABILIZACAO",catalogo=construir_catalogo(v));self.assertTrue(any("ENS-001" in h["evidencias_favoraveis"] and h["status"]!="NAO_TESTAVEL" for h in hips))

    def test_t_orig_01_a_06(self):
        casos=[("ENDOGENA_CONSTRUTIVA",("projeto executivo com detalhe executivo","execução divergente e resultado incompatível com o requisito")),("EXOGENA",("avaria por impacto posterior em obra de terceiro","registro confirma impacto posterior e intervenção externa")),("FUNCIONAL",("fenômeno inerente ao comportamento funcional normal","ensaio confirma comportamento funcional")),("USO_OPERACAO_MANUTENCAO",("ausência de manutenção e uso inadequado","registro confirma manutenção inadequada e uso inadequado")),("MISTA",("impacto posterior, obra de terceiro, ausência de manutenção e uso inadequado","impacto posterior, intervenção externa, manutenção inadequada e uso inadequado")),("INCONCLUSIVA",("mancha sem elementos causais suficientes",))]
        for esperado,textos in casos:
            with self.subTest(esperado=esperado):self.assertEqual(inferir_origem("causa sustentada",self.evidencias(*textos)),esperado)

    def test_t_crit_01_a_05(self):
        casos=[("risco grave de segurança e instabilidade","CRITICA"),("perda de funcionalidade e degradação relevante","MEDIA"),("anomalia localizada sem repercussão relevante","MINIMA")]
        for texto,esperado in casos:
            ev=[e for e in self.evidencias(texto) if e["tipo"]=="OBSERVACAO"];cons=avaliar_consequencias("ANOMALIA",ev);self.assertEqual(derivar_criticidade("ANOMALIA",cons)[0],esperado)
        self.assertEqual(derivar_criticidade("CONFORME",avaliar_consequencias("CONFORME",[]))[0],"NAO_APLICAVEL");ev=[e for e in self.evidencias("alteração cromática observada") if e["tipo"]=="OBSERVACAO"];self.assertEqual(derivar_criticidade("ANOMALIA",avaliar_consequencias("ANOMALIA",ev))[0],"INCONCLUSIVA")

    def test_t_rep_01_flag_sem_conteudo_nao_elegivel(self):
        self.assertNotEqual(classificacoes("ANOMALIA",{"causa":"x","origem":"ENDOGENA_CONSTRUTIVA","evidencias":["OBS-001"],"reparo_definido":True})[3],"ELEGIVEL_ORCAMENTO_VICIO")
    def test_t_rep_02_reparo_completo_elegivel(self):
        ev=self.evidencias("detalhe executivo e execução divergente");rep=estruturar_reparo("falha executiva","VEDACOES",ev);self.assertEqual(classificacoes("ANOMALIA",{"causa":"x","origem":"ENDOGENA_CONSTRUTIVA","evidencias":["OBS-001"],"reparo":rep})[3],"ELEGIVEL_ORCAMENTO_VICIO")
    def test_t_vicio_tipo_01_a_03(self):
        self.assertEqual(tipo_vicio(self.evidencias("defeito aparente visível em inspeção ordinária"),True),"APARENTE");self.assertEqual(tipo_vicio(self.evidencias("defeito oculto não identificável por inspeção ordinária"),True),"OCULTO");self.assertEqual(tipo_vicio(self.evidencias("sem dado de detectabilidade"),True),"INCONCLUSIVO")

    def test_e2e_c2_exogeno_nao_elegivel(self):
        obs=[self.obs(1,"Avaria localizada por impacto posterior",sistema="REVESTIMENTOS",manifestacao="desplacamento"),self.obs(2,"Avaria localizada por impacto posterior em obra de terceiro",sistema="REVESTIMENTOS",manifestacao="desplacamento")];r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria(obs));p=r["analise_final"]["patologias"][0]
        self.assertEqual(p["origem"],"EXOGENA");self.assertFalse(p["vicio_construtivo"]["caracterizado"]);self.assertEqual(p["elegibilidade_orcamento"],"NAO_ELEGIVEL")
    def test_e2e_c3_inconclusivo_com_ressalva(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria([self.obs(1,"Mancha de umidade sem elemento causal discriminante")]));p=r["analise_final"]["patologias"][0]
        self.assertIsNone(p["causa"]);self.assertEqual(p["origem"],"INCONCLUSIVA");self.assertFalse(p["vicio_construtivo"]["caracterizado"]);self.assertEqual(r["gate"],"APTO_PARA_REDACAO_COM_RESSALVAS")

if __name__=="__main__":unittest.main()
