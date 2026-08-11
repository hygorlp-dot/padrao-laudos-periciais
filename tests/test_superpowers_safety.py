import json
import re
import subprocess
import unittest
from pathlib import Path

from scripts.terceiros.verificar_superpowers import verificar


ROOT = Path(__file__).resolve().parents[1]


def normalized(path):
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).casefold()


class SuperpowersIntegrationTest(unittest.TestCase):
    def test_manifest_pin_license_and_deny_defaults(self):
        manifest = json.loads((ROOT / "docs/terceiros/superpowers-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["upstream"], "obra/superpowers")
        self.assertEqual(manifest["version"], "v6.2.0")
        self.assertEqual(manifest["commit"], "3dcbd5c4b48e02263fbf4a3c01e3fe4f81d584d9")
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["telemetry_default"], "DISABLED")
        self.assertEqual(manifest["egress_default"], "DENY")
        self.assertEqual(len(manifest["skill_trees"]), 8)

    def test_upstream_trees_and_license_are_exact(self):
        self.assertEqual(verificar(), [])

    def test_selected_executables_have_no_network_egress(self):
        failures = [item for item in verificar() if item.startswith("EXECUTABLE_EGRESS")]
        self.assertEqual(failures, [])

    def test_only_selected_workflow_skills_are_integrated(self):
        selected = {
            "test-driven-development", "systematic-debugging",
            "verification-before-completion", "requesting-code-review",
            "receiving-code-review", "writing-plans", "executing-plans",
            "using-superpowers",
        }
        manifest = json.loads((ROOT / "docs/terceiros/superpowers-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["skill_trees"]), selected)
        self.assertFalse((ROOT / ".agents/skills/brainstorming").exists())

    def test_safety_skill_contains_all_domain_invariants(self):
        text = (ROOT / ".agents/skills/engenharia-seguranca-pericial/SKILL.md").read_text(encoding="utf-8")
        required = (
            "isolamento de evidências", "invariância por ordem",
            "evidência irrelevante", "remoção de evidência essencial",
            "gates recalculados independentemente", "valor + unidade",
            "egress deny-by-default", "aprovada por constante", "fail-closed",
            "alegação ≠ observação", "norma ≠ evidência física",
            "NÃO CONSTATADO ≠ INEXISTENTE",
        )
        for item in required:
            self.assertIn(item, text)

    def test_agents_requires_material_change_workflow(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        sequence = (
            "reprodução do bug", "teste falhando", "causa-raiz", "correção",
            "adversarial/property tests", "regressão", "revisão", "verificação final",
        )
        workflow = text[text.index("Cumprir e registrar nesta ordem:"):]
        positions = [workflow.index(item) for item in sequence]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("engenharia-seguranca-pericial", text)

    def test_first_party_rules_override_superpowers_without_trivial_bureaucracy(self):
        agents = normalized(ROOT / "AGENTS.md")
        wrapper = normalized(ROOT / ".agents/skills/engenharia-seguranca-pericial/SKILL.md")
        for text in (agents, wrapper):
            self.assertIn("AGENTS.md é canônico sobre `using-superpowers`".casefold(), text)
            self.assertIn("não tentar invocar Skills não vendorizadas".casefold(), text)
            self.assertIn("`brainstorming`", text)
            self.assertIn("proporcionalmente ao risco", text)
            self.assertIn("perguntas e operações triviais", text)

    def test_independent_review_and_external_fallback_are_explicit(self):
        agents = normalized(ROOT / "AGENTS.md")
        wrapper = normalized(ROOT / ".agents/skills/engenharia-seguranca-pericial/SKILL.md")
        for text in (agents, wrapper):
            self.assertIn("subagente independente quando disponível", text)
            self.assertIn("review package", text)
            self.assertIn("revisão externa do PR antes do merge".casefold(), text)
            self.assertIn("nunca declarar revisão independente concluída sem evidência", text)

    def test_telemetry_environment_is_disabled_and_private_data_is_untracked(self):
        policy = json.loads((ROOT / ".agents/superpowers-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["environment"]["SUPERPOWERS_DISABLE_TELEMETRY"], "true")
        self.assertEqual(policy["environment"]["DISABLE_TELEMETRY"], "true")
        self.assertFalse(policy["allow_external_egress"])
        if not (ROOT / ".git").exists():
            self.skipTest("árvore materializada sem metadados Git")
        tracked = subprocess.run(
            ["git", "ls-files", "referencias/privadas/*"], cwd=ROOT,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        self.assertEqual(tracked, "")


if __name__ == "__main__":
    unittest.main()
