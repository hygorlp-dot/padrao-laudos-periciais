import copy
import json
import unittest
from pathlib import Path

from scripts.triagem_pericial.validar_delimitacao import validar_arquivo, validar_relacoes
from scripts.triagem_pericial.classificar_tipo import classificar


RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = RAIZ / "tests" / "fixtures" / "triagem"


def _fixture_valida():
    return json.loads((FIXTURES / "delimitacao-minima-valida.json").read_text(encoding="utf-8"))


class DelimitacaoPericialTest(unittest.TestCase):
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
