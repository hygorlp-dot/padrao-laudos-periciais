import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.conhecimento_privado.inventariar import inventariar
from scripts.planejamento_pericial.gerar_plano import _perfil
from scripts.planejamento_pericial.gerar_processo import _campos_alegacao
from scripts.planejamento_pericial.validar_plano import validar


RAIZ = Path(__file__).resolve().parents[1]


class PlanejamentoPericialTest(unittest.TestCase):
    def test_manifestacao_e_causa_alegadas_sao_separadas(self):
        manifestacao,causa=_campos_alegacao("A autora relata infiltração decorrente de falha na impermeabilização.")
        self.assertEqual(manifestacao,"infiltração")
        self.assertEqual(causa,"falha na impermeabilização")

    def test_extracao_nao_possui_limites_artificiais(self):
        processo=(RAIZ/"scripts/planejamento_pericial/gerar_processo.py").read_text(encoding="utf-8")
        plano=(RAIZ/"scripts/planejamento_pericial/gerar_plano.py").read_text(encoding="utf-8")
        self.assertNotIn("len(alegacoes) >= 80",processo)
        self.assertNotIn("algs[:30]",plano)
    def test_plano_ficticio_valida_e_cobre_quesito(self):
        self.assertEqual(validar(RAIZ / "tests/fixtures/planejamento/plano-vistoria-valido.json"), [])

    def test_perfis_nao_contaminam_tipos(self):
        avaliacao = json.dumps(_perfil("AVALIACAO_IMOBILIARIA"), ensure_ascii=False).lower()
        rodovia = json.dumps(_perfil("ENGENHARIA_RODOVIARIA"), ensure_ascii=False).lower()
        vicios = json.dumps(_perfil("VICIOS_CONSTRUTIVOS"), ensure_ascii=False).lower()
        self.assertNotIn("patologia", avaliacao)
        self.assertNotIn("residencial", rodovia)
        self.assertIn("manifestação", vicios)
        self.assertIn("valor", avaliacao)
        self.assertIn("rodovia", rodovia)

    def test_inventario_docm_incremental_sem_catalogo_manual(self):
        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            destino = raiz / "modelos-referenciais/outros/modelo.docm"
            destino.parent.mkdir(parents=True)
            with zipfile.ZipFile(destino, "w") as pacote:
                pacote.writestr("word/document.xml", '<w:document xmlns:w="x"><w:t>Laudo fictício de avaliação com valor de mercado.</w:t></w:document>')
            primeiro = inventariar(raiz)
            segundo = inventariar(raiz)
            self.assertEqual(primeiro["arquivos"][0]["id"], segundo["arquivos"][0]["id"])
            self.assertEqual(segundo["arquivos"][0]["acao_processamento"], "REUTILIZADO")
            self.assertEqual(segundo["arquivos"][0]["situacao_extracao"], "TEXTO_INSUFICIENTE")
            derivado = json.loads((raiz / "conhecimento/modelos/MOD-0001.json").read_text(encoding="utf-8"))
            self.assertIn("conclusões", derivado["elementos_proibidos_como_regra"])

    def test_dezessete_cenarios_sinteticos_documentados(self):
        cenarios = json.loads((RAIZ / "tests/fixtures/planejamento-cenarios.json").read_text(encoding="utf-8"))["cenarios"]
        self.assertEqual(len(cenarios), 17)
        self.assertEqual(len({c["id"] for c in cenarios}), 17)


if __name__ == "__main__": unittest.main()
