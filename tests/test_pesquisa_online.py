import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from scripts.conhecimento_privado.pesquisa_online import pesquisar,dominio_oficial,buscar_seguro,reconciliar_fontes,extrair_sucessao,cache_valido,AgentSearchProvider,MockSearchProvider,EgressPolicy
from scripts.conhecimento_privado.verificar_vigencia import verificar
from scripts.motor_vicios.pipeline import executar_pipeline_motor
class Resposta:
    def read(self):return b"conteudo oficial ficticio"
class PesquisaOnlineTest(unittest.TestCase):
    def test_rejeita_dominio_nao_oficial(self):self.assertFalse(dominio_oficial("https://example.com/norma"))
    def test_cache_com_mock_e_vigencia_explicita(self):
        with tempfile.TemporaryDirectory() as td:
            meta=pesquisar("https://www.gov.br/exemplo",Path(td),lambda *a,**k:Resposta(),EgressPolicy(permitir_egress=True))
            self.assertTrue((Path(td)/(meta["sha256"]+".bin")).exists());self.assertEqual(verificar(meta)["status_vigencia"],"PENDENTE_VERIFICACAO")
    def test_busca_classifica_oficial_e_secundaria(self):
        class P:
            EGRESS_CAPABILITY="LOCAL_NO_EGRESS"
            def buscar(self,q):return [{"id":"F1","url":"https://www.gov.br/ato"},{"id":"F2","url":"https://blog.example/ato"}]
        r=buscar_seguro("ato",P(),EgressPolicy(permitir_egress=True));self.assertEqual(r["status"],"CONCLUIDA");self.assertTrue(r["resultados"][0]["oficial"]);self.assertEqual(r["resultados"][1]["status_uso"],"APENAS_DESCOBERTA")
    def test_contradicao_revogada_e_sucessora(self):
        r=reconciliar_fontes([{"id":"F1","url":"https://www.gov.br/a","status_vigencia":"REVOGADA","oficial":True},{"id":"F2","url":"https://www.gov.br/b","status_vigencia":"VIGENTE","oficial":True}])
        self.assertTrue(r["conflito"]);self.assertEqual(extrair_sucessao("Revoga Resolução 123/2020","F2")["alvo_textual"],"123/2020")
    def test_timeout_sem_rede_e_erros_http(self):
        for erro,status in ((TimeoutError(),"TIMEOUT"),(OSError(),"SEARCH_PROVIDER_INDISPONIVEL"),(RuntimeError("HTTP 404"),"ERRO_PROVIDER"),(RuntimeError("HTTP 500"),"ERRO_PROVIDER")):
            class P:
                EGRESS_CAPABILITY="LOCAL_NO_EGRESS"
                def buscar(self,q,e=erro):raise e
            self.assertEqual(buscar_seguro("consulta",P(),EgressPolicy(permitir_egress=True))["status"],status)
    def test_cache_valido_e_expirado(self):
        agora=datetime.now(timezone.utc);self.assertTrue(cache_valido({"acessado_em":agora.isoformat()},agora));self.assertFalse(cache_valido({"acessado_em":(agora-timedelta(days=2)).isoformat()},agora))
    def test_providers_mock_e_agente(self):
        mock=MockSearchProvider([{"url":"https://www.gov.br/fonte"}]);self.assertEqual(buscar_seguro("fonte pública",mock,EgressPolicy(permitir_egress=True))["status"],"CONCLUIDA")
        agente=AgentSearchProvider(lambda q:[{"url":"https://www.dnit.gov.br/manual","query":q}]);self.assertTrue(agente.EXTERNAL_DATA_EGRESS_REQUIRED)
        with self.assertRaises(PermissionError): agente.buscar("manual público")
        self.assertEqual(agente.buscar("manual público",EgressPolicy(permitir_egress=True))[0]["query"],"manual público")
    def test_mock_integrado_ao_fluxo_do_motor(self):
        raiz=Path(__file__).resolve().parents[1];load=lambda p:json.loads((raiz/p).read_text(encoding="utf-8"));processo=load("tests/fixtures/schemas/processo-valido.json");delim=load("tests/fixtures/triagem/delimitacao-minima-valida.json");plano=load("tests/fixtures/planejamento/plano-vistoria-valido.json");vistoria=load("tests/fixtures/schemas/vistoria-valida.json")
        r=executar_pipeline_motor(processo,delim,plano,vistoria,{"search_provider":MockSearchProvider([{"url":"https://www.gov.br/fonte"}])});self.assertEqual(r["analise_inicial"]["pesquisa_online"]["status"],"CONCLUIDA");self.assertEqual(r["analise_inicial"]["pesquisa_online"]["fontes_oficiais_localizadas"],["https://www.gov.br/fonte"])
