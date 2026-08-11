import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.extracao_pje.classificar_documentos import classificar_documento
from scripts.extracao_pje.catalogar_imagens import catalogar_imagens
from scripts.triagem_pericial.classificar_tipo import CRITERIOS, classificar
from scripts.triagem_pericial.capabilities import capability, pode_delimitar, pode_planejar
from scripts.planejamento_pericial.validar_plano import validar
from scripts.planejamento_pericial.gerar_plano import gerar as gerar_plano
from scripts.motor_vicios.regras_probatorias import DIMENSOES_CONSTRUTIVAS, DIVERGENCIAS_CONSTRUTIVAS, suporte_endogeno
from scripts.motor_vicios.regras import inferir_origem
from scripts.auditoria_pericial.detector import executar_detector
from scripts.auditoria_pericial.deep_audit import executar_deep_audit
from scripts.terceiros.catalogar_repositorios import classificar_egress, politica_trust, pode_receber_dados_privados
from scripts.terceiros.verificar_atualizacoes import verificar


CONTEXTO={"arquivo":"autos.pdf","sha256":"0"*64,"documento_id":"DOC-PJE-001","id_pje":"900001"}


def documento(texto, ident="DOC-PJE-001", classe="PETICAO_INICIAL"):
    return {"documento_id":ident,"classe_normalizada":classe,"paginas":[{"texto_bruto":texto}]}


class PaginaImagens:
    width,height=600,800
    images=[{"x0":20,"top":100,"x1":220,"bottom":280},{"x0":320,"top":400,"x1":520,"bottom":580},{"x0":10,"top":10,"x1":40,"bottom":40}]
    def extract_text(self):return "Foto 1\nFigura 2"
    def extract_words(self,**_):return [
        {"text":"Foto","x0":20,"top":285,"x1":60,"bottom":300},{"text":"1","x0":65,"top":285,"x1":75,"bottom":300},
        {"text":"Figura","x0":320,"top":585,"x1":375,"bottom":600},{"text":"2","x0":380,"top":585,"x1":390,"bottom":600},
    ]
class LeitorImagens:
    def pagina_geometrica(self,_):return PaginaImagens()


class PaginaImagemAmbigua(PaginaImagens):
    images=[{"x0":20,"top":100,"x1":220,"bottom":280},{"x0":25,"top":105,"x1":225,"bottom":280}]
    def extract_text(self):return "Foto 1"
    def extract_words(self,**_):return [
        {"text":"Foto","x0":20,"top":285,"x1":60,"bottom":300},
        {"text":"1","x0":65,"top":285,"x1":75,"bottom":300},
    ]


class LeitorImagemAmbigua:
    def pagina_geometrica(self,_):return PaginaImagemAmbigua()


class PaginaRotuloSemImagem(PaginaImagemAmbigua):
    images=[]


class LeitorRotuloSemImagem:
    def pagina_geometrica(self,_):return PaginaRotuloSemImagem()


class PaginaDoisRotulosUmaImagem(PaginaImagemAmbigua):
    images=[{"x0":20,"top":100,"x1":220,"bottom":280}]
    def extract_text(self):return "Foto 1 Figura 2"
    def extract_words(self,**_):return [
        {"text":"Foto","x0":20,"top":285,"x1":60,"bottom":300},
        {"text":"1","x0":65,"top":285,"x1":75,"bottom":300},
        {"text":"Figura","x0":20,"top":285,"x1":60,"bottom":300},
        {"text":"2","x0":65,"top":285,"x1":75,"bottom":300},
    ]


class LeitorDoisRotulosUmaImagem:
    def pagina_geometrica(self,_):return PaginaDoisRotulosUmaImagem()


