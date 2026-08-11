import json
import unittest
from pathlib import Path

from scripts.terceiros.verificar_design_motion import verificar

RAIZ = Path(__file__).resolve().parents[1]


class GovernancaDesenvolvimentoTest(unittest.TestCase):
    def test_bridges_apontam_para_fontes_canonicas(self):
        for nome in ("CODEX.md", "CLAUDE.md", "GEMINI.md", "CURSOR.md", "WINDSURF.md"):
            texto = (RAIZ / nome).read_text(encoding="utf-8")
            self.assertIn("AGENTS.md", texto)
            self.assertIn("padrao-governanca-desenvolvimento.md", texto)

    def test_templates_e_politica_presentes(self):
        esperados = (
            ".github/ISSUE_TEMPLATE/bug.yml",
            ".github/ISSUE_TEMPLATE/improvement.yml",
            ".github/ISSUE_TEMPLATE/feature.yml",
            ".github/ISSUE_TEMPLATE/config.yml",
            ".github/PULL_REQUEST_TEMPLATE.md",
        )
        self.assertTrue(all((RAIZ / p).is_file() for p in esperados))
        agentes = (RAIZ / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Não implementar", agentes)
        self.assertIn("design-motion-principles", agentes)

    def test_manifesto_third_party_e_integridade(self):
        dados = json.loads((RAIZ / "docs/terceiros/design-motion-principles-blobs.json").read_text(encoding="utf-8"))
        self.assertEqual(dados["commit"], "4a9ca879f24a361f4dca4174fe2da0f67b5ddee3")
        self.assertEqual(dados["license"], "MIT")
        self.assertEqual(len(dados["blobs"]), 16)
        self.assertEqual(verificar(), [])

    def test_wrapper_ui_pericial(self):
        texto = (RAIZ / ".agents/skills/ui-pericial/SKILL.md").read_text(encoding="utf-8")
        for termo in ("PRODUCTIVITY_TOOL", "Emil", "Jakub", "Jhey", "prefers-reduced-motion", "PROGRESS"):
            self.assertIn(termo, texto)


if __name__ == "__main__":
    unittest.main()
