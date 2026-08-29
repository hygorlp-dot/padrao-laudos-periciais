import copy
import json
import unittest
from pathlib import Path

from scripts.auditoria_pericial import auditar_aspecto,executar_detector
from scripts.auditoria_pericial.detector import detectar_cenario_tautologico
from scripts.auditoria_pericial.proposition import auditar_proposicoes
from scripts.motor_vicios.evidencias import construir_catalogo,consolidar_aspectos,pontuar_associacao
from scripts.motor_vicios.normas import avaliar_conformidade_normativa
from scripts.motor_vicios.pipeline import executar_pipeline_motor
from scripts.motor_vicios.validar_motor import validar

RAIZ=Path(__file__).resolve().parents[1]
def load(p):return json.loads((RAIZ/p).read_text(encoding="utf-8"))

class AceitacaoControladaSkillsTest(unittest.TestCase):
    def setUp(self):
        self.processo=load("tests/fixtures/schemas/processo-valido.json");self.delim=load("tests/fixtures/triagem/delimitacao-minima-valida.json");self.plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json");self.vistoria=load("tests/fixtures/schemas/vistoria-valida.json")
    def obs(self,i,texto,**extra):
        x={"id":f"OBS-{i:03d}","descricao_objetiva":texto,"resultado":"OBSERVADO","ambiente":"Sala","trecho":"T1","elemento":"Junta","sistema":"IMPERMEABILIZACAO","manifestacao":"umidade","metodo":["INSPECAO_VISUAL"],"fotografias":[],"medicoes":[],"alegacoes":["ALG-001"],"questoes":["QT-001"],"quesitos":["QUE-001"],"proveniencia":[f"ARQ-{i:03d}"]};x.update(extra);return x
    def norma(self,limite=.5):
        return {"id":"NOR-001","titulo":"Norma sintetica","numero":"1","requisito":"Abertura maxima","verificada":True,"vigencia_inicio":"2010-01-01","data_relevante":"2020-01-01","metodo_verificacao":"Medicao direta","criterio":{"operador":"<=","valor":limite,"unidade":"mm","grandeza":"abertura"},"proveniencia":["NOR-LOCAL"],"sistema":"IMPERMEABILIZACAO","classificacao_fonte":"FONTE_TECNICA_LOCAL_VERIFICADA","entidade":"Entidade sintetica","status_verificacao":"VERIFICADO"}

    def test_parafrases_e_negativo_proximo(self):
        textos=["vedação deteriorada","selagem da junta encontra-se degradada","material de fechamento da interface apresenta perda de integridade"]
        for i,texto in enumerate(textos,1):self.assertIn("VEDACAO_DETERIORADA",construir_catalogo({"observacoes":[self.obs(i,texto)]})[0]["aspectos_suportados"])
        self.assertNotIn("VEDACAO_DETERIORADA",construir_catalogo({"observacoes":[self.obs(9,"vedação aparenta íntegra")]})[0]["aspectos_suportados"])
    def test_contradicao_respeita_trecho(self):
        cat=construir_catalogo({"observacoes":[self.obs(1,"vedação deteriorada",trecho="A"),self.obs(2,"vedação íntegra",trecho="B")]});self.assertTrue(all(x["status"]=="GROUNDED" for x in consolidar_aspectos(cat)))
        cat[1]["trecho"]="A";self.assertIn("CONTRADICTED",{x["status"] for x in consolidar_aspectos(cat)})
    def test_claim_audit_atua_em_evidencia_aspecto(self):
        e=construir_catalogo({"observacoes":[self.obs(1,"vedação deteriorada")]})[0];self.assertEqual(auditar_aspecto(e,"VEDACAO_DETERIORADA")["veredito"],"GROUNDED");self.assertEqual(e["auditoria_aspectos"][1]["modo"],"INTEGRACAO_METODOLOGICA_ADAPTADA")

    def test_adv_final_01_foto_planejada_nao_prova(self):
        f={"id":"FOT-001","finalidade_planejada":"registrar umidade por falha de vedação","descricao_visual_observada":None,"proveniencia":["ARQ-FOT"]};e=construir_catalogo({"fotografias":[f]})[0];self.assertEqual(e["aspectos_suportados"],[])
    def test_e2e_fot_interpretada_aspecto_claim_pat(self):
        f={"id":"FOT-001","finalidade_planejada":"registrar falha","descricao_visual_observada":"mancha localizada junto à interface","ambiente":"Sala","sistema":"IMPERMEABILIZACAO","questoes":["QT-001"],"proveniencia":["ARQ-FOT"]};o=self.obs(1,"mancha localizada junto à interface",fotografias=["FOT-001"]);v=copy.deepcopy(self.vistoria);v["observacoes"]=[o];v["fotografias"]=[f];cat=construir_catalogo(v);foto=next(e for e in cat if e["id"]=="FOT-001");audit=auditar_aspecto(foto,"MANCHA_VISIVEL");r=executar_pipeline_motor(self.processo,self.delim,self.plano,v)
        self.assertEqual(audit["veredito"],"GROUNDED");self.assertIn("FOT-001",r["analise_final"]["patologias"][0]["constatacao"]["fotografias"])
        claim=next(c for c in r["claims_finais"] if c.get("evidencia_id")=="FOT-001" and "MANCHA_VISIVEL" in c["aspectos_requeridos"]);ground=next(a for a in r["grounding_final"] if a["claim_id"]==claim["id"]);self.assertEqual((ground["veredito"],ground["evidencias"]),("GROUNDED",["FOT-001"]))

    def test_e2e_nor_01_02_03(self):
        n=self.norma();base={"id":"MED-001","tipo":"MEDICAO","grandeza":"abertura","unidade":"mm"}
        self.assertEqual(avaliar_conformidade_normativa(n,[{**base,"valor":.4}])["resultado"],"ATENDE");self.assertEqual(avaliar_conformidade_normativa(n,[{**base,"valor":.8}])["resultado"],"NAO_ATENDE");self.assertEqual(avaliar_conformidade_normativa(n,[])["resultado"],"INCONCLUSIVO")
    def test_e2e_norma_requisito_medicao_comparacao_claim_grounding(self):
        v=copy.deepcopy(self.vistoria);v["medicoes"]=[{"id":"MED-001","grandeza":"abertura","valor":.4,"unidade":"mm","anotacao":"abertura medida","ambiente":"Ambiente fictício","sistema":"REVESTIMENTOS","questoes":["QT-001"],"proveniencia":["ARQ-MED-001"]}];v["observacoes"][0]["medicoes"]=["MED-001"]
        n=self.norma();n.update({"titulo":"fissura superficial","sistema":"REVESTIMENTOS"})
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,v,{"normas":[n],"data_relevante":"2020-01-01"});pat=r["analise_final"]["patologias"][0];av=pat["normas_relacionadas"][0]["avaliacao_conformidade"]
        self.assertEqual(av["resultado"],"ATENDE");self.assertEqual(av["evidencias"],["MED-001"])
        claims={c["tipo"]:c for c in r["claims_finais"] if c["tipo"] in {"REQUISITO_NORMATIVO","CONFORMIDADE_NORMATIVA"}};audits={a["tipo"]:a for a in r["grounding_final"] if a["tipo"] in claims}
        self.assertEqual(claims["REQUISITO_NORMATIVO"]["aspectos_requeridos"],["REQUISITO_NORMATIVO_VERIFICADO"]);self.assertEqual(set(claims["CONFORMIDADE_NORMATIVA"]["aspectos_requeridos"]),{"REQUISITO_NORMATIVO_VERIFICADO","MEDICAO_REGISTRADA"});self.assertEqual(audits["REQUISITO_NORMATIVO"]["veredito"],"GROUNDED");self.assertEqual(audits["CONFORMIDADE_NORMATIVA"]["veredito"],"GROUNDED")
        for valor,esperado in ((.8,"NAO_ATENDE"),(None,"INCONCLUSIVO")):
            variante=copy.deepcopy(v)
            if valor is None:variante["medicoes"]=[];variante["observacoes"][0]["medicoes"]=[]
            else:variante["medicoes"][0]["valor"]=valor
            obtido=executar_pipeline_motor(self.processo,self.delim,self.plano,variante,{"normas":[n],"data_relevante":"2020-01-01"});self.assertEqual(obtido["analise_final"]["patologias"][0]["normas_relacionadas"][0]["avaliacao_conformidade"]["resultado"],esperado)
            if esperado=="INCONCLUSIVO":self.assertFalse(any(c["tipo"]=="CONFORMIDADE_NORMATIVA" for c in obtido["claims_finais"]))
    def test_proposition_audit_verifica_requisito_nao_conformidade(self):
        claim={"id":"CLM-001","tipo":"REQUISITO_NORMATIVO"};g={"claim_id":"CLM-001","veredito":"GROUNDED","evidencias":["NOR-001"]};e={"id":"NOR-001","tipo":"NORMA","acessivel":True,"proveniencia":["https://www.abnt.org.br/norma"],"classe_probatoria":"EVIDENCIA_PRIMARIA","aspectos_suportados":["REQUISITO_NORMATIVO_VERIFICADO"],"aspectos_contraditos":[],"classificacao_fonte":"FONTE_PRIMARIA_OFICIAL","entidade":"Entidade sintética","documento":"Norma sintética","dominio":"abnt.org.br","url":"https://www.abnt.org.br/norma","dominio_oficial":True,"status_verificacao":"VERIFICADO","escopo_fonte":"CONTEUDO_NORMATIVO","conteudo_normativo_verificado":True,"conteudo_consultado":"requisito sintético","requisito":"requisito sintético"};r=auditar_proposicoes([claim],[g],[e])[0];self.assertEqual((r["verdict"],r["authority"]),("SUPPORTED","FONTE_PRIMARIA_OFICIAL"))

    def test_doc_e_ensaio_associacao_positiva_ambigua(self):
        ctx={"questoes":["QT-001"],"sistema":"FACHADA","ambiente":"Sala"};self.assertEqual(pontuar_associacao({"questoes":["QT-001"],"sistema":"FACHADA"},ctx)["confianca"],"ALTA");self.assertEqual(pontuar_associacao({"descricao":"Manual da piscina","sistema":"PISCINA"},ctx)["status"],"PENDENTE_ASSOCIACAO");self.assertEqual(pontuar_associacao({"ambiente":"Cobertura"},ctx)["status"],"PENDENTE_ASSOCIACAO")
    def test_adv_final_06_consequencia_null_invalida(self):
        r=executar_pipeline_motor(self.processo,self.delim,self.plano,self.vistoria);obj=copy.deepcopy(r["analise_final"]);obj["patologias"][0]["consequencias"]["seguranca"]=None;self.assertTrue(validar(obj,self.processo,self.delim,self.plano,self.vistoria))
    def test_detectores_novos(self):
        base={"patologias":[],"questoes_saneadas":[],"cobertura_quesitos":[],"catalogo_evidencias":[{"id":"FOT-001","tipo":"FOTOGRAFIA","estado_interpretacao":"NAO_INTERPRETADA","aspectos_suportados":["MANCHA_VISIVEL"]},{"id":"NOR-001","tipo":"NORMA","aspectos_suportados":["CONFORMIDADE_NORMATIVA"]}]};tipos={x["tipo"] for x in executar_detector(base)};self.assertIn("FOT_NAO_INTERPRETADA_USADA_COMO_PROVA",tipos);self.assertIn("NORMA_SOZINHA_PROVA_CONFORMIDADE",tipos)
    def test_adv_final_09_sem_cenario_tautologico(self):
        fonte=(RAIZ/"tests/test_motor_vicios.py").read_text(encoding="utf-8");self.assertEqual(detectar_cenario_tautologico(fonte),[]);self.assertTrue(detectar_cenario_tautologico("self.assertEqual(entrada, entrada)"))

if __name__=="__main__":unittest.main()