class HardeningAdicionalTest(unittest.TestCase):
    def test_doc_class_parte_artigo_e_ambiguidade(self):
        for titulo in ("Manifestação da parte autora","parte ré","carta de intimação","art. 5º da Constituição"):
            with self.subTest(titulo=titulo):self.assertNotEqual(classificar_documento(titulo,"PETICAO")["classe_normalizada"],"ART_RRT")
        for titulo in ("Anotação de Responsabilidade Técnica","RRT nº 123456"):
            self.assertEqual(classificar_documento(titulo,"DOCUMENTO")["classe_normalizada"],"ART_RRT")
        art=classificar_documento("ART nº 123456","DOCUMENTO","Responsável técnico CREA 123")
        self.assertEqual(art["classe_normalizada"],"ART_RRT")
        ambiguo=classificar_documento("ART","PETICAO","")
        self.assertEqual(ambiguo["status_revisao"],"PENDENTE_REVISAO")
        import scripts.extracao_pje.classificar_documentos as modulo
        regras=modulo.REGRAS_CLASSIFICACAO
        try:
            titulo_composto="Petição inicial com anotação de responsabilidade técnica"
            esperado=classificar_documento(titulo_composto,"DOCUMENTO")
            modulo.REGRAS_CLASSIFICACAO=tuple(reversed(regras))
            self.assertEqual(classificar_documento(titulo_composto,"DOCUMENTO"),esperado)
            self.assertEqual(esperado["classe_normalizada"],"OUTRO")
            self.assertEqual(esperado["status_revisao"],"PENDENTE_REVISAO")
        finally:
            modulo.REGRAS_CLASSIFICACAO=regras

    def test_tipo_pericial_empate_fontes_e_ordem(self):
        empate=classificar([documento("segurança viária")])
        self.assertIn(empate.tipo,{"ENGENHARIA_RODOVIARIA","SEGURANCA_VIARIA"});self.assertIn("SEGURANCA_VIARIA" if empate.tipo=="ENGENHARIA_RODOVIARIA" else "ENGENHARIA_RODOVIARIA",empate.alternativas);self.assertNotEqual(empate.nivel,"ALTA")
        self.assertNotIn("convergência entre múltiplas peças",empate.criterios)
        multipla=classificar([documento("engenharia rodoviária pavimento rodoviário", "DOC-PJE-001"),documento("rodovia federal acostamento", "DOC-PJE-002","DECISAO")])
        self.assertEqual(multipla.tipo,"ENGENHARIA_RODOVIARIA");self.assertIn("convergência entre múltiplas peças independentes",multipla.criterios)
        self.assertEqual(classificar([]).tipo,"OUTRO")
        original=classificar([documento("valor de mercado método comparativo")])
        invertidos=dict(reversed(list(CRITERIOS.items())))
        self.assertEqual(classificar([documento("valor de mercado método comparativo")],criterios=invertidos).tipo,original.tipo)

    def test_registry_cobre_todos_e_bloqueia_perfis_ausentes(self):
        for tipo in (*CRITERIOS,"OUTRO"):
            item=capability(tipo);self.assertEqual(item["TIPO"],tipo)
        for tipo in ("SINISTRO_VIARIO","ORCAMENTO_E_MEDICAO","ESTRUTURAS","TOPOGRAFIA_E_DIVISAS","INSTALACOES_PREDIAIS","SEGURANCA_VIARIA"):
            self.assertFalse(pode_delimitar(tipo));self.assertFalse(pode_planejar(tipo));self.assertEqual(capability(tipo)["STATUS"],"PERFIL_ESPECIALIZADO_NAO_IMPLEMENTADO")
        self.assertTrue(pode_delimitar("OUTRO"));self.assertTrue(pode_planejar("OUTRO"))
        self.assertFalse(pode_planejar("NOVO_TIPO_SEM_CAPABILITY"))
        amostras={
            "VICIOS_CONSTRUTIVOS":"manifestação patológica infiltração fissura",
            "AVALIACAO_IMOBILIARIA":"avaliação imobiliária valor de mercado método comparativo",
            "ENGENHARIA_RODOVIARIA":"engenharia rodoviária pavimento rodoviário acostamento",
            "SINISTRO_VIARIO":"acidente de trânsito sinistro viário animal solto na pista",
            "ORCAMENTO_E_MEDICAO":"medição de serviços planilha orçamentária memória de cálculo",
            "ESTRUTURAS":"perícia estrutural estabilidade estrutural risco de colapso",
            "TOPOGRAFIA_E_DIVISAS":"levantamento topográfico divisa do imóvel georreferenciamento",
            "INSTALACOES_PREDIAIS":"instalação elétrica instalação hidrossanitária rede de esgoto",
            "SEGURANCA_VIARIA":"sinalização de advertência risco na pista",
        }
        for tipo,texto in amostras.items():
            with self.subTest(tipo=tipo):self.assertEqual(classificar([documento(texto)]).tipo,tipo)
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);processo=json.loads(Path("tests/fixtures/schemas/processo-valido.json").read_text(encoding="utf8"));delimitacao=json.loads(Path("tests/fixtures/triagem/delimitacao-minima-valida.json").read_text(encoding="utf8"));delimitacao["tipo_pericia"]["tipo"]="ESTRUTURAS"
            (d/"processo.json").write_text(json.dumps(processo),encoding="utf8");(d/"delimitacao-pericial.json").write_text(json.dumps(delimitacao),encoding="utf8")
            with self.assertRaisesRegex(ValueError,"PERFIL_ESPECIALIZADO_NAO_IMPLEMENTADO"):gerar_plano(d)

    def test_validar_plano_malformado_nunca_crasha(self):
        casos=({}, {"schema_version":"2.0.0","cobertura":None}, {"schema_version":"2.0.0","atividades":["x"]}, {"schema_version":"2.0.0","cobertura":[{}]}, {"schema_version":"9.0.0"})
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"plano.json"
            for caso in casos:
                p.write_text(json.dumps(caso),encoding="utf8");self.assertTrue(validar(p))
            p.write_text("{",encoding="utf8");self.assertTrue(validar(p))

    def test_rotulos_de_imagem_sao_isolados_e_invariantes(self):
        imagens,fotos=catalogar_imagens(LeitorImagens(),1,1,CONTEXTO,1,1)
        self.assertEqual([(f["numero_original"],f["bbox"]["x0"]) for f in fotos],[('1',20.0),('2',320.0)])
        self.assertEqual(imagens[2]["tipo"],"OUTRO")
        PaginaImagens.images=list(reversed(PaginaImagens.images))
        try:
            _,reordenadas=catalogar_imagens(LeitorImagens(),1,1,CONTEXTO,1,1)
            self.assertEqual({(f["numero_original"],f["bbox"]["x0"]) for f in reordenadas},{('1',20.0),('2',320.0)})
        finally:PaginaImagens.images=list(reversed(PaginaImagens.images))
        imagens_ambiguas,fotos_ambiguas=catalogar_imagens(LeitorImagemAmbigua(),1,1,CONTEXTO,1,1)
        self.assertEqual(fotos_ambiguas,[])
        self.assertTrue(all(item["tipo"]=="OUTRO" for item in imagens_ambiguas))
        imagens_sem_rotulo,fotos_sem_rotulo=catalogar_imagens(LeitorRotuloSemImagem(),1,1,CONTEXTO,1,1)
        self.assertEqual((imagens_sem_rotulo,fotos_sem_rotulo),([],[]))
        imagens_duplo_rotulo,fotos_duplo_rotulo=catalogar_imagens(LeitorDoisRotulosUmaImagem(),1,1,CONTEXTO,1,1)
        self.assertEqual(fotos_duplo_rotulo,[])
        self.assertEqual(imagens_duplo_rotulo[0]["tipo"],"OUTRO")

    def test_taxonomia_causal_e_fonte_unica(self):
        dimensao=next(iter(DIMENSOES_CONSTRUTIVAS));divergencia=next(iter(DIVERGENCIAS_CONSTRUTIVAS))
        mesma_fonte=[
            {"id":"DOC-1-A","proveniencia":[{"documento_id":"DOC-1","pagina_pdf":1}],"aspectos_suportados":[dimensao]},
            {"id":"DOC-1-B","proveniencia":[{"documento_id":"DOC-1","pagina_pdf":2}],"aspectos_suportados":[divergencia]},
        ]
        self.assertFalse(suporte_endogeno(mesma_fonte))
        self.assertEqual(inferir_origem("causa",mesma_fonte),"INCONCLUSIVA")
        evidencias=[mesma_fonte[0],{"id":"DOC-2","proveniencia":[{"documento_id":"DOC-2","pagina_pdf":1}],"aspectos_suportados":[divergencia]}]
        self.assertTrue(suporte_endogeno(evidencias))
        self.assertEqual(inferir_origem("causa",evidencias),"ENDOGENA_CONSTRUTIVA")
        pat={"id":"PAT-001","origem":"ENDOGENA_CONSTRUTIVA","evidencias":["DOC-1-A","DOC-2"],"analise_causal":{"fundamentos":["DOC-1-A","DOC-2"]},"vicio_construtivo":{"caracterizado":False},"constatacao":{"situacao":"ANOMALIA"},"consequencias":{}}
        resultado={"patologias":[pat],"catalogo_evidencias":evidencias,"questoes_saneadas":[],"cobertura_quesitos":[]}
        self.assertNotIn("ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA",{a["tipo"] for a in executar_detector(resultado)})
        self.assertNotIn("ORIGEM_ENDOGENA_SEM_EVIDENCIA_CONSTRUTIVA",{a["tipo"] for a in executar_deep_audit([],resultado)})

    def test_terceiros_trust_egress_e_update_local(self):
        self.assertEqual(politica_trust("nome-arbitrario",None)["review_status"],"UNREVIEWED")
        self.assertEqual(classificar_egress(["print('local')"]),"UNKNOWN")
        self.assertEqual(classificar_egress(["requests.get('https://example.com')"]),"YES")
        self.assertFalse(pode_receber_dados_privados("UNKNOWN",politica_trust("nome-arbitrario",None)))
        with tempfile.TemporaryDirectory() as td:
            raiz=Path(td);bare=raiz/"remote.git";repo=raiz/"repo";outro=raiz/"outro"
            subprocess.run(["git","init","--bare",str(bare)],check=True,capture_output=True)
            subprocess.run(["git","clone",str(bare),str(repo)],check=True,capture_output=True)
            for pasta in (repo,):
                subprocess.run(["git","-C",str(pasta),"config","user.email","test@example.invalid"],check=True);subprocess.run(["git","-C",str(pasta),"config","user.name","Teste"],check=True)
            (repo/"a.txt").write_text("a");subprocess.run(["git","-C",str(repo),"add","a.txt"],check=True);subprocess.run(["git","-C",str(repo),"commit","-m","a"],check=True,capture_output=True);subprocess.run(["git","-C",str(repo),"push","-u","origin","HEAD"],check=True,capture_output=True)
            self.assertEqual(next(x for x in verificar(raiz) if x["repo"]=="repo")["status"],"SEM_ATUALIZACAO_CONFIRMADA")
            subprocess.run(["git","clone",str(bare),str(outro)],check=True,capture_output=True);subprocess.run(["git","-C",str(outro),"config","user.email","test@example.invalid"],check=True);subprocess.run(["git","-C",str(outro),"config","user.name","Teste"],check=True);(outro/"b.txt").write_text("b");subprocess.run(["git","-C",str(outro),"add","b.txt"],check=True);subprocess.run(["git","-C",str(outro),"commit","-m","b"],check=True,capture_output=True);subprocess.run(["git","-C",str(outro),"push"],check=True,capture_output=True)
            self.assertEqual(next(x for x in verificar(raiz) if x["repo"]=="repo")["status"],"ATUALIZACAO_DISPONIVEL")


if __name__=="__main__":unittest.main()
