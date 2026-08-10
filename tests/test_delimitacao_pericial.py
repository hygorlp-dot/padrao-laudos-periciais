import copy
import json
import unittest
from pathlib import Path

from scripts.triagem_pericial.validar_delimitacao import validar_arquivo, validar_relacoes
from scripts.triagem_pericial.classificar_tipo import classificar
from scripts.triagem_pericial.extrair_quesitos import extrair
from scripts.triagem_pericial.semantica import melhores
from scripts.triagem_pericial.gerar_delimitacao import _tema_dos_autos


RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures" / "triagem"


def _fixture_valida():
    return json.loads((FIXTURES / "delimitacao-minima-valida.json").read_text(encoding="utf-8"))


class DelimitacaoPericialTest(unittest.TestCase):
  def test_adv_final_08_decisao_curta_prevalece_sobre_peticao_longa(self):
    docs=[{"documento_id":"DOC-PJE-001","classe_normalizada":"DECISAO","paginas":[{"texto_bruto":"Perícia para avaliar estabilidade das fissuras.","referencia":{"pagina_pdf":1}}]},{"documento_id":"DOC-PJE-002","classe_normalizada":"PETICAO_INICIAL","paginas":[{"texto_bruto":"A parte discorre extensamente sobre umidade, pintura, cerâmica, portas, cobertura, infiltração, impermeabilização e desplacamentos. Requer verificar todos esses itens por perícia técnica.","referencia":{"pagina_pdf":2}}]}]
    tema,fonte=_tema_dos_autos(docs,"fallback");self.assertEqual(fonte["documento_id"],"DOC-PJE-001");self.assertIn("fissura",tema.lower());self.assertNotIn("umidade",tema.lower())
  def test_tres_processos_mesmo_tipo_produzem_temas_especificos(self):
    temas=[]
    for i,texto in enumerate(("Determinar fissuras e suas causas na parede.","Verificar infiltração e umidade na cobertura.","Verificar desplacamentos e suas causas no revestimento."),1):
      doc={"documento_id":f"DOC-PJE-{i:03d}","classe_normalizada":"DECISAO","paginas":[{"texto_bruto":texto,"referencia":{"pagina_pdf":1}}]}
      temas.append(_tema_dos_autos([doc],"fallback")[0])
    self.assertEqual(len(set(temas)),3);self.assertNotIn("fallback",temas)
  def test_vinculo_semantico_nao_e_round_robin(self):
    qts=[{"id":"QT-001","descricao":"medir fissura na parede"},{"id":"QT-002","descricao":"verificar infiltração na cobertura"}]
    self.assertEqual(melhores("Qual a extensão da infiltração no telhado?",qts),["QT-002"])

  def test_quesito_claro_em_contestacao_e_extraido(self):
    prov={"arquivo":"ficticio.pdf","sha256":"0"*64,"documento_id":"DOC-PJE-001","id_pje":"1","pagina_pdf":1,"pagina_documento":1,"pagina_original":None,"trecho":"x","natureza":"DOCUMENTADO","metodo_extracao":"TEXTO_DIGITAL","confianca":{"nivel":"ALTA"},"status_verificacao":"VERIFICADO"}
    texto="QUESITOS:\n1. Informe se existe infiltração na cobertura?"
    doc={"documento_id":"DOC-PJE-001","id_pje":"1","titulo_original":"Contestação","classe_normalizada":"CONTESTACAO","paginas":[{"texto_bruto":texto,"referencia":{"pagina_pdf":1,"pagina_documento":1,"pagina_original":None}}],"blocos_texto":[{"pagina":{"pagina_pdf":1},"proveniencia":prov}]}
    self.assertEqual(len(extrair([doc])),1)
  def test_classificador_distingue_familias_sem_identificador_de_processo(self):
    def doc(texto, classe="DECISAO", numero=1):
      return {"documento_id": f"DOC-PJE-{numero:03d}", "classe_normalizada": classe,
              "paginas": [{"texto_bruto": texto}]}
    casos = [
      ("VICIOS_CONSTRUTIVOS", "Perícia sobre vício construtivo, infiltração e fissura no imóvel adquirido."),
      ("AVALIACAO_IMOBILIARIA", "Apurar o valor de mercado e valor do aluguel pelo método comparativo de dados de mercado."),
      ("ENGENHARIA_RODOVIARIA", "Engenharia rodoviária: condições da rodovia federal, acostamento e sinalização da rodovia."),
    ]
    for esperado, texto in casos:
      with self.subTest(esperado=esperado):
        self.assertEqual(classificar([doc(texto)]).tipo, esperado)

  def test_fixture_minima_atende_schema_e_relacoes(self):
    self.assertEqual(validar_arquivo(FIXTURES / "delimitacao-minima-valida.json"), [])

  def test_cenarios_obrigatorios_estao_documentados(self):
    cenarios = {item["id"] for item in json.loads((FIXTURES / "cenarios.json").read_text(encoding="utf-8"))["cenarios"]}
    self.assertEqual(cenarios, {
        "vicios_construtivos", "avaliacao_imobiliaria", "engenharia_rodoviaria",
        "tipo_hibrido", "tipo_outro", "decisao_delimitadora", "ausencia_decisao_clara",
        "quesito_tecnico", "quesito_parcialmente_juridico", "quesito_juridico",
        "quesito_repetitivo", "ressalva_documental", "ressalva_temporal",
        "conflito_resolvivel", "conflito_bloqueante", "nao_constatado_nao_inexistente",
        "tema_insuficiente",
    })

  def test_apto_nao_admite_conflito_bloqueante_aberto(self):
    dado = _fixture_valida()
    dado["conflitos"] = [{
        "id": "CNF-001", "tipo": "delimitação", "descricao": "Conflito fictício",
        "fontes": [dado["proveniencia"][0], dado["proveniencia"][0]],
        "classificacao": "BLOQUEANTE", "resolucao": None, "status": "ABERTO",
    }]
    self.assertTrue(any("conflitos bloqueantes" in erro for erro in validar_relacoes(dado)))


  def test_apto_exige_cobertura_de_todos_os_quesitos(self):
    dado = _fixture_valida()
    quesito = {
        "id": "QUE-001", "origem": "JUIZO", "documento_id": "DOC-PJE-001",
        "id_pje": "900001", "numero_original": "1", "caminho_original": "1",
        "ordem_real": 1, "texto_integral": "Quesito fictício?", "subitens": [],
        "paginas": [{"pagina_pdf": 3, "pagina_documento": 1, "pagina_original": None}],
        "pertinencia": "PERTINENTE_TECNICO", "questoes_tecnicas_relacionadas": ["QT-001"],
        "evidencias_necessarias": [], "ressalvas_aplicaveis": [],
        "status_cobertura": "SEM_TRATAMENTO", "materia_tecnica": "Condição fictícia",
        "materia_juridica_associada": None, "secoes_laudisticas_previstas": [],
        "proveniencia": [copy.deepcopy(dado["proveniencia"][0])],
    }
    dado["quesitos"] = [quesito]
    erros = validar_relacoes(dado)
    self.assertTrue(any("ausentes da matriz" in erro for erro in erros))
    self.assertTrue(any("SEM_TRATAMENTO" in erro for erro in erros))


if __name__ == "__main__":
    unittest.main()
