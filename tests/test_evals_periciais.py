import json,unittest
from pathlib import Path
from scripts.auditoria_pericial import auditar_claim
from scripts.auditoria_pericial.executar_evals import executar
RAIZ=Path(__file__).resolve().parents[1]
class EvalsPericiaisTest(unittest.TestCase):
    def test_runner_executa_todos_os_evals(self):
        resultados=executar(RAIZ/"evals/pericial");self.assertEqual(len(resultados),3);self.assertTrue(all(r["aprovado"] for r in resultados))
    def test_evals_possuem_contrato_de_propriedades(self):
        arquivos=sorted((RAIZ/"evals/pericial").glob("*.json"));self.assertEqual(len(arquivos),3)
        for caminho in arquivos:
            with self.subTest(eval=caminho.name):
                e=json.loads(caminho.read_text(encoding="utf-8"));self.assertTrue(e["input"]);self.assertTrue(e["assertions"]);self.assertTrue(e["expected_properties"]);self.assertTrue(e["prohibited_behaviors"]);self.assertIn(e["severity"],{"CRITICO","IMPORTANTE","EDITORIAL"})
    def test_runner_nao_depende_do_id_do_cenario(self):
        caso=json.loads((RAIZ/"evals/pericial/recalque-insuficiente.json").read_text(encoding="utf-8"));caso["id"]="EVAL-RENOMEADO"
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            Path(pasta,"caso.json").write_text(json.dumps(caso),encoding="utf-8");resultado=executar(Path(pasta))[0]
        self.assertTrue(resultado["aprovado"]);self.assertEqual(resultado["obtido"]["veredito"],"INSUFFICIENT")
    def test_eval_recalque_executa_grounding_insuficiente(self):
        claim={"id":"CLM-001","tipo":"CAUSA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"Recalque diferencial","aspectos_requeridos":["MECANISMO","CAUSA"]}
        evidencia={"id":"OBS-001","tipo":"OBSERVACAO","proveniencia":["ARQ-VIS-001"],"aspectos_suportados":["MECANISMO"]}
        self.assertEqual(auditar_claim(claim,[evidencia],[evidencia])["veredito"],"INSUFFICIENT")
    def test_eval_normativo_executa_estado_nao_verificavel(self):
        claim={"id":"CLM-002","tipo":"CONFORMIDADE_NORMATIVA","natureza":"INTERPRETIVE","saliencia":"LOAD_BEARING","texto":"Item fictício"}
        fonte={"id":"NOR-001","tipo":"NORMA","proveniencia":["fonte"],"acessivel":False}
        self.assertEqual(auditar_claim(claim,[fonte],[fonte])["veredito"],"UNVERIFIABLE")
if __name__=="__main__":unittest.main()
