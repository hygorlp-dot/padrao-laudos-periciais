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

    def test_frontend_stack_preserva_precedencia_first_party(self):
        agentes = (RAIZ / "AGENTS.md").read_text(encoding="utf-8")
        required = (
            ".agents/skills/ui-pericial/SKILL.md",
            ".agents/skills/frontend-design/SKILL.md",
            ".agents/skills/design-motion-principles/SKILL.md",
        )
        for path in required:
            self.assertIn(path, agentes)
        self.assertIn("first-party", agentes)
        self.assertIn("NO_DOMAIN_LOGIC_IN_UI", agentes)
        self.assertNotIn("net-new", agentes)
        positions = [agentes.index(path) for path in required]
        self.assertEqual(positions, sorted(positions))

    def test_roteamento_ui_transitivo_repete_a_ordem_canonica(self):
        wrapper = (RAIZ / ".agents/skills/ui-pericial/SKILL.md").read_text(encoding="utf-8")
        governance = (RAIZ / "docs/padroes/padrao-governanca-desenvolvimento.md").read_text(encoding="utf-8")
        self.assertLess(wrapper.index("frontend-design"), wrapper.index("design-motion-principles"))
        self.assertLess(governance.index("ui-pericial"), governance.index("frontend-design"))
        self.assertLess(governance.index("frontend-design"), governance.index("design-motion-principles"))

    def test_catalogos_externos_sao_discovery_sem_autorizacao(self):
        python_policy = (RAIZ / "docs/padroes/catalogo-externo-python.md").read_text(encoding="utf-8")
        api_policy = (RAIZ / "docs/padroes/catalogo-externo-apis.md").read_text(encoding="utf-8")
        for value in (
            "6ff59a63c6db5f23ec808381994050bbf324801d",
            "AWESOME_PYTHON_ENTRY != ADOPT",
            "CATALOG_DISCOVERY != DEPENDENCY_APPROVAL",
            "POPULAR != NECESSARY",
        ):
            self.assertIn(value, python_policy)
        for value in (
            "c045a2eb505f0f8b7992bb4af53cc020f25003fd",
            "PUBLIC_APIS_ENTRY != APPROVED_INTEGRATION",
            "PUBLIC_APIS_ENTRY != AUTHORITATIVE_SOURCE",
            "CATALOG_DISCOVERY != PROVIDER_VALIDATION",
            "NO_AUTH != PRIVACY_SAFE",
        ):
            self.assertIn(value, api_policy)

    def test_matriz_roadmap_classifica_skills_sem_antecipar_frontend(self):
        matrix = (RAIZ / "docs/padroes/matriz-skills-roadmap.md").read_text(encoding="utf-8")
        for phase in (
            "APPLICATION_LAYER_V1",
            "LOCAL_API_V1",
            "FRONTEND_SHELL_V1",
            "PROCESS_CASE_UI",
            "VISTORIA_UI",
            "EVIDENCE_UI",
            "TECHNICAL_FINDINGS_UI",
            "LAUDO_UI",
            "BUDGET_UI",
            "AI_GATEWAY",
        ):
            self.assertIn(phase, matrix)
        for category in ("REQUIRED", "RECOMMENDED", "CONDITIONAL", "NOT_APPLICABLE"):
            self.assertIn(category, matrix)
        application = matrix[matrix.index("## APPLICATION_LAYER_V1"):matrix.index("## LOCAL_API_V1")]
        self.assertIn("frontend-design", application)
        self.assertIn("NOT_APPLICABLE", application)

    def test_matriz_ui_preserva_gates_globais_obrigatorios(self):
        matrix = (RAIZ / "docs/padroes/matriz-skills-roadmap.md").read_text(encoding="utf-8")
        phases = ("PROCESS_CASE_UI","VISTORIA_UI","EVIDENCE_UI","TECHNICAL_FINDINGS_UI","LAUDO_UI","BUDGET_UI","AI_GATEWAY")
        required = ("verification-before-completion","repository-safety-gate","requesting-code-review","receiving-code-review")
        for phase,next_phase in zip(phases,phases[1:]):
            section=matrix[matrix.index(f"## {phase}"):matrix.index(f"## {next_phase}")]
            for skill in required:self.assertIn(skill,section,f"{phase} sem {skill}")


if __name__ == "__main__":
    unittest.main()
