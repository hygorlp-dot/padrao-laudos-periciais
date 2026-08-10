import copy
import unittest

from scripts.auditoria_pericial.deep_audit import executar_deep_audit
from scripts.auditoria_pericial.detector import executar_detector
from scripts.auditoria_pericial.proposition import auditar_proposicoes,classificar_autoridade
from scripts.motor_vicios.autocorrigir import autocorrigir
from scripts.motor_vicios.evidencias import construir_catalogo
from scripts.motor_vicios.regras import inferir_origem,avaliar_consequencias,derivar_criticidade

def obs(i,texto,**extra):
    dado={"id":f"OBS-{i:03d}","descricao_objetiva":texto,"resultado":"OBSERVADO","proveniencia":[f"FONTE-{i:03d}"]};dado.update(extra);return dado

def catalogo(*textos):return construir_catalogo({"observacoes":[obs(i,t) for i,t in enumerate(textos,1)]})

def proposicao(fonte):
    claim={"id":"CLM-001","tipo":"REQUISITO_NORMATIVO"};ground={"claim_id":"CLM-001","veredito":"GROUNDED","evidencias":[fonte["id"]]};return auditar_proposicoes([claim],[ground],[fonte])[0]

class CorrecaoCirurgicaMotorV1Test(unittest.TestCase):
    def test_neg_01_02_03_e_blind_01_02(self):
        for texto,proibido in (("Não foi observado impacto posterior.","IMPACTO_REGISTRADO"),("Não há risco grave de segurança.","RISCO_SEGURANCA_REGISTRADO"),("Não há perda de funcionalidade.","PERDA_FUNCIONAL_REGISTRADA"),("Não foi observado impacto posterior ou intervenção externa.","IMPACTO_REGISTRADO")):
            e=catalogo(texto)[0];self.assertNotIn(proibido,e["aspectos_suportados"]);self.assertIn(proibido,e["aspectos_contraditos"])
        c=catalogo("Não foram observados indícios de instabilidade ou risco grave de segurança.");self.assertNotEqual(derivar_criticidade("ANOMALIA",avaliar_consequencias("ANOMALIA",c))[0],"CRITICA")

    def test_neg_04_05_07_08(self):
        e=catalogo("Sem sinais de infiltração ativa.")[0];self.assertIn("INFILTRACAO_ATIVA",e["aspectos_contraditos"]);self.assertNotIn("INFILTRACAO_ATIVA",e["aspectos_suportados"])
        causa=catalogo("Não foi possível determinar a causa.")[0]["auditoria_aspectos"];self.assertTrue(any(a["aspecto"]=="CAUSA_INCONCLUSIVA" and a["polaridade"]=="INCERTO" for a in causa))
        hipotese=catalogo("Não se pode descartar hipótese de infiltração.")[0]["auditoria_aspectos"];self.assertTrue(any(a["aspecto"]=="INFILTRACAO_ATIVA" and a["polaridade"]=="HIPOTETICO" for a in hipotese))
        self.assertIn("AUSENCIA_DEGRAU",catalogo("Ausência de degrau.")[0]["aspectos_suportados"])

    def test_neg_06_e_blind_07_duas_polaridades(self):
        a=catalogo("Não há fissura na parede, mas existe fissura no teto.")[0]["auditoria_aspectos"];f=[x for x in a if x["aspecto"]=="FISSURA_PRESENTE"];self.assertEqual([(x["localizacao"],x["polaridade"]) for x in f],[("PAREDE","NEGADO"),("TETO","AFIRMADO")])

    def test_grounding_inicial_nao_e_circular(self):
        e=catalogo("Vedação deteriorada.")[0];a=next(x for x in e["auditoria_aspectos"] if x["aspecto"]=="VEDACAO_DETERIORADA");self.assertFalse(a["aspectos_derivados_consultados"]);self.assertIn("vedacao deteriorada",a["trecho_fonte"].lower())
        neg=catalogo("Não houve impacto posterior.")[0];a=next(x for x in neg["auditoria_aspectos"] if x["aspecto"]=="IMPACTO_REGISTRADO");self.assertEqual(a["veredito"],"CONTRADICTED")

    def test_ori_01_e_blind_03_estado_repetido_nao_e_origem(self):self.assertEqual(inferir_origem("falha de vedação",catalogo("interface com vedação deteriorada","interface com vedação deteriorada")),"INCONCLUSIVA")

    def test_ori_02_e_blind_04_endogena_com_nexo_construtivo(self):
        e=catalogo("projeto executivo com detalhe executivo","execução divergente e resultado incompatível com o requisito");self.assertEqual(inferir_origem("não conformidade executiva",e),"ENDOGENA_CONSTRUTIVA")

    def test_ori_03_a_06_outras_origens(self):
        self.assertEqual(inferir_origem("evento posterior",catalogo("impacto posterior em obra de terceiro","avaria por impacto e intervenção externa")),"EXOGENA")
        self.assertEqual(inferir_origem("manutenção",catalogo("ausência de manutenção e uso inadequado","sem manutenção e operação inadequada")),"USO_OPERACAO_MANUTENCAO")
        self.assertEqual(inferir_origem("funcional",catalogo("fenômeno inerente ao comportamento funcional","funcionamento normal e comportamento funcional")),"FUNCIONAL")
        misto=catalogo("projeto executivo com detalhe executivo e ausência de manutenção e uso inadequado","execução divergente, sem manutenção e operação inadequada");self.assertEqual(inferir_origem("contribuições convergentes",misto),"MISTA")

    def test_nor_auth_01_02_e_blind_05(self):
        blog={"id":"NOR-001","tipo":"NORMA","acessivel":True,"proveniencia":["BLOG-SECUNDARIO"],"classificacao_fonte":"FONTE_SECUNDARIA","escopo_fonte":"CONTEUDO_NORMATIVO","conteudo_normativo_verificado":True,"conteudo_consultado":"requisito x","requisito":"requisito x"};self.assertEqual(proposicao(blog)["authority"],"FONTE_SECUNDARIA");self.assertNotEqual(proposicao(blog)["verdict"],"SUPPORTED")
        oficial={**blog,"proveniencia":["https://oficial.example/norma"],"classificacao_fonte":"FONTE_PRIMARIA_OFICIAL","entidade":"Entidade oficial sintética","documento":"Documento sintético","dominio":"oficial.example","url":"https://oficial.example/norma","dominio_oficial":True,"status_verificacao":"VERIFICADO"};self.assertEqual((proposicao(oficial)["authority"],proposicao(oficial)["verdict"]),("FONTE_PRIMARIA_OFICIAL","SUPPORTED"))

    def test_nor_auth_03_04_05_e_blind_06(self):
        metadata={"id":"NOR-001","tipo":"NORMA","acessivel":True,"proveniencia":["CATALOGO-OFICIAL"],"classificacao_fonte":"FONTE_PRIMARIA_OFICIAL","entidade":"ABNT","documento":"Catálogo","dominio":"abnt.org.br","url":"https://abnt.org.br/catalogo","dominio_oficial":True,"status_verificacao":"VERIFICADO","escopo_fonte":"METADADOS","requisito":"item 5.3 determina X"};self.assertEqual(proposicao(metadata)["verdict"],"UNVERIFIABLE")
        conteudo={**metadata,"escopo_fonte":"CONTEUDO_NORMATIVO","conteudo_normativo_verificado":True,"conteudo_consultado":"O item 5.3 determina X."};self.assertEqual(proposicao(conteudo)["verdict"],"SUPPORTED")
        blog={**conteudo,"id":"NOR-002","classificacao_fonte":"FONTE_SECUNDARIA","proveniencia":["BLOG"]};self.assertEqual(classificar_autoridade(conteudo),"FONTE_PRIMARIA_OFICIAL");self.assertEqual(classificar_autoridade(blog),"FONTE_SECUNDARIA")

    def test_detectores_deep_e_autocorrecao(self):
        e={"id":"OBS-001","tipo":"OBSERVACAO","aspectos_suportados":["IMPACTO_REGISTRADO"],"auditoria_aspectos":[{"aspecto":"IMPACTO_REGISTRADO","polaridade":"NEGADO","aspectos_derivados_consultados":True}]};n={"id":"NOR-001","tipo":"NORMA","authority":"FONTE_PRIMARIA_OFICIAL","classificacao_fonte":"FONTE_SECUNDARIA"};pat={"id":"PAT-001","origem":"ENDOGENA_CONSTRUTIVA","evidencias":["OBS-001"],"analise_causal":{"aspectos_origem":[]},"vicio_construtivo":{"caracterizado":True},"recomendacao":{"necessaria":True,"descricao":{}},"reparabilidade":"REPARAVEL","elegibilidade_orcamento":"ELEGIVEL_ORCAMENTO_VICIO","normas_relacionadas":[]};resultado={"patologias":[pat],"catalogo_evidencias":[e,n],"cobertura_quesitos":[],"questoes_saneadas":[]}
        tipos={x["tipo"] for x in executar_detector(resultado)};self.assertTrue({"NEGACAO_CONVERTIDA_EM_FATO","ASPECTO_AUTO_GROUNDED","ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA","AUTORIDADE_NORMATIVA_AUTODECLARADA"}<=tipos)
        profundos={x["tipo"] for x in executar_deep_audit([],resultado)};self.assertTrue({"NEGACAO_CONVERTIDA_EM_FATO","ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA","AUTORIDADE_NORMATIVA_AUTODECLARADA"}<=profundos)
        final,_=autocorrigir(resultado,[],[],executar_deep_audit([],resultado));self.assertEqual(final["patologias"][0]["origem"],"INCONCLUSIVA");self.assertFalse(final["patologias"][0]["vicio_construtivo"]["caracterizado"]);self.assertEqual(final["catalogo_evidencias"][0]["aspectos_suportados"],[]);self.assertEqual(final["catalogo_evidencias"][1]["authority"],"NAO_DETERMINADA")

if __name__=="__main__":unittest.main()
